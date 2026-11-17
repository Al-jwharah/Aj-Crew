# Tool approvals offer task-scoped and read-only pattern grants beneath the ceiling

Decided by: Al-jwharah (owner, @Al-jwharah)
Date: 2026-11-17

## Decision

Interactive tool approval cards offer four bounded choices — Approve once, Approve for this task, Always allow safe read-only pattern, and Deny — where task-scoped grants live only in memory for `(session_key, task_epoch_id)` and persistent pattern grants accept only verified read-only operations stored in the hidden `approval-grants` store, both strictly subordinate to `POLICY ∩ PROFILE` and `approval_modes` revocation.

## Why

- Operators running multi-agent waves hit approval fatigue when forced to choose between single-call prompts and session-wide blanket trust.
- Scoping task grants to `(session_key, task_epoch_id)` in memory eliminates cross-session bleed while keeping repetitive steps inside one task friction-free.
- Restricting persistent pattern grants to verified read-only operations (with `name_grant` binary-shadowing verification on shell reads) prevents a permanent grant from ever becoming a mutating or credential-reading capability.

## Evidence

- Owner architecture directive on `Al-jwharah/Aj-Crew` (`main`, 2026-11-17) specifying Mission 2 (`task_scoped_grants.py` + `safe_pattern_grants.py` + `approval-grants` hidden store).
