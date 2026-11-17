"""Unified host execution budget shared across subagents and workflow pools.

Subagent spawns and dynamic-workflow ``ctx.agent()`` steps compete for the same
host processes and RAM, yet previously counted concurrency in separate silos.
This leaf module provides one process-wide slot and memory-reserve gate that
both surfaces consult without introducing import cycles into ``runtime_ownership``
or ``workflows.__init__``.
"""

from __future__ import annotations

import asyncio
import math
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field


def _clean_cost_gb(cost_gb: float) -> float:
    if isinstance(cost_gb, bool) or not isinstance(cost_gb, (int, float)):
        return 0.0
    value = float(cost_gb)
    if not math.isfinite(value) or value < 0.0:
        return 0.0
    return value


@dataclass(frozen=True)
class BudgetTicket:
    """Handle returned when a run claims capacity from :class:`HostExecutionBudget`."""

    ticket_id: str
    owner: str
    kind: str
    cost_gb: float
    _loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class BudgetSnapshot:
    """Point-in-time view of active host orchestration usage."""

    max_slots: int
    active_slots: int
    reserved_gb: float
    by_kind: dict[str, int]


class HostExecutionBudget:
    """Process-wide slot and memory-reserve coordinator for background agent work."""

    def __init__(self, max_slots: int = 4) -> None:
        self._lock = threading.Lock()
        self._max_slots = max(1, int(max_slots))
        self._tickets: dict[str, BudgetTicket] = {}
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        self._external_readers: dict[str, Callable[[], int]] = {}
        self._release_callbacks: dict[str, Callable[[], None]] = {}

    def _reap_closed_locked(self) -> None:
        stale = [
            tid
            for tid, ticket in self._tickets.items()
            if ticket._loop is not None and ticket._loop.is_closed()
        ]
        for tid in stale:
            self._tickets.pop(tid, None)
        if self._waiters:
            self._waiters = [w for w in self._waiters if not w[0].is_closed()]

    def _external_counts_locked(self, *, exclude_kind: str | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for kind, reader in list(self._external_readers.items()):
            if exclude_kind is not None and kind == exclude_kind:
                continue
            try:
                val = max(0, int(reader()))
            except Exception:
                val = 0
            if val > 0:
                counts[kind] = counts.get(kind, 0) + val
        return counts

    def bind_external_slot_reader(self, kind: str, reader: Callable[[], int] | None) -> None:
        """Bind or clear a live external slot counter (e.g. ``SubagentManager``)."""
        with self._lock:
            if reader is None:
                self._external_readers.pop(kind, None)
            else:
                self._external_readers[kind] = reader

    def register_release_callback(self, name: str, callback: Callable[[], None] | None) -> None:
        """Register or clear a callback invoked when a ticket slot frees up."""
        with self._lock:
            if callback is None:
                self._release_callbacks.pop(name, None)
            else:
                self._release_callbacks[name] = callback

    def notify_external_release(self) -> None:
        """Wake the next parked ticket waiter when an external lane frees a slot."""
        next_waiter: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None
        with self._lock:
            self._reap_closed_locked()
            if self._waiters:
                next_waiter = self._waiters[0]
        if next_waiter is not None and not next_waiter[0].is_closed():
            next_waiter[0].call_soon_threadsafe(next_waiter[1].set)

    @property
    def max_slots(self) -> int:
        with self._lock:
            return self._max_slots

    def set_max_slots(self, max_slots: int) -> None:
        """Update the slot ceiling and wake any parked waiters if capacity grew."""
        clamped = max(1, int(max_slots))
        to_wake: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        with self._lock:
            self._reap_closed_locked()
            grew = clamped > self._max_slots
            self._max_slots = clamped
            if grew:
                to_wake = list(self._waiters)
        for loop, ev in to_wake:
            if not loop.is_closed():
                loop.call_soon_threadsafe(ev.set)

    def active_count(self, *, kind: str | None = None) -> int:
        with self._lock:
            self._reap_closed_locked()
            ext = self._external_counts_locked()
            if kind is None:
                return len(self._tickets) + sum(ext.values())
            return sum(1 for t in self._tickets.values() if t.kind == kind) + ext.get(kind, 0)

    def reserved_gb(self) -> float:
        with self._lock:
            self._reap_closed_locked()
            return round(sum(t.cost_gb for t in self._tickets.values()), 6)

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            self._reap_closed_locked()
            counts: dict[str, int] = dict(self._external_counts_locked())
            total_gb = 0.0
            for ticket in self._tickets.values():
                counts[ticket.kind] = counts.get(ticket.kind, 0) + 1
                total_gb += ticket.cost_gb
            return BudgetSnapshot(
                max_slots=self._max_slots,
                active_slots=sum(counts.values()),
                reserved_gb=round(total_gb, 6),
                by_kind=counts,
            )

    def try_acquire(
        self,
        *,
        owner: str,
        kind: str = "subagent",
        cost_gb: float = 0.0,
        max_slots_override: int | None = None,
    ) -> BudgetTicket | None:
        """Claim one slot immediately if below the effective cap, else ``None``."""
        clean_cost = _clean_cost_gb(cost_gb)
        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        with self._lock:
            self._reap_closed_locked()
            cap = (
                max(1, int(max_slots_override))
                if max_slots_override is not None and max_slots_override > 0
                else self._max_slots
            )
            ext_total = sum(self._external_counts_locked().values())
            if len(self._tickets) + ext_total >= cap:
                return None
            ticket = BudgetTicket(
                ticket_id=uuid.uuid4().hex[:16],
                owner=str(owner),
                kind=str(kind),
                cost_gb=clean_cost,
                _loop=running_loop,
            )
            self._tickets[ticket.ticket_id] = ticket
            return ticket

    async def acquire(
        self,
        *,
        owner: str,
        kind: str = "subagent",
        cost_gb: float = 0.0,
        timeout: float | None = None,
    ) -> BudgetTicket:
        """Wait in FIFO order for one host execution slot, bounded by *timeout*."""
        immediate = self.try_acquire(owner=owner, kind=kind, cost_gb=cost_gb)
        if immediate is not None:
            return immediate

        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        entry = (loop, wake)
        with self._lock:
            self._waiters.append(entry)
        deadline = None if timeout is None else loop.time() + max(0.0, float(timeout))
        try:
            while True:
                ticket = self.try_acquire(owner=owner, kind=kind, cost_gb=cost_gb)
                if ticket is not None:
                    return ticket
                wake.clear()
                ticket = self.try_acquire(owner=owner, kind=kind, cost_gb=cost_gb)
                if ticket is not None:
                    return ticket
                if deadline is not None:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"timed out waiting for host execution budget ({kind}:{owner})"
                        )
                    await asyncio.wait_for(wake.wait(), timeout=remaining)
                else:
                    await wake.wait()
        finally:
            with self._lock:
                if entry in self._waiters:
                    self._waiters.remove(entry)

    def release(self, ticket: BudgetTicket | str | None) -> bool:
        """Release *ticket* idempotently and wake the oldest parked waiter."""
        if ticket is None:
            return False
        tid = ticket.ticket_id if isinstance(ticket, BudgetTicket) else str(ticket)
        next_waiter: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None
        callbacks: list[Callable[[], None]] = []
        with self._lock:
            self._reap_closed_locked()
            removed = self._tickets.pop(tid, None)
            if removed is None:
                return False
            if self._waiters:
                next_waiter = self._waiters[0]
            callbacks = list(self._release_callbacks.values())
        if next_waiter is not None and not next_waiter[0].is_closed():
            next_waiter[0].call_soon_threadsafe(next_waiter[1].set)
        for cb in callbacks:
            try:
                cb()
            except Exception:
                pass
        return True


_SHARED_LOCK = threading.Lock()
_SHARED_BUDGET: HostExecutionBudget | None = None


def shared_execution_budget(default_max_slots: int = 4) -> HostExecutionBudget:
    """Return the process-wide :class:`HostExecutionBudget` singleton."""
    global _SHARED_BUDGET
    with _SHARED_LOCK:
        if _SHARED_BUDGET is None:
            _SHARED_BUDGET = HostExecutionBudget(max_slots=default_max_slots)
        return _SHARED_BUDGET


def reset_shared_execution_budget(max_slots: int = 4) -> HostExecutionBudget:
    """Replace the singleton in unit tests so no state leaks across cases."""
    global _SHARED_BUDGET
    with _SHARED_LOCK:
        _SHARED_BUDGET = HostExecutionBudget(max_slots=max_slots)
        return _SHARED_BUDGET
