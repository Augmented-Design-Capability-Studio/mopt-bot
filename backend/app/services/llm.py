"""Server-side Gemini via google-genai: use Chat API (chats.create + send_message), not raw generate_content."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from app.problem_brief import (
    is_chat_cold_start,
    current_weights_prompt_section,
    locked_goal_terms_prompt_section,
    surface_problem_brief_for_chat_prompt,
)
from app.algorithm_catalog import STUDY_ENABLED_ALGORITHM_NAMES
from app.problems.registry import get_study_port
from app.problems.schema_shared import goal_terms_schema

from app.prompts.study_chat import (
    STUDY_CHAT_AMBIGUITY_DISCIPLINE,
    STUDY_CHAT_BRIEF_UPDATE_TASK,
    STUDY_CHAT_CHANGE_ACK_CHECK_TASK,
    STUDY_CHAT_GROUNDING_DISCIPLINE,
    STUDY_CHAT_HARD_CONSTRAINT_DISCIPLINE,
    STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
    STUDY_CHAT_ITEMS_DISCIPLINE,
    STUDY_CHAT_OQ_CLASSIFY_TASK,
    STUDY_CHAT_OUT_OF_SCOPE_DISCIPLINE,
    STUDY_CHAT_SANDBOX_RULES,
    STUDY_CHAT_SEARCH_STRATEGY_ANCHORING,
    STUDY_CHAT_SYSTEM_PROMPT,
    STUDY_CHAT_SYSTEM_PROMPT_WARM,
    STUDY_CHAT_USER_ALGORITHM_CHOICE_TASK,
    STUDY_CHAT_VISIBLE_REPLY_TASK,
    STUDY_CHAT_VISUALIZATION_GUIDANCE,
    STUDY_CHAT_WORKFLOW_AGILE,
    STUDY_CHAT_WORKFLOW_DEMO,
    STUDY_CHAT_WORKFLOW_WATERFALL,
    STUDY_CHAT_RUN_ACK_AGILE,
    STUDY_CHAT_RUN_ACK_BASE,
    STUDY_CHAT_RUN_ACK_DEMO,
    STUDY_CHAT_RUN_ACK_WATERFALL,
    sandbox_rules_relevant,
    visualization_guidance_relevant,
)
from app.schemas import (
    OpenQuestionClassification,
    OpenQuestionClassifierInput,
    OpenQuestionClassifierTurn,
)
from app.services.capabilities import build_capabilities_block
from app.services.chat_context_policy import (
    ChatContextProfile,
    ContextTemperature,
    build_execution_mode_block,
    build_temperature_guardrails_block,
    resolve_context_profile,
)
from app.services.docs_index import search_reference_excerpts

log = logging.getLogger(__name__)


# --- Gemini explicit context caching ------------------------------------------------
# Keyed registry of cached system instructions. The Gemini explicit-cache API has model-
# and size-dependent minimums (e.g. some flash variants reject content under ~1k tokens),
# so creation may fail on previews — we treat caching as best-effort and fall back to
# inline ``system_instruction`` whenever the cache cannot be created or has expired.
_CACHE_TTL_SECONDS = 300

# (cache_key) -> (cache_resource_name, expiry_unix_seconds)
_PROMPT_CACHE_REGISTRY: dict[tuple[Any, ...], tuple[str, float]] = {}
# Cache keys we've already failed to create — don't keep retrying on every turn.
_PROMPT_CACHE_BLOCKLIST: set[tuple[Any, ...]] = set()


def _get_or_create_system_cache(
    client: "genai.Client",
    *,
    model_name: str,
    system_text: str,
    cache_key: tuple[Any, ...],
) -> str | None:
    """Return a cached-content resource name for ``system_text``, or ``None`` to fall back.

    Best-effort: any SDK error (size below minimum, unsupported model, transient
    failure) results in ``None`` and the caller should pass ``system_instruction``
    inline. Successful creates are remembered for ``_CACHE_TTL_SECONDS``.
    """
    import time

    if cache_key in _PROMPT_CACHE_BLOCKLIST:
        return None
    now = time.time()
    entry = _PROMPT_CACHE_REGISTRY.get(cache_key)
    if entry is not None:
        name, expires_at = entry
        if now < expires_at - 10:  # refresh slightly before TTL to avoid edge misses
            return name
        _PROMPT_CACHE_REGISTRY.pop(cache_key, None)
    try:
        cache = client.caches.create(
            model=model_name,
            config=types.CreateCachedContentConfig(
                system_instruction=system_text,
                ttl=f"{_CACHE_TTL_SECONDS}s",
            ),
        )
    except Exception as exc:
        log.info(
            "Gemini explicit-cache create failed for key=%s (%s); falling back to inline system_instruction",
            cache_key,
            exc,
        )
        _PROMPT_CACHE_BLOCKLIST.add(cache_key)
        return None
    name = getattr(cache, "name", None)
    if not name:
        _PROMPT_CACHE_BLOCKLIST.add(cache_key)
        return None
    _PROMPT_CACHE_REGISTRY[cache_key] = (name, now + _CACHE_TTL_SECONDS)
    return name


# Default panel schema follows the default study benchmark (``test_problem_id`` default ``vrptw``).
CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA: dict[str, Any] = get_study_port(None).panel_patch_response_json_schema()


def _study_benchmark_appendix(test_problem_id: str | None) -> str | None:
    blob = get_study_port(test_problem_id).study_prompt_appendix()
    if not blob or not str(blob).strip():
        return None
    return str(blob).strip()

_PROBLEM_BRIEF_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": ["gathered", "assumption"]},
        "source": {"type": "string", "enum": ["user", "upload", "agent"]},
    },
    "required": ["id", "text", "kind", "source"],
}


def _escape_regex_literal(raw: str) -> str:
    """Escape regex metacharacters for use inside a negative lookahead literal."""
    metas = r".^$*+?{}[]\|()/"
    out: list[str] = []
    for ch in raw:
        if ch in metas:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _build_problem_brief_item_schema(
    forbidden_id_prefixes: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Item schema with an optional id-prefix forbid (reserves the synthesizer
    namespace, e.g. VRPTW's ``config-driver-pref-*``).

    JSON Schema ``pattern`` is matched against the entire string by Gemini's
    structured output. A negative-lookahead anchor (``^(?!…)``) rejects ids
    that start with any forbidden prefix while accepting everything else.
    """
    item_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "text": {"type": "string"},
            "kind": {"type": "string", "enum": ["gathered", "assumption"]},
            "source": {"type": "string", "enum": ["user", "upload", "agent"]},
            "goal_key": {
                "type": "string",
                "description": (
                    "Optional. Canonical goal_term key (e.g. `travel_time`, "
                    "`capacity_penalty`) when this row anchors to that "
                    "goal_term. Two server-side consumers act on it: "
                    "(1) **Lifecycle** — on `kind: \"assumption\"` rows, the "
                    "resolver drops the row once `K` has user-gathered "
                    "evidence in the brief. (2) **Display** — on rows whose "
                    "text follows `<Label> (<role>, weight N) — <rationale>`, "
                    "the server keeps the parenthesized middle in sync with "
                    "live `goal_terms[K].{type, weight}`, so just write the "
                    "rationale honestly and the numbers will stay current. "
                    "Both behaviors compose; set the field whenever either "
                    "applies. Omit on qualitative rows that don't anchor "
                    "to a specific goal_term."
                ),
            },
        },
        "required": ["id", "text", "kind", "source"],
    }
    prefixes = sorted(
        p for p in (forbidden_id_prefixes or ()) if isinstance(p, str) and p
    )
    if prefixes:
        lookaheads = "".join(f"(?!{_escape_regex_literal(p)})" for p in prefixes)
        item_schema["properties"]["id"] = {
            "type": "string",
            "pattern": f"^{lookaheads}.*",
            "description": (
                "Items[].id reserves a synthesizer namespace — do NOT start "
                "the id with any of these auto-generated prefixes: "
                f"{', '.join(prefixes)}. Pick a fresh id outside these prefixes."
            ),
        }
    return item_schema


