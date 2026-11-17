"""Telegram webhook transport, self-authenticating route, and settings contract tests."""

from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from aj_crew import webhooks
from aj_crew.config.loader import CRED_TELEGRAM_WEBHOOK_SECRET, AjCrewConfig
from aj_crew.dashboard.handlers import messaging as msg_handlers
from aj_crew.dashboard.token_auth import (
    TELEGRAM_WEBHOOK_PATH,
    is_csrf_exempt,
    token_auth_middleware,
)
from aj_crew.telegram import gateway as tg_gateway
from aj_crew.telegram.client import (
    TELEGRAM_MAX_WEBHOOK_BYTES,
    TELEGRAM_SECRET_HEADER,
    delete_telegram_webhook,
    record_webhook_update_id,
    set_telegram_webhook,
    validate_webhook_secret,
    validate_webhook_url,
    verify_telegram_webhook_secret,
)

VALID_SECRET = "tg_webhook_secret_0123456789abcdef"
VALID_URL = "https://bot.example.com/api/messaging/telegram/webhook"


class _FakeContent:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def iter_chunked(self, n: int):
        for i in range(0, len(self._data), n):
            yield self._data[i : i + n]


class _FakeWebhookRequest(dict):
    def __init__(
        self,
        *,
        app: dict[str, Any],
        body: bytes = b'{"update_id": 101, "message": {"text": "hi"}}',
        headers: dict[str, str] | None = None,
        remote: str = "149.154.167.200",
        content_length: int | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.method = "POST"
        self.path = TELEGRAM_WEBHOOK_PATH
        self.remote = remote
        self.headers = headers or {}
        self.content = _FakeContent(body)
        self.content_length = len(body) if content_length is None else content_length
        self.charset: str | None = None
        self.can_read_body = bool(self.content_length)
        self.content_type = "application/json"


class TestWebhookValidationAndAuth:
    def test_validate_webhook_url_enforces_clean_https(self) -> None:
        assert validate_webhook_url(VALID_URL) is None
        assert validate_webhook_url("") is not None
        assert validate_webhook_url("http://bot.example.com/hook") is not None
        assert validate_webhook_url("https://user:pass@bot.example.com/hook") is not None
        assert validate_webhook_url("https://bot.example.com/hook#frag") is not None
        assert validate_webhook_url("https://bot.example.com/has space") is not None

    def test_validate_and_verify_webhook_secret_fail_closed(self) -> None:
        assert validate_webhook_secret(VALID_SECRET) is None
        assert validate_webhook_secret("short_secret") is not None
        assert validate_webhook_secret("bad$char$in$secret$token") is not None
        assert validate_webhook_secret("a" * 257) is not None

        assert verify_telegram_webhook_secret(VALID_SECRET, VALID_SECRET) is True
        assert verify_telegram_webhook_secret(None, VALID_SECRET) is False
        assert verify_telegram_webhook_secret("", VALID_SECRET) is False
        assert verify_telegram_webhook_secret("wrong_secret_value_1234", VALID_SECRET) is False
        # Fail closed when expected secret is missing or below minimum length.
        assert verify_telegram_webhook_secret(VALID_SECRET, "") is False
        assert verify_telegram_webhook_secret("short", "short") is False

    def test_replay_deduplication_is_bounded(self) -> None:
        seen: OrderedDict[int, None] = OrderedDict()
        assert record_webhook_update_id(seen, 0, cap=3) is False
        assert record_webhook_update_id(seen, 10, cap=3) is True
        assert record_webhook_update_id(seen, 10, cap=3) is False
        assert record_webhook_update_id(seen, 11, cap=3) is True
        assert record_webhook_update_id(seen, 12, cap=3) is True
        assert record_webhook_update_id(seen, 13, cap=3) is True
        # 10 was evicted when 13 arrived under cap=3; 11..13 remain.
        assert list(seen.keys()) == [11, 12, 13]
        assert record_webhook_update_id(seen, 12, cap=3) is False

    @pytest.mark.asyncio
    async def test_set_and_delete_webhook_client_calls(self) -> None:
        fake_client = SimpleNamespace(_call_raw=AsyncMock(return_value={"ok": True}))
        assert (
            await set_telegram_webhook(
                fake_client,  # type: ignore[arg-type]
                url=VALID_URL,
                secret_token=VALID_SECRET,
            )
            is True
        )
        fake_client._call_raw.assert_awaited_once_with(
            "setWebhook",
            {
                "url": VALID_URL,
                "secret_token": VALID_SECRET,
                "allowed_updates": ["message", "callback_query"],
            },
        )

        fake_client._call_raw.reset_mock()
        assert await delete_telegram_webhook(fake_client, drop_pending_updates=True) is True  # type: ignore[arg-type]
        fake_client._call_raw.assert_awaited_once_with(
            "deleteWebhook", {"drop_pending_updates": True}
        )

        with pytest.raises(ValueError, match="https://"):
            await set_telegram_webhook(
                fake_client,  # type: ignore[arg-type]
                url="http://insecure.example.com/hook",
                secret_token=VALID_SECRET,
            )


class TestWebhookMiddlewareAndRoute:
    def test_route_is_post_only_bypass_and_csrf_exempt(self) -> None:
        assert is_csrf_exempt(TELEGRAM_WEBHOOK_PATH, "POST") is True
        for method in ("GET", "PUT", "DELETE", "PATCH"):
            assert is_csrf_exempt(TELEGRAM_WEBHOOK_PATH, method) is False

    @pytest.mark.asyncio
    async def test_token_auth_allows_post_only_for_telegram_webhook(self) -> None:
        mw = token_auth_middleware()

        async def reached(_req: Any) -> web.Response:
            return web.Response(text="reached")

        for method, expected in (("POST", 200), ("GET", 403), ("PUT", 403)):
            req = MagicMock(spec=web.Request)
            req.path = TELEGRAM_WEBHOOK_PATH
            req.method = method
            req.query = {}
            req.cookies = {}
            req.headers = {}
            req.remote = "149.154.167.200"
            resp = await mw(req, reached)
            assert (resp.status == 200) is (expected == 200)

    @pytest.mark.asyncio
    async def test_webhook_route_authenticates_deduplicates_and_caps_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(msg_handlers, "_sel", lambda: MagicMock())
        webhooks._reset_auth_throttle()

        dispatched: list[dict[str, Any]] = []
        seen: OrderedDict[int, None] = OrderedDict()

        def handle_update(update: dict[str, Any]) -> bool:
            if not record_webhook_update_id(seen, int(update["update_id"])):
                return False
            dispatched.append(update)
            return True

        transport = SimpleNamespace(
            _webhook_mode=True,
            _webhook_secret=VALID_SECRET,
            client=SimpleNamespace(_closed=False),
            handle_webhook_update=handle_update,
        )
        state = SimpleNamespace(channel_transports={"telegram": transport})
        app = {"state": state}

        # 1. Missing or wrong secret -> 401 before touching payload
        resp_unauth = await msg_handlers.api_telegram_webhook(_FakeWebhookRequest(app=app))  # type: ignore[arg-type]
        assert resp_unauth.status == 401
        assert dispatched == []

        resp_wrong = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(
                app=app,
                headers={TELEGRAM_SECRET_HEADER: "wrong_secret_token_value"},
            )  # type: ignore[arg-type]
        )
        assert resp_wrong.status == 401
        assert dispatched == []

        # 2. Valid secret -> 200 and dispatches once; replay -> duplicate=True
        good_headers = {TELEGRAM_SECRET_HEADER: VALID_SECRET}
        resp_ok = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(app=app, headers=good_headers)  # type: ignore[arg-type]
        )
        assert resp_ok.status == 200
        assert len(dispatched) == 1
        assert b'"duplicate": false' in resp_ok.body

        resp_dup = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(app=app, headers=good_headers)  # type: ignore[arg-type]
        )
        assert resp_dup.status == 200
        assert len(dispatched) == 1
        assert b'"duplicate": true' in resp_dup.body

        # 3. Malformed JSON or missing update_id -> 400; oversize -> 413
        resp_bad_json = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(app=app, headers=good_headers, body=b"{bad")  # type: ignore[arg-type]
        )
        assert resp_bad_json.status == 400

        resp_no_uid = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(app=app, headers=good_headers, body=b'{"message": {}}')  # type: ignore[arg-type]
        )
        assert resp_no_uid.status == 400

        resp_huge = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(
                app=app,
                headers=good_headers,
                body=b"{}",
                content_length=TELEGRAM_MAX_WEBHOOK_BYTES + 1,
            )  # type: ignore[arg-type]
        )
        assert resp_huge.status == 413

        # 4. Disabled or closed client -> 503
        transport._webhook_mode = False
        resp_disabled = await msg_handlers.api_telegram_webhook(
            _FakeWebhookRequest(app=app, headers=good_headers)  # type: ignore[arg-type]
        )
        assert resp_disabled.status == 503


