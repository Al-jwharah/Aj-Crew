"""The shipped build contacts none of the upstream project's services on its own.

Aj Crew is a fork, and the upstream project's release feed, usage beacon,
feedback form and app catalog are that project's, not this one's. A build that
defaulted to them would offer the upstream project's builds as its own updates,
report its installs to their collector, send survey answers to their form and
read their catalog on every store load. These tests pin the defaults that keep
all four off until an operator names an endpoint or opts in.

The suite's floor configures a release feed for the update tests
(``_release_feed_test_hosts``), so the tests of the shipped default clear it
again, and the constants themselves are read from source rather than from the
patched module.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from aj_crew.apps import official_catalog
from aj_crew.config.sections_telemetry import TelemetryConfig
from aj_crew.dashboard.handlers import feedback, updates
from aj_crew.platform import update_capability, update_layout
from aj_crew.platform.update_capability import derive_capability

_SRC = Path(update_layout.__file__).resolve().parents[1]


def _module_constants(relative: str) -> dict[str, object]:
    """Top-level ``NAME = <literal>`` assignments of a source file, by name."""
    tree = ast.parse((_SRC / relative).read_text(encoding="utf-8"))
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                found[target.id] = node.value.value
    return found


@pytest.fixture
def _no_feed(monkeypatch):
    """The shipped state: no release feed named anywhere."""
    monkeypatch.delenv("AJCREW_CDN_BASE", raising=False)
    monkeypatch.setattr(update_layout, "DEFAULT_FEED_BASE", "")
    monkeypatch.setattr(update_layout, "DEFAULT_ARTIFACT_BASE", "")


class TestTheSourceNamesNoUpstreamHost:
    def test_the_release_feed_hosts_are_empty(self):
        constants = _module_constants("platform/update_layout.py")
        assert constants["DEFAULT_FEED_BASE"] == ""
        assert constants["DEFAULT_ARTIFACT_BASE"] == ""

    def test_the_beacon_endpoint_is_empty(self):
        constants = _module_constants("config/sections_telemetry.py")
        assert constants["_DEFAULT_BEACON_ENDPOINT"] == ""

    def test_the_survey_endpoints_are_empty(self):
        constants = _module_constants("dashboard/handlers/feedback.py")
        assert constants["_INGESTION_URL"] == ""
        assert constants["_PROMPT_URL"] == ""


class TestNoReleaseFeed:
    def test_there_is_no_feed_to_check(self, _no_feed):
        assert update_layout.cdn_bases() == ("", "")
        assert update_layout.release_feed_configured() is False

    def test_an_empty_base_is_not_a_safe_base(self, _no_feed):
        # Every route that installs gates on this, so it refuses on its own.
        assert update_layout.cdn_bases_are_safe() is False

    def test_no_installer_command_is_offered(self, _no_feed):
        # A ``curl`` line against an empty base could not work; an empty command
        # is what callers already render as "nothing to copy".
        assert update_layout.wheel_update_command("stable") == ""

    def test_the_pip_hint_explains_instead_of_naming_a_command(self, _no_feed):
        hint = update_layout.non_managed_pip_upgrade_command("stable")
        assert hint.command is None
        assert hint.note == update_layout.NO_RELEASE_FEED_NOTE

    def test_an_override_names_both_bases(self, _no_feed, monkeypatch):
        monkeypatch.setenv("AJCREW_CDN_BASE", "https://cdn.example.test/")
        assert update_layout.cdn_bases() == (
            "https://cdn.example.test",
            "https://cdn.example.test",
        )
        assert update_layout.release_feed_configured() is True

    @pytest.mark.parametrize("dist", ["wheel", "source"])
    def test_the_capability_says_where_updates_come_from(self, _no_feed, dist, tmp_path):
        capability = derive_capability(install_root=str(tmp_path), dist=dist)
        assert capability.managed_by == "ajcrew"
        assert capability.can_download is False
        assert capability.can_apply is False
        assert capability.remediation == {
            "kind": "command",
            "message": update_layout.NO_RELEASE_FEED_NOTE,
            "command": "",
        }
        # Re-pinning for a channel must not invent a command either.
        repinned = capability.for_channel("insider")
        assert repinned.remediation is not None
        assert repinned.remediation["command"] == ""

    def test_the_note_points_at_this_project(self):
        assert "github.com/Al-jwharah/Aj-Crew" in update_layout.NO_RELEASE_FEED_NOTE

    def test_the_check_reports_no_verdict_without_touching_the_network(
        self, _no_feed, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("AJCREW_PROJECT_DIR", raising=False)
        monkeypatch.setattr(update_layout, "data_home", lambda: tmp_path)
        monkeypatch.setattr(update_capability, "distribution", lambda: "wheel")
        original = dict(updates._update_info)
        reached: list[str] = []

        async def _record(url: str) -> tuple[int, bytes]:
            reached.append(url)
            return 200, b"{}"

        monkeypatch.setattr(updates, "_fetch_feed_bytes", _record)
        try:
            asyncio.run(updates._do_update_check())
            info = updates.get_update_info()
        finally:
            updates._update_info.clear()
            updates._update_info.update(original)

        assert reached == []
        assert info["update_available"] is not True
        assert info["check_status"] == "failed"
        assert info["error_code"] == "feed_unreachable"


class TestNoUsageBeacon:
    def test_the_beacon_is_off_and_has_nowhere_to_send(self):
        cfg = TelemetryConfig()
        assert cfg.beacon_enabled is False
        assert cfg.beacon_endpoint == ""


class TestNoFeedbackSurvey:
    def test_consent_cannot_make_the_survey_reachable(self, monkeypatch):
        # Whatever the telemetry settings say, there is nowhere to send an
        # answer: the gate answers no before it reads them.
        def _unexpected(*args: object, **kwargs: object) -> object:
            raise AssertionError("the consent ladder was consulted with no survey endpoint")

        monkeypatch.setattr(feedback, "_INGESTION_URL", "")
        monkeypatch.setattr(feedback, "_PROMPT_URL", "")
        monkeypatch.setattr(feedback.AjCrewConfig, "load", _unexpected)
        monkeypatch.setattr(feedback.beacon, "telemetry_permitted", _unexpected)
        assert feedback._telemetry_permitted("feedback_submit") is False


class TestNoCatalogFetch:
    def test_the_store_stays_off_the_network_unless_opted_in(self, monkeypatch):
        monkeypatch.delenv(official_catalog.SKIP_FETCH_ENV, raising=False)
        assert official_catalog.store_fetch_skipped() is True
        assert official_catalog.fetch_document(official_catalog.OFFICIAL_CATALOG_URL) is None
