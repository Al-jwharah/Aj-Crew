"""Unit and integration tests for ACP_BACKEND_NATIVE, DICloak subscriptions,
live model discovery, and Perplexity MCP tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web

from aj_crew import mcp_core
from aj_crew.acp.harness.strands_keys import write_keys_file
from aj_crew.agent_sdk import backend_install, backends, host_auth, tool_gate
from aj_crew.crewmate_harness import bots_cannot_run_on
from aj_crew.kiro_prerequisite_service import KiroPrerequisiteService
from aj_crew.mcp_tools import dispatch, perplexity
from aj_crew.subscriptions.discovery import clear_models_cache, discover_provider_models
from aj_crew.subscriptions.flows import (
    _LOOPBACK_RUNNERS,
    _PENDING_FLOWS,
    begin_subscription_connect,
    complete_pasted_connect,
    disconnect_provider,
    save_direct_provider,
)
from aj_crew.subscriptions.store import subscription_status_rows


def test_native_backend_is_selectable_and_unlocked_on_windows_and_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert backends.ACP_BACKEND_NATIVE == "native"
    assert backends.ACP_BACKEND_NATIVE in backends.ACP_BACKENDS_KNOWN
    assert backends.ACP_BACKEND_NATIVE in backends.BASELINE_SELECTABLE_BACKENDS
    assert backends.ACP_BACKEND_NATIVE in backends.ACP_BACKENDS_INDEPENDENT_SETUP
    assert backends.ACP_BACKEND_NATIVE in backends.ACP_BACKENDS_ACP_RUNTIME
    assert not tool_gate.is_enforced(backends.ACP_BACKEND_NATIVE)
    assert bots_cannot_run_on(backends.ACP_BACKEND_NATIVE) is False

    for fake_plat in ("win32", "linux", "darwin"):
        monkeypatch.setattr("sys.platform", fake_plat)
        assert not tool_gate.is_enforced(backends.ACP_BACKEND_NATIVE)

    decl = next(
        d for d in host_auth.AGENT_AUTH_DECLARATIONS if d.backend == backends.ACP_BACKEND_NATIVE
    )
    assert decl.entitlement_source == "host_vault"
    assert decl.host_logout_retires_children is False

    probe = backend_install.probe_backend(backends.ACP_BACKEND_NATIVE)
    assert probe.installed == "installed"
    assert probe.missing_components == ()


@pytest.mark.asyncio
async def test_dicloak_copy_connect_links_never_force_relogin() -> None:
    _PENDING_FLOWS.clear()
    try:
        chatgpt = await begin_subscription_connect(
            "chatgpt", dashboard_origin="http://127.0.0.1:8080"
        )
        qs_cg = parse_qs(urlsplit(chatgpt["connect_url"]).query)
        assert "prompt" not in qs_cg
        assert "max_age" not in qs_cg
        assert qs_cg["code_challenge_method"] == ["S256"]
        assert qs_cg["redirect_uri"] == ["http://localhost:1455/auth/callback"]

        gemini = await begin_subscription_connect(
            "gemini",
            dashboard_origin="http://127.0.0.1:8080",
            client_id="123456-test.apps.googleusercontent.com",
        )
        qs_gm = parse_qs(urlsplit(gemini["connect_url"]).query)
        assert "prompt" not in qs_gm
        assert "max_age" not in qs_gm
        assert qs_gm["access_type"] == ["offline"]
        assert qs_gm["code_challenge_method"] == ["S256"]

        pplx = await begin_subscription_connect(
            "perplexity", dashboard_origin="http://127.0.0.1:8080"
        )
        assert "/perplexity/connect?nonce=" in pplx["connect_url"]
        assert pplx["state"] in _PENDING_FLOWS
    finally:
        _PENDING_FLOWS.clear()
        for runner in list(_LOOPBACK_RUNNERS.values()):
            await runner.cleanup()
        _LOOPBACK_RUNNERS.clear()


@pytest.mark.asyncio
async def test_vault_backed_direct_provider_and_live_model_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AJCREW_HOME", str(tmp_path))
    clear_models_cache()

    async def handle_models(_req: web.Request) -> web.Response:
        return web.json_response(
            {
                "data": [
                    {"id": "live-alpha-1", "context_length": 128000},
                    {"id": "live-beta-2", "context_length": 64000},
                ]
            }
        )

    app = web.Application()
    app.router.add_get("/v1/models", handle_models)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        saved = await save_direct_provider(
            "openrouter",
            api_key="sk-or-test-secret-value",
            base_url=f"http://127.0.0.1:{port}/v1",
        )
        assert saved["connected"] is True
        ids = [m["id"] for m in saved["models"]]
        assert "openrouter/live-alpha-1" in ids
        assert "openrouter/live-beta-2" in ids

        # Verify config.json never contains the plaintext secret
        raw_cfg = (tmp_path / "config.json").read_text(encoding="utf-8")
        assert "sk-or-test-secret-value" not in raw_cfg
        assert "secret://native-provider-openrouter" in raw_cfg

        # Verify KiroPrerequisiteService marks setup complete and skips kiro-cli probe
        svc = KiroPrerequisiteService(data_home=tmp_path)
        assert svc.initial_setup_complete is True
        snap = await svc.snapshot()
        assert snap["initial_setup_complete"] is True

        rows = subscription_status_rows()
        or_row = next(r for r in rows if r["id"] == "openrouter")
        assert or_row["connected"] is True

        discovered = await discover_provider_models("openrouter")
        assert [m.id for m in discovered] == [
            "openrouter/live-alpha-1",
            "openrouter/live-beta-2",
        ]

        from aj_crew.subscriptions import discovery as disc_mod

        async def _fake_pplx_discover(pid: str, info: dict[str, Any], tok: str) -> list[Any]:
            return []

        monkeypatch.setattr(disc_mod, "_discover_perplexity", _fake_pplx_discover)
        await complete_pasted_connect("perplexity", "pplx-test-key-999")
        raw_cfg_after = (tmp_path / "config.json").read_text(encoding="utf-8")
        assert "pplx-test-key-999" not in raw_cfg_after
        assert "secret://native-provider-perplexity" in raw_cfg_after

        await disconnect_provider("openrouter")
        await disconnect_provider("perplexity")
        rows_after = subscription_status_rows()
        assert next(r for r in rows_after if r["id"] == "openrouter")["connected"] is False
    finally:
        await runner.cleanup()


def test_perplexity_mcp_tools_are_registered_and_route_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_names = {s["name"] for s in perplexity.schemas()}
    assert tool_names == {"perplexity_search", "perplexity_deep_research"}

    captured_calls: list[tuple[str, dict[str, Any]]] = []

    def fake_gateway_post(
        path: str, payload: dict[str, Any], *, timeout: float = 0.0, **kwargs: Any
    ) -> dict[str, Any]:
        captured_calls.append((path, payload))
        return {"ok": True, "result": "Answer [1]\n\nSources:\n[1] https://example.com"}

    monkeypatch.setattr(mcp_core, "_post", fake_gateway_post)

    out_search = dispatch("perplexity_search", {"query": "latest ACP spec", "recency": "week"})
    assert "https://example.com" in out_search
    assert captured_calls[-1] == (
        "/api/perplexity-mcp/query",
        {"mode": "search", "query": "latest ACP spec", "recency": "week"},
    )

    out_deep = dispatch("perplexity_deep_research", {"topic": "compare multi-agent harnesses"})
    assert "https://example.com" in out_deep
    assert captured_calls[-1][1]["mode"] == "deep_research"


@pytest.mark.asyncio
async def test_native_acp_engine_round_trip_turn_with_permission_gate(tmp_path: Path) -> None:
    call_idx = 0

    async def handle_chat(req: web.Request) -> web.StreamResponse:
        nonlocal call_idx
        call_idx += 1
        resp = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await resp.prepare(req)
        if call_idx == 1:
            chunk = {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "tc_1",
                                    "type": "function",
                                    "function": {
                                        "name": "fs_read",
                                        "arguments": json.dumps({"path": "hello.txt"}),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
            await resp.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        else:
            chunk = {"choices": [{"delta": {"content": "Hello from native engine!"}}]}
            await resp.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle_chat)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "hello.txt").write_text("jewel-ok\n", encoding="utf-8")
        home = tmp_path / "home"
        home.mkdir()
        keys_file = write_keys_file(
            str(tmp_path),
            {
                "local": json.dumps(
                    {
                        "id": "local",
                        "kind": "openai_compat",
                        "label": "Loopback",
                        "base_url": f"http://127.0.0.1:{port}/v1",
                        "default_model": "loopback-1",
                        "credentials": {"api_key": "sk-test"},
                    }
                )
            },
        )
        import os
        import sys

        env = dict(os.environ)
        env["AJCREW_HOME"] = str(home)
        env["AJCREW_NATIVE_KEYS_FILE"] = keys_file
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "aj_crew.acp.native_engine",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert proc.stdin and proc.stdout
        permission_asked = False
        chunks: list[str] = []

        async def send(msg: dict[str, Any]) -> None:
            assert proc.stdin
            proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            await proc.stdin.drain()

        async def wait_id(req_id: int) -> dict[str, Any]:
            nonlocal permission_asked
            assert proc.stdout
            while True:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
                frame = json.loads(raw.decode("utf-8"))
                if frame.get("method") == "session/request_permission":
                    permission_asked = True
                    await send(
                        {
                            "jsonrpc": "2.0",
                            "id": frame["id"],
                            "result": {
                                "outcome": {"outcome": "selected", "optionId": "allow_once"}
                            },
                        }
                    )
                    continue
                if frame.get("method") == "session/update":
                    upd = frame.get("params", {}).get("update", {})
                    if upd.get("sessionUpdate") == "agent_message_chunk":
                        chunks.append(upd.get("content", {}).get("text", ""))
                if frame.get("id") == req_id:
                    return frame

        await send(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}}
        )
        await wait_id(1)
        await send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": str(ws), "mcpServers": []},
            }
        )
        snew = await wait_id(2)
        sid = snew["result"]["sessionId"]
        await send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {
                    "sessionId": sid,
                    "prompt": [{"type": "text", "text": "Read hello.txt"}],
                },
            }
        )
        res = await wait_id(3)
        assert res["result"]["stopReason"] == "end_turn"
        assert permission_asked is True
        assert "".join(chunks) == "Hello from native engine!"
        assert not Path(keys_file).exists()

        proc.stdin.close()
        await asyncio.wait_for(proc.wait(), timeout=5)
    finally:
        await runner.cleanup()
