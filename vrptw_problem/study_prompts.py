"""VRPTW-specific participant chat appendix and config-derivation prompts (study layer)."""

from __future__ import annotations

# Single source of truth for how driver-preference rules are carried in the
# brief and the panel. Imported into both the brief-update prompt (so the
# hidden brief LLM emits structured rules) and the config-derive prompt (so
# the panel-derive LLM consumes them verbatim) — keeps the two sides in
# lockstep without copy-paste drift.
DRIVER_PREFERENCES_BRIEF_CONTRACT = """
### Driver-preference rules — structured contract

Driver-preference rules (e.g. "Alice avoids Zone D", "Bob prefers express orders",
"Carol dislikes long shifts past 6.5 hours") live as structured JSON under the
goal term `worker_preference`, at this exact path on both the brief and the panel:

    goal_terms.worker_preference.properties.driver_preferences

Each rule object uses these fields:
- `vehicle_idx` (integer 0–4): Alice=0, Bob=1, Carol=2, Dave=3, Eve=4
- `condition` (string): exactly one of `avoid_zone`, `order_priority`, `shift_over_limit`
- `penalty` (number ≥ 0): cost-units added when the rule fires
- For `avoid_zone`: `zone` (integer 1–5) where A=1, B=2, C=3, D=4, E=5 (depot=0 is invalid)
- For `order_priority`: `order_priority` (string) — exactly `express` or `standard`
- For `shift_over_limit`: `limit_minutes` (number > 0) — e.g. 390 for 6.5h
- Optional: `aggregation` (`per_stop` default, or `once_per_route`)

Worked example — user says "Alice doesn't like Zone D":

    "goal_terms": {
      "worker_preference": {
        "weight": 1.0,
        "type": "soft",
        "properties": {
          "driver_preferences": [
            {"vehicle_idx": 0, "condition": "avoid_zone", "zone": 4, "penalty": 50}
          ]
        }
      }
    }

Rules:
- **Vague mention → ask, don't commit an empty term.** If the user names the
  concept but no concrete rule (e.g. *"I'd like to set some driver preferences"*),
  ASK which driver / what condition — do **not** commit a `worker_preference` term
  with empty `driver_preferences`. Materialise the term only once you have at least
  one concrete rule.
- **Concrete rule → same-turn structured emission is mandatory.** The moment the
  user introduces a driver-preference rule (e.g. *"Alice doesn't like Zone D"*,
  *"add something for Bob who prefers express orders"*) the brief patch for **that
  turn** MUST include `goal_terms.worker_preference.properties.driver_preferences =
  [...]` with the rule populated. A prose `items[]` row about the rule is
  **insufficient** — the panel gets no rule and the term goes hollow.
- **Provenance:** a driver-preference rule the user explicitly asked for
  is `kind: "gathered"`, `source: "user"`, **not** an assumption — even
  when your visible reply uses fait-accompli phrasing. The synthesized
  prose row defaults to gathered for the same reason; do not override it
  to assumption.
- The `driver_preferences` array is **atomic**: send the complete current list
  whenever you change it. Partial merges of individual rules are not supported.
- The system **synthesizes one participant-facing `gathered` row per rule**
  (id `config-driver-pref-{vid}-{discriminator}`) from this carrier — don't write
  those rows yourself, and don't add a separate prose row restating a rule.
- When the brief carries a non-empty `properties.driver_preferences`, copy it
  verbatim into the panel under the same path. Do **not** re-derive rules from
  prose when the structured array is present.
- When introducing a new preference rule, also include `worker_preference` in
  the goal term map (with at least a default weight) so the parent term is
  active in the panel.
""".strip()


# Appended to the domain-neutral study system prompt when test_problem_id is vrptw.

