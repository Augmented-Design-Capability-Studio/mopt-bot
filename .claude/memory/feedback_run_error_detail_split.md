---
name: feedback_run_error_detail_split
description: Run failures split into participant error_message (clean) vs researcher error_detail (raw); plus the .get present-null pitfall.
metadata:
  type: feedback
---

Two related lessons from session-73906e05 (VRPTW runs failing as opaque "error").

**Failure surfacing is a two-field split.** `runs.error_message` is
participant-facing and kept clean/generic; `runs.error_detail` is a
researcher-only raw diagnostic (exception type + message + traceback). The run
router's failure handlers set both; `helpers.run_to_out(row, include_detail=)`
only emits `error_detail` when `include_detail` is True, and `list_runs` passes
that iff `principal != Principal.client`. Never leak `error_detail` to
participants. Frontend: `ResearcherDetail` shows the reason + a red diagnostic
box; participant `ResultsPanel` shows only `error_message`. Column carried
through the archive export and the analysis DB (`loaded_runs.error_detail`).

**Why:** before this, the router's bare `except Exception` collapsed every
unexpected per-problem failure to `"Optimization failed"`, and the researcher
console hardcoded the string `"error"` — so four failed runs were undiagnosable
without reading server logs.

**How to apply:** when adding a failure path, set `error_detail` with the real
cause; keep `error_message` participant-safe. See [[feedback_run_never_crashes_on_tuning_knob]].

**The `.get` present-null pitfall (the actual bug):** `float(raw.get(k, default))`
defaults ONLY when the key is absent. The config panel sends nullable fields
(e.g. VRPTW `max_shift_hours: null` = "no cap") as present-with-None, so `.get`
returns None and `float(None)` raises TypeError (not ValueError → not surfaced).
Coerce with an explicit None check: `x = default if raw.get(k) is None else raw.get(k)`.
Same shape still exists for epochs/pop_size/random_seed in both ports' parsers.
