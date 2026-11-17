"""Encrypted vault storage and provider presets for native subscriptions and APIs."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from aj_crew.config.loader import AjCrewConfig, update_config_locked
from aj_crew.config.paths import config_dir
from aj_crew.mcp_gateway.secret_uri import SECRET_URI_PREFIX
from aj_crew.secrets import SecretVault

logger = logging.getLogger(__name__)

VAULT_KEY_PREFIX = "native-provider-"

#: Built-in provider presets shown in Onboarding and Settings -> Agent Harness.
#: Zero hardcoded model ids: every model list comes from live discovery or ``"auto"``.
PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "chatgpt": {
        "id": "chatgpt",
        "label": "ChatGPT Subscription",
        "kind": "chatgpt_oauth",
        "auth_mode": "oauth_pkce",
        "base_url": "https://api.openai.com/v1",
        "oauth_authorize_url": "https://auth.openai.com/oauth/authorize",
        "oauth_token_url": "https://auth.openai.com/oauth/token",
        "default_client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "scopes": "openid profile email offline_access",
        "loopback_port": 1455,
        "loopback_path": "/auth/callback",
    },
    "gemini": {
        "id": "gemini",
        "label": "Google Gemini",
        "kind": "gemini",
        "auth_mode": "oauth_or_key",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "oauth_authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "oauth_token_url": "https://oauth2.googleapis.com/token",
        "scopes": "https://www.googleapis.com/auth/generative-language.retriever https://www.googleapis.com/auth/cloud-platform",
    },
    "perplexity": {
        "id": "perplexity",
        "label": "Perplexity Pro & Sonar",
        "kind": "perplexity",
        "auth_mode": "connect_link_or_key",
        "base_url": "https://api.perplexity.ai",
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI API",
        "kind": "openai_compat",
        "auth_mode": "api_key",
        "base_url": "https://api.openai.com/v1",
    },
    "anthropic": {
        "id": "anthropic",
        "label": "Anthropic API",
        "kind": "anthropic",
        "auth_mode": "api_key",
        "base_url": "https://api.anthropic.com/v1",
    },
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek API",
        "kind": "openai_compat",
        "auth_mode": "api_key",
        "base_url": "https://api.deepseek.com/v1",
    },
    "openrouter": {
        "id": "openrouter",
        "label": "OpenRouter",
        "kind": "openai_compat",
        "auth_mode": "api_key",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "ollama": {
        "id": "ollama",
        "label": "Local Ollama",
        "kind": "ollama",
        "auth_mode": "keyless",
        "base_url": "http://127.0.0.1:11434/v1",
    },
}


def vault_name_for(provider_id: str) -> str:
    """Vault key name for *provider_id*."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in provider_id.strip().lower())
    return f"{VAULT_KEY_PREFIX}{safe[:48]}"


def secret_uri_for(provider_id: str) -> str:
    """``secret://`` URI referencing *provider_id*'s vault entry."""
    return f"{SECRET_URI_PREFIX}{vault_name_for(provider_id)}"


def _vault() -> SecretVault:
    return SecretVault(config_dir())


def save_provider_secret_payload(provider_id: str, payload: dict[str, Any]) -> str:
    """Store *payload* (token or JSON credential record) in the AES-GCM vault; return its ``secret://`` ref."""
    vname = vault_name_for(provider_id)
    serialized = json.dumps({**payload, "updated_at": int(time.time())}, separators=(",", ":"))
    _vault().set_sync(vname, serialized)
    return f"{SECRET_URI_PREFIX}{vname}"


def load_provider_secret_payload(secret_ref: str) -> dict[str, Any] | None:
    """Read and parse a stored provider secret payload from *secret_ref* (or plain secret string)."""
    if not secret_ref or not secret_ref.startswith(SECRET_URI_PREFIX):
        return None
    name = secret_ref[len(SECRET_URI_PREFIX) :].strip()
    if not name:
        return None
    try:
        secret = _vault().get(name)
    except Exception:
        logger.warning("Failed reading provider secret %r from vault", name, exc_info=True)
        return None
    if secret is None:
        return None
    raw = secret.reveal()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"api_key": raw}


def delete_provider_secret(provider_id: str) -> None:
    """Remove *provider_id*'s vault credential if stored."""
    try:
        _vault().delete_sync(vault_name_for(provider_id))
    except Exception:
        logger.debug("Could not delete vault entry for %r", provider_id, exc_info=True)


