"""A gateway started under a foreign ``AJCREW_PORT`` must not hand it to its children.

The gateway exports its live listener as
``AJCREW_BOUND_PORT`` but keeps an inherited ``AJCREW_PORT`` (an agent shell
of ANOTHER gateway carries one). The client resolution chain reads
``AJCREW_PORT`` first, so without the spawn-time drop every child -- the agent
CLI and the managed MCP servers it starts -- dials the other gateway with this
gateway's credential and fails ``internal_auth_mismatch``.

The fix lives at spawn time (``acp.launch.drop_foreign_inherited_port``), never in
a spec written to disk: the bound port is transient and must not be persisted
under the operator-intent name.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import acp_launch_capture as capture_mod
import pytest

from aj_crew.acp.launch import drop_foreign_inherited_port
from aj_crew.agent_sdk.backends import ACP_BACKEND_KIRO


def test_a_foreign_inherited_port_is_dropped_so_the_bound_port_wins():
    env = {"AJCREW_PORT": "7790", "AJCREW_BOUND_PORT": "35705", "OTHER": "x"}
    drop_foreign_inherited_port(env)
    assert env == {"AJCREW_BOUND_PORT": "35705", "OTHER": "x"}


@pytest.mark.parametrize("same", ["35705", " 35705 "])
def test_the_operators_own_port_this_gateway_bound_is_kept(same):
    env = {"AJCREW_PORT": same, "AJCREW_BOUND_PORT": "35705"}
    drop_foreign_inherited_port(env)
    assert env["AJCREW_PORT"] == same


def test_without_a_bound_port_nothing_proves_the_inherited_value_foreign():
    env = {"AJCREW_PORT": "7790"}
    drop_foreign_inherited_port(env)
    assert env == {"AJCREW_PORT": "7790"}


@pytest.mark.parametrize("bound", ["", "auto", "secret", "0", "-1", "65536", "123456", "１２３"])
def test_an_ill_formed_bound_port_never_drops_anything(bound):
    env = {"AJCREW_PORT": "7790", "AJCREW_BOUND_PORT": bound}
    drop_foreign_inherited_port(env)
    assert env["AJCREW_PORT"] == "7790"


def test_no_inherited_port_is_a_no_op():
    env = {"AJCREW_BOUND_PORT": "35705"}
    drop_foreign_inherited_port(env)
    assert env == {"AJCREW_BOUND_PORT": "35705"}


def test_the_spawned_child_resolves_the_gateway_that_spawned_it(tmp_path, monkeypatch):
    """Through the real client launch: the child env carries the bound port only."""
    recorders: list = []

    class _Spy(capture_mod._Recorder):
        def __init__(self) -> None:
            super().__init__()
            recorders.append(self)

    monkeypatch.setattr(capture_mod, "_Recorder", _Spy)
    capture_mod.capture(
        ACP_BACKEND_KIRO,
        tmp_path,
        extra_patches=[
            patch.dict(os.environ, {"AJCREW_PORT": "7790", "AJCREW_BOUND_PORT": "35705"})
        ],
    )
    assert recorders, "the capture did not reach the spawn"
    child_env = recorders[-1].env
    assert "AJCREW_PORT" not in child_env
    assert child_env.get("AJCREW_BOUND_PORT") == "35705"


def test_the_managed_spec_on_disk_never_carries_the_transient_port(monkeypatch):
    """Design-review contract: the bound port is not persisted into a written spec."""
    from aj_crew.agent import _managed_mcp_env, managed_mcp_spec_entry

    monkeypatch.delenv("AJCREW_HOME", raising=False)
    monkeypatch.setenv("AJCREW_PORT", "7790")
    monkeypatch.setenv("AJCREW_BOUND_PORT", "35705")
    assert "AJCREW_PORT" not in _managed_mcp_env()
    entry = managed_mcp_spec_entry("ajcrew-core")
    assert entry is not None
    assert "AJCREW_PORT" not in (entry.get("env") or {})
