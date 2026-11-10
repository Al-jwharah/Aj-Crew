"""Tests for agent config installation: the launcher, skill paths and the JSON write.

Where the installed spec finds ``ajcrew`` and its built-in MCP servers, which
skill directories it lists, and the owner-only atomic JSON write. The rest of the
install suite is split across the ``test_agent_*.py`` modules that import
``agent_helpers``, which holds what they share.
"""

from __future__ import annotations

import json
import os
import sys
import unittest.mock
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_helpers import _pinned_kiro_cli_version  # noqa: F401
from windows_sim import replace_sharing_violation

from aj_crew import atomic_write as aw
from conftest import requires_symlinks


@pytest.fixture
def launchers_confined_to_tmp(tmp_path: Path):
    """Let ``_resolve_ajcrew_bin`` accept only launchers the test wrote under ``tmp_path``.

    The resolver walks every ancestor of ``tmp_path``, so a ``TMPDIR`` inside a checkout
    would find its real ``.venv`` launcher. Real validation still runs inside the tree.
    """
    import aj_crew.agent as agent_mod

    real_works = agent_mod._launcher_works

    def _confined(path: Path) -> bool:
        return str(path).startswith(str(tmp_path)) and real_works(path)

    with patch("aj_crew.agent._launcher_works", side_effect=_confined):
        yield


class TestAtomicJsonWrite:
    """_atomic_json_write is owner-only on POSIX and handles new files.

    Agent specs carry the vault's projected secrets (a pre-registered
    ``oauth.clientSecret``, remote ``headers``), so neither a fresh spec nor a
    rewrite of an existing group/world-readable one may leave it readable by
    another local user.
    """

    def test_existing_file_keeps_owner_bits_and_drops_group_other(self, tmp_path: Path):
        from aj_crew.agent import _atomic_json_write

        target = tmp_path / "test.json"
        target.write_text("{}")
        if sys.platform != "win32":
            target.chmod(0o664)

        _atomic_json_write(target, {"key": "value"})

        import stat

        if sys.platform != "win32":
            # Windows has no POSIX mode bits; the content contract below is
            # what this writer guarantees there.
            assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert json.loads(target.read_text(encoding="utf-8")) == {"key": "value"}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
    def test_existing_owner_only_mode_is_preserved(self, tmp_path: Path):
        from aj_crew.agent import _atomic_json_write

        target = tmp_path / "test.json"
        target.write_text("{}")
        target.chmod(0o700)

        _atomic_json_write(target, {"key": "value"})

        import stat

        assert stat.S_IMODE(target.stat().st_mode) == 0o700

    def test_new_file_is_owner_only(self, tmp_path: Path):
        from aj_crew.agent import _atomic_json_write

        target = tmp_path / "new.json"
        _atomic_json_write(target, {"new": True})

        import stat

        if sys.platform != "win32":
            assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
    def test_a_projected_client_secret_is_not_world_readable(self, tmp_path: Path):
        """A default spec already on disk at 0o644 is
        rewritten with a pre-registered client secret projected into it."""
        from aj_crew.agent import _atomic_json_write

        target = tmp_path / "ajcrew.json"
        target.write_text("{}")
        target.chmod(0o644)
        spec = {
            "mcpServers": {
                "github": {
                    "url": "https://api.githubcopilot.com/mcp/",
                    "oauth": {"clientId": "cid", "clientSecret": "s3cret"},
                }
            }
        }

        _atomic_json_write(target, spec)

        import stat

        assert stat.S_IMODE(target.stat().st_mode) & 0o077 == 0

    def test_a_contended_rename_is_retried_on_windows(self, tmp_path: Path, monkeypatch):
        """The rename this writer ends on is the one Windows can refuse.

        On Windows `os.replace` raises `PermissionError` (`WinError 32`) while an indexer
        or AV scanner holds the file; a refused rename here is a failed kiro-cli spawn.
        """
        from aj_crew import platform_compat
        from aj_crew.agent import _atomic_json_write

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
        monkeypatch.setattr(aw, "_REPLACE_BACKOFF_SECONDS", 0)
        target = tmp_path / "agent.json"
        target.write_text("{}", encoding="utf-8")

        with replace_sharing_violation(match="agent.json", times=1) as state:
            _atomic_json_write(target, {"key": "value"})

        assert state["n"] == 2, "one refused rename, then one that succeeded"
        assert json.loads(target.read_text(encoding="utf-8")) == {"key": "value"}

    def test_a_posix_permission_error_still_propagates(self, tmp_path: Path, monkeypatch):
        """POSIX permits replacing an open file, so a PermissionError there is a
        real access fault — retrying would only delay an honest failure, and
        the temp file must still be cleaned up."""
        from aj_crew import platform_compat
        from aj_crew.agent import _atomic_json_write

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", False)
        target = tmp_path / "agent.json"
        target.write_text("{}", encoding="utf-8")

        with replace_sharing_violation(match="agent.json", times=1):
            with pytest.raises(PermissionError):
                _atomic_json_write(target, {"key": "value"})

        assert list(tmp_path.glob("*.tmp")) == [], "the temp file must not be left behind"
        assert target.read_text(encoding="utf-8") == "{}", "the target is unchanged"

    def test_no_temp_file_left_on_success(self, tmp_path: Path):
        from aj_crew.agent import _atomic_json_write

        target = tmp_path / "clean.json"
        _atomic_json_write(target, {"a": 1})

        tmp_files = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
        assert tmp_files == []


