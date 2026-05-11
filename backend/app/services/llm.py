"""Server-side Gemini via google-genai: use Chat API (chats.create + send_message), not raw generate_content."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from google import genai
from google.genai import types

from app.problem_brief import (
    is_chat_cold_start,
    current_weights_prompt_section,
    locked_goal_terms_prompt_section,
    surface_problem_brief_for_chat_prompt,
)
from app.problems.registry import get_study_port
from app.problems.schema_shared import GOAL_TERMS_SCHEMA, goal_terms_schema

from app.prompts.study_chat import (
    STUDY_CHAT_BRIEF_UPDATE_TASK,
    STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
    STUDY_CHAT_ITEMS_DISCIPLINE,
    STUDY_CHAT_OQ_CLASSIFY_TASK,
    STUDY_CHAT_OQ_MAINTAIN_TASK,
    STUDY_CHAT_PHASE_CONFIGURATION,
    STUDY_CHAT_PHASE_DISCOVERY,
    STUDY_CHAT_PHASE_STRUCTURING,
    STUDY_CHAT_RUN_ACK_AGILE,
    STUDY_CHAT_RUN_ACK_BASE,
    STUDY_CHAT_RUN_ACK_DEMO,
    STUDY_CHAT_RUN_ACK_WATERFALL,
    STUDY_CHAT_SANDBOX_RULES,
    STUDY_CHAT_STRUCTURED_JSON_RULES,
    STUDY_CHAT_SYSTEM_PROMPT,
    STUDY_CHAT_VISIBLE_REPLY_TASK,
    STUDY_CHAT_VISUALIZATION_GUIDANCE,
    STUDY_CHAT_WORKFLOW_AGILE,
    STUDY_CHAT_WORKFLOW_DEMO,
    STUDY_CHAT_WORKFLOW_WATERFALL,
    sandbox_rules_relevant,
    visualization_guidance_relevant,
)
from app.schemas import (
    ChatModelTurn,
    ConsolidatedChatTurn,
    OpenQuestionClassification,
    OpenQuestionClassifierInput,
    OpenQuestionClassifierTurn,
    OpenQuestionMaintenanceTurn,
    ProblemBriefUpdateTurn,
    RunTriggerIntentTurn,
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

_PROBLEM_BRIEF_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["id", "text"],
}

def _build_problem_brief_patch_schema(goal_terms_subschema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "goal_summary": {"type": "string"},
            "run_summary": {"type": "string"},
            "items": {"type": "array", "items": _PROBLEM_BRIEF_ITEM_SCHEMA},
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
            "solver_scope": {"type": "string"},
            "backend_template": {"type": "string"},
        },
    }


# Default permissive schema for back-compat call sites that don't know which
# port is active (e.g. legacy structured chat-turn flow). Problem-aware paths
# build their own via `_build_brief_update_response_schema(test_problem_id)`.
_PROBLEM_BRIEF_PATCH_SCHEMA: dict[str, Any] = _build_problem_brief_patch_schema(
    GOAL_TERMS_SCHEMA
)

CHAT_MODEL_TURN_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "ChatModelTurn",
    "type": "object",
    "properties": {
        "assistant_message": {
            "type": "string",
            "description": "Visible reply to the participant.",
        },
        "problem_brief_patch": {
            "anyOf": [
                _PROBLEM_BRIEF_PATCH_SCHEMA,
                {"type": "null"},
            ],
        },
        "replace_editable_items": {"type": "boolean"},
        "replace_open_questions": {"type": "boolean"},
        "cleanup_mode": {"type": "boolean"},
    },
    "required": ["assistant_message"],
}

def _build_brief_update_response_schema(test_problem_id: str | None) -> dict[str, Any]:
    """Per-problem brief-update response schema.

    Each port supplies its own `goal_terms[key].properties` shape via
    `StudyProblemPort.goal_term_properties_schema()`; the schema_shared
    factory slots it in. Schema construction is cheap (plain dict assembly)
    so we rebuild per call rather than caching.
    """
    port = get_study_port(test_problem_id)
    properties_subschema = port.goal_term_properties_schema()
    goal_terms_sub = goal_terms_schema(properties_subschema)
    return {
        "title": "ProblemBriefUpdateTurn",
        "type": "object",
        "properties": {
            "problem_brief_patch": {
                "anyOf": [
                    _build_problem_brief_patch_schema(goal_terms_sub),
                    {"type": "null"},
                ],
            },
            "replace_editable_items": {"type": "boolean"},
            "replace_open_questions": {"type": "boolean"},
            "cleanup_mode": {"type": "boolean"},
            # LLM-reported classification of the visible reply that just got
            # sent. Used by the workflow-compliance check to decide whether
            # the brief delta matches what the visible reply promised, without
            # running brittle regexes on the natural-language reply text.
            "visible_reply_intent": {
                "type": "object",
                "properties": {
                    "claims_brief_change": {"type": "boolean"},
                    "asks_user_question": {"type": "boolean"},
                },
            },
        },
    }


# Back-compat constant — uses permissive defaults. Problem-aware code paths
# call `_build_brief_update_response_schema(test_problem_id)` instead.
BRIEF_UPDATE_RESPONSE_JSON_SCHEMA: dict[str, Any] = _build_brief_update_response_schema(None)

OQ_MAINTAIN_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "DefinitionMaintenance",
    "type": "object",
    "properties": {
        "open_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        },
        # Per-row decisions on `kind: "assumption"` rows in the brief's
        # `items[]`. Agile/demo only; waterfall LLMs should leave this
        # empty (the server also ignores it on waterfall turns).
        "assumption_actions": {
            "type": "array",
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
    },
    "required": ["open_questions"],
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
                },
                "required": ["question_id", "bucket"],
            },
        },
    },
    "required": ["classifications"],
}


_DEFINITION_INTENT_JSON_SCHEMA: dict[str, Any] = {
    "title": "DefinitionIntentClassification",
    "type": "object",
    "properties": {
        "cleanup_intent": {"type": "boolean"},
        "clear_intent": {"type": "boolean"},
        "is_change_intent": {"type": "boolean"},
    },
    "required": ["cleanup_intent", "clear_intent", "is_change_intent"],
}

_DEFINITION_INTENT_SYSTEM = (
    "You are a lightweight intent classifier for a research optimization chat tool. "
    "Participants are study users writing free-form English messages.\n\n"
    "Classify the message for exactly three flags:\n"
    "- cleanup_intent: true if the user wants to remove, deduplicate, merge, tidy, or reorganize "
    "items in the Definition panel (e.g. 'tidy up the list', 'there are duplicates', "
    "'remove the repeated stuff', 'clean that up', 'consolidate the gathered items').\n"
    "- clear_intent: true if the user wants to wipe all Definition content and start over from "
    "scratch (e.g. 'start over', 'reset everything', 'forget what I told you', 'fresh start', "
    "'wipe the slate', 'begin again from zero').\n"
    "- is_change_intent: true if the message is **asking the assistant to change the problem "
    "definition or solver configuration** — adding/removing/editing goals, constraints, weights, "
    "algorithm choice, or any solver setting.  False when the message is a concept question, a "
    "knowledge-base lookup, a clarification request about something already on the panel, casual "
    "chat, or a request for an explanation that doesn't ask for any edit (e.g. 'what does GA "
    "mean?', 'why is travel time penalized?', 'can you explain the convergence plot?', 'how does "
    "this benchmark work?', 'thanks').  When in doubt — and especially for any explicit edit verb "
    "or new constraint/value — return true so the pipeline runs.\n\n"
    "Return ONLY valid JSON. cleanup_intent and clear_intent default to false; is_change_intent "
    "defaults to true (conservative — better to refresh the panel than miss a real edit)."
)

CONSOLIDATED_CHAT_TURN_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "ConsolidatedChatTurn",
    "type": "object",
    "properties": {
        # `assistant_message` first so Gemini emits it before the structured tail —
        # if a streaming consumer is added later, the visible reply is the first
        # chunk available, and the model has the full text in context when it
        # decides the intent flags.
        "assistant_message": {
            "type": "string",
            "description": "Participant-visible reply.",
        },
        "cleanup_intent": {"type": "boolean"},
        "clear_intent": {"type": "boolean"},
        "is_change_intent": {"type": "boolean"},
        "should_trigger_run": {"type": "boolean"},
        "intent_type": {
            "type": "string",
            "enum": ["none", "affirm_invite", "direct_request"],
        },
        "confidence": {"type": "number"},
        "is_run_invitation": {"type": "boolean"},
        # Clause split for mixed-intent turns. Quoting the user's own words
        # (lightly edited) keeps the brief-update LLM scoped to the edit half
        # and avoids the concept-question half polluting brief patches.
        "change_clause": {
            "type": "string",
            "description": (
                "The portion of the user's message that asks for a brief / config "
                "change. Quote or lightly paraphrase the user's own words. Empty "
                "string when the message has no edit ask."
            ),
        },
        "question_clause": {
            "type": "string",
            "description": (
                "The portion of the user's message that is a concept question / "
                "knowledge lookup / clarification. Empty string when the message "
                "has no question."
            ),
        },
    },
    "required": [
        "assistant_message",
        "cleanup_intent",
        "clear_intent",
        "is_change_intent",
        "should_trigger_run",
        "intent_type",
        "is_run_invitation",
    ],
}


RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "RunTriggerIntentTurn",
    "type": "object",
    "properties": {
        "should_trigger_run": {"type": "boolean"},
        "intent_type": {"type": "string", "enum": ["none", "affirm_invite", "direct_request"]},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["should_trigger_run", "intent_type"],
}

RUN_INVITATION_CLASSIFICATION_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "AssistantRunInvitationClassification",
    "type": "object",
    "properties": {
        "is_run_invitation": {"type": "boolean"},
    },
    "required": ["is_run_invitation"],
}

CHAT_TEMPERATURE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "ChatTemperatureClassification",
    "type": "object",
    "properties": {
        "temperature": {"type": "string", "enum": ["cold", "warm", "hot"]},
    },
    "required": ["temperature"],
}

WorkflowPhase = Literal["discovery", "structuring", "configuration"]


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


def _phase_prompt(phase: WorkflowPhase) -> str:
    if phase == "configuration":
        return STUDY_CHAT_PHASE_CONFIGURATION
    if phase == "structuring":
        return STUDY_CHAT_PHASE_STRUCTURING
    return STUDY_CHAT_PHASE_DISCOVERY


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
    apx = _study_benchmark_appendix(test_problem_id)
    if apx:
        parts.append(apx)
    return parts


def resolve_workflow_phase(
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
) -> WorkflowPhase:
    brief = current_problem_brief or {}
    goal_summary = str(brief.get("goal_summary") or "").strip()
    items = brief.get("items") if isinstance(brief.get("items"), list) else []
    open_questions = brief.get("open_questions") if isinstance(brief.get("open_questions"), list) else []
    non_system_items = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("kind") or "").strip().lower() in {"gathered", "assumption"}
        and str(item.get("text") or "").strip()
    ]
    has_panel = bool(current_panel and isinstance(current_panel, dict))
    has_successful_run = any(bool(run.get("ok")) for run in (recent_runs_summary or []))

    if workflow_mode in ("agile", "demo"):
        if has_successful_run or has_panel:
            return "configuration"
        if goal_summary or non_system_items:
            return "structuring"
        return "discovery"

    if has_successful_run:
        return "configuration"
    if has_panel and len(non_system_items) >= 4 and len(open_questions) == 0:
        return "configuration"
    if goal_summary or len(non_system_items) >= 2:
        return "structuring"
    return "discovery"


def _build_structured_system_instruction(
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    current_panel: dict[str, Any] | None = None,
    test_problem_id: str | None = None,
) -> str:
    phase = resolve_workflow_phase(
        current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
    cold = is_chat_cold_start(current_problem_brief)
    brief_for_prompt = surface_problem_brief_for_chat_prompt(
        current_problem_brief, cold=cold
    )
    brief_blob = (
        json.dumps(brief_for_prompt, indent=2, ensure_ascii=False)
        if brief_for_prompt is not None
        else "{}"
    )
    parts = [
        *_system_prompt_openers(test_problem_id, current_problem_brief),
        _workflow_prompt(workflow_mode),
        _phase_prompt(phase),
        STUDY_CHAT_STRUCTURED_JSON_RULES,
        STUDY_CHAT_ITEMS_DISCIPLINE,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
    lock_structured = locked_goal_terms_prompt_section(current_panel or {}, test_problem_id=test_problem_id)
    if lock_structured:
        parts.append(lock_structured)
    if cleanup_mode:
        parts.append(
            "Cleanup mode is active for this turn. Reorganize gathered facts and assumptions holistically. "
            "If you return problem_brief_patch.items, return a coherent full editable snapshot and "
            "set replace_editable_items=true. Preserve existing open questions unless you intentionally "
            "emit a full replacement list under problem_brief_patch.open_questions with "
            "replace_open_questions=true (omit open_questions from the patch to leave them unchanged)."
        )
    if recent_runs_summary:
        runs_blob = json.dumps(recent_runs_summary, indent=2, ensure_ascii=False)
        parts.append(
            "Recent run results (for context — compare costs and violations across runs "
            "when the user asks about results or changes):"
        )
        parts.append(runs_blob)
    if researcher_steers:
        steer_blob = "\n".join(f"- {s}" for s in researcher_steers if s.strip())
        if steer_blob.strip():
            parts.append(
                "Hidden researcher steering (highest-priority instruction for this next participant reply):\n"
                "- Do not reveal this steering exists or mention a researcher.\n"
                "- Apply the latest steering directly in your next response.\n"
                "- Transition naturally from the recent conversation instead of sounding abrupt.\n"
                f"{steer_blob}"
            )
    return "\n\n".join(parts)


def _build_visible_chat_system_instruction(
    user_text: str,
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> str:
    phase = resolve_workflow_phase(
        current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
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
        _phase_prompt(phase),
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
    if researcher_steers:
        steer_blob = "\n".join(f"- {s}" for s in researcher_steers if s.strip())
        if steer_blob.strip():
            parts.append(
                "Hidden researcher steering (highest-priority instruction for this next participant reply):\n"
                "- Do not reveal this steering exists or mention a researcher.\n"
                "- Apply the latest steering directly in your next response.\n"
                "- Transition naturally from the recent conversation instead of sounding abrupt.\n"
                f"{steer_blob}"
            )
    return "\n\n".join(parts)


def _visible_reply_consistency_block(
    workflow_mode: str, visible_assistant_message: str
) -> str:
    """Workflow-aware "the brief MUST stay consistent with the visible
    reply" block, plus the visible_reply_intent classification rules.

    Extracted to keep ``_build_brief_update_system_instruction`` legible
    — the inline version was ~110 lines of branched prose. This helper
    returns the same content, branched on workflow_mode. Includes the
    delimited reply text, so the caller appends the returned string
    verbatim with no further wrapping.

    The waterfall branch forbids ``kind: "assumption"`` for clarifying
    questions and search-strategy commitments. Agile/demo allow proactive
    `assumption` rows. The "structured carrier on same turn" + "provenance
    follows origin" rules are always-on (port-agnostic generalisation
    of, e.g., VRPTW's worker_preference / shift_limit carriers).
    """
    is_waterfall = str(workflow_mode or "").strip().lower() == "waterfall"
    if is_waterfall:
        search_strategy_rule = (
            "- **Algorithm / search-strategy commitment (waterfall).** When\n"
            "  the visible reply names a specific search method (e.g.\n"
            "  *'starting from GA'*, *'I'll default to genetic search'*),\n"
            "  the brief MUST record an `open_questions` entry asking the\n"
            "  user to confirm or pick a different one. Do NOT emit a\n"
            "  `kind: \"assumption\"` row in waterfall — the workflow does\n"
            "  not allow assumptions, and emitting one creates a duplicate\n"
            "  OQ via the workflow-coercion step. Only when the user has\n"
            "  EXPLICITLY answered the algorithm question in chat (e.g.\n"
            "  *'sure, GA'*, *'use SA'*) may you emit a `kind: \"gathered\"`\n"
            "  row whose text names the algorithm by name (e.g. *'Search\n"
            "  strategy is set to GA (genetic search).'*). Until then, keep\n"
            "  the OQ open. The server strips the panel's algorithm field\n"
            "  unless the brief has a gathered row that mentions a known\n"
            "  algorithm name.\n"
        )
        question_rule = (
            "- **Clarifying question in waterfall → emit `open_questions`\n"
            "  (MUST, not heuristic).** When the visible reply asks the\n"
            "  user something (e.g. *'how strict is the capacity limit?'*,\n"
            "  *'which search method?'*, *'would you like to introduce\n"
            "  penalties for late arrivals or capacity limits?'*), the\n"
            "  brief MUST record an `open_questions` entry on this turn\n"
            "  (merge-append; do not set `replace_open_questions` unless\n"
            "  intentionally replacing the full list). This obligation\n"
            "  is symmetric with the `visible_reply_intent.asks_user_\n"
            "  question` flag you also emit — if you set that flag true,\n"
            "  the patch MUST contain a matching new OQ. Asking a\n"
            "  question in chat without recording it is a regression.\n"
            "  Never use `kind: \"assumption\"` to capture an unanswered\n"
            "  question in waterfall.\n"
        )
    else:
        search_strategy_rule = (
            "- **Algorithm / search-strategy commitment (agile/demo).** When\n"
            "  the visible reply names a specific search method (e.g.\n"
            "  *'starting from GA'*, *'using SA for now'*), emit a\n"
            "  `kind: \"assumption\"`, `source: \"agent\"` brief items[] row\n"
            "  whose text names the algorithm by name (e.g. *'Search\n"
            "  strategy is set to GA (genetic search) as a starting\n"
            "  point.'*). The server strips the panel's algorithm field\n"
            "  unless the brief mentions a known algorithm name —\n"
            "  failing to land this row breaks the auto-first-run gate.\n"
        )
        question_rule = (
            "- **Clarifying question or floated goal (agile/demo, MUST).**\n"
            "  When the visible reply asks the user something or floats\n"
            "  a possible goal/constraint to add, follow the workflow's\n"
            "  own rules — agile prefers a tentative `kind: \"assumption\"`\n"
            "  items[] row (announced as fait accompli); demo prefers an\n"
            "  `open_questions` entry. Either way, the structured patch\n"
            "  MUST land this turn. This obligation is symmetric with\n"
            "  `visible_reply_intent.asks_user_question` /\n"
            "  `claims_brief_change`: if either flag is true, the patch\n"
            "  MUST contain at least one matching row (new OQ for an\n"
            "  unanswered question; new items[] row for a claimed\n"
            "  change). Announcing in chat without landing the row is a\n"
            "  regression — the user sees the announcement but the panel\n"
            "  stays blank.\n"
        )
    body = (
        "## Visible assistant reply that JUST got sent to the user (this turn)\n"
        "Treat the reply below as authoritative context for what the participant\n"
        "has just been told. The hidden brief MUST stay consistent with it:\n"
        "\n"
        "- **Committed change → emit the matching patch.** If the reply commits\n"
        "  to a specific brief change (e.g. *'Changes I made: increased the\n"
        "  lateness penalty weight'*, *'I'll bump capacity overflow to hard'*,\n"
        "  *'Adding a workload-balance assumption'*), emit the corresponding\n"
        "  `problem_brief_patch` so the brief and the visible chat agree.\n"
        "- **Structured carrier → populate it on the same turn.** When the\n"
        "  committed change is a goal term whose schema defines a\n"
        "  `properties` shape (e.g. VRPTW's `worker_preference` carries\n"
        "  rules under `properties.driver_preferences`; `shift_limit`\n"
        "  carries `properties.max_shift_hours`), the patch MUST populate\n"
        "  that structured carrier on this turn — not just write a prose\n"
        "  `items[]` row. Emitting only a prose row leaves the panel\n"
        "  blank, the synthesized prose row never renders, and the rule\n"
        "  flickers in only on a later turn when you re-read the brief.\n"
        "  See the active-benchmark appendix for the exact carrier path.\n"
        "- **Provenance follows origin, not phrasing.** A change the user\n"
        "  asked for (*'Alice doesn't like Zone D'*, *'add a shift\n"
        "  limit'*) is `kind: \"gathered\"`, `source: \"user\"` — even if\n"
        "  your visible reply uses fait-accompli phrasing. Reserve\n"
        "  `kind: \"assumption\"` for terms you proactively introduced\n"
        "  without a user request (typically post-run, motivated by run\n"
        "  feedback the user did not name).\n"
        f"{search_strategy_rule}"
        f"{question_rule}"
        "- **Pure descriptive / future-intent text → no patch needed.** If the\n"
        "  reply only describes future intent without naming a concrete change\n"
        "  or asking anything (e.g. *'I'll think about that'*, *'Let me know\n"
        "  what you want next'*), no patch is required for that intent.\n"
        "\n"
        "Never contradict the visible reply.\n"
        "\n"
        "## Visible-reply intent classification (required)\n"
        "Also populate `visible_reply_intent` with two booleans describing\n"
        "the visible reply you just read:\n"
        "\n"
        "- `claims_brief_change`: true iff the reply states or implies that\n"
        "  the brief / Definition / solver setup was just changed (past tense\n"
        "  fait accompli — *'I've added X'*, *'Bumped Y to 12'*, *'Changes I\n"
        "  made: …'*, *'Mapped lateness to a soft constraint'*). False when\n"
        "  the reply only describes future intent (*'I'll think about it'*),\n"
        "  asks a question, gives a concept explanation, invites an upload,\n"
        "  or says *'setting up your first run'* in the future-intent sense.\n"
        "  This flag is what downstream compliance uses to verify the\n"
        "  matching `problem_brief_patch` actually landed — be honest about\n"
        "  it: if you did NOT emit a patch, set this false.\n"
        "- `asks_user_question`: true iff the reply explicitly asks the user\n"
        "  to answer something (clarifying question, choice between options,\n"
        "  *'would you like…'*, *'should I…'*). False for rhetorical or\n"
        "  conversational questions that do not require a user answer.\n"
        "\n"
        "```\n"
        + visible_assistant_message.strip()
        + "\n```"
    )
    return body


def _build_brief_update_system_instruction(
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_answered_open_question: bool = False,
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    visible_assistant_message: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> str:
    phase = resolve_workflow_phase(
        current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
    cold = is_chat_cold_start(current_problem_brief)
    brief_for_prompt = surface_problem_brief_for_chat_prompt(
        current_problem_brief, cold=cold
    )
    brief_blob = (
        json.dumps(brief_for_prompt, indent=2, ensure_ascii=False)
        if brief_for_prompt is not None
        else "{}"
    )
    parts = [
        *_system_prompt_openers(test_problem_id, current_problem_brief),
        _workflow_prompt(workflow_mode),
        _phase_prompt(phase),
        STUDY_CHAT_BRIEF_UPDATE_TASK,
        STUDY_CHAT_ITEMS_DISCIPLINE,
        STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
    gate_block = _gate_status_prompt_block(gate_status)
    if gate_block:
        parts.append(gate_block)
    # Pass the visible chat reply that JUST got sent to the user (before this
    # hidden brief turn runs) so the brief can stay consistent with what the
    # participant just read. Without this, the brief LLM and the chat LLM
    # operate independently and can diverge — the most common failure is the
    # chat saying "Changes I made: …" while the hidden turn skips the patch.
    if visible_assistant_message and visible_assistant_message.strip():
        parts.append(
            _visible_reply_consistency_block(
                workflow_mode, visible_assistant_message
            )
        )
    lock_blob = locked_goal_terms_prompt_section(current_panel or {}, test_problem_id=test_problem_id)
    if lock_blob:
        parts.append(lock_blob)
    if cleanup_mode and current_panel and isinstance(current_panel, dict) and current_panel:
        parts.append(
            "Current saved **panel configuration** (authoritative numeric weights, algorithm, "
            "iterations, population, benchmark-specific penalties or extras, `only_active_terms`, algorithm_params, …). "
            "When you rewrite gathered rows (one row per objective or penalty term), **carry these "
            "values through** in plain language (e.g. “… weight is set to N”). The server merges "
            "slot-backed lines from this panel after cleanup, but matching the numbers here avoids "
            "confusing churn."
        )
        parts.append(json.dumps(current_panel, indent=2, ensure_ascii=False))
    if is_run_acknowledgement:
        parts.append(_run_ack_prompt(workflow_mode))
        if workflow_mode not in ("agile", "demo"):
            parts.append(
                "**Waterfall — hidden brief after run:** merge-append **`problem_brief_patch.open_questions`** "
                "(omit `replace_open_questions` or set it false unless you intentionally replace the entire list). "
                "Add or refine **one or two** questions when there is something left to clarify; skip if the "
                "specification is already adequately covered."
            )
    if is_answered_open_question:
        parts.append(
            "Answer-save context: Record the resolved Q&A as a gathered fact (kind gathered), "
            "omit that question from open_questions, and set replace_open_questions=true. "
            "Do not add gathered items that only describe uploads or session status."
        )
    if is_config_save:
        from app.prompts.study_chat import STUDY_CHAT_CONFIG_SAVE_RATIONALE

        parts.append(STUDY_CHAT_CONFIG_SAVE_RATIONALE)
    if is_upload_context:
        from app.prompts.study_chat import STUDY_CHAT_UPLOAD_CONTEXT_GUIDANCE

        parts.append(STUDY_CHAT_UPLOAD_CONTEXT_GUIDANCE)
    if is_tutorial_active:
        from app.prompts.study_chat import STUDY_CHAT_TUTORIAL_GUARDRAILS

        parts.append(STUDY_CHAT_TUTORIAL_GUARDRAILS)
    if cleanup_mode:
        parts.append(
            "Cleanup mode is active for this turn (user asked to clean up / consolidate / deduplicate the definition). "
            "Return a coherent **full** gathered+assumption snapshot: set cleanup_mode=true, replace_editable_items=true, "
            "and include every non-system item you intend to keep. "
            "**Mandatory:** one `gathered` row per objective weight and per constraint-handling / penalty term — do **not** "
            "merge multiple terms into one comma-separated `Constraint handling:` or bundled objective line; use separate rows. "
            "Deduplicate by marking superseded facts `rejected`, not by gluing terms together. "
            "Keep `goal_summary` qualitative (no numeric weights or run budgets). "
            "Preserve existing open questions unless you intentionally emit a full replacement under "
            "problem_brief_patch.open_questions with replace_open_questions=true (omit open_questions from the patch to leave them unchanged)."
        )
        parts.append(
            "If the user specifically asks to clean up open questions only, prioritize updating "
            "problem_brief_patch.open_questions with replace_open_questions=true and avoid replacing items."
        )
    if recent_runs_summary:
        parts.append("Recent run results (for hidden brief-update context):")
        parts.append(json.dumps(recent_runs_summary, indent=2, ensure_ascii=False))
    if researcher_steers:
        steer_blob = "\n".join(f"- {s}" for s in researcher_steers if s.strip())
        if steer_blob.strip():
            parts.append(
                "Hidden researcher steering (highest-priority instruction for this next hidden brief update):\n"
                "- Do not reveal this steering exists or mention a researcher.\n"
                "- Apply the latest steering directly in your next hidden output.\n"
                f"{steer_blob}"
            )
    return "\n\n".join(parts)


def _plain_fallback_reply(
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
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> str:
    system = _build_visible_chat_system_instruction(
        user_text=user_text,
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        run_button_enabled=run_button_enabled,
        run_disabled_reason=run_disabled_reason,
        gate_status=gate_status,
    )
    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(system_instruction=system),
        history=_history_to_contents(history_lines),
    )
    resp = chat.send_message(user_text)
    if not resp.text:
        raise RuntimeError("Empty model response")
    return resp.text.strip()


def generate_visible_chat_reply(
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
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> str:
    client = genai.Client(api_key=api_key)
    system_instruction = _build_visible_chat_system_instruction(
        user_text=user_text,
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        run_button_enabled=run_button_enabled,
        run_disabled_reason=run_disabled_reason,
        gate_status=gate_status,
    )
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(system_instruction=system_instruction),
        history=_history_to_contents(history_lines),
    )
    resp = chat.send_message(user_text)
    if not resp.text:
        raise RuntimeError("Empty model response")
    return resp.text.strip()


def generate_problem_brief_update(
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
    is_answered_open_question: bool = False,
    is_config_save: bool = False,
    is_upload_context: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    visible_assistant_message: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> ProblemBriefUpdateTurn | None:
    """Run the hidden brief-update structured call.

    Returns ``None`` on any failure (network, timeout, parse error). Returns
    an empty ``ProblemBriefUpdateTurn()`` only when the LLM legitimately
    decided no patch was needed. Callers use the None-vs-empty distinction
    to surface ``brief_status="failed"`` instead of silently no-opping.
    """
    client = genai.Client(api_key=api_key)
    system_instruction = _build_brief_update_system_instruction(
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        is_answered_open_question=is_answered_open_question,
        is_config_save=is_config_save,
        is_upload_context=is_upload_context,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        visible_assistant_message=visible_assistant_message,
        gate_status=gate_status,
    )
    history = _history_to_contents(history_lines)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=_build_brief_update_response_schema(test_problem_id),
    )
    try:
        chat = client.chats.create(
            model=model_name,
            config=config,
            history=history,
        )
        resp = chat.send_message(user_text)
        raw = resp.text
        log.info(
            "Brief-update Gemini raw response: %s",
            raw if raw is not None else "<no text>",
        )
        if resp.parsed is not None:
            if isinstance(resp.parsed, ProblemBriefUpdateTurn):
                return resp.parsed
            if isinstance(resp.parsed, dict):
                return ProblemBriefUpdateTurn.model_validate(resp.parsed)
        if not raw:
            raise RuntimeError("Empty model response")
        return ProblemBriefUpdateTurn.model_validate_json(raw)
    except Exception as e:
        log.warning("Brief-update structured call failed (%s); returning None to signal failure", e)
        return None


def maintain_definition_state(
    *,
    workflow_mode: str,
    user_message: str,
    visible_reply: str,
    current_open_questions: list[dict[str, Any]],
    current_assumptions: list[dict[str, Any]] | None = None,
    recent_gathered: list[str],
    api_key: str,
    model_name: str,
    test_problem_id: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]] | None:
    """Run one focused Gemini call to maintain definition state end-to-end.

    For all workflow modes this returns the FULL updated open-question list
    (adds / drops / keeps / rephrases). For agile/demo it additionally
    returns ``assumption_actions`` — per-row decisions on each existing
    ``kind: "assumption"`` row in the brief's ``items[]``: keep / rephrase
    / drop / promote_to_gathered. (Waterfall has no assumption rows.)

    Deliberately decoupled from the brief-update LLM so the definition
    lifecycle is owned by one focused call rather than entangled with
    goal_terms / items merging — that entanglement was the regression
    where the brief LLM would skip an OQ-add or prune an OQ the user had
    not actually dismissed.

    Returns:
        ``{"open_questions": [...], "assumption_actions": [...]}`` on
        success. ``None`` on any failure (no key, network error, parse
        failure). On ``None`` the caller keeps the existing state — never
        a destructive default.
    """
    if not api_key or not model_name:
        return None
    parts = [
        *_system_prompt_openers(test_problem_id, current_problem_brief=None),
        _workflow_prompt(workflow_mode),
        STUDY_CHAT_OQ_MAINTAIN_TASK,
    ]
    gate_block = _gate_status_prompt_block(gate_status)
    if gate_block:
        parts.append(gate_block)
    system_instruction = "\n\n".join(parts)
    payload: dict[str, Any] = {
        "workflow_mode": workflow_mode,
        "user_message": str(user_message or ""),
        "visible_reply": str(visible_reply or ""),
        "current_open_questions": [
            {
                "id": str(q.get("id") or ""),
                "text": str(q.get("text") or ""),
            }
            for q in current_open_questions or []
            if isinstance(q, dict) and str(q.get("text") or "").strip()
        ],
        "recent_gathered": [str(t) for t in (recent_gathered or []) if str(t).strip()][:8],
    }
    # Only include current_assumptions in the payload when the workflow
    # actually uses them — keeps waterfall prompts uncluttered.
    mode_lower = str(workflow_mode or "").strip().lower()
    if mode_lower in ("agile", "demo") and current_assumptions:
        payload["current_assumptions"] = [
            {
                "id": str(a.get("id") or ""),
                "text": str(a.get("text") or ""),
            }
            for a in current_assumptions
            if isinstance(a, dict)
            and str(a.get("id") or "").strip()
            and str(a.get("text") or "").strip()
        ]
    user_text = json.dumps(payload, ensure_ascii=False, indent=2)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=OQ_MAINTAIN_RESPONSE_JSON_SCHEMA,
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
            "Definition-maintain Gemini raw response: %s",
            raw if raw is not None else "<no text>",
        )
        if isinstance(resp.parsed, dict):
            turn = OpenQuestionMaintenanceTurn.model_validate(resp.parsed)
        elif raw:
            turn = OpenQuestionMaintenanceTurn.model_validate_json(raw)
        else:
            return None
    except Exception as e:
        log.warning(
            "Definition-maintain structured call failed (%s); returning None", e
        )
        return None
    open_questions = [
        {
            "text": item.text.strip(),
            **({"id": item.id.strip()} if item.id and item.id.strip() else {}),
        }
        for item in turn.open_questions
        if item.text and item.text.strip()
    ]
    assumption_actions: list[dict[str, Any]] = []
    # Only honour assumption_actions on agile/demo turns. Even if the LLM
    # mistakenly emits them on a waterfall turn, the brief has no
    # assumption rows for them to act on, so dropping the field is safe.
    if mode_lower in ("agile", "demo"):
        for action in turn.assumption_actions:
            entry: dict[str, Any] = {
                "id": action.id.strip(),
                "action": action.action,
            }
            if action.rephrased_text and action.rephrased_text.strip():
                entry["rephrased_text"] = action.rephrased_text.strip()
            if entry["id"]:
                assumption_actions.append(entry)
    return {
        "open_questions": open_questions,
        "assumption_actions": assumption_actions,
    }


def maintain_open_questions(
    *,
    workflow_mode: str,
    user_message: str,
    visible_reply: str,
    current_open_questions: list[dict[str, Any]],
    recent_gathered: list[str],
    api_key: str,
    model_name: str,
    test_problem_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Backward-compat shim: returns just the open_questions list.

    New callers should use :func:`maintain_definition_state`, which also
    returns assumption-row decisions for agile/demo. This wrapper keeps
    older callers / monkey-patched tests working without forcing them to
    learn the richer return shape.
    """
    result = maintain_definition_state(
        workflow_mode=workflow_mode,
        user_message=user_message,
        visible_reply=visible_reply,
        current_open_questions=current_open_questions,
        current_assumptions=None,
        recent_gathered=recent_gathered,
        api_key=api_key,
        model_name=model_name,
        test_problem_id=test_problem_id,
    )
    if result is None:
        return None
    return result.get("open_questions") or []


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