_PROBLEM_BRIEF_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "topic": {
            "type": "string",
            "enum": ["upload", "primary_goal", "search_strategy", "other"],
            "description": (
                "Required classifier. Set to one of `upload`, `primary_goal`, "
                "or `search_strategy` ONLY if your question targets that "
                "foundational topic — those topics are server-managed and any "
                "OQ tagged with them is dropped at merge time (the server "
                "surfaces and removes its own canonical row). For every other "
                "clarifying question (driver count, shift length, term "
                "meaning, etc.) set `other`. Always populated; never null."
            ),
        },
        "goal_key": {
            "type": "string",
            "description": (
                "Optional. Canonical goal_term key (e.g. `capacity_penalty`, "
                "`lateness_penalty`) when this OQ proposes adding or tuning "
                "that specific term — common for *\"Should I add a capacity "
                "penalty?\"*-style post-run asks. The server resolves the "
                "OQ automatically once `K` lands in `brief.goal_terms` (or "
                "the user edits its weight/type/rank via the panel), so you "
                "don't have to remember to drop it via "
                "`replace_open_questions=true`. Omit for scenario "
                "clarifications that don't propose a specific goal_term, "
                "and for foundational-topic OQs (those use the server "
                "monitor state machine instead). Same vocabulary as "
                "`ProblemBriefItem.goal_key`."
            ),
        },
    },
    "required": ["id", "text", "topic"],
}

_PROBLEM_BRIEF_UNMODELED_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Log of a participant request that does not map to any defined goal-term "
        "key and is not a hard constraint already enforced by the encoding. "
        "Emit one entry per genuinely-unmodeled request — used by researchers "
        "to triage what users wanted that the study didn't cover. Append-only "
        "on merge: never re-emit existing rows."
    ),
    "properties": {
        "user_text": {
            "type": "string",
            "description": (
                "Short quote of what the participant asked for, in their words "
                "(e.g. 'penalty for driving during 7-9am peak hours')."
            ),
        },
        "closest_match": {
            "type": "string",
            "description": (
                "Optional: the closest supported alias key, if any (e.g. "
                "'travel_time'). Use null/omit when nothing in the table is a "
                "reasonable proxy."
            ),
        },
        "rationale": {
            "type": "string",
            "description": (
                "One sentence explaining why this is unmodeled — preferably "
                "grounded in the problem docs (e.g. 'task uniqueness is "
                "enforced by the routing encoding, not weighted')."
            ),
        },
    },
    "required": ["user_text"],
    "additionalProperties": False,
}


def _build_problem_brief_patch_schema(
    goal_terms_subschema: dict[str, Any],
    forbidden_id_prefixes: frozenset[str] | None = None,
) -> dict[str, Any]:
    item_schema = _build_problem_brief_item_schema(forbidden_id_prefixes)
    return {
        "type": "object",
        "properties": {
            "goal_summary": {"type": "string"},
            # ``runs`` is server-managed (filled by ``derivation.consolidate_runs``
            # on every run-ack). The LLM never writes here — anything it emits
            # would be overwritten by the normalizer on the next pass.
            "items": {"type": "array", "items": item_schema},
            "open_questions": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "string"},
                        _PROBLEM_BRIEF_QUESTION_SCHEMA,
                    ]
                },
            },
            "goal_terms": goal_terms_subschema,
            "replace_goal_terms": {"type": "boolean"},
            "unmodeled_requests": {
                "type": "array",
                "items": _PROBLEM_BRIEF_UNMODELED_REQUEST_SCHEMA,
            },
            "topic_engaged_next": {
                "type": "boolean",
                "description": (
                    "Set to true ONCE this turn's conversation arrives at the "
                    "problem-module's topic (participant describes their "
                    "optimization problem, names domain entities, asks what's "
                    "being optimized, refers to uploaded domain data, etc.). "
                    "One-way sticky: omit / leave false on small-talk or "
                    "off-topic turns; never emit false to downgrade. The "
                    "merge OR-folds true into the brief's persisted "
                    "topic_engaged flag, which gates whether the next system "
                    "prompt exposes benchmark-specific vocabulary."
                ),
            },
            "solver_scope": {"type": "string"},
            "backend_template": {"type": "string"},
        },
    }


OQ_CLASSIFIER_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "OpenQuestionClassifierTurn",
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "bucket": {
                        "type": "string",
                        "enum": ["gathered", "assumption", "new_open_question"],
                    },
                    "rephrased_text": {"type": "string"},
                    "assumption_text": {"type": "string"},
                    "new_question_text": {"type": "string"},
                    "goal_term_proposal": {
                        "type": "object",
                        "description": (
                            "Optional. When the answer concretely endorses a "
                            "benchmark goal-term concept (per the per-problem "
                            "vocabulary in the system prompt), emit the matching "
                            "canonical key plus its constraint type so the brief "
                            "→ panel sync can attach a weight. Omit when the "
                            "answer is not a goal-term endorsement (e.g. setting "
                            "an algorithm, a numeric threshold, or a free-text "
                            "constraint description)."
                        ),
                        "properties": {
                            "key": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["objective", "soft", "hard", "custom"],
                            },
                        },
                        "required": ["key", "type"],
                    },
                },
                "required": ["question_id", "bucket"],
            },
        },
    },
    "required": ["classifications"],
}


CHAT_TEMPERATURE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "ChatTemperatureClassification",
    "type": "object",
    "properties": {
        "temperature": {"type": "string", "enum": ["cold", "warm", "hot"]},
    },
    "required": ["temperature"],
}

def _history_to_contents(history_lines: list[tuple[str, str]]) -> list[types.Content]:
    """Map DB roles user/assistant to Gemini user/model Content turns."""
    out: list[types.Content] = []
    for role, text in history_lines:
        if not text.strip():
            continue
        r = "user" if role == "user" else "model"
        out.append(types.Content(role=r, parts=[types.Part(text=text)]))
    return out


