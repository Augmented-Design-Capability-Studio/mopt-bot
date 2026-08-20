"""Deterministic state derivation for the session-coding tool.

Anchors every exchange to its verified result state (chat-turn
``pre_turn_state``, never snapshots), and derives from it:

- the **structured config diff** (``structured_config_diff``) — per-goal-term
  field changes + solver-knob changes, rendered as chips in the UI and fed as
  evidence into the LLM tagging pass (``coding_llm``);
- the **brief-side definition delta** (``brief_for_display``) — the brief minus
  its ``goal_terms`` config mirror and ``runs`` history, so a def Δ never
  duplicates the config Δ;
- deterministic **search-strategy / search-param** tag suggestions — hard
  structural facts (the algorithm field changed; a solver knob changed), the one
  judgment-free slice of the coding scheme.

Goal-term tag suggestions (origin / first-applied / mentioned / dropped …)
are judgment calls and come from the LLM pass in ``coding_llm`` — NOT from this
module. Problem-specific knowledge (which terms count as captured) is sourced
from the ``StudyProblemPort`` so the main backend stays problem-agnostic.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Panel goal-term carriers that aren't requirement goal terms.
_CARRIER_KEYS = {"search_strategy", "algorithm"}
# Panel-level solver knobs that count as a "search parameter" change. NOTE:
# ``random_seed`` is deliberately excluded — it's an internal per-run seed, not a
# tuning decision a researcher codes, and it churns on its own.
_PARAM_FIELDS = (
    "algorithm_params",
    "epochs",
    "pop_size",
    "early_stop",
    "early_stop_patience",
    "early_stop_epsilon",
    "use_greedy_init",
)


def _load(panel_json: str | None) -> dict[str, Any]:
    try:
        p = json.loads(panel_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return p if isinstance(p, dict) else {}


def _problem(panel: dict) -> dict:
    prob = panel.get("problem")
    return prob if isinstance(prob, dict) else panel


def _goal_terms(prob: dict) -> dict:
    gt = prob.get("goal_terms")
    return gt if isinstance(gt, dict) else {}


def _rank_order(terms: dict, keys) -> list:
    """Keys ordered by their ``rank`` (missing rank sinks to the bottom); used to
    detect a genuine re-rank of the *common* terms, excluding the renumber
    cascade caused by add/remove."""
    return sorted(
        keys,
        key=lambda k: (
            terms[k].get("rank")
            if isinstance(terms.get(k), dict) and terms[k].get("rank") is not None
            else 10**9,
            k,
        ),
    )


def _captured_terms(port: Any, panel: dict) -> set[str]:
    """Present-and-active goal-term keys per the problem port (optional hook)."""
    fn = getattr(port, "formulation_quality_for_config", None)
    if fn is None or not panel:
        return set()
    try:
        res = fn(panel) or {}
    except Exception:
        return set()
    return set(res.get("captured_terms") or [])


def _norm_nums(obj: Any) -> Any:
    """Coerce every number to float so ``50`` and ``50.0`` compare equal — the
    stored config re-serializes numbers inconsistently between turns, which would
    otherwise register as phantom changes."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _norm_nums(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm_nums(v) for v in obj]
    return obj