_CONSOLIDATED_CHAT_OUTPUT_RULES = (
    "## Output format\n"
    "Return JSON only — no markdown fences around the JSON, no commentary outside the JSON object.\n"
    "All fields below are required.\n"
    "- `assistant_message` (string): the participant-visible reply. Write this first; "
    "be conversational, concise, and follow every guardrail in the sections above. "
    "Never include schema keys, JSON, or '```' fences inside `assistant_message` itself. "
    "If the user asked a concept question, answer it briefly and stop.\n"
    "- `cleanup_intent` (bool): true ONLY when the user explicitly asks to clean up, "
    "deduplicate, consolidate, tidy, or reorganize Definition items / open questions.\n"
    "- `clear_intent` (bool): true ONLY when the user explicitly asks to wipe Definition "
    "content and start over (e.g. 'reset everything', 'forget what I told you').\n"
    "- `is_change_intent` (bool): true when the user is asking the assistant to change the "
    "problem definition or solver configuration (add/remove/edit goals, constraints, weights, "
    "algorithm, settings). False for pure concept questions, knowledge lookups, clarifications, "
    "or casual chat that doesn't ask for any edit. When in doubt, return true.\n"
    "- `should_trigger_run` (bool): true ONLY when the user clearly intends to start a run NOW "
    "(direct request, OR affirmative reply to a recent assistant invitation to run). Never true "
    "for the auto-posted run-completion context lines that contain 'Run #N just completed'.\n"
    "- `intent_type` (enum: none|affirm_invite|direct_request): the kind of run intent above. "
    "Use 'none' when should_trigger_run is false.\n"
    "- `confidence` (number 0..1): how confident you are in the run-intent classification.\n"
    "- `is_run_invitation` (bool): true if `assistant_message` ITSELF asks the participant to "
    "start/trigger/launch a run now (so the next turn's affirmative reply can auto-fire). "
    "False for replies that only describe config changes or discuss possible future runs.\n"
    "- `change_clause` (string): when the user's message mixes an edit ask with a concept "
    "question (e.g. 'Yes, bump punctuality. Also, where do traffic times come from?'), put "
    "the edit half here — quote or lightly paraphrase the user's own words, NEVER expand "
    "their scope. If the user only asked a question or made small talk, leave this an empty "
    "string. If the entire message is an edit ask, copy the message verbatim. This string "
    "becomes the input to the hidden brief-update pass.\n"
    "- `question_clause` (string): the concept-question half of a mixed-intent turn. Empty "
    "string when the message has no question. The visible reply already addresses both "
    "halves; this field is for downstream observability only."
)