def _workflow_prompt(workflow_mode: str) -> str:
    if workflow_mode == "agile":
        return STUDY_CHAT_WORKFLOW_AGILE
    if workflow_mode == "demo":
        return STUDY_CHAT_WORKFLOW_DEMO
    return STUDY_CHAT_WORKFLOW_WATERFALL


def _gate_status_prompt_block(gate_status: dict[str, Any] | None) -> str | None:
    """Render the structured run-gate snapshot for prompt injection.

    The dict comes from :func:`app.optimization_gate.gate_status` and carries
    deterministic flags (``goal_term_present``, ``search_strategy_present``,
    ``open_questions_pending``, ``gate_engaged``, ``ready_to_run``,
    ``missing``). Prompts read these flags by name to decide whether to ask
    about a missing prerequisite (waterfall) or fait-accompli a default
    (agile). No NL parsing — the values are produced from saved panel /
    brief state, not from chat text.
    """
    if not isinstance(gate_status, dict) or not gate_status:
        return None
    blob = json.dumps(gate_status, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "## Run-gate status (machine-readable; reflects saved panel + brief)\n"
        "Use these flags to decide what the next reply must do. ``missing`` is\n"
        "ordered by waterfall elicitation phase (goal_term → search_strategy →\n"
        "open_questions → gate_engaged); pop the head and address it. In\n"
        "agile, ``search_strategy`` missing is a fait-accompli cue (assume a\n"
        "default and announce); in waterfall it is an ask cue (ask in chat\n"
        "AND record an open_questions row).\n"
        f"```json\n{blob}\n```"
    )


def _run_ack_prompt(workflow_mode: str) -> str:
    if workflow_mode == "agile":
        wf_addendum = STUDY_CHAT_RUN_ACK_AGILE
    elif workflow_mode == "demo":
        wf_addendum = STUDY_CHAT_RUN_ACK_DEMO
    else:
        wf_addendum = STUDY_CHAT_RUN_ACK_WATERFALL
    return f"{STUDY_CHAT_RUN_ACK_BASE}\n{wf_addendum}"


CHANGE_ACK_CHECK_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "unacknowledged_indices": {
            "type": "array",
            "items": {"type": "integer"},
        },
    },
    "required": ["unacknowledged_indices"],
}


USER_ALGORITHM_CHOICE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "algorithm": {
            "type": "string",
            # Study-enabled methods only (+ "none"); disabled methods like
            # SwarmSA are intentionally not selectable. See algorithm_catalog.
            "enum": [*STUDY_ENABLED_ALGORITHM_NAMES, "none"],
        },
    },
    "required": ["algorithm"],
}


def classify_user_search_strategy_choice(
    *,
    user_text: str,
    api_key: str | None,
    model_name: str | None,
    agent_prompt: str | None = None,
) -> str | None:
    """Return the canonical algorithm the PARTICIPANT settled on, or ``None``.

    Reads the participant's own message — not the main-turn model's patch — so a
    chat answer authorizes the same way a panel answer does, regardless of how
    the main-turn model phrased its output.

    ``agent_prompt`` is the agent's immediately-preceding visible message (what
    the participant is replying to). When supplied, the classifier can resolve a
    bare AFFIRMATION: the agent proposes a method ("how does GA sound?") and the
    participant replies "sounds good" — the choice is GA even though their own
    words name nothing (P_0602). Without it, only a method the participant names
    themselves counts. Closed-vocabulary structured output (no regex / keyword
    matching in code). Fail-safe: ``None`` on any error or missing key.
    """
    if not api_key or not model_name or not str(user_text or "").strip():
        return None
    # Frame as a 2-line transcript so the affirmation rule has the agent's
    # proposal to bind to; agent-less form stays a plain participant message.
    if str(agent_prompt or "").strip():
        contents = f"Agent: {str(agent_prompt).strip()}\nParticipant: {str(user_text).strip()}"
    else:
        contents = f"Participant: {str(user_text).strip()}"
    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=STUDY_CHAT_USER_ALGORITHM_CHOICE_TASK,
            response_mime_type="application/json",
            response_json_schema=USER_ALGORITHM_CHOICE_RESPONSE_JSON_SCHEMA,
        )
        resp = client.models.generate_content(
            model=model_name, contents=contents, config=config
        )
        parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
    except Exception as exc:
        log.warning("User search-strategy classify failed (%s); skipping (fail-safe)", exc)
        return None
    algo = (parsed or {}).get("algorithm") if isinstance(parsed, dict) else None
    return algo if algo in set(STUDY_ENABLED_ALGORITHM_NAMES) else None


def check_changes_acknowledged(
    *,
    visible_reply: str,
    changes: list[str],
    api_key: str | None,
    model_name: str | None,
) -> list[int] | None:
    """Which of ``changes`` does ``visible_reply`` fail to convey to the user?

    The change list is computed deterministically by
    ``pipeline_verification.compute_material_brief_changes``; this call only
    asks the model to judge coverage **by meaning** (paraphrase-tolerant — no
    regex, no keyword matching). Returns the indices the reply doesn't
    acknowledge, or ``None`` on any failure / missing key, so a transport or
    parse error never blocks the turn (caller treats ``None`` as "no issue").
    """
    if not api_key or not model_name or not changes:
        return None
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(changes))
    user_payload = (
        'Assistant reply:\n"""\n'
        + (visible_reply or "").strip()
        + '\n"""\n\nMaterial changes applied this turn:\n'
        + numbered
    )
    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=STUDY_CHAT_CHANGE_ACK_CHECK_TASK,
            response_mime_type="application/json",
            response_json_schema=CHANGE_ACK_CHECK_RESPONSE_JSON_SCHEMA,
        )
        resp = client.models.generate_content(
            model=model_name, contents=user_payload, config=config
        )
        parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
    except Exception as exc:
        log.warning("Change-acknowledgement check failed (%s); skipping (fail-safe)", exc)
        return None
    idxs = parsed.get("unacknowledged_indices") if isinstance(parsed, dict) else None
    if not isinstance(idxs, list):
        return None
    return [i for i in idxs if isinstance(i, int) and 0 <= i < len(changes)]


