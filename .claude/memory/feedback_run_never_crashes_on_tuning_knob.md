---
name: feedback_run_never_crashes_on_tuning_knob
description: Search-tuning knobs (early_stop_patience/epsilon) must clamp, not raise — a run must never hard-fail on a knob it may not even use
metadata:
  type: feedback
---

`parse_problem_config` (both `vrptw_problem/study_bridge.py` and `knapsack_problem/study_bridge.py`) must NOT `raise` on out-of-range `early_stop_patience`/`early_stop_epsilon` — clamp into range / fall back to default instead. Two reasons: (1) these knobs are pure don't-cares while `early_stop=False` (the optimizer ignores them), and (2) the panel schema permits any integer so a panel derive/LLM can persist a stale or zero value that saves fine but then crashes the run — a layer disagreement.

**Why:** session-8745c964 (knapsack tutorial, P18_t): the run-ack chat derive wrote `early_stop_patience=0`, `early_stop_epsilon=0.001` (0.001 ≠ either port's default → LLM-authored, not deterministic). `early_stop` was False, yet the validator's `<1` check hard-failed Runs #3–5 with "early_stop_patience must be between 1 and 5000." Breaks tutorial cleanliness ([[project_tutorial_cleanliness]]).

**How to apply:** The Config UI already clamps identically (`SearchStrategySection.tsx` `Math.max(1, Math.min(5000, …))`) — the backend must match, not be stricter. Fix both ports symmetrically ([[project_workflow_axes]]). This is a deterministic-gate/ownership fix, not a prompt bandage ([[feedback_no_prompt_bandages]]) — you can't stop the LLM derive from emitting a bad value, so the validator is the gate that must tolerate it. Related plumbing: [[feedback_solver_knob_carrier_gap]] (making early_stop reachable from chat).
