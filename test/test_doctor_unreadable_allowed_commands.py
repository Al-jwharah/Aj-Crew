"""``ajcrew doctor`` names each agent spec ``allowedCommands`` entry Aj Crew's
gate cannot read.

On KAS and claude Aj Crew answers a spec's ``toolsSettings`` shell
``allowedCommands`` at its own gate and refuses what they do not match under
``denyByDefault``. An entry it cannot read allows nothing there, so a scheduled
job refuses a command kiro-cli would run. The doctor row is where the operator
learns which entry, before a run does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aj_crew import cli_doctor
from aj_crew.acp_backends import ACP_BACKEND_CLAUDE, ACP_BACKEND_KAS
from aj_crew.agent_sdk.backends import ACP_BACKEND_KIRO
from aj_crew.config.loader import AjCrewConfig
from aj_crew.doctor_checks import agents

_UNREADABLE = r"ls \p{L}+"
_ISSUE = "an agent spec has allowedCommands entries Aj Crew cannot read"


def _write_spec(directory: Path, name: str, allowed: list[Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    spec = {
        "name": name,
        "prompt": "p",
        "toolsSettings": {"execute_bash": {"denyByDefault": True, "allowedCommands": allowed}},
    }
    (directory / f"{name}.json").write_text(json.dumps(spec), encoding="utf-8")


def _cfg(main: str = ACP_BACKEND_KAS, member: str = ACP_BACKEND_KAS) -> AjCrewConfig:
    cfg = AjCrewConfig()
    cfg.agent.acp_backend = main
    cfg.agent.member_acp_backend = member
    return cfg


@pytest.fixture()
def agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "agents"
    monkeypatch.setattr(cli_doctor, "_agents_dir", lambda: directory)
    return directory


def _run(cfg: AjCrewConfig, project: Path | None = None) -> list[str]:
    issues: list[str] = []
    agents._doctor_unreadable_allowed_commands(cfg, str(project) if project else None, issues)
    return issues


def test_an_unreadable_entry_is_named_with_its_agent_and_why(agents_dir: Path, capsys) -> None:
    _write_spec(agents_dir, "probe", ["git status", r"^sleep \d+$", _UNREADABLE])
    assert _run(_cfg()) == [_ISSUE]
    out = capsys.readouterr().out
    assert f"'probe' toolsSettings.execute_bash.allowedCommands entry {_UNREADABLE!r}" in out
    assert "the escape \\p" in out
    # The entries Aj Crew reads are not named.
    assert "git status" not in out and "sleep" not in out


def test_specs_whose_every_entry_reads_print_nothing(agents_dir: Path, capsys) -> None:
    _write_spec(agents_dir, "probe", ["git status", r"^ls [[:alnum:]]+$", "(?i)^whoami$"])
    assert _run(_cfg()) == []
    assert capsys.readouterr().out == ""


def test_a_project_spec_is_read_too(agents_dir: Path, tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    _write_spec(project / ".kiro" / "agents", "local", [_UNREADABLE])
    assert _run(_cfg(), project) == [_ISSUE]
    assert "'local'" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("main", "member", "checked"),
    [
        (ACP_BACKEND_KAS, ACP_BACKEND_KAS, True),
        (ACP_BACKEND_CLAUDE, "codex", True),
        (ACP_BACKEND_KIRO, ACP_BACKEND_KAS, True),
        # kiro-cli reads the entries itself, so Aj Crew's reading of them is moot.
        (ACP_BACKEND_KIRO, "codex", False),
    ],
)
def test_only_a_backend_aj_crew_answers_them_on_is_checked(
    agents_dir: Path, main: str, member: str, checked: bool
) -> None:
    _write_spec(agents_dir, "probe", [_UNREADABLE])
    assert _run(_cfg(main, member)) == ([_ISSUE] if checked else [])
