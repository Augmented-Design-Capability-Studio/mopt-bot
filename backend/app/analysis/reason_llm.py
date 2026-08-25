"""Improvement-REASON attribution for the session-coding tool.

A separate labeling layer from the change tags: for each RUN (canonical-cost
change vs the previous run) and each formulation-score jump, WHY did the outcome
move. Deterministic candidates come from the verified structural evidence (what
changed between the runs); an OPTIONAL, fully separate LLM pass double-checks
them against the conversation and returns its own reason list + rationale.

Strict separation from the change-tag machinery (researcher requirement):
different annotation type (``reason``), different cache table
(``CodingLlmReasons``), different endpoint/button — running or purging reasons
never touches ``code`` tags or the ``CodingLlmTags`` cache, and vice versa.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# The reason vocabulary (multi-select). Keep in sync with ReasonCell.tsx.
REASONS = [
    "new-goal-term",     # a goal term became active
    "term-removed",      # a goal term was taken out
    "weight-rebalance",  # weights changed on existing terms
    "term-type-change",  # hard/soft/objective/custom changed
    "detail-refinement", # a term's structured specifics changed
    "ranking-change",    # priorities reordered
    "algorithm-switch",  # search strategy changed
    "search-budget",     # epochs / population changed
    "knob-tuning",       # algorithm-specific hyperparameters changed
    "feasibility-fix",   # went from infeasible to feasible
    "stochastic-rerun",  # nothing changed — different draw of the same config
    "other",
]

_BUDGET_FIELDS = {"epochs", "pop_size"}
_MAX_RATIONALE = 240


def reasons_from_diffs(diffs: list[dict[str, Any]]) -> list[str]:
    """Deterministic reason candidates from the structured config diffs of the
    exchanges in the attribution window (between the previous run and this one).
    Empty window → ``stochastic-rerun``."""
    out: list[str] = []

    def add(r: str) -> None:
        if r not in out:
            out.append(r)

    saw_any = False
    for d in diffs:
        if not d:
            continue
        saw_any = True
        if d.get("added"):
            add("new-goal-term")
        for t in d.get("terms") or []:
            for c in t.get("changes") or []:
                f = c.get("field")
                if f == "weight":
                    add("weight-rebalance")
                elif f == "type":
                    # soft↔custom is the panel's UNLOCK mechanic (switching to
                    # "custom" is how a user hand-edits the weight) — not a
                    # semantic type change, so it never drives an outcome on its
                    # own. Transitions involving hard/objective DO count.
                    if {c.get("from"), c.get("to")} != {"soft", "custom"}:
                        add("term-type-change")
                elif f == "rank":
                    add("ranking-change")
                elif f == "properties":
                    add("detail-refinement")
        if d.get("removed"):
            add("term-removed")
        if d.get("algorithm"):
            add("algorithm-switch")
        for p in d.get("params") or []:
            add("search-budget" if p.get("field") in _BUDGET_FIELDS else "knob-tuning")
    if not saw_any:
        out.append("stochastic-rerun")
    return out


def _fmt_delta(v: float) -> str:
    return f"{v:+,.0f}"


def render_run_evidence(row: dict[str, Any]) -> str:
    """Compact evidence text for one run row (used in the LLM prompt)."""
    parts = []
    od = row.get("outcome_delta") or {}
    if od.get("cost_delta") is not None:
        parts.append(f"cost {_fmt_delta(od['cost_delta'])} vs previous run")
    if od.get("feasible_from") is not None and od.get("feasible_from") != od.get("feasible_to"):
        parts.append(f"feasibility {od['feasible_from']} -> {od['feasible_to']}")
    movers = od.get("movers") or []
    if movers:
        parts.append("component movers: " + ", ".join(f"{m['term']} {_fmt_delta(m['delta'])}" for m in movers))
    sugg = row.get("reason_suggestions") or []
    det = [s["reason"] for s in sugg if s.get("source") == "auto"]
    if det:
        parts.append("mechanical candidates: " + ", ".join(det))
    return "; ".join(parts) if parts else "(no evidence)"


def verify_reasons(
    targets: list[dict[str, Any]],
    api_key: str,
    model: str,
) -> dict[str, list[dict[str, Any]]] | None:
    """LLM double-check of the mechanical reason candidates.

    ``targets``: [{ref, evidence, context}] — evidence = render_run_evidence
    output + window diff lines; context = truncated conversation of the window.
    Returns {ref: [{reason, rationale, source: "llm"}]} or None on failure (the
    caller keeps any existing cache)."""
    if not api_key or not model or not targets:
        return None

    blocks = []
    for i, t in enumerate(targets):
        blocks.append(f"[{i}]\nEVIDENCE: {t['evidence']}\nCONVERSATION SINCE PREVIOUS RUN:\n{t['context']}")
    prompt = (
        "For each numbered run, judge WHY the outcome changed. Choose reasons "
        "ONLY from the vocabulary; correct the mechanical candidates when the "
        "conversation contradicts them (e.g. a change was requested but not the "
        "driver of the improvement). Return one entry per run.\n\n" + "\n\n".join(blocks)
    )
    system = (
        "You audit causal attributions for optimization runs in a research "
        "transcript. The EVIDENCE lines are verified facts (cost delta vs the "
        "previous run, which cost components moved, what changed in the config "
        "between the runs). Reason vocabulary:\n"
        + "\n".join(f"- `{r}`" for r in REASONS)
        + "\n\nRules:\n"
        "- Prefer the reason whose changed fields match the components that "
        "actually moved (a workload-weight change that coincides with the "
        "workload component dropping IS the driver; a change to a term whose "
        "component did not move is probably not).\n"
        "- `stochastic-rerun` when nothing changed between runs.\n"
        "- `feasibility-fix` is an OUTCOME QUALIFIER, not a cause: use it when "
        "the run turned feasible and that is what matters (even if cost rose), "
        "but NEVER alone — always pair it with the causal change that produced "
        "feasibility (e.g. `term-type-change` + `feasibility-fix`).\n"
        "- A type change between `soft` and `custom` is the panel's weight-unlock "
        "mechanic, NOT a semantic type change — attribute such episodes to "
        "`weight-rebalance`, not `term-type-change`.\n"
        "- Multiple reasons are allowed when several changes plausibly "
        "contributed. Keep rationales to one short sentence.\n"
        "- Output structured JSON only."
    )
    schema = {
        "type": "object",
        "properties": {
            "runs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "reasons": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "reason": {"type": "string", "enum": REASONS},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["reason", "rationale"],
                            },
                        },
                    },
                    "required": ["index", "reasons"],
                },
            }
        },
        "required": ["runs"],
    }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=0.0,
            ),
        )
        parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
    except Exception as exc:
        log.warning("LLM reason verification failed (%s)", exc)
        return None

    out: dict[str, list[dict[str, Any]]] = {}
    for entry in (parsed or {}).get("runs", []) or []:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        reasons = entry.get("reasons")
        if not isinstance(idx, int) or not (0 <= idx < len(targets)) or not isinstance(reasons, list):
            continue
        cleaned = []
        seen: set[str] = set()
        for r in reasons:
            if not isinstance(r, dict) or r.get("reason") not in REASONS or r["reason"] in seen:
                continue
            seen.add(r["reason"])
            cleaned.append({"reason": r["reason"],
                            "rationale": str(r.get("rationale") or "")[:_MAX_RATIONALE],
                            "source": "llm"})
        # Backstop for the pairing rule: `feasibility-fix` is an outcome
        # qualifier and must ride WITH a causal reason. A standalone verdict is
        # rejected (no entry stored), so that run falls back to the mechanical
        # candidates — which always pair it with the causes they found.
        if [c["reason"] for c in cleaned] == ["feasibility-fix"]:
            continue
        if cleaned:
            out[targets[idx]["ref"]] = cleaned
    return out
