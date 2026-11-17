"""Task-scoped approval grants: bounded to one ``(session_key, task_epoch_id)``.

Grants minted with "Approve for this task" authorize repeating the SAME
``(canonical_tool_id, capability_class, scope_prefix)`` within the active task
or subagent wave only, expiring automatically when the task finishes, after the
2-hour monotonic ceiling, or immediately when enterprise policy revokes session
trust modes (:mod:`aj_crew.approval_mode_policy`). Wildcard ``"*"`` grants are
refused at mint and match time.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from aj_crew.approval_mode_policy import (
    register_deny_hook,
    register_reset_hook,
    session_mode_permitted,
)

MAX_TASK_GRANT_TTL_SECS: float = 7200.0

READ_ONLY_CAPABILITY_CLASSES: frozenset[str] = frozenset(
    {
        "read",
        "search",
        "glob",
        "grep",
        "list_dir",
        "inspect_readonly",
        "shell_readonly",
    }
)

MUTATING_CAPABILITY_CLASSES: frozenset[str] = frozenset(
    {
        "write",
        "edit",
        "delete",
        "shell_mutating",
        "mcp_mutating",
    }
)

FORBIDDEN_TASK_CAPABILITY_CLASSES: frozenset[str] = frozenset(
    {
        "computer_use",
        "credential_access",
        "ceiling_write",
    }
)


class InvalidTaskGrantError(ValueError):
    """Raised when a task-scoped grant request violates safety bounds."""


def _normalize_scope_prefix(scope_prefix: str) -> str:
    cleaned = str(scope_prefix or "").strip()
    if not cleaned or cleaned == "*" or "*" in cleaned:
        raise InvalidTaskGrantError(
            f"task-scoped grants require an explicit non-wildcard scope prefix, got {scope_prefix!r}"
        )
    normed = os.path.normpath(cleaned).replace("\\", "/")
    if os.name == "nt":
        normed = normed.lower()
    return normed.rstrip("/") or "/"


def _scope_covered(candidate: str, granted_prefix: str) -> bool:
    if not candidate or "*" in candidate:
        return False
    norm_cand = os.path.normpath(candidate.strip()).replace("\\", "/")
    if os.name == "nt":
        norm_cand = norm_cand.lower()
    norm_cand = norm_cand.rstrip("/") or "/"
    if granted_prefix == "/":
        return False
    return norm_cand == granted_prefix or norm_cand.startswith(f"{granted_prefix}/")


@dataclass(frozen=True)
class TaskScopedGrant:
    """In-memory grant scoped strictly to ``(session_key, task_epoch_id)``."""

    grant_id: str
    session_key: str
    task_epoch_id: str
    canonical_tool_id: str
    capability_class: str
    scope_prefix: str
    created_mono: float
    expires_mono: float

    @property
    def is_mutating(self) -> bool:
        return self.capability_class not in READ_ONLY_CAPABILITY_CLASSES


class TaskScopedGrantStore:
    """Thread-safe ephemeral store of task-scoped approval grants."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._by_epoch: dict[tuple[str, str], dict[str, TaskScopedGrant]] = {}

    def mint(
        self,
        *,
        session_key: str,
        task_epoch_id: str,
        canonical_tool_id: str,
        capability_class: str,
        scope_prefix: str,
        ttl_secs: float = MAX_TASK_GRANT_TTL_SECS,
    ) -> TaskScopedGrant:
        """Mint a bounded grant for ``(session_key, task_epoch_id)``."""
        s_key = str(session_key or "").strip()
        t_epoch = str(task_epoch_id or "").strip()
        tool_id = str(canonical_tool_id or "").strip()
        cap = str(capability_class or "").strip()
        if not s_key or not t_epoch:
            raise InvalidTaskGrantError("session_key and task_epoch_id must be non-empty")
        if not tool_id or tool_id == "*" or "*" in tool_id:
            raise InvalidTaskGrantError(f"wildcard or empty canonical_tool_id refused: {tool_id!r}")
        if cap in FORBIDDEN_TASK_CAPABILITY_CLASSES:
            raise InvalidTaskGrantError(f"capability_class {cap!r} cannot be task-granted")
        if cap not in READ_ONLY_CAPABILITY_CLASSES and cap not in MUTATING_CAPABILITY_CLASSES:
            raise InvalidTaskGrantError(f"unknown capability_class: {cap!r}")

        required_mode = "trust_reads" if cap in READ_ONLY_CAPABILITY_CLASSES else "trust"
        if not session_mode_permitted(required_mode):
            raise InvalidTaskGrantError(
                f"governance ceiling currently denies approval mode {required_mode!r}"
            )

        norm_prefix = _normalize_scope_prefix(scope_prefix)
        clamped_ttl = min(MAX_TASK_GRANT_TTL_SECS, max(1.0, float(ttl_secs)))
        now = self._clock()
        grant = TaskScopedGrant(
            grant_id=uuid.uuid4().hex[:16],
            session_key=s_key,
            task_epoch_id=t_epoch,
            canonical_tool_id=tool_id,
            capability_class=cap,
            scope_prefix=norm_prefix,
            created_mono=now,
            expires_mono=now + clamped_ttl,
        )
        with self._lock:
            bucket = self._by_epoch.setdefault((s_key, t_epoch), {})
            bucket[grant.grant_id] = grant
        return grant

    def matches(
        self,
        *,
        session_key: str,
        task_epoch_id: str,
        canonical_tool_id: str,
        capability_class: str,
        target_scope: str,
    ) -> TaskScopedGrant | None:
        """Return the matching live grant if permitted by policy, else ``None``."""
        s_key = str(session_key or "").strip()
        t_epoch = str(task_epoch_id or "").strip()
        tool_id = str(canonical_tool_id or "").strip()
        cap = str(capability_class or "").strip()
        if not s_key or not t_epoch or not tool_id or not cap:
            return None
        required_mode = "trust_reads" if cap in READ_ONLY_CAPABILITY_CLASSES else "trust"
        if not session_mode_permitted(required_mode):
            return None

        now = self._clock()
        with self._lock:
            bucket = self._by_epoch.get((s_key, t_epoch))
            if not bucket:
                return None
            expired_ids = [gid for gid, g in bucket.items() if now >= g.expires_mono]
            for gid in expired_ids:
                bucket.pop(gid, None)
            if not bucket:
                self._by_epoch.pop((s_key, t_epoch), None)
                return None
            for grant in bucket.values():
                if (
                    grant.canonical_tool_id == tool_id
                    and grant.capability_class == cap
                    and _scope_covered(target_scope, grant.scope_prefix)
                ):
                    return grant
        return None

    def revoke_task(self, session_key: str, task_epoch_id: str) -> int:
        """Drop all grants for one completed/cancelled task epoch."""
        with self._lock:
            popped = self._by_epoch.pop((str(session_key), str(task_epoch_id)), None)
            return len(popped) if popped else 0

    def revoke_session(self, session_key: str) -> int:
        """Drop all grants across every task epoch of *session_key*."""
        target = str(session_key)
        removed = 0
        with self._lock:
            keys = [k for k in self._by_epoch if k[0] == target]
            for key in keys:
                removed += len(self._by_epoch.pop(key, ()))
        return removed

    def revoke_denied_modes(self, denied_modes: frozenset[str]) -> int:
        """Purge stored grants whose backing trust mode was denied by policy."""
        drop_reads = "trust_reads" in denied_modes
        drop_mutating = "trust" in denied_modes
        if not drop_reads and not drop_mutating:
            return 0
        removed = 0
        with self._lock:
            for epoch_key in list(self._by_epoch):
                bucket = self._by_epoch[epoch_key]
                to_delete = [
                    gid
                    for gid, grant in bucket.items()
                    if (grant.is_mutating and drop_mutating)
                    or (not grant.is_mutating and drop_reads)
                ]
                for gid in to_delete:
                    bucket.pop(gid, None)
                    removed += 1
                if not bucket:
                    self._by_epoch.pop(epoch_key, None)
        return removed

    def _on_policy_deny(self, denied_modes: frozenset[str]) -> None:
        self.revoke_denied_modes(denied_modes)

    def clear(self) -> None:
        with self._lock:
            self._by_epoch.clear()