def active_native_providers(cfg: AjCrewConfig | None = None) -> dict[str, dict[str, Any]]:
    """Enabled native provider entries from ``agent.native_providers``."""
    loaded = cfg if cfg is not None else AjCrewConfig.load()
    raw = getattr(loaded.agent, "native_providers", None) or {}
    out: dict[str, dict[str, Any]] = {}
    for pid, info in raw.items():
        if not isinstance(info, dict) or not info.get("enabled", True):
            continue
        preset = PROVIDER_PRESETS.get(pid, {})
        kind = str(info.get("kind") or preset.get("kind") or "openai_compat")
        base_url = str(info.get("base_url") or preset.get("base_url") or "").rstrip("/")
        api_key_ref = str(info.get("api_key_ref") or "")
        if kind != "ollama" and not api_key_ref:
            continue
        out[pid] = {
            "id": pid,
            "kind": kind,
            "label": str(info.get("label") or preset.get("label") or pid),
            "base_url": base_url,
            "api_key_ref": api_key_ref,
            "default_model": str(info.get("default_model") or ""),
            "client_id": str(info.get("client_id") or preset.get("default_client_id") or ""),
        }
    return out


def has_active_native_provider(cfg: AjCrewConfig | None = None) -> bool:
    """True when at least one native subscription or API provider is configured and usable."""
    try:
        providers = active_native_providers(cfg)
    except Exception:
        return False
    for info in providers.values():
        if info["kind"] == "ollama":
            return True
        payload = load_provider_secret_payload(str(info.get("api_key_ref") or ""))
        if payload and (payload.get("access_token") or payload.get("api_key")):
            return True
    return False


def resolve_all_native_provider_credentials(
    cfg: AjCrewConfig | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the resolved in-memory credential bundle handed via one-time ``0600`` scratch file."""
    providers = active_native_providers(cfg)
    resolved: dict[str, dict[str, Any]] = {}
    for pid, info in providers.items():
        secret_data = load_provider_secret_payload(str(info.get("api_key_ref") or "")) or {}
        if info["kind"] != "ollama" and not (
            secret_data.get("access_token") or secret_data.get("api_key")
        ):
            continue
        resolved[pid] = {
            **info,
            "credentials": secret_data,
        }
    return resolved


def upsert_native_provider_config(
    provider_id: str,
    entry: dict[str, Any],
    *,
    activate_native_backend: bool = True,
) -> None:
    """Atomically save *entry* into ``agent.native_providers[provider_id]``."""
    from aj_crew.agent_sdk.backends import ACP_BACKEND_NATIVE

    def _mutate(doc: dict[str, Any]) -> dict[str, Any]:
        agent_sec = doc.setdefault("agent", {})
        if not isinstance(agent_sec, dict):
            agent_sec = {}
            doc["agent"] = agent_sec
        providers_map = agent_sec.setdefault("native_providers", {})
        if not isinstance(providers_map, dict):
            providers_map = {}
            agent_sec["native_providers"] = providers_map
        existing = providers_map.get(provider_id)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(entry)
        providers_map[provider_id] = merged
        if activate_native_backend:
            agent_sec["acp_backend"] = ACP_BACKEND_NATIVE
        return doc

    update_config_locked(mutate=_mutate)


def remove_native_provider_config(provider_id: str) -> None:
    """Remove *provider_id* from ``agent.native_providers``."""

    def _mutate(doc: dict[str, Any]) -> dict[str, Any]:
        agent_sec = doc.get("agent")
        if isinstance(agent_sec, dict):
            providers_map = agent_sec.get("native_providers")
            if isinstance(providers_map, dict):
                providers_map.pop(provider_id, None)
        return doc

    update_config_locked(mutate=_mutate)


def subscription_status_rows(cfg: AjCrewConfig | None = None) -> list[dict[str, Any]]:
    """Safe, secret-free status rows for every preset and custom native provider."""
    loaded = cfg if cfg is not None else AjCrewConfig.load()
    configured = getattr(loaded.agent, "native_providers", None) or {}
    seen: list[str] = list(PROVIDER_PRESETS.keys()) + [
        k for k in configured.keys() if k not in PROVIDER_PRESETS
    ]
    rows: list[dict[str, Any]] = []
    for pid in seen:
        preset = PROVIDER_PRESETS.get(pid, {})
        raw_entry = configured.get(pid)
        entry: dict[str, Any] = raw_entry if isinstance(raw_entry, dict) else {}
        kind = str(entry.get("kind") or preset.get("kind") or "openai_compat")
        api_key_ref = str(entry.get("api_key_ref") or "")
        payload = load_provider_secret_payload(api_key_ref) if api_key_ref else None
        has_cred = bool(
            kind == "ollama"
            and pid in configured
            or (payload and (payload.get("access_token") or payload.get("api_key")))
        )
        rows.append(
            {
                "id": pid,
                "label": str(entry.get("label") or preset.get("label") or pid),
                "kind": kind,
                "auth_mode": str(preset.get("auth_mode") or "api_key"),
                "base_url": str(entry.get("base_url") or preset.get("base_url") or ""),
                "default_model": str(entry.get("default_model") or ""),
                "enabled": bool(entry.get("enabled", True)) if pid in configured else False,
                "connected": has_cred and bool(entry.get("enabled", True)),
                "account_hint": str(payload.get("account_email") or "") if payload else "",
            }
        )
    return rows
