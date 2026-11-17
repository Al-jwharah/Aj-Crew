"""Unit tests for the Compound Harness Architecture (Phase 3):
1. Planner -> Cheap Executor role routing (ROLE_MODEL_KEYS, resolve_compound_role_model).
2. Deterministic post-turn self-correction verifier (compound_verify).
3. Zero-embedding SQLite FTS5 BM25 lesson/playbook ranking & compact executor pruning (compound_fts).
"""

from __future__ import annotations

import time
from pathlib import Path

from aj_crew.compound_fts import (
    compact_executor_caps,
    fts5_bm25_scores,
    fts5_rank_entries,
    fts5_select_playbooks,
    is_compact_executor_turn,
)
from aj_crew.compound_verify import (
    MAX_RECOVERY_DIFF_CHARS,
    MAX_SELF_CORRECTION_ATTEMPTS,
    build_self_correction_prompt,
    verify_modified_files,
)
from aj_crew.config.loader import AjCrewConfig, resolve_effective_model
from aj_crew.config.sections_agent_fields import (
    EXECUTOR_WORKER_AGENTS,
    PLANNER_WORKER_AGENTS,
    ROLE_MODEL_KEYS,
    coerce_role_efforts,
    coerce_role_models,
)
from aj_crew.context_assembly.budget import _resolve_caps_cached
from aj_crew.lesson_validation import order_by_request_relevance
from aj_crew.subagent_parts.model_choice import (
    _subagent_default_effort,
    _subagent_default_model,
    resolve_compound_role_model,
)


def test_planner_and_executor_role_models_route_without_hardcoded_ids() -> None:
    assert ROLE_MODEL_KEYS == ("background", "subagent", "planner", "executor")

    coerced = coerce_role_models(
        {
            "planner": "provider/strong-planner",
            "executor": "provider/fast-executor",
            "background": "auto",
            "unknown_role": "ignored",
        }
    )
    assert coerced == {
        "planner": "provider/strong-planner",
        "executor": "provider/fast-executor",
    }

    efforts = coerce_role_efforts({"planner": "high", "executor": "low", "subagent": ""})
    assert efforts == {"planner": "high", "executor": "low"}

    cfg = AjCrewConfig()
    cfg.agent.acp_backend = "opencode"
    cfg.agent.role_models = dict(coerced)
    cfg.agent.role_efforts = dict(efforts)

    assert _subagent_default_model(cfg) == "provider/fast-executor"
    assert _subagent_default_effort(cfg) == "low"

    for planner_agent in PLANNER_WORKER_AGENTS:
        assert (
            resolve_effective_model(cfg, None, backend="opencode", template=planner_agent)
            == "provider/strong-planner"
        )
    for exec_agent in EXECUTOR_WORKER_AGENTS:
        assert (
            resolve_effective_model(cfg, None, backend="opencode", template=exec_agent)
            == "provider/fast-executor"
        )

    # Unpinned roles resolve safely through resolve_usable_model ("auto" -> served or "")
    unpinned_cfg = AjCrewConfig()
    assert (
        resolve_compound_role_model(
            "executor",
            ["provider/fast-executor", "provider/strong-planner"],
            backend="opencode",
            cfg=unpinned_cfg,
        )
        == ""
    )
    assert (
        resolve_compound_role_model(
            "executor",
            ["provider/fast-executor", "provider/strong-planner"],
            backend="opencode",
            cfg=cfg,
        )
        == "provider/fast-executor"
    )


def test_deterministic_self_correction_verifier_catches_syntax_and_bounds_diff(
    tmp_path: Path,
) -> None:
    good_py = tmp_path / "good.py"
    good_py.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    bad_py = tmp_path / "broken_module.py"
    bad_py.write_text("def broken(\n    x = 1\n", encoding="utf-8")

    bad_json = tmp_path / "broken_config.json"
    bad_json.write_text('{"key": "value", }\n', encoding="utf-8")

    assert verify_modified_files([good_py]) == []

    issues = verify_modified_files([good_py, bad_py, bad_json])
    assert len(issues) == 2
    kinds = {issue.kind for issue in issues}
    assert kinds == {"SyntaxError", "JSONDecodeError"}

    prompt = build_self_correction_prompt(
        issues,
        tool_errors=["pytest failed: SyntaxError in broken_module.py"] * 20,
        attempt=1,
    )
    assert f"attempt 1/{MAX_SELF_CORRECTION_ATTEMPTS}" in prompt
    assert "broken_module.py" in prompt
    assert "broken_config.json" in prompt
    assert len(prompt) <= MAX_RECOVERY_DIFF_CHARS


def test_zero_embedding_fts5_bm25_ranks_in_milliseconds_and_prunes_executor_caps() -> None:
    entries = [
        ({"id": "generic"}, "Always run python tests cleanly in the project workspace"),
        ({"id": "specific"}, "Run python tests with pkce_loopback_nonce verification enabled"),
        ({"id": "unrelated"}, "Format markdown tables with aligned pipes"),
    ]

    t0 = time.perf_counter()
    scores = fts5_bm25_scores([text for _, text in entries], "python pkce_loopback_nonce")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 50.0
    assert scores[1] < scores[0] < 0.0
    assert scores[2] == 0.0

    ranked = fts5_rank_entries(entries, "pkce_loopback_nonce")
    assert ranked[0][0]["id"] == "specific"

    # order_by_request_relevance breaks equal-overlap ties using FTS5 BM25 rarity
    tie_entries: list[tuple[object, str]] = [
        ("generic_first", "Check python configuration values carefully"),
        ("rare_second", "Check gatewayd socket configuration values"),
    ]
    # Query has 1 rare token in second or equal overlap where IDF favours rare token:
    ordered = order_by_request_relevance(tie_entries, "gatewayd configuration")
    assert ordered[0][0] == "rare_second"

    # Zero-overlap preserves exact caller order
    assert order_by_request_relevance(tie_entries, "nonexistent_xyz_token") == tie_entries

    playbooks = [
        {"name": "git-commit", "description": "Create clean git commits", "triggers": ["commit"]},
        {
            "name": "mcp-perplexity",
            "description": "Deep citation research via Perplexity Sonar",
            "triggers": ["perplexity", "sonar"],
        },
    ]
    picked = fts5_select_playbooks(playbooks, "run sonar citation search", top_k=1)
    assert [p["name"] for p in picked] == ["mcp-perplexity"]

    # Compact executor pruning shrinks verbose optional history/projects while keeping lessons intact
    assert is_compact_executor_turn("ajcrew-worker") is True
    assert is_compact_executor_turn("ajcrew") is False
    full_caps = _resolve_caps_cached(200_000)
    pruned = compact_executor_caps(full_caps)
    assert pruned.memory_history < full_caps.memory_history
    assert pruned.projects < full_caps.projects
    assert pruned.lessons == full_caps.lessons
    assert pruned.lessons_startup == full_caps.lessons_startup
    assert pruned.protected_context == full_caps.protected_context
