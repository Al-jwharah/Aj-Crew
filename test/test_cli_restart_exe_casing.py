"""``ajcrew restart`` respawns the gateway under the on-disk ``.exe`` spelling.

On Windows ``shutil.which("ajcrew")`` spells the extension it appends as
``PATHEXT`` does, so it returns ``...\\ajcrew.EXE`` while the file on disk is
``ajcrew.exe``. A launcher shim that dispatches on its own basename refuses
the upper-case spelling and exits at once, after restart has already stopped
the old gateway. Both lookups restart makes -- the bare ``argv[0]`` one in
``_own_console_script`` and the PATH fallback in ``_spawn_detached_gateway`` --
must hand ``Popen`` the true spelling.

Windows is forced only inside the casing helper: forcing ``IS_WINDOWS`` for the
whole spawn would switch the detach flags and other platform branches too.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aj_crew import cli_server, env, platform_compat
from aj_crew.testing.ids import UNALLOCATABLE_PID


def _windows_casing(path: str | None) -> str:
    """The real helper, run as if on Windows, for exactly one call."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(platform_compat, "IS_WINDOWS", True)
        return env.resolved_command_casing(path)


def _shim(tmp_path: Path) -> tuple[str, str]:
    """A launcher on disk as ``ajcrew.exe``, and the ``.EXE`` spelling of it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    actual = bin_dir / "ajcrew.exe"
    actual.write_text("#!/bin/sh\n", encoding="utf-8")
    actual.chmod(0o755)
    return str(actual), str(bin_dir / "ajcrew.EXE")


@pytest.fixture
def windows_casing(monkeypatch):
    # create=True so the test fails on its assertion, not on the patch, when the
    # call site does not route through the helper.
    monkeypatch.setattr(cli_server, "resolved_command_casing", _windows_casing, raising=False)


def test_path_fallback_spawns_the_on_disk_spelling(tmp_path, monkeypatch, windows_casing):
    """The Toolbox case: ``python -m aj_crew restart``, so argv[0] is no script."""
    actual, raw = _shim(tmp_path)
    monkeypatch.setattr(cli_server, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "aj_crew" / "__main__.py"), "restart"])
    proc = MagicMock(pid=UNALLOCATABLE_PID)
    with (
        patch("aj_crew.cli_server.shutil.which", return_value=raw),
        patch("aj_crew.cli_server.subprocess.Popen", return_value=proc) as popen,
    ):
        spawned = cli_server._spawn_detached_gateway(5476)
    assert spawned is proc
    assert popen.call_args.args[0] == [actual, "gateway", "--port", "5476"]


def test_bare_argv0_resolves_to_the_on_disk_spelling(tmp_path, monkeypatch, windows_casing):
    """A shell that found ``ajcrew`` on PATH leaves a bare argv[0]."""
    actual, raw = _shim(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ajcrew", "restart"])
    with patch("aj_crew.cli_server.shutil.which", return_value=raw):
        assert cli_server._own_console_script() == actual


def test_an_unrepairable_path_is_spawned_unchanged(tmp_path, monkeypatch, windows_casing):
    """The repair never invents a path: an unlistable directory keeps its spelling."""
    raw = str(tmp_path / "missing" / "ajcrew.EXE")
    monkeypatch.setattr(cli_server, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "aj_crew" / "__main__.py"), "restart"])
    proc = MagicMock(pid=UNALLOCATABLE_PID)
    with (
        patch("aj_crew.cli_server.shutil.which", return_value=raw),
        patch("aj_crew.cli_server.subprocess.Popen", return_value=proc) as popen,
    ):
        spawned = cli_server._spawn_detached_gateway()
    assert spawned is proc
    assert popen.call_args.args[0] == [raw, "gateway"]
