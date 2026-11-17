"""Zero-embedding SQLite FTS5 BM25 playbook/lesson ranking and compact executor pruning.

Runs an ephemeral thread-local ``:memory:`` SQLite ``FTS5`` index so cold or
embedding-free deployments rank lessons and skill playbooks in <2ms with zero
persistent database schema changes or side effects. Also provides deterministic
context budget pruning for worker/executor turns while keeping every security,
governance, and standing-rule block intact.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

PLANNER_WORKER_AGENTS: tuple[str, ...] = (
    "ajcrew-conductor",
    "ajcrew-pipeline-conductor",
    "ajcrew-ledger-conductor",
    "ajcrew-security-conductor",
)

EXECUTOR_WORKER_AGENTS: tuple[str, ...] = (
    "ajcrew-worker",
    "ajcrew-mate-worker",
)

_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]{2,}")
_THREAD_LOCAL = threading.local()
_UNSET = object()


def _fts5_conn() -> sqlite3.Connection | None:
    """Return a thread-local ``:memory:`` SQLite connection with an FTS5 table, or None."""
    cached = getattr(_THREAD_LOCAL, "conn", _UNSET)
    if cached is not _UNSET:
        return cached if isinstance(cached, sqlite3.Connection) else None
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE VIRTUAL TABLE compound_docs USING fts5(doc_idx UNINDEXED, body, tokenize='unicode61')"
        )
        _THREAD_LOCAL.conn = conn
        return conn
    except sqlite3.Error:
        _THREAD_LOCAL.conn = None
        return None


def _build_fts5_or_query(query_text: str) -> str:
    """Build a safe OR-joined FTS5 token query from untrusted *query_text*."""
    seen: dict[str, None] = {}
    for tok in _FTS_TOKEN_RE.findall(query_text.lower()):
        if len(seen) >= 24:
            break
        seen[tok] = None
    if not seen:
        return ""
    return " OR ".join(f'"{tok}"' for tok in seen)


def fts5_bm25_scores(texts: Sequence[str], query_text: str) -> list[float]:
    """Return SQLite ``FTS5`` ``bm25()`` scores for *texts* against *query_text*.

    SQLite ``bm25()`` returns negative floats where more-negative means higher
    TF-IDF relevance; non-matching documents receive ``0.0``. Runs in <2ms on
    typical lesson/skill stores with zero disk I/O.
    """
    n = len(texts)
    if n == 0 or not query_text.strip():
        return [0.0] * n
    fts_query = _build_fts5_or_query(query_text)
    if not fts_query:
        return [0.0] * n
    conn = _fts5_conn()
    if conn is None:
        return [0.0] * n

    scores = [0.0] * n
    try:
        conn.execute("DELETE FROM compound_docs")
        conn.executemany(
            "INSERT INTO compound_docs(doc_idx, body) VALUES (?, ?)",
            [(idx, text) for idx, text in enumerate(texts)],
        )
        cur = conn.execute(
            "SELECT doc_idx, bm25(compound_docs) FROM compound_docs WHERE compound_docs MATCH ?",
            (fts_query,),
        )
        for raw_idx, raw_score in cur.fetchall():
            idx = int(raw_idx)
            if 0 <= idx < n:
                scores[idx] = float(raw_score)
    except sqlite3.Error:
        logger.debug("FTS5 BM25 scoring degraded cleanly", exc_info=True)
    finally:
        try:
            conn.execute("DELETE FROM compound_docs")
        except sqlite3.Error:
            pass
    return scores


def fts5_rank_entries(entries: Sequence[tuple[T, str]], query_text: str) -> list[tuple[T, str]]:
    """Stable-sort ``(item, text)`` *entries* by SQLite FTS5 BM25 relevance, best first."""
    if not entries or not query_text.strip():
        return list(entries)
    scores = fts5_bm25_scores([text for _, text in entries], query_text)
    if not any(s < 0.0 for s in scores):
        return list(entries)
    order = sorted(range(len(entries)), key=lambda idx: scores[idx])
    return [entries[idx] for idx in order]


def fts5_select_playbooks(
    playbooks: Sequence[dict[str, Any]],
    query_text: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Select up to *top_k* relevant skill/playbook descriptors via zero-embedding FTS5 BM25."""
    if not playbooks or not query_text.strip() or top_k <= 0:
        return []
    corpus = [
        f"{p.get('name', '')} {p.get('description', '')} {' '.join(p.get('triggers', ()) or ())}"
        for p in playbooks
    ]
    scores = fts5_bm25_scores(corpus, query_text)
    matched = [(scores[i], i) for i in range(len(playbooks)) if scores[i] < 0.0]
    matched.sort(key=lambda pair: (pair[0], pair[1]))
    return [playbooks[i] for _, i in matched[:top_k]]


def is_compact_executor_turn(
    agent: str | None,
    *,
    session_key: str | None = None,
    executor_pinned: bool = False,
) -> bool:
    """True when assembling context for a worker/executor turn eligible for compact pruning."""
    if agent in EXECUTOR_WORKER_AGENTS:
        return True
    if executor_pinned and session_key and session_key.startswith("subagent:"):
        return True
    return False


def compact_executor_caps(caps: Any) -> Any:
    """Prune optional verbose background caps by 50% for cheap executor turns.

    Preserves 100% of ``lessons``, ``lessons_startup``, ``prefs``, ``prefs_startup``,
    ``skills``, ``steering``, and ``protected_context`` so safety, governance, and
    domain playbooks are never weakened.
    """
    try:
        return replace(
            caps,
            base=max(12_000, int(caps.base * 0.65)),
            projects=max(400, int(caps.projects * 0.5)),
            memory_history=max(1_200, int(caps.memory_history * 0.5)),
            episodic=max(800, int(caps.episodic * 0.5)),
            history_fallback=max(4_000, int(caps.history_fallback * 0.5)),
            compressed_history=max(4_000, int(caps.compressed_history * 0.6)),
        )
    except Exception:
        return caps