def _canon(obj: Any) -> str:
    """Order-insensitive, number-normalized JSON string for change comparison."""
    try:
        return json.dumps(_norm_nums(obj), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""


def _term_origins_from_brief(brief: dict) -> dict[str, str]:
    """``goal_term key -> "user"|"agent"`` from the brief's OWN recorded
    provenance: a term whose evidence traces to a ``gathered`` brief item (or an
    item tagged with its goal_key) was brought up by the user; an
    ``assumption``-only term was introduced by the agent.

    This reads the study's per-turn provenance directly (the response that adds a
    user-requested term records a ``gathered`` item with that goal_key, and the
    term's ``evidence_item_ids`` point at it), which is far more reliable than the
    aggregated ``goal_term_origins`` for "did the user bring this up?"."""
    if not isinstance(brief, dict):
        return {}
    items = brief.get("items") or []
    kind_by_id = {it.get("id"): it.get("kind") for it in items if isinstance(it, dict) and it.get("id")}
    by_goal_key: dict[str, set] = {}
    for it in items:
        if isinstance(it, dict) and it.get("goal_key"):
            by_goal_key.setdefault(it["goal_key"], set()).add(it.get("kind"))
    out: dict[str, str] = {}
    for k, v in (brief.get("goal_terms") or {}).items():
        kinds = set(by_goal_key.get(k, set()))
        if isinstance(v, dict):
            for eid in v.get("evidence_item_ids") or []:
                kinds.add(kind_by_id.get(eid))
        if "gathered" in kinds:
            out[k] = "user"
        elif "assumption" in kinds:
            out[k] = "agent"
    return out


def structured_config_diff(prev_prob: dict, prob: dict) -> dict[str, Any] | None:
    """Structural diff of two panel ``problem`` objects → a compact, typed shape
    the UI renders as chips and the LLM pass consumes as evidence::

        {"algorithm": {"from": "PSO", "to": "GA"},          # only when changed
         "params":  [{"field": "epochs", "from": 100, "to": 200}, ...],
         "terms":   [{"term": "lateness_penalty",
                      "changes": [{"field": "weight", "from": 80, "to": 160},
                                  {"field": "type", "from": "soft", "to": "hard"},
                                  {"field": "rank", "from": 2, "to": 1},
                                  {"field": "properties"}]}],   # objects → no from/to
         "added":   [{"term": "capacity_penalty", "weight": 3, "type": "hard", "rank": 3}],
         "removed": ["waiting_time"]}

    Number- and order-insensitive via ``_canon`` (50 == 50.0; a re-serialized
    param dict in a different key order is NOT a change). Rank changes keep the
    established semantics: only when the relative order of the *common* terms
    changed (excludes the renumber cascade from add/remove). Param changes are
    suppressed when the algorithm ALSO changed (the knobs then just carry the new
    algorithm's defaults, already conveyed by the algorithm entry). ``None`` when
    nothing changed."""
    prev_gt = _goal_terms(prev_prob)
    gt = _goal_terms(prob)
    common = set(prev_gt) & set(gt)
    diff: dict[str, Any] = {}

    terms: list[dict[str, Any]] = []
    for k in sorted(common):
        if k in _CARRIER_KEYS:
            continue
        a, b = prev_gt.get(k), gt.get(k)
        if not (isinstance(a, dict) and isinstance(b, dict)):
            continue
        changes: list[dict[str, Any]] = []
        if _canon(a.get("weight")) != _canon(b.get("weight")):
            changes.append({"field": "weight", "from": a.get("weight"), "to": b.get("weight")})
        if a.get("type") != b.get("type"):
            changes.append({"field": "type", "from": a.get("type"), "to": b.get("type")})
        # Properties = the term's structured specifics (VRPTW: driver_preferences,
        # max_shift_hours) — objects, so the chip just says "detail changed".
        if _canon(a.get("properties")) != _canon(b.get("properties")):
            changes.append({"field": "properties"})
        if changes:
            terms.append({"term": k, "changes": changes})
    if _rank_order(prev_gt, common) != _rank_order(gt, common):
        for k in sorted(common):
            if k in _CARRIER_KEYS:
                continue
            a, b = prev_gt.get(k), gt.get(k)
            if not (isinstance(a, dict) and isinstance(b, dict)) or a.get("rank") == b.get("rank"):
                continue
            entry = next((t for t in terms if t["term"] == k), None)
            change = {"field": "rank", "from": a.get("rank"), "to": b.get("rank")}
            if entry is None:
                terms.append({"term": k, "changes": [change]})
            else:
                entry["changes"].append(change)
    if terms:
        diff["terms"] = terms

    added = []
    for k in sorted(set(gt) - set(prev_gt)):
        if k in _CARRIER_KEYS:
            continue
        v = gt.get(k) if isinstance(gt.get(k), dict) else {}
        added.append({"term": k, "weight": v.get("weight"), "type": v.get("type"), "rank": v.get("rank")})
    if added:
        diff["added"] = added
    removed = sorted(k for k in set(prev_gt) - set(gt) if k not in _CARRIER_KEYS)
    if removed:
        diff["removed"] = removed

    if prev_prob.get("algorithm") != prob.get("algorithm"):
        diff["algorithm"] = {"from": prev_prob.get("algorithm"), "to": prob.get("algorithm")}
    else:
        params = [
            {"field": f, "from": prev_prob.get(f), "to": prob.get(f)}
            for f in _PARAM_FIELDS
            if _canon(prev_prob.get(f)) != _canon(prob.get(f))
        ]
        if params:
            diff["params"] = params

    return diff or None


# Brief keys stripped from the def Δ: ``goal_terms`` mirrors the panel config
# (that change belongs in the cfg Δ) and ``runs`` is run-history churn.
_BRIEF_MIRROR_KEYS = ("goal_terms", "runs")


def brief_for_display(brief: dict) -> dict:
    """The brief minus its config mirror and run history — the BRIEF-side content
    (items, open questions, goal summary, unmodeled requests …). Used for both
    the def-Δ change gate and the def-Δ display, so a def Δ never fires on (or
    shows) what is really a config change or run churn."""
    if not isinstance(brief, dict):
        return {}
    return {k: _deep(v) for k, v in brief.items() if k not in _BRIEF_MIRROR_KEYS}


def _search_changes(prev_prob: dict, prob: dict, origin_by_term: dict[str, str],
                    suppress_fallback: bool) -> list[dict[str, Any]]:
    """Deterministic search-strategy / search-param tag suggestions — the one
    judgment-free slice of the coding scheme (the algorithm field / a solver knob
    changed, hard structural facts). Origin defaults to the agent; strategy
    upgrades to the user when the ``search_strategy`` carrier's provenance is
    ``gathered`` (the participant drove the choice) — and the caller further
    forces ``user`` on manual-edit ack turns. Params carry no reliable user
    signal, so they stay agent."""
    changes: list[dict[str, Any]] = []
    search_user = not suppress_fallback and origin_by_term.get("search_strategy") == "user"
    algorithm_changed = prev_prob.get("algorithm") != prob.get("algorithm")
    if algorithm_changed:
        changes.append({"origin": "user" if search_user else "agent",
                        "type": "search-strategy", "term": None, "effect": "applied", "captured": None})
    # Compared order-/number-insensitively via `_canon`; suppressed when the
    # algorithm also changed (the knobs then just carry the new solver's defaults).
    if not algorithm_changed and any(
        _canon(prev_prob.get(f)) != _canon(prob.get(f)) for f in _PARAM_FIELDS
    ):
        changes.append({"origin": "agent",
                        "type": "search-param", "term": None, "effect": "applied", "captured": None})
    return changes


def _recognized_terms(brief: dict) -> set[str]:
    """Goal terms the agent has REGISTERED this turn — anything carrying a
    goal_key in the brief's items or open_questions, plus whatever's in
    goal_terms. Broader than the config: a term can be recognised (discussed,
    noted) here without being an active config goal term yet."""
    out: set[str] = set()
    for it in brief.get("items") or []:
        if isinstance(it, dict) and it.get("goal_key"):
            out.add(it["goal_key"])
    for oq in brief.get("open_questions") or []:
        if isinstance(oq, dict) and oq.get("goal_key"):
            out.add(oq["goal_key"])
    out.update(_goal_terms(brief).keys())
    return {k for k in out if k and k not in _CARRIER_KEYS}


def _post_run_refs(messages: list[Any]) -> set[str]:
    """``message:{source_id}`` of every assistant chat turn that FOLLOWS a run —
    i.e. a run event occurred since the previous chat turn. Those turns are where
    the agent reacts to results and (in agile) proactively re-tunes."""
    out: set[str] = set()
    run_since = False
    for m in sorted(messages, key=lambda x: ((getattr(x, "ts_epoch", 0) or 0), x.id)):
        role = getattr(m, "role", None)
        kind = getattr(m, "kind", "") or ""
        if kind == "run":
            run_since = True
        elif role == "assistant" and kind == "chat":
            if run_since:
                out.add(f"message:{m.source_id}")
            run_since = False
    return out


def _oq_answer_refs(messages: list[Any]) -> set[str]:
    """``message:{source_id}`` of assistant chat turns preceded by an
    ``Answered … open questions`` user message — the terms configured there were
    AGENT-asked (the user only answered), so their origin is agent even though
    the answer is logged with ``gathered`` provenance."""
    out: set[str] = set()
    answered_since = False
    for m in sorted(messages, key=lambda x: ((getattr(x, "ts_epoch", 0) or 0), x.id)):
        role = getattr(m, "role", None)
        kind = getattr(m, "kind", "") or ""
        if role == "user" and kind == "chat" and (getattr(m, "content", "") or "").startswith("Answered "):
            answered_since = True
        elif role == "assistant" and kind == "chat":
            if answered_since:
                out.add(f"message:{m.source_id}")
            answered_since = False
    return out


def _deep(x: Any) -> Any:
    try:
        return json.loads(json.dumps(x))
    except (TypeError, ValueError):
        return x


# A participant panel save emits a structured audit message ("Config edited: …" /
# "Definition edited: …"). We parse it deterministically — NOT natural language —
# to learn WHICH goal terms the participant touched, so a pre-edit row can undo
# exactly those and keep the agent's own result (incl. pipeline-added companion
# details) for everything else.
_GOAL_TERM_EDIT = re.compile(r"-\s*(?:added |removed )?goal term (\w+)", re.IGNORECASE)


def _parse_config_edit(content: str) -> tuple[set[str], bool, set[str]]:
    """From a ``Config/Definition edited`` message → (edited goal-term keys,
    ranks_reordered, edited panel search fields). ``Priority order:`` reorders
    every term's rank; ``Driver preferences:`` edits ``worker_preference``;
    ``Shift limit:`` edits ``shift_limit``. ``Algorithm:`` edits the strategy (the
    ``search_strategy`` carrier + the panel ``algorithm``/``algorithm_params``,
    which silently flip to the new solver's defaults); ``Max iterations:`` /
    ``Population size:`` edit ``epochs`` / ``pop_size``."""
    edited: set[str] = set()
    search: set[str] = set()
    ranks = False
    for ln in content.splitlines():
        ln = ln.strip()
        if not ln.startswith("-"):
            continue
        m = _GOAL_TERM_EDIT.match(ln)
        if m:
            edited.add(m.group(1))
            continue
        low = ln.lower()
        if low.startswith("- priority order"):
            ranks = True
        elif low.startswith("- driver preferences"):
            edited.add("worker_preference")
        elif low.startswith("- shift limit"):
            edited.add("shift_limit")
        elif low.startswith("- algorithm"):
            edited.add("search_strategy")  # restore the brief/panel carrier
            search |= {"algorithm", "algorithm_params"}  # + the panel top-level fields
        elif low.startswith("- max iterations"):
            search.add("epochs")
        elif low.startswith("- population size"):
            search.add("pop_size")
    return edited, ranks, search


def _user_edit_info(messages: list[Any]) -> dict[str, tuple[set[str], bool, set[str]]]:
    """``message:{source_id}`` (assistant turn) → (edited term keys, ranks_reordered,
    edited search fields) from the participant panel-edit message(s) that precede
    it. The edit was applied BEFORE this turn ran, so this turn's pre-state already
    carries it — so the PRIOR exchange must not inherit those edited fields by
    looking ahead into this (already-edited) pre-state (P02 lateness 80→160 @13:33;
    P01 25:25 re-rank; P30 algorithm PSO→GA @12:36)."""
    out: dict[str, tuple[set[str], bool, set[str]]] = {}
    terms: set[str] = set()
    search: set[str] = set()
    ranks = False
    for m in sorted(messages, key=lambda x: ((getattr(x, "ts_epoch", 0) or 0), x.id)):
        role = getattr(m, "role", None)
        kind = getattr(m, "kind", "") or ""
        content = getattr(m, "content", "") or ""
        if role == "user" and kind == "chat" and (
            content.startswith("Config edited") or content.startswith("Definition edited")
        ):
            t, r, s = _parse_config_edit(content)
            terms |= t
            search |= s
            ranks = ranks or r
        elif role == "assistant" and kind == "chat":
            if terms or ranks or search:
                out[f"message:{m.source_id}"] = (set(terms), ranks, set(search))
            terms, search, ranks = set(), set(), False
    return out


def _patch_goal_terms_by_ref(messages: list[Any]) -> dict[str, dict]:
    """``message:{source_id}`` → the reply's OWN brief-patch goal_terms
    (``meta.v2_turn_snapshot.problem_brief_patch.goal_terms``) — the agent's stated
    action that turn. Used to restore a participant-edited term to the agent's own
    value (the verified next-state carries the edit on that field, so it can't be
    used there)."""
    out: dict[str, dict] = {}
    for m in messages:
        if getattr(m, "role", None) != "assistant" or (getattr(m, "kind", "") or "") != "chat":
            continue
        meta = _load(getattr(m, "meta_json", None))
        v2 = meta.get("v2_turn_snapshot") if isinstance(meta, dict) else None
        patch = v2.get("problem_brief_patch") if isinstance(v2, dict) else None
        gt = patch.get("goal_terms") if isinstance(patch, dict) else None
        if isinstance(gt, dict) and gt:
            out[f"message:{m.source_id}"] = gt
    return out


def _restore_edited(gt: dict, pre_gt: dict, patch_gt: dict,
                    edited_terms: set[str], ranks_reordered: bool) -> None:
    """In-place: for each term the participant edited, replace it with the AGENT's
    own value — the reply's patch if the reply set it, else this reply's pre-state
    (or drop it if the agent never had it). ``ranks_reordered`` restores every
    term's rank the same way. Terms the participant did NOT touch are left as the
    verified next-state had them — so pipeline-added companion details (e.g.
    ``worker_preference.driver_preferences`` the pipeline fills in) stay on the
    turn that produced them."""
    pre_gt = pre_gt if isinstance(pre_gt, dict) else {}
    patch_gt = patch_gt if isinstance(patch_gt, dict) else {}

    def agent_value(term: str) -> dict | None:
        if isinstance(patch_gt.get(term), dict):
            return _deep(patch_gt[term])
        if isinstance(pre_gt.get(term), dict):
            return _deep(pre_gt[term])
        return None

    for term in edited_terms:
        av = agent_value(term)
        if av is None:
            gt.pop(term, None)  # agent never had it → the participant added it
        else:
            gt[term] = av
    if ranks_reordered:
        for term, cur in gt.items():
            if not isinstance(cur, dict):
                continue
            src = patch_gt.get(term) if isinstance(patch_gt.get(term), dict) else pre_gt.get(term)
            if isinstance(src, dict) and src.get("rank") is not None:
                cur["rank"] = src["rank"]


def _restore_search_fields(prob: dict, pre_prob: dict, edited_search: set[str]) -> None:
    """In-place: restore each participant-edited PANEL search field (``algorithm``,
    ``algorithm_params``, ``epochs``, ``pop_size``) to this reply's own pre-state
    value (the agent's config for that row — a run-ack doesn't touch the solver),
    so a later ``Algorithm:`` edit can't surface early (P30 9:06 stays PSO)."""
    pre_prob = pre_prob if isinstance(pre_prob, dict) else {}
    for f in edited_search:
        if f in pre_prob:
            prob[f] = _deep(pre_prob[f])
        else:
            prob.pop(f, None)


def _reconstruct_after_edit(pre_brief: dict, pre_panel: dict, next_brief: dict, next_panel: dict,
                            patch_gt: dict, edited_terms: set[str], ranks_reordered: bool,
                            edited_search: set[str]) -> tuple[dict, dict]:
    """Rebuild an exchange's (brief, panel) when a participant edit lands between
    this reply and the next. Base = the VERIFIED next-state (the real post-pipeline
    config, incl. companion details the raw patch lacks), then undo ONLY what the
    participant edited: goal terms (restored to the agent's own value) and panel
    search fields. So the reply's own result is shown in full while the
    participant's later edit is left off (P04: worker_preference details stay on
    3:57; P30: 9:06 keeps PSO, not the 12:36 GA edit)."""
    recon_brief = _deep(next_brief) if isinstance(next_brief, dict) else {}
    if isinstance(recon_brief, dict):
        bgt = recon_brief.get("goal_terms")
        if not isinstance(bgt, dict):
            bgt = {}
            recon_brief["goal_terms"] = bgt
        _restore_edited(bgt, pre_brief.get("goal_terms") if isinstance(pre_brief, dict) else {},
                        patch_gt, edited_terms, ranks_reordered)
    recon_panel = _deep(next_panel) if isinstance(next_panel, dict) else {}
    pprob = _problem(recon_panel)
    pgt = pprob.get("goal_terms")
    if not isinstance(pgt, dict):
        pgt = {}
        pprob["goal_terms"] = pgt
    _restore_edited(pgt, _goal_terms(_problem(pre_panel)), patch_gt, edited_terms, ranks_reordered)
    _restore_search_fields(pprob, _problem(pre_panel), edited_search)
    return recon_brief, recon_panel


def _assistant_states(messages: list[Any]) -> list[tuple[str, dict, dict]]:
    """Ordered ``[(row_ref, brief, panel)]`` for the assistant chat turns that
    carry ``meta.pre_turn_state`` (the state the model saw that turn)."""
    out: list[tuple[str, dict, dict]] = []
    for m in sorted(messages, key=lambda x: ((x.ts_epoch or 0.0), x.id)):
        meta = _load(getattr(m, "meta_json", None))
        pre = meta.get("pre_turn_state") if isinstance(meta, dict) else None
        if not isinstance(pre, dict):
            continue
        panel = pre.get("panel_config")
        if not isinstance(panel, dict):
            continue
        brief = pre.get("problem_brief")
        out.append((f"message:{m.source_id}", brief if isinstance(brief, dict) else {}, panel))
    return out


def build_turn_derivations(messages: list[Any], port: Any) -> dict[str, dict[str, Any]]:
    """Per assistant-turn state derivations, keyed by ``message:{source_id}``.

    **State-appearance attribution.** Each row must show the real-time state at
    that exchange. ``pre_turn_state`` is the state BEFORE a reply, so a reply's
    result lives in the NEXT turn's pre-state — we therefore use the next turn's
    state as this exchange's RESULT state (``R``) and display it, so the config
    reflects the agent's response, not the user-send state (P01 workload @16:11).

    But a structured user edit (OQ answer, config/definition panel edit) happens
    BETWEEN chats and lands in the next turn's pre-state too — that state belongs
    to the NEXT exchange, not this one; ``result_state`` handles both cases.

    Per exchange this emits: the deterministic search-tag suggestions, captured
    terms, the structured config diff (chips + LLM evidence), the stripped
    brief-side def Δ, the full result-state display JSONs, and the open
    goal-term OQs (LLM evidence). Every exchange with a state is emitted (even
    change-free ones) so the display always shows the result state."""
    states = _assistant_states(messages)
    post_run_refs = _post_run_refs(messages)
    oq_answer_refs = _oq_answer_refs(messages)
    user_edit_info = _user_edit_info(messages)
    patch_by_ref = _patch_goal_terms_by_ref(messages)

    def result_state(i: int) -> tuple[dict, dict]:
        """The def/config shown for an exchange, taken ONLY from chat-turn
        ``pre_turn_state`` (never a snapshot).

        Default = the NEXT turn's pre-state: a reply's changes settle through the
        pipeline a beat after it replies, so its result is the state the next turn
        starts from (the small post-reply delay). This is the faithful record of a
        reply's synced result (the brief patch can't stand in for it — the sync
        re-ranks / coerces types / clamps weights).

        EXCEPT when a USER action lands between this reply and the next turn:

        - the next turn ANSWERS an open question (``oq_answer_refs``) — keep own
          pre-state so the open question stays visible (P02 7:25);
        - the next turn was preceded by a participant panel edit
          (``user_edit_info``) — the next pre-state carries that edit, which
          belongs to the exchange the edit folds into, NOT this reply. So we
          keep the VERIFIED next-state (which has the real post-pipeline config,
          including companion details the raw patch lacks) and undo ONLY the terms
          the edit named, restoring them to the agent's own value: P04 keeps
          ``worker_preference``'s pipeline-added driver-preference details on 3:57
          while the 5:45 express/lateness edits don't leak back; P01 24:21 keeps
          the agent's punctuality weight→20 but not the 25:25 re-rank; P02 13:06
          stays 80 (that reply changed nothing there)."""
        if i + 1 >= len(states):
            return states[i][1], states[i][2]
        next_ref = states[i + 1][0]
        if next_ref in oq_answer_refs:
            return states[i][1], states[i][2]
        if next_ref in user_edit_info:
            edited_terms, ranks_reordered, edited_search = user_edit_info[next_ref]
            return _reconstruct_after_edit(
                states[i][1], states[i][2], states[i + 1][1], states[i + 1][2],
                patch_by_ref.get(states[i][0], {}), edited_terms, ranks_reordered, edited_search)
        return states[i + 1][1], states[i + 1][2]

    out: dict[str, dict[str, Any]] = {}
    # The "before" state for the first STATE-CARRYING exchange is normally its
    # own pre-state (so its diff shows what that reply changed, not everything
    # vs empty). BUT the session's opening assistant turn(s) carry NO
    # ``pre_turn_state`` (the setup reply pre-dates state recording), and their
    # changes are already baked into the first recorded pre-state — diffing
    # against it SWALLOWS them (P07: the 0:00 setup reply added capacity +
    # lateness; the 0:32 exchange showed no cfg Δ; 9/28 sessions affected). So
    # when state-less assistant chat turns precede the first recorded state,
    # the baseline is EMPTY and the first exchange surfaces everything the
    # conversation has built up to that point.
    prev_brief: dict = states[0][1] if states else {}
    prev_panel: dict = states[0][2] if states else {}
    if states:
        first_state_id = int(states[0][0].split(":", 1)[1])
        stateless_lead = any(
            getattr(m, "role", None) == "assistant" and (getattr(m, "kind", "") or "") == "chat"
            and (m.source_id or 0) < first_state_id
            for m in messages
        )
        if stateless_lead:
            prev_brief, prev_panel = {}, {}
    for i in range(len(states)):
        ref = states[i][0]
        # Drop the provenance→user fallback on post-run re-tunes and OQ-answer
        # turns (both are agent-driven despite the brief's provenance).
        suppress = ref in post_run_refs or ref in oq_answer_refs
        brief_r, panel_r = result_state(i)
        captured = _captured_terms(port, panel_r)
        origins = _term_origins_from_brief(brief_r)
        changes = _search_changes(_problem(prev_panel), _problem(panel_r), origins, suppress)
        # A search change landing on THIS turn because the participant edited the
        # panel (the reconstruction pushed the edit onto its own ack turn) is
        # user-origin: the participant made it by hand (P30 algorithm PSO→GA
        # @12:36 = user).
        if ref in user_edit_info:
            _et, _r, edited_search = user_edit_info[ref]
            if edited_search:
                for c in changes:
                    c["origin"] = "user"
        cfg_diff = structured_config_diff(_problem(prev_panel), _problem(panel_r))
        if cfg_diff is None and _canon(prev_panel) != _canon(panel_r):
            # The panel changed outside the modeled fields (rare) — still flag it.
            cfg_diff = {"other": True}
        def_changed = _canon(brief_for_display(prev_brief)) != _canon(brief_for_display(brief_r))
        stripped_def = brief_for_display(brief_r)
        out[ref] = {
            "changes": changes,
            "captured_terms": sorted(captured),
            # Def Δ = the stripped, BRIEF-side content only (no goal_terms/runs).
            "definition_change": (
                json.dumps(stripped_def, indent=2, ensure_ascii=False)
                if def_changed and stripped_def else None
            ),
            # Cfg Δ = the structured diff (chips), not a JSON dump.
            "config_change": cfg_diff,
            # Result-state brief/panel (FULL) for the row to display.
            "problem_def": json.dumps(brief_r, indent=2, ensure_ascii=False) if brief_r else None,
            "problem_config": json.dumps(panel_r, indent=2, ensure_ascii=False) if panel_r else None,
            # Open goal-term OQs at the result state — LLM-pass evidence.
            "open_goal_oqs": sorted({
                oq["goal_key"] for oq in (brief_r.get("open_questions") or [])
                if isinstance(oq, dict) and oq.get("goal_key") and oq["goal_key"] not in _CARRIER_KEYS
            }),
        }
        prev_brief, prev_panel = brief_r, panel_r
    return out


def goal_term_keys(snapshots: list[Any], port: Any) -> list[str]:
    """Canonical goal-term keys for the term dropdown: the port's FULL weight
    catalog (VRPTW = all 8, incl. the optional ``waiting_time``) unioned with
    every term this participant actually used (custom terms included), carriers
    excluded."""
    keys: set[str] = set()
    for hook in ("weight_item_labels", "weight_display_keys"):
        fn = getattr(port, hook, None)
        if fn is not None:
            try:
                keys.update(fn() or [])
            except Exception:
                pass
    for s in snapshots:
        gt = _goal_terms(_problem(_load(s.panel_config_json)))
        keys.update(k for k in gt if k not in _CARRIER_KEYS)
    return sorted(keys)