def generate_consolidated_chat_turn(
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
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> ConsolidatedChatTurn | None:
    """Single structured Gemini call: visible reply + intent flags.

    Returns ``None`` on any failure (no key, network error, schema parse twice).
    Callers should fall back to ``generate_visible_chat_reply`` plus
    regex-based intent classification on ``None``.
    """
    if not api_key or not model_name:
        return None

    base_system = _build_visible_chat_system_instruction(
        user_text=user_text,
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
        api_key=api_key,
        model_name=model_name,
        run_button_enabled=run_button_enabled,
        run_disabled_reason=run_disabled_reason,
        gate_status=gate_status,
    )
    system_instruction = f"{base_system}\n\n{_CONSOLIDATED_CHAT_OUTPUT_RULES}"

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=CONSOLIDATED_CHAT_TURN_RESPONSE_JSON_SCHEMA,
    )

    def _attempt() -> ConsolidatedChatTurn | None:
        try:
            chat = client.chats.create(
                model=model_name,
                config=config,
                history=_history_to_contents(history_lines),
            )
            resp = chat.send_message(user_text)
        except Exception as exc:
            log.warning("Consolidated chat-turn call failed (%s)", exc)
            return None
        # `resp.parsed` is the SDK's pre-validated dict; fall back to raw text.
        parsed: Any = resp.parsed
        if parsed is None:
            raw = resp.text or ""
            if not raw.strip():
                return None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return None
        if isinstance(parsed, ConsolidatedChatTurn):
            return parsed
        if isinstance(parsed, dict):
            try:
                return ConsolidatedChatTurn.model_validate(parsed)
            except Exception as exc:
                log.warning("Consolidated chat-turn validation failed (%s)", exc)
                return None
        return None

    turn = _attempt()
    if turn is not None:
        return turn
    # One retry — same SDK call, fresh chat session, no extra prompt mutation.
    # Schema parse failures are usually transient (truncated response, model
    # paraphrasing the schema) and clear on a second sample.
    log.info("Consolidated chat-turn first attempt failed; retrying once")
    return _attempt()


