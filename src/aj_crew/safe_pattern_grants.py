"""Persistent read-only / safe pattern approval grants (gateway-owned).

"Always allow safe pattern" persists ONLY verified read-only / non-destructive
operations in ``<config_dir>/approval-grants/grants.json`` (a ``HIDDEN`` leaf
under the OS sandbox and fenced by ``security._CREW_SECRET_LEAVES``). Mutating
tools, network egress, credential reads, and computer-use actions are
unconditionally refused at both mint and match time so an operator click can
never silently turn into a permanent write/exec blank check.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aj_crew.approval_mode_policy import (
    register_deny_hook,
    register_reset_hook,
    session_mode_permitted,
)
from aj_crew.atomic_write import atomic_write
from aj_crew.config.paths import config_dir
from aj_crew.owner_only_files import mkdirs_owner_only

APPROVAL_GRANTS_DIR_LEAF = "approval-grants"
APPROVAL_GRANTS_FILE = "grants.json"
_MAX_GRANTS_FILE_BYTES = 256 * 1024

SAFE_ELIGIBLE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "read",
        "search",
        "glob",
        "grep",
        "list_dir",
        "inspect_readonly",
        "shell_readonly",
    }
)

SAFE_READONLY_SHELL_VERBS: frozenset[str] = frozenset(
    {
        "cat",
        "head",
        "tail",
        "wc",
        "ls",
        "pwd",
        "stat",
        "file",
        "which",
        "rg",
        "grep",
    }
)

SAFE_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "rev-parse",
        "branch",
    }
)

_SHELL_UNSAFE_TOKENS = ("|", ";", "&&", "||", ">", "<", "`", "$(", "\n", "\r")


class GrantNotSafeEligibleError(ValueError):
    """Raised when attempting to mint or match a persistent grant for an unsafe tool."""


def _is_safe_readonly_shell_command(command_line: str) -> tuple[bool, str]:
    """Verify *command_line* is a simple, non-redirecting read-only command."""
    stripped = (command_line or "").strip()
    if not stripped:
        return False, ""
    if any(tok in stripped for tok in _SHELL_UNSAFE_TOKENS):
        return False, ""
    try:
        argv = shlex.split(stripped, posix=(os.name != "nt"))
    except ValueError:
        return False, ""
    if not argv:
        return False, ""
    prog = os.path.basename(argv[0]).lower()
    if prog.endswith(".exe"):
        prog = prog[:-4]
    if prog == "git":
        if len(argv) < 2 or argv[1] not in SAFE_GIT_SUBCOMMANDS:
            return False, ""
        # Refuse git branch/diff flags that mutate or write files
        if argv[1] == "branch" and any(
            a not in ("--show-current", "-a", "-r", "--list", "-v") for a in argv[2:]
        ):
            return False, ""
        if any(a.startswith(("--output", "-o", "--ext-diff", "--exec")) for a in argv[2:]):
            return False, ""
        return True, f"git {argv[1]}"
    if prog in SAFE_READONLY_SHELL_VERBS:
        return True, prog
    return False, ""


def _default_shell_refusal_check(command_line: str) -> bool:
    """Return True if ``name_grant`` refuses the command's binary resolution."""
    from aj_crew.name_grant import name_grant_refusal

    return name_grant_refusal(command_line) is not None


def _read_regular_json_nofollow(path: Path) -> dict[str, Any] | None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        if not nofollow:
            pre = os.lstat(path)
            if stat.S_ISLNK(pre.st_mode):
                return None
        fd = os.open(path, os.O_RDONLY | nofollow)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > _MAX_GRANTS_FILE_BYTES:
            return None
        raw = os.read(fd, _MAX_GRANTS_FILE_BYTES + 1)
        if len(raw) > _MAX_GRANTS_FILE_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


@dataclass(frozen=True)
class SafePatternGrant:
    """One persistent read-only pattern grant stored under ``approval-grants/``."""

    grant_id: str
    canonical_tool_id: str
    capability_class: str
    pattern: str
    workspace_prefix: str
    created_at: float


