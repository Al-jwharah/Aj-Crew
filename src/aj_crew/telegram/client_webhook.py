"""Telegram Bot API webhook registration, verification, and replay deduplication.

Optional self-authenticating webhook transport alongside the default ``getUpdates``
long-polling mode:

* :func:`validate_webhook_url` enforces ``https://`` (no plaintext, no embedded
  credentials, no fragment, no whitespace).
* :func:`validate_webhook_secret` enforces 16-256 characters of Telegram's
  ``[A-Za-z0-9_-]`` ``secret_token`` alphabet so weak/empty secrets are refused.
* :func:`verify_telegram_webhook_secret` compares ``X-Telegram-Bot-Api-Secret-Token``
  in constant time via :func:`hmac.compare_digest` and fails closed when no valid
  expected secret is configured.
* :func:`record_webhook_update_id` suppresses duplicate ``update_id`` deliveries
  within a bounded ``OrderedDict`` window.
* :func:`set_telegram_webhook` / :func:`delete_telegram_webhook` call ``setWebhook``
  and ``deleteWebhook`` through the client's validated ``_call_raw`` round trip.
"""

from __future__ import annotations

import hmac
import logging
import re
import urllib.parse
from collections import OrderedDict
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from aj_crew.telegram.client import TelegramClient

logger = logging.getLogger("aj_crew.telegram.client")

#: Header Telegram attaches to every webhook delivery when ``secret_token`` is set.
TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

#: Bounded inbound webhook JSON body size (1 MiB).
TELEGRAM_MAX_WEBHOOK_BYTES = 1024 * 1024

#: Request stash key so the route reads the body once under its byte cap.
TELEGRAM_WEBHOOK_REQUEST_KEY = "aj_crew.telegram.webhook_body"

#: Maximum recent ``update_id``s retained in memory for duplicate suppression.
TELEGRAM_WEBHOOK_DEDUP_CAP = 4096

#: Telegram allows 1-256 chars of ``[A-Za-z0-9_-]``; require >= 16 chars fail-closed.
MIN_WEBHOOK_SECRET_LEN = 16
MAX_WEBHOOK_SECRET_LEN = 256
WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")

#: Update kinds Aj Crew's Telegram dispatcher handles.
DEFAULT_ALLOWED_UPDATES: tuple[str, ...] = ("message", "callback_query")


def validate_webhook_url(url: str) -> str | None:
    """Return ``None`` when *url* is a valid ``https://`` webhook endpoint, else reason."""
    if not isinstance(url, str):
        return "webhook_url must be a string"
    cleaned = url.strip()
    if not cleaned:
        return "webhook_url is required when mode is 'webhook'"
    if any(ch.isspace() for ch in cleaned):
        return "webhook_url must not contain whitespace"
    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except ValueError:
        return "webhook_url is not a valid URL"
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return "webhook_url must use https:// with a valid hostname"
    if parsed.username or parsed.password:
        return "webhook_url must not embed credentials"
    if parsed.fragment:
        return "webhook_url must not include a URL fragment"
    return None


def validate_webhook_secret(secret: str) -> str | None:
    """Return ``None`` when *secret* meets the 16-256 ``[A-Za-z0-9_-]`` contract."""
    if not isinstance(secret, str):
        return "webhook_secret must be a string"
    cleaned = secret.strip()
    if not cleaned:
        return "webhook_secret is required when mode is 'webhook'"
    if len(cleaned) < MIN_WEBHOOK_SECRET_LEN or len(cleaned) > MAX_WEBHOOK_SECRET_LEN:
        return (
            f"webhook_secret must be {MIN_WEBHOOK_SECRET_LEN}-{MAX_WEBHOOK_SECRET_LEN} "
            "characters"
        )
    if not WEBHOOK_SECRET_RE.fullmatch(cleaned):
        return "webhook_secret may contain only letters, digits, '-' and '_'"
    return None


def verify_telegram_webhook_secret(header_value: str | None, expected_secret: str | None) -> bool:
    """Constant-time verification of ``X-Telegram-Bot-Api-Secret-Token`` (fail closed)."""
    if not isinstance(expected_secret, str) or validate_webhook_secret(expected_secret) is not None:
        return False
    if not isinstance(header_value, str) or not header_value:
        return False
    if len(header_value) > MAX_WEBHOOK_SECRET_LEN:
        return False
    return hmac.compare_digest(
        header_value.encode("utf-8"),
        expected_secret.strip().encode("utf-8"),
    )


def record_webhook_update_id(
    seen: "OrderedDict[int, None]",
    update_id: int,
    *,
    cap: int = TELEGRAM_WEBHOOK_DEDUP_CAP,
) -> bool:
    """Record *update_id* and return ``True`` if fresh, ``False`` if a duplicate replay."""
    if update_id <= 0:
        return False
    if update_id in seen:
        seen.move_to_end(update_id)
        return False
    seen[update_id] = None
    while len(seen) > max(1, cap):
        seen.popitem(last=False)
    return True


async def set_telegram_webhook(
    client: "TelegramClient",
    *,
    url: str,
    secret_token: str,
    allowed_updates: Sequence[str] = DEFAULT_ALLOWED_UPDATES,
) -> bool:
    """Register *url* and *secret_token* with Telegram's ``setWebhook`` method."""
    url_err = validate_webhook_url(url)
    if url_err is not None:
        raise ValueError(url_err)
    sec_err = validate_webhook_secret(secret_token)
    if sec_err is not None:
        raise ValueError(sec_err)
    data = await client._call_raw(
        "setWebhook",
        {
            "url": url.strip(),
            "secret_token": secret_token.strip(),
            "allowed_updates": list(allowed_updates),
        },
    )
    if isinstance(data, dict) and data.get("ok"):
        return True
    desc = (
        str(data.get("description", "") or "rejected")[:80]
        if isinstance(data, dict)
        else "rejected"
    )
    logger.warning("Telegram setWebhook rejected (%s)", desc)
    return False


async def delete_telegram_webhook(
    client: "TelegramClient",
    *,
    drop_pending_updates: bool = False,
) -> bool:
    """Remove an active webhook registration via Telegram's ``deleteWebhook`` method."""
    data = await client._call_raw(
        "deleteWebhook",
        {"drop_pending_updates": bool(drop_pending_updates)},
    )
    return bool(isinstance(data, dict) and data.get("ok"))