def generate_chat_turn(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
    current_panel: dict[str, Any] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_tutorial_active: bool = False,
    test_problem_id: str | None = None,
    run_button_enabled: bool | None = None,
    run_disabled_reason: str | None = None,
    gate_status: dict[str, Any] | None = None,
) -> ChatModelTurn:
    """Compatibility wrapper that now prioritizes the visible assistant reply."""
    try:
        text = generate_visible_chat_reply(
            user_text=user_text,
            history_lines=history_lines,
            api_key=api_key,
            model_name=model_name,
            current_problem_brief=current_problem_brief,
            workflow_mode=workflow_mode,
            current_panel=current_panel,
            recent_runs_summary=recent_runs_summary,
            researcher_steers=researcher_steers,
            cleanup_mode=cleanup_mode,
            is_run_acknowledgement=is_run_acknowledgement,
            is_tutorial_active=is_tutorial_active,
            test_problem_id=test_problem_id,
            run_button_enabled=run_button_enabled,
            run_disabled_reason=run_disabled_reason,
            gate_status=gate_status,
        )
    except Exception as e:
        log.warning("Visible chat failed (%s); using plain fallback", e)
        text = _plain_fallback_reply(
            user_text,
            history_lines,
            api_key,
            model_name,
            current_problem_brief,
            workflow_mode,
            current_panel,
            recent_runs_summary,
            researcher_steers,
            cleanup_mode,
            is_run_acknowledgement,
            is_tutorial_active=is_tutorial_active,
            test_problem_id=test_problem_id,
            run_button_enabled=run_button_enabled,
            run_disabled_reason=run_disabled_reason,
            gate_status=gate_status,
        )
    return ChatModelTurn(assistant_message=text, panel_patch=None)


