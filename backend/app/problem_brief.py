from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

CONFIG_ITEM_PREFIX = "config-"
_OPEN_QUESTION_TOKEN_RE = re.compile(r"[a-z0-9]+")
_OPEN_QUESTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "may",
    "of",
    "on",
    "or",
    "our",
    "should",
    "the",
    "to",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}
_UPLOAD_OPEN_QUESTION_KEYWORDS = (
    "upload",
    "uploaded",
    "file",
    "files",
    "csv",
    "pdf",
    "spreadsheet",
    "dataset",
    "data sheet",
    "driver info",
    "order data",
)

def locked_goal_terms_prompt_section(panel_config: Any, test_problem_id: str | None = None) -> str | None:
    """Human-readable block for chat / brief system prompts when goal terms are locked in the panel."""
    if not isinstance(panel_config, dict):
        return None
    problem = panel_config.get("problem") if isinstance(panel_config.get("problem"), dict) else None
    if not isinstance(problem, dict):
        return None
    raw = problem.get("locked_goal_terms")
    if not isinstance(raw, list) or not raw:
        return None
    from app.problems.registry import get_study_port

    labels = get_study_port(test_problem_id).weight_item_labels()
    lines: list[str] = []
    for key in raw:
        if not isinstance(key, str) or not key.strip():
            continue
        label = labels.get(key, key.replace("_", " ").strip().title())
        lines.append(f"- `{key}` — {label}")
    if not lines:
        return None
    body = "\n".join(lines)
    return (
        "## Locked goal terms (saved Problem Config)\n"
        "The participant locked these objective/penalty terms in the **Problem Config** UI. "
        "**Do not** propose changing weights or penalties for these keys (including via `problem_brief_patch`) unless the "
        "user says they unlocked them. If they ask to change a locked term, say clearly that it is locked and they must "
        "unlock it in Problem Config first.\n"
        f"{body}"
    )


def current_weights_prompt_section(
    panel_config: Any,
    *,
    test_problem_id: str | None = None,
    temperature: str = "warm",
) -> str | None:
    """
    Visible-chat prompt block surfacing each goal term's current numeric importance level
    (weight) plus its constraint type, in human labels. Lets the assistant quote concrete
    numbers when a participant asks "why is X at Y?" without forcing the LLM to extract
    them from brief prose.

    Suppressed in cold state (would leak benchmark identity through the labels).
    """
    if temperature == "cold":
        return None
    if not isinstance(panel_config, dict):
        return None
    problem = panel_config.get("problem") if isinstance(panel_config.get("problem"), dict) else None
    if not isinstance(problem, dict):
        return None
    weights = problem.get("weights")
    if not isinstance(weights, dict) or not weights:
        return None

    constraint_types = problem.get("constraint_types") if isinstance(problem.get("constraint_types"), dict) else {}
    order = problem.get("goal_term_order") if isinstance(problem.get("goal_term_order"), list) else None

    from app.problems.registry import get_study_port

    labels = get_study_port(test_problem_id).weight_item_labels()

    if order:
        keys = [k for k in order if isinstance(k, str) and k in weights]
        for k in sorted(weights):
            if k not in keys:
                keys.append(k)
    else:
        keys = sorted(weights)

    type_label = {
        "objective": "Objective",
        "soft": "Soft",
        "hard": "Hard",
        "custom": "Custom",
    }
    lines: list[str] = []
    for key in keys:
        value = weights.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        label = labels.get(str(key), str(key).replace("_", " ").strip().title())
        ctype_raw = constraint_types.get(str(key)) if isinstance(constraint_types, dict) else None
        ctype = type_label.get(str(ctype_raw or "objective").lower(), "Objective")
        lines.append(f"- {label}: {float(value):g}  ({ctype})")
    if not lines:
        return None

    body = "\n".join(lines)
    return (
        "## Current importance levels (saved Problem Config)\n"
        "These are the participant's actual numeric weights right now, listed in their priority order. "
        "When the participant asks **\"why is X at Y?\"** or **\"what are the current weights?\"**, quote "
        "these values directly — by their human labels above, never by snake_case keys. Frame answers "
        "relative to the rest of the list (which term dominates, which is being downweighted, what "
        "constraint type each one carries).\n"
        f"{body}"
    )