class SafePatternGrantStore:
    """Gateway-owned store for persistent read-only approval grants."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        clock: Callable[[], float] = time.time,
        shell_refused: Callable[[str], bool] = _default_shell_refusal_check,
    ) -> None:
        self._lock = threading.Lock()
        self._base_dir = base_dir
        self._clock = clock
        self._shell_refused = shell_refused
        self._mem_cache: tuple[tuple[str, int, int] | None, list[SafePatternGrant]] | None = None

    def _grants_path(self) -> Path:
        root = self._base_dir if self._base_dir is not None else config_dir()
        return root / APPROVAL_GRANTS_DIR_LEAF / APPROVAL_GRANTS_FILE

    def _file_sig(self, path: Path) -> tuple[str, int, int] | None:
        try:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode):
                return None
            return (str(path), st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _load_locked(self) -> list[SafePatternGrant]:
        path = self._grants_path()
        sig = self._file_sig(path)
        if self._mem_cache is not None and self._mem_cache[0] == sig:
            return list(self._mem_cache[1])
        if sig is None:
            self._mem_cache = (None, [])
            return []
        doc = _read_regular_json_nofollow(path)
        if not doc or doc.get("version") != 1:
            self._mem_cache = (sig, [])
            return []
        raw_items = doc.get("grants")
        if not isinstance(raw_items, list):
            return []
        out: list[SafePatternGrant] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            cap = str(item.get("capability_class") or "")
            tool_id = str(item.get("canonical_tool_id") or "")
            pattern = str(item.get("pattern") or "")
            if (
                cap not in SAFE_ELIGIBLE_CAPABILITIES
                or not tool_id
                or "*" in tool_id
                or not pattern
                or pattern == "*"
            ):
                continue
                out.append(
                    SafePatternGrant(
                        grant_id=str(item.get("grant_id") or ""),
                        canonical_tool_id=tool_id,
                        capability_class=cap,
                        pattern=pattern,
                        workspace_prefix=str(item.get("workspace_prefix") or ""),
                        created_at=float(item.get("created_at") or 0.0),
                    )
                )
        self._mem_cache = (sig, list(out))
        return out

    def _save_locked(self, grants: list[SafePatternGrant]) -> None:
        target = self._grants_path()
        mkdirs_owner_only(target.parent)
        payload = {
            "version": 1,
            "grants": [asdict(g) for g in grants],
        }
        atomic_write(
            target,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            restrict_to_owner=True,
            restrict_on_error="warn",
        )
        self._mem_cache = (self._file_sig(target), list(grants))

    def mint_grant(
        self,
        *,
        canonical_tool_id: str,
        capability_class: str,
        pattern: str,
        workspace_prefix: str = "",
        sample_command: str = "",
    ) -> SafePatternGrant:
        """Persist a verified read-only pattern grant; raises on any unsafe shape."""
        tool_id = str(canonical_tool_id or "").strip()
        cap = str(capability_class or "").strip()
        pat = str(pattern or "").strip()
        if cap not in SAFE_ELIGIBLE_CAPABILITIES:
            raise GrantNotSafeEligibleError(
                f"capability_class {cap!r} is not read-only safe eligible"
            )
        if not tool_id or "*" in tool_id:
            raise GrantNotSafeEligibleError(f"invalid canonical_tool_id: {tool_id!r}")
        if not pat or pat == "*" or "*" in pat:
            raise GrantNotSafeEligibleError(f"wildcard or empty pattern refused: {pat!r}")
        if not session_mode_permitted("trust_reads"):
            raise GrantNotSafeEligibleError("governance ceiling denies trust_reads grants")

        if cap == "shell_readonly":
            probe = sample_command or pat
            ok, canonical_pat = _is_safe_readonly_shell_command(probe)
            if not ok or canonical_pat != pat:
                raise GrantNotSafeEligibleError(
                    f"shell command {probe!r} is not an eligible read-only pattern ({pat!r})"
                )
            if self._shell_refused(probe):
                raise GrantNotSafeEligibleError(
                    f"shell command {probe!r} failed trusted binary verification"
                )

        ws_norm = ""
        if workspace_prefix.strip():
            ws_norm = os.path.normpath(workspace_prefix.strip()).replace("\\", "/")
            if os.name == "nt":
                ws_norm = ws_norm.lower()

        with self._lock:
            existing = self._load_locked()
            for g in existing:
                if (
                    g.canonical_tool_id == tool_id
                    and g.capability_class == cap
                    and g.pattern == pat
                    and g.workspace_prefix == ws_norm
                ):
                    return g
            grant = SafePatternGrant(
                grant_id=uuid.uuid4().hex[:16],
                canonical_tool_id=tool_id,
                capability_class=cap,
                pattern=pat,
                workspace_prefix=ws_norm,
                created_at=self._clock(),
            )
            existing.append(grant)
            self._save_locked(existing)
            return grant

    def matches_grant(
        self,
        *,
        canonical_tool_id: str,
        capability_class: str,
        target: str,
        workspace: str = "",
        check_shell_binary: bool = True,
    ) -> SafePatternGrant | None:
        """Return a stored grant iff read-only policy and binary checks pass."""
        if capability_class not in SAFE_ELIGIBLE_CAPABILITIES:
            return None
        if not session_mode_permitted("trust_reads"):
            return None
        tool_id = str(canonical_tool_id or "").strip()
        if not tool_id or "*" in tool_id:
            return None

        matched_pattern = str(target or "").strip()
        if capability_class == "shell_readonly":
            ok, canonical_pat = _is_safe_readonly_shell_command(matched_pattern)
            if not ok or (check_shell_binary and self._shell_refused(matched_pattern)):
                return None
            matched_pattern = canonical_pat

        ws_norm = ""
        if workspace.strip():
            ws_norm = os.path.normpath(workspace.strip()).replace("\\", "/")
            if os.name == "nt":
                ws_norm = ws_norm.lower()

        with self._lock:
            grants = self._load_locked()
        for grant in grants:
            if grant.canonical_tool_id != tool_id or grant.capability_class != capability_class:
                continue
            if grant.workspace_prefix and (
                not ws_norm
                or (
                    ws_norm != grant.workspace_prefix
                    and not ws_norm.startswith(f"{grant.workspace_prefix}/")
                )
            ):
                continue
            if capability_class == "shell_readonly":
                if grant.pattern == matched_pattern:
                    return grant
            else:
                norm_target = os.path.normpath(matched_pattern).replace("\\", "/")
                norm_pat = os.path.normpath(grant.pattern).replace("\\", "/")
                if os.name == "nt":
                    norm_target = norm_target.lower()
                    norm_pat = norm_pat.lower()
                if norm_target == norm_pat or norm_target.startswith(f"{norm_pat.rstrip('/')}/"):
                    return grant
        return None

    def list_grants(self) -> list[SafePatternGrant]:
        with self._lock:
            return self._load_locked()

    def revoke_grant(self, grant_id: str) -> bool:
        with self._lock:
            existing = self._load_locked()
            kept = [g for g in existing if g.grant_id != grant_id]
            if len(kept) == len(existing):
                return False
            self._save_locked(kept)
            return True

    def clear_all(self) -> int:
        with self._lock:
            existing = self._load_locked()
            if existing:
                self._save_locked([])
            return len(existing)

    def _on_policy_deny(self, denied_modes: frozenset[str]) -> None:
        if "trust_reads" in denied_modes:
            self.clear_all()

    def _reset_cache(self) -> None:
        with self._lock:
            self._mem_cache = None


_DEFAULT_SAFE_STORE = SafePatternGrantStore()
register_deny_hook("safe_pattern_grants", _DEFAULT_SAFE_STORE._on_policy_deny)
register_reset_hook("safe_pattern_grants", _DEFAULT_SAFE_STORE._reset_cache)


def default_safe_pattern_grant_store() -> SafePatternGrantStore:
    return _DEFAULT_SAFE_STORE
