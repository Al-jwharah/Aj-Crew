# SPDX-License-Identifier: Apache-2.0
"""A legacy built-in binding is listed once its DM thread holds a message.

A legacy binding is ``source: builtin`` with no ``member_id`` (an older
install's ``assistant``, the built-in ``ajcrew-conductor``). It follows the
rule every non-dashboard-created row follows: ``GET /api/members`` ships it with
``dashboard_created`` false and lets ``has_dm_message`` decide, and
``GET /api/agents`` (the crewmate pickers) lists it only when that thread holds a
message. The reserved ``default`` member and a dashboard-created crewmate are
listed either way.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from chat_test_helpers import _make_state

from aj_crew.config.loader import AjCrewAgentConfig
from aj_crew.mate_worker import is_legacy_binding

#: Legacy bindings whose DM thread holds a message.
CHATTED = ("helper", "ajcrew-conductor")
#: Legacy bindings with no thread, or a thread holding only metadata.
UNCHATTED = ("ajcrew-worker", "opened")


def _fake_config():
    builtin = {"source": "builtin", "member_id": ""}
    return SimpleNamespace(
        agents={
            "default": AjCrewAgentConfig(kiro_agent="ajcrew", source="builtin"),
            "ada": AjCrewAgentConfig(kiro_agent="ada", source="ajcrew", member_id="m-ada"),
            "helper": AjCrewAgentConfig(kiro_agent="ajcrew", **builtin),
            "ajcrew-conductor": AjCrewAgentConfig(kiro_agent="ajcrew-conductor", **builtin),
            "ajcrew-worker": AjCrewAgentConfig(kiro_agent="ajcrew-worker", **builtin),
            "opened": AjCrewAgentConfig(kiro_agent="ajcrew", **builtin),
        },
        default_agent="default",
        memory_stores={},
        degraded_sections=frozenset(),
    )


@pytest.fixture(autouse=True)
def _owner_caller(_floor_monkeypatch):
    _floor_monkeypatch.setattr(
        "aj_crew.dashboard.handlers.source_providers.is_owner_dashboard_request",
        lambda request: True,
    )


@pytest.fixture
def seeded(tmp_path):
    """A state whose chatted legacy threads hold a message; ``opened`` only a title."""
    from aj_crew import members as members_mod

    fake = _fake_config()
    state = _make_state(tmp_path)
    with patch("aj_crew.config.loader.AjCrewConfig.load", return_value=fake):
        for name in (*CHATTED, "opened"):
            slug = members_mod.member_slug(name, fake)
            members_mod.write_dm_binding(slug, member=name, slot_key=f"member-{slug}")
            key = members_mod.member_thread_session_alias(slug)
            if name == "opened":
                state.conversation_log.set_title(key, "Opened")
            else:
                state.conversation_log.append(key, "user", "hello")
        yield state


def _app(state) -> web.Application:
    from aj_crew.dashboard.handlers import api_ajcrew_agents
    from aj_crew.dashboard.handlers.members import api_members

    @web.middleware
    async def _auth(request: web.Request, handler):
        request.setdefault("app", "")
        request.setdefault("user", "local-app")
        return await handler(request)

    app = web.Application(middlewares=[_auth])
    app["state"] = state
    app.router.add_get("/api/agents", api_ajcrew_agents)
    app.router.add_get("/api/members", api_members)
    return app


def test_only_a_builtin_binding_without_an_id_is_legacy():
    assert is_legacy_binding("assistant", SimpleNamespace(source="builtin", member_id=""))
    assert is_legacy_binding("ajcrew-conductor", SimpleNamespace(source="builtin", member_id=""))
    assert not is_legacy_binding("default", SimpleNamespace(source="builtin", member_id=""))
    assert not is_legacy_binding("mate", SimpleNamespace(source="builtin", member_id="mate"))
    assert not is_legacy_binding("shared-v1", SimpleNamespace(source="ajcrew", member_id=""))


@pytest.mark.asyncio
async def test_the_members_roster_lets_the_thread_decide(seeded) -> None:
    async with TestClient(TestServer(_app(seeded))) as client:
        body = await (await client.get("/api/members")).json()
    rows = {r["name"]: r for r in body["members"]}
    for name in (*CHATTED, *UNCHATTED):
        assert rows[name]["dashboard_created"] is False
    for name in CHATTED:
        assert rows[name]["has_dm_message"] is True
    for name in UNCHATTED:
        assert rows[name]["has_dm_message"] is False
    assert rows["ada"]["dashboard_created"] is True
    assert "default" in rows


@pytest.mark.asyncio
async def test_the_agents_roster_lists_a_legacy_binding_once_chatted(seeded) -> None:
    async with TestClient(TestServer(_app(seeded))) as client:
        names = {a["name"] for a in (await (await client.get("/api/agents")).json())["agents"]}
    assert set(CHATTED) <= names
    assert not set(UNCHATTED) & names
    assert {"default", "ada"} <= names


@pytest.mark.asyncio
async def test_a_live_slot_row_lists_an_unflushed_legacy_thread(seeded) -> None:
    """A message still in memory counts before it reaches the transcript."""
    from aj_crew import members as members_mod

    fake = _fake_config()
    slug = members_mod.member_slug("opened", fake)
    seeded._slots[f"member-{slug}"] = SimpleNamespace(messages=[{"role": "user"}])
    try:
        async with TestClient(TestServer(_app(seeded))) as client:
            body = await (await client.get("/api/agents")).json()
    finally:
        seeded._slots.pop(f"member-{slug}", None)
    assert "opened" in {a["name"] for a in body["agents"]}


@pytest.mark.asyncio
async def test_the_picker_catalog_offers_the_conductor_template_without_a_thread(
    tmp_path, monkeypatch
) -> None:
    """The pickers read ``GET /api/agents/catalog``, not ``GET /api/agents``.

    On a fresh install the built-in conductor has no DM binding, so the roster
    leaves its legacy binding out; the catalog still offers its installed spec
    as a template.
    """
    from aj_crew.agent_discovery import AgentInfo
    from aj_crew.dashboard.handlers import agent_catalog

    conductor = AgentInfo(
        name="ajcrew-conductor",
        filename="ajcrew-conductor.json",
        description="",
        model="",
        source="builtin",
        ajcrew_owned=True,
    )
    from aj_crew.config.loader import AjCrewConfig

    # A real config: the catalog also reads the session's harness off it.
    fake = AjCrewConfig()
    fake.agents = dict(_fake_config().agents)
    fake.default_agent = "default"
    monkeypatch.setattr(agent_catalog, "list_agents", lambda **_: [conductor])
    monkeypatch.setattr(agent_catalog, "refresh_materialized_agents", lambda **_: None)
    monkeypatch.setattr(agent_catalog.agent_state, "all_fork_info", lambda: {})
    app = _app(_make_state(tmp_path))
    app.router.add_get("/api/agents/catalog", agent_catalog.api_agent_catalog)
    with patch("aj_crew.config.loader.AjCrewConfig.load", return_value=fake):
        async with TestClient(TestServer(app)) as client:
            catalog = (await (await client.get("/api/agents/catalog")).json())["agents"]
            roster = (await (await client.get("/api/agents")).json())["agents"]
    templates = {r["name"] for r in catalog if r["selection_kind"] == "template"}
    assert "ajcrew-conductor" in templates
    assert "ajcrew-conductor" not in {r["name"] for r in roster}