def classify_run_trigger_intent(
    user_text: str,
    history_lines: list[tuple[str, str]],
    api_key: str,
    model_name: str,
    workflow_mode: str = "waterfall",
) -> RunTriggerIntentTurn:
    """
    Classify whether the latest participant message should trigger optimization.
    This is intent-only; router-level gate checks remain authoritative.
    """
    from app.routers.sessions import intent as session_intent

    if session_intent.is_run_acknowledgement_message(user_text):
        return RunTriggerIntentTurn()
    client = genai.Client(api_key=api_key)
    system_instruction = "\n\n".join(
        [
            "You classify whether the participant is asking to start optimization now.",
            _workflow_prompt(workflow_mode),
            (
                "Return JSON only. Set should_trigger_run=true only when the user clearly intends to start a run now, "
                "either by direct request (e.g., asking to run/start optimize) or by affirmative response to a recent "
                "assistant invitation to run. If intent is ambiguous, return should_trigger_run=false."
            ),
            (
                "Never set should_trigger_run=true for automated run-result context lines (e.g. messages containing "
                "\"Run #\" and \"just completed\", or \"Please interpret these results\") — those are not the user "
                "asking to start a new run."
            ),
            (
                "Set intent_type to one of: "
                "none (no clear run intent), affirm_invite (affirmative reply to run invitation), "
                "direct_request (explicit request to run now)."
            ),
        ]
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=RUN_TRIGGER_INTENT_RESPONSE_JSON_SCHEMA,
    )
    try:
        chat = client.chats.create(
            model=model_name,
            config=config,
            history=_history_to_contents(history_lines),
        )
        resp = chat.send_message(user_text)
        raw = resp.text
        if resp.parsed is not None:
            if isinstance(resp.parsed, RunTriggerIntentTurn):
                turn = resp.parsed
            elif isinstance(resp.parsed, dict):
                turn = RunTriggerIntentTurn.model_validate(resp.parsed)
            else:
                turn = RunTriggerIntentTurn()
        else:
            turn = RunTriggerIntentTurn.model_validate_json(raw or "{}")
        if not turn.should_trigger_run:
            return turn
        if turn.intent_type == "none":
            return RunTriggerIntentTurn(should_trigger_run=False, intent_type="none", confidence=turn.confidence)
        return turn
    except Exception as e:
        log.warning("Run-trigger intent classification failed (%s); defaulting to no-trigger", e)
        return RunTriggerIntentTurn()


