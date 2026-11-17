"""Aj Crew's own built-in Python ACP engine harness (``ACP_BACKEND_NATIVE``).

Subclasses :class:`~aj_crew.acp.harness.kas.KasHarness` because the session-level
projection (``_meta.kiro.customAgents``, ``mcpServers``, ``excludedTools``,
``disabledTools``, ``permissions``, ``mate_worker`` specs, ``member_dispatch``,
and ``crew_panel``) is identical, while the spawn needs neither ``kiro-cli``,
Node, nor a Kiro OIDC account: it launches ``python -m aj_crew.acp.native_engine``
and delivers resolved provider secrets via a one-time ``0600`` scratch file.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from typing import Any

from aj_crew.acp.harness._common import defer_mandatory_mcps_env
from aj_crew.acp.harness.base import SpawnContext, SpawnPlan, TeardownPolicy
from aj_crew.acp.harness.kas import KasHarness
from aj_crew.acp.harness.strands_keys import write_keys_file
from aj_crew.acp.types import ACP_BACKEND_NATIVE, METHOD_SESSION_CLOSE

logger = logging.getLogger(__name__)

NATIVE_SPAWN_LABEL = "native-engine"
NATIVE_KEYS_FILE_ENV = "AJCREW_NATIVE_KEYS_FILE"


def _resolve_native_python() -> str:
    """Return the Python interpreter used to launch ``aj_crew.acp.native_engine``."""
    return sys.executable


class NativeHarness(KasHarness):
    """Host strategy for Aj Crew's built-in Python ACP engine."""

    backend = ACP_BACKEND_NATIVE
    agent_prompt_notice = ""
    agent_prompt_applied = True

    async def resolve_spawn(self, ctx: SpawnContext) -> SpawnPlan:
        """Build SpawnPlan for ``python -m aj_crew.acp.native_engine``."""
        self.spawn_sandbox_mode = ctx.sandbox_mode
        self.agent_prompt_notice = ""
        self.agent_prompt_applied = True
        python_bin = _resolve_native_python()
        return SpawnPlan(
            argv=[python_bin, "-m", "aj_crew.acp.native_engine"],
            spawn_label=NATIVE_SPAWN_LABEL,
            stderr_label=NATIVE_SPAWN_LABEL,
            host_auth=False,
        )

    def apply_spawn_env(
        self,
        env: dict[str, str],
        *,
        spawned_binary: str | None = None,
        cli_owned_auth: bool = False,
    ) -> None:
        """Strip Kiro CLI keys and write one-time ``0600`` native provider credentials."""
        from aj_crew.config.loader import strip_kiro_cli_api_key
        from aj_crew.subscriptions.store import resolve_all_native_provider_credentials

        strip_kiro_cli_api_key(env)
        defer_mandatory_mcps_env(env)

        scratch = env.get("AJCREW_SCRATCH") or env.get("TMPDIR") or ""
        if scratch and scratch != "<scratch>" and os.path.isdir(scratch):
            try:
                bundle = resolve_all_native_provider_credentials()
                if bundle:
                    keys_path = write_keys_file(
                        scratch,
                        {
                            pid: (
                                str(val)
                                if not isinstance(val, dict)
                                else __import__("json").dumps(val)
                            )
                            for pid, val in bundle.items()
                        },
                    )
                    env[NATIVE_KEYS_FILE_ENV] = keys_path
            except Exception:
                logger.warning("Could not write native provider keys file", exc_info=True)

    @property
    def teardown(self) -> TeardownPolicy:
        """Evict the in-memory session while keeping its persisted JSON record."""
        return TeardownPolicy(method=METHOD_SESSION_CLOSE, notification=False)

    def release(self, agent_capabilities: Mapping[str, Any] | None) -> TeardownPolicy | None:
        """Evict via ``session/close``."""
        return TeardownPolicy(method=METHOD_SESSION_CLOSE, notification=False)
