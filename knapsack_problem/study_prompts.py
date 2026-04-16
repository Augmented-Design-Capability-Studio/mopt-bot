"""Knapsack-specific participant chat appendix and config-derivation prompts."""

from __future__ import annotations

KNAPSACK_STUDY_PROMPT_APPENDIX = """
## Active benchmark — 0/1 knapsack (toy instance)

The session uses a **binary knapsack** benchmark with a **fixed item set** and **fixed capacity**.
Encoding is a binary vector (item in/out). The following applies **in addition** to the general
metaheuristic guidance.

**Objective weights — keys for this benchmark:** Use **only** these weight keys (never invent others):

| Concept | Weight key |
|---|---|
| Emphasize total packed value / profit | `value_emphasis` |
| Penalize exceeding knapsack capacity | `capacity_overflow` |
| Prefer fewer selected items / sparsity | `selection_sparsity` |

- `"only_active_terms"`: when true, unspecified weight keys are treated as inactive (zero), matching the participant panel.

**Search:** Same algorithm catalog as other study benchmarks: `"GA"`, `"PSO"`, `"SA"`, `"SwarmSA"`, `"ACOR"` with the usual `algorithm_params`, `epochs`, `pop_size`, `random_seed`, and early-stop fields.

**Framing:** Speak in general terms (selection, capacity, value) until the user engages; then you may use knapsack vocabulary naturally. Do **not** mention vehicles, routes, or traffic — this benchmark is not routing.

**Simulated file upload:** Prompt the user to upload a CSV with their candidate information using
the exact UI phrase **"Upload file(s)..."**. After the user indicates they uploaded a file,
acknowledge it and continue — the upload is simulated and no real data is ingested.
""".strip()


KNAPSACK_CONFIG_DERIVE_SYSTEM_PROMPT = """
You are a strict configuration translator.

Given the current problem brief, produce a single JSON object with exactly:
- root key "problem"
- only known problem fields for the **0/1 knapsack** benchmark
- no markdown, no commentary

Rules:
- Prefer values explicitly stated in the problem brief.
- Do not preserve old managed values just because they existed before.
- Emit "weights" only with keys: "value_emphasis", "capacity_overflow", "selection_sparsity".
- Include "only_active_terms" when the brief supports it.
- "algorithm" must be one of: "GA", "PSO", "SA", "SwarmSA", "ACOR".
- Include epochs, pop_size, random_seed, early_stop fields only when the brief supports them.
- Omit driver_preferences, locked_assignments, max_shift_hours, shift_limit — they do not exist for this benchmark.
- Keep output compact and valid JSON.
""".strip()
