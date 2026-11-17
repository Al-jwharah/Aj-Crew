"""DICloak / browser-reuse PKCE & Connect-Link flows and token refresh."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp
from aiohttp import web

from aj_crew.subscriptions.store import (
    PROVIDER_PRESETS,
    delete_provider_secret,
    load_provider_secret_payload,
    remove_native_provider_config,
    save_provider_secret_payload,
    upsert_native_provider_config,
)

logger = logging.getLogger(__name__)

_PENDING_TTL_SECS = 600.0


@dataclass
class PendingConnectFlow:
    provider_id: str
    state: str
    code_verifier: str
    redirect_uri: str
    client_id: str
    created_at: float
    dashboard_origin: str


_PENDING_FLOWS: dict[str, PendingConnectFlow] = {}
_LOOPBACK_RUNNERS: dict[int, web.AppRunner] = {}
_SHARED_BRIDGE_PORT: int = 0


def _prune_expired_flows() -> None:
    now = time.monotonic()
    expired = [k for k, v in _PENDING_FLOWS.items() if now - v.created_at > _PENDING_TTL_SECS]
    for k in expired:
        _PENDING_FLOWS.pop(k, None)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _completion_html(provider_label: str, dashboard_origin: str) -> str:
    safe_label = html.escape(provider_label)
    deep_link = "ajcrew://auth-complete"
    fallback = html.escape(f"{dashboard_origin.rstrip('/')}/settings?tab=agent-backend")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Connected — Aj Crew</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0B0F14; color: #E6EDF3;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .card {{ background: #121923; border: 1px solid #243044; border-radius: 12px;
           padding: 28px 32px; max-width: 440px; text-align: center; }}
  a.btn {{ display: inline-block; margin-top: 14px; padding: 8px 18px; border-radius: 8px;
           background: #10B981; color: #0B0F14; font-weight: 600; text-decoration: none; }}
</style>
</head>
<body>
  <div class="card">
    <h2>{safe_label} Connected</h2>
    <p>Credentials saved to Aj Crew's encrypted vault and live models discovered.</p>
    <a class="btn" href="{fallback}">Return to Aj Crew Dashboard</a>
  </div>
  <script>
    try {{ window.location.href = {deep_link!r}; }} catch (e) {{}}
    setTimeout(function() {{ window.location.replace({fallback!r}); }}, 1200);
  </script>
</body>
</html>"""


