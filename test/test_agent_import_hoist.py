"""Module-scope ``aj_crew.agent`` imports stay at module scope.

The four modules below import ``from aj_crew.agent import ...`` at module
scope. ``aj_crew.agent`` imports nothing from ``aj_crew.dashboard.*`` or
``aj_crew.session``, so no import cycle exists; these tests keep the imports
at module scope and prove no cycle exists in either load order.

Order-dependent cycles only surface in a fresh interpreter, not under a
bare import in an already-warm test process — hence the subprocess runs.
"""

import re
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"

_HOISTED_MODULES = (
    "aj_crew.dashboard.handlers.agents",
    "aj_crew.dashboard.handlers.mcp",
    "aj_crew.dashboard.handlers.hooks",
    "aj_crew.session",
)

_HOISTED_FILES = (
    "aj_crew/dashboard/handlers/agents.py",
    "aj_crew/dashboard/handlers/mcp.py",
    "aj_crew/dashboard/handlers/mcp_agent_sync.py",
    "aj_crew/dashboard/handlers/mcp_config_entries.py",
    "aj_crew/dashboard/handlers/mcp_config_files.py",
    "aj_crew/dashboard/handlers/mcp_config_purge.py",
    "aj_crew/dashboard/handlers/mcp_gateway_routes.py",
    "aj_crew/dashboard/handlers/mcp_gateway_stubs.py",
    "aj_crew/dashboard/handlers/mcp_probe.py",
    "aj_crew/dashboard/handlers/hooks.py",
    "aj_crew/dashboard/handlers/hooks_scripts.py",
    "aj_crew/dashboard/handlers/hooks_webhook_intake.py",
    "aj_crew/dashboard/handlers/hooks_webhooks.py",
    "aj_crew/session.py",
    "aj_crew/session_parts/claims.py",
    "aj_crew/session_parts/config_apply.py",
    "aj_crew/session_parts/links.py",
    "aj_crew/session_parts/policy.py",
    "aj_crew/session_parts/provider_probes.py",
    "aj_crew/session_parts/record.py",
    "aj_crew/session_parts/runtimes.py",
    "aj_crew/session_parts/state_views.py",
    "aj_crew/session_parts/sweeps.py",
    "aj_crew/session_parts/teardown.py",
    "aj_crew/session_parts/turn_context.py",
)


#: ``handlers/agents.py`` runs the functions its ``dashboard/agent_admin`` owners
#: define on its own globals, so the ratchet reads those owners as part of it.
_COMPOSED_OWNERS = {
    "aj_crew/dashboard/handlers/agents.py": "aj_crew/dashboard/agent_admin",
}


def _hoisted_text(rel: str) -> str:
    """*rel*'s source, followed by the owner modules it composes."""
    text = (_SRC / rel).read_text(encoding="utf-8")
    owner_dir = _COMPOSED_OWNERS.get(rel)
    if owner_dir is None:
        return text
    owners = sorted((_SRC / owner_dir).glob("[!_]*.py"))
    assert len(owners) >= 13, f"{owner_dir}: the composed owners were not found"
    return "\n".join([text, *(owner.read_text(encoding="utf-8") for owner in owners)])


def _fresh_import(statements: str) -> None:
    """Run import statements in a fresh child interpreter; fail on any error."""
    res = subprocess.run(
        [sys.executable, "-c", statements],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert res.returncode == 0, (
        f"fresh-interpreter import failed (a hoisted import created a cycle?):\n" f"{res.stderr}"
    )


def test_hoisted_modules_import_together_fresh() -> None:
    """All four hoisted modules import together in a cold interpreter."""
    _fresh_import("; ".join(f"import {m}" for m in _HOISTED_MODULES))


def test_hoisted_modules_import_agent_first_fresh() -> None:
    """Loading aj_crew.agent BEFORE the handlers must also be cycle-free.

    A cycle between ``agent`` and these modules would be order-dependent:
    it can pass in one load order and raise ImportError in the other.
    """
    _fresh_import("; ".join(["import aj_crew.agent"] + [f"import {m}" for m in _HOISTED_MODULES]))


def test_no_function_local_agent_imports_remain() -> None:
    """Ratchet: no function-local ``from aj_crew.agent import`` in the four files.

    Covers all three spellings; ``from aj_crew import agent`` matches the bare
    ``agent`` name so ``agent_state`` does not trip it. Comments are excluded.
    """
    local_import = re.compile(
        r"^[ \t]+(?:"
        r"from aj_crew\.agent import"
        r"|import aj_crew\.agent\b"
        r"|from aj_crew import [^#\n]*\bagent\b"
        r")",
        re.MULTILINE,
    )
    offenders = {}
    for rel in _HOISTED_FILES:
        text = _hoisted_text(rel)
        hits = local_import.findall(text)
        if hits:
            offenders[rel] = len(hits)
    assert not offenders, (
        f"function-local aj_crew.agent imports reintroduced: {offenders}; "
        f"import at module scope instead (no cycle exists — see issue #1050)"
    )


def test_members_and_artifacts_import_first_fresh() -> None:
    """``aj_crew.members`` loads when the first ``aj_crew`` import reaches ``artifacts``.

    ``artifacts`` -> ``hooks`` -> ``webhooks`` -> ``validation``, so ``validation``
    must read its content cap from the ``constants`` leaf, not ``artifacts``.
    """
    _fresh_import("import aj_crew.members; import aj_crew.artifacts")
    _fresh_import("import aj_crew.artifacts; import aj_crew.members")


def test_validation_is_a_leaf_that_never_imports_artifacts() -> None:
    """The closing edge stays deleted: loading ``validation`` must not pull
    ``artifacts`` in, or the cycle above is one hoisted import from returning."""
    _fresh_import(
        "import sys; import aj_crew.validation; "
        "assert 'aj_crew.artifacts' not in sys.modules, 'validation imports artifacts'"
    )
