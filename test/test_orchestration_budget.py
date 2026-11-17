"""Unit tests for the unified HostExecutionBudget and cross-platform incarnation tracking."""

from __future__ import annotations

import asyncio
import os

import pytest

from aj_crew import platform_compat
from aj_crew.orchestration_budget import (
    HostExecutionBudget,
    reset_shared_execution_budget,
    shared_execution_budget,
)
from aj_crew.session_pid_tracking import (
    capture_process_incarnation,
    incarnation_matches_live,
)


@pytest.fixture(autouse=True)
def _isolated_budget():
    reset_shared_execution_budget(max_slots=4)
    yield
    reset_shared_execution_budget(max_slots=4)


def test_try_acquire_enforces_shared_cap_across_subagent_and_workflow_kinds() -> None:
    budget = HostExecutionBudget(max_slots=2)
    t1 = budget.try_acquire(owner="sub-1", kind="subagent", cost_gb=0.5)
    t2 = budget.try_acquire(owner="wf-1", kind="workflow", cost_gb=0.75)
    t3 = budget.try_acquire(owner="sub-2", kind="subagent", cost_gb=0.5)

    assert t1 is not None
    assert t2 is not None
    assert t3 is None

    snap = budget.snapshot()
    assert snap.max_slots == 2
    assert snap.active_slots == 2
    assert snap.reserved_gb == pytest.approx(1.25)
    assert snap.by_kind == {"subagent": 1, "workflow": 1}

    assert budget.release(t1) is True
    assert budget.release(t1) is False  # idempotent
    t3_retry = budget.try_acquire(owner="sub-2", kind="subagent", cost_gb=0.5)
    assert t3_retry is not None


@pytest.mark.asyncio
async def test_fifo_waiter_wakes_on_release_and_cap_raise() -> None:
    budget = HostExecutionBudget(max_slots=1)
    first = await budget.acquire(owner="holder-1", kind="subagent")
    entered = asyncio.Event()
    order: list[str] = []

    async def waiter(name: str) -> None:
        entered.set()
        ticket = await budget.acquire(owner=name, kind="workflow")
        order.append(name)
        budget.release(ticket)

    t_a = asyncio.create_task(waiter("wf-a"))
    await entered.wait()
    entered.clear()
    t_b = asyncio.create_task(waiter("wf-b"))
    await entered.wait()
    await asyncio.sleep(0)

    budget.release(first)
    await asyncio.gather(t_a, t_b)
    assert order == ["wf-a", "wf-b"]
    assert budget.active_count() == 0


@pytest.mark.asyncio
async def test_external_slot_reader_blocks_workflow_until_notified() -> None:
    ext_running = 2
    budget = shared_execution_budget()
    budget.set_max_slots(2)
    budget.bind_external_slot_reader("subagent", lambda: ext_running)

    assert budget.try_acquire(owner="wf-1", kind="workflow") is None

    acquired = asyncio.Event()

    async def claim() -> None:
        ticket = await budget.acquire(owner="wf-1", kind="workflow", timeout=2.0)
        acquired.set()
        budget.release(ticket)

    task = asyncio.create_task(claim())
    await asyncio.sleep(0)
    assert not acquired.is_set()

    ext_running = 1
    budget.notify_external_release()
    await task
    assert acquired.is_set()


def test_host_boot_id_and_process_incarnation_round_trip_on_current_pid() -> None:
    boot = platform_compat.host_boot_id()
    assert isinstance(boot, str) and boot != ""

    own_pid = os.getpid()
    record = capture_process_incarnation(own_pid)
    assert record is not None
    assert record["pid"] == own_pid
    assert record["boot_id"] == boot
    assert incarnation_matches_live(record) is True

    # Recycled PID (wrong start_id) or rebooted host (wrong boot_id) fails closed.
    tampered_start = dict(record, start_id="0:recycled")
    assert incarnation_matches_live(tampered_start) is False

    tampered_boot = dict(record, boot_id="rebooted-epoch")
    assert incarnation_matches_live(tampered_boot) is False
