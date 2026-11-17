"""Unit tests for TaskScopedGrantStore, SafePatternGrantStore, and Ed25519 session_pid verification."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aj_crew import platform_compat, session_pid_sig
from aj_crew.safe_pattern_grants import (
    GrantNotSafeEligibleError,
    SafePatternGrantStore,
)
from aj_crew.task_scoped_grants import (
    InvalidTaskGrantError,
    TaskScopedGrantStore,
)


def test_task_scoped_grant_matches_only_same_session_and_task_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aj_crew.task_scoped_grants.session_mode_permitted", lambda _m: True)
    now = 100.0
    store = TaskScopedGrantStore(clock=lambda: now)

    grant = store.mint(
        session_key="dashboard:chat-1",
        task_epoch_id="epoch-a",
        canonical_tool_id="fs_write",
        capability_class="write",
        scope_prefix="/repo/src/module",
        ttl_secs=600.0,
    )
    assert grant.is_mutating is True

    # Matches inside same session, same epoch, and sub-path under scope_prefix.
    assert (
        store.matches(
            session_key="dashboard:chat-1",
            task_epoch_id="epoch-a",
            canonical_tool_id="fs_write",
            capability_class="write",
            target_scope="/repo/src/module/file.py",
        )
        is not None
    )
    # Never bleeds to another session or another task epoch or outside scope_prefix.
    assert (
        store.matches(
            session_key="dashboard:chat-2",
            task_epoch_id="epoch-a",
            canonical_tool_id="fs_write",
            capability_class="write",
            target_scope="/repo/src/module/file.py",
        )
        is None
    )
    assert (
        store.matches(
            session_key="dashboard:chat-1",
            task_epoch_id="epoch-b",
            canonical_tool_id="fs_write",
            capability_class="write",
            target_scope="/repo/src/module/file.py",
        )
        is None
    )
    assert (
        store.matches(
            session_key="dashboard:chat-1",
            task_epoch_id="epoch-a",
            canonical_tool_id="fs_write",
            capability_class="write",
            target_scope="/repo/other/file.py",
        )
        is None
    )

    # Expires cleanly at monotonic TTL.
    now = 701.0
    assert (
        store.matches(
            session_key="dashboard:chat-1",
            task_epoch_id="epoch-a",
            canonical_tool_id="fs_write",
            capability_class="write",
            target_scope="/repo/src/module/file.py",
        )
        is None
    )


def test_task_scoped_grant_refuses_wildcards_computer_use_and_policy_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aj_crew.task_scoped_grants.session_mode_permitted", lambda _m: True)
    store = TaskScopedGrantStore()

    with pytest.raises(InvalidTaskGrantError):
        store.mint(
            session_key="s1",
            task_epoch_id="e1",
            canonical_tool_id="*",
            capability_class="read",
            scope_prefix="/repo",
        )
    with pytest.raises(InvalidTaskGrantError):
        store.mint(
            session_key="s1",
            task_epoch_id="e1",
            canonical_tool_id="fs_read",
            capability_class="read",
            scope_prefix="/repo/*",
        )
    with pytest.raises(InvalidTaskGrantError):
        store.mint(
            session_key="s1",
            task_epoch_id="e1",
            canonical_tool_id="computer",
            capability_class="computer_use",
            scope_prefix="/screen",
        )

    store.mint(
        session_key="s1",
        task_epoch_id="e1",
        canonical_tool_id="fs_write",
        capability_class="write",
        scope_prefix="/repo/src",
    )
    store.mint(
        session_key="s1",
        task_epoch_id="e1",
        canonical_tool_id="fs_read",
        capability_class="read",
        scope_prefix="/repo/src",
    )
    # Revoking 'trust' purges mutating grants while preserving read grants.
    assert store.revoke_denied_modes(frozenset({"trust"})) == 1
    assert (
        store.matches(
            session_key="s1",
            task_epoch_id="e1",
            canonical_tool_id="fs_write",
            capability_class="write",
            target_scope="/repo/src/a.py",
        )
        is None
    )
    assert (
        store.matches(
            session_key="s1",
            task_epoch_id="e1",
            canonical_tool_id="fs_read",
            capability_class="read",
            target_scope="/repo/src/a.py",
        )
        is not None
    )


def test_safe_pattern_grants_enforce_readonly_and_binary_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("aj_crew.safe_pattern_grants.session_mode_permitted", lambda _m: True)
    shadowed = False
    store = SafePatternGrantStore(
        base_dir=tmp_path,
        clock=lambda: 1700000000.0,
        shell_refused=lambda _cmd: shadowed,
    )

    # Mutating / computer_use / shell redirects are unconditionally refused!
    for bad_cap in ("write", "edit", "delete", "computer_use", "network"):
        with pytest.raises(GrantNotSafeEligibleError):
            store.mint_grant(
                canonical_tool_id="fs_write",
                capability_class=bad_cap,
                pattern="/repo/src",
            )
    with pytest.raises(GrantNotSafeEligibleError):
        store.mint_grant(
            canonical_tool_id="bash",
            capability_class="shell_readonly",
            pattern="git status",
            sample_command="git status > /tmp/pwn",
        )

    # Legitimate read-only git status mints and persists cleanly.
    g = store.mint_grant(
        canonical_tool_id="bash",
        capability_class="shell_readonly",
        pattern="git status",
        workspace_prefix=str(tmp_path / "repo"),
        sample_command="git status",
    )
    assert (tmp_path / "approval-grants" / "grants.json").is_file()
    assert (
        store.matches_grant(
            canonical_tool_id="bash",
            capability_class="shell_readonly",
            target="git status",
            workspace=str(tmp_path / "repo" / "sub"),
        )
        == g
    )
    # Shell injection / redirect on match fails closed!
    assert (
        store.matches_grant(
            canonical_tool_id="bash",
            capability_class="shell_readonly",
            target="git status && rm -rf /",
            workspace=str(tmp_path / "repo"),
        )
        is None
    )
    # Binary shadowing reported by name_grant fails closed!
    shadowed = True
    assert (
        store.matches_grant(
            canonical_tool_id="bash",
            capability_class="shell_readonly",
            target="git status",
            workspace=str(tmp_path / "repo"),
        )
        is None
    )


def test_ed25519_session_pid_verifies_when_sel_hmac_key_is_sandbox_masked(
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "sel_hmac.key"
    key_file.write_bytes(b"\x42" * 32)
    with (
        patch.object(session_pid_sig, "config_dir", return_value=tmp_path),
        patch.object(session_pid_sig, "_sel_hmac_key_bytes", return_value=None),
        patch.object(platform_compat, "get_process_start_id", return_value="start-tok-1"),
        patch.object(session_pid_sig, "sel_hmac_key_path", return_value=key_file),
    ):
        session_pid_sig.publish_session_pid(7777, "dashboard:sandboxed-slot")
        assert (tmp_path / "session-pid-verify" / "ed25519.pub").is_file()
        assert (tmp_path / "session-pid-verify" / "session_pid_7777.ed25519").is_file()

        # Simulate OS sandbox unreadable mask (PermissionError on sel_hmac.key)!
        with (
            patch.object(session_pid_sig, "_load_hmac_key", return_value=None),
            patch.object(session_pid_sig, "_sel_key_read_denied", return_value=True),
        ):
            assert session_pid_sig.verify_session_pid(7777) == "dashboard:sandboxed-slot"

            # Forgery of session_pid_7777.txt inside the sandbox fails Ed25519 verification!
            (tmp_path / "session_pid_7777.txt").write_text(
                "dashboard:forged-victim\nstart-tok-1", encoding="utf-8"
            )
            assert session_pid_sig.verify_session_pid(7777) == ""


def test_hook_gate_scoped_grants_never_bypass_denied_rules_or_governance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    from aj_crew.hooks import TOOL_AUTO_APPROVE, TOOL_DENY, HookManager
    from aj_crew.platform import context as ctx_mod
    from aj_crew.platform.bootstrap import build_default_context
    from aj_crew.platform.governance import parse_policy
    from aj_crew.task_scoped_grants import default_task_grant_store

    monkeypatch.setenv("AJCREW_HOME", str(tmp_path))
    monkeypatch.setattr("aj_crew.task_scoped_grants.session_mode_permitted", lambda _m: True)
    store = default_task_grant_store()
    store.clear()
    try:
        store.mint(
            session_key="dashboard:s1",
            task_epoch_id="ep-1",
            canonical_tool_id="fs_write",
            capability_class="write",
            scope_prefix=str(tmp_path / "workspace"),
        )
        store.mint(
            session_key="dashboard:s1",
            task_epoch_id="ep-1",
            canonical_tool_id="bash",
            capability_class="shell_mutating",
            scope_prefix=str(tmp_path / "workspace"),
        )
        hm = HookManager()

        # Benign in-scope write auto-approves via scoped-grants tier.
        ok_verdict = hm.on_tool_call(
            "Write file",
            session_key="dashboard:s1",
            task_epoch_id="ep-1",
            workspace_cwd=str(tmp_path / "workspace"),
            tool_kind="edit",
            raw_params={"path": str(tmp_path / "workspace" / "app.py")},
            mcp_tool_name="fs_write",
            mcp_identity_trusted=True,
        )
        assert (ok_verdict.action, ok_verdict.tier) == (TOOL_AUTO_APPROVE, "scoped-grants")

        # Built-in denied_rules ALWAYS defeat a task-scoped bash grant.
        deny_verdict = hm.on_tool_call(
            "Running: rm -rf /",
            session_key="dashboard:s1",
            task_epoch_id="ep-1",
            workspace_cwd=str(tmp_path / "workspace"),
            is_shell=True,
            command="rm -rf /",
        )
        assert (deny_verdict.action, deny_verdict.tier) == (TOOL_DENY, "deny-rules")

        # Governance POLICY ∩ PROFILE ceiling ALWAYS defeats a task-scoped write grant.
        from aj_crew.config.loader import AjCrewConfig

        base = build_default_context(AjCrewConfig.load())
        policy = parse_policy(
            {
                "version": 1,
                "boot": {"fail_closed": True},
                "filesystem": {
                    "write": {
                        "mode": "deny",
                        "deny": [str(tmp_path / "workspace" / "secret*")],
                    }
                },
            }
        )
        ctx_mod.set_context(dataclasses.replace(base, governance=policy))
        try:
            gov_verdict = hm.on_tool_call(
                "Write secret",
                session_key="dashboard:s1",
                task_epoch_id="ep-1",
                workspace_cwd=str(tmp_path / "workspace"),
                tool_kind="edit",
                raw_params={"path": str(tmp_path / "workspace" / "secret_notes.txt")},
                mcp_tool_name="fs_write",
                mcp_identity_trusted=True,
            )
            assert (gov_verdict.action, gov_verdict.tier) == (TOOL_DENY, "governance")
        finally:
            ctx_mod.reset_context()
    finally:
        store.clear()