_DEFAULT_STORE = TaskScopedGrantStore()
register_deny_hook("task_scoped_grants", _DEFAULT_STORE._on_policy_deny)
register_reset_hook("task_scoped_grants", _DEFAULT_STORE.clear)


def default_task_grant_store() -> TaskScopedGrantStore:
    return _DEFAULT_STORE


_BUILTIN_READ_TOOL_IDS: frozenset[str] = frozenset({"fs_read", "read", "read_file", "Read"})
_BUILTIN_GLOB_TOOL_IDS: frozenset[str] = frozenset({"glob", "Glob"})
_BUILTIN_GREP_TOOL_IDS: frozenset[str] = frozenset({"grep", "Grep"})
_BUILTIN_WRITE_TOOL_IDS: frozenset[str] = frozenset(
    {"fs_write", "write", "str_replace", "fs_append", "Edit", "Write"}
)


def _extract_first_path_param(raw_params: object) -> str:
    if not isinstance(raw_params, dict):
        return ""
    for key in ("path", "file_path", "filePath", "directory", "target"):
        val = raw_params.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list) and len(val) == 1 and isinstance(val[0], str) and val[0].strip():
            return val[0].strip()
    return ""


def derive_scoped_grant_subject(
    call: object, *, workspace_cwd: str = ""
) -> tuple[str, str, str, str] | None:
    """Derive ``(canonical_tool_id, capability_class, target_scope, safe_target)`` for *call*.

    Returns ``None`` whenever the call lacks a proven identity or targets a
    forbidden class (e.g. ``computer_use``), so the scoped-grants tier steps aside.
    """
    from aj_crew.safe_pattern_grants import _is_safe_readonly_shell_command

    mcp_server = str(getattr(call, "mcp_server", "") or "").strip()
    mcp_tool = str(getattr(call, "mcp_tool", "") or "").strip()
    title = str(getattr(call, "title", "") or "").strip()
    if (
        "ajcrew-computer" in mcp_server
        or mcp_tool.startswith("computer_")
        or title.startswith("mcp__ajcrew-computer__")
    ):
        return None

    ws = str(workspace_cwd or getattr(call, "spec_write_cwd", "") or "").strip()
    is_shell = bool(getattr(call, "is_shell", False))
    command = getattr(call, "command", None)
    if is_shell and isinstance(command, str) and command.strip():
        ok, _ = _is_safe_readonly_shell_command(command)
        scope = ws or "/workspace"
        if ok:
            return ("bash", "shell_readonly", scope, command.strip())
        return ("bash", "shell_mutating", scope, "")

    identity_trusted = bool(getattr(call, "identity_trusted", False))
    raw_params = getattr(call, "raw_params", None)
    kind = str(getattr(call, "kind", "") or "").strip().lower()

    if identity_trusted and mcp_server and mcp_tool:
        tool_id = f"@{mcp_server}/{mcp_tool}"
        cap = "inspect_readonly" if kind in ("read", "fetch", "search") else "mcp_mutating"
        param_path = _extract_first_path_param(raw_params)
        scope = param_path or ws or f"/{mcp_server}"
        safe_target = scope if cap == "inspect_readonly" else ""
        return (tool_id, cap, scope, safe_target)

    harness_tool = str(getattr(call, "harness_builtin_tool", "") or "").strip()
    raw_builtin = mcp_tool if (identity_trusted and mcp_tool and not mcp_server) else harness_tool
    if not raw_builtin:
        return None

    if raw_builtin in _BUILTIN_READ_TOOL_IDS:
        tool_id, cap = "fs_read", "read"
    elif raw_builtin in _BUILTIN_GLOB_TOOL_IDS:
        tool_id, cap = "glob", "glob"
    elif raw_builtin in _BUILTIN_GREP_TOOL_IDS:
        tool_id, cap = "grep", "grep"
    elif (
        raw_builtin in _BUILTIN_WRITE_TOOL_IDS
        or kind == "edit"
        or bool(getattr(call, "diff_path", ""))
    ):
        tool_id, cap = "fs_write", "write"
    else:
        return None

    raw_path = (
        _extract_first_path_param(raw_params) or str(getattr(call, "diff_path", "") or "").strip()
    )
    if not raw_path or "*" in raw_path:
        return None
    expanded = os.path.expanduser(raw_path)
    is_anchored = os.path.isabs(expanded) or (
        expanded.startswith("/") and not expanded.startswith("//")
    )
    if not is_anchored:
        if not ws or not (os.path.isabs(ws) or ws.startswith("/")):
            return None
        expanded = os.path.join(ws, expanded)
    safe_target = expanded if cap in READ_ONLY_CAPABILITY_CLASSES else ""
    return (tool_id, cap, expanded, safe_target)
