"""Conflict-free workspace reader/writer leases for parallel multi-agent execution.

Parallel research/review waves (``mode="read"``) share a workspace concurrently
while no overlapping writer holds it. Parallel implementation waves
(``mode="write"``) run concurrently when their declared ``write_scope`` path
prefixes are disjoint, and serialize or surface a conflict when two writers claim
overlapping paths.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

LeaseMode = Literal["read", "write"]


def _canonical_workspace(cwd: str) -> str:
    expanded = os.path.expanduser(cwd.strip())
    return os.path.normcase(os.path.realpath(expanded))


def _normalize_scope(write_scope: Iterable[str] | None) -> tuple[str, ...]:
    """Normalize repo-relative path prefixes; ``("",)`` means the whole workspace."""
    if write_scope is None:
        return ("",)
    cleaned: list[str] = []
    for raw in write_scope:
        item = str(raw).strip().replace("\\", "/").strip("/")
        if not item or item == ".":
            return ("",)
        parts = [seg for seg in item.split("/") if seg and seg != "."]
        if any(seg == ".." for seg in parts):
            # Traversal outside the workspace conservatively locks the whole root.
            return ("",)
        norm = "/".join(parts)
        if os.name == "nt":
            norm = norm.lower()
        cleaned.append(norm)
    if not cleaned:
        return ("",)
    # Deduplicate and drop prefixes already covered by a broader ancestor prefix.
    unique = sorted(set(cleaned), key=lambda s: (s.count("/"), len(s), s))
    minimal: list[str] = []
    for candidate in unique:
        if any(_prefixes_overlap(existing, candidate) for existing in minimal):
            continue
        minimal.append(candidate)
    return tuple(minimal)


def _prefixes_overlap(a: str, b: str) -> bool:
    """True when prefix *a* and prefix *b* name the same subtree or one contains the other."""
    if a == "" or b == "" or a == b:
        return True
    return a.startswith(f"{b}/") or b.startswith(f"{a}/")


def _scopes_overlap(scope_a: tuple[str, ...], scope_b: tuple[str, ...]) -> bool:
    return any(_prefixes_overlap(a, b) for a in scope_a for b in scope_b)


@dataclass(frozen=True)
class WorkspaceLease:
    """An active reader or writer claim on a workspace subtree."""

    lease_id: str
    holder: str
    workspace: str
    mode: LeaseMode
    scope: tuple[str, ...]


@dataclass(frozen=True)
class LeaseAcquireOutcome:
    """Result of a non-blocking lease attempt, naming any conflicting holders."""

    lease: WorkspaceLease | None
    conflicts: tuple[WorkspaceLease, ...] = ()

    @property
    def granted(self) -> bool:
        return self.lease is not None


class WorkspaceWriteLeaseTable:
    """Process-wide reader/writer lock table keyed by canonical workspace + path prefixes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, WorkspaceLease] = {}
        self._by_workspace: dict[str, dict[str, WorkspaceLease]] = {}
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []

    def _conflicts_locked(
        self, workspace: str, mode: LeaseMode, scope: tuple[str, ...]
    ) -> list[WorkspaceLease]:
        active = self._by_workspace.get(workspace)
        if not active:
            return []
        conflicts: list[WorkspaceLease] = []
        for existing in active.values():
            if mode == "read" and existing.mode == "read":
                continue
            if _scopes_overlap(scope, existing.scope):
                conflicts.append(existing)
        return conflicts

    def try_acquire(
        self,
        cwd: str,
        *,
        holder: str,
        mode: LeaseMode = "read",
        write_scope: Iterable[str] | None = None,
    ) -> LeaseAcquireOutcome:
        """Attempt to acquire a workspace lease immediately without blocking."""
        if mode not in ("read", "write"):
            raise ValueError(f"invalid lease mode: {mode!r}")
        if not cwd or not cwd.strip():
            raise ValueError("cwd must be a non-empty workspace path")
        workspace = _canonical_workspace(cwd)
        scope = _normalize_scope(write_scope) if mode == "write" else _normalize_scope(write_scope)
        with self._lock:
            conflicts = self._conflicts_locked(workspace, mode, scope)
            if conflicts:
                return LeaseAcquireOutcome(lease=None, conflicts=tuple(conflicts))
            lease = WorkspaceLease(
                lease_id=uuid.uuid4().hex[:16],
                holder=str(holder),
                workspace=workspace,
                mode=mode,
                scope=scope,
            )
            self._by_id[lease.lease_id] = lease
            self._by_workspace.setdefault(workspace, {})[lease.lease_id] = lease
            return LeaseAcquireOutcome(lease=lease)

    async def acquire(
        self,
        cwd: str,
        *,
        holder: str,
        mode: LeaseMode = "read",
        write_scope: Iterable[str] | None = None,
        timeout: float | None = None,
    ) -> WorkspaceLease:
        """Acquire a workspace lease, waiting until conflicting holders release."""
        first = self.try_acquire(cwd, holder=holder, mode=mode, write_scope=write_scope)
        if first.lease is not None:
            return first.lease

        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        entry = (loop, wake)
        with self._lock:
            self._waiters.append(entry)
        deadline = None if timeout is None else loop.time() + max(0.0, float(timeout))
        try:
            while True:
                attempt = self.try_acquire(cwd, holder=holder, mode=mode, write_scope=write_scope)
                if attempt.lease is not None:
                    return attempt.lease
                wake.clear()
                attempt = self.try_acquire(cwd, holder=holder, mode=mode, write_scope=write_scope)
                if attempt.lease is not None:
                    return attempt.lease
                if deadline is not None:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        holders = ", ".join(c.holder for c in attempt.conflicts) or "unknown"
                        raise TimeoutError(
                            f"timed out acquiring {mode} workspace lease on {cwd!r} "
                            f"(held by {holders})"
                        )
                    await asyncio.wait_for(wake.wait(), timeout=remaining)
                else:
                    await wake.wait()
        finally:
            with self._lock:
                if entry in self._waiters:
                    self._waiters.remove(entry)

    def release(self, lease: WorkspaceLease | str | None) -> bool:
        """Release *lease* idempotently and wake any waiting readers/writers."""
        if lease is None:
            return False
        lid = lease.lease_id if isinstance(lease, WorkspaceLease) else str(lease)
        to_wake: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        with self._lock:
            removed = self._by_id.pop(lid, None)
            if removed is None:
                return False
            ws_map = self._by_workspace.get(removed.workspace)
            if ws_map is not None:
                ws_map.pop(lid, None)
                if not ws_map:
                    self._by_workspace.pop(removed.workspace, None)
            to_wake = list(self._waiters)
        for loop, ev in to_wake:
            if not loop.is_closed():
                loop.call_soon_threadsafe(ev.set)
        return True

    def active_leases_for(self, cwd: str | None = None) -> list[WorkspaceLease]:
        """List active leases (for *cwd* when given, else across all workspaces)."""
        with self._lock:
            if cwd is None:
                return list(self._by_id.values())
            workspace = _canonical_workspace(cwd)
            return list(self._by_workspace.get(workspace, {}).values())


_LEASES_LOCK = threading.Lock()
_SHARED_LEASES: WorkspaceWriteLeaseTable | None = None


def shared_workspace_leases() -> WorkspaceWriteLeaseTable:
    """Return the process-wide :class:`WorkspaceWriteLeaseTable` singleton."""
    global _SHARED_LEASES
    with _LEASES_LOCK:
        if _SHARED_LEASES is None:
            _SHARED_LEASES = WorkspaceWriteLeaseTable()
        return _SHARED_LEASES


def reset_shared_workspace_leases() -> WorkspaceWriteLeaseTable:
    """Replace the singleton in unit tests."""
    global _SHARED_LEASES
    with _LEASES_LOCK:
        _SHARED_LEASES = WorkspaceWriteLeaseTable()
        return _SHARED_LEASES
