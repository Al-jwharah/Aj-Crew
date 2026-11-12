"""The declared ``Tool.title`` table matches what each own MCP server lists."""

from __future__ import annotations

import pytest

from aj_crew import mcp_core, mcp_cron, mcp_dashboard
from aj_crew.mcp_tool_titles import _table, declared_tool_title, with_titles

_SERVERS = {
    "ajcrew-core": mcp_core,
    "ajcrew-dashboard": mcp_dashboard,
    "ajcrew-cron": mcp_cron,
}


def _install_builtins_that_declare_agent_tools() -> None:
    """Write each shipped built-in that declares manifest ``agentTools`` into the test home.

    ``ajcrew-core`` lists such a tool only for a first-party app: one whose installed
    slot the builtin owns. A real gateway registers every built-in at boot; the isolated
    test home has none.
    """
    import json

    from aj_crew.apps import manager
    from aj_crew.apps.discovery import discover_builtin_apps

    for app in discover_builtin_apps():
        if app.get("agentTools"):
            root = manager.app_dir(app["name"])
            root.mkdir(parents=True, exist_ok=True)
            (root / "app.json").write_text(json.dumps(app), encoding="utf-8")
            (root / manager.INSTALLED_META_FILENAME).write_text(
                json.dumps({"name": app["name"], "enabled": True, "source": "builtin"}),
                encoding="utf-8",
            )


@pytest.mark.parametrize("server", sorted(_SERVERS))
def test_every_listed_tool_carries_its_declared_title(server: str, monkeypatch) -> None:
    # The title table covers every DECLARED tool. ``ajcrew-core`` lists an app's
    # tools only while that app is enabled, and the isolated test home has
    # none installed, so the gate is held open here to compare the whole table.
    from aj_crew.mcp_tools import app_tools
    from aj_crew.mcp_tools import code_channels as code_channel_tools

    _install_builtins_that_declare_agent_tools()
    monkeypatch.setattr(app_tools, "app_enabled_state", lambda _name: True)
    # Likewise the code-channel tools, listed only while slack.code_channels is on.
    monkeypatch.setattr(code_channel_tools, "_toggle_on", lambda: True)
    listed = _SERVERS[server]._list_tools()
    assert {t["name"]: t.get("title") for t in listed} == _table()[server]


def test_table_names_only_the_three_own_servers() -> None:
    assert set(_table()) == set(_SERVERS)


def test_titles_are_short_single_line_copy() -> None:
    for server, titles in _table().items():
        for tool, title in titles.items():
            assert title.strip() == title and "\n" not in title, (server, tool)
            assert 0 < len(title) <= 40, (server, tool)


def test_lookup_is_keyed_by_server() -> None:
    assert declared_tool_title("ajcrew-core", "spawn_run") == "Start sub-agent"
    assert declared_tool_title("other-mcp", "spawn_run") == ""
    assert declared_tool_title("ajcrew-core", "no_such_tool") == ""


def test_with_titles_copies_and_keeps_a_title_the_descriptor_already_has() -> None:
    own = {"name": "spawn_run", "title": "Custom"}
    bare = {"name": "spawn_run"}
    out = with_titles("ajcrew-core", [own, bare])
    assert out == [own, {"name": "spawn_run", "title": "Start sub-agent"}]
    assert "title" not in bare
