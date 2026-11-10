"""The fakes, pool factory and config-dir fixture the LLM pool test modules share.

``test_llm_pool.py`` and its ``_effort``, ``_ccworker`` and ``_lifecycle`` siblings import
what they use of these by name: ``FakeWorker``, an in-memory worker;
``_make_pool_with_fake_workers``, a pool pre-loaded with them and marked started;
``_zero_tool_client``, an ``AcpClient`` double whose agent spec answers the zero-tool check;
``_real_client_without_io``, which lets a worker build a real ``AcpClient`` that never spawns;
and the autouse ``_config_dir_tracks_patched_home``, which points ``llm_pool.config_dir()``
at ``<patched home>/.ajcrew`` and which every test module of the family imports.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from aj_crew.acp.client import AcpClient
from aj_crew.knowledge.llm_pool import LLMPool, Worker


@pytest.fixture(autouse=True)
def _config_dir_tracks_patched_home(_floor_monkeypatch):
    """Keep ``llm_pool.config_dir()`` pointed at ``<patched home>/.ajcrew``.

    The data home moved from ``~/.ajcrew`` to ``~/.kiro/crew`` (``config_dir()``),
    and ``_read_config`` now reads ``config_dir()/config.json`` rather than
    ``Path.home()/".ajcrew"/"config.json"``. These tests patch
    ``llm_pool.Path.home`` per-test and write ``config.json`` under
    ``<home>/.ajcrew`` — but ``config_dir()`` reads ``AJCREW_HOME`` (pinned to
    a *different* tmp dir by the conftest ``_isolate_ajcrew_home`` fixture), so
    without this redirect the config would never be found. Redirect
    ``config_dir`` to ``Path.home()/".ajcrew"`` (evaluated lazily, so it tracks
    whatever ``Path.home()`` each test patches), preserving the existing
    ``.ajcrew/config.json`` layout the tests build.
    """
    _floor_monkeypatch.setattr(
        "aj_crew.knowledge.llm_pool.config_dir", lambda: Path.home() / ".ajcrew"
    )


def _zero_tool_client(*, spec_declares_zero_tools: bool = True) -> AsyncMock:
    """An ``AcpClient`` double whose resolved agent spec answers the zero-tool check.

    ``effective_spec_declares_zero_tools`` and ``authored_spec_declares_zero_tools``
    are synchronous on the real client, so they are plain mocks rather than the
    coroutines an ``AsyncMock`` attribute would be. The authored read answers the
    same value as the effective check, so a double built as unconfirmed is
    unconfirmed on both.
    """
    client = AsyncMock()
    client.effective_spec_declares_zero_tools = MagicMock(return_value=spec_declares_zero_tools)
    client.authored_spec_declares_zero_tools = MagicMock(return_value=spec_declares_zero_tools)
    return client


@contextmanager
def _real_client_without_io() -> Iterator[None]:
    """Let ``AcpWorker`` build a real ``AcpClient`` whose process and spec reads are stubbed.

    The worker's choices (backend, sandbox mode, model pin) land on the client it
    built, so a test reads them there instead of from the constructor's call record.
    """
    with (
        patch.object(AcpClient, "ensure_ready", AsyncMock()),
        patch.object(AcpClient, "shutdown", AsyncMock()),
        patch.object(AcpClient, "authored_spec_declares_zero_tools", return_value=True),
        patch.object(AcpClient, "effective_spec_declares_zero_tools", return_value=True),
        patch.object(AcpClient, "spec_zero_tools", new_callable=PropertyMock, return_value=True),
    ):
        yield


class FakeWorker(Worker):
    """In-memory worker for testing pool mechanics."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = list(responses or ["ok"])
        self._call_count = 0
        self._alive = True
        self._started = False
        self.resets = 0

    async def start(self) -> None:
        self._started = True

    async def send_message(self, prompt: str, timeout: float = 60.0) -> str:
        if not self._alive:
            raise RuntimeError("worker is dead")
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

    async def shutdown(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    async def reset_conversation(self) -> None:
        self.resets += 1
        self.calls_since_reset = 0


def _make_pool_with_fake_workers(pool_size: int = 3, responses: list[str] | None = None) -> LLMPool:
    """Create a pool pre-loaded with FakeWorkers (skips real process spawn)."""
    pool = LLMPool(pool_size=pool_size)
    pool._started = True
    pool._provider_type = "test"
    for i in range(pool_size):
        worker = FakeWorker(responses=responses)
        worker._started = True
        pool._workers.append(worker)
        pool._available.put_nowait(i)
    return pool
