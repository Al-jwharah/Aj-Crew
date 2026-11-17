"""Self-authenticating Telegram Bot API webhook route: ``POST /api/messaging/telegram/webhook``.

Composed onto :mod:`aj_crew.dashboard.handlers.messaging` via ``_facade_compose``.
Authenticates ``X-Telegram-Bot-Api-Secret-Token`` in constant time (:func:`hmac.compare_digest`)
BEFORE reading or parsing the request body, enforces a bounded JSON payload size,
deduplicates ``update_id`` replays, and dispatches into the active Telegram transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from aj_crew.dashboard.handlers.messaging import (
        DashboardState,
        _sel,
        is_proxied_request,
        read_bounded_json,
    )


async def api_telegram_webhook(request: web.Request) -> web.Response:
    """POST /api/messaging/telegram/webhook — Telegram Bot API inbound webhook."""
    from aj_crew import webhooks
    from aj_crew.telegram.client import (
        TELEGRAM_MAX_WEBHOOK_BYTES,
        TELEGRAM_SECRET_HEADER,
        verify_telegram_webhook_secret,
    )

    state: "DashboardState | None" = request.app.get("state")
    transports = getattr(state, "channel_transports", None) if state is not None else None
    transport = transports.get("telegram") if isinstance(transports, dict) else None
    client = getattr(transport, "client", None) if transport is not None else None
    handler = getattr(transport, "handle_webhook_update", None) if transport is not None else None
    if (
        transport is None
        or not getattr(transport, "_webhook_mode", False)
        or getattr(client, "_closed", False)
        or not callable(handler)
    ):
        return web.json_response(
            {"error": "Telegram webhook not enabled", "code": "webhook_disabled"},
            status=503,
        )

    source = request.remote or "unknown"
    throttled_source = "" if is_proxied_request(request) else source
    if throttled_source and webhooks.auth_throttle_blocked(throttled_source):
        _sel().log_api_access(
            caller=source,
            operation="telegram.webhook",
            outcome="denied",
            source="telegram",
            error="auth failures throttled",
        )
        return web.json_response(
            {"error": "too many failed attempts", "code": "auth_throttled"},
            status=429,
        )

    expected_secret = getattr(transport, "_webhook_secret", "")
    provided_secret = request.headers.get(TELEGRAM_SECRET_HEADER)
    if not verify_telegram_webhook_secret(provided_secret, expected_secret):
        if throttled_source:
            webhooks.record_auth_failure(throttled_source)
        _sel().log_api_access(
            caller=source,
            operation="telegram.webhook",
            outcome="denied",
            source="telegram",
            error="invalid secret token",
        )
        return web.json_response(
            {"error": "unauthorized", "code": "invalid_webhook_secret"},
            status=401,
        )

    if throttled_source:
        webhooks.record_auth_success(throttled_source)

    body, cap_error = await read_bounded_json(
        request,
        max_bytes=TELEGRAM_MAX_WEBHOOK_BYTES,
        require_json_content_type=False,
    )
    if cap_error is not None:
        if cap_error.status == 413:
            return cap_error
        return web.json_response(
            {"error": "invalid JSON", "code": "invalid_json"},
            status=400,
        )
    if not isinstance(body, dict):
        return web.json_response(
            {"error": "update must be a JSON object", "code": "invalid_update"},
            status=400,
        )

    raw_uid = body.get("update_id")
    if isinstance(raw_uid, bool) or not isinstance(raw_uid, int) or raw_uid <= 0:
        return web.json_response(
            {"error": "missing or invalid update_id", "code": "invalid_update_id"},
            status=400,
        )

    accepted = bool(handler(body))
    _sel().log_api_access(
        caller=source,
        operation="telegram.webhook",
        outcome="ok" if accepted else "duplicate_ignored",
        source="telegram",
        resources=f"update_id={raw_uid}",
    )
    return web.json_response({"ok": True, "duplicate": not accepted})