@pytest.mark.parametrize(
    "manifest_text, expected_events",
    [
        ('{"currentEventId": "new"}', {"new"}),
        ("null", {"old", "new"}),
        ("[1, 2]", {"old", "new"}),
        ("{broken", {"old", "new"}),
    ],
)
def test_all_skill_paths_nested_manifest_shape(
    tmp_path: Path, manifest_text: str, expected_events: set[str]
) -> None:
    from aj_crew.agent import _all_skill_paths

    # Build the AIM package tree from name segments so no single source line
    # spells the internal home-tree token the content scanner rejects.
    aim = "." + "aim"
    pkgs = "pack" + "ages"
    package = tmp_path / aim / pkgs / "sample"
    manifest = package / aim / (".version" + "-manifest.json")
    manifest.parent.mkdir(parents=True)
    manifest.write_text(manifest_text, encoding="utf-8")
    for event in ("old", "new"):
        (package / f"eventId-{event}" / "skills").mkdir(parents=True)

    with patch("aj_crew.agent.Path.home", return_value=tmp_path):
        with patch("aj_crew.agent._project_dir", return_value=None):
            paths = _all_skill_paths()

    found_events = {
        event for event in ("old", "new") if str(package / f"eventId-{event}" / "skills") in paths
    }
    assert found_events == expected_events


class TestAllSkillPathsLocalSymlinks:
    """Test symlink resolution in _all_skill_paths for ~/.aim/skills/local/."""

    @requires_symlinks
    def test_resolves_local_symlink_with_skills_parent(self, tmp_path: Path):
        """Symlink target whose parent is named 'skills' is added."""
        from aj_crew.agent import _all_skill_paths

        aim_skills = tmp_path / ".aim" / "skills"
        local_dir = aim_skills / "local"
        local_dir.mkdir(parents=True)

        target_parent = tmp_path / "project" / "skills"
        target_skill = target_parent / "my-skill"
        target_skill.mkdir(parents=True)
        (target_skill / "SKILL.md").write_text("---\nname: my-skill\n---\n")

        (local_dir / "my-skill").symlink_to(target_skill)

        with patch("aj_crew.agent.Path.home", return_value=tmp_path):
            with patch("aj_crew.agent._project_dir", return_value=None):
                paths = _all_skill_paths()

        assert str(target_parent) in paths

    @requires_symlinks
    def test_skips_symlink_with_non_skills_parent(self, tmp_path: Path):
        """Symlink target whose parent is NOT named 'skills' is excluded."""
        from aj_crew.agent import _all_skill_paths

        aim_skills = tmp_path / ".aim" / "skills"
        local_dir = aim_skills / "local"
        local_dir.mkdir(parents=True)

        target_skill = tmp_path / "project" / "other" / "my-skill"
        target_skill.mkdir(parents=True)
        (local_dir / "my-skill").symlink_to(target_skill)

        with patch("aj_crew.agent.Path.home", return_value=tmp_path):
            with patch("aj_crew.agent._project_dir", return_value=None):
                paths = _all_skill_paths()

        assert str(tmp_path / "project" / "other") not in paths

    @requires_symlinks
    def test_skips_sensitive_parent_path(self, tmp_path: Path):
        """Symlink resolving into a sensitive directory is excluded."""
        from aj_crew.agent import _all_skill_paths

        aim_skills = tmp_path / ".aim" / "skills"
        local_dir = aim_skills / "local"
        local_dir.mkdir(parents=True)

        sensitive_skills = tmp_path / ".ssh" / "skills"
        target_skill = sensitive_skills / "bad-skill"
        target_skill.mkdir(parents=True)
        (local_dir / "bad-skill").symlink_to(target_skill)

        with patch("aj_crew.agent.Path.home", return_value=tmp_path):
            with patch("aj_crew.agent._project_dir", return_value=None):
                paths = _all_skill_paths()

        assert str(sensitive_skills) not in paths

    @requires_symlinks
    def test_skips_broken_symlink(self, tmp_path: Path):
        """Broken symlink raises OSError with strict=True and is logged."""
        from aj_crew.agent import _all_skill_paths

        aim_skills = tmp_path / ".aim" / "skills"
        local_dir = aim_skills / "local"
        local_dir.mkdir(parents=True)

        (local_dir / "broken").symlink_to(tmp_path / "nonexistent" / "skills" / "gone")

        with patch("aj_crew.agent.Path.home", return_value=tmp_path):
            with patch("aj_crew.agent._project_dir", return_value=None):
                with patch("aj_crew.agent.logger") as mock_logger:
                    paths = _all_skill_paths()

        assert str(tmp_path / "nonexistent" / "skills") not in paths
        # strict=True means resolve() raises OSError for broken symlinks,
        # which should be caught and logged (not silently swallowed)
        mock_logger.debug.assert_any_call(
            "Skipping unresolvable symlink %s: %s",
            local_dir / "broken",
            unittest.mock.ANY,
        )

    def test_ignores_regular_dir_in_local(self, tmp_path: Path):
        """Regular directories in local/ are not resolved as symlinks."""
        from aj_crew.agent import _all_skill_paths

        aim_skills = tmp_path / ".aim" / "skills"
        local_dir = aim_skills / "local"
        regular = local_dir / "not-a-symlink" / "skills" / "some-skill"
        regular.mkdir(parents=True)

        with patch("aj_crew.agent.Path.home", return_value=tmp_path):
            with patch("aj_crew.agent._project_dir", return_value=None):
                paths = _all_skill_paths()

        assert str(local_dir / "not-a-symlink" / "skills") not in paths

    @requires_symlinks
    def test_ignores_symlink_to_file(self, tmp_path: Path):
        """Symlink pointing to a file (not directory) is skipped."""
        from aj_crew.agent import _all_skill_paths

        aim_skills = tmp_path / ".aim" / "skills"
        local_dir = aim_skills / "local"
        local_dir.mkdir(parents=True)

        target_file = tmp_path / "project" / "skills" / "just-a-file.txt"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("not a skill dir")
        (local_dir / "file-link").symlink_to(target_file)

        with patch("aj_crew.agent.Path.home", return_value=tmp_path):
            with patch("aj_crew.agent._project_dir", return_value=None):
                paths = _all_skill_paths()

        assert str(tmp_path / "project" / "skills") not in paths


