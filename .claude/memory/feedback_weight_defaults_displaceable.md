---
name: feedback-weight-defaults-displaceable
description: Weight defaults must be displaceable cold-start seeds, never frozen relational clamps that fight the organic run-feedback loop
type: feedback
---

The study's premise is **free-flowing, organic preference elicitation**:
the participant runs → observes the cost breakdown → retunes, and the loop
(not a baked-in prior) drives the final weight vector. Three kinds of
prompt "default" exist; they are NOT equivalent:

1. **Mapping / disambiguation** (e.g. bare "priority" → `lateness_penalty`,
   not `express_miss_penalty`). About *which knob*, not magnitude. KEEP.
2. **Single-term cold-start seeds** (e.g. `max_shift_hours` 8.0 when a limit
   is mentioned without a number; `shift_limit` weight 500 for a strict cap).
   A starting number for a concept named-but-unquantified. KEEP — you can't
   avoid seeding *some* number, and a transparent displaceable seed beats a
   hidden arbitrary one. Safe only because the config-derive reads the
   brief's *current* value, so a user/run change is never re-clamped.
3. **Cross-term relational priors** (e.g. "keep lateness ≥ 2× express unless
   the user overrides"). These impose a trade-off rate the user never stated
   AND get re-applied every config-derive turn (`re-derive from the brief
   this turn`), so they can snap a run-driven organic change back. REMOVE /
   DEMOTE — this is the only kind that defeats the free-flow premise.

**Why:** a frozen relational clamp silently overrides exactly the organic
feedback the study is about (user nudges express up after seeing express
orders arrive late → agent re-clamps to 2×). Defaults don't defeat
free-flow; *frozen* defaults do. The distinction is prior-vs-lock: a prior
the loop can move is fine; a clamp that survives feedback is not.

**How to apply:** when editing `*/study_prompts.py` weight guidance, never
write "keep X ≥ N× Y" or "X stronger than Y" style ratios. If two terms
co-exist with no stated relative emphasis, seed comparable weights and let
the loop set the balance. Removed the VRPTW 2× lateness/express rule (June
2026). Single-value cold-start seeds stay. Relates to [[feedback_agile_proactive_assumptions]]
(agent proposes, loop + participant decide) and the run-ack /
plateau feedback machinery in [[project_workflow_axes]].

**Implemented scheme (June 2026) — three-tier × symmetric rank nudge.**
Weight is derived from `(type, rank)` in `frontend/.../problemConfig/
ProblemConfigBlocks.tsx` (`suggestedWeightForType` + `rankNudgeFactor`):
- **Tier base by type:** objective 1, soft 10, hard 100 — a clean 1/10/100
  penalty hierarchy (objective is the *baseline*; penalties dominate). `custom`
  = participant-typed manual override.
- **Rank nudge:** small SYMMETRIC ±10% around the tier base (`RANK_NUDGE=0.1`),
  centered on the middle rank so higher rank goes up AND lower rank goes down,
  never crossing a tier. Applies to ALL non-custom types incl. hard.
- **Seed vs clamp (load-bearing):** the tier×nudge is a STARTING SEED only.
  `handleConstraintTypeChange` reseeds to the tier (deliberate re-categorize),
  but `handleReorder` applies only the RELATIVE rank delta to the *current*
  weight (`current × nextFactor/prevFactor`) — it never resets to the tier
  base, so an agent's or participant's free / significant adjustment survives a
  reorder. The agent is told (VRPTW `study_prompts.py`) the tiers are a start
  and it may retune far past them.
- **Deleted magic:** the old `chatEmphasisBoost` (regex keyword-match on chat —
  violated [[feedback_no_regex_for_nl]]) and `contributionAdjust` (silent
  run-share auto-tuning) are gone; weight is now a pure function of (type,rank)
  plus explicit agent/participant edits. Also removed the panel-vs-agent
  mismatch (panel hard=100 vs agent shift=500). NOTE: knapsack port seed brief
  still hard-codes per-term weights (40/0.5) — not yet aligned to the tiers.

**Paper angle:** defend the organic claim empirically with a *displacement
metric* — fraction of sessions whose final weight vector moved away from the
seeded defaults, and how far. High displacement = the loop, not the prior,
drove the outcome.
