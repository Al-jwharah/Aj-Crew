"""Deterministic post-turn self-correction verifier for the Compound Harness.

Checks files modified during an agent turn for deterministic syntax/parse defects
(Python AST syntax and JSON validity) using Crew's no-link, sensitive-path-gated
file reader, and formats a concise (<1,500 chars) recovery continuation prompt so
a cheap executor model repairs its own broken edit before surfacing to the user.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from aj_crew.hooks import safe_read_file_bytes_nolink
from aj_crew.security.paths import is_sensitive_path

MAX_SELF_CORRECTION_ATTEMPTS = 2
MAX_RECOVERY_DIFF_CHARS = 1500
_MAX_VERIFY_FILE_BYTES = 512 * 1024


@dataclass(frozen=True)
class VerificationIssue:
    """One deterministic syntax or structural error on a turn-modified file."""

    path: str
    line: int
    column: int
    kind: str
    message: str
    snippet: str = ""

    def format_concise(self) -> str:
        loc = f"{self.path}:{self.line}:{self.column}" if self.line > 0 else self.path
        head = f"- {loc} [{self.kind}]: {self.message}"
        if self.snippet:
            return f"{head}\n    {self.snippet.strip()[:160]}"
        return head


def _safe_read_verified_source(raw_path: str | Path) -> tuple[str, str] | None:
    """Read regular UTF-8 file text through the no-link, sensitive-path gate."""
    try:
        resolved = os.path.realpath(str(raw_path))
    except OSError:
        return None
    if not resolved or is_sensitive_path(resolved):
        return None
    suffix = Path(resolved).suffix.lower()
    if suffix not in (".py", ".json"):
        return None
    raw = safe_read_file_bytes_nolink(
        resolved,
        within_root=os.path.dirname(resolved),
        max_bytes=_MAX_VERIFY_FILE_BYTES + 1,
        allow_truncate=True,
    )
    if raw is None or len(raw) > _MAX_VERIFY_FILE_BYTES:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return resolved, f"__DECODE_ERROR__:{exc}"
    return resolved, text


def verify_modified_files(paths: Iterable[str | Path]) -> list[VerificationIssue]:
    """Run fast in-process deterministic syntax checks over turn-modified *paths*."""
    issues: list[VerificationIssue] = []
    seen: set[str] = set()
    for candidate in paths:
        key = str(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        loaded = _safe_read_verified_source(candidate)
        if loaded is None:
            continue
        resolved, text = loaded
        display_name = Path(resolved).name
        if text.startswith("__DECODE_ERROR__:"):
            issues.append(
                VerificationIssue(
                    path=display_name,
                    line=1,
                    column=1,
                    kind="UnicodeDecodeError",
                    message="File is not valid UTF-8",
                )
            )
            continue

        suffix = Path(resolved).suffix.lower()
        if suffix == ".py":
            try:
                ast.parse(text, filename=display_name)
            except SyntaxError as exc:
                lineno = int(exc.lineno or 1)
                col = int(exc.offset or 1)
                src_lines = text.splitlines()
                line_text = (
                    src_lines[lineno - 1] if 1 <= lineno <= len(src_lines) else (exc.text or "")
                )
                issues.append(
                    VerificationIssue(
                        path=display_name,
                        line=lineno,
                        column=col,
                        kind="SyntaxError",
                        message=str(exc.msg or "invalid syntax"),
                        snippet=line_text,
                    )
                )
        elif suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                src_lines = text.splitlines()
                line_text = src_lines[exc.lineno - 1] if 1 <= exc.lineno <= len(src_lines) else ""
                issues.append(
                    VerificationIssue(
                        path=display_name,
                        line=int(exc.lineno),
                        column=int(exc.colno),
                        kind="JSONDecodeError",
                        message=str(exc.msg),
                        snippet=line_text,
                    )
                )
    return issues


def build_self_correction_prompt(
    issues: Sequence[VerificationIssue],
    *,
    tool_errors: Sequence[str] = (),
    attempt: int = 1,
) -> str:
    """Build a bounded (<1,500 chars) deterministic recovery continuation prompt."""
    if not issues and not tool_errors:
        return ""
    header = (
        f"[Compound Self-Correction — attempt {attempt}/{MAX_SELF_CORRECTION_ATTEMPTS}]\n"
        "Deterministic verification found errors in the files touched during the turn:\n"
    )
    footer = "\nFix these exact errors now and re-verify before concluding."
    budget = MAX_RECOVERY_DIFF_CHARS - len(header) - len(footer) - 32
    lines: list[str] = []
    used = 0
    for issue in issues:
        formatted = issue.format_concise()
        if used + len(formatted) + 1 > budget:
            lines.append("- ... (additional issues truncated)")
            break
        lines.append(formatted)
        used += len(formatted) + 1
    for err in tool_errors:
        cleaned = f"- [ToolError]: {' '.join(str(err).split())[:220]}"
        if used + len(cleaned) + 1 > budget:
            break
        lines.append(cleaned)
        used += len(cleaned) + 1
    body = "\n".join(lines)
    out = f"{header}{body}{footer}"
    return out[:MAX_RECOVERY_DIFF_CHARS]
