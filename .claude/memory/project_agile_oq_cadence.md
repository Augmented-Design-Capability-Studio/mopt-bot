---
name: project_agile_oq_cadence
description: Agile post-run OQ:assumption ratio is a researcher-controlled blocked-randomization lever (not a soft prompt bias)
metadata:
  type: project
---

In agile mode, whether a **post-run** turn raises an open question vs commits an
assumption is a **controlled-study independent variable**, not the old soft
~70/30 prompt bias.

**Mechanism (blocked randomization):** runs are grouped into blocks of N. In each
block EXACTLY ONE post-run turn is the OQ turn, at a *uniformly random position
within the block* (seeded per `(session, N, block)` → reproducible/auditable); the
rest are assumptions. So the realized ratio is exact `1:(N-1)` without pinning the
OQ to a fixed run index. The server resolves the directive on each agile run-ack
turn and injects a "raise one OQ" / "add one assumption" block that OVERRIDES the
soft bias.

**Pieces:** `backend/app/services/agile_post_run_schedule.py` (`post_run_oq_directive`,
pure + tested) → computed in `router.py` on the run-ack turn (run_number = max in
recent_runs_summary) → threaded `run_chat_pipeline → generate_main_turn →
build_main_turn_system_instruction` as `post_run_directive` → prompt block in
`_build_visible_chat_system_instruction` after `_run_ack_prompt`. Researcher field
`StudySession.agile_oq_every_n_runs` (nullable int; migration in db_maintenance;
PATCH via `model_fields_set`; dropdown in `ResearcherDetail.tsx`, agile-only).

Values: `null` = off (soft bias), `0` = never (all assumptions), `1` = every run
(all OQs), `N≥2` = one OQ per N runs. This is effectively a controllable 5th axis
beyond the [[project_workflow_axes]] four. Decision with user: forced one decision
per run; blocked-random (not fixed cadence) to avoid confounding OQ with run
position.