def extract_companion_rules(
    *,
    test_problem_id: str | None,
    goal_term_key: str,
    companion_field: str,
    source_text: str,
    current_rules: list[Any] | None,
    api_key: str | None,
    model_name: str | None,
) -> list[Any] | None:
    """Deterministic fallback that turns a participant's free-text rule into the
    companion term's structured carrier when the main agent failed to.

    The main-turn LLM is unreliable at populating list companions (VRPTW
    ``driver_preferences``) — it acknowledges the rule in prose but omits the
    array. This focused, single-task call (the participant's wording + the
    current rules + the port's domain instructions, constrained to the carrier's
    JSON schema) is far more reliable. Returns the COMPLETE updated rule list
    (existing rules preserved + any new ones the text describes), or ``None`` on
    any failure / opt-out so it never blocks the turn.
    """
    if not api_key or not model_name or not test_problem_id:
        return None
    text = (source_text or "").strip()
    if not text:
        return None
    try:
        port = get_study_port(test_problem_id)
        instructions = port.companion_extraction_instructions(goal_term_key)
        if not instructions or not str(instructions).strip():
            return None  # port opted this term out
        props_schema = port.goal_term_properties_schema() or {}
        array_schema = (
            props_schema.get("properties", {}).get(companion_field)
            if isinstance(props_schema, dict)
            else None
        )
        if not isinstance(array_schema, dict):
            return None
    except Exception:  # pragma: no cover — never block on registry/schema hiccups
        return None

    response_schema = {
        "type": "object",
        "properties": {"rules": array_schema},
        "required": ["rules"],
        "additionalProperties": False,
    }
    system = (
        str(instructions).strip()
        + "\n\n## Your task\n"
        "Return the COMPLETE updated rule list as JSON `{\"rules\": [...]}`. "
        "Start from the current rules given below and ADD any rule the "
        "participant's text describes; keep every existing rule unless the text "
        "clearly removes or changes it. Do not invent rules the text doesn't "
        "state. If the text adds nothing new, return the current rules unchanged."
    )
    user_payload = (
        "Current rules:\n"
        + json.dumps(current_rules or [], ensure_ascii=False)
        + "\n\nParticipant's wording:\n\"\"\"\n"
        + text
        + "\n\"\"\""
    )
    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=response_schema,
        )
        resp = client.models.generate_content(
            model=model_name, contents=user_payload, config=config
        )
        parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
    except Exception as exc:
        log.warning("Companion-rule extraction failed (%s); skipping (fail-safe)", exc)
        return None
    rules = parsed.get("rules") if isinstance(parsed, dict) else None
    if not isinstance(rules, list):
        return None
    return rules


def classify_chat_temperature(
    *,
    user_text: str,
    current_problem_brief: dict[str, Any] | None,
    current_panel: dict[str, Any] | None,
    recent_runs_summary: list[dict[str, Any]] | None,
    api_key: str,
    model_name: str,
) -> ContextTemperature:
    brief = current_problem_brief or {}
    has_goal_summary = bool(str(brief.get("goal_summary") or "").strip())
    item_count = len(brief.get("items") or []) if isinstance(brief.get("items"), list) else 0
    open_question_count = (
        len(brief.get("open_questions") or []) if isinstance(brief.get("open_questions"), list) else 0
    )
    panel_problem = current_panel.get("problem") if isinstance(current_panel, dict) else None
    has_panel_problem = bool(panel_problem and isinstance(panel_problem, dict))
    has_runs = bool(recent_runs_summary)

    evidence = {
        "has_goal_summary": has_goal_summary,
        "item_count": item_count,
        "open_question_count": open_question_count,
        "has_panel_problem": has_panel_problem,
        "has_runs": has_runs,
    }
    system_instruction = (
        "Classify chat context temperature for a participant-facing optimization assistant.\n"
        "Return JSON only with key `temperature` in {cold,warm,hot}.\n"
        "Rules:\n"
        "- cold: generic capability/small-talk questions without concrete task details.\n"
        "- warm: concrete problem-definition intent appears, but no deep config/run context.\n"
        "- hot: concrete config tuning or run-result comparison context.\n"
        "A generic message like 'how do you optimize?' should be cold unless session evidence is already warm/hot."
    )
    user_payload = (
        f"User message:\n{user_text}\n\n"
        f"Session evidence JSON:\n{json.dumps(evidence, ensure_ascii=False)}"
    )
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=CHAT_TEMPERATURE_RESPONSE_JSON_SCHEMA,
    )
    resp = client.models.generate_content(model=model_name, contents=user_payload, config=config)
    parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
    temp = str(parsed.get("temperature") or "").strip().lower()
    if temp not in {"cold", "warm", "hot"}:
        raise ValueError("Invalid chat temperature classification")
    return temp  # type: ignore[return-value]


def _system_prompt_openers(
    test_problem_id: str | None, current_problem_brief: dict[str, Any] | None
) -> list[str]:
    parts = [STUDY_CHAT_SYSTEM_PROMPT]
    if is_chat_cold_start(current_problem_brief):
        return parts
    # Warm-only guidance (run results, run-button, algorithm/weight Q&A) +
    # benchmark vocabulary. Cold turns are pure goal-elicitation and shed both.
    parts.append(STUDY_CHAT_SYSTEM_PROMPT_WARM)
    apx = _study_benchmark_appendix(test_problem_id)
    if apx:
        parts.append(apx)
    return parts


