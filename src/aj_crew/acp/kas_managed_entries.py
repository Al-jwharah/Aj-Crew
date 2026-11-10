"""Resolve the managed invocation of each Crew server the active KAS agent declares.

Split out of :mod:`aj_crew.acp.kas_agents` for its line cap; that module keeps
the import path (``kas_agents.resolve_managed_entries``).
"""

from __future__ import annotations

from typing import Any

from aj_crew.mcp_cleanup import AJCREW_BIN_MCP_SERVERS

_MANAGED_MCP_SERVER_NAMES = frozenset(AJCREW_BIN_MCP_SERVERS)


def resolve_managed_entries(
    custom_agents: list[dict[str, Any]] | None,
    agent_id: str,
) -> dict[str, Any]:
    """The managed invocation for each managed server the ACTIVE agent declares.

    Blocking: :func:`~aj_crew.agent.managed_mcp_spec_entry` resolves the
    ``ajcrew`` launcher with filesystem and ``PATH`` probes. Call it off the
    event loop and hand the result to
    :func:`~aj_crew.acp.kas_agents.hoist_servers_for_session`, which then stays
    free of I/O. A name whose invocation does not resolve maps to ``None``, the
    same answer the in-place lookup gives.
    """
    from aj_crew.agent import managed_mcp_spec_entry

    names: set[str] = set()
    for descriptor in custom_agents or ():
        if not isinstance(descriptor, dict) or descriptor.get("id") != agent_id:
            continue
        declared = descriptor.get("mcpServers")
        if isinstance(declared, dict):
            names.update(name for name in declared if name in _MANAGED_MCP_SERVER_NAMES)
    return {name: managed_mcp_spec_entry(name, include_opt_in=True) for name in sorted(names)}