_EXPLICIT_VALUE_RE = re.compile(
    r"\b(?:set to|weight(?:ed)? to|weight(?:ed)? at|target(?:ed)? at|target(?:ed)? of|target of|penalty of)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_ALGORITHM_PARAM_RE = re.compile(
    r"\balgorithm parameter\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+is set to\s+([^\s]+)",
    re.IGNORECASE,
)
# Real solver-config tokens that should never appear in a qualitative goal summary.
# Bare English words like "weight"/"penalty"/"algorithm" are NOT included here — they are
# normal vocabulary in optimization problems (e.g. knapsack uses "weight" as a domain term).
# Numeric annotations attached to those words are stripped separately by the regex below.
_GOAL_SUMMARY_FORBIDDEN_RE = re.compile(
    r"\b(?:pop_size|temp_init|cooling_rate|c1|c2|pc|pm)\b",
    re.IGNORECASE,
)
# Strip inline numeric annotations like "(weight 1)", "weight=5", "penalty 50",
# "120 epochs", "30 iterations", "pop_size 100" — the goal summary should stay qualitative.
_GOAL_SUMMARY_NUMERIC_ANNOTATION_RE = re.compile(
    r"""
    (?:
      \(\s*(?:weights?|penalt(?:y|ies)|epochs?|iterations?|generations?|
              pop_size|population|c1|c2|pc|pm|temp_init|cooling_rate)
        [^)]*\d[^)]*\)                       # parenthetical with one of those tokens + digit
    | \b(?:weights?|penalt(?:y|ies)|pop_size|population|epochs?|
              iterations?|generations?|c1|c2|pc|pm|temp_init|cooling_rate)
        \s*[=:]?\s*\d+(?:\.\d+)?             # "weight 5", "penalty=10", "pop_size 100"
    | \b\d+(?:\.\d+)?\s*(?:epochs?|iterations?|generations?)\b   # "120 epochs"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Model sometimes emits fake "open questions" like "Cap shifts? (Answered: 8h)." — fold into gathered instead.
# Pattern covers common model formatting variants: (Answered: X), [Answered: X], — Answer: X, - Answered: X.
_ANSWERED_SUFFIX_IN_OPQ_RE = re.compile(
    r"^(?P<q>.+?)\s*(?:\(\s*answered\s*:\s*|\[\s*answered\s*:\s*|[-–]\s*answer\s*:\s*|[-–]\s*answered\s*:\s*)(?P<a>.+?)[\])]?\s*\.?\s*\Z",
    re.IGNORECASE | re.DOTALL,
)

def _compact_uid() -> str:
    return uuid4().hex[:10]


def _new_item_id(kind: str) -> str:
    k = "assumption" if kind == "assumption" else "gathered"
    return f"item-{k}-{_compact_uid()}"


def _new_question_id() -> str:
    return f"question-open-{_compact_uid()}"


def default_problem_brief(test_problem_id: str | None = None) -> dict[str, Any]:
    from app.problems.registry import get_study_port

    port = get_study_port(test_problem_id)
    tmpl = port.problem_brief_template_fields()
    return {
        "goal_summary": "",
        "run_summary": "",
        "items": [],
        "open_questions": [],
        "goal_terms": {},
        "unmodeled_requests": [],
        # LLM-judged conversation warmth (one-way sticky). False = the
        # conversation hasn't arrived at the problem-module's topic yet, so
        # the system prompt hides the benchmark appendix and the LLM stays
        # domain-neutral. The brief-update model flips this to True once it
        # judges the participant has engaged with the benchmark's subject
        # matter; once True it never returns to False — see
        # ``merge_problem_brief_patch``.
        "topic_engaged": False,
        "solver_scope": tmpl.get("solver_scope", "general_metaheuristic_translation"),
        "backend_template": tmpl.get("backend_template", "routing_time_windows"),
    }


def _normalize_unmodeled_request(raw: Any) -> dict[str, Any] | None:
    """Normalize one ``unmodeled_requests`` entry.

    Each entry tracks something the participant asked for that has no
    matching goal-term key and is not a hard constraint already enforced by
    the encoding. The shape is intentionally small — researcher-facing
    triage value, not a structured solver input. Returns ``None`` when the
    entry has no usable ``user_text`` (without that, the row is noise).
    """
    if not isinstance(raw, dict):
        return None
    user_text = raw.get("user_text")
    if not isinstance(user_text, str):
        return None
    user_text = user_text.strip()
    if not user_text:
        return None
    out: dict[str, Any] = {"user_text": user_text}
    closest = raw.get("closest_match")
    if isinstance(closest, str):
        closest = closest.strip()
        if closest:
            out["closest_match"] = closest
    rationale = raw.get("rationale")
    if isinstance(rationale, str):
        rationale = rationale.strip()
        if rationale:
            out["rationale"] = rationale
    at = raw.get("at")
    if isinstance(at, str):
        at = at.strip()
        if at:
            out["at"] = at
    return out


CHAT_PROMPT_COLD_BACKEND_TEMPLATE = "deferred"
# Back-compat export for tests/tools that still import this symbol.
CHAT_PROMPT_COLD_SYSTEM_ITEM_TEXT = (
    "Session uses a fixed benchmark-backed solver; benchmark details appear once goals are stated."
)


def is_chat_cold_start(brief: dict[str, Any] | None) -> bool:
    """Cold-start = the conversation has not yet arrived at the problem-module's
    topic, so the system prompt hides benchmark vocabulary and server-side
    monitors (upload / goal / algorithm) stay dormant.

    Two signals, OR'd:

    1. **LLM-judged flag.** ``brief.topic_engaged`` is one-way sticky and
       set when the brief-update LLM emits ``topic_engaged_next: true``.
       Primary signal when present.
    2. **Content fallback.** Any ``items[]`` row with
       ``source in {user, upload}`` and non-empty text, OR a non-empty
       ``goal_summary``. Agent-pushed defaults (``source: agent``) are
       deliberately excluded so a mediocre starter push or an agile
       pre-confirmation assumption doesn't flip warmth on its own.

    The fallback exists because the LLM is unreliable at emitting
    ``topic_engaged_next``. Without it, the monitors never run even when
    the participant has clearly engaged with the domain — exactly the
    failure mode that left a session with no algorithm assumption and no
    goal OQ despite the user describing a routing problem and uploading
    data.
    """
    if not isinstance(brief, dict):
        return True
    if bool(brief.get("topic_engaged")):
        return False
    if str(brief.get("goal_summary") or "").strip():
        return False
    items = brief.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip().lower()
            if source not in {"user", "upload"}:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            return False
    return True


def surface_problem_brief_for_chat_prompt(brief: dict[str, Any] | None, *, cold: bool) -> dict[str, Any] | None:
    """
    Return a copy of the brief for LLM system instructions. When cold, mask template fields
    so the model is not primed with benchmark-specific nouns (DB row is unchanged).
    """
    if brief is None:
        return None
    if not cold:
        return brief
    surf = deepcopy(brief) if isinstance(brief, dict) else {}
    surf["backend_template"] = CHAT_PROMPT_COLD_BACKEND_TEMPLATE
    if "solver_scope" in surf:
        surf["solver_scope"] = "general_metaheuristic_translation"
    return surf


def _clean_question_fragment(text: str) -> str:
    return re.sub(r"^\s*(?:[-*•]\s+|\d+[\.\)]\s*)", "", text).strip()


def _normalize_question_status(raw: Any) -> str:
    status = str(raw or "open").strip().lower()
    if status not in {"open", "answered"}:
        return "open"
    return status


def _normalize_question_answer_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _normalize_question(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        text = str(raw.get("text") or "").strip()
        if not text:
            return None
        question_id = str(raw.get("id") or _new_question_id())
        status = _normalize_question_status(raw.get("status"))
        answer_text = _normalize_question_answer_text(raw.get("answer_text"))
        if status == "open":
            answer_text = None
        return {"id": question_id, "text": text, "status": status, "answer_text": answer_text}
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return {"id": _new_question_id(), "text": text, "status": "open", "answer_text": None}


def _preserve_answered_state(
    incoming: list[dict[str, Any]], base_by_id: dict[str, dict[str, Any]]
) -> None:
    """In-place: for questions that exist in base with status answered, keep that state
    if the incoming question lacks status/answer_text (e.g. from model schema omission)."""
    for i, q in enumerate(incoming):
        qid = str(q.get("id", "") or "").strip()
        base = base_by_id.get(qid) if qid else None
        if not base or str(base.get("status") or "").strip().lower() != "answered":
            continue
        incoming_status = str(q.get("status") or "").strip().lower()
        incoming_answer = _normalize_question_answer_text(q.get("answer_text"))
        if incoming_status != "answered" or incoming_answer is None:
            incoming[i] = {
                **q,
                "status": base.get("status", "answered"),
                "answer_text": base.get("answer_text"),
            }


def _split_question_text(text: str) -> list[str]:
    """Split one stored OQ string into its constituent open questions.

    Sentence-aware so that inline-option phrasings stay a single OQ:

    * ``"How strict is the limit? Options A, B, C. Should I go with the default?"``
      → two OQs (``"How strict is the limit? Options A, B, C."`` and
      ``"Should I go with the default?"``).  The declarative ``"Options A, B, C."``
      is attached to the preceding question rather than emitted as its own row.
    * ``"Which method? Options include GA, PSO, SA."`` → one OQ; the trailing
      declarative is attached to the lone question.
    * ``"How strict should lateness be? Should overtime be capped?"`` → two OQs
      (existing concatenated-questions behaviour, preserved).
    * Pure declarative text becomes a single OQ.

    Concretely: split on terminal-punctuation sentence boundaries (``?``, ``!``,
    ``.``), then for each sentence — if it ends with ``?``/``!`` it starts a new
    OQ; otherwise it's a declarative annotation that re-attaches to the most
    recent OQ (or, if none exists yet, buffers as a leading prefix that prepends
    onto the first question we see, or emits as a standalone declarative OQ if
    no question ever arrives).
    """
    fragments: list[str] = []
    pending_lead: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_question_fragment(raw_line)
        if not line:
            continue
        # Negative lookahead `(?!\()` keeps "Shift cap? (Answered: 8h)." glued
        # — used by merge-time sanitization of fake answered questions.
        for part in re.split(r"(?<=[?!.])\s+(?!\()", line):
            cleaned = _clean_question_fragment(part)
            if not cleaned:
                continue
            is_question = cleaned.endswith("?") or cleaned.endswith("!")
            if is_question:
                if pending_lead:
                    cleaned = " ".join(pending_lead + [cleaned])
                    pending_lead = []
                fragments.append(cleaned)
            elif fragments:
                # Declarative tail — annotation for the most recent question.
                fragments[-1] = f"{fragments[-1]} {cleaned}"
            else:
                # No question yet — buffer as a leading prefix.
                pending_lead.append(cleaned)
    if pending_lead:
        # Pure declarative input (no `?`/`!` ever seen) — emit as a single OQ.
        fragments.append(" ".join(pending_lead))
    return fragments


def _coerce_question_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in value:
        normalized = _normalize_question(entry)
        if normalized is None:
            continue
        fragments = _split_question_text(normalized["text"])
        if not fragments:
            continue
        if len(fragments) == 1:
            out.append(
                {
                    "id": normalized["id"],
                    "text": fragments[0],
                    "status": normalized.get("status", "open"),
                    "answer_text": normalized.get("answer_text"),
                }
            )
            continue
        for idx, fragment in enumerate(fragments, start=1):
            out.append(
                {
                    "id": f"{normalized['id']}-{idx}",
                    "text": fragment,
                    "status": normalized.get("status", "open"),
                    "answer_text": normalized.get("answer_text"),
                }
            )
    return out


def _gathered_text_key(text: Any) -> str:
    return str(text or "").strip().lower()


def _sentence_start(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s[0].upper() + s[1:] if len(s) > 1 else s.upper()


def _ensure_terminator(s: str) -> str:
    t = s.strip()
    if not t:
        return t
    if t[-1] not in ".!?":
        t += "."
    return _sentence_start(t)


def _sanitize_goal_summary(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    # First pass: strip numeric annotations inline rather than dropping whole clauses.
    stripped = _GOAL_SUMMARY_NUMERIC_ANNOTATION_RE.sub(" ", raw)
    stripped = re.sub(r"\(\s*\)", "", stripped)
    stripped = re.sub(r"\s+([,.;:!?])", r"\1", stripped)
    stripped = re.sub(r"\s{2,}", " ", stripped).strip()
    if not stripped:
        return ""
    # Second pass: drop clauses that still mention real config tokens (pop_size, c1, …).
    clauses = [chunk.strip() for chunk in re.split(r"[.;]", stripped) if chunk.strip()]
    clean_clauses = [clause for clause in clauses if not _GOAL_SUMMARY_FORBIDDEN_RE.search(clause)]
    if not clean_clauses:
        return ""
    return _ensure_terminator(" ".join(clean_clauses))


def _sanitize_run_summary(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    one_line = " ".join(raw.split())
    return _ensure_terminator(one_line)


def _format_answered_open_question_gathered(question: str, answer: str) -> str:
    """Turn a resolved Q&A into one gathered line: literal question — answer (then normalized punctuation)."""
    a = (answer or "").strip()
    if not a:
        return ""
    q = (question or "").strip()
    combined = f"{q} — {a}" if q else a
    return _ensure_terminator(combined)


def _promote_answered_open_questions_to_gathered(
    items: list[dict[str, Any]], questions: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Answered questions with non-empty answer_text become gathered rows; removed from open_questions."""
    seen = {
        _gathered_text_key(i.get("text"))
        for i in items
        if isinstance(i, dict) and str(i.get("kind") or "").strip().lower() == "gathered"
    }
    new_items = list(items)
    kept_q: list[dict[str, Any]] = []
    for q in questions:
        st = str(q.get("status") or "").strip().lower()
        at = str(q.get("answer_text") or "").strip()
        if st != "answered" or not at:
            kept_q.append(q)
            continue
        qtext = str(q.get("text") or "").strip()
        combined = _format_answered_open_question_gathered(qtext, at)
        key = _gathered_text_key(combined)
        if key not in seen:
            seen.add(key)
            qid = str(q.get("id") or _new_question_id())
            new_items.append(
                {
                    "id": f"item-gathered-from-question-{qid}",
                    "text": combined,
                    "kind": "gathered",
                    "source": "user",
                }
            )
    return new_items, kept_q


def _split_pseudo_answered_open_questions(
    questions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strip '(Answered: …)' suffix questions into gathered rows; return (gathered, questions_kept)."""
    gathered_out: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for q in questions:
        text = str(q.get("text") or "").strip()
        m = _ANSWERED_SUFFIX_IN_OPQ_RE.match(text)
        if not m:
            kept.append(q)
            continue
        q_part = m.group("q").strip()
        a_part = m.group("a").strip()
        combined = _format_answered_open_question_gathered(q_part, a_part) if q_part else _ensure_terminator(a_part)
        qid = str(q.get("id") or _new_question_id())
        gathered_out.append(
            {
                "id": f"item-gathered-from-question-{qid}",
                "text": combined,
                "kind": "gathered",
                "source": "user",
            }
        )
    return gathered_out, kept


def _merge_gathered_deduped(items: list[dict[str, Any]], additions: list[dict[str, Any]]) -> None:
    seen = {
        _gathered_text_key(i.get("text"))
        for i in items
        if isinstance(i, dict) and str(i.get("kind") or "").strip().lower() == "gathered"
    }
    for g in additions:
        key = _gathered_text_key(g.get("text"))
        if key not in seen:
            seen.add(key)
            items.append(g)


def _question_text_key(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _question_tokens(text: Any) -> set[str]:
    tokens = {
        t
        for t in _OPEN_QUESTION_TOKEN_RE.findall(str(text or "").strip().lower())
        if t and t not in _OPEN_QUESTION_STOPWORDS and not t.isdigit()
    }
    return tokens


def _question_fact_corpus(brief: dict[str, Any]) -> list[set[str]]:
    rows: list[str] = []
    goal_summary = str(brief.get("goal_summary") or "").strip()
    if goal_summary:
        rows.append(goal_summary)
    for item in brief.get("items") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        rows.append(text)
    corpus: list[set[str]] = []
    for row in rows:
        tokens = _question_tokens(row)
        if tokens:
            corpus.append(tokens)
    return corpus


def _question_is_resolved_by_corpus(question: dict[str, Any], corpus: list[set[str]]) -> bool:
    q_tokens = _question_tokens(question.get("text"))
    if not q_tokens or not corpus:
        return False
    required_overlap = max(2, min(3, len(q_tokens)))
    for fact_tokens in corpus:
        shared = q_tokens & fact_tokens
        if len(shared) < required_overlap:
            continue
        coverage = len(shared) / max(1, len(q_tokens))
        # Conservative threshold to avoid deleting genuinely open questions.
        if coverage >= 0.66 and any(len(tok) >= 4 for tok in shared):
            return True
    return False


def cleanup_open_questions(
    brief: Any, *, infer_resolved: bool = True
) -> tuple[dict[str, Any], dict[str, int | bool]]:
    """
    Normalize and prune open questions with deterministic rules.

    Returns (cleaned_brief, metadata) where metadata tracks removals by reason.
    """
    normalized = normalize_problem_brief(brief)
    original_count = len(normalized.get("open_questions") or [])
    deduped_questions: list[dict[str, Any]] = []
    seen_question_texts: set[str] = set()
    duplicate_removed = 0
    for question in normalized.get("open_questions") or []:
        key = _question_text_key(question.get("text"))
        if not key:
            continue
        if key in seen_question_texts:
            duplicate_removed += 1
            continue
        seen_question_texts.add(key)
        deduped_questions.append(question)

    inferred_removed = 0
    if infer_resolved and deduped_questions:
        corpus = _question_fact_corpus(normalized)
        kept: list[dict[str, Any]] = []
        for question in deduped_questions:
            if _question_is_resolved_by_corpus(question, corpus):
                inferred_removed += 1
                continue
            kept.append(question)
        deduped_questions = kept

    cleaned = {**normalized, "open_questions": deduped_questions}
    metadata: dict[str, int | bool] = {
        "infer_resolved": infer_resolved,
        "original_count": original_count,
        "removed_duplicates": duplicate_removed,
        "removed_inferred": inferred_removed,
        "final_count": len(deduped_questions),
        "removed_total": original_count - len(deduped_questions),
    }
    return cleaned, metadata


def question_is_upload_related(question: Any) -> bool:
    """Heuristic marker for open questions that are asking for uploaded source files."""
    if not isinstance(question, dict):
        return False
    text = str(question.get("text") or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _UPLOAD_OPEN_QUESTION_KEYWORDS)


def upload_satisfies_open_question(
    question: Any,
    uploaded_file_names: list[str],
) -> bool:
    """
    Placeholder validator for future upload-content checks.

    TODO: inspect uploaded file contents/metadata and return False when required
    information is still missing for a specific question.
    """
    if not question_is_upload_related(question):
        return False
    _ = uploaded_file_names
    return True


UPLOAD_MARKER_ITEM_ID = "item-gathered-upload"


def _format_upload_marker_text(file_names: list[str]) -> str:
    if not file_names:
        return ""
    return f"Source data file(s) uploaded: {', '.join(file_names)}."


def _is_upload_marker_item(item: Any) -> bool:
    """True for gathered rows that exist solely to record an upload event.

    Matches three flavours:
    - canonical id `item-gathered-upload` (current behavior),
    - any row with `source == "upload"` (programmatic provenance),
    - legacy `item-gathered-from-question-…` rows whose text contains the
      literal "Uploaded file(s) received: …" answer string that the prior
      version of this function emitted (so that retroactive fixes clean up
      stale duplicates on the next upload turn).
    """
    if not isinstance(item, dict):
        return False
    if str(item.get("kind") or "").strip().lower() != "gathered":
        return False
    if str(item.get("id") or "") == UPLOAD_MARKER_ITEM_ID:
        return True
    if str(item.get("source") or "").strip().lower() == "upload":
        return True
    item_id = str(item.get("id") or "")
    text = str(item.get("text") or "").strip().lower()
    if item_id.startswith("item-gathered-from-question-") and "uploaded file(s) received" in text:
        return True
    return False


def resolve_upload_open_questions_after_upload(brief: Any, uploaded_file_names: list[str]) -> dict[str, Any]:
    """Drop upload-related open questions and record a single canonical upload marker.

    Earlier behavior marked the matching open question as `answered` with an
    "Uploaded file(s) received: …" answer string and let
    `_promote_answered_open_questions_to_gathered` fold that into a
    "<question> — <answer>" gathered row. That worked for the immediate-feedback
    UX (the OQ vanished right away) but produced a verbose string that
    overlapped with anything the LLM later wrote about the upload, leaving the
    Definition with two near-duplicate rows.

    This now removes the OQ directly and emits one canonical gathered row with
    `id=item-gathered-upload`, `source="upload"`. Legacy upload markers (older
    canonical rows or "Q — A" promotions from the previous behavior) are
    swept on the same turn so prior duplicates get reconciled too.
    """
    normalized = normalize_problem_brief(brief)
    clean_files = [str(name).strip() for name in uploaded_file_names if str(name).strip()]
    if not clean_files:
        return normalized

    next_questions: list[dict[str, Any]] = []
    matched_any_question = False
    for question in normalized.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        if (
            _normalize_question_status(question.get("status")) == "open"
            and upload_satisfies_open_question(question, clean_files)
        ):
            matched_any_question = True
            continue
        next_questions.append(question)

    items_without_upload_marker = [
        deepcopy(item)
        for item in (normalized.get("items") or [])
        if not _is_upload_marker_item(item)
    ]
    had_legacy_marker = len(items_without_upload_marker) != len(normalized.get("items") or [])

    upload_text = _format_upload_marker_text(clean_files)
    items_without_upload_marker.append(
        {
            "id": UPLOAD_MARKER_ITEM_ID,
            "text": upload_text,
            "kind": "gathered",
            "source": "upload",
        }
    )

    if not matched_any_question and not had_legacy_marker and upload_text in {
        str(item.get("text") or "").strip()
        for item in (normalized.get("items") or [])
        if isinstance(item, dict)
    }:
        # Identical marker already present, no upload OQ pending — nothing to do.
        return normalized

    return normalize_problem_brief(
        {**normalized, "items": items_without_upload_marker, "open_questions": next_questions}
    )


_GOAL_TERM_TYPE_VALUES: frozenset[str] = frozenset({"objective", "soft", "hard", "custom"})


def _normalize_property_via_ports(prop_key: str, prop_val: Any) -> tuple[bool, Any] | None:
    """Ask each registered port whether it owns this goal-term property key.

    Returns the first ``(keep, value)`` decision a port supplies, or ``None``
    when no port claims the key. Stays problem-agnostic: this function never
    references VRPTW or knapsack property names directly.
    """
    try:
        from app.problems.registry import iter_study_ports
    except Exception:  # pragma: no cover — defensive
        return None
    for port in iter_study_ports():
        try:
            decision = port.normalize_goal_term_property(prop_key, prop_val)
        except Exception:  # pragma: no cover — defensive
            continue
        if decision is not None:
            return decision
    return None


def _normalize_goal_term_entry(raw: Any) -> dict[str, Any] | None:
    """Tolerant goal-term entry validator. Returns None when no usable weight is present."""
    if not isinstance(raw, dict):
        return None
    weight = raw.get("weight")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        return None
    out: dict[str, Any] = {"weight": float(weight)}
    raw_type = str(raw.get("type") or "").strip().lower()
    out["type"] = raw_type if raw_type in _GOAL_TERM_TYPE_VALUES else "objective"
    if isinstance(raw.get("locked"), bool):
        out["locked"] = bool(raw["locked"])
    rank_raw = raw.get("rank")
    if not isinstance(rank_raw, bool):
        try:
            rank = int(rank_raw)
            if rank > 0:
                out["rank"] = rank
        except (TypeError, ValueError):
            pass
    evidence_raw = raw.get("evidence_item_ids")
    if isinstance(evidence_raw, list):
        evidence_ids: list[str] = []
        seen: set[str] = set()
        for eid in evidence_raw:
            if not isinstance(eid, str):
                continue
            cleaned = eid.strip()
            if not cleaned or cleaned in seen:
                continue
            evidence_ids.append(cleaned)
            seen.add(cleaned)
        if evidence_ids:
            out["evidence_item_ids"] = evidence_ids
    note_raw = raw.get("ambiguity_note")
    if isinstance(note_raw, dict):
        rationale_raw = note_raw.get("chosen_rationale")
        alternatives_raw = note_raw.get("considered_alternatives")
        cleaned_alternatives: list[str] = []
        if isinstance(alternatives_raw, list):
            seen_alts: set[str] = set()
            for alt in alternatives_raw:
                if not isinstance(alt, str):
                    continue
                cleaned_alt = alt.strip()
                if not cleaned_alt or cleaned_alt in seen_alts:
                    continue
                cleaned_alternatives.append(cleaned_alt)
                seen_alts.add(cleaned_alt)
        rationale = (
            rationale_raw.strip() if isinstance(rationale_raw, str) else ""
        )
        if cleaned_alternatives or rationale:
            note_out: dict[str, Any] = {}
            if cleaned_alternatives:
                note_out["considered_alternatives"] = cleaned_alternatives
            if rationale:
                note_out["chosen_rationale"] = rationale
            out["ambiguity_note"] = note_out
    props_raw = raw.get("properties")
    if isinstance(props_raw, dict):
        normalized_props: dict[str, Any] = {}
        for prop_key, prop_val in props_raw.items():
            if not isinstance(prop_key, str):
                continue
            decision = _normalize_property_via_ports(prop_key, prop_val)
            if decision is None:
                # No port owns this property key — pass through unchanged so
                # future problem domains can lean on goal_terms.properties
                # without coordinating with the main backend.
                normalized_props[prop_key] = deepcopy(prop_val)
                continue
            keep, value = decision
            if keep:
                normalized_props[prop_key] = value
        if normalized_props:
            out["properties"] = normalized_props
    return out


def _normalize_goal_terms_map(raw: Any) -> dict[str, dict[str, Any]]:
    """Drop malformed entries silently; keep the rest. Preserves R1 mitigation."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        entry = _normalize_goal_term_entry(value)
        if entry is None:
            continue
        out[key] = entry
    return out


def _merge_goal_term_entry(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge two goal-term entries.

    Top-level fields (weight, type, rank, locked) — patch wins per key.
    `properties` is deep-merged at the property-name level so updating only
    `driver_preferences` does not drop a sibling like `max_shift_hours`.
    Inside `properties`, list values (notably `driver_preferences`) are
    replaced wholesale — rule lists are atomic; partial merges produce
    rule-identity ambiguity we deliberately avoid.
    """
    out = deepcopy(base)
    for key, val in patch.items():
        if key == "properties" and isinstance(val, dict):
            base_props = out.get("properties") if isinstance(out.get("properties"), dict) else {}
            merged_props = deepcopy(base_props)
            for prop_key, prop_val in val.items():
                merged_props[prop_key] = deepcopy(prop_val)
            out["properties"] = merged_props
        else:
            out[key] = deepcopy(val) if isinstance(val, (dict, list)) else val
    return out


def _merge_goal_terms_maps(
    base: dict[str, Any] | None, patch: dict[str, Any] | None
) -> dict[str, dict[str, Any]]:
    """Per-key deep merge of two goal_terms maps."""
    merged: dict[str, dict[str, Any]] = (
        deepcopy(base) if isinstance(base, dict) else {}
    )
    if not isinstance(patch, dict):
        return merged
    for key, entry in patch.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if isinstance(merged.get(key), dict):
            merged[key] = _merge_goal_term_entry(merged[key], entry)
        else:
            merged[key] = deepcopy(entry)
    return merged


def _normalize_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    item_id = str(raw.get("id") or "").strip()
    lowered_text = text.lower()
    if item_id == "config-only-active-terms" or (
        "only active objective terms should be applied" in lowered_text
        or "inactive objective terms may also remain available" in lowered_text
    ):
        return None
    kind = str(raw.get("kind", "assumption")).strip().lower()
    if kind == "system":
        return None
    if kind not in {"gathered", "assumption"}:
        kind = "assumption"
    source = str(raw.get("source", "agent")).strip().lower()
    if source == "system":
        source = "agent"
    if source not in {"user", "upload", "agent"}:
        source = "agent"
    return {
        "id": str(raw.get("id") or _new_item_id(kind)),
        "text": text,
        "kind": kind,
        "source": source,
    }


def normalize_problem_brief(raw: Any) -> dict[str, Any]:
    base = default_problem_brief()
    if not isinstance(raw, dict):
        return base

    goal_summary = _sanitize_goal_summary(raw.get("goal_summary", ""))
    run_summary = _sanitize_run_summary(raw.get("run_summary", ""))
    solver_scope = str(raw.get("solver_scope") or base["solver_scope"]).strip() or base["solver_scope"]
    backend_template = (
        str(raw.get("backend_template") or base["backend_template"]).strip() or base["backend_template"]
    )

    normalized_items: list[dict[str, Any]] = []
    for entry in raw.get("items", []):
        item = _normalize_item(entry)
        if item is None:
            continue
        normalized_items.append(item)
    normalized_items = _reconcile_problem_brief_items(normalized_items)
    questions = _coerce_question_list(raw.get("open_questions"))
    promoted_items, questions = _promote_answered_open_questions_to_gathered(normalized_items, questions)
    promoted_items = _reconcile_problem_brief_items(promoted_items)
    goal_terms = _normalize_goal_terms_map(raw.get("goal_terms"))
    unmodeled_raw = raw.get("unmodeled_requests")
    unmodeled_requests: list[dict[str, Any]] = []
    if isinstance(unmodeled_raw, list):
        seen_texts: set[str] = set()
        for entry in unmodeled_raw:
            normalized = _normalize_unmodeled_request(entry)
            if normalized is None:
                continue
            key = normalized["user_text"].lower()
            if key in seen_texts:
                continue
            seen_texts.add(key)
            unmodeled_requests.append(normalized)
    return {
        "goal_summary": goal_summary,
        "run_summary": run_summary,
        "items": promoted_items,
        "open_questions": questions,
        "goal_terms": goal_terms,
        "unmodeled_requests": unmodeled_requests,
        "topic_engaged": bool(raw.get("topic_engaged")),
        "solver_scope": solver_scope,
        "backend_template": backend_template,
    }


def merge_problem_brief_patch(base_brief: Any, patch: Any) -> dict[str, Any]:
    """Merge partial model brief patches without dropping prior gathered facts."""
    base = normalize_problem_brief(base_brief)
    if not isinstance(patch, dict):
        return base

    merged = deepcopy(base)
    replace_editable_items = bool(patch.get("replace_editable_items"))
    replace_open_questions = bool(patch.get("replace_open_questions"))

    if "goal_summary" in patch:
        raw_goal = patch.get("goal_summary") or ""
        sanitized_goal = _sanitize_goal_summary(raw_goal)
        # Only overwrite when we have a usable sanitized value, OR the model
        # explicitly cleared it (raw was empty/whitespace). If the model wrote a
        # non-empty summary that the sanitizer couldn't keep anything from, retain
        # the prior summary instead of silently wiping it.
        if sanitized_goal or not str(raw_goal).strip():
            merged["goal_summary"] = sanitized_goal
    if "run_summary" in patch:
        merged["run_summary"] = _sanitize_run_summary(patch.get("run_summary") or "")
    # If the model sets replace_open_questions but omits open_questions (common on cleanup
    # turns that only replace items), keep the existing list — do not wipe it.
    if "open_questions" in patch:
        incoming_questions = _coerce_question_list(patch.get("open_questions"))
        extra_gathered, incoming_questions = _split_pseudo_answered_open_questions(incoming_questions)
        if extra_gathered:
            _merge_gathered_deduped(merged["items"], extra_gathered)
        base_questions_by_id = {str(q.get("id", "")): q for q in merged.get("open_questions") or []}
        if replace_open_questions:
            _preserve_answered_state(incoming_questions, base_questions_by_id)
            merged["open_questions"] = incoming_questions
        else:
            existing_questions = _coerce_question_list(merged.get("open_questions"))
            base_by_id = {str(q.get("id", "")): q for q in existing_questions}
            index_by_id: dict[str, int] = {}
            seen = set()
            for index, question in enumerate(existing_questions):
                question_id = str(question.get("id") or "").strip()
                if question_id:
                    index_by_id[question_id] = index
                seen.add(str(question.get("text") or "").strip().lower())
            for question in incoming_questions:
                question_id = str(question.get("id") or "").strip()
                if question_id and question_id in index_by_id:
                    to_merge = [dict(question)]
                    _preserve_answered_state(to_merge, base_by_id)
                    existing_questions[index_by_id[question_id]] = to_merge[0]
                    seen.add(str(question.get("text") or "").strip().lower())
                    continue
                key = str(question.get("text") or "").strip().lower()
                if key in seen:
                    continue
                existing_questions.append(question)
                seen.add(key)
            merged["open_questions"] = existing_questions
    if "solver_scope" in patch:
        merged["solver_scope"] = str(patch.get("solver_scope") or base["solver_scope"]).strip() or base["solver_scope"]
    if "backend_template" in patch:
        merged["backend_template"] = (
            str(patch.get("backend_template") or base["backend_template"]).strip() or base["backend_template"]
        )
    if "goal_terms" in patch:
        # Per-key deep merge — see _merge_goal_term_entry for `properties` semantics.
        # `replace_goal_terms` flag (when set true) replaces the full map instead.
        # Defence against LLM-emitted prose rows that would collide with the
        # synthesizer's id namespace (e.g. `config-driver-pref-*`) is enforced
        # at the JSON-schema layer via `port.all_synthesized_id_prefixes()` —
        # see `_build_problem_brief_item_schema` in `app.services.llm`.
        # Gemini rejects any items[] entry whose id matches a forbidden prefix,
        # so by the time the patch reaches this merge step, the id namespace is
        # already exclusive to the synthesizer.
        if bool(patch.get("replace_goal_terms")):
            merged["goal_terms"] = _normalize_goal_terms_map(patch.get("goal_terms"))
        else:
            normalized_patch = _normalize_goal_terms_map(patch.get("goal_terms"))
            merged["goal_terms"] = _merge_goal_terms_maps(merged.get("goal_terms"), normalized_patch)

    if "unmodeled_requests" in patch:
        # Append-only by default — once a participant request is logged as
        # unmodeled it stays in the audit trail so researchers can review what
        # users wanted that wasn't covered. Dedupe by `user_text` to avoid
        # blowups if the LLM re-emits the same row on a subsequent turn.
        existing_unmodeled = (
            list(merged.get("unmodeled_requests") or [])
            if isinstance(merged.get("unmodeled_requests"), list)
            else []
        )
        seen_unmodeled = {
            str(entry.get("user_text") or "").strip().lower()
            for entry in existing_unmodeled
            if isinstance(entry, dict)
        }
        incoming_unmodeled = patch.get("unmodeled_requests")
        if isinstance(incoming_unmodeled, list):
            for raw in incoming_unmodeled:
                normalized_entry = _normalize_unmodeled_request(raw)
                if normalized_entry is None:
                    continue
                key = normalized_entry["user_text"].lower()
                if key in seen_unmodeled:
                    continue
                seen_unmodeled.add(key)
                existing_unmodeled.append(normalized_entry)
        merged["unmodeled_requests"] = existing_unmodeled

    if replace_editable_items and "items" not in patch:
        merged["items"] = []
        return normalize_problem_brief(merged)
    if "items" in patch and isinstance(patch.get("items"), list):
        incoming_items = [item for raw in patch["items"] if (item := _normalize_item(raw)) is not None]
        if replace_editable_items:
            merged["items"] = list(incoming_items)
            return normalize_problem_brief(merged)
        existing_items = [deepcopy(item) for item in merged["items"] if isinstance(item, dict)]
        result_items: list[dict[str, Any]] = []
        index_by_id: dict[str, int] = {}
        for existing in existing_items:
            existing_id = str(existing.get("id"))
            index_by_id[existing_id] = len(result_items)
            result_items.append(existing)

        seen_identity: set[tuple[str, str]] = {
            (str(item.get("kind")), str(item.get("text")).strip().lower()) for item in result_items
        }
        for incoming in incoming_items:
            incoming_id = str(incoming.get("id"))
            identity = (str(incoming.get("kind")), str(incoming.get("text")).strip().lower())
            if incoming_id in index_by_id:
                result_items[index_by_id[incoming_id]] = incoming
                continue
            if identity in seen_identity:
                continue
            result_items.append(incoming)
            seen_identity.add(identity)

        merged["items"] = result_items

    # Topic-warmth is a one-way sticky flag. The brief-update LLM emits
    # ``topic_engaged_next: true`` once it judges the conversation has arrived
    # at the problem-module's topic; we OR-fold into the persisted flag.
    # ``false`` is never honored — once warm, the system stays warm so a
    # later off-topic detour doesn't re-leak the cold-start sandbox guard.
    incoming_warmth = patch.get("topic_engaged_next")
    if isinstance(incoming_warmth, bool) and incoming_warmth:
        merged["topic_engaged"] = True

    return normalize_problem_brief(merged)


_WATERFALL_ASSUMPTION_QUESTION_PREFIX = "Confirm or correct: "


def coerce_problem_brief_for_workflow(brief: Any, workflow_mode: str | None) -> dict[str, Any]:
    """
    Enforce workflow-specific invariants at persistence boundaries.

    Waterfall invariant: do not store `kind: "assumption"` rows. Convert them
    into `open_questions` (with the "Confirm or correct: …" prefix) so
    uncertainty is explicitly tracked and gated.

    Demo invariant: also strips `kind: "assumption"` rows, but **drops them
    silently** rather than converting to an OQ. Two reasons:
      - The "Confirm or correct: …" framing reads like a foregone conclusion,
        which is exactly the assumption-flavored UI the user is trying to
        avoid in demo recordings.
      - The chat prompt requires a proper open question for tunable defaults
        (algorithm choice, etc.) to already exist when the agent commits to
        one. If the agent slips and emits an assumption alongside or instead,
        the working value is still on the panel and any proper OQ remains —
        the silent drop just removes the stray row.

    Agile is unaffected — assumptions are first-class there.
    """
    normalized = normalize_problem_brief(brief)
    mode = str(workflow_mode or "").strip().lower()
    if mode not in {"waterfall", "demo"}:
        return normalized

    items = list(normalized.get("items") or [])
    open_questions = list(normalized.get("open_questions") or [])
    convert_to_oq = mode == "waterfall"

    # Track existing OQ texts (case-insensitive, whitespace-collapsed) so
    # that converting a fresh assumption with new id but identical text to
    # one already coerced earlier doesn't duplicate the OQ. Without this
    # dedupe, every chat turn that re-states the same agent-side assumption
    # (with a freshly generated item id) leaves another "Confirm or
    # correct: …" OQ behind.
    def _norm_oq_text(s: Any) -> str:
        return " ".join(str(s or "").strip().lower().split())

    seen_oq_texts: set[str] = {
        _norm_oq_text(q.get("text"))
        for q in open_questions
        if isinstance(q, dict)
    }

    next_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind != "assumption":
            next_items.append(item)
            continue

        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if convert_to_oq:
            new_text = f"{_WATERFALL_ASSUMPTION_QUESTION_PREFIX}{text}"
            normalized_new_text = _norm_oq_text(new_text)
            if normalized_new_text in seen_oq_texts:
                # Already represented by an existing OQ (likely from a prior
                # turn that coerced an earlier assumption with the same
                # underlying text but a different id). Drop the duplicate.
                continue
            open_questions.append(
                {
                    "id": f"question-open-from-assumption-{str(item.get('id') or '').strip() or _compact_uid()}",
                    "text": new_text,
                    "status": "open",
                    "answer_text": None,
                }
            )
            seen_oq_texts.add(normalized_new_text)
        # Demo: silently drop. Agent's prompt rule already requires a proper
        # OQ-with-choices to be emitted for tunable defaults; the panel keeps
        # the working value, so the run still works.

    return {**normalized, "items": next_items, "open_questions": open_questions}


def sync_problem_brief_from_panel(
    base_brief: Any, panel_config: Any, test_problem_id: str | None = None
) -> dict[str, Any]:
    """Mirror saved config choices back into the editable problem brief.

    Provenance preservation: when an existing brief row already populates a config
    slot as `kind: "assumption"`, the panel-derived row inherits that assumption
    kind/source. Without this, an agent's proposed assumption would be silently
    promoted to `kind: "gathered"` on every panel round-trip, erasing the
    distinction between agent-proposed defaults and participant-confirmed facts.
    """
    base = normalize_problem_brief(base_brief)
    merged = deepcopy(base)

    existing_slot_provenance: dict[str, tuple[str, str]] = {}
    for item in merged["items"]:
        if not isinstance(item, dict):
            continue
        slot = _problem_brief_item_slot(item, test_problem_id=test_problem_id)
        if slot is None:
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in {"gathered", "assumption"}:
            continue
        source = str(item.get("source") or "").strip().lower()
        existing_slot_provenance[slot] = (kind, source)

    panel_items = _brief_items_from_panel(panel_config, test_problem_id=test_problem_id)
    for item in panel_items:
        slot = _problem_brief_item_slot(item, test_problem_id=test_problem_id)
        if slot is None:
            continue
        prev = existing_slot_provenance.get(slot)
        if prev is None or prev[0] != "assumption":
            continue
        prev_source = prev[1] if prev[1] in {"user", "upload", "agent"} else "agent"
        item["kind"] = "assumption"
        item["source"] = prev_source

    panel_slots = {
        slot
        for item in panel_items
        if (slot := _problem_brief_item_slot(item, test_problem_id=test_problem_id)) is not None
    }
    merged["items"] = [
        deepcopy(item)
        for item in merged["items"]
        if isinstance(item, dict)
        and not str(item.get("id") or "").startswith(CONFIG_ITEM_PREFIX)
        and _problem_brief_item_slot(item, test_problem_id=test_problem_id) not in panel_slots
    ]
    merged["items"].extend(panel_items)

    # Mirror the panel's structured `goal_terms` map (canonical solver-config
    # storage on the panel side) into the brief verbatim. This makes manual
    # UI-side edits — like adding a driver_preferences rule — first-class
    # brief data without going through prose. The brief's `goal_terms` is
    # the structured source of truth; the prose `config-weight-*` items
    # above remain for participant-facing display.
    panel_goal_terms = _panel_goal_terms(panel_config)
    if panel_goal_terms is not None:
        prior_goal_terms = base.get("goal_terms")
        if not isinstance(prior_goal_terms, dict):
            prior_goal_terms = {}
        removed_keys = {
            key for key in prior_goal_terms.keys() if key not in panel_goal_terms
        }
        if removed_keys and test_problem_id is not None:
            try:
                from app.problems.registry import get_study_port

                port = get_study_port(test_problem_id)
                strip_ids = port.brief_item_ids_to_strip_on_goal_term_removal(
                    removed_keys=removed_keys,
                    prior_goal_terms=prior_goal_terms,
                    brief_items=list(merged.get("items") or []),
                )
            except Exception:  # pragma: no cover — defensive, never block the sync
                strip_ids = set()
            if strip_ids:
                merged["items"] = [
                    item
                    for item in merged["items"]
                    if not (
                        isinstance(item, dict)
                        and str(item.get("id") or "") in strip_ids
                    )
                ]
        merged["goal_terms"] = panel_goal_terms

    return normalize_problem_brief(merged)


def _panel_goal_terms(panel_config: Any) -> dict[str, Any] | None:
    """Extract `panel.problem.goal_terms` as a dict, or None when absent."""
    if not isinstance(panel_config, dict):
        return None
    problem = panel_config.get("problem") if isinstance(panel_config.get("problem"), dict) else panel_config
    if not isinstance(problem, dict):
        return None
    goal_terms = problem.get("goal_terms")
    if not isinstance(goal_terms, dict):
        return None
    return deepcopy(goal_terms)


def _detect_algorithm_text(text: str) -> str | None:
    lowered = text.lower()
    if "swarmsa" in lowered or "swarm sa" in lowered or "swarm-based simulated annealing" in lowered:
        return "SwarmSA"
    if "particle swarm" in lowered or re.search(r"\bpso\b", lowered):
        return "PSO"
    if "genetic algorithm" in lowered or re.search(r"\bga\b", lowered):
        return "GA"
    if "simulated annealing" in lowered or re.search(r"\bsa\b", lowered):
        return "SA"
    if "ant colony" in lowered or re.search(r"\bacor\b", lowered):
        return "ACOR"
    return None


def _config_item(item_id: str, text: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "text": text,
        "kind": "gathered",
        "source": "agent",
    }


def _weight_item_text(
    label: str,
    value: float,
    constraint_type: str | None,
    rationale: str | None = None,
) -> str:
    """Render the synthesized ``config-weight-<key>`` row text.

    Format: ``"<Label> (<role>, weight N) <rationale>."``. When the port
    didn't supply a rationale phrase, fall back to the bare
    ``"<Label> is a <role> term (weight N)."`` form so the brief still
    carries the key fact even on ports that haven't populated
    ``goal_term_rationales``.
    """
    ctype = (constraint_type or "").strip().lower()
    if ctype in ("hard", "soft"):
        role = f"{ctype} constraint"
    elif ctype == "custom":
        role = "custom locked"
    else:
        role = "primary objective"
    rationale_clause = (rationale or "").strip()
    if rationale_clause:
        return f"{label} ({role}, weight {value}) {rationale_clause}."
    if ctype == "custom":
        return f"{label} uses a custom locked value (weight {value})."
    return f"{label} is a {role} term (weight {value})."


def _problem_brief_item_slot(
    item: dict[str, Any], test_problem_id: str | None = None
) -> str | None:
    # Port-specific slots take precedence so problem-only id prefixes (e.g.
    # VRPTW's `config-driver-pref-*`, `config-shift-hard-penalty`) and any
    # legacy-id renames are recognised before the neutral fallback. When the
    # caller doesn't know the active session's test_problem_id (e.g. inside
    # `normalize_problem_brief`), iterate all registered ports — the main
    # backend stays problem-agnostic and the first port to recognise the
    # item wins.
    try:
        from app.problems.registry import get_study_port, iter_study_ports

        ports_to_try = (
            [get_study_port(test_problem_id)]
            if test_problem_id is not None
            else iter_study_ports()
        )
    except Exception:  # pragma: no cover — defensive
        ports_to_try = []
    for port in ports_to_try:
        try:
            port_slot = port.problem_brief_item_slot(item)
        except Exception:  # pragma: no cover — defensive
            continue
        if port_slot is not None:
            return port_slot
    item_id = str(item.get("id") or "")
    slot = _slot_from_item_id(item_id)
    if slot is not None:
        return slot
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    return _slot_from_text(text)


def problem_brief_item_slot(
    item: dict[str, Any], test_problem_id: str | None = None
) -> str | None:
    """Public wrapper for slot detection used by session-merge guards."""
    return _problem_brief_item_slot(item, test_problem_id=test_problem_id)


def _slot_from_item_id(item_id: str) -> str | None:
    """Neutral (problem-agnostic) slot detection from an item id.

    Problem-specific id prefixes are handled via
    ``StudyProblemPort.problem_brief_item_slot``; this function handles only
    the shared scaffolding ids (search strategy, algorithm, epochs,
    pop_size, only_active_terms, generic ``config-weight-*``,
    ``config-algorithm-param-*``).
    """
    if item_id == "config-search-strategy":
        return "search_strategy"
    if item_id == "config-algorithm":
        return "algorithm"
    if item_id == "config-epochs":
        return "epochs"
    if item_id == "config-pop-size":
        return "pop_size"
    if item_id == "config-only-active-terms":
        return "only_active_terms"
    if item_id.startswith("config-weight-"):
        return f"weight:{item_id.removeprefix('config-weight-')}"
    if item_id.startswith("config-algorithm-param-"):
        return f"algorithm_param:{item_id.removeprefix('config-algorithm-param-')}"
    # Goal-term validator rows surface the agent's inference for a
    # ``goal_terms`` key that lacks a backing items[] row. They share the
    # same slot as ``config-weight-{key}`` so the reconciler keeps only the
    # later (more specific) one when both exist. Once the panel-sync
    # synthesises ``config-weight-{key}`` with concrete weight + type, the
    # vague validator row is redundant and gets dropped.
    if item_id.startswith("item-validator-"):
        return f"weight:{item_id.removeprefix('item-validator-')}"
    return None


def _slot_from_text(text: str) -> str | None:
    lowered = text.lower()
    if lowered.startswith("search strategy:"):
        return "search_strategy"
    algorithm_param_match = _ALGORITHM_PARAM_RE.search(text)
    if algorithm_param_match:
        return f"algorithm_param:{algorithm_param_match.group(1)}"
    if _detect_algorithm_text(text):
        return "algorithm"
    if ("population size" in lowered or "swarm size" in lowered) and _EXPLICIT_VALUE_RE.search(text):
        return "pop_size"
    if any(marker in lowered for marker in ("epoch", "epochs", "iteration", "iterations")) and _EXPLICIT_VALUE_RE.search(text):
        return "epochs"
    if "only active objective terms should be applied" in lowered or "inactive objective terms may also remain available" in lowered:
        return "only_active_terms"
    return None


def _reconcile_problem_brief_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_index_by_slot: dict[str, int] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        slot = _problem_brief_item_slot(item)
        if slot is not None:
            last_index_by_slot[slot] = index

    reconciled: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        slot = _problem_brief_item_slot(item)
        if slot is not None and last_index_by_slot.get(slot) != index:
            continue
        reconciled.append(item)
    return reconciled


def _numeric_field(d: dict[str, Any], key: str) -> int | float | None:
    v = d.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _weights_and_types_from_problem(
    problem: dict[str, Any],
) -> tuple[dict[str, float], dict[str, str]]:
    """Pull (weights, constraint_types) from a panel `problem` block.

    Prefers the canonical `goal_terms` map (post-sanitize storage); falls
    back to the legacy top-level `weights` / `constraint_types` fields when
    `goal_terms` is absent. On conflict, `goal_terms` wins — this enforces
    the R4 "structured-wins" rule documented in the plan.
    """
    weights: dict[str, float] = {}
    constraint_types: dict[str, str] = {}

    goal_terms = problem.get("goal_terms")
    if isinstance(goal_terms, dict):
        for key, entry in goal_terms.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            weight_val = entry.get("weight")
            if isinstance(weight_val, bool) or not isinstance(weight_val, (int, float)):
                continue
            weights[key] = float(weight_val)
            term_type = str(entry.get("type") or "").strip().lower()
            if term_type in _GOAL_TERM_TYPE_VALUES:
                constraint_types[key] = term_type

    if not weights:
        legacy_weights = problem.get("weights")
        if isinstance(legacy_weights, dict):
            for key, value in legacy_weights.items():
                if not isinstance(key, str):
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                weights[key] = float(value)
        legacy_types = problem.get("constraint_types")
        if isinstance(legacy_types, dict):
            for key, value in legacy_types.items():
                if isinstance(key, str) and isinstance(value, str):
                    lowered = value.strip().lower()
                    if lowered in _GOAL_TERM_TYPE_VALUES:
                        constraint_types[key] = lowered

    return weights, constraint_types


def _brief_items_from_panel(panel_config: Any, test_problem_id: str | None = None) -> list[dict[str, Any]]:
    from app.algorithm_catalog import (
        DEFAULT_ALGORITHM_PARAMS,
        DEFAULT_EPOCHS,
        DEFAULT_POP_SIZE,
        allowed_param_keys,
        canonical_algorithm_stored,
        param_value_is_default,
    )

    if not isinstance(panel_config, dict):
        return []

    problem = panel_config.get("problem") if isinstance(panel_config.get("problem"), dict) else panel_config
    if not isinstance(problem, dict):
        return []

    from app.problems.registry import get_study_port

    port = get_study_port(test_problem_id)
    weight_labels = port.weight_item_labels()
    try:
        weight_rationales = port.goal_term_rationales()
        if not isinstance(weight_rationales, dict):
            weight_rationales = {}
    except Exception:  # pragma: no cover — defensive
        weight_rationales = {}
    items: list[dict[str, Any]] = []

    algorithm = str(problem.get("algorithm") or "").strip()
    epochs = problem.get("epochs")
    if epochs is None:
        epochs = DEFAULT_EPOCHS
    pop_size = problem.get("pop_size")
    if pop_size is None:
        pop_size = DEFAULT_POP_SIZE

    # `only_active_terms` is a researcher-controlled switch (set on the panel JSON),
    # not a participant-facing fact. It is intentionally NOT mirrored into the brief
    # so it never surfaces in the definition panel or the chat payload to the model.

    # Read weights and constraint types from `goal_terms` first — that's the
    # canonical solver-config storage on the panel side after sanitization.
    # Fall back to legacy top-level `weights` / `constraint_types` (for
    # unsanitized / legacy panels and tests). On conflict, goal_terms wins.
    weights, constraint_types = _weights_and_types_from_problem(problem)
    if weights:
        for key in sorted(weights):
            value = weights[key]
            label = weight_labels.get(str(key), str(key).replace("_", " ").capitalize())
            ctype = constraint_types.get(str(key)) if isinstance(constraint_types, dict) else None
            rationale = weight_rationales.get(str(key)) if isinstance(weight_rationales, dict) else None
            items.append(
                _config_item(
                    f"config-weight-{key}",
                    _weight_item_text(
                        label,
                        float(value),
                        str(ctype) if isinstance(ctype, str) else None,
                        rationale=str(rationale).strip() if isinstance(rationale, str) else None,
                    ),
                )
            )

    algorithm_params = problem.get("algorithm_params")
    algo_key = canonical_algorithm_stored(algorithm) if algorithm else None
    allowed_ap = allowed_param_keys(algo_key) if algo_key else frozenset()
    strategy_details: list[str] = []
    if isinstance(epochs, (int, float)) and not isinstance(epochs, bool):
        strategy_details.append(f"max iterations {epochs}")
    if isinstance(pop_size, (int, float)) and not isinstance(pop_size, bool):
        strategy_details.append(f"population size {pop_size}")
    if isinstance(algorithm_params, dict) and allowed_ap:
        for key in sorted(algorithm_params):
            if key not in allowed_ap:
                continue
            value = algorithm_params.get(key)
            if algo_key and param_value_is_default(algo_key, key, value):
                continue
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, (int, float)):
                rendered = str(value)
            elif isinstance(value, str) and value.strip():
                rendered = value.strip()
            else:
                continue
            strategy_details.append(f"{key}={rendered}")

    # Search-strategy extras (not algorithm_params): keep in the same gathered line so brief→panel
    # seeding and chat context retain greedy init / early-stop / seed settings across sync.
    if isinstance(problem.get("use_greedy_init"), bool):
        strategy_details.append(
            "greedy initialization on" if problem["use_greedy_init"] else "greedy initialization off"
        )
    if isinstance(problem.get("early_stop"), bool):
        strategy_details.append(
            "stop early on plateau on" if problem["early_stop"] else "stop early on plateau off"
        )
    if (esp := _numeric_field(problem, "early_stop_patience")) is not None:
        strategy_details.append(f"plateau patience {int(esp)}")
    if (ese := _numeric_field(problem, "early_stop_epsilon")) is not None:
        strategy_details.append(f"min improvement epsilon {float(ese):g}")
    if (rs := _numeric_field(problem, "random_seed")) is not None:
        strategy_details.append(f"random seed {int(rs)}")

    if algorithm and strategy_details:
        items.append(
            _config_item(
                "config-search-strategy",
                f"Search strategy: {algorithm} ({', '.join(strategy_details)}).",
            )
        )

    # Per-port prose synthesis from goal_terms (e.g. VRPTW renders one
    # `config-driver-pref-*` row per driver_preference rule). Reads from the
    # canonical `goal_terms` map only — never from prose.
    goal_terms = problem.get("goal_terms")
    if isinstance(goal_terms, dict) and goal_terms:
        try:
            extras = get_study_port(test_problem_id).synthesize_brief_items_from_goal_terms(
                goal_terms
            )
        except AttributeError:
            extras = []
        for extra in extras:
            if isinstance(extra, dict) and str(extra.get("id") or "").strip():
                items.append(extra)

    return items
