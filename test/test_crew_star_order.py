"""The per-crew ``star_order``: a starred mate's place in the left dock.

Written by dragging a dock row (PUT /api/agents/{name}), read back by
GET /api/members, ignored by everything else. These tests pin what makes it a
safe ordering key:

* it round-trips through the real config load/save,
* junk in the hand-editable config reads as 0 ("not placed"), never a crash,
* the API refuses a non-integer or out-of-range value and writes nothing,
* unstarring clears it, so a re-star lands at the bottom of the dock.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from chat_test_helpers import _make_state

from aj_crew.config.loader import AjCrewAgentConfig, AjCrewConfig
from aj_crew.config.paths import config_dir
from aj_crew.config.sections_session import STAR_ORDER_MAX


@pytest.fixture(autouse=True)
def _owner_caller(_floor_monkeypatch):
    _floor_monkeypatch.setattr(
        "aj_crew.dashboard.handlers.source_providers.is_owner_dashboard_request",
        lambda request: True,
    )


class TestConfigField:
    def test_defaults_to_not_placed(self):
        assert AjCrewAgentConfig(kiro_agent="x").star_order == 0

    def test_round_trips_through_save_and_load(self):
        cfg = AjCrewConfig.load()
        cfg.agents["placed"] = AjCrewAgentConfig(
            kiro_agent="ajcrew", starred=True, star_order=3
        )
        cfg.save()
        assert AjCrewConfig.load().agents["placed"].star_order == 3

    @pytest.mark.parametrize(
        "junk, expected",
        [
            ("x", 0),
            (True, 0),
            ([1], 0),
            (None, 0),
            (-4, 0),
            (1.5, 0),
            (STAR_ORDER_MAX + 1, STAR_ORDER_MAX),
        ],
    )
    def test_junk_in_config_is_bounded(self, junk, expected):
        """config.json is hand-editable: a bad value only moves the row."""
        cfg = AjCrewConfig.load()
        cfg.agents["weird"] = AjCrewAgentConfig(kiro_agent="ajcrew", starred=True)
        cfg.save()
        path = config_dir() / "config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["agents"]["weird"]["star_order"] = junk
        path.write_text(json.dumps(data), encoding="utf-8")
        assert AjCrewConfig.load().agents["weird"].star_order == expected


def _crud_app() -> web.Application:
    from aj_crew.dashboard.handlers import api_ajcrew_agent_update

    app = web.Application()
    app.router.add_put("/api/agents/{name}", api_ajcrew_agent_update)
    return app


@pytest.fixture()
def starred_agent():
    cfg = AjCrewConfig.load()
    cfg.agents["fav"] = AjCrewAgentConfig(
        kiro_agent="ajcrew", workspace="default", memory_store="default", starred=True
    )
    cfg.save()
    return "fav"


class TestUpdateEndpoint:
    @pytest.mark.asyncio
    async def test_order_persists(self, starred_agent):
        async with TestClient(TestServer(_crud_app())) as client:
            resp = await client.put(f"/api/agents/{starred_agent}", json={"star_order": 2})
            assert resp.status == 200
        assert AjCrewConfig.load().agents[starred_agent].star_order == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("junk", ["1", True, 1.0, None, -1, STAR_ORDER_MAX + 1])
    async def test_bad_order_is_refused_and_writes_nothing(self, starred_agent, junk):
        async with TestClient(TestServer(_crud_app())) as client:
            resp = await client.put(
                f"/api/agents/{starred_agent}", json={"workspace": "other", "star_order": junk}
            )
            assert resp.status == 400
            assert (await resp.json())["code"] == "invalid_star_order"
        stored = AjCrewConfig.load().agents[starred_agent]
        assert stored.star_order == 0
        assert stored.workspace == "default"

    @pytest.mark.asyncio
    async def test_unstar_clears_the_order(self, starred_agent):
        async with TestClient(TestServer(_crud_app())) as client:
            await client.put(f"/api/agents/{starred_agent}", json={"star_order": 4})
            assert (
                await client.put(f"/api/agents/{starred_agent}", json={"starred": False})
            ).status == 200
        stored = AjCrewConfig.load().agents[starred_agent]
        assert stored.starred is False
        assert stored.star_order == 0

    @pytest.mark.asyncio
    async def test_unstarred_crew_holds_no_order(self, starred_agent):
        async with TestClient(TestServer(_crud_app())) as client:
            await client.put(f"/api/agents/{starred_agent}", json={"starred": False})
            await client.put(f"/api/agents/{starred_agent}", json={"star_order": 5})
        assert AjCrewConfig.load().agents[starred_agent].star_order == 0


def _members_app(state) -> web.Application:
    from aj_crew.dashboard.handlers.members import api_members

    @web.middleware
    async def _auth(request: web.Request, handler):
        request.setdefault("app", "")
        request.setdefault("user", "local-app")
        return await handler(request)

    app = web.Application(middlewares=[_auth])
    app["state"] = state
    app.router.add_get("/api/members", api_members)
    return app


@pytest.mark.asyncio
async def test_roster_rows_carry_star_order(tmp_path):
    fake = SimpleNamespace(
        agents={
            "top": AjCrewAgentConfig(kiro_agent="top", starred=True, star_order=1),
            "plain": AjCrewAgentConfig(kiro_agent="plain"),
        },
        default_agent="top",
        memory_stores={},
        degraded_sections=frozenset(),
    )
    state = _make_state(tmp_path)
    with patch("aj_crew.dashboard.handlers.members.AjCrewConfig.load", return_value=fake):
        async with TestClient(TestServer(_members_app(state))) as client:
            body = await (await client.get("/api/members")).json()
    rows = {r["name"]: r for r in body["members"]}
    assert rows["top"]["star_order"] == 1
    assert rows["plain"]["star_order"] == 0