def classify_assistant_run_invitation(
    assistant_text: str,
    api_key: str,
    model_name: str,
    workflow_mode: str = "waterfall",
) -> bool:
    """Classify whether the assistant reply is asking the participant to start a run."""
    from app.routers.sessions import intent as session_intent

    text = str(assistant_text or "").strip()
    if not text:
        return False
    if not api_key or not model_name:
        return session_intent.assistant_reply_is_asking_about_run(text)
    client = genai.Client(api_key=api_key)
    system_instruction = "\n\n".join(
        [
            "You classify whether an assistant message is inviting the participant to run optimization now.",
            _workflow_prompt(workflow_mode),
            (
                "Return JSON only with {\"is_run_invitation\": boolean}. "
                "True only when the assistant is asking to start/run/trigger optimization now "
                "(including forked prompts like 'run now or make other adjustments first?'). "
                "False for statements that only describe config changes or discuss possible future runs."
            ),
        ]
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=RUN_INVITATION_CLASSIFICATION_RESPONSE_JSON_SCHEMA,
    )
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=text,
            config=config,
        )
        parsed = resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
        return bool(parsed.get("is_run_invitation"))
    except Exception as e:
        log.warning("Assistant run-invitation classification failed (%s); falling back to regex", e)
        return session_intent.assistant_reply_is_asking_about_run(text)


