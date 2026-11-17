"""Dashboard HTTP routes for subscriptions, direct providers, and Perplexity MCP proxy."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from aiohttp import web

from aj_crew.dashboard.handlers.kiro_prerequisite import _is_dashboard_owner
from aj_crew.subscriptions import (
    active_native_providers,
    begin_subscription_connect,
    complete_pasted_connect,
    disconnect_provider,
    discover_all_models,
    load_provider_secret_payload,
    save_direct_provider,
    subscription_status_rows,
)

logger = logging.getLogger(__name__)

_CODE_OWNER_REQUIRED = "dashboard_owner_required"


def _owner_denied() -> web.Response:
    return web.json_response(
        {"error": "dashboard owner required", "code": _CODE_OWNER_REQUIRED},
        status=403,
    )


def _dashboard_origin(request: web.Request) -> str:
    scheme = request.scheme or "http"
    host = request.host or "127.0.0.1:8080"
    return f"{scheme}://{host}"


async def api_subscriptions_status(request: web.Request) -> web.Response:
    """GET /api/subscriptions — safe status rows + cached discovered models."""
    if not _is_dashboard_owner(request):
        return _owner_denied()
    rows = await asyncio.to_thread(subscription_status_rows)
    models = await discover_all_models(force=False)
    return web.json_response(
        {
            "providers": rows,
            "models": [m.as_dict() for m in models],
        }
    )


async def api_subscriptions_begin(request: web.Request) -> web.Response:
    """POST /api/subscriptions/begin — mint a DICloak Copy-Connect-Link."""
    if not _is_dashboard_owner(request):
        return _owner_denied()
    try:
        body = await request.json()
    except Exception:
        body = {}
    provider_id = str((body or {}).get("provider") or "").strip().lower()
    client_id = str((body or {}).get("client_id") or "").strip()
    try:
        started = await begin_subscription_connect(
            provider_id,
            dashboard_origin=_dashboard_origin(request),
            client_id=client_id,
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc), "code": "invalid_provider"}, status=400)
    return web.json_response(started)


async def api_subscriptions_complete(request: web.Request) -> web.Response:
    """POST /api/subscriptions/complete — complete via pasted callback URL or token."""
    if not _is_dashboard_owner(request):
        return _owner_denied()
    try:
        body = await request.json()
    except Exception:
        body = {}
    provider_id = str((body or {}).get("provider") or "").strip().lower()
    pasted = str((body or {}).get("value") or "").strip()
    nonce = str((body or {}).get("nonce") or "").strip()
    try:
        result = await complete_pasted_connect(provider_id, pasted, nonce=nonce)
    except Exception as exc:
        return web.json_response({"error": str(exc), "code": "connect_failed"}, status=400)
    return web.json_response(result)


async def api_subscriptions_save(request: web.Request) -> web.Response:
    """POST /api/subscriptions/save — save direct API-key or Local Ollama provider."""
    if not _is_dashboard_owner(request):
        return _owner_denied()
    try:
        body = await request.json()
    except Exception:
        body = {}
    provider_id = str((body or {}).get("provider") or "").strip().lower()
    if not provider_id:
        return web.json_response(
            {"error": "provider is required", "code": "invalid_provider"}, status=400
        )
    try:
        result = await save_direct_provider(
            provider_id,
            api_key=str((body or {}).get("api_key") or ""),
            base_url=str((body or {}).get("base_url") or ""),
            default_model=str((body or {}).get("default_model") or ""),
            label=str((body or {}).get("label") or ""),
            kind=str((body or {}).get("kind") or ""),
        )
    except Exception as exc:
        return web.json_response({"error": str(exc), "code": "save_failed"}, status=400)
    return web.json_response(result)


async def api_subscriptions_delete(request: web.Request) -> web.Response:
    """DELETE /api/subscriptions/{provider} — disconnect a provider."""
    if not _is_dashboard_owner(request):
        return _owner_denied()
    provider_id = str(request.match_info.get("provider") or "").strip().lower()
    if not provider_id:
        return web.json_response(
            {"error": "provider is required", "code": "invalid_provider"}, status=400
        )
    await disconnect_provider(provider_id)
    return web.json_response({"ok": True, "provider": provider_id})


async def api_subscriptions_refresh_models(request: web.Request) -> web.Response:
    """POST /api/subscriptions/refresh-models — force live model re-discovery."""
    if not _is_dashboard_owner(request):
        return _owner_denied()
    models = await discover_all_models(force=True)
    return web.json_response({"ok": True, "models": [m.as_dict() for m in models]})


async def api_perplexity_mcp_query(request: web.Request) -> web.Response:
    """POST /api/perplexity-mcp/query — strict internal gateway leg for ``ajcrew-core``."""
    if request.get("internal_auth") is not True:
        return web.json_response(
            {
                "ok": False,
                "error": "internal authentication required",
                "code": "internal_auth_required",
            },
            status=403,
        )
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    providers = await asyncio.to_thread(active_native_providers)
    pplx = providers.get("perplexity")
    if pplx is None:
        return web.json_response(
            {
                "ok": False,
                "error": "Perplexity is not connected. Connect Perplexity under Settings -> Agent Harness -> Subscriptions & Providers.",
            },
            status=200,
        )
    creds = await asyncio.to_thread(
        load_provider_secret_payload, str(pplx.get("api_key_ref") or "")
    )
    token = str((creds or {}).get("access_token") or (creds or {}).get("api_key") or "").strip()
    if not token:
        return web.json_response(
            {"ok": False, "error": "Perplexity credential is missing in vault."},
            status=200,
        )

    mode = str((body or {}).get("mode") or "search")
    query = str((body or {}).get("query") or "").strip()
    recency = str((body or {}).get("recency") or "").strip()
    model_name = "sonar-deep-research" if mode == "deep_research" else "sonar-pro"
    base_url = str(pplx.get("base_url") or "https://api.perplexity.ai").rstrip("/")

    req_payload: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": query}],
    }
    if recency in ("hour", "day", "week", "month", "year"):
        req_payload["search_recency_filter"] = recency

    timeout = aiohttp.ClientTimeout(total=160 if mode == "deep_research" else 50)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=req_payload,
            ) as resp:
                resp_json = await resp.json(content_type=None)
                if resp.status >= 400 or not isinstance(resp_json, dict):
                    err_detail = (
                        resp_json.get("error", {}).get("message")
                        if isinstance(resp_json, dict) and isinstance(resp_json.get("error"), dict)
                        else str(resp.status)
                    )
                    return web.json_response(
                        {"ok": False, "error": f"Perplexity HTTP {resp.status}: {err_detail}"},
                        status=200,
                    )
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=200)

    choices = resp_json.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        content = str(msg.get("content") or "")
    citations = resp_json.get("citations") or []
    if isinstance(citations, list) and citations:
        cite_lines = "\n".join(f"[{idx}] {url}" for idx, url in enumerate(citations, 1))
        content = f"{content}\n\nSources:\n{cite_lines}"
    return web.json_response({"ok": True, "result": content})
