"""Unit tests for handoff/v1 structured envelopes and wave digests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aj_crew.subagent import (
    HANDOFF_ENVELOPE_MAX_CHARS,
    HANDOFF_SCHEMA_VERSION,
    build_handoff_envelope,
    format_handoff_digest,
    format_wave_handoff_digest,
    read_handoff_envelope,
    write_handoff_envelope,
)


def test_handoff_envelope_redacts_secrets_bounds_length_and_persists(tmp_path: Path) -> None:
    secret_token = "ghp_" + "A" * 38
    huge_output = f"Completed audit using token {secret_token}. " + ("detail line " * 400)

    env = build_handoff_envelope(
        "a1b2c3d4e5f60718",
        verdict="succeeded",
        raw_result=huge_output,
        changed_files=["src/aj_crew/orchestration_budget.py", "test/test_orchestration_budget.py"],
        follow_up_session="subagent:a1b2c3d4e5f60718",
        credits=0.12,
        elapsed=4.2,
    )
    assert env.schema == HANDOFF_SCHEMA_VERSION
    assert secret_token not in env.summary

    digest = format_handoff_digest(env)
    assert len(digest) <= HANDOFF_ENVELOPE_MAX_CHARS
    assert secret_token not in digest
    assert "subagents/a1b2c3d4e5f60718/handoff.json" in digest

    written = write_handoff_envelope(env.run_id, env, full_result=huge_output, base_dir=tmp_path)
    assert written.is_file()

    loaded = read_handoff_envelope(env.run_id, base_dir=tmp_path)
    assert loaded is not None
    assert loaded["schema"] == HANDOFF_SCHEMA_VERSION
    assert loaded["verdict"] == "succeeded"
    assert secret_token not in loaded["full_result_excerpt"]


def test_read_handoff_envelope_refuses_traversal_and_symlinks(tmp_path: Path) -> None:
    assert read_handoff_envelope("../escape", base_dir=tmp_path) is None
    assert read_handoff_envelope("..", base_dir=tmp_path) is None

    outside = tmp_path / "outside.json"
    outside.write_text('{"schema": "handoff/v1"}', encoding="utf-8")
    run_dir = tmp_path / "subagents" / "symrun"
    run_dir.mkdir(parents=True)
    link = run_dir / "handoff.json"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation requires privilege on this host")
    assert read_handoff_envelope("symrun", base_dir=tmp_path) is None


def test_wave_handoff_digest_coalesces_parallel_runs() -> None:
    e1 = build_handoff_envelope("run01", verdict="succeeded", raw_result="Fixed parser edge case")
    e2 = build_handoff_envelope("run02", verdict="failed", error="Timeout waiting for fixture")
    table = format_wave_handoff_digest([e1, e2])
    assert "| `run01` | `succeeded` |" in table
    assert "| `run02` | `failed` |" in table
    assert "subagents/run01/handoff.json" in table