class TestTelegramGatewayWebhookStartup:
    @pytest.mark.asyncio
    async def test_webhook_mode_skips_polling_and_registers_set_webhook(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatched: list[dict[str, Any]] = []
        connect_calls = 0
        set_wh_calls: list[tuple[str, str]] = []

        class FakeClient:
            def __init__(self, *, token: str, on_callback: Any) -> None:
                self.token = token
                self.on_callback = on_callback
                self.on_close: Any = None
                self.on_status: Any = None
                self._last_status: Any = None
                self._closed = False

            def set_message_handler(self, _h: Any) -> None:
                return None

            async def get_me(self) -> dict[str, Any]:
                return {"username": "ajcrew_bot", "id": 77}

            async def set_my_commands(self, _cmds: Any) -> bool:
                return True

            def _dispatch(self, update: dict[str, Any]) -> None:
                dispatched.append(update)

            async def close(self) -> None:
                self._closed = True
                if self.on_close:
                    self.on_close()

        class FakeTransport:
            def __init__(self, client: Any, **_kw: Any) -> None:
                self.client = client

            async def receive(self, _u: Any) -> None:
                return None

            async def connect(self) -> None:
                nonlocal connect_calls
                connect_calls += 1

        class FakeDispatcher:
            def __init__(self, **_kw: Any) -> None:
                self.client: Any = None
                self.transport: Any = None
                self.bot_username = ""
                self.bot_id = 0

            async def on_callback(self, *_a: Any) -> None:
                return None

            async def handle_message(self, *_a: Any) -> None:
                return None

            async def deliver_spawn_approval(self, *_a: Any) -> None:
                return None

            async def _drain_queue(self, *_a: Any) -> None:
                return None

        async def fake_set_webhook(_client: Any, *, url: str, secret_token: str) -> bool:
            set_wh_calls.append((url, secret_token))
            return True

        monkeypatch.setattr(tg_gateway, "TelegramClient", FakeClient)
        monkeypatch.setattr(tg_gateway, "TelegramTransport", FakeTransport)
        monkeypatch.setattr(tg_gateway, "TelegramDispatcher", FakeDispatcher)
        monkeypatch.setattr(tg_gateway, "set_telegram_webhook", fake_set_webhook)
        monkeypatch.setattr(tg_gateway, "register_channel_delivery", lambda *_a: None)
        monkeypatch.setattr(tg_gateway, "unregister_channel_delivery", lambda *_a: None)
        monkeypatch.setattr(tg_gateway, "unregister_drain", lambda *_a: None)

        state = SimpleNamespace(
            channel_transports={},
            telegram_connected=False,
            telegram_connect_error="",
            register_channel_transport=lambda t: state.channel_transports.__setitem__(
                "telegram", t
            ),
        )
        cfg = AjCrewConfig()
        cfg.telegram.mode = "webhook"
        cfg.telegram.webhook_url = VALID_URL
        orch = SimpleNamespace(
            _telegram_enabled=True,
            _telegram_bot_token="123456:ABCDEF_valid_looking_token",
            _telegram_allowed_user_ids=[42],
            _telegram_webhook_secret=VALID_SECRET,
            _cfg=cfg,
            sessions=object(),
            ctx_builder=object(),
            dashboard_state=state,
        )

        client = await tg_gateway.maybe_start_telegram(orch)  # type: ignore[arg-type]
        assert client is not None
        assert connect_calls == 0
        assert set_wh_calls == [(VALID_URL, VALID_SECRET)]
        assert state.telegram_connected is True

        reg_transport = state.channel_transports["telegram"]
        assert reg_transport.handle_webhook_update({"update_id": 500, "message": {}}) is True
        assert reg_transport.handle_webhook_update({"update_id": 500, "message": {}}) is False
        assert len(dispatched) == 1

        await client.close()
        assert getattr(reg_transport, "_webhook_mode") is False
        assert getattr(reg_transport, "_webhook_secret") == ""

    @pytest.mark.asyncio
    async def test_webhook_mode_without_secret_fails_closed(self) -> None:
        state = SimpleNamespace(
            telegram_connected=True,
            telegram_connect_error="",
            register_channel_transport=lambda _t: None,
        )
        cfg = AjCrewConfig()
        cfg.telegram.mode = "webhook"
        cfg.telegram.webhook_url = VALID_URL
        cfg.load_credentials = lambda **_kw: {CRED_TELEGRAM_WEBHOOK_SECRET: ""}  # type: ignore[method-assign]
        orch = SimpleNamespace(
            _telegram_enabled=True,
            _telegram_bot_token="123456:ABCDEF_valid_looking_token",
            _telegram_allowed_user_ids=[42],
            _cfg=cfg,
            sessions=object(),
            ctx_builder=object(),
            dashboard_state=state,
        )
        assert await tg_gateway.maybe_start_telegram(orch) is None  # type: ignore[arg-type]
        assert state.telegram_connected is False
        assert "webhook_secret" in state.telegram_connect_error
