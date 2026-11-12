"""The onboarding engine's module list, read by both facade contract test files.

``test_onboarding_import_refactor_contract.py`` imports each module first and reads
what each binds; ``test_onboarding_import_refactor_contract_patch_guards.py`` reads the
same list to find a rebound name's other holders.
"""

from __future__ import annotations

#: Every module of the engine, facade included.
_ENGINE_MODULES = (
    "aj_crew.onboarding_import",
    "aj_crew.onboarding_scan",
    "aj_crew.onboarding_plan",
    "aj_crew.onboarding_apply",
    "aj_crew.onboarding_sources",
    "aj_crew.onboarding_sources.amazon_quick",
    "aj_crew.onboarding_sources.claude_code",
    "aj_crew.onboarding_sources.codex",
    "aj_crew.onboarding_sources.gemini",
    "aj_crew.onboarding_sources.hermes",
    "aj_crew.onboarding_sources.lineage",
    "aj_crew.onboarding_sources.openclaw",
)