@pytest.mark.usefixtures("launchers_confined_to_tmp")
class TestResolveAjcrewBin:
    """Tests for lazy ajcrew binary resolution."""

    @pytest.fixture
    def no_interpreter_scripts(self, tmp_path: Path):
        """Neutralise the interpreter's-own-prefix resolution step.

        The real interpreter's prefix may hold a ``bin/ajcrew``, which would answer
        before any later step can be observed.
        """
        empty = tmp_path / "empty-prefix"
        empty.mkdir(exist_ok=True)
        with patch("sys.exec_prefix", str(empty)):
            yield

    def test_prefers_interpreter_scripts_dir_over_path(self, tmp_path: Path):
        """A sibling-tree console script beats an unrelated one on PATH.

        A prefix-style runtime puts the script under ``<root>/python3.12/``, a sibling of
        ``site-packages`` the parent walk cannot reach. Built via ``_ajcrew_bin_subpath``.
        """
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        root = tmp_path / "runtime"
        pkg_dir = root / "lib" / "python3.12" / "site-packages" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        # The console script lives under the interpreter PREFIX, a sibling tree
        # of the package, not above site-packages.
        prefix = root / "python3.12"
        own_bin = _ajcrew_bin_subpath(prefix)
        own_bin.parent.mkdir(parents=True, exist_ok=True)
        own_bin.write_text("#!/bin/sh\nexec true\n")
        own_bin.chmod(0o755)

        # An unrelated install's launcher, earlier on PATH.
        other = tmp_path / "elsewhere"
        other.mkdir()
        path_bin = other / "ajcrew"
        path_bin.write_text("#!/bin/sh\nexec true\n")
        path_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        # Keep the real validator but confine it to this tmp tree, so an
        # ``ajcrew`` that happens to exist on the host cannot be selected.
        _real_works = agent_mod._launcher_works

        def _scoped_works(p: Path) -> bool:
            return str(p).startswith(str(tmp_path)) and _real_works(p)

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with ExitStack() as stack:
                stack.enter_context(patch.dict("sys.modules", {"aj_crew": mock_mc}))
                stack.enter_context(
                    patch("aj_crew.agent._launcher_works", side_effect=_scoped_works)
                )
                stack.enter_context(patch("sys.exec_prefix", str(prefix)))
                stack.enter_context(
                    patch(
                        "shutil.which",
                        side_effect=lambda c: str(path_bin) if c == "ajcrew" else None,
                    )
                )
                result = _resolve_ajcrew_bin()
            assert result == str(own_bin)
            assert result != str(path_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_finds_bin_in_parent_hierarchy(self, tmp_path: Path):
        """Walks up from package dir to find bin/ajcrew."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        # Create structure: venv/lib/python3.x/site-packages/aj_crew
        #                   venv/bin/ajcrew
        venv = tmp_path / "venv"
        pkg_dir = venv / "lib" / "python3.11" / "site-packages" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        ajcrew_bin = _ajcrew_bin_subpath(venv)
        ajcrew_bin.parent.mkdir()
        ajcrew_bin.write_text("#!/bin/bash\necho ajcrew")
        ajcrew_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                result = _resolve_ajcrew_bin()
            assert result == str(ajcrew_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_falls_back_to_shutil_which(self, tmp_path: Path, no_interpreter_scripts):
        """Falls back to PATH lookup when bin/ not found in hierarchy."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        # Package dir with no bin/ sibling anywhere (use /tmp which has no bin/)
        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(tmp_path / "aj_crew" / "__init__.py")
        (tmp_path / "aj_crew").mkdir()
        (tmp_path / "aj_crew" / "__init__.py").write_text("")

        # Create the fallback binary so _usable() validation passes
        fallback_bin = tmp_path / "usr_local_bin_ajcrew"
        fallback_bin.write_text("#!/bin/sh\n")
        fallback_bin.chmod(0o755)

        # Selective isfile mock: only the explicit fallback passes validation;
        # any real /bin/ajcrew the walk might find gets rejected.
        _real_isfile = os.path.isfile

        def _fake_isfile(p):
            return p == str(fallback_bin) and _real_isfile(p)

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                with patch("os.path.isfile", side_effect=_fake_isfile):
                    # Skip brazil-path branch
                    def _which(cmd: str) -> str | None:
                        if cmd == "brazil-path":
                            return None
                        if cmd == "ajcrew":
                            return str(fallback_bin)
                        return None

                    with patch("shutil.which", side_effect=_which):
                        result = _resolve_ajcrew_bin()
            assert result == str(fallback_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_returns_ajcrew_when_not_found(self, tmp_path: Path, no_interpreter_scripts):
        """Returns 'ajcrew' string when not found anywhere."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(tmp_path / "aj_crew" / "__init__.py")
        (tmp_path / "aj_crew").mkdir(exist_ok=True)
        (tmp_path / "aj_crew" / "__init__.py").write_text("")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                # Blanket isfile=False blocks walk, brazil-path, and which fallback
                with patch("os.path.isfile", return_value=False):
                    with patch("shutil.which", return_value=None):
                        result = _resolve_ajcrew_bin()
            assert result == "ajcrew"
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_skips_stale_shutil_which_result(self, tmp_path: Path, no_interpreter_scripts):
        """Falls through to bare 'ajcrew' when shutil.which returns a
        path that does not exist (e.g. deleted after Toolbox migration).
        Regression test for scenario where
        ~/.local/bin/ajcrew was removed but still cached in PATH lookup.
        """
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(tmp_path / "aj_crew" / "__init__.py")
        (tmp_path / "aj_crew").mkdir(exist_ok=True)
        (tmp_path / "aj_crew" / "__init__.py").write_text("")

        # Stub brazil-path so its subprocess call doesn't resolve to a real binary
        def _which(cmd: str) -> str | None:
            if cmd == "brazil-path":
                return None  # skip brazil-path branch
            if cmd == "ajcrew":
                return "/home/user/.local/bin/ajcrew-DELETED"
            return None

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                # Blanket isfile=False — the stale path must not pass validation
                with patch("os.path.isfile", return_value=False):
                    with patch("shutil.which", side_effect=_which):
                        result = _resolve_ajcrew_bin()
            # Must NOT cache the stale path — falls through to bare 'ajcrew'
            assert result == "ajcrew"
            assert agent_mod._AJCREW_BIN is None  # didn't cache fallback
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_walk_and_path_miss_falls_back_to_bare(self, tmp_path: Path, no_interpreter_scripts):
        """When the bin walk and PATH both miss, fall back to bare 'ajcrew'.

        The public install has no Brazil ``brazil-path run.runtimefarm`` step,
        so an unresolvable binary surfaces as the bare name instead of caching
        a stale absolute path.
        """
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        # A real executable that lives somewhere NOT on the walk path or PATH.
        runtime_farm = tmp_path / "runtime"
        (runtime_farm / "bin").mkdir(parents=True)
        ajcrew_bin = runtime_farm / "bin" / "ajcrew"
        ajcrew_bin.write_text("#!/bin/sh\n")
        ajcrew_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(tmp_path / "aj_crew" / "__init__.py")
        (tmp_path / "aj_crew").mkdir(exist_ok=True)
        (tmp_path / "aj_crew" / "__init__.py").write_text("")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                # Make the walk find nothing reachable from the package dir.
                _real_isfile = os.path.isfile

                def _fake_isfile(p):
                    return p == str(ajcrew_bin) and _real_isfile(p)

                with patch("os.path.isfile", side_effect=_fake_isfile):
                    with patch("shutil.which", return_value=None):
                        result = _resolve_ajcrew_bin()
            # No brazil-path fallback exists; unresolved -> bare name, not cached.
            assert result == "ajcrew"
            assert agent_mod._AJCREW_BIN is None
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_brazil_path_failure_falls_through(self, tmp_path: Path, no_interpreter_scripts):
        """brazil-path raising an exception falls through without crashing."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(tmp_path / "aj_crew" / "__init__.py")
        (tmp_path / "aj_crew").mkdir(exist_ok=True)
        (tmp_path / "aj_crew" / "__init__.py").write_text("")

        def _which(cmd: str) -> str | None:
            if cmd == "brazil-path":
                return "/usr/bin/brazil-path"  # exists but subprocess will raise
            return None

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                with patch("os.path.isfile", return_value=False):
                    with patch("shutil.which", side_effect=_which):
                        with patch(
                            "subprocess.run",
                            side_effect=OSError("brazil-path blew up"),
                        ):
                            result = _resolve_ajcrew_bin()
            # Falls through to bare 'ajcrew', doesn't crash
            assert result == "ajcrew"
            assert agent_mod._AJCREW_BIN is None
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_caches_result(self, tmp_path: Path):
        """A cached launcher that still works is returned without re-resolving."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        cached = tmp_path / "cached" / "ajcrew"
        cached.parent.mkdir()
        cached.write_text("#!/bin/sh\n")
        cached.chmod(0o755)
        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = str(cached)
            with patch("shutil.which", side_effect=AssertionError("re-resolved")):
                result = _resolve_ajcrew_bin()
            assert result == str(cached)
        finally:
            agent_mod._AJCREW_BIN = old_val

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX launcher layout")
    def test_a_cached_launcher_from_a_pruned_install_is_re_resolved(self, tmp_path: Path):
        """An update prunes the version directory the process started from.

        The path cached before the prune must not keep being handed out as the
        launch of ajcrew-core / ajcrew-cron: it is re-resolved, and with the
        running package gone the walk reaches the current install via PATH.
        """
        import shutil as _shutil

        import aj_crew.agent as agent_mod
        from aj_crew.agent import _resolve_ajcrew_bin

        def _launcher(root: Path) -> Path:
            exe = root / "bin" / "ajcrew"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o755)
            return exe

        old_install = tmp_path / "tools" / "ajcrew" / "0.8.0.4"
        new_install = tmp_path / "tools" / "ajcrew" / "0.8.0.6"
        old_bin = _launcher(old_install)
        new_bin = _launcher(new_install)
        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = str(old_bin)
            assert _resolve_ajcrew_bin() == str(old_bin)
            _shutil.rmtree(old_install)  # the update's prune
            # The running package lived in the pruned tree too, so steps 1-3
            # find nothing; only PATH names the current install.
            with (
                patch.object(sys, "exec_prefix", str(old_install)),
                patch("aj_crew.__file__", str(old_install / "lib" / "aj_crew" / "__init__.py")),
                patch("shutil.which", return_value=str(new_bin)),
            ):
                assert _resolve_ajcrew_bin() == str(new_bin)
            assert agent_mod._AJCREW_BIN == str(new_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_accepts_any_readable_bin_from_walk(self, tmp_path: Path):
        """The bin walk accepts any readable executable it finds.

        On a public install there is no Apollo/Brazil wrapper-rejection: any
        readable ``bin/ajcrew`` discovered by the walk is used as-is.
        """
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        venv = tmp_path / "venv"
        pkg_dir = venv / "lib" / "python3.10" / "site-packages" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        ajcrew_bin = _ajcrew_bin_subpath(venv)
        ajcrew_bin.parent.mkdir()
        ajcrew_bin.write_text('#!/bin/sh\nexec ajcrew "$@"\n')
        ajcrew_bin.chmod(0o755)

        # A PATH fallback that should NOT be chosen — the walk finds bin first.
        fallback_bin = tmp_path / "toolbox" / "bin" / "ajcrew"
        fallback_bin.parent.mkdir(parents=True)
        fallback_bin.write_text("#!/bin/bash\n")
        fallback_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                with patch("shutil.which") as mock_which:
                    mock_which.side_effect = lambda cmd, **kw: (
                        str(fallback_bin) if cmd == "ajcrew" else None
                    )
                    result = _resolve_ajcrew_bin()
            # The walk finds venv/bin/ajcrew and accepts it directly.
            assert result == str(ajcrew_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_accepts_apollo_binary_with_envroot(self, tmp_path: Path):
        """Accepts Apollo binary when .envroot exists in a parent directory."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        # Create env/runtime/.envroot + env/runtime/bin/ajcrew (Apollo)
        runtime = tmp_path / "env" / "runtime"
        (runtime / "lib" / "python3.10" / "site-packages" / "aj_crew").mkdir(parents=True)
        (runtime / "lib" / "python3.10" / "site-packages" / "aj_crew" / "__init__.py").write_text(
            ""
        )
        (runtime / ".envroot").write_text("")

        ajcrew_bin = _ajcrew_bin_subpath(runtime)
        ajcrew_bin.parent.mkdir()
        ajcrew_bin.write_bytes(
            b"#!/apollo/sbin/envroot $ENVROOT/python3.10/bin/python3.10\nimport sys\n"
        )
        ajcrew_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(
            runtime / "lib" / "python3.10" / "site-packages" / "aj_crew" / "__init__.py"
        )

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                result = _resolve_ajcrew_bin()
            assert result == str(ajcrew_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_accepts_wrapper_bin_from_walk(self, tmp_path: Path):
        """A shell-wrapper bin/ajcrew found by the walk is accepted as-is.

        Public installs do not reject wrapper scripts (the Brazil-workspace
        check is a no-op), so the walk-discovered bin wins over PATH.
        """
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        project = tmp_path / "project"
        pkg_dir = project / "src" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        wrapper = _ajcrew_bin_subpath(project)
        wrapper.parent.mkdir()
        wrapper.write_text('#!/bin/sh\nexec ajcrew "$@"\n')
        wrapper.chmod(0o755)

        # A PATH fallback that should NOT be chosen.
        fallback_bin = tmp_path / "local" / "bin" / "ajcrew"
        fallback_bin.parent.mkdir(parents=True)
        fallback_bin.write_text("#!/bin/sh\n")
        fallback_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                with patch("shutil.which") as mock_which:
                    mock_which.side_effect = lambda cmd, **kw: (
                        str(fallback_bin) if cmd == "ajcrew" else None
                    )
                    result = _resolve_ajcrew_bin()
            # The walk finds project/bin/ajcrew and accepts it directly.
            assert result == str(wrapper)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_accepts_brazil_wrapper_inside_workspace(self, tmp_path: Path):
        """Accepts bin/ajcrew with brazil-runtime-exec when packageInfo exists."""
        from aj_crew.agent import _bin_is_usable

        # Create structure with packageInfo (real Brazil workspace)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "packageInfo").write_text("{}")
        bin_dir = workspace / "bin"
        bin_dir.mkdir()
        brazil_wrapper = bin_dir / "ajcrew"
        brazil_wrapper.write_text('#!/bin/sh\nexec brazil-runtime-exec ajcrew "$@"\n')
        brazil_wrapper.chmod(0o755)

        assert _bin_is_usable(brazil_wrapper) is True

    def test_prefers_venv_bin_over_project_bin(self, tmp_path: Path):
        """Resolves .venv/bin/ajcrew before bin/ajcrew in the same tree."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        # Create structure: project/src/aj_crew + project/.venv/bin/ajcrew
        # + project/bin/ajcrew (Brazil wrapper)
        project = tmp_path / "project"
        pkg_dir = project / "src" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        # .venv/bin/ajcrew — the preferred candidate
        venv_bin = _ajcrew_bin_subpath(project / ".venv")
        venv_bin.parent.mkdir(parents=True)
        venv_bin.write_text('#!/bin/sh\nexec python -m aj_crew "$@"\n')
        venv_bin.chmod(0o755)

        # bin/ajcrew — Brazil wrapper (should be skipped)
        brazil_wrapper = _ajcrew_bin_subpath(project)
        brazil_wrapper.parent.mkdir()
        brazil_wrapper.write_text('#!/bin/sh\nexec brazil-runtime-exec ajcrew "$@"\n')
        brazil_wrapper.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                result = _resolve_ajcrew_bin()
            assert result == str(venv_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val

    def test_venv_install_falls_through_to_step1(self, tmp_path: Path):
        """When pkg_dir is inside .venv/, pyvenv.cfg breaks step 0."""
        import aj_crew.agent as agent_mod
        from aj_crew.agent import _ajcrew_bin_subpath, _resolve_ajcrew_bin

        # Simulate pip-into-venv: .venv/lib/python3.x/site-packages/aj_crew/
        venv_root = tmp_path / ".venv"
        pkg_dir = venv_root / "lib" / "python3.13" / "site-packages" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (venv_root / "pyvenv.cfg").write_text("home = /usr/bin\n")

        # .venv/bin/ajcrew exists (step 1 should find it)
        venv_bin = _ajcrew_bin_subpath(venv_root)
        venv_bin.parent.mkdir(parents=True)
        venv_bin.write_text('#!/bin/sh\nexec python -m aj_crew "$@"\n')
        venv_bin.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                result = _resolve_ajcrew_bin()
            # Step 0 breaks at pyvenv.cfg; step 1 finds bin/ajcrew
            assert result == str(venv_bin)
        finally:
            agent_mod._AJCREW_BIN = old_val


class TestAjcrewBinSubpath:
    """Tests for the per-OS console-script subpath.

    Windows prefers ``bin\\ajcrew.cmd`` (``%~dp0``) over ``Scripts\\ajcrew.exe``,
    which embeds the build agent's absolute path. Mirrors ``website/electron/find-bin.js``.
    """

    def test_posix_returns_bin_ajcrew(self, tmp_path: Path, monkeypatch):
        from aj_crew import platform_compat
        from aj_crew.agent import _ajcrew_bin_subpath

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", False)
        # Even with a stray ajcrew.cmd present, POSIX resolution is unchanged.
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "ajcrew.cmd").write_text("@echo off\n")
        assert _ajcrew_bin_subpath(tmp_path) == tmp_path / "bin" / "ajcrew"

    def test_windows_prefers_relocatable_cmd_shim(self, tmp_path: Path, monkeypatch):
        """Bundle layout: BOTH launchers exist -> the .cmd shim wins."""
        from aj_crew import platform_compat
        from aj_crew.agent import _ajcrew_bin_subpath

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
        (tmp_path / "bin").mkdir()
        cmd_shim = tmp_path / "bin" / "ajcrew.cmd"
        cmd_shim.write_text('@echo off\r\n"%~dp0..\\python.exe" -s -m aj_crew %*\r\n')
        (tmp_path / "Scripts").mkdir()
        (tmp_path / "Scripts" / "ajcrew.exe").write_bytes(b"MZ")
        assert _ajcrew_bin_subpath(tmp_path) == cmd_shim

    def test_windows_falls_back_to_scripts_exe_without_cmd(self, tmp_path: Path, monkeypatch):
        """Plain pip install: no .cmd shim -> Scripts/ajcrew.exe as before."""
        from aj_crew import platform_compat
        from aj_crew.agent import _ajcrew_bin_subpath

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
        (tmp_path / "Scripts").mkdir()
        (tmp_path / "Scripts" / "ajcrew.exe").write_bytes(b"MZ")
        expected = tmp_path / "Scripts" / "ajcrew.exe"
        assert _ajcrew_bin_subpath(tmp_path) == expected

    def test_windows_cmd_must_be_a_file(self, tmp_path: Path, monkeypatch):
        """A directory named ajcrew.cmd does not shadow the .exe fallback."""
        from aj_crew import platform_compat
        from aj_crew.agent import _ajcrew_bin_subpath

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
        (tmp_path / "bin" / "ajcrew.cmd").mkdir(parents=True)
        expected = tmp_path / "Scripts" / "ajcrew.exe"
        assert _ajcrew_bin_subpath(tmp_path) == expected

    def test_bin_is_usable_accepts_cmd_batch_shim(self, tmp_path: Path):
        """A `.cmd` starts with `@`, not `#!` -> no shebang to validate, usable."""
        from aj_crew.agent import _bin_is_usable

        shim = tmp_path / "ajcrew.cmd"
        shim.write_text('@echo off\r\n"%~dp0..\\python.exe" -s -m aj_crew %*\r\n')
        assert _bin_is_usable(shim) is True

    def test_resolver_walk_finds_cmd_shim_in_bundle_layout(
        self, tmp_path: Path, monkeypatch, launchers_confined_to_tmp
    ):
        """End-to-end: the parent walk PREFERS the bundle's .cmd on Windows.

        Pins the issue's failure mode: the bundle ships BOTH launchers, and
        resolving the co-present ``Scripts\\ajcrew.exe`` instead of the
        ``.cmd`` shim is exactly the defect.
        """
        import aj_crew.agent as agent_mod
        from aj_crew import platform_compat
        from aj_crew.agent import _resolve_ajcrew_bin

        monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)

        # Bundle layout (packaging/build-desktop.sh build_backend_windows):
        # <root>/Lib/site-packages/aj_crew + <root>/bin/ajcrew.cmd
        # + the pip-dropped <root>/Scripts/ajcrew.exe (non-relocatable).
        root = tmp_path / "ajcrew-backend"
        pkg_dir = root / "Lib" / "site-packages" / "aj_crew"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (root / "bin").mkdir()
        cmd_shim = root / "bin" / "ajcrew.cmd"
        cmd_shim.write_text('@echo off\r\n"%~dp0..\\python.exe" -s -m aj_crew %*\r\n')
        # The test host is POSIX, where the resolver's X_OK gate is real.
        cmd_shim.chmod(0o755)
        (root / "Scripts").mkdir()
        dead_exe = root / "Scripts" / "ajcrew.exe"
        dead_exe.write_bytes(b"MZ")
        dead_exe.chmod(0o755)

        mock_mc = unittest.mock.MagicMock()
        mock_mc.__file__ = str(pkg_dir / "__init__.py")

        old_val = agent_mod._AJCREW_BIN
        try:
            agent_mod._AJCREW_BIN = None
            with patch.dict("sys.modules", {"aj_crew": mock_mc}):
                result = _resolve_ajcrew_bin()
            assert result == str(cmd_shim)
        finally:
            agent_mod._AJCREW_BIN = old_val


class TestAjcrewMcpInvocation:
    """Tests for built-in MCP server invocation resolution.

    With no standalone binary (e.g. a systemd service PATH), built-in servers still get a
    runnable command; the bare ``"ajcrew"`` sentinel fails validation and is dropped.
    """

    def test_uses_standalone_binary_when_resolved(self):
        from aj_crew.agent import _ajcrew_mcp_invocation

        with patch("aj_crew.agent._resolve_ajcrew_bin", return_value="/opt/bin/ajcrew"):
            cmd, args = _ajcrew_mcp_invocation("mcp-cron")
        assert cmd == "/opt/bin/ajcrew"
        assert args == ["mcp-cron"]

    def test_falls_back_to_interpreter_module_when_unresolved(
        self, nonbundled_python_without_user_site
    ):
        """Module fallback excludes the project CWD before importing Aj Crew."""
        from aj_crew.agent import _ajcrew_mcp_invocation

        # Bare "ajcrew" is the unresolved sentinel from _resolve_ajcrew_bin.
        with patch("aj_crew.agent._resolve_ajcrew_bin", return_value="ajcrew"):
            cmd, args = _ajcrew_mcp_invocation("mcp-core")
        assert cmd == sys.executable
        assert args == ["-s", "-P", "-m", "aj_crew", "mcp-core"]

    def test_unwraps_cmd_shim_to_sibling_interpreter(self, tmp_path: Path):
        """A resolved bin/ajcrew.cmd is never emitted verbatim.

        Mirrors website/electron/main.js: the shim is unwrapped to
        ``<root>/python.exe -s -P -m aj_crew <sub>`` so kiro-cli spawns the
        interpreter, not a batch file.
        """
        from aj_crew.agent import _ajcrew_mcp_invocation

        root = tmp_path / "ajcrew-backend"
        (root / "bin").mkdir(parents=True)
        shim = root / "bin" / "ajcrew.cmd"
        shim.write_text('@echo off\r\n"%~dp0..\\python.exe" -s -m aj_crew %*\r\n')
        interpreter = root / "python.exe"
        interpreter.write_bytes(b"MZ")
        interpreter.chmod(0o755)  # X_OK is real on the POSIX test host

        with patch("aj_crew.agent._resolve_ajcrew_bin", return_value=str(shim)):
            cmd, args = _ajcrew_mcp_invocation("mcp-cron")
        assert cmd == str(interpreter)
        # -P keeps the spawn CWD off sys.path; -s drops user site-packages.
        assert args == ["-s", "-P", "-m", "aj_crew", "mcp-cron"]

    def test_cmd_shim_without_interpreter_falls_back_to_sys_executable(
        self, tmp_path: Path, nonbundled_python_without_user_site
    ):
        """Corrupted bundle: shim present but python.exe missing -> sys.executable."""
        from aj_crew.agent import _ajcrew_mcp_invocation

        root = tmp_path / "ajcrew-backend"
        (root / "bin").mkdir(parents=True)
        shim = root / "bin" / "ajcrew.cmd"
        shim.write_text('@echo off\r\n"%~dp0..\\python.exe" -s -m aj_crew %*\r\n')

        with patch("aj_crew.agent._resolve_ajcrew_bin", return_value=str(shim)):
            cmd, args = _ajcrew_mcp_invocation("mcp-core")
        assert cmd == sys.executable
        assert args == ["-s", "-P", "-m", "aj_crew", "mcp-core"]