def _build_visible_chat_system_instruction(
    user_text: str,
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
    post_run_directive: str | None = None,
) -> str:
    cold = is_chat_cold_start(current_problem_brief)
    brief_for_prompt = surface_problem_brief_for_chat_prompt(
        current_problem_brief, cold=cold
    )
    brief_blob = (
        json.dumps(brief_for_prompt, indent=2, ensure_ascii=False)
        if brief_for_prompt is not None
        else "{}"
    )
    fallback_profile = resolve_context_profile(
        user_text=user_text,
        current_problem_brief=current_problem_brief,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
    profile = fallback_profile
    # The heuristic and the LLM classifier consume the same structural signals
    # (has_goal_summary / item_count / open_question_count / has_panel_problem /
    # has_runs), so at the unambiguous extremes they must agree. Only spend an
    # LLM round-trip when the heuristic lands in the genuinely ambiguous "warm"
    # bucket where user_text content can tip the call.
    if api_key and model_name and fallback_profile.temperature == "warm":
        try:
            model_temperature = classify_chat_temperature(
                user_text=user_text,
                current_problem_brief=current_problem_brief,
                current_panel=current_panel,
                recent_runs_summary=recent_runs_summary,
                api_key=api_key,
                model_name=model_name,
            )
            profile = ChatContextProfile(
                temperature=model_temperature,
                execution_mode=fallback_profile.execution_mode,
            )
        except Exception as exc:
            log.warning("Chat-temperature classification failed (%s); using fallback heuristics", exc)
    mention_mealpy = "mealpy" in str(user_text or "").lower() or "library" in str(user_text or "").lower()
    capabilities_block = build_capabilities_block(
        test_problem_id=test_problem_id,
        mention_mealpy=mention_mealpy,
        temperature=profile.temperature,
    )
    doc_excerpts = search_reference_excerpts(
        repo_root=Path(__file__).resolve().parents[3],
        user_text=user_text,
        test_problem_id=test_problem_id,
        temperature=profile.temperature,
        api_key=api_key,
    )

    parts = [
        *_system_prompt_openers(test_problem_id, current_problem_brief),
        _workflow_prompt(workflow_mode),
        build_temperature_guardrails_block(profile.temperature),
        build_execution_mode_block(profile.execution_mode),
        capabilities_block,
        STUDY_CHAT_VISIBLE_REPLY_TASK,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
    # Sandbox rules ("don't write code / show source") only matter when the
    # user is probing the sandbox (asks about code, library, implementation
    # details) or on cold start (the most common moment for that probe).
    # Skipping them on neutral turns saves ~20 lines of prompt budget.
    if sandbox_rules_relevant(user_text, cold=cold):
        parts.append(STUDY_CHAT_SANDBOX_RULES)
    else:
        log.debug(
            "Skipping STUDY_CHAT_SANDBOX_RULES (cold=%s, no sandbox keywords)",
            cold,
        )
    # Visualization guidance is a ~50-line block; load it only when this
    # turn could plausibly need it. Two triggers (either suffices):
    #   - We're at or near the pre-first-run announcement window:
    #     no completed runs yet AND we're not on a cold-start turn
    #     (cold-start ≈ no goals/items/OQs yet, so nothing to announce).
    #   - The user message explicitly mentions a visualization-shaped
    #     keyword (chart, plot, color route, axis, etc.), which is when
    #     the change-request half kicks in.
    has_completed_runs = bool(recent_runs_summary)
    if (
        visualization_guidance_relevant(user_text)
        or (not has_completed_runs and not cold)
    ):
        parts.append(STUDY_CHAT_VISUALIZATION_GUIDANCE)
    else:
        log.debug(
            "Skipping STUDY_CHAT_VISUALIZATION_GUIDANCE for this turn "
            "(cold=%s, has_completed_runs=%s, viz_keyword_match=%s)",
            cold,
            has_completed_runs,
            False,
        )
    # Run-button awareness — keep the agent honest about whether the
    # participant can actually click Run optimization right now. Pairs with the
    # "## Run-button awareness" section in STUDY_CHAT_SYSTEM_PROMPT.
    if run_button_enabled is True:
        parts.append("Run optimization button: ENABLED")
    elif run_button_enabled is False:
        reason = (run_disabled_reason or "Run prerequisites are not yet met.").strip()
        parts.append(f"Run optimization button: DISABLED — reason: {reason}")
    gate_block = _gate_status_prompt_block(gate_status)
    if gate_block:
        parts.append(gate_block)
    if doc_excerpts:
        parts.append("Reference excerpts (participant-safe docs):")
        parts.append("\n\n".join(f"- {excerpt}" for excerpt in doc_excerpts))
    lock_blob = locked_goal_terms_prompt_section(current_panel or {}, test_problem_id=test_problem_id)
    if lock_blob:
        parts.append(lock_blob)
    weights_blob = current_weights_prompt_section(
        current_panel or {},
        test_problem_id=test_problem_id,
        temperature=profile.temperature,
    )
    if weights_blob:
        parts.append(weights_blob)
    if is_run_acknowledgement:
        parts.append(_run_ack_prompt(workflow_mode))
        # Controlled-study lever (agile): the server pre-decided whether THIS
        # post-run turn raises an open question or commits an assumption (blocked
        # randomization), overriding the soft OQ/assumption bias above.
        if post_run_directive == "open_question":
            parts.append(
                "## Post-run decision (this turn, REQUIRED)\n\n"
                "Raise EXACTLY ONE `open_questions` entry about a genuine "
                "modeling fork the run result raised, and add NO new assumption "
                "this turn. This overrides the default assumption-leaning bias."
            )
        elif post_run_directive == "assumption":
            parts.append(
                "## Post-run decision (this turn, REQUIRED)\n\n"
                "Commit EXACTLY ONE new assumption (a `kind:\"assumption\"` row "
                "responding to the run result) and raise NO open question this "
                "turn. Keep the visible-reply vocabulary plain (\"working "
                "setting\", \"I'll roll with X for now\")."
            )
    if is_tutorial_active:
        from app.prompts.study_chat import STUDY_CHAT_TUTORIAL_GUARDRAILS

        parts.append(STUDY_CHAT_TUTORIAL_GUARDRAILS)
    if cleanup_mode:
        parts.append(
            "Cleanup mode is active for this turn. Acknowledge cleanup naturally if relevant, but keep the visible "
            "reply focused on participant-facing guidance."
        )
    if recent_runs_summary:
        parts.append("Recent run results (for participant-visible chat context):")
        parts.append(json.dumps(recent_runs_summary, indent=2, ensure_ascii=False))
    # NOTE: the hidden-researcher-steer block is intentionally NOT emitted here.
    # This function is only the first of ~9 blocks the main-turn assembly stacks
    # (see build_main_turn_system_instruction); appending the steer here buried
    # it ~60% into the prompt, behind ~17k chars of conservative brief/grounding
    # disciplines that then out-weighed it. It is appended LAST instead, so its
    # "outranks your standing defaults" claim is backed by recency.
    return "\n\n".join(parts)


def classify_answered_open_questions(
    *,
    inputs: list[OpenQuestionClassifierInput],
    workflow_mode: str,
    current_problem_brief: dict[str, Any] | None,
    api_key: str,
    model_name: str,
    test_problem_id: str | None = None,
) -> list[OpenQuestionClassification]:
    """Rephrase + bucket-route a batch of just-answered OQs per workflow rules.

    Returns one classification per input. On any failure (network, parse, missing
    key) returns an empty list — caller falls back to existing promotion logic so
    the participant's save is never blocked.
    """
    if not inputs:
        return []
    brief_for_prompt = surface_problem_brief_for_chat_prompt(
        current_problem_brief, cold=is_chat_cold_start(current_problem_brief)
    )
    brief_blob = (
        json.dumps(brief_for_prompt, indent=2, ensure_ascii=False)
        if brief_for_prompt is not None
        else "{}"
    )
    parts = [
        *_system_prompt_openers(test_problem_id, current_problem_brief),
        _workflow_prompt(workflow_mode),
        STUDY_CHAT_OQ_CLASSIFY_TASK,
        f"Workflow mode for this batch: **{workflow_mode}**",
        "Brief snapshot (use it for terminology consistency only — do not echo it back):",
        brief_blob,
    ]
    system_instruction = "\n\n".join(parts)
    payload = {
        "answered_open_questions": [item.model_dump() for item in inputs],
    }
    user_text = json.dumps(payload, ensure_ascii=False, indent=2)

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=OQ_CLASSIFIER_RESPONSE_JSON_SCHEMA,
    )
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=user_text,
            config=config,
        )
        raw = resp.text
        log.info(
            "OQ-classify Gemini raw response: %s",
            raw if raw is not None else "<no text>",
        )
        if isinstance(resp.parsed, dict):
            turn = OpenQuestionClassifierTurn.model_validate(resp.parsed)
        elif raw:
            turn = OpenQuestionClassifierTurn.model_validate_json(raw)
        else:
            return []
        return list(turn.classifications)
    except Exception as e:
        log.warning("OQ-classify structured call failed (%s); returning empty", e)
        return []


