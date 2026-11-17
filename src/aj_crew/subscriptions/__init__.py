"""Direct model providers, subscription bridges, and live model discovery."""

from __future__ import annotations

from aj_crew.subscriptions.discovery import (
    DiscoveredModel,
    clear_models_cache,
    discover_all_models,
    discover_provider_models,
    get_cached_or_discover_models,
)
from aj_crew.subscriptions.flows import (
    begin_subscription_connect,
    complete_pasted_connect,
    disconnect_provider,
    handle_loopback_oauth_callback,
    render_perplexity_connect_page,
    save_direct_provider,
)
from aj_crew.subscriptions.store import (
    PROVIDER_PRESETS,
    active_native_providers,
    has_active_native_provider,
    load_provider_secret_payload,
    resolve_all_native_provider_credentials,
    save_provider_secret_payload,
    subscription_status_rows,
)

__all__ = [
    "DiscoveredModel",
    "PROVIDER_PRESETS",
    "active_native_providers",
    "begin_subscription_connect",
    "clear_models_cache",
    "complete_pasted_connect",
    "disconnect_provider",
    "discover_all_models",
    "discover_provider_models",
    "get_cached_or_discover_models",
    "handle_loopback_oauth_callback",
    "has_active_native_provider",
    "load_provider_secret_payload",
    "render_perplexity_connect_page",
    "resolve_all_native_provider_credentials",
    "save_direct_provider",
    "save_provider_secret_payload",
    "subscription_status_rows",
]
