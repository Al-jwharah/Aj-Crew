"""100% dynamic live model discovery across connected subscriptions and direct APIs."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from aj_crew.subscriptions.flows import refresh_oauth_payload_if_needed
from aj_crew.subscriptions.store import active_native_providers

logger = logging.getLogger(__name__)

_CACHE_TTL_SECS = 300.0


@dataclass(frozen=True)
class DiscoveredModel:
    """One live-discovered model and its wire-normalization capability profile."""

    id: str
    raw_model: str
    name: str
    provider: str
    protocol: str
    context_window: int = 128000
    supports_tools: bool = True
    supports_temperature: bool = True
    supports_reasoning_effort: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "context_window": self.context_window,
            "supports_tools": self.supports_tools,
            "supports_temperature": self.supports_temperature,
            "supports_effort": self.supports_reasoning_effort,
        }


_DISCOVERY_CACHE: dict[str, tuple[float, list[DiscoveredModel]]] = {}


def clear_models_cache(provider_id: str | None = None) -> None:
    """Drop cached live discovery entries (one provider or all)."""
    if provider_id is None:
        _DISCOVERY_CACHE.clear()
    else:
        _DISCOVERY_CACHE.pop(provider_id, None)


def _infer_capabilities(raw_id: str, kind: str, meta: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Infer (supports_tools, supports_temperature, supports_reasoning_effort) from live metadata."""
    lower = raw_id.lower()
    is_reasoning = bool(
        meta.get("reasoning")
        or "reason" in lower
        or "thinking" in lower
        or lower.startswith(("o1", "o3", "o4"))
        or "deep-research" in lower
    )
    if kind == "perplexity":
        has_tools = "sonar" in lower and "deep-research" not in lower and "reason" not in lower
        has_temp = not is_reasoning
        return has_tools, has_temp, is_reasoning
    has_temp = not (lower.startswith(("o1", "o3", "o4")) or meta.get("rejects_temperature") is True)
    return True, has_temp, is_reasoning


async def _discover_openai_or_chatgpt(
    provider_id: str,
    info: dict[str, Any],
    token: str,
) -> list[DiscoveredModel]:
    base_url = str(info["base_url"]).rstrip("/")
    kind = str(info["kind"])
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    urls = [f"{base_url}/models"]
    if kind == "chatgpt_oauth":
        urls.insert(0, "https://chatgpt.com/backend-api/models")

    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in urls:
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status >= 400:
                        continue
                    data = await resp.json(content_type=None)
            except Exception:
                continue
            items: list[Any] = []
            if isinstance(data, dict):
                items = data.get("data") or data.get("models") or []
            elif isinstance(data, list):
                items = data
            out: list[DiscoveredModel] = []
            for row in items:
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("id") or row.get("slug") or row.get("name") or "").strip()
                if not mid or any(
                    skip in mid.lower()
                    for skip in ("embedding", "whisper", "tts", "moderation", "dall-e")
                ):
                    continue
                ctx_win = int(
                    row.get("context_length")
                    or row.get("max_tokens")
                    or row.get("context_window")
                    or 128000
                )
                tools_ok, temp_ok, effort_ok = _infer_capabilities(mid, kind, row)
                display = str(row.get("title") or row.get("name") or mid)
                out.append(
                    DiscoveredModel(
                        id=f"{provider_id}/{mid}",
                        raw_model=mid,
                        name=f"{info['label']}: {display}",
                        provider=provider_id,
                        protocol="openai_compat",
                        context_window=ctx_win,
                        supports_tools=tools_ok,
                        supports_temperature=temp_ok,
                        supports_reasoning_effort=effort_ok,
                    )
                )
            if out:
                return out
    return []


async def _discover_gemini(
    provider_id: str,
    info: dict[str, Any],
    creds: dict[str, Any],
) -> list[DiscoveredModel]:
    base_url = str(info["base_url"]).rstrip("/")
    headers: dict[str, str] = {"Accept": "application/json"}
    params: dict[str, str] = {}
    if creds.get("access_token"):
        headers["Authorization"] = f"Bearer {creds['access_token']}"
    elif creds.get("api_key"):
        params["key"] = str(creds["api_key"])

    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{base_url}/models", headers=headers, params=params) as resp:
            if resp.status >= 400:
                return []
            data = await resp.json(content_type=None)
    items = data.get("models") if isinstance(data, dict) else []
    out: list[DiscoveredModel] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        methods = row.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        raw_name = str(row.get("name") or "")
        mid = raw_name.removeprefix("models/").strip()
        if not mid or "embedding" in mid.lower():
            continue
        ctx_win = int(row.get("inputTokenLimit") or 1048576)
        effort_ok = bool(row.get("thinking")) or "thinking" in mid.lower() or "pro" in mid.lower()
        display = str(row.get("displayName") or mid)
        out.append(
            DiscoveredModel(
                id=f"{provider_id}/{mid}",
                raw_model=mid,
                name=f"{info['label']}: {display}",
                provider=provider_id,
                protocol="gemini",
                context_window=ctx_win,
                supports_tools=True,
                supports_temperature=True,
                supports_reasoning_effort=effort_ok,
            )
        )
    return out


async def _discover_anthropic(
    provider_id: str,
    info: dict[str, Any],
    token: str,
) -> list[DiscoveredModel]:
    base_url = str(info["base_url"]).rstrip("/")
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{base_url}/models", headers=headers) as resp:
            if resp.status >= 400:
                return []
            data = await resp.json(content_type=None)
    items = data.get("data") if isinstance(data, dict) else []
    out: list[DiscoveredModel] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if not mid:
            continue
        display = str(row.get("display_name") or mid)
        out.append(
            DiscoveredModel(
                id=f"{provider_id}/{mid}",
                raw_model=mid,
                name=f"{info['label']}: {display}",
                provider=provider_id,
                protocol="anthropic",
                context_window=200000,
                supports_tools=True,
                supports_temperature=True,
                supports_reasoning_effort=True,
            )
        )
    return out


