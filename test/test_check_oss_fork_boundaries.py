"""Unit tests for scripts/check_oss_fork_boundaries.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_oss_fork_boundaries.py"
_SPEC = importlib.util.spec_from_file_location("check_oss_fork_boundaries", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
scanner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = scanner
_SPEC.loader.exec_module(scanner)


def test_clean_public_diff_passes() -> None:
    diff = (
        "diff --git a/src/aj_crew/example.py b/src/aj_crew/example.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/aj_crew/example.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+# Public module using example placeholder ARN\n"
        '+ROLE_EXAMPLE = "arn:aws:iam::123456789012:role/example-role"\n'
        '+HOME_DOC = "/home/ubuntu/workspace"\n'
    )
    assert scanner.scan_diff(diff) == []


def test_detects_internal_domain_digest_aws_arn_workstation_path_and_new_builtin_app() -> None:
    synthetic_domain = "corp-secret.internal-example.invalid"
    extra_digests = frozenset({scanner.sha256_token(synthetic_domain)})
    diff = (
        "diff --git a/src/aj_crew/apps/builtins/brand_new_app/server.py "
        "b/src/aj_crew/apps/builtins/brand_new_app/server.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/aj_crew/apps/builtins/brand_new_app/server.py\n"
        "@@ -0,0 +1,4 @@\n"
        f'+WIKI = "https://wiki.{synthetic_domain}/page"\n'
        '+REAL_ARN = "arn:aws:iam::987654321098:role/prod-secret"\n'
        '+LOCAL_PATH = "/Users/johndoe/private-notes/token.txt"\n'
        "+import aws_rum_web  # aws-rum-web\n"
    )
    findings = scanner.scan_diff(
        diff,
        allowed_backend_apps=frozenset({"existing_app"}),
        allowed_frontend_apps=frozenset(),
        extra_host_digests=extra_digests,
    )
    rules = {f.rule_id for f in findings}
    assert rules == {
        "no-new-builtin-apps",
        "internal-domain-digest",
        "aws-account-arn",
        "leaked-workstation-path",
        "forbidden-aws-rum-web",
    }


def test_missing_diff_file_exits_2_fail_closed(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.diff"
    assert scanner.main(["--diff-file", str(missing)]) == 2


def test_cli_returns_1_on_violation_and_0_on_clean_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_file = tmp_path / "clean.diff"
    clean_file.write_text(
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,0 +1,1 @@\n"
        "+Hello Aj Crew!\n",
        encoding="utf-8",
    )
    assert scanner.main(["--diff-file", str(clean_file)]) == 0

    bad_file = tmp_path / "bad.diff"
    bad_file.write_text(
        "diff --git a/CODE_APPROVERS.yaml b/CODE_APPROVERS.yaml\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/CODE_APPROVERS.yaml\n"
        "@@ -0,0 +1,1 @@\n"
        "+approvers: []\n",
        encoding="utf-8",
    )
    assert scanner.main(["--diff-file", str(bad_file)]) == 1
    out = capsys.readouterr().out
    assert "[forbidden-internal-build-file]" in out
