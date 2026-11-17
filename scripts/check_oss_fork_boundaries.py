#!/usr/bin/env python3
"""Offline OSS fork-boundary diff scanner for Al-jwharah/Aj-Crew.

Replaces the upstream AWS OIDC + private S3 ruleset dependency with a
deterministic, stdlib-only scanner that checks ONLY added lines and newly added
paths in a change. Uses SHA-256 host/package digests from
``scripts/verify_no_internal_host.py`` so no internal wordlist is spelled in
plaintext inside the public repository (per ``docs/system-specs/oss-fork-boundaries.md``).

Exit codes:
  0 — clean diff
  1 — one or more fork-boundary violations found
  2 — diff input missing or unreadable (fail closed)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Import SHA-256 digest sets from sibling verify_no_internal_host.py without
# spelling any internal host or package name in plaintext.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import verify_no_internal_host as _host_gate  # noqa: E402

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_DIFF_PLUS_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")

_PLACEHOLDER_AWS_ACCOUNTS = frozenset(
    {
        "000000000000",
        "111111111111",
        "111122223333",
        "123456789012",
        "210987654321",
        "222233334444",
        "444455556666",
        "999999999999",
    }
)
_ARN_ACCOUNT_RE = re.compile(r"\barn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:(\d{12}):")

_ALLOWED_SAMPLE_USERS = frozenset(
    {
        "admin",
        "alice",
        "bob",
        "ci",
        "demo",
        "dev",
        "developer",
        "docker",
        "ec2-user",
        "example",
        "foo",
        "bar",
        "me",
        "operator",
        "root",
        "runner",
        "test",
        "ubuntu",
        "user",
        "username",
        "vagrant",
        "you",
        "your-name",
        "yourname",
    }
)
_WORKSTATION_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_])/Users/([A-Za-z0-9._-]+)/"
    r"|(?<![A-Za-z0-9_])/home/([A-Za-z0-9._-]+)/"
    r"|\b[Cc]:\\Users\\([A-Za-z0-9._-]+)\\)"
)

_FORBIDDEN_RUM_RE = re.compile(r"\baws-rum-web\b")

_BUILTIN_APPS_BACKEND_PREFIX = "src/aj_crew/apps/builtins/"
_BUILTIN_APPS_FRONTEND_PREFIX = "website/src/apps/"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    col: int
    rule_id: str
    text: str

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: [{self.rule_id}] {self.text}"


def _existing_builtin_app_slugs(root: pathlib.Path) -> tuple[frozenset[str], frozenset[str]]:
    backend_dir = root / "src" / "aj_crew" / "apps" / "builtins"
    web_dir = root / "website" / "src" / "apps"
    b_slugs = (
        frozenset(
            p.name for p in backend_dir.iterdir() if p.is_dir() and not p.name.startswith("_")
        )
        if backend_dir.is_dir()
        else frozenset()
    )
    w_slugs = (
        frozenset(p.name for p in web_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))
        if web_dir.is_dir()
        else frozenset()
    )
    return b_slugs, w_slugs


def parse_unified_diff(diff_text: str) -> tuple[list[tuple[str, int, str]], set[str]]:
    """Return ``(added_lines, newly_created_files)`` from a ``git diff`` output."""
    added_lines: list[tuple[str, int, str]] = []
    new_files: set[str] = set()
    current_path: str | None = None
    lineno = 0
    pending_new_file = False

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_path = None
            lineno = 0
            pending_new_file = False
            continue
        if raw_line.startswith("new file mode "):
            pending_new_file = True
            continue
        m_file = _DIFF_PLUS_FILE_RE.match(raw_line)
        if m_file:
            current_path = m_file.group(1)
            if pending_new_file:
                new_files.add(current_path)
            continue
        if raw_line.startswith("+++ /dev/null"):
            current_path = None
            continue
        m_hunk = _HUNK_RE.match(raw_line)
        if m_hunk:
            lineno = int(m_hunk.group(1))
            continue
        if current_path is None or lineno <= 0:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added_lines.append((current_path, lineno, raw_line[1:]))
            lineno += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        elif raw_line.startswith(" "):
            lineno += 1
    return added_lines, new_files


def _is_test_or_scanner_path(path: str) -> bool:
    return (
        path.startswith("test/")
        or "/tests/" in path
        or path.endswith((".test.ts", ".test.tsx", ".spec.ts"))
        or path == "scripts/check_oss_fork_boundaries.py"
    )


def scan_diff(
    diff_text: str,
    *,
    allowed_backend_apps: frozenset[str] | None = None,
    allowed_frontend_apps: frozenset[str] | None = None,
    extra_host_digests: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Scan unified *diff_text* and return deterministic :class:`Finding` rows."""
    if allowed_backend_apps is None or allowed_frontend_apps is None:
        b_apps, w_apps = _existing_builtin_app_slugs(REPO_ROOT)
        if allowed_backend_apps is None:
            allowed_backend_apps = b_apps
        if allowed_frontend_apps is None:
            allowed_frontend_apps = w_apps

    denylist = _host_gate._Denylist(
        _host_gate.HOST_DIGESTS | extra_host_digests,
        _host_gate.NAME_DIGESTS,
        _host_gate.BUILD_MARKER_DIGESTS,
    )

    added_lines, new_files = parse_unified_diff(diff_text)
    findings: list[Finding] = []

    for nf in sorted(new_files):
        if nf == "CODE_APPROVERS.yaml" or nf.endswith("/CODE_APPROVERS.yaml"):
            findings.append(
                Finding(nf, 1, 1, "forbidden-internal-build-file", "CODE_APPROVERS.yaml")
            )
        if nf.startswith(_BUILTIN_APPS_BACKEND_PREFIX):
            rest = nf[len(_BUILTIN_APPS_BACKEND_PREFIX) :]
            slug = rest.split("/", 1)[0]
            if "/" in rest and not slug.startswith("_") and slug not in allowed_backend_apps:
                findings.append(
                    Finding(nf, 1, 1, "no-new-builtin-apps", f"new built-in backend app {slug!r}")
                )
        if nf.startswith(_BUILTIN_APPS_FRONTEND_PREFIX):
            rest = nf[len(_BUILTIN_APPS_FRONTEND_PREFIX) :]
            slug = rest.split("/", 1)[0]
            if "/" in rest and not slug.startswith("_") and slug not in allowed_frontend_apps:
                findings.append(
                    Finding(nf, 1, 1, "no-new-builtin-apps", f"new built-in frontend app {slug!r}")
                )

    for path, lineno, content in added_lines:
        if path == "scripts/check_oss_fork_boundaries.py":
            continue
        is_test = _is_test_or_scanner_path(path)

        # 1. Internal host / package SHA-256 digest match (outside explicit exclusions)
        rel_wheel_style = path.removeprefix("src/")
        excused = (
            _host_gate.EXCLUSIONS[rel_wheel_style][1]
            if rel_wheel_style in _host_gate.EXCLUSIONS
            else frozenset()
        )
        folded = content.encode("utf-8", errors="replace").replace(b"\\.", b".")
        for token in folded.translate(_host_gate._TOKENIZE).split():
            matched_digest = denylist.match(token)
            if matched_digest is not None and matched_digest not in excused and not is_test:
                col = max(1, content.lower().find(token.decode("utf-8", "replace").lower()) + 1)
                findings.append(Finding(path, lineno, col, "internal-domain-digest", content))
                break

        # 2. Forbidden RUM SDK re-introduction outside docs explaining the ban
        if not is_test and not path.startswith("docs/"):
            m_rum = _FORBIDDEN_RUM_RE.search(content)
            if m_rum:
                findings.append(
                    Finding(path, lineno, m_rum.start() + 1, "forbidden-aws-rum-web", content)
                )

        # 3. Non-placeholder 12-digit AWS account IDs in ARNs (production/CI/config files)
        if not is_test and not path.startswith("docs/"):
            for m_arn in _ARN_ACCOUNT_RE.finditer(content):
                acct = m_arn.group(1)
                if acct not in _PLACEHOLDER_AWS_ACCOUNTS:
                    findings.append(
                        Finding(path, lineno, m_arn.start(1) + 1, "aws-account-arn", content)
                    )
                    break

        # 4. Leaked personal workstation paths
        if not is_test:
            for m_ws in _WORKSTATION_PATH_RE.finditer(content):
                uname = (m_ws.group(1) or m_ws.group(2) or m_ws.group(3) or "").lower()
                if uname and uname not in _ALLOWED_SAMPLE_USERS and not uname.startswith("<"):
                    findings.append(
                        Finding(
                            path,
                            lineno,
                            m_ws.start() + 1,
                            "leaked-workstation-path",
                            content,
                        )
                    )
                    break

    return findings


