"""Kiro-optional: kiro-cli must not be required when a non-kiro backend is configured.

Three scenarios are pinned:

1. kiro-cli absent, non-kiro backend configured → ``warm_up`` returns ``None``
   (probe skipped) and ``_ensure_prerequisites`` omits the kiro-cli install note.
2. kiro-cli absent, nothing else installed → no crash, ``warm_up`` returns
   ``None``, ``_ensure_prerequisites`` returns ``True``.
3. kiro-cli present (or kiro backend selected) → behaviour is unchanged:
   ``warm_up`` returns a ``Task``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aj_crew.agent_sdk.backends import (
    ACP_BACKEND_CLAUDE,
    ACP_BACKEND_KAS,
    ACP_BACKEND_KIRO,
)
from aj_crew.kiro_prerequisite_service import (
    KiroPrerequisiteService,
    _kiro_family_backend_is_selected,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pin_backend(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    """Point ``AjCrewConfig.load`` at a minimal stub returning *backend*."""

    def _load() -> SimpleNamespace:
        return SimpleNamespace(agent=SimpleNamespace(acp_backend=backend))

    monkeypatch.setattr("aj_crew.config.AjCrewConfig.load", _load)


def _make_service(tmp_path_factory: pytest.TempPathFactory) -> KiroPrerequisiteService:
    """Minimal service instance with no filesystem side-effects."""
    return KiroPrerequisiteService(
        data_home=tmp_path_factory.mktemp("kiro_svc"),
        warm_up_delay=0.0,
        assume_ready=False,
    )


# ---------------------------------------------------------------------------
# 1. Helper predicate
# ---------------------------------------------------------------------------


class TestKiroFamilyBackendIsSelected:
    """``_kiro_family_backend_is_selected`` answers for every configuration."""

    def test_kiro_backend_is_kiro_family(self, monkeypatch):
        _pin_backend(monkeypatch, ACP_BACKEND_KIRO)
        assert _kiro_family_backend_is_selected() is True

    def test_kas_backend_is_kiro_family(self, monkeypatch):
        _pin_backend(monkeypatch, ACP_BACKEND_KAS)
        assert _kiro_family_backend_is_selected() is True

    def test_claude_backend_is_not_kiro_family(self, monkeypatch):
        _pin_backend(monkeypatch, ACP_BACKEND_CLAUDE)
        assert _kiro_family_backend_is_selected() is False

    @pytest.mark.parametrize(
        "backend", ["codex", "goose", "pi", "deepseek", "strands", "opencode", "copilot"]
    )
    def test_independent_backends_are_not_kiro_family(self, monkeypatch, backend):
        _pin_backend(monkeypatch, backend)
        assert _kiro_family_backend_is_selected() is False

    def test_unreadable_config_fails_safe_to_true(self, monkeypatch):
        """An unreadable config must not suppress the probe — fail safe."""

        def _raises() -> None:
            raise OSError("no config")

        monkeypatch.setattr("aj_crew.config.AjCrewConfig.load", _raises)
        assert _kiro_family_backend_is_selected() is True


# ---------------------------------------------------------------------------
# 2. warm_up skipped on non-kiro backend
# ---------------------------------------------------------------------------


class TestWarmUpSkippedOnNonKiroBackend:
    """``warm_up()`` must return ``None`` when no kiro-family backend is configured."""

    def test_warm_up_returns_none_for_non_kiro_backend(self, monkeypatch, tmp_path_factory):
        """Non-kiro backend: no task created, no kiro-cli spawn attempted."""
        _pin_backend(monkeypatch, ACP_BACKEND_CLAUDE)
        svc = _make_service(tmp_path_factory)
        result = svc.warm_up()
        assert result is None, "warm_up must return None for a non-kiro-family backend"
        # Calling again is idempotent (no task was latched).
        assert svc.warm_up() is None

    @pytest.mark.parametrize("backend", ["codex", "goose", "strands"])
    def test_warm_up_returns_none_for_independent_backend(
        self, monkeypatch, backend, tmp_path_factory
    ):
        _pin_backend(monkeypatch, backend)
        svc = _make_service(tmp_path_factory)
        assert svc.warm_up() is None

    def test_warm_up_returns_task_for_kiro_backend(self, monkeypatch, tmp_path_factory):
        """kiro (or KAS) backend: a Task is created as before."""
        _pin_backend(monkeypatch, ACP_BACKEND_KIRO)
        svc = _make_service(tmp_path_factory)

        async def _run() -> None:
            task = svc.warm_up()
            assert task is not None, "warm_up must return a Task for a kiro-family backend"
            assert isinstance(task, asyncio.Task)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())

    def test_warm_up_returns_task_for_kas_backend(self, monkeypatch, tmp_path_factory):
        """KAS relay backend: a Task is created as before."""
        _pin_backend(monkeypatch, ACP_BACKEND_KAS)
        svc = _make_service(tmp_path_factory)

        async def _run() -> None:
            task = svc.warm_up()
            assert task is not None
            assert isinstance(task, asyncio.Task)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 3. _ensure_prerequisites omits kiro note on non-kiro backend
# ---------------------------------------------------------------------------


class TestEnsurePrerequisitesOmitsKiroNoteOnNonKiroBackend:
    """``_ensure_prerequisites`` must not print the kiro-cli install note when
    the configured backend is not kiro-family and kiro-cli is absent.
    """

    def test_no_kiro_note_for_non_kiro_backend(self, monkeypatch, capsys):
        """Non-kiro backend + no kiro-cli: note must NOT appear."""
        _pin_backend(monkeypatch, ACP_BACKEND_CLAUDE)
        # kiro-cli absent, node present (suppress node note; focus on kiro)

        def _which(cmd: str) -> str | None:
            return None if "kiro" in cmd else "/usr/bin/node"

        monkeypatch.setattr("aj_crew.cli_setup.shutil.which", _which)

        from aj_crew.cli_setup import _ensure_prerequisites

        result = _ensure_prerequisites()
        captured = capsys.readouterr().out
        assert result is True
        assert (
            "kiro-cli" not in captured
        ), f"kiro-cli note must not appear for non-kiro backend; got: {captured!r}"

    def test_kiro_note_printed_for_kiro_backend_when_absent(self, monkeypatch, capsys):
        """kiro backend + no kiro-cli: note MUST appear (unchanged behaviour)."""
        _pin_backend(monkeypatch, ACP_BACKEND_KIRO)

        def _which(cmd: str) -> str | None:
            return None  # nothing on PATH

        monkeypatch.setattr("aj_crew.cli_setup.shutil.which", _which)

        from aj_crew.cli_setup import _ensure_prerequisites

        result = _ensure_prerequisites()
        captured = capsys.readouterr().out
        assert result is True
        assert (
            "kiro-cli" in captured
        ), f"kiro-cli install note must appear for kiro backend; got: {captured!r}"

    def test_nothing_installed_no_crash(self, monkeypatch):
        """kiro absent + nothing installed: no crash, returns True."""
        _pin_backend(monkeypatch, ACP_BACKEND_CLAUDE)
        monkeypatch.setattr("aj_crew.cli_setup.shutil.which", lambda _cmd: None)

        from aj_crew.cli_setup import _ensure_prerequisites

        # Must not raise.
        assert _ensure_prerequisites() is True