def classify_definition_intents(
    content: str, api_key: str, model_name: str
) -> tuple[bool, bool, bool]:
    """Classify a user message as cleanup / clear / change intents.

    Returns ``(cleanup_intent, clear_intent, is_change_intent)``.

    ``is_change_intent`` gates the brief-update + panel-derivation pipelines:
    when False (concept questions, clarifications, knowledge lookups, casual
    chat) the server short-circuits both LLM calls.

    Falls back to regex on any LLM failure; the regex fallback returns
    ``is_change_intent=True`` conservatively so we don't drop a real edit.
    """
    from app.routers.sessions import intent as _intent

    # Fast path: the Definition-cleanup button posts a fixed string. No LLM call
    # is needed to classify it — both buttons (cleanup-definition, clear-state)
    # have stable, exact-match phrasings the frontend controls.
    fixed = _intent.classify_fixed_phrase_intents(content)
    if fixed is not None:
        return fixed

    if not api_key or not model_name:
        return (
            _intent.is_definition_cleanup_request(content),
            _intent.is_definition_clear_request(content),
            _intent.is_change_intent_fallback(content),
        )
    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=_DEFINITION_INTENT_SYSTEM,
            response_mime_type="application/json",
            response_json_schema=_DEFINITION_INTENT_JSON_SCHEMA,
        )
        chat = client.chats.create(model=model_name, config=config, history=[])
        resp = chat.send_message(content)
        data: dict[str, Any] = (
            resp.parsed if isinstance(resp.parsed, dict) else json.loads(resp.text or "{}")
        )
        # Schema marks is_change_intent required, but default True if the model
        # omits it so we never silently drop a real edit.
        change_intent = data.get("is_change_intent", True)
        return (
            bool(data.get("cleanup_intent")),
            bool(data.get("clear_intent")),
            bool(change_intent),
        )
    except Exception as e:
        log.warning("Definition intent classification failed (%s); falling back to regex", e)
        return (
            _intent.is_definition_cleanup_request(content),
            _intent.is_definition_clear_request(content),
            _intent.is_change_intent_fallback(content),
        )


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
    phase = resolve_workflow_phase(
        brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
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
            _phase_prompt(phase),
            port.config_derive_system_prompt(),
        ]
    )
    # Static per (model, workflow, phase, problem). Try explicit caching to cut input
    # tokens on the heavy gemini-pro derivation; if the SDK rejects (e.g. content below
    # the model's minimum), seamlessly fall back to inline system_instruction.
    cache_key = (
        "config_derive",
        model_name,
        workflow_mode,
        phase,
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
        if resp.parsed is not None:
            if isinstance(resp.parsed, dict):
                parsed = resp.parsed
            elif isinstance(resp.parsed, ChatModelTurn):
                parsed = resp.parsed.panel_patch or {}
            else:
                parsed = {}
        else:
            parsed = json.loads(raw) if raw else {}
        if not isinstance(parsed, dict) or not isinstance(parsed.get("problem"), dict):
            return None
        return {"problem": parsed["problem"]}
    except Exception as e:
        log.warning("Config derivation model failed (%s); falling back", e)
        return None
