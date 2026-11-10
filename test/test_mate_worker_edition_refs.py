# SPDX-License-Identifier: Apache-2.0
"""The worker base exposes the tools of every edition server it mounts.

``build_agent_config`` adds each ``McpToolingProvider.extra_mcp_servers()`` entry
to ``mcpServers`` only; the default spec gains the matching ``@<server>`` refs in
a later step that the worker base never ran. kiro-cli exposes only servers named
in ``tools``, so a worker mounted the edition's servers and saw none of their
tools. The base now references each one, in ``tools`` and never in
``allowedTools``.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import aj_crew.config.paths as paths_mod
from aj_crew import agent
from aj_crew.agent_files import MATE_WORKER_AGENT_FILENAME
from aj_crew.agent_materialization import service_agents
from aj_crew.config.loader import AjCrewConfig
from aj_crew.platform import build_default_context, set_context
from aj_crew.platform.context import reset_context

EDITION_SERVERS = {
    "edition-tools": {"command": "edition-tools", "args": ["--stdio"]},
    "edition-creds": {"command": "/opt/edition/creds", "args": []},
}


class _EditionTooling:
    def extra_mcp_servers(self):
        return {name: dict(spec) for name, spec in EDITION_SERVERS.items()}

    def extra_skills(self):
        return []


@pytest.fixture
def mates(tmp_path, monkeypatch):
    kiro = tmp_path / "kiro"
    user = kiro / "agents"
    user.mkdir(parents=True)
    monkeypatch.setattr(paths_mod, "kiro_home", lambda: kiro)
    monkeypatch.setattr(paths_mod, "kiro_agents_dir", lambda: user)
    monkeypatch.setattr(agent, "kiro_agents_dir_path", lambda: user)
    return kiro / "mates" / "agents"


@pytest.fixture
def edition():
    base = build_default_context(AjCrewConfig())
    set_context(dataclasses.replace(base, mcp_tooling=_EditionTooling()))
    yield
    reset_context()


def _worker(mates) -> dict:
    service_agents._install_mate_worker_agent()
    return json.loads((mates / MATE_WORKER_AGENT_FILENAME).read_text(encoding="utf-8"))


def test_the_worker_base_references_every_edition_server_it_mounts(mates, edition):
    spec = _worker(mates)
    for name in EDITION_SERVERS:
        assert name in spec["mcpServers"]
        assert spec["tools"].count(f"@{name}") == 1


def test_the_refs_expose_the_tools_without_approving_them(mates, edition):
    allowed = _worker(mates).get("allowedTools") or []
    for name in EDITION_SERVERS:
        assert not any(t == f"@{name}" or t.startswith(f"@{name}/") for t in allowed)


def test_the_core_refs_are_kept(mates, edition):
    tools = _worker(mates)["tools"]
    assert "@ajcrew-core" in tools
    assert "@ajcrew-work" in tools


def test_a_server_the_base_does_not_mount_gets_no_ref():
    config = {"mcpServers": {"edition-tools": {}}, "tools": ["@ajcrew-core"]}
    base = build_default_context(AjCrewConfig())
    set_context(dataclasses.replace(base, mcp_tooling=_EditionTooling()))
    try:
        service_agents._register_edition_refs(config)
    finally:
        reset_context()
    assert config["tools"] == ["@ajcrew-core", "@edition-tools"]


def test_a_standalone_build_adds_no_ref():
    set_context(build_default_context(AjCrewConfig()))
    config = {"mcpServers": {"edition-tools": {}}, "tools": ["@ajcrew-core"]}
    try:
        service_agents._register_edition_refs(config)
    finally:
        reset_context()
    assert config["tools"] == ["@ajcrew-core"]


@pytest.mark.parametrize("tooling", [_EditionTooling(), None], ids=["edition", "standalone"])
def test_a_scalar_wildcard_is_kept_as_every_tool(tooling):
    """An operator's ``"tools": "*"`` still exposes every tool; it never becomes ``[]``."""
    base = build_default_context(AjCrewConfig())
    set_context(base if tooling is None else dataclasses.replace(base, mcp_tooling=tooling))
    config = {"mcpServers": {"edition-tools": {}}, "tools": "*"}
    try:
        service_agents._register_edition_refs(config)
    finally:
        reset_context()
    assert config["tools"] == ["*"]


def test_a_full_rebuild_and_a_member_cron_s_worker_keep_the_edition_refs(
    tmp_path, monkeypatch, edition
):
    """End to end: the start's own ``rebuild_agent_config``, then a Bot's cron worker session."""
    from aj_crew import mate_worker
    from aj_crew.agent_files import AGENT_FILENAME
    from aj_crew.execution_context import ExecutionContext, MemoryStoreRef
    from aj_crew.kiro_cli import SPEC_PERMISSIONS_MIN_VERSION
    from aj_crew.mate_worker import MATE_WORKER_AGENT

    monkeypatch.setattr(paths_mod, "_resolve_default_home", lambda: tmp_path / "default")
    user = tmp_path / "home" / "agents"
    mates = tmp_path / "home" / "mates" / "agents"
    user.mkdir(parents=True)
    mates.mkdir(parents=True)
    monkeypatch.setattr(agent, "kiro_agents_dir_path", lambda: user)
    monkeypatch.setattr(paths_mod, "mate_agents_dir", lambda: mates)
    monkeypatch.setattr(agent, "KIRO_AGENTS_DIR", user)
    monkeypatch.setattr(
        "aj_crew.kiro_cli.installed_kiro_cli_version", lambda: SPEC_PERMISSIONS_MIN_VERSION
    )
    launcher = tmp_path / "bin" / "ajcrew"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setattr(agent, "_AJCREW_BIN", str(launcher))
    monkeypatch.setattr(agent, "_KIRO_MCP_JSON", tmp_path / "kiro-global-mcp.json")
    monkeypatch.setattr(agent, "_DEFAULT_KIRO_HOOKS_DIR", tmp_path / "hooks")
    monkeypatch.setattr("aj_crew.apps.bridges._mcp_json_path", lambda: user / AGENT_FILENAME)

    agent.rebuild_agent_config()

    on_disk = json.loads((mates / MATE_WORKER_AGENT_FILENAME).read_text(encoding="utf-8"))
    for name in EDITION_SERVERS:
        assert on_disk["tools"].count(f"@{name}") == 1

    own = {"name": "alpha", "prompt": "", "tools": ["@notes"]}
    own["mcpServers"] = {"notes": {"command": "notes-mcp"}}
    (mates / "alpha.json").write_text(json.dumps(own), encoding="utf-8")
    monkeypatch.setattr(mate_worker, "mate_file_for_member", lambda member, config=None: member)
    monkeypatch.setattr(mate_worker, "globally_disabled_refs", lambda names: [])
    store = MemoryStoreRef("member-alpha", "alpha")
    worker = mate_worker.cron_worker_execution(
        ExecutionContext("alpha", store, "member", "ajcrew")
    )
    assert worker is not None and worker.template_id == MATE_WORKER_AGENT
    monkeypatch.setattr(
        "aj_crew.execution_context.read_session_execution",
        lambda key: worker if key == "cron:hourly" else None,
    )
    spec = mate_worker.worker_session_spec(dict(on_disk), "cron:hourly")
    for name in EDITION_SERVERS:
        assert f"@{name}" in spec["tools"] and name in spec["mcpServers"]
    assert "@notes" in spec["tools"]
