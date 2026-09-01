---
name: ranking-asymmetry-finding
description: Confirmed headline finding — all 14 waterfall vs exactly 7/14 agile participants reordered goal-term rankings; ownership explanation; P09/P19 label resolution
metadata:
  type: project
---

Confirmed (Aug 2026, two independent checks that now agree with zero
per-participant disagreements): **all 14 waterfall participants reordered
goal-term rankings at least once; exactly 7/14 agile did** (Fisher p=.0058).

- Check A (structural, use as the paper's definition): consecutive panel
  snapshots, relative order of COMMON terms changed (add/remove renumbering
  excluded). Check B: manual coding tags type='ranking'.
- Agile rankers: P01, P05, P09, P13, P15, P17, P23.
- Label resolutions: P09 IS a ranker (real reorder at snapshot 1237→1238
  manual_save, express above travel_time; missing tag added 2026-08-31 as
  anno on message:2268, origin=user/type=ranking/term=express_miss_penalty).
  P19 is NOT a ranker (user confirmed a system glitch; their old 'ranking'
  tags were re-coded to weight — the change was a lateness soft→hard type
  promotion, never a reorder).
- Steering was fair / conservative: agile got MORE rank-directed steering
  (11 rank-or-config nudge sends vs 3) and still half never ranked; 12/14
  waterfall reranked with ZERO rank-related steers. Unprompted: 12/14
  waterfall vs 5/14 agile (P05, P09 reranked after nudges).
- Mechanism (proposed, descriptive-supported): OWNERSHIP, not the run gate.
  12/14 waterfall first reranks happen AFTER the first run (~16 min, runs
  ~6 min) so it is iterative refinement, not forced setup. Waterfall users
  authored priorities by answering trade-off OQs (axis 1) → revisit their
  own draft; agile received rankings as agent assumptions (axis 2 fait
  accompli) → treat structure as agent's territory. Dissociation: 6/7 agile
  non-rankers still made user-initiated WEIGHT edits (P25: zero, also
  ignored 4 steers) — engaged with magnitudes, not structure.
- Analysis scripts in session scratchpads: confirm_ranking.py,
  steer_rank.py. DB backup before the tag insert:
  mopt_analysis_SAFECOPY_2026-08-31.db.

Related: [[pretask-predictors-quiz-finding]] (same theme: the discretionary
side of formulation is where user behavior differentiates),
[[Agile vs Waterfall — the 4 canonical differences]]
