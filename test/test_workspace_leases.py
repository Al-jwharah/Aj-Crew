"""Unit tests for WorkspaceWriteLeaseTable (disjoint write waves + read waves)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aj_crew.workspace_leases import (
    WorkspaceWriteLeaseTable,
    reset_shared_workspace_leases,
)


@pytest.fixture(autouse=True)
def _isolated_leases():
    reset_shared_workspace_leases()
    yield
    reset_shared_workspace_leases()


def test_read_leases_coexist_but_block_overlapping_write(tmp_path: Path) -> None:
    table = WorkspaceWriteLeaseTable()
    cwd = str(tmp_path)
    r1 = table.try_acquire(cwd, holder="reader-1", mode="read", write_scope=["src"])
    r2 = table.try_acquire(cwd, holder="reader-2", mode="read", write_scope=["src/api"])
    assert r1.granted and r1.lease is not None
    assert r2.granted and r2.lease is not None

    w_conflict = table.try_acquire(cwd, holder="writer-1", mode="write", write_scope=["src/api"])
    assert not w_conflict.granted
    assert {c.holder for c in w_conflict.conflicts} == {"reader-1", "reader-2"}

    # Disjoint directory succeeds concurrently!
    w_disjoint = table.try_acquire(cwd, holder="writer-docs", mode="write", write_scope=["docs"])
    assert w_disjoint.granted and w_disjoint.lease is not None

    table.release(r1.lease)
    table.release(r2.lease)
    w_now = table.try_acquire(cwd, holder="writer-1", mode="write", write_scope=["src/api"])
    assert w_now.granted and w_now.lease is not None


def test_overlapping_ancestor_and_descendant_write_scopes_conflict(tmp_path: Path) -> None:
    table = WorkspaceWriteLeaseTable()
    cwd = str(tmp_path)
    parent = table.try_acquire(
        cwd, holder="writer-parent", mode="write", write_scope=["website/src"]
    )
    assert parent.granted and parent.lease is not None

    child = table.try_acquire(
        cwd, holder="writer-child", mode="write", write_scope=["website/src/components"]
    )
    assert not child.granted
    assert tuple(c.holder for c in child.conflicts) == ("writer-parent",)

    sibling = table.try_acquire(
        cwd, holder="writer-sibling", mode="write", write_scope=["website/tests"]
    )
    assert sibling.granted and sibling.lease is not None


@pytest.mark.asyncio
async def test_async_acquire_serializes_conflicting_writers_in_fifo_order(tmp_path: Path) -> None:
    table = WorkspaceWriteLeaseTable()
    cwd = str(tmp_path)
    first = await table.acquire(cwd, holder="w1", mode="write", write_scope=["src/core"])
    ready = asyncio.Event()
    order: list[str] = []

    async def contender(name: str) -> None:
        ready.set()
        lease = await table.acquire(cwd, holder=name, mode="write", write_scope=["src/core"])
        order.append(name)
        table.release(lease)

    t2 = asyncio.create_task(contender("w2"))
    await ready.wait()
    ready.clear()
    t3 = asyncio.create_task(contender("w3"))
    await ready.wait()
    await asyncio.sleep(0)

    table.release(first)
    await asyncio.gather(t2, t3)
    assert order == ["w2", "w3"]
    assert table.active_leases_for(cwd) == []
