"""Tests for the guarded ``~/.kiro/crew`` -> ``~/.ajcrew`` data-home migration state machine."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from aj_crew.config import paths
from conftest import make_dir_link


class TestGuardedDataHomeMigration:
    """Verify non-destructive migration, marker states, symlink refusal, and AJCREW_HOME."""

    @pytest.fixture(autouse=True)
    def _reset_caches(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        fake_home = tmp_path / "user-home"
        fake_home.mkdir()
        monkeypatch.delenv("AJCREW_HOME", raising=False)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        monkeypatch.setattr(paths, "_resolved_home", None)
        monkeypatch.setattr(paths, "_config_dir_memo", None)
        monkeypatch.setattr(paths, "_override_home_pin", None)
        monkeypatch.setattr(paths, "_write_recovery_breadcrumb", lambda _p: None)

    def test_fresh_install_creates_dot_ajcrew_with_fresh_marker(self) -> None:
        home = Path.home()
        resolved = paths.config_dir()
        assert resolved == home / ".ajcrew"
        assert resolved.is_dir()
        assert not (home / ".kiro" / "crew").exists()
        marker = json.loads(
            (resolved / paths.HOME_MIGRATION_STATE_FILE).read_text(encoding="utf-8")
        )
        assert marker["state"] == "fresh"

    def test_existing_kiro_crew_migrates_non_destructively_to_dot_ajcrew(self) -> None:
        home = Path.home()
        legacy = home / ".kiro" / "crew"
        (legacy / "profiles").mkdir(parents=True)
        (legacy / "config.json").write_text('{"agent": {"model": "auto"}}', encoding="utf-8")
        (legacy / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
        (legacy / "profiles" / "dev.json").write_text('{"version": 1}', encoding="utf-8")
        # Volatile runtime directory should not break or pollute migrated home.
        (legacy / "run").mkdir()
        (legacy / "run" / "gateway.pid").write_text("12345", encoding="utf-8")

        # Pure peek_data_home() before migration points at legacy without mutating disk.
        assert paths.peek_data_home() == legacy
        assert not (home / ".ajcrew").exists()

        resolved = paths.config_dir()
        assert resolved == home / ".ajcrew"
        assert (resolved / "config.json").read_text(
            encoding="utf-8"
        ) == '{"agent": {"model": "auto"}}'
        assert (resolved / ".env").read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-test\n"
        assert (resolved / "profiles" / "dev.json").is_file()
        assert not (resolved / "run").exists()
        # Legacy directory stays intact for non-destructive rollback safety!
        assert (legacy / "config.json").is_file()
        marker = json.loads(
            (resolved / paths.HOME_MIGRATION_STATE_FILE).read_text(encoding="utf-8")
        )
        assert marker["state"] == "completed"

    def test_interrupted_migrating_marker_falls_back_safely_to_kiro_crew(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        home = Path.home()
        legacy = home / ".kiro" / "crew"
        legacy.mkdir(parents=True)
        (legacy / "config.json").write_text('{"ok": true}', encoding="utf-8")
        target = home / ".ajcrew"
        target.mkdir(parents=True)
        (target / paths.HOME_MIGRATION_STATE_FILE).write_text(
            json.dumps({"state": "migrating", "version": 1}), encoding="utf-8"
        )

        with caplog.at_level(logging.WARNING, logger=paths.__name__):
            resolved = paths.config_dir()
        assert resolved == legacy
        assert any("migrating" in r.message or "incomplete" in r.message for r in caplog.records)

    def test_symlinked_target_is_refused_and_falls_back_to_kiro_crew(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        home = Path.home()
        legacy = home / ".kiro" / "crew"
        legacy.mkdir(parents=True)
        (legacy / "config.json").write_text('{"ok": true}', encoding="utf-8")
        decoy = tmp_path / "attacker-dir"
        decoy.mkdir()
        make_dir_link(home / ".ajcrew", decoy)

        with caplog.at_level(logging.WARNING, logger=paths.__name__):
            resolved = paths.config_dir()
        assert resolved == legacy
        assert list(decoy.iterdir()) == []

    def test_ajcrew_home_override_always_wins_over_both(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        home = Path.home()
        (home / ".kiro" / "crew").mkdir(parents=True)
        (home / ".kiro" / "crew" / "config.json").write_text("{}", encoding="utf-8")
        custom = tmp_path / "explicit-override"
        monkeypatch.setenv("AJCREW_HOME", str(custom))

        assert paths.config_dir() == custom.resolve()
        assert not (home / ".ajcrew").exists()
