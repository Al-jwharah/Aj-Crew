"""Compact structured handoffs (``handoff/v1``) for subagents and parallel waves.

Instead of dumping multi-kilobyte raw worker transcripts into a parent or
conductor's context window, completed runs persist their full redacted output
and metadata to ``<data_home>/subagents/<run_id>/handoff.json`` (under the
read-only sealed ``subagents`` tree) and deliver a compact ``<= 1,200``-character
pointer envelope or coalesced wave summary table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import json
    import os
    import stat

    from aj_crew.subagent import (
        Path,
        Sequence,
        _redact_and_truncate,
        atomic_write,
        data_home,
        format_subagent_usage,
    )

HANDOFF_SCHEMA_VERSION = "handoff/v1"
HANDOFF_SUMMARY_MAX_CHARS = 600
HANDOFF_ENVELOPE_MAX_CHARS = 1200
_MAX_HANDOFF_FILE_BYTES = 256 * 1024
_MAX_CHANGED_FILES = 32


@dataclass(frozen=True)
class SubagentHandoffEnvelope:
    """Bounded structured summary and artifact pointer for one completed subagent."""

    schema: str
    run_id: str
    verdict: str
    summary: str
    changed_files: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    follow_up_session: str = ""
    usage: str = ""


def _extract_executive_summary(raw_text: str, max_chars: int = HANDOFF_SUMMARY_MAX_CHARS) -> str:
    """Extract a clean, redacted summary without cutting mid-credential."""
    if not raw_text or not raw_text.strip():
        return ""
    collapsed = " ".join(line.strip() for line in raw_text.splitlines() if line.strip())
    return _redact_and_truncate(collapsed, max_chars)


def build_handoff_envelope(
    run_id: str,
    *,
    verdict: str,
    raw_result: str = "",
    error: str = "",
    changed_files: "Sequence[str]" = (),
    artifacts: "Sequence[str]" = (),
    follow_up_session: str = "",
    credits: object = 0.0,
    elapsed: object = 0.0,
) -> SubagentHandoffEnvelope:
    """Construct a redacted ``handoff/v1`` envelope from a run's terminal state."""
    clean_verdict = verdict if verdict in ("succeeded", "failed", "blocked") else "failed"
    basis = raw_result if raw_result and raw_result.strip() else error
    summary = _extract_executive_summary(basis, HANDOFF_SUMMARY_MAX_CHARS)
    files = tuple(
        _redact_and_truncate(str(p).strip(), 200)
        for p in list(changed_files)[:_MAX_CHANGED_FILES]
        if str(p).strip()
    )
    rel_handoff = f"subagents/{run_id}/handoff.json"
    art_list = [rel_handoff]
    for item in artifacts:
        cleaned = _redact_and_truncate(str(item).strip(), 240)
        if cleaned and cleaned not in art_list:
            art_list.append(cleaned)
    usage_line = format_subagent_usage(credits, elapsed)
    return SubagentHandoffEnvelope(
        schema=HANDOFF_SCHEMA_VERSION,
        run_id=str(run_id),
        verdict=clean_verdict,
        summary=summary,
        changed_files=files,
        artifacts=tuple(art_list[:16]),
        follow_up_session=str(follow_up_session or ""),
        usage=usage_line,
    )


def write_handoff_envelope(
    run_id: str,
    envelope: SubagentHandoffEnvelope,
    *,
    full_result: str = "",
    base_dir: "Path | None" = None,
) -> "Path":
    """Atomically persist ``handoff.json`` inside the run's ``subagents/<run_id>/`` folder."""
    safe_id = os.path.basename(str(run_id).strip())
    if not safe_id or safe_id in (".", ".."):
        raise ValueError(f"invalid run_id for handoff envelope: {run_id!r}")
    root = (base_dir if base_dir is not None else data_home()) / "subagents" / safe_id
    root.mkdir(parents=True, exist_ok=True)
    target = root / "handoff.json"
    payload = {
        "schema": envelope.schema,
        "run_id": envelope.run_id,
        "verdict": envelope.verdict,
        "summary": envelope.summary,
        "changed_files": list(envelope.changed_files),
        "artifacts": list(envelope.artifacts),
        "follow_up_session": envelope.follow_up_session,
        "usage": envelope.usage,
        "full_result_excerpt": _redact_and_truncate(full_result, 32_000) if full_result else "",
    }
    atomic_write(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target


def read_handoff_envelope(
    run_id: str, *, base_dir: "Path | None" = None
) -> "dict[str, Any] | None":
    """Read a persisted ``handoff.json`` safely without following symlinks."""
    safe_id = os.path.basename(str(run_id).strip())
    if not safe_id or safe_id in (".", ".."):
        return None
    target = (
        (base_dir if base_dir is not None else data_home()) / "subagents" / safe_id / "handoff.json"
    )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        if not nofollow:
            pre = os.lstat(target)
            if stat.S_ISLNK(pre.st_mode):
                return None
        fd = os.open(target, os.O_RDONLY | nofollow)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > _MAX_HANDOFF_FILE_BYTES:
            return None
        raw = os.read(fd, _MAX_HANDOFF_FILE_BYTES + 1)
        if len(raw) > _MAX_HANDOFF_FILE_BYTES:
            return None
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


def format_handoff_digest(envelope: SubagentHandoffEnvelope) -> str:
    """Format one ``handoff/v1`` envelope into a compact ``<= 1,200``-char block."""
    lines = [
        f"[handoff/v1 run={envelope.run_id} verdict={envelope.verdict}"
        + (f" usage={envelope.usage!r}" if envelope.usage else "")
        + "]",
    ]
    if envelope.summary:
        lines.append(f"Summary: {envelope.summary}")
    if envelope.changed_files:
        shown = ", ".join(envelope.changed_files[:8])
        extra = len(envelope.changed_files) - 8
        suffix = f" (+{extra} more)" if extra > 0 else ""
        lines.append(f"Changed files: {shown}{suffix}")
    if envelope.artifacts:
        lines.append(f"Artifact pointer: {envelope.artifacts[0]}")
    if envelope.follow_up_session:
        lines.append(f"Continue handle: {envelope.follow_up_session}")
    body = "\n".join(lines)
    if len(body) <= HANDOFF_ENVELOPE_MAX_CHARS:
        return body
    return body[: HANDOFF_ENVELOPE_MAX_CHARS - 1] + "…"


def format_wave_handoff_digest(envelopes: "Sequence[SubagentHandoffEnvelope]") -> str:
    """Coalesce a parallel subagent wave into a single structured digest table."""
    if not envelopes:
        return ""
    rows = [
        "| Run | Verdict | Summary | Pointer |",
        "|---|---|---|---|",
    ]
    for env in envelopes:
        short_summary = (env.summary[:140] + "…") if len(env.summary) > 140 else env.summary
        safe_cell = short_summary.replace("|", "\\|").replace("\n", " ")
        ptr = env.artifacts[0] if env.artifacts else f"subagents/{env.run_id}/handoff.json"
        rows.append(f"| `{env.run_id}` | `{env.verdict}` | {safe_cell} | `{ptr}` |")
    return "\n".join(rows)
