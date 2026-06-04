"""Agile post-run OQ/assumption scheduling (controlled-study lever).

In agile mode the agent's choice between raising an open question and committing
an assumption after a run was historically a soft prompt bias (~70/30) — not
measurable, not researcher-controllable, not reproducible. For a controlled
study we make it a deterministic independent variable:

**Blocked randomization.** Runs are grouped into blocks of ``every_n_runs``. In
each block EXACTLY ONE post-run turn is designated the open-question turn, at a
*uniformly random position within that block*; the other ``N-1`` are assumption
turns. So the realized OQ:assumption ratio is exactly ``1:(N-1)`` per block (no
small-N drift), while the OQ is NOT pinned to a fixed run index (which would
confound "OQ" with "the 5th run"). The draw is seeded per ``(session, N, block)``
so it is reproducible and auditable per participant.

The server resolves the directive on each agile run-ack turn and injects a
"raise one OQ" / "add one assumption" instruction into that turn's prompt,
overriding the soft bias.
"""

from __future__ import annotations

import random
from typing import Literal

PostRunDirective = Literal["open_question", "assumption"]

# Sentinel values for ``every_n_runs``:
#   None → feature OFF (fall back to the model's soft ~70/30 bias).
#   0    → "Never" raise an OQ (every post-run turn is an assumption).
#   1    → "Every run" is an OQ.
#   N≥2  → one OQ per block of N, at a random position in the block.


def post_run_oq_directive(
    *,
    session_id: str,
    run_number: int,
    every_n_runs: int | None,
    workflow_mode: str | None,
) -> PostRunDirective | None:
    """Return the forced post-run directive for this turn, or ``None``.

    ``None`` means "no directive" — the turn is not an agile post-run turn, the
    feature is off, or inputs are invalid — and the caller leaves the soft prompt
    bias in place. ``run_number`` is the 1-based index of the just-completed run.
    """
    if (workflow_mode or "").strip().lower() != "agile":
        return None
    if every_n_runs is None:
        return None  # feature off
    if not isinstance(run_number, int) or run_number < 1:
        return None
    n = int(every_n_runs)
    if n <= 0:
        return "assumption"  # "Never" → always an assumption
    if n == 1:
        return "open_question"  # "Every run" → always an OQ
    idx = run_number - 1
    block_index = idx // n
    position_in_block = idx % n
    # Reproducible per (session, cadence, block): the OQ lands at one random
    # position in the block, the same way every time this is recomputed.
    rng = random.Random(f"{session_id}:{n}:{block_index}")
    oq_position = rng.randrange(n)
    return "open_question" if position_in_block == oq_position else "assumption"
