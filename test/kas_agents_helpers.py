"""Shared support for the KAS agent projection tests.

Holds ``_spec``, the agent spec builder (one stock spec plus keyword overrides)
that ``test_kas_agents.py`` and ``test_kas_agents_mcp_servers.py`` both import.
"""

from __future__ import annotations


def _spec(**over):
    base = {
        "name": "ajcrew",
        "description": "the crew agent",
        "prompt": "You are Kiro.",
        "tools": ["fs_read", "fs_write", "@ajcrew-core"],
        "mcpServers": {"ajcrew-core": {"command": "x"}},
        "model": "auto",
        "includeMcpJson": False,
    }
    base.update(over)
    return base
