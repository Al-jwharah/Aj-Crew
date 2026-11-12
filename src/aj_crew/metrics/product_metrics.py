"""``PRODUCT_METRICS`` -- the reviewed metric names a product destination may get.

The local JSONL sink and an operator's own collector receive everything the core
collects. A PRODUCT destination -- one that reports how Aj Crew is used, back to
whoever builds it -- receives only the names below, carried by
``OtlpDestination.allow``. Everything else stays on the machine: most instruments
exist for local debugging, and the larger the exported set, the larger the privacy
question each release has to answer.

Two rules this set obeys, both enforced by ``test_product_metrics.py``:

* **Counters and gauges only.** A fixed-bucket histogram's buckets may not survive
  a receiving backend, so a distribution is exported as a bucket-labelled counter
  instead. An up/down counter is excluded for the same reason a gauge replaces it:
  "how many right now" is read from live state, not accumulated.
* **Every name is a real instrument.** Each entry is a full instrument name,
  ``ajcrew.`` prefix included, that some module actually declares. The test
  resolves each one against the declaring constant, so a typo or a renamed
  instrument fails there rather than silently exporting nothing.

Names are spelled as literals rather than imported from the declaring modules on
purpose. This set is read where a destination is BUILT, which is downstream of
``metrics.provider``; ``metrics.turns`` imports that module at module scope, so
importing the declaring constants from here would close an import cycle through
it. Keeping this module stdlib-only avoids the question entirely, and the test
does the import and asserts the two agree -- the same guarantee, one step later.

A name joins this set only in a reviewed change that also updates the exported-
metrics list in ``docs/guides/telemetry-otlp-export.md``.
"""

from __future__ import annotations

# Sessions, turns and session trees.
_SESSIONS = frozenset(
    {
        "ajcrew.session.started",
        "ajcrew.session.idle_expired",
        "ajcrew.subagent.spawned",
        "ajcrew.subagent.completed",
        "ajcrew.context.compactions",
        # Finished turns (metrics/turn_completed.py): closed outcome,
        # trigger_source, origin and harness only.
        "ajcrew.turn.completed",
        # Turns that hit the timeout ceiling: a closed `path` and two booleans.
        "ajcrew.turn.timeout.cause",
    }
)

# Crew sessions and session control (metrics/crew_log_export.py,
# metrics/session_control_calls.py). `agent_kind`, `actor`, `parent_kind` and
# `caller` fold anything outside their closed sets to `other`; `depth` and
# `nth` are fixed buckets.
_CREW = frozenset(
    {
        "ajcrew.crew.session.started",
        "ajcrew.crew.turn.started",
        "ajcrew.crew.session.tree.depth",
        "ajcrew.crew.session.tree.child",
        "ajcrew.crew.session_control.calls",
    }
)

# Work ledger and Crew Mode (metrics/work.py, metrics/crew_mode.py). Every
# attribute is a tuple-backed enum or a fixed bucket, with `other` as the
# remainder.
_WORK = frozenset(
    {
        "ajcrew.work.created",
        "ajcrew.work.item_closed",
        "ajcrew.work.dispatches",
        "ajcrew.work.reports",
        "ajcrew.crew_mode.turned_on",
        "ajcrew.crew_mode.new_chats",
        "ajcrew.crew_mode.runs_finished",
        "ajcrew.crew_mode.steers_per_run",
        "ajcrew.crew_mode.worker_waits",
    }
)

# Features: did this subsystem do its job, and how often.
_FEATURES = frozenset(
    {
        "ajcrew.cron.fires",
        "ajcrew.artifact.created",
        "ajcrew.workflow.runs",
        "ajcrew.approval.decisions",
        "ajcrew.autonudge.loops.started",
        "ajcrew.autonudge.loops.stopped",
        "ajcrew.autonudge.ticks",
        # A registered monitor kind or `other` (metrics/monitor_loops.py).
        "ajcrew.monitor.decisions",
        # Outcome folded by webhooks.metric_outcome.
        "ajcrew.webhook.requests",
        # Feature-use counters (metrics/feature_usage.py).
        "ajcrew.memory.recalled",
        "ajcrew.lesson.injected",
        "ajcrew.skill.lazy_load.count",
        "ajcrew.app.task.completed",
        "ajcrew.channel.message.received",
        "ajcrew.ui.control.clicked",
    }
)

# What is installed and switched on. Every one of these is an observable gauge
# read from live state at collection time.
_INVENTORY = frozenset(
    {
        "ajcrew.inventory.crons.active",
        "ajcrew.inventory.monitor_loops.active",
        "ajcrew.inventory.skills.installed",
        "ajcrew.inventory.memory.migrated",
        "ajcrew.inventory.knowledge.documents",
        "ajcrew.inventory.lessons",
        "ajcrew.inventory.mcp.servers",
        "ajcrew.inventory.config.toggle",
        "ajcrew.inventory.probe.failures",
        # Crewmates the person created; the count rides in the value.
        "ajcrew.inventory.members",
    }
)

# In-product recommendations: feature tips, the Explore panel (milestones.py)
# and feature videos -- are they used, and does a recommended feature get used.
# Every attribute value is closed at its emit site: tip and video features are
# shipped doc names or Explore ids, milestone values are catalog keys, and
# milestone.reached{recommended_by} is one of tip / explore / video / several /
# none. No tip id, video id or timestamp is an attribute.
_RECOMMENDATIONS = frozenset(
    {
        "ajcrew.tips.feedback",
        "ajcrew.feature_video.status",
        "ajcrew.milestone.panel_opened",
        "ajcrew.milestone.starter_clicked",
        "ajcrew.milestone.reached",
        "ajcrew.milestone.skipped",
        "ajcrew.milestone.mark_all_done",
        "ajcrew.milestone.notice_shown",
        "ajcrew.milestone.features_completed",
    }
)

#: The v1 export allowlist: every metric a product destination may receive.
PRODUCT_METRICS: "frozenset[str]" = (
    _SESSIONS | _CREW | _WORK | _FEATURES | _INVENTORY | _RECOMMENDATIONS
)

# PENDING -- reviewed for export but NOT exportable yet. Each one joins
# PRODUCT_METRICS in the change that clears its reason, not before.
#
# Held on an OPEN attribute value, not on a missing instrument:
#   ajcrew.turn.tokens -- the instrument exists and the metric is wanted, but
#     its `model` attribute is the configured model id, which is not drawn from
#     any set this repo controls: on a non-Kiro backend it can be a provider
#     resource id, so its range is whatever that provider names and whatever the
#     person pointed the backend at. `provider` is configured the same way. Every
#     attribute value on an exported series has to come from a closed enum, so
#     this one waits for a bucketed or enumerated stand-in for those two. A
#     negative guard in test_product_metrics.py keeps it out, so putting it back
#     is a deliberate change rather than an edit nobody reads.
#
# Held on the instrument KIND:
#   ajcrew.turn.completed.duration -- every attribute is closed, but it is a
#     histogram, and this allowlist takes counters and gauges only. It joins
#     when the export path carries native histograms; until then the outcome
#     mix is read from ajcrew.turn.completed.
#
# Held on a missing instrument -- a name here with no instrument would export
# nothing while reading as if it did:
#   ajcrew.knowledge.searched
#
# Held on the kind oracle:
#   ajcrew.crew.session.tree.roots -- an observable gauge declared outside
#     inventory_gauges / process_gauges, so the kind check would read it as a
#     counter. It joins once the test's gauge population includes it.
#
# Not proposed: ajcrew.crew_log.* is the crew log's own runtime health
# (queue depths, fold timings, lost writes). It stays on the machine.
