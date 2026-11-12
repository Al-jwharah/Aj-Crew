"""Behavioral metrics: their own scope, closed Feature / Activity / Entity.

The unit tests pin the reshape for each listed metric. The export-path test drives
the REAL provider, recorder and local JSONL sink, and reads the shards back: a
behavioral metric lands under ``aj.crew`` with the new shape, and an ordinary
product metric still lands under ``aj_crew`` with its attributes untouched.
"""

from __future__ import annotations

import json

import pytest

from aj_crew.config.loader import AjCrewConfig, TelemetryConfig
from aj_crew.metrics import feature_usage as fu
from aj_crew.metrics import provider as provider_mod
from aj_crew.metrics.behavioral_metrics import (
    BEHAVIORAL_METRICS,
    BEHAVIORAL_SCOPE,
    behavioral_attributes,
)
from aj_crew.metrics.recorder import MetricsRecorder


@pytest.mark.parametrize(
    ("name", "attrs", "expected"),
    [
        (
            "ajcrew.tips.feedback",
            {"action": "helpful", "source": "curated", "feature": "artifacts.md"},
            {
                "Feature": "tips",
                "Activity": "helpful",
                "Entity": "artifacts.md",
                "source": "curated",
            },
        ),
        (
            "ajcrew.feature_video.status",
            {"status": "seen", "feature": "monitor-loops"},
            {"Feature": "feature_video", "Activity": "seen", "Entity": "monitor-loops"},
        ),
        (
            "ajcrew.milestone.panel_opened",
            {},
            {"Feature": "milestone", "Activity": "panel_opened"},
        ),
        (
            "ajcrew.milestone.starter_clicked",
            {"surface": "panel", "milestone": "widgets", "send": "prefill"},
            {
                "Feature": "milestone",
                "Activity": "starter_clicked",
                "Entity": "widgets",
                "surface": "panel",
                "send": "prefill",
            },
        ),
        (
            "ajcrew.milestone.reached",
            {
                "group": "features",
                "milestone": "slack",
                "via": "arrived",
                "recommended_by": "explore",
            },
            {
                "Feature": "milestone",
                "Activity": "reached",
                "Entity": "slack",
                "group": "features",
                "via": "arrived",
                "recommended_by": "explore",
            },
        ),
        (
            "ajcrew.milestone.skipped",
            {"surface": "empty_state", "milestone": "all"},
            {
                "Feature": "milestone",
                "Activity": "skipped",
                "Entity": "all",
                "surface": "empty_state",
            },
        ),
        (
            "ajcrew.milestone.mark_all_done",
            {},
            {"Feature": "milestone", "Activity": "mark_all_done"},
        ),
        (
            "ajcrew.milestone.notice_shown",
            {"group": "features"},
            {"Feature": "milestone", "Activity": "notice_shown", "group": "features"},
        ),
        (
            "ajcrew.milestone.features_completed",
            {"via": "organic"},
            {"Feature": "milestone", "Activity": "features_completed", "via": "organic"},
        ),
    ],
)
def test_each_metric_gets_its_shape(name, attrs, expected):
    before = dict(attrs)
    assert behavioral_attributes(name, attrs) == expected
    assert attrs == before, "the caller's dict must not be changed"


def test_every_metric_is_covered_by_the_shape_table_above():
    """A new entry must come with a row in the parametrized table."""
    assert len(BEHAVIORAL_METRICS) == 9


def test_a_missing_activity_attribute_reads_other():
    assert behavioral_attributes("ajcrew.tips.feedback", {})["Activity"] == "other"


class _Meter:
    def __init__(self) -> None:
        self.points: list = []

    def create_counter(self, name, **_kw):
        meter = self

        class _Counter:
            def add(self, value, attributes=None):
                meter.points.append((name, dict(attributes or {})))

        return _Counter()


def test_the_recorder_routes_only_listed_counters():
    main, behavioral = _Meter(), _Meter()
    rec = MetricsRecorder(main, behavioral)
    rec.counter("ajcrew.milestone.reached", attrs={"milestone": "slack", "via": "manual"})
    rec.counter("ajcrew.memory.recalled", attrs={"path": "tool", "hit": "true"})
    assert behavioral.points == [
        (
            "ajcrew.milestone.reached",
            {"Feature": "milestone", "Activity": "reached", "Entity": "slack", "via": "manual"},
        )
    ]
    assert main.points == [("ajcrew.memory.recalled", {"path": "tool", "hit": "true"})]


def test_a_recorder_without_a_behavioral_meter_changes_nothing():
    main = _Meter()
    MetricsRecorder(main).counter("ajcrew.milestone.panel_opened", attrs={})
    assert main.points == [("ajcrew.milestone.panel_opened", {})]


def _exported(local_dir) -> "dict[str, list[tuple[str, dict]]]":
    """metric name -> [(scope name, point attributes)] off the real local shards."""
    out: "dict[str, list[tuple[str, dict]]]" = {}
    for shard in sorted(local_dir.glob("metrics-*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for rm in json.loads(line).get("resource_metrics") or []:
                for sm in rm.get("scope_metrics") or []:
                    scope = (sm.get("scope") or {}).get("name")
                    for metric in sm.get("metrics") or []:
                        for point in (metric.get("data") or {}).get("data_points") or []:
                            out.setdefault(metric["name"], []).append(
                                (scope, point.get("attributes") or {})
                            )
    return out


def test_the_real_export_path_splits_the_scopes(tmp_path, monkeypatch):
    fake = AjCrewConfig(
        telemetry=TelemetryConfig(
            enabled=True, local_dir=str(tmp_path), export_interval_seconds=3600
        )
    )
    monkeypatch.setattr(AjCrewConfig, "load", classmethod(lambda cls: fake))
    monkeypatch.delenv("AJCREW_TELEMETRY", raising=False)
    provider_mod.reset_for_testing()
    try:
        assert provider_mod.get_recorder().enabled is True
        fu.record_tip_feedback("helpful", "curated", "artifacts.md")
        fu.record_memory_recalled("tool", hit=True)
        provider_mod.shutdown()
        exported = _exported(tmp_path)
    finally:
        provider_mod.reset_for_testing()

    assert exported["ajcrew.tips.feedback"] == [
        (
            BEHAVIORAL_SCOPE,
            {
                "Feature": "tips",
                "Activity": "helpful",
                "Entity": "artifacts.md",
                "source": "curated",
            },
        )
    ]
    assert exported["ajcrew.memory.recalled"] == [("aj_crew", {"path": "tool", "hit": "true"})]