def render_perplexity_connect_page(nonce: str, post_action_url: str) -> tuple[int, str]:
    """Render the 1-step DICloak connect page for Perplexity without triggering email/OTP login."""
    _prune_expired_flows()
    flow = _PENDING_FLOWS.get(nonce)
    if flow is None or flow.provider_id != "perplexity":
        return (
            400,
            "<html><body><h3>Connect link expired. Generate a fresh link in Aj Crew.</h3></body></html>",
        )
    action = html.escape(post_action_url)
    safe_nonce = html.escape(nonce)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Connect Perplexity — Aj Crew</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0B0F14; color: #E6EDF3;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #121923; border: 1px solid #243044; border-radius: 12px;
           padding: 28px 32px; width: 100%; max-width: 460px; }}
  input {{ width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px;
           border: 1px solid #243044; background: #0B0F14; color: #E6EDF3; margin: 10px 0 14px; }}
  button {{ width: 100%; padding: 10px 16px; border-radius: 8px; border: none;
            background: #10B981; color: #0B0F14; font-weight: 600; cursor: pointer; }}
  .hint {{ font-size: 12.5px; color: #8B98A9; line-height: 1.5; }}
</style>
</head>
<body>
  <div class="card">
    <h2 style="margin-top:0">Connect Perplexity Pro / Sonar</h2>
    <p class="hint">Paste your Perplexity API key (from your already-signed-in Perplexity Settings &rarr; API tab in this DICloak profile) to unlock live Sonar search, Deep Research MCP tools, and model discovery — zero re-login needed.</p>
    <form method="post" action="{action}">
      <input type="hidden" name="nonce" value="{safe_nonce}" />
      <input type="password" name="token" placeholder="pplx-..." required autofocus />
      <button type="submit">Connect &amp; Discover Models</button>
    </form>
  </div>
</body>
</html>"""
    return 200, page


async def _ensure_chatgpt_loopback_listener() -> bool:
    """Bind temporary 127.0.0.1:1455 listener for ChatGPT Codex PKCE callback if free."""
    port = 1455
    if port in _LOOPBACK_RUNNERS:
        return True
    app = web.Application()

    async def _cb(req: web.Request) -> web.Response:
        state = req.query.get("state", "")
        code = req.query.get("code", "")
        ok, html_body = await handle_loopback_oauth_callback(state=state, code=code)
        return web.Response(text=html_body, status=200 if ok else 400, content_type="text/html")

    app.router.add_get("/auth/callback", _cb)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        _LOOPBACK_RUNNERS[port] = runner
        return True
    except OSError:
        await runner.cleanup()
        return False


async def _ensure_shared_bridge_listener() -> int:
    """Bind a dedicated 127.0.0.1 loopback bridge for DICloak Gemini/Perplexity connect links."""
    global _SHARED_BRIDGE_PORT
    if _SHARED_BRIDGE_PORT and _SHARED_BRIDGE_PORT in _LOOPBACK_RUNNERS:
        return _SHARED_BRIDGE_PORT

    app = web.Application()

    async def _oauth_cb(req: web.Request) -> web.Response:
        state = req.query.get("state", "")
        code = req.query.get("code", "")
        ok, html_body = await handle_loopback_oauth_callback(state=state, code=code)
        return web.Response(text=html_body, status=200 if ok else 400, content_type="text/html")

    async def _pplx_get(req: web.Request) -> web.Response:
        nonce = req.query.get("nonce", "")
        status, html_body = render_perplexity_connect_page(
            nonce, f"http://127.0.0.1:{_SHARED_BRIDGE_PORT}/perplexity/complete"
        )
        return web.Response(text=html_body, status=status, content_type="text/html")

    async def _pplx_post(req: web.Request) -> web.Response:
        post = await req.post()
        nonce = str(post.get("nonce") or "").strip()
        token = str(post.get("token") or "").strip()
        flow = _PENDING_FLOWS.get(nonce)
        origin = flow.dashboard_origin if flow else "http://127.0.0.1:8080"
        if flow is None or flow.provider_id != "perplexity" or not token:
            return web.Response(
                text="<html><body><h3>Invalid or expired connect token.</h3></body></html>",
                status=400,
                content_type="text/html",
            )
        _PENDING_FLOWS.pop(nonce, None)
        await _finalize_connected_provider("perplexity", {"api_key": token})
        return web.Response(
            text=_completion_html("Perplexity Pro & Sonar", origin),
            status=200,
            content_type="text/html",
        )

    app.router.add_get("/oauth2callback", _oauth_cb)
    app.router.add_get("/perplexity/connect", _pplx_get)
    app.router.add_post("/perplexity/complete", _pplx_post)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = getattr(site, "_server", None)
    sock_list = getattr(sockets, "sockets", None) or []
    bound_port = int(sock_list[0].getsockname()[1]) if sock_list else 0
    _SHARED_BRIDGE_PORT = bound_port
    _LOOPBACK_RUNNERS[bound_port] = runner
    return bound_port


async def begin_subscription_connect(
    provider_id: str,
    *,
    dashboard_origin: str,
    client_id: str = "",
) -> dict[str, Any]:
    """Create a one-time ``state``/``nonce`` Copy-Connect-Link for pasting into DICloak."""
    _prune_expired_flows()
    preset = PROVIDER_PRESETS.get(provider_id)
    if preset is None:
        raise ValueError(f"Unknown subscription provider: {provider_id!r}")

    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()

    if provider_id == "perplexity":
        bridge_port = await _ensure_shared_bridge_listener()
        connect_url = f"http://127.0.0.1:{bridge_port}/perplexity/connect?nonce={state}"
        _PENDING_FLOWS[state] = PendingConnectFlow(
            provider_id="perplexity",
            state=state,
            code_verifier=verifier,
            redirect_uri=connect_url,
            client_id="",
            created_at=time.monotonic(),
            dashboard_origin=dashboard_origin,
        )
        return {
            "provider": "perplexity",
            "connect_url": connect_url,
            "state": state,
            "loopback_listening": bool(bridge_port),
        }

    if provider_id == "chatgpt":
        listening = await _ensure_chatgpt_loopback_listener()
        redirect_uri = "http://localhost:1455/auth/callback"
        resolved_cid = client_id.strip() or str(preset["default_client_id"])
        # Never pass prompt=login or max_age=0: reuse active DICloak session!
        params = {
            "response_type": "code",
            "client_id": resolved_cid,
            "redirect_uri": redirect_uri,
            "scope": str(preset["scopes"]),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        connect_url = f"{preset['oauth_authorize_url']}?{urlencode(params)}"
        _PENDING_FLOWS[state] = PendingConnectFlow(
            provider_id="chatgpt",
            state=state,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            client_id=resolved_cid,
            created_at=time.monotonic(),
            dashboard_origin=dashboard_origin,
        )
        return {
            "provider": "chatgpt",
            "connect_url": connect_url,
            "state": state,
            "loopback_listening": listening,
        }

    if provider_id == "gemini":
        resolved_cid = client_id.strip()
        if not resolved_cid:
            raise ValueError(
                "Enter an OAuth Client ID for Google PKCE, or paste a Gemini API key directly."
            )
        bridge_port = await _ensure_shared_bridge_listener()
        redirect_uri = f"http://127.0.0.1:{bridge_port}/oauth2callback"
        # access_type=offline without prompt=login so active DICloak Google session approves in 1 click
        params = {
            "response_type": "code",
            "client_id": resolved_cid,
            "redirect_uri": redirect_uri,
            "scope": str(preset["scopes"]),
            "access_type": "offline",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        connect_url = f"{preset['oauth_authorize_url']}?{urlencode(params)}"
        _PENDING_FLOWS[state] = PendingConnectFlow(
            provider_id="gemini",
            state=state,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            client_id=resolved_cid,
            created_at=time.monotonic(),
            dashboard_origin=dashboard_origin,
        )
        return {
            "provider": "gemini",
            "connect_url": connect_url,
            "state": state,
            "loopback_listening": True,
        }

    raise ValueError(f"Provider {provider_id!r} uses direct API key setup")


async def _exchange_pkce_code(flow: PendingConnectFlow, code: str) -> dict[str, Any]:
    preset = PROVIDER_PRESETS[flow.provider_id]
    token_url = str(preset["oauth_token_url"])
    form = {
        "grant_type": "authorization_code",
        "client_id": flow.client_id,
        "code": code,
        "redirect_uri": flow.redirect_uri,
        "code_verifier": flow.code_verifier,
    }
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(token_url, data=form) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400 or not isinstance(body, dict) or not body.get("access_token"):
                err = (
                    body.get("error_description") or body.get("error")
                    if isinstance(body, dict)
                    else resp.status
                )
                raise RuntimeError(f"OAuth token exchange failed ({err})")
            expires_in = int(body.get("expires_in") or 3600)
            return {
                "access_token": str(body["access_token"]),
                "refresh_token": str(body.get("refresh_token") or ""),
                "expires_at": int(time.time()) + expires_in,
                "token_url": token_url,
                "client_id": flow.client_id,
            }


async def refresh_oauth_payload_if_needed(
    provider_id: str, secret_ref: str
) -> dict[str, Any] | None:
    """Refresh an expired OAuth subscription token in the vault when a refresh_token is stored."""
    payload = load_provider_secret_payload(secret_ref)
    if not payload:
        return None
    expires_at = int(payload.get("expires_at") or 0)
    refresh_tok = str(payload.get("refresh_token") or "")
    token_url = str(payload.get("token_url") or "")
    client_id = str(payload.get("client_id") or "")
    if not expires_at or time.time() + 120 < expires_at or not refresh_tok or not token_url:
        return payload

    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
        "client_id": client_id,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(token_url, data=form) as resp:
                body = await resp.json(content_type=None)
                if resp.status < 400 and isinstance(body, dict) and body.get("access_token"):
                    updated = {
                        **payload,
                        "access_token": str(body["access_token"]),
                        "refresh_token": str(body.get("refresh_token") or refresh_tok),
                        "expires_at": int(time.time()) + int(body.get("expires_in") or 3600),
                    }
                    await asyncio.to_thread(save_provider_secret_payload, provider_id, updated)
                    return updated
    except Exception:
        logger.warning(
            "Token refresh failed for %r; using current token", provider_id, exc_info=True
        )
    return payload


def _stamp_setup_complete() -> None:
    from aj_crew.config.paths import config_dir
    from aj_crew.kiro_prerequisite_service import KiroPrerequisiteService

    KiroPrerequisiteService(data_home=config_dir())._mark_setup_complete()


async def _finalize_connected_provider(
    provider_id: str,
    secret_payload: dict[str, Any],
    *,
    base_url: str = "",
    client_id: str = "",
) -> list[dict[str, Any]]:
    from aj_crew.subscriptions.discovery import discover_provider_models

    preset = PROVIDER_PRESETS.get(provider_id, {})
    secret_ref = await asyncio.to_thread(save_provider_secret_payload, provider_id, secret_payload)
    entry: dict[str, Any] = {
        "kind": str(preset.get("kind") or "openai_compat"),
        "label": str(preset.get("label") or provider_id),
        "base_url": (base_url or str(preset.get("base_url") or "")).rstrip("/"),
        "api_key_ref": secret_ref,
        "enabled": True,
    }
    if client_id:
        entry["client_id"] = client_id
    await asyncio.to_thread(upsert_native_provider_config, provider_id, entry)
    try:
        await asyncio.to_thread(_stamp_setup_complete)
    except Exception:
        logger.debug("Could not stamp independent backend setup marker", exc_info=True)
    models = await discover_provider_models(provider_id)
    return [m.as_dict() for m in models]


async def handle_loopback_oauth_callback(*, state: str, code: str) -> tuple[bool, str]:
    """Complete a PKCE callback arriving on localhost/127.0.0.1 and return auto-redirect HTML."""
    _prune_expired_flows()
    flow = _PENDING_FLOWS.pop(state, None)
    if flow is None or not code:
        return False, "<html><body><h3>Invalid or expired OAuth state.</h3></body></html>"
    try:
        token_payload = await _exchange_pkce_code(flow, code)
        await _finalize_connected_provider(
            flow.provider_id,
            token_payload,
            client_id=flow.client_id,
        )
    except Exception as exc:
        logger.warning("OAuth callback exchange failed for %r: %s", flow.provider_id, exc)
        return (
            False,
            f"<html><body><h3>Connection failed: {html.escape(str(exc))}</h3></body></html>",
        )
    label = str(PROVIDER_PRESETS.get(flow.provider_id, {}).get("label") or flow.provider_id)
    return True, _completion_html(label, flow.dashboard_origin)


async def complete_pasted_connect(
    provider_id: str,
    pasted: str,
    *,
    nonce: str = "",
) -> dict[str, Any]:
    """Complete connection when a DICloak profile proxies loopback (paste callback URL or token)."""
    text = pasted.strip()
    if not text:
        raise ValueError("Pasted callback URL or credential cannot be empty")
    if text.startswith(("http://", "https://")):
        parsed = urlsplit(text)
        qs = parse_qs(parsed.query)
        state = (qs.get("state") or [""])[0]
        code = (qs.get("code") or [""])[0]
        flow = _PENDING_FLOWS.pop(state, None)
        if flow is None or not code:
            raise ValueError("Callback URL is missing a valid code or active state")
        token_payload = await _exchange_pkce_code(flow, code)
        models = await _finalize_connected_provider(
            flow.provider_id, token_payload, client_id=flow.client_id
        )
        return {"provider": flow.provider_id, "connected": True, "models": models}

    if nonce:
        _PENDING_FLOWS.pop(nonce, None)
    models = await _finalize_connected_provider(provider_id, {"api_key": text})
    return {"provider": provider_id, "connected": True, "models": models}


async def save_direct_provider(
    provider_id: str,
    *,
    api_key: str = "",
    base_url: str = "",
    default_model: str = "",
    label: str = "",
    kind: str = "",
) -> dict[str, Any]:
    """Save a direct API-key or keyless Local Ollama provider and run live model discovery."""
    from aj_crew.subscriptions.discovery import discover_provider_models

    preset = PROVIDER_PRESETS.get(provider_id, {})
    resolved_kind = kind or str(preset.get("kind") or "openai_compat")
    resolved_url = (base_url.strip() or str(preset.get("base_url") or "")).rstrip("/")
    if not resolved_url:
        raise ValueError("base_url is required")

    api_key_ref = ""
    if api_key.strip():
        api_key_ref = await asyncio.to_thread(
            save_provider_secret_payload, provider_id, {"api_key": api_key.strip()}
        )
    elif resolved_kind != "ollama":
        from aj_crew.config.loader import AjCrewConfig

        existing = (AjCrewConfig.load().agent.native_providers or {}).get(provider_id) or {}
        api_key_ref = str(existing.get("api_key_ref") or "")
        if not api_key_ref:
            raise ValueError(f"API key is required for {provider_id}")

    entry: dict[str, Any] = {
        "kind": resolved_kind,
        "label": label.strip() or str(preset.get("label") or provider_id),
        "base_url": resolved_url,
        "api_key_ref": api_key_ref,
        "default_model": default_model.strip(),
        "enabled": True,
    }
    await asyncio.to_thread(upsert_native_provider_config, provider_id, entry)
    try:
        await asyncio.to_thread(_stamp_setup_complete)
    except Exception:
        logger.debug("Could not stamp independent backend setup marker", exc_info=True)
    models = await discover_provider_models(provider_id)
    return {"provider": provider_id, "connected": True, "models": [m.as_dict() for m in models]}


async def disconnect_provider(provider_id: str) -> None:
    """Disconnect *provider_id* and purge its vault entry and cached models."""
    from aj_crew.subscriptions.discovery import clear_models_cache

    await asyncio.to_thread(remove_native_provider_config, provider_id)
    await asyncio.to_thread(delete_provider_secret, provider_id)
    clear_models_cache(provider_id)