def _git_diff_from_base(base_ref: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "--unified=0", base_ref, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git diff exited {proc.returncode}")
    return proc.stdout


def sha256_token(text: str) -> str:
    """Helper for tests to hash a synthetic domain/token without storing wordlists."""
    return hashlib.sha256(text.lower().encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diff-file",
        type=pathlib.Path,
        default=None,
        help="Path to a pre-computed unified diff file.",
    )
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("OSS_BOUNDARY_BASE_REF", ""),
        help="Git base ref to diff against HEAD when --diff-file is omitted.",
    )
    args = parser.parse_args(argv)

    try:
        if args.diff_file is not None:
            diff_text = args.diff_file.read_text(encoding="utf-8", errors="replace")
        elif args.base_ref:
            diff_text = _git_diff_from_base(args.base_ref)
        else:
            # Default local check: uncommitted + staged changes against HEAD.
            proc = subprocess.run(
                ["git", "--no-optional-locks", "diff", "--unified=0", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "git diff HEAD failed")
            diff_text = proc.stdout
    except Exception as exc:
        print(f"check_oss_fork_boundaries: could not read diff: {exc}", file=sys.stderr)
        return 2

    findings = scan_diff(diff_text)
    if findings:
        for f in findings:
            print(f.format())
        return 1
    print("oss-fork-boundaries: clean ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
