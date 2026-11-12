"""``ajcrew agent delete`` runs the dashboard delete's teardown.

The CLI delete and ``DELETE /api/agents/{name}`` share ``_remove_member_leftovers``:
the avatar, the goal check-in schedules, the worktrees and the private template
copy all go with the record, whichever surface deleted it. Each item removed
prints one line. A step that fails leaves the delete committed and the other
steps run; the command names the failure on stderr and exits 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cli_commands_coverage_helpers import _ns

from aj_crew import agent_state
from aj_crew import cli_commands as cc
from aj_crew import crewmate_worktree
from aj_crew.config import config_dir
from aj_crew.config.loader import AjCrewAgentConfig, AjCrewConfig
from aj_crew.cron import CronService
from aj_crew.dashboard import goal_reminder
from aj_crew.dashboard.agent_admin import avatars
from aj_crew.dashboard.handlers import agents as agents_facade
from aj_crew.member_goals import CADENCES
from aj_crew.members import member_slug

CREW = "design-crew"


def _write_template(agents_dir: Path, stem: str) -> None:
    spec = {"name": stem, "model": "claude-x", "tools": ["ReadFile"]}
    (agents_dir / f"{stem}.json").write_text(json.dumps(spec), encoding="utf-8")


def _seed(agents_dir: Path) -> CronService:
    """A default crew and ``design-crew``: a private copy, a staged avatar, check-ins."""
    _write_template(agents_dir, "ajcrew")
    _write_template(agents_dir, CREW)
    agent_state.set_fork_info(CREW, forked_from="ajcrew", private_to=CREW)
    cfg = AjCrewConfig()
    cfg.agents = {
        "ajcrew": AjCrewAgentConfig(kiro_agent="ajcrew"),
        CREW: AjCrewAgentConfig(kiro_agent=CREW),
    }
    cfg.default_agent = "ajcrew"
    cfg.save()
    avatar_dir = avatars._avatars_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    (avatar_dir / f"{avatars._avatar_stem(CREW)}.pending.png").write_bytes(b"\x89PNG")
    svc = CronService(base_dir=config_dir())
    svc.add_job("unrelated", "do it", every_secs=3600)
    for slug in (member_slug(CREW, cfg), member_slug("ajcrew", cfg)):
        for cadence in CADENCES:
            svc.add_managed_job(
                goal_reminder.managed_key(slug, cadence),
                name=f"{slug} {cadence}",
                message="x",
                cron_expr="0 9 * * *",
            )
    return svc


def _job_names() -> list[str]:
    jobs = CronService(base_dir=config_dir()).list_jobs(include_disabled=True)
    return sorted(j.name for j in jobs)


def _delete(agents_dir: Path) -> None:
    with patch("aj_crew.agent.KIRO_AGENTS_DIR", agents_dir):
        cc._handle_agent(_ns(agent_action="delete", name=CREW))


def test_cli_delete_removes_what_the_dashboard_delete_removes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _seed(agents_dir)
    kept_slug = member_slug("ajcrew", AjCrewConfig.load())

    _delete(agents_dir)

    assert CREW not in AjCrewConfig.load().agents
    assert not (agents_dir / f"{CREW}.json").exists()
    assert agent_state.get_fork_info(CREW) is None
    assert (agents_dir / "ajcrew.json").exists()
    assert avatars._pending_avatar_path(CREW) is None
    # Only the deleted crew's check-ins go; another crew's and a plain job stay.
    assert _job_names() == sorted(["unrelated", *(f"{kept_slug} {c}" for c in CADENCES)])
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert lines[0] == f"Deleted agent: {CREW}"
    assert "Removed avatar" in lines
    assert f"Removed private template copy: {CREW}" in lines
    assert sum(line.startswith("Removed goal check-in: ") for line in lines) == len(CADENCES)
    assert out.err == ""


def test_a_failed_step_is_reported_and_the_rest_still_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _seed(agents_dir)

    with (
        patch.object(agents_facade, "_remove_avatar_files", lambda _name: None),
        pytest.raises(SystemExit) as exc,
    ):
        _delete(agents_dir)

    assert exc.value.code == 1
    assert CREW not in AjCrewConfig.load().agents
    # The avatar could not go, and the steps after it still ran.
    assert avatars._pending_avatar_path(CREW) is not None
    assert not (agents_dir / f"{CREW}.json").exists()
    assert not any(name.startswith(member_slug(CREW, AjCrewConfig())) for name in _job_names())
    out = capsys.readouterr()
    assert f"Deleted agent: {CREW}" in out.out
    assert f"Removed private template copy: {CREW}" in out.out
    assert out.err.strip() == f"Error: could not remove the avatar of '{CREW}'"


def test_worktrees_print_one_line_each_and_a_failed_lookup_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _seed(agents_dir)
    monkeypatch.setattr(
        crewmate_worktree, "remove_for_member", lambda *_a: (["/ws/done"], ["/ws/dirty"])
    )

    _delete(agents_dir)

    lines = capsys.readouterr().out.splitlines()
    assert "Removed worktree: /ws/done" in lines
    assert "Kept worktree: /ws/dirty" in lines

    cfg = AjCrewConfig.load()
    cfg.agents[CREW] = AjCrewAgentConfig(kiro_agent="ajcrew")
    cfg.save()
    monkeypatch.setattr(crewmate_worktree, "remove_for_member", lambda *_a: None)
    with pytest.raises(SystemExit) as exc:
        _delete(agents_dir)
    assert exc.value.code == 1
    assert CREW not in AjCrewConfig.load().agents
    assert capsys.readouterr().err.strip() == f"Error: could not remove the worktrees of '{CREW}'"


def test_an_unreadable_cron_store_is_a_failed_step_not_none_to_remove(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unreadable store lists as empty; reading that as "no check-ins" would
    exit 0 while the schedules come back once the file is repaired."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    _seed(agents_dir)
    (config_dir() / "crons.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _delete(agents_dir)

    assert exc.value.code == 1
    assert CREW not in AjCrewConfig.load().agents
    out = capsys.readouterr()
    assert f"Removed private template copy: {CREW}" in out.out
    assert out.err.strip() == f"Error: could not remove the goal check-ins of '{CREW}'"