def generate_config_from_brief(
    brief: dict[str, Any] | None,
    current_panel: dict[str, Any] | None,
    api_key: str,
    model_name: str,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
    test_problem_id: str | None = None,
) -> dict[str, Any] | None:
    """One-shot structured call that derives a panel patch from a brief."""
    if not api_key.strip():
        return None
    client = genai.Client(api_key=api_key)
    brief_blob = json.dumps(brief or {}, ensure_ascii=False)
    user_prompt = (
        "Current problem brief JSON:\n"
        f"{brief_blob}\n\n"
        "Current panel JSON (auxiliary only; do not preserve managed fields from it):\n"
        f"{json.dumps(current_panel or {}, ensure_ascii=False)}\n"
    )
    port = get_study_port(test_problem_id)
    system_instruction = "\n\n".join(
        [
            _workflow_prompt(workflow_mode),
            STUDY_CHAT_SEARCH_STRATEGY_ANCHORING,
            port.config_derive_system_prompt(),
        ]
    )
    # Static per (model, workflow, problem). Try explicit caching to cut input
    # tokens on the heavy gemini-pro derivation; if the SDK rejects (e.g. content below
    # the model's minimum), seamlessly fall back to inline system_instruction.
    cache_key = (
        "config_derive",
        model_name,
        workflow_mode,
        test_problem_id or "",
    )
    cached_name = _get_or_create_system_cache(
        client,
        model_name=model_name,
        system_text=system_instruction,
        cache_key=cache_key,
    )
    if cached_name is not None:
        config = types.GenerateContentConfig(
            cached_content=cached_name,
            response_mime_type="application/json",
            response_json_schema=port.panel_patch_response_json_schema(),
        )
    else:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_json_schema=port.panel_patch_response_json_schema(),
        )
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=config,
        )
        raw = resp.text or ""
        if isinstance(resp.parsed, dict):
            parsed = resp.parsed
        else:
            parsed = json.loads(raw) if raw else {}
        if not isinstance(parsed, dict) or not isinstance(parsed.get("problem"), dict):
            return None
        return {"problem": parsed["problem"]}
    except Exception as e:
        log.warning("Config derivation model failed (%s); falling back", e)
        return None


# ============================================================================
# Main-turn LLM
# ============================================================================
# Replaces the today-split (consolidated-turn ⇒ visible reply + intents,
# brief-update ⇒ patch + replace flags + intent re-classification,
# maintain ⇒ OQ lifecycle + assumption actions) with ONE structured call.
# See docs/.implementation/PIPELINE_V2_PLAN.md.


def _build_main_turn_schema(test_problem_id: str | None) -> dict[str, Any]:
    """JSON-schema for the V2 main turn response.

    Unions:
    - assistant_message + inline_followup
    - intent flags (change / cleanup / clear / run-trigger / run-invitation)
    - clause split (change_clause + question_clause)
    - problem_brief_patch (per-port goal_terms typing + forbidden synthesized prefixes)
    - replace flags + cleanup_mode
    - assumption_actions list (agile/demo only — ignored on waterfall by the merge)
    """
    port = get_study_port(test_problem_id)
    properties_subschema = port.goal_term_properties_schema()
    goal_terms_sub = goal_terms_schema(properties_subschema)
    from app.problems.port import all_synthesized_id_prefixes

    forbidden_prefixes = all_synthesized_id_prefixes(port)
    return {
        "title": "ChatTurnResponse",
        "type": "object",
        "properties": {
            "assistant_message": {
                "type": "string",
                "description": "Participant-visible reply (one-shot, no streaming).",
            },
            "inline_followup": {
                "type": "string",
                "description": (
                    "Optional plain-English follow-up sentence used by the pipeline "
                    "status bubble when verification flags a pause. The frontend "
                    "renders this next to the Retry / Revert / Keep-chatting action "
                    "row. Emit ONLY when you would expect verification to flag this "
                    "turn (e.g. you committed to multiple things and aren't sure "
                    "they're all consistent); otherwise omit."
                ),
            },
            "is_change_intent": {
                "type": "boolean",
                "description": (
                    "True iff the user is asking the assistant to change the "
                    "problem definition or solver config. False for concept "
                    "questions, knowledge lookups, casual chat. Conservative "
                    "default true so missing fields don't drop real edits."
                ),
            },
            "cleanup_intent": {"type": "boolean"},
            "clear_intent": {"type": "boolean"},
            "should_trigger_run": {"type": "boolean"},
            "intent_type": {
                "type": "string",
                "enum": ["none", "affirm_invite", "direct_request"],
            },
            "confidence": {"type": "number"},
            "is_run_invitation": {
                "type": "boolean",
                "description": (
                    "True iff your assistant_message itself invites the participant "
                    "to click Run optimization right now (not a hypothetical, not "
                    "a request for confirmation)."
                ),
            },
            "change_clause": {
                "type": "string",
                "description": (
                    "Populate with the commit/change portion of your visible "
                    "reply WHEN the reply commits to a brief change (e.g. "
                    "*\"I've added a lateness penalty.\"*, *\"Bumped capacity "
                    "weight to 30.\"*, *\"Switched algorithm to GA.\"*). The "
                    "server uses this signal to enforce that "
                    "`problem_brief_patch` carries a matching delta — if you "
                    "populate this field but emit an empty patch, the turn is "
                    "paused for retry with a `claim_without_delta` issue. "
                    "Leave empty on question turns, concept-question replies, "
                    "and any reply that doesn't actually commit a brief "
                    "change (in those cases the reply has nothing to back "
                    "with structured delta)."
                ),
            },
            "question_clause": {
                "type": "string",
                "description": (
                    "Populate with the question portion of your visible reply "
                    "WHEN the reply asks the participant a clarifying question "
                    "proposing a NON-FOUNDATIONAL brief change (e.g. *\"Would "
                    "you like me to add a capacity penalty?\"*, weight tuning, "
                    "optional constraint). The server uses this signal to "
                    "enforce that the brief carries a matching OQ — if you "
                    "populate this field but emit no new OQ (and don't "
                    "`rephrase`/`mark_answered` an existing one via "
                    "`oq_actions`), the turn is paused for retry. **Leave "
                    "empty/null for foundational-topic asks** (primary_goal "
                    "/ upload / search_strategy) — the server-managed monitor "
                    "state machine surfaces those OQs automatically; "
                    "populating `question_clause` for them is incorrect. Also "
                    "leave empty on commit-only turns, concept-question turns, "
                    "and replies that don't actually ask for a brief change."
                ),
            },
            "problem_brief_patch": {
                "anyOf": [
                    _build_problem_brief_patch_schema(goal_terms_sub, forbidden_prefixes),
                    {"type": "null"},
                ],
                "description": (
                    "Structured edit to the brief. Emit on every change-intent turn. "
                    "Coordinate with assistant_message so the visible reply's claims "
                    "match the patch's content. Leave null on pure concept-question "
                    "turns (is_change_intent=false)."
                ),
            },
            "replace_editable_items": {"type": "boolean"},
            "replace_open_questions": {"type": "boolean"},
            "cleanup_mode": {"type": "boolean"},
            "assumption_actions": {
                "type": "array",
                "description": (
                    "Per-row decisions on existing kind:`assumption` items. "
                    "Agile/demo only — leave empty in waterfall (no assumption rows "
                    "exist there). Use `promote_to_gathered` ONLY when the user "
                    "explicitly locked the assumption in (named the term, said "
                    "*\"lock that in\"* or equivalent unambiguous confirmation); "
                    "`drop` when the user invalidated it; `rephrase` for wording "
                    "corrections; `keep` is the default. Ambiguous *\"yes / sure "
                    "/ sounds good\"* replies are NOT a promotion signal — leave "
                    "the assumption as `keep` and let the user lock it in later."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": [
                                "keep",
                                "rephrase",
                                "drop",
                                "promote_to_gathered",
                            ],
                        },
                        "rephrased_text": {"type": "string"},
                    },
                    "required": ["id", "action"],
                },
            },
            "oq_actions": {
                "type": "array",
                "description": (
                    "Per-row OQ lifecycle decisions. Symmetric to "
                    "`assumption_actions`. Use this for routine "
                    "*\"keep / drop / rephrase / mark this OQ answered\"* "
                    "turns instead of round-tripping the full survivor list "
                    "via `replace_open_questions=true`. `drop` removes the "
                    "OQ outright — pair with the committed `goal_terms` / "
                    "items[] delta when the answer is now structurally "
                    "represented (e.g. a `config-weight-K` row was just "
                    "synthesized). `mark_answered` writes `answer_text` and "
                    "the server folds it into a gathered row. `rephrase` "
                    "updates the text in place. `keep` is the default; you "
                    "may omit OQs you don't need to touch."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": [
                                "keep",
                                "rephrase",
                                "drop",
                                "mark_answered",
                            ],
                        },
                        "rephrased_text": {"type": "string"},
                        "answer_text": {"type": "string"},
                    },
                    "required": ["id", "action"],
                },
            },
        },
        "required": ["assistant_message"],
    }


