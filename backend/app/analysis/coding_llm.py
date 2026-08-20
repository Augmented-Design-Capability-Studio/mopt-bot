"""LLM change-tagging for the session-coding tool.

The judgment-heavy half of the coding scheme — WHO initiated a goal-term change
(origin), WHEN a term first truly landed (applied), and what was merely talked
about (mentioned / dropped / declined) — kept mis-firing under mechanical
rules, because the answer lives in the conversation, not the config diff alone.
So a structured-output Gemini pass reads every exchange TOGETHER WITH the
deterministic evidence (the verified per-turn config diff, captured set, open
goal-term OQs) and proposes the composite change tags. No keyword/regex
matching (the project's no-NL-parsing rule): free text goes to the LLM, and
everything structural is computed by ``coding_suggestions`` and handed to it as
facts.

Two batched calls per session: a recall-oriented GENERATE pass proposes tags,
then a precision-oriented ADVERSARIAL AUDIT pass re-reads the same evidence and
keeps / fixes / drops each proposed tag (it cannot add new ones) — catching
mis-attributions like a file-upload exchange getting a user-origin tag. Results
are cached (``models.CodingLlmTags``) so a timeline refresh never re-hits the
API. Search-strategy / search-param tags are deliberately OUT of scope here —
they are hard structural facts emitted deterministically by
``coding_suggestions._search_changes``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_ORIGINS = ["user", "agent"]
_TYPES = ["goal-term", "detail", "weight", "term-type", "ranking"]
_EFFECTS = ["applied", "mentioned", "dropped", "declined", "removed"]
_MAX_USER_CHARS = 2000
_MAX_AGENT_CHARS = 1500
_MAX_RATIONALE_CHARS = 240


# Structured-diff field → coding-scheme change type.
_FIELD_TO_TYPE = {"weight": "weight", "type": "term-type", "rank": "ranking", "properties": "detail"}
_FACT_RATIONALE = "verified config change"


def _fact_changes(diff: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """``(type, term, effect)`` for every goal-term change the structured diff
    PROVES happened this exchange — the completeness floor no LLM may miss."""
    out: list[tuple[str, str, str]] = []
    if not diff:
        return out
    for t in diff.get("terms") or []:
        for c in t.get("changes") or []:
            ctype = _FIELD_TO_TYPE.get(c.get("field"))
            if ctype and t.get("term"):
                out.append((ctype, t["term"], "applied"))
    for a in diff.get("added") or []:
        if a.get("term"):
            out.append(("goal-term", a["term"], "applied"))
    for r in diff.get("removed") or []:
        out.append(("goal-term", r, "removed"))
    return out


def _backfill_facts(by_index: dict[int, list[dict[str, Any]]], exchanges: list[dict[str, Any]],
                    derivations: dict[str, dict[str, Any]]) -> None:
    """In-place completeness guarantee: every fact-backed change missing from the
    LLM's proposal becomes a tag. The LLM must never be the completeness
    mechanism for changes we can prove structurally (P01: 19 exchanges of weight
    changes, 0 tagged by a lite model). Origin is set deterministically where it
    is structural — a PANEL-EDIT ack turn is the participant's own hand (user),
    an OQ-ANSWER turn configures agent-asked terms (agent) — else left None
    (rendered `?`) for the audit pass to attribute."""
    for i, r in enumerate(exchanges):
        deriv = derivations.get(r.get("row_ref") or "") or {}
        facts = _fact_changes(deriv.get("config_change"))
        if not facts:
            continue
        tags = by_index.setdefault(i, [])
        have = {(t.get("type"), t.get("term")) for t in tags}
        mark = _marker((r.get("user_prompt") or "").strip())
        forced = None
        note = ""
        if mark and mark.startswith("PANEL EDIT"):
            forced, note = "user", " (participant panel edit)"
        elif mark and mark.startswith("OQ ANSWER"):
            forced, note = "agent", " (configured from the agent's open question)"
        for ctype, term, effect in facts:
            if (ctype, term) in have:
                continue
            tags.append({"origin": forced, "type": ctype, "term": term, "effect": effect,
                         "rationale": _FACT_RATIONALE + note})
        if not tags:
            by_index.pop(i, None)


def _term_catalog(port: Any) -> dict[str, str]:
    """{goal_term key: label} from the problem port."""
    try:
        labels = port.weight_item_labels() or {}
    except Exception:
        labels = {}
    return {k: str(v) for k, v in labels.items()}


def _observed_terms(derivations: dict[str, dict[str, Any]]) -> set[str]:
    """Every goal-term key that actually appears in this session's evidence —
    captured sets, diff entries, open OQs — so participant-invented custom terms
    are taggable too."""
    seen: set[str] = set()
    for d in derivations.values():
        seen.update(d.get("captured_terms") or [])
        seen.update(d.get("open_goal_oqs") or [])
        diff = d.get("config_change") or {}
        for t in diff.get("terms") or []:
            if isinstance(t, dict) and t.get("term"):
                seen.add(t["term"])
        for a in diff.get("added") or []:
            if isinstance(a, dict) and a.get("term"):
                seen.add(a["term"])
        seen.update(diff.get("removed") or [])
    return seen


def _fmt_num(v: Any) -> str:
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _render_diff(diff: dict[str, Any] | None) -> str:
    """One compact line per structural fact, e.g.
    ``+ capacity_penalty (w=3 hard r3)`` / ``lateness_penalty weight 80→160``."""
    if not diff:
        return ""
    lines: list[str] = []
    for a in diff.get("added") or []:
        # NOTE: the rank slot a new term receives is part of the addition, not a
        # ranking decision — deliberately NOT rendered, so it can't invite a
        # spurious `ranking` tag.
        bits = []
        if a.get("weight") is not None:
            bits.append(f"w={_fmt_num(a['weight'])}")
        if a.get("type"):
            bits.append(str(a["type"]))
        lines.append(f"+ {a.get('term')}" + (f" ({' '.join(bits)})" if bits else ""))
    for t in diff.get("removed") or []:
        lines.append(f"- {t}")
    for t in diff.get("terms") or []:
        for c in t.get("changes") or []:
            f = c.get("field")
            if f == "properties":
                lines.append(f"{t.get('term')} details changed")
            else:
                lines.append(
                    f"{t.get('term')} {f} {_fmt_num(c.get('from'))}→{_fmt_num(c.get('to'))}"
                )
    if diff.get("algorithm"):
        alg = diff["algorithm"]
        lines.append(f"algorithm {alg.get('from')}→{alg.get('to')} (tagged elsewhere — ignore)")
    if diff.get("params"):
        lines.append("solver params changed (tagged elsewhere — ignore)")
    return "\n".join(lines)


def _marker(user_prompt: str) -> str | None:
    """Classify the special structured user messages so the model reads them as
    what they are, not free chat."""
    if user_prompt.startswith("Config edited") or user_prompt.startswith("Definition edited"):
        return ("PANEL EDIT — the participant changed the panel BY HAND; the listed "
                "changes are the user's own actions (origin: user)")
    if user_prompt.startswith("Answered "):
        return ("OQ ANSWER — the participant answered the agent's open question(s); "
                "terms configured from the answer were AGENT-asked (origin: agent)")
    if user_prompt.startswith("I started Run"):
        return "RUN START notification (not free chat)"
    if user_prompt.startswith("I'm uploading") or user_prompt.startswith("Uploaded "):
        return ("FILE UPLOAD — the participant only attached data files; this is NOT "
                "a goal-term mention by the user (anything goal-related in the reply "
                "is the AGENT speaking)")
    return None


def _render_exchange(i: int, row: dict[str, Any], deriv: dict[str, Any] | None) -> str:
    user = (row.get("user_prompt") or "").strip()
    agent = (row.get("summary") or "").strip()
    if len(user) > _MAX_USER_CHARS:
        user = user[:_MAX_USER_CHARS] + " …[truncated]"
    if len(agent) > _MAX_AGENT_CHARS:
        agent = agent[:_MAX_AGENT_CHARS] + " …[truncated]"
    parts = [f"[{i}]"]
    mark = _marker(user) if user else None
    if mark:
        parts.append(f"NOTE: {mark}")
    parts.append(f"USER: {user if user else '(none — agent-initiated turn)'}")
    parts.append(f"AGENT: {agent}")
    facts = _render_diff((deriv or {}).get("config_change"))
    parts.append("CONFIG CHANGES THIS EXCHANGE:\n" + (facts if facts else "(none)"))
    if deriv:
        cap = deriv.get("captured_terms") or []
        parts.append(f"ACTIVE TERMS AFTER: {', '.join(cap) if cap else '(none)'}")
        oqs = deriv.get("open_goal_oqs") or []
        if oqs:
            parts.append(f"OPEN QUESTIONS ABOUT: {', '.join(oqs)}")
    return "\n".join(parts)


def _system_instruction(catalog: dict[str, str], extra_terms: set[str]) -> str:
    catalog_block = "\n".join(f"- `{k}` — {label}" for k, label in catalog.items())
    custom = sorted(extra_terms - set(catalog))
    custom_block = ("\nSession-specific custom terms: " + ", ".join(f"`{t}`" for t in custom)) if custom else ""
    return (
        "You are coding a research transcript: a participant and an AI assistant "
        "collaboratively formulate an optimization problem. Each numbered exchange "
        "shows the conversation plus VERIFIED structural facts (config changes that "
        "actually happened, the active goal terms afterwards, open questions). "
        "Produce composite change tags per exchange. Output structured JSON only.\n\n"
        f"Goal terms:\n{catalog_block}{custom_block}\n\n"
        "Each tag = {origin, type, term, effect, rationale}:\n"
        "- origin: who INITIATED this specific change — `user` (the participant "
        "asked for/made it, in their own words or by a panel edit) or `agent` (the "
        "assistant proposed/assumed/re-tuned it, including changes the participant "
        "merely approved by answering the agent's open question).\n"
        "- type: `goal-term` (term added/removed/first configured), `weight`, "
        "`term-type` (hard/soft/objective/custom), `ranking`, `detail` (a term's "
        "structured specifics, e.g. driver preferences, shift-hours limit).\n"
        "- effect: `applied` (the config verifiably changed — ONLY when the facts "
        "show it), `mentioned` (a term was raised/discussed/promised but the "
        "config did NOT change this exchange — tag at its FIRST such mention), "
        "`dropped` (a previously-raised term is now clearly never landing: the "
        "conversation moved on for good — tag at the exchange where that becomes "
        "clear), `declined` (one side proposed it and the other side rejected it), "
        "`removed` (a term that WAS active got taken out).\n"
        "- rationale: one short sentence quoting/paraphrasing the evidence.\n\n"
        "PRIMARY GOAL: for every goal term that ever becomes active, tag the "
        "exchange where it FIRST became active (`applied`, type `goal-term`) with "
        "its true origin. Weight/type/rank/detail changes to already-active terms "
        "get their own tags on the exchange where the facts show them.\n"
        "SECONDARY GOAL — MENTION SCAN (work hard at this): for EVERY exchange, "
        "actively scan both the USER and AGENT text against the goal-term list. "
        "Semantic mentions count — \"arrive within the delivery window\" is "
        "lateness_penalty, \"don't overload the vans\" is capacity_penalty — not "
        "just literal key names. At a term's FIRST mention while it is not yet "
        "active, emit {<mentioner>, goal-term, term, mentioned} — EVEN IF the "
        "other side does not react at all. A user constraint the assistant "
        "silently ignores (no config change, no follow-up) is still "
        "`mentioned` with origin `user` at that exchange; an assistant "
        "suggestion or open question the user never engages with is still "
        "`mentioned` with origin `agent` at the ask. The mention in the text "
        "ALONE suffices — `mentioned` needs NO structural corroboration "
        "(only `applied` does).\n"
        "WHAT COUNTS AS A MENTION: a requirement, preference, or concern about "
        "the term expressed in the speaker's OWN words. NOT a mention: uploading "
        "or naming data files/columns; describing what the data contains; the "
        "assistant describing its own capabilities (\"I can analyze travel "
        "times\"). And the ORIGIN is the side whose TEXT contains the mention: "
        "if only the ASSISTANT's reply names the term (e.g. it lists options "
        "after a file upload), the origin is `agent` — never `user` just "
        "because the user's message came first.\n"
        "COMPLETENESS CROSS-CHECK before you answer: (a) every term that becomes "
        "active whose earliest mention PRECEDES its application must carry that "
        "earlier `mentioned` tag too — both tags, on their respective "
        "exchanges; (b) an exchange whose facts show config changes may ALSO "
        "need `mentioned` tags for other, merely-mentioned terms; (c) "
        "END-OF-SESSION SWEEP: every term that was raised but is still not "
        "active at the last exchange must end with a `dropped` tag on the "
        "exchange where it was last in play / clearly abandoned (`declined` "
        "instead if it was explicitly rejected).\n\n"
        "Rules:\n"
        "- Trust the CONFIG CHANGES facts over the prose: if the assistant claims a "
        "change but the facts show none, that is `mentioned`, not `applied`.\n"
        "- Origin follows who ORIGINATED the requirement, not who executed it: a "
        "user request the agent implements is `user`; an agent post-run re-tune of "
        "a user's term is `agent`; a term configured because the user answered the "
        "agent's open question is `agent`.\n"
        "- A NEWLY ADDED term's rank slot is part of the addition — do NOT emit a "
        "`ranking` tag for it. `ranking` is only for a deliberate re-prioritization "
        "of EXISTING terms.\n"
        "- Do NOT tag search strategy/algorithm or solver-parameter changes — they "
        "are tagged elsewhere.\n"
        "- Do not restate an unchanged config as new tags: `applied` requires the "
        "facts to show the change. (`mentioned`/`dropped`/`declined` come from "
        "the conversation and need no config change.)\n"
        "- At most one tag per (term, type, effect) per exchange."
    )


def tag_session_changes(
    rows: list[dict[str, Any]],
    derivations: dict[str, dict[str, Any]],
    port: Any,
    api_key: str,
    model: str,
) -> dict[str, list[dict[str, Any]]] | None:
    """``{row_ref: [{origin, type, term, effect, rationale}]}`` for one session,
    via one batched structured-output Gemini call.

    Returns ``None`` on failure or missing key/model/catalog — the caller must
    then KEEP any existing cache (a failed run is not an empty result)."""
    if not api_key or not model:
        return None
    catalog = _term_catalog(port)
    if not catalog:
        return None

    exchanges = [r for r in rows if r.get("codeable") and r.get("row_ref")]
    if not exchanges:
        return {}

    observed = _observed_terms(derivations)
    term_keys = sorted(set(catalog) | observed)

    block_list = [
        _render_exchange(i, r, derivations.get(r["row_ref"])) for i, r in enumerate(exchanges)
    ]
    user_prompt = (
        "Tag the numbered exchanges. Return one entry per exchange that has "
        "anything to code (omit the rest).\n\n" + "\n\n".join(block_list)
    )

    schema = {
        "type": "object",
        "properties": {
            "exchanges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "origin": {"type": "string", "enum": _ORIGINS},
                                    "type": {"type": "string", "enum": _TYPES},
                                    "term": {"type": "string", "enum": term_keys},
                                    "effect": {"type": "string", "enum": _EFFECTS},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["origin", "type", "term", "effect", "rationale"],
                            },
                        },
                    },
                    "required": ["index", "changes"],
                },
            }
        },
        "required": ["exchanges"],
    }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        parsed = _generate_json(
            client, types, model, _system_instruction(catalog, observed), user_prompt, schema
        )
    except Exception as exc:
        log.warning("LLM change tagging failed (%s)", exc)
        return None

    valid_terms = set(term_keys)
    by_index: dict[int, list[dict[str, Any]]] = {}
    for entry in (parsed or {}).get("exchanges", []) or []:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        changes = entry.get("changes")
        if not isinstance(idx, int) or not (0 <= idx < len(exchanges)) or not isinstance(changes, list):
            continue
        seen: set[tuple] = set()
        cleaned: list[dict[str, Any]] = []
        for c in changes:
            if not isinstance(c, dict):
                continue
            origin, ctype = c.get("origin"), c.get("type")
            term, effect = c.get("term"), c.get("effect")
            if (origin not in _ORIGINS or ctype not in _TYPES
                    or term not in valid_terms or effect not in _EFFECTS):
                continue
            key = (origin, ctype, term, effect)
            if key in seen:
                continue
            seen.add(key)
            rationale = str(c.get("rationale") or "")[:_MAX_RATIONALE_CHARS]
            cleaned.append({"origin": origin, "type": ctype, "term": term,
                            "effect": effect, "rationale": rationale})
        if cleaned:
            by_index[idx] = cleaned

    # Completeness floor: every structurally PROVEN change the LLM missed is
    # backfilled (origin deterministic on panel-edit/OQ-answer turns, else `?`
    # for the audit to attribute). The LLM is judgment, not coverage.
    _backfill_facts(by_index, exchanges, derivations)

    # Second, ADVERSARIAL pass: audit every proposed tag against the same
    # evidence (keep / fix / drop — it cannot add tags; fact-backed tags may
    # only be fixed, never dropped). Generation is recall-oriented and
    # occasionally mis-attributes (P01 0:00: a file-upload exchange got
    # travel_time tagged origin USER while the tag's own rationale said the
    # AGENT mentioned it); the audit is precision-oriented and catches exactly
    # that — and supplies the origin for backfilled `?` tags. Best-effort: if
    # the verify call fails, keep the unverified tags.
    if by_index:
        try:
            by_index = _verify_tags(client, types, model, block_list, by_index, term_keys)
        except Exception as exc:
            log.warning("LLM tag verification failed — keeping unverified tags (%s)", exc)

    return {exchanges[idx]["row_ref"]: tags for idx, tags in by_index.items() if tags}


def _generate_json(client: Any, types: Any, model: str, system: str,
                   prompt: str, schema: dict) -> dict:
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
    return parsed if isinstance(parsed, dict) else {}


_VERIFY_INSTRUCTION = (
    "You are AUDITING proposed coding tags for a research transcript, against the "
    "same evidence blocks. For EACH proposed tag decide: `keep` (the evidence "
    "supports origin, type, term, and effect), `fix` (right idea, wrong field — "
    "supply the corrected fields), or `drop` (unsupported). You may NOT invent new "
    "tags. Be skeptical — when the evidence does not support the tag, drop it.\n\n"
    "SPECIAL CASES:\n"
    "- A tag marked [FACT] restates a structurally VERIFIED config change — it may "
    "NOT be dropped. Your only job on it is the origin (and you may refine the "
    "rationale via `fix`).\n"
    "- A tag whose origin shows `?` is unattributed — you MUST `fix` it with the "
    "correct origin: `user` if the participant asked for / made this change (their "
    "text or a panel edit), `agent` if the assistant proposed, assumed, or re-tuned "
    "it on its own (incl. post-run adjustments and changes the participant merely "
    "approved by answering the agent's question).\n\n"
    "Errors to hunt for:\n"
    "- ORIGIN on the wrong side: the origin must be the side whose OWN text raises "
    "the term (or, for `applied`, who originated the requirement). A tag whose "
    "rationale says the ASSISTANT mentioned the term cannot have origin `user`. A "
    "file-upload or data-description message raises NO goal terms.\n"
    "- `applied` without the CONFIG CHANGES facts showing that change.\n"
    "- `ranking` tagged for a NEWLY ADDED term (its rank slot is part of the add).\n"
    "- Duplicated or restated tags for a config that did not change that exchange.\n"
    "- The wrong goal term for what the text actually discusses.\n"
    "Output one verdict per proposed tag, addressed by (exchange_index, tag_index)."
)


def _verify_tags(client: Any, types: Any, model: str, block_list: list[str],
                 by_index: dict[int, list[dict[str, Any]]],
                 term_keys: list[str]) -> dict[int, list[dict[str, Any]]]:
    """Audit pass: keep / fix / drop each proposed tag. Only exchanges that have
    proposed tags are re-sent (with their tags listed). Tags without a verdict
    are kept."""
    sections = []
    for idx in sorted(by_index):
        tag_lines = "\n".join(
            f"  ({j}) {t.get('origin') or '?'} · {t['type']} · {t['term']} · {t['effect']}"
            f" — {t['rationale']}"
            + (" [FACT]" if str(t.get("rationale") or "").startswith(_FACT_RATIONALE) else "")
            for j, t in enumerate(by_index[idx])
        )
        sections.append(f"{block_list[idx]}\nPROPOSED TAGS:\n{tag_lines}")
    prompt = "Audit the proposed tags on these exchanges.\n\n" + "\n\n".join(sections)

    schema = {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "exchange_index": {"type": "integer"},
                        "tag_index": {"type": "integer"},
                        "action": {"type": "string", "enum": ["keep", "fix", "drop"]},
                        "origin": {"type": "string", "enum": _ORIGINS},
                        "type": {"type": "string", "enum": _TYPES},
                        "term": {"type": "string", "enum": term_keys},
                        "effect": {"type": "string", "enum": _EFFECTS},
                        "reason": {"type": "string"},
                    },
                    "required": ["exchange_index", "tag_index", "action"],
                },
            }
        },
        "required": ["verdicts"],
    }
    parsed = _generate_json(client, types, model, _VERIFY_INSTRUCTION, prompt, schema)

    dropped: set[tuple[int, int]] = set()
    for v in (parsed or {}).get("verdicts", []) or []:
        if not isinstance(v, dict):
            continue
        ei, ti = v.get("exchange_index"), v.get("tag_index")
        if not (isinstance(ei, int) and isinstance(ti, int)):
            continue
        tags = by_index.get(ei)
        if tags is None or not (0 <= ti < len(tags)):
            continue
        action = v.get("action")
        is_fact = str(tags[ti].get("rationale") or "").startswith(_FACT_RATIONALE)
        if action == "drop":
            if not is_fact:  # fact-backed tags are structurally proven — undroppable
                dropped.add((ei, ti))
        elif action == "fix":
            t = tags[ti]
            fixable = ("origin",) if is_fact else ("origin", "type", "term", "effect")
            for f in fixable:  # a fact's type/term/effect are structurally proven
                if v.get(f) is not None:
                    t[f] = v[f]
            reason = str(v.get("reason") or "").strip()
            if reason:
                t["rationale"] = reason[:_MAX_RATIONALE_CHARS]

    out: dict[int, list[dict[str, Any]]] = {}
    for idx, tags in by_index.items():
        kept: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        for j, t in enumerate(tags):
            if (idx, j) in dropped:
                continue
            key = (t.get("origin"), t["type"], t["term"], t["effect"])
            if key in seen:
                continue
            seen.add(key)
            kept.append(t)
        if kept:
            out[idx] = kept
    return out
