---
name: feedback_lock_two_stores_reconcile
description: Lock is one concept in two stores (panel locked_goal_terms list vs brief goal_terms[k].locked); panel is authoritative and the derive path must reconcile brief←panel.
metadata:
  type: feedback
---

A goal term's **lock** lives in two places that must always agree:
- Panel `problem.locked_goal_terms` (a list) — where the Config lock 🔒 button
  and the **"custom" type switch** write; what the solver / chat prompt read.
  **Authoritative.**
- Brief `goal_terms[key].locked` (a bool, True-or-absent) — what the
  Definition-tab lock icon reads and what promotion detection uses. A mirror.

**Why it drifts:** on a brief→panel derive turn, `_mirror_locked_from_brief`
folds brief opinions into the panel list AND preserves panel-only locks, so the
panel list is the merged truth — but nothing taught the *brief* about a
panel-only lock (e.g. participant switched a term to "custom" in Config, whose
lock never round-tripped through a panel Save). Result: brief `locked` None vs
panel True → `compute_brief_panel_drift` value_mismatch that S5 retry can't
clear, and the Def tab shows the term as unlocked (P12, `lateness_penalty`).

**How to apply:** the drift check is correct to flag this (see test
`test_drift_detector_flags_per_field_value_mismatch`) — the fix is the missing
*aligner*, not weakening the check. `sync.realign_brief_locks_from_panel` mirrors
the settled panel lock set back into the brief (True for locked keys, drop the
key otherwise), called in the S5 `derive_config` block next to
`realign_panel_scalars_from_brief` (brief→panel scalars) and
`gapfill_brief_companions_from_panel` (panel→brief companions). Frontend:
switching to "custom" locks; switching to any other type (objective/soft/hard)
releases that lock — one shared coupling in `handleConstraintTypeChange`.
Relates to [[feedback_panel_authoritative_for_algorithm]] and
[[feedback_companion_goal_term_pattern]].