_MAIN_TURN_OUTPUT_RULES = (
    "## Output rules\n\n"
    "You emit ONE structured response: visible reply, intent flags, brief "
    "patch, per-row OQ decisions, and (agile/demo only) per-row assumption "
    "decisions. Plan the patch in lockstep with the visible reply — the "
    "server's verification will flag mismatches and force a retry.\n\n"
    "**Goal summary.** When committing the FIRST primary objective and "
    "`current_problem_brief.goal_summary` is empty, set "
    "`problem_brief_patch.goal_summary` to a short qualitative sentence "
    "(e.g. *\"Minimize total travel time.\"*). No numbers, algorithm names, "
    "or budgets.\n\n"
    "**Algorithm carrier.** When committing a search-strategy algorithm, "
    "populate `problem_brief_patch.goal_terms.search_strategy.properties."
    "algorithm` with one of: GA, PSO, SA, ACOR.\n\n"
    "**Open questions.** Every OQ you emit MUST have a `topic` field set to "
    "one of `upload`, `primary_goal`, `search_strategy`, or `other`. The "
    "first three are server-managed — the server surfaces canonical rows "
    "for uncovered foundational topics and removes them when covered, so "
    "any OQ you tag with one of those topics is dropped at merge. For your "
    "own clarifications (driver count, term meaning, ambiguity forks, etc.) "
    "set `topic: \"other\"`. ADD an `other` OQ when your visible reply "
    "asks a question; DROP / MARK ANSWERED via `oq_actions` when the user "
    "has answered, deferred, or the topic has resolved; KEEP otherwise. "
    "Never emit an OQ for permission-to-run.\n\n"
    "**OQ lifecycle (preferred path).** Use `oq_actions` for routine "
    "per-row decisions on existing OQs: `drop` once the answer is "
    "structurally represented elsewhere (e.g. you just committed the "
    "proposed `goal_terms[K]` plus its items[] row), `mark_answered` with "
    "`answer_text` when the user's reply is the answer, `rephrase` to "
    "tighten wording. `replace_open_questions=true` is for genuine cleanup "
    "turns that re-author the full list — not for routine drops.\n\n"
    "**Goal-term anchor (safety net).** When an OQ proposes a specific "
    "goal_term (e.g. *\"Should I add a capacity penalty?\"*), tag the row "
    "with `goal_key` set to the canonical key. The server auto-resolves "
    "the OQ when (a) the key is newly committed to `goal_terms` this turn "
    "and (b) the brief carries gathered info for the key. Tuning OQs on "
    "keys that were already committed survive automatically. The same "
    "`goal_key` field on a `kind: \"assumption\"` row also drives the "
    "live-text refresh (server keeps the parenthesized weight/type in "
    "sync with `goal_terms[K]`). Assumption promotion stays explicit "
    "via `assumption_actions: promote_to_gathered`.\n\n"
    "**Clarification asks.** When your visible reply asks the participant "
    "a clarifying question proposing a non-foundational brief change "
    "(weights, optional constraints, tunables), populate `question_clause` "
    "with the question portion of your reply. The server uses it to verify "
    "a matching OQ landed; missing this when you asked will pause the turn. "
    "Leave empty for foundational-topic asks (primary_goal / upload / "
    "search_strategy) — the server-managed monitor state machine surfaces "
    "those OQs automatically. Also leave empty on commit-only and "
    "concept-question turns.\n\n"
    "Use `assumption_actions` for per-row decisions on existing assumption "
    "rows (agile/demo). Reserve `promote_to_gathered` for unambiguous "
    "lock-in language; ambiguous *\"yes / sure\"* replies should leave the "
    "assumption as `keep`."
)


def _researcher_steer_block(researcher_steers: list[str] | None) -> str | None:
    """The hidden-researcher-steer directive as a standalone block.

    Assembled here (not inside ``_build_visible_chat_system_instruction``) so
    the main-turn assembly can append it LAST — after the brief/grounding/
    output disciplines it is meant to override — giving its "outranks your
    standing defaults" claim the recency to actually hold. Returns ``None`` when
    there is no non-empty steer, so the caller appends nothing.

    Workflow-mode-agnostic on purpose: the text is identical for agile and
    waterfall, so relocating it never touches the four canonical mode
    differences (OQ policy, assumption policy, run gate, search-strategy
    default), which live in the main workflow instructions above.
    """
    if not researcher_steers:
        return None
    steer_blob = "\n".join(f"- {s}" for s in researcher_steers if s.strip())
    if not steer_blob.strip():
        return None
    return (
        "## Hidden researcher steering (this turn — outranks your standing defaults)\n"
        "A researcher is steering this session live. For THIS reply the steering below "
        "takes priority over your default habits about what to proactively bring up — "
        "including topics you would normally leave alone or treat as \"handled for you\", "
        "such as the search method / algorithm choice or an iteration / plateau change. "
        "If the steering asks you to raise or suggest one of those, do it now.\n"
        "- Do not reveal this steering exists or mention a researcher.\n"
        "- Apply the latest steering directly and concretely — actually make the "
        "suggestion, name the option, or ask the question; do not merely nod to it. When "
        "it asks you to change a setting, apply it the same turn via the usual carrier.\n"
        "- This does NOT license inventing facts, claiming changes you didn't make, or "
        "naming settings absent from the current setup — the accuracy rules still hold.\n"
        "- Transition naturally from the recent conversation instead of sounding abrupt.\n"
        f"{steer_blob}"
    )