async def _discover_perplexity(
    provider_id: str,
    info: dict[str, Any],
    token: str,
) -> list[DiscoveredModel]:
    base_url = str(info["base_url"]).rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    discovered_ids: list[tuple[str, str]] = []
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for path in ("/models", "/rest/models"):
            try:
                async with session.get(f"{base_url}{path}", headers=headers) as resp:
                    if resp.status >= 400:
                        continue
                    data = await resp.json(content_type=None)
                    rows = (
                        data.get("data") or data.get("models") if isinstance(data, dict) else data
                    )
                    if isinstance(rows, list):
                        for item in rows:
                            if isinstance(item, dict):
                                mid = str(item.get("id") or item.get("slug") or "").strip()
                                title = str(item.get("name") or item.get("label") or mid)
                                if mid:
                                    discovered_ids.append((mid, title))
                            elif isinstance(item, str) and item.strip():
                                discovered_ids.append((item.strip(), item.strip()))
            except Exception:
                continue

    # Perplexity's Sonar API does not always expose a /models list endpoint; include
    # Perplexity's documented Sonar modes alongside any live-returned account models.
    sonar_modes = [
        ("sonar", "Sonar Search"),
        ("sonar-pro", "Sonar Pro"),
        ("sonar-reasoning-pro", "Sonar Reasoning Pro"),
        ("sonar-deep-research", "Sonar Deep Research"),
    ]
    seen: set[str] = set()
    merged: list[tuple[str, str]] = []
    for mid, title in [*discovered_ids, *sonar_modes]:
        if mid not in seen:
            seen.add(mid)
            merged.append((mid, title))

    out: list[DiscoveredModel] = []
    for mid, title in merged:
        tools_ok, temp_ok, effort_ok = _infer_capabilities(mid, "perplexity", {})
        out.append(
            DiscoveredModel(
                id=f"{provider_id}/{mid}",
                raw_model=mid,
                name=f"{info['label']}: {title}",
                provider=provider_id,
                protocol="perplexity",
                context_window=128000,
                supports_tools=tools_ok,
                supports_temperature=temp_ok,
                supports_reasoning_effort=effort_ok,
            )
        )
    return out


async def discover_provider_models(provider_id: str) -> list[DiscoveredModel]:
    """Run live model discovery for one configured provider and update cache."""
    providers = await asyncio.to_thread(active_native_providers)
    info = providers.get(provider_id)
    if info is None:
        _DISCOVERY_CACHE.pop(provider_id, None)
        return []

    kind = str(info["kind"])
    api_key_ref = str(info.get("api_key_ref") or "")
    creds: dict[str, Any] = {}
    if api_key_ref:
        creds = await refresh_oauth_payload_if_needed(provider_id, api_key_ref) or {}
    token = str(creds.get("access_token") or creds.get("api_key") or "")

    try:
        if kind in ("openai_compat", "chatgpt_oauth", "ollama"):
            models = await _discover_openai_or_chatgpt(provider_id, info, token)
        elif kind == "gemini":
            models = await _discover_gemini(provider_id, info, creds)
        elif kind == "anthropic":
            models = await _discover_anthropic(provider_id, info, token)
        elif kind == "perplexity":
            models = await _discover_perplexity(provider_id, info, token)
        else:
            models = []
    except Exception:
        logger.warning("Live model discovery failed for %r", provider_id, exc_info=True)
        models = []

    default_pin = str(info.get("default_model") or "").strip()
    if default_pin and all(m.raw_model != default_pin and m.id != default_pin for m in models):
        raw = default_pin.removeprefix(f"{provider_id}/")
        tools_ok, temp_ok, effort_ok = _infer_capabilities(raw, kind, {})
        models.insert(
            0,
            DiscoveredModel(
                id=f"{provider_id}/{raw}",
                raw_model=raw,
                name=f"{info['label']}: {raw}",
                provider=provider_id,
                protocol=kind if kind in ("anthropic", "gemini", "perplexity") else "openai_compat",
                supports_tools=tools_ok,
                supports_temperature=temp_ok,
                supports_reasoning_effort=effort_ok,
            ),
        )

    _DISCOVERY_CACHE[provider_id] = (time.monotonic(), models)
    return models


async def discover_all_models(*, force: bool = False) -> list[DiscoveredModel]:
    """Discover models across all active native providers in parallel."""
    providers = await asyncio.to_thread(active_native_providers)
    now = time.monotonic()
    tasks = []
    cached_results: list[DiscoveredModel] = []
    for pid in providers:
        cached = _DISCOVERY_CACHE.get(pid)
        if not force and cached is not None and (now - cached[0]) < _CACHE_TTL_SECS:
            cached_results.extend(cached[1])
        else:
            tasks.append(discover_provider_models(pid))
    if tasks:
        fresh = await asyncio.gather(*tasks, return_exceptions=True)
        for item in fresh:
            if isinstance(item, list):
                cached_results.extend(item)
    return cached_results


async def get_cached_or_discover_models(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Return ``GET /api/models`` payload for ``ACP_BACKEND_NATIVE``."""
    discovered = await discover_all_models(force=refresh)
    rows: list[dict[str, Any]] = [
        {
            "id": "auto",
            "name": "Auto (Active Provider Default)",
            "provider": "native",
            "supports_tools": True,
            "supports_effort": True,
        }
    ]
    rows.extend(m.as_dict() for m in discovered)
    return rows
