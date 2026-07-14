---
name: feedback_solver_knob_carrier_gap
description: A solver knob unreachable from chat because it's missing from the carrier schema/mirrors — the agent then confabulates applying it
metadata:
  type: feedback
---

For a search-strategy/solver knob to be changeable from chat it must be in ALL of: (1) the carrier schema (`VRPTW_GOAL_TERM_PROPERTIES_SCHEMA` — `additionalProperties:False` silently strips anything absent, so a model write is lost), (2) the forward carrier→panel mirror (`sync.py` `sync_panel_from_problem_brief`), (3) the reverse panel→carrier mirror (`problem_brief.py` `sync_problem_brief_from_panel`, next to the P_0602 algorithm mirror), and (4) the prompt (`STUDY_CHAT_SEARCH_STRATEGY_ANCHORING`). Miss any and the knob is unreachable; the agent will still *describe* changing it (confabulated compliance) because the steer reaches the reply but no writer exists.

**Why:** `early_stop` had only the panel field + `always_preserve_current_if_present`, not the carrier path. P17 (VRPTW, ~study halfway) steered "disable stop-early-on-plateau / run all iterations" 6×; `early_stop` stayed True across all 24 runs and the agent claimed success anyway (run19==run20 cost proved the one epoch bump was inert while early_stop was on).

**How to apply:** Boolean knobs need `isinstance(x, bool)` gating in the forward mirror, NOT truthiness — `false` is the meaningful value, not "unset" (epochs/pop_size use truthiness and would drop it). Both mirrors are required or you reintroduce the [[feedback_panel_authoritative_for_algorithm]] / [[feedback_lock_two_stores_reconcile]] drift class (stale carrier clobbers a later panel edit). This was a silent mid-study fix (schema+2 mirrors+prompt; plateau-OQ scripted text deliberately left unchanged so no participant-facing string moved). Confabulation itself is a reportable design finding — see [[feedback_no_prompt_bandages]] (structural writer, not a prompt bandage).