VRPTW_STUDY_PROMPT_APPENDIX = """
## Active benchmark — fleet scheduling (VRPTW)

The session uses a **vehicle routing with time windows** style benchmark. The solver
exposes a fixed set of weight keys — never invent new ones. Reveal a key only when
the user clearly brings up the related concept.

**User language → weight key**

| If the user mentions… | Weight key |
|---|---|
| travel time, duration, makespan, distance, fuel, mileage, operating cost | `travel_time` |
| shift overtime past max hours, fleet overtime (minute-linear) | `shift_limit` |
| deadlines, time windows, late arrivals, punctuality, on-time | `lateness_penalty` |
| overloading, capacity, load limits, packing | `capacity_penalty` |
| fairness, balanced workload, equal shifts, equitable distribution | `workload_balance` |
| driver comfort, worker preferences, zone avoidance, assignment preferences | `worker_preference` + driver_preferences rules |
| express / VIP / SLA / urgent service, priority-tier orders | `express_miss_penalty` |
| arriving too early, idle wait before window | `waiting_time` |
| maximum shift duration limit, max hours per driver | `max_shift_hours` |
| "must assign X to Y", fixed assignments | `locked_assignments` |
| algorithm choice (GA / PSO / SA / ACOR), greedy init, run budget | `algorithm`, `use_greedy_init`, `epochs`, `pop_size` |

**Disambiguation — generic "priority" vs express SLA:** bare "priority" /
"top priority" / "prioritize on-time" → `lateness_penalty`, not
`express_miss_penalty`. Use `express_miss_penalty` only when the user clearly
means express-tier / VIP / SLA / priority-order service class misses.

**Truly fixed (encoded, no knob — acknowledge as already enforced, don't make a weight key):**
- Every task is served exactly once (enforced by the routing encoding).
- Locked / forced assignments (`locked_assignments`).

**Tunable even when called "hard":** capacity (`capacity_penalty`) and shift
overtime (`shift_limit`/`max_shift_hours`) are weight keys — "hard" just sets
the `type`, so commit the key, don't drop it to a fact row.

**Out-of-scope requests** (e.g. CO₂ emissions, weather risk, seniority
weighting): never invent a weight key. Apply the global ambiguity discipline
and emit a `problem_brief_patch.unmodeled_requests` entry naming the
closest alias and a one-sentence rationale.

**Simulated upload behavior:**
- Direct the user to the **Upload file(s)...** chat-footer button
  (exact UI string with the ellipsis) for order data + driver info.
- After upload, reference the **city traffic API** at least once to ground
  travel-time reasoning.
- Don't mention logistics, uploads, or the traffic API before the user
  introduces the domain.
""".strip() + "\n\n" + DRIVER_PREFERENCES_BRIEF_CONTRACT


VRPTW_CONFIG_DERIVE_SYSTEM_PROMPT = """
You translate the current problem brief into a VRPTW panel JSON. The
response_json_schema enforces structure (root `"problem"`, allowed weight
keys, algorithm enum, etc.) — don't restate it. Focus on the judgment
calls the schema cannot enforce.

**Brief is authoritative.**
- Translate, do not propose. If `brief.goal_terms` is empty, emit
  `weights: {}` / `goal_terms: {}` — never invent keys from items[] prose
  alone. The server drops unauthorised keys anyway.
- For managed panel fields (weights, algorithm, algorithm_params, epochs,
  pop_size, max_shift_hours, driver_preferences, locked_assignments,
  only_active_terms, early_stop*, use_greedy_init), re-derive from the
  brief this turn. Don't preserve stale values.
- Omit a key the user **rejected** or expressed **no preference** about
  ("no workload-balance preference", "don't care about waiting"). When in
  doubt, omit.

**Anchoring (load-bearing).** Every emitted weight key needs at least one
items[] row backing it (`gathered`, or `assumption` in agile/demo). Cite
the supporting ids via `goal_terms[<key>].evidence_item_ids`; the server
drops new keys without a valid cite. `worker_preference` and `shift_limit`
self-anchor when their `properties` carrier is populated — explicit cites
optional there.

**Term-type defaults.** Keep one primary objective implicit (omit it from
`constraint_types`); soft for tunable trade-offs; hard only when the user
framed it as strict; custom only on explicit user request.

**Weights follow type.** Pick each term's type — the server seeds a new term's
weight from it (objective < soft < hard), so don't quote a starting weight
number for a new term; name its role ("a hard capacity limit"). After a run you
may retune an existing term to any value.

**Disambiguation deltas (the brief table covers most cases):**
- Bare "priority" / "on-time" → `lateness_penalty`, not
  `express_miss_penalty`. Reserve the latter for express/VIP/SLA tier.
- Co-existing `lateness_penalty` and `express_miss_penalty` are distinct
  terms — keep both when anchored. Do NOT impose a fixed ratio between them:
  if the user gave no relative emphasis, seed them at comparable weights and
  let the run-feedback loop (and the participant) set the balance. Never
  re-clamp a ratio the participant or a run already moved away from.
- Early-arrival / idle-wait → `waiting_time` only on explicit
  early-arrival evidence ("arrive too early", "idle wait"). Never infer
  from generic "slack" / "buffer".
- `max_shift_hours` default 8.0 when a limit is mentioned without a
  duration. (Weight `shift_limit` from its type per the weight-seeding rule
  above — treat it as a strict/hard constraint for a firm cap — not a fixed
  special-case number.)

**Driver-preference rules.** When the brief carries
`goal_terms.worker_preference.properties.driver_preferences`, copy the
list verbatim into `problem.driver_preferences` and include
`worker_preference` in `weights` so the parent term is active. The
structured entry is authoritative — do not re-derive from prose. Rule
shape is in the `DRIVER_PREFERENCES_BRIEF_CONTRACT` section below.

**Algorithm extraction (mandatory).** Any items[] row naming a search
method commits the panel — emit `algorithm` even when embedded in a
sentence about another setting. Canonical mappings:
GA / genetic / evolutionary → `GA`; PSO / particle swarm → `PSO`;
SA / simulated annealing → `SA`; ACOR / ant colony → `ACOR`. If the
same row also names greedy init, emit `use_greedy_init` alongside.
""".strip() + "\n\n" + DRIVER_PREFERENCES_BRIEF_CONTRACT
