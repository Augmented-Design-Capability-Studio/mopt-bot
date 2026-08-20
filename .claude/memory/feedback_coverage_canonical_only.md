---
name: feedback_coverage_canonical_only
description: Formulation-quality coverage counts ONLY the 7 briefed canonical terms (0-11 total). Idle-wait (waiting_time) is NOT scored and NOT in the canonical cost — it's a manually-coded qualitative phenomenon (agile never revealed it). The 8-term/w8 experiment was reverted.
metadata:
  type: feedback
---

The analyzer's formulation-quality score (`formulation_quality_for_config` in each
study port; surfaced in the Aggregate notebook's `snapshots` frame) must score
**only the briefed canonical terms**. VRPTW canonical = travel_time + 3 hard + 3
soft = 7; `coverage` (0-7) + `hard_bonus` (0-3) + `objective_bonus` (0-1) = the
0-11 `formulation_score`.

**Why:** `coverage` was `len(captured_terms)` = every active goal term, so an
un-briefed term (e.g. `waiting_time`/idle-wait, w8 — deliberately omitted from the
canonical set, see [[project_workflow_axes]] symmetry) silently inflated coverage
and the score, contradicting the "canonical 7 / 0-11" framing and breaking
cross-session comparability.

**How to apply:** The port keeps `coverage` = active canonical terms only (7);
`formulation_score` = coverage + hard_bonus + objective_bonus (0-11). `captured_terms`
stays the full active superset (incl. un-briefed terms like idle-wait) — drives the
per-term timing chart, NOT the score. No idle-wait scoring fields on the port.

**Idle-wait experiment — tried then REVERTED (2026-08).** Briefly promoted idle-wait
to a scored 8th coverage term (`*_with_wait` port fields, cell 21 at /8-/12) and added
it to the canonical cost objective (`OFFICIAL_WEIGHTS` w8=0.5). Reverted because the
DATA killed it: idle-wait is transient — in the FINAL config 0/26 sessions kept it, so
crediting it changed no score (identical bars). The real finding is an EXPLORATION
asymmetry: ~6/13 waterfall participants surfaced idle-wait mid-session vs 0/13 agile
(Fisher p≈0.015), all dropped before the end — i.e. **the agile agent never revealed
it.** So idle-wait is now a QUALITATIVE phenomenon only: reported in notebook **cell 17**
(a placeholder for hand-coded goal-term origins from the Session-coding tab; the
auto brief-provenance chart was removed), computed from `captured_terms`. Canonical
objective is back to 7 terms, w8=0 (`OFFICIAL_WEIGHTS` removed). Cell 15 (hard-
constraints-binding barh) deleted; cell 22 replaced with a FINAL-vs-MAX formulation-
score agile/waterfall comparison (max = each participant's peak snapshot score;
non-monotonic formulations mean max slightly sharpens the waterfall gap).

**Canonical COST weight — w3 (time-window) raised 50→200 (2026-08).** The canonical
cost objective is `DEFAULT_WEIGHTS` in `vrptw_problem/user_input.py` (single source;
`evaluate_official`/`canonical_evaluation_for_result` re-score every run's schedule under
it, seed-averaged; participant panel default too, but the study is DONE so this only
affects our re-evaluation, not stored sessions). `w3` was the cheap hard constraint
(50/min vs shift w2=500/min, capacity w4=1000/unit) — raised to 200/min (researcher
decision, mid-way to shift; both are hard per-minute constraints). Effect: sharpens the
agile-vs-waterfall gap in best-run canonical cost (agile median 3184→5200; waterfall
~1029 unchanged since their best runs rarely violate TW). Hard-constraint HARDNESS is
enforced by the binary `feasible` flag (any TW violation → infeasible), independent of
w3 — the weight only sets continuous cost magnitude. The finding (workload_balance is
the main term agile does worse on; agile also more TW-violations/infeasible bests) is
ROBUST across w3∈{50..1000}. Weights are NOT directly comparable raw — different units;
at w3=50 a typical TW violation (~52 min) already cost ~2600 ≈ capacity's ~4000.

Notebook source of truth = `backend/analysis/notebooks/browser_cells.py`
(re-imported via "Import .py"); keep the `PyodideNotebook.tsx` seed cells roughly in
sync. Relates to [[project_session_coding_scheme]].