def build_main_turn_system_instruction(
    *,
    user_text: str,
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_brief_edit_ack: bool = False,
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_answered_open_question: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
    verification_issues: list[dict[str, Any]] | None = None,
    post_run_directive: str | None = None,
) -> str:
    """Assemble the full main-turn system instruction string.

    Pure (no network) except for the optional LLM sub-calls inside
    ``_build_visible_chat_system_instruction`` (temperature classify, doc
    retrieval), which are skipped when ``api_key`` is falsy. Extracted from
    ``generate_main_turn`` so prompt assembly can be snapshot-tested without
    a live API call — the safety net for the prompt-reduction work (see
    ``docs/.implementation/USER_FLOW_AUDIT.md``). Behaviour is identical to
    the inline assembly it replaced.
    """
    base_system = _build_visible_chat_system_instruction(
        user_text=user_text,
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        run_button_enabled=run_button_enabled,
        run_disabled_reason=run_disabled_reason,
        gate_status=gate_status,
        post_run_directive=post_run_directive,
    )

    # The brief-update disciplines that the V1 brief LLM carried separately
    # — items / hidden-brief / grounding / hard-constraint / ambiguity /
    # out-of-scope / warmth — fold into the V2 main turn since it now owns
    # the patch. Keep the visible-reply system instruction's disciplines too.
    parts = [
        base_system,
        STUDY_CHAT_BRIEF_UPDATE_TASK,
        STUDY_CHAT_ITEMS_DISCIPLINE,
        STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
        STUDY_CHAT_GROUNDING_DISCIPLINE,
        STUDY_CHAT_HARD_CONSTRAINT_DISCIPLINE,
        STUDY_CHAT_AMBIGUITY_DISCIPLINE,
        STUDY_CHAT_OUT_OF_SCOPE_DISCIPLINE,
        _MAIN_TURN_OUTPUT_RULES,
    ]
    if is_brief_edit_ack:
        parts.append(
            "## Brief-edit acknowledgement\n\n"
            "The participant just saved a manual edit to the problem definition. "
            "In your visible reply, acknowledge it and list the specific changes "
            "as short bullet points (one per change). Where the edit implies "
            "further structural updates (rephrasing related rows, adjusting goal "
            "terms / weights / algorithm to fit, asking about consequences), emit "
            "those in `problem_brief_patch`. Do NOT echo back what the user typed "
            "verbatim."
        )
    if is_config_save:
        from app.prompts.study_chat import STUDY_CHAT_CONFIG_SAVE_RATIONALE

        parts.append(STUDY_CHAT_CONFIG_SAVE_RATIONALE)
        parts.append(
            "## Config-save inverse-derivation\n\n"
            "Treat the saved panel as ground truth. Your patch may refresh the "
            "brief's prose to mirror new panel values but must NOT propose "
            "panel changes — the panel was just authored by the user. The "
            "server will skip the config-derivation step on this turn."
        )
    if is_upload_context:
        from app.prompts.study_chat import STUDY_CHAT_UPLOAD_CONTEXT_GUIDANCE

        parts.append(STUDY_CHAT_UPLOAD_CONTEXT_GUIDANCE)
    if is_answered_open_question:
        from app.prompts.study_chat import STUDY_CHAT_ANSWERED_OQ_CONTEXT

        parts.append(STUDY_CHAT_ANSWERED_OQ_CONTEXT)
    if verification_issues:
        # Issue feedback block — appended on retry so the LLM can target
        # the specific issues the verifier flagged. Plain-English to match
        # what the participant sees in the status bubble.
        issue_lines = []
        for raw in verification_issues:
            if not isinstance(raw, dict):
                continue
            category = str(raw.get("category") or "").strip()
            subject = str(raw.get("subject") or "").strip()
            message = str(raw.get("message") or "").strip()
            severity = str(raw.get("severity") or "error").strip()
            issue_lines.append(
                f"- [{severity}] {category}"
                + (f" ({subject})" if subject else "")
                + (f": {message}" if message else "")
            )
        parts.append(
            "## Verification feedback (retry)\n\n"
            "Your previous response had the issues listed below. Regenerate the "
            "structured response with these specific corrections — don't redo "
            "the whole turn from scratch.\n\n"
            "**Least-damage rule:** fix ONLY the flagged issue(s) and preserve "
            "everything else. Do not newly drop or wholesale-replace "
            "`open_questions`, and do not commit goal_terms or `oq_actions` "
            "the flagged issue doesn't require. When a fix can be made either "
            "by deleting/committing or by softening the visible reply, prefer "
            "softening the reply — never resolve a question the participant "
            "hasn't actually answered.\n\n"
            + "\n".join(issue_lines)
        )

    # Hidden researcher steering goes LAST — after every standing discipline and
    # even after the retry-feedback block — so it is the final instruction the
    # model reads. This is what makes its stated priority real; when it lived
    # inside base_system it was out-weighed by the ~17k chars appended after it.
    # Kept across retries by design (the steers are threaded through the retry
    # context), matching the one-shot-but-persistent contract in
    # load_fresh_researcher_steers.
    steer_block = _researcher_steer_block(researcher_steers)
    if steer_block:
        parts.append(steer_block)

    return "\n\n".join(parts)


def generate_main_turn(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_brief_edit_ack: bool = False,
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_answered_open_question: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
    verification_issues: list[dict[str, Any]] | None = None,
    post_run_directive: str | None = None,
):
    """Main-turn LLM. ONE call returning everything needed for
    the turn: visible reply, intents, brief patch, assumption actions.

    Returns ``ChatTurnResponse`` or ``None`` on failure (callers should
    treat ``None`` as a transient transport/parse error and surface the
    paused state through the pipeline status, not silently no-op).

    ``verification_issues`` is non-empty on a retry — the issues are
    appended as an audit block so the model can fix specific problems.
    """
    from app.schemas import ChatTurnResponse

    if not api_key or not model_name:
        return None

    system_instruction = build_main_turn_system_instruction(
        user_text=user_text,
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        is_brief_edit_ack=is_brief_edit_ack,
        is_config_save=is_config_save,
        is_upload_context=is_upload_context,
        is_answered_open_question=is_answered_open_question,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        run_button_enabled=run_button_enabled,
        run_disabled_reason=run_disabled_reason,
        gate_status=gate_status,
        verification_issues=verification_issues,
        post_run_directive=post_run_directive,
    )
    schema = _build_main_turn_schema(test_problem_id)

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=schema,
    )

    def _attempt():
        try:
            chat = client.chats.create(
                model=model_name,
                config=config,
                history=_history_to_contents(history_lines),
            )
            resp = chat.send_message(user_text)
        except Exception as exc:
            log.warning("Main-turn LLM call failed (%s)", exc)
            return None
        parsed: Any = resp.parsed
        if parsed is None:
            raw = resp.text or ""
            if not raw.strip():
                return None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return None
        if isinstance(parsed, ChatTurnResponse):
            return parsed
        if isinstance(parsed, dict):
            try:
                return ChatTurnResponse.model_validate(parsed)
            except Exception as exc:
                log.warning("Main-turn LLM validation failed (%s)", exc)
                return None
        return None

    turn = _attempt()
    if turn is not None:
        return turn
    log.info("Main-turn LLM first attempt failed; retrying once")
    return _attempt()
