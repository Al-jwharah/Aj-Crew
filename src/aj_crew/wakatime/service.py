"""Resolve WakaTime config + secret into a ready client.

The API key is read only from the encrypted vault. There is deliberately no
``.env``/environment fallback: a key placed in ``.env`` is loaded by the
gateway into the process environment, and the agent-spawn scrub strips only the
credential names it knows, so an unknown key can reach an agent subprocess and
be exfiltrated. Vault-only keeps the key off that path entirely.

The base URL comes from ``config.wakatime.api_base_url`` (empty = the public
WakaTime API), so a self-hosted Wakapi/Hackatime backend is a config change,
not a code change.
"""

from __future__ import annotations

import logging

from aj_crew.config.loader import CRED_WAKATIME_API_KEY, AjCrewConfig
from aj_crew.config.paths import config_dir
from aj_crew.secrets.vault import SecretVault
from aj_crew.wakatime.client import DEFAULT_API_BASE, WakaTimeClient

logger = logging.getLogger(__name__)


def resolve_api_key() -> str:
    """Return the WakaTime API key from the vault, or ``""`` if not set.

    Best-effort: a missing or unreadable vault yields ``""`` (integration stays
    off) rather than raising.
    """
    try:
        secret = SecretVault(config_dir()).get(CRED_WAKATIME_API_KEY)
    except Exception:
        return ""
    return secret.reveal() if secret is not None else ""


def resolve_base_url(config: AjCrewConfig | None = None) -> str:
    """Return the configured API base URL, or the public default."""
    cfg = config or AjCrewConfig.load()
    configured = (cfg.wakatime.api_base_url or "").strip()
    return configured or DEFAULT_API_BASE


def build_client(config: AjCrewConfig | None = None) -> WakaTimeClient | None:
    """Build a ready WakaTimeClient, or ``None`` when the integration is
    disabled or has no API key.

    Returning ``None`` (rather than raising) lets callers treat "not set up" as
    an ordinary empty state instead of an error path.
    """
    cfg = config or AjCrewConfig.load()
    if not cfg.wakatime.enabled:
        return None
    api_key = resolve_api_key()
    if not api_key:
        return None
    return WakaTimeClient(api_key=api_key, api_base=resolve_base_url(cfg))
