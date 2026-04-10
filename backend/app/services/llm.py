"""Server-side Gemini via google-genai: use Chat API (chats.create + send_message), not raw generate_content."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from google import genai
from google.genai import types

from app.problem_brief import locked_goal_terms_prompt_section

from app.prompts.study_chat import (
    STUDY_CHAT_BRIEF_UPDATE_TASK,
    STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
    STUDY_CHAT_CONFIG_DERIVE_SYSTEM_PROMPT,
    STUDY_CHAT_PHASE_CONFIGURATION,
    STUDY_CHAT_PHASE_DISCOVERY,
    STUDY_CHAT_PHASE_STRUCTURING,
    STUDY_CHAT_RUN_ACK_AGILE,
    STUDY_CHAT_RUN_ACK_BASE,
    STUDY_CHAT_RUN_ACK_WATERFALL,
    STUDY_CHAT_STRUCTURED_JSON_RULES,
    STUDY_CHAT_SYSTEM_PROMPT,
    STUDY_CHAT_VISIBLE_REPLY_TASK,
    STUDY_CHAT_WORKFLOW_AGILE,
    STUDY_CHAT_WORKFLOW_WATERFALL,
)
from app.schemas import ChatModelTurn, ProblemBriefUpdateTurn, RunTriggerIntentTurn

log = logging.getLogger(__name__)

# Gemini rejects nested OpenAPI "additional_properties" when passing a Pydantic model as
# response_schema (dict[str, Any] becomes additionalProperties: true). Use response_json_schema
# with a hand-written schema instead. Keep it explicit around `problem.weights`, since a loose
# "object" schema lets malformed fragments like `{"weights": "{"}` slip through.
_WEIGHTS_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Only these objective keys exist — omit keys the user did not discuss. "
        "Never invent names; never add fuel_cost unless the user explicitly mentioned fuel, mileage, or operating/monetary cost."
    ),
    "properties": {
        "travel_time": {"type": "number"},
        "fuel_cost": {"type": "number"},
        "deadline_penalty": {"type": "number"},
        "capacity_penalty": {"type": "number"},
        "workload_balance": {"type": "number"},
        "worker_preference": {"type": "number"},
        "priority_penalty": {"type": "number"},
    },
    "additionalProperties": False,
}

# Union of all keys MEALpy accepts per algorithm (see app.algorithm_catalog / optimizer.py).
_ALGORITHM_PARAMS_PROPERTY_NAMES: tuple[str, ...] = (
    "pc",
    "pm",
    "c1",
    "c2",
    "w",
    "temp_init",
    "cooling_rate",
    "max_sub_iter",
    "t0",
    "t1",
    "move_count",
    "mutation_rate",
    "mutation_step_size",
    "mutation_step_size_damp",
    "sample_count",
    "intent_factor",
    "zeta",
)

_ALGORITHM_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Optional tuning object. Only use keys that exist for the selected algorithm — "
        "GA: pc, pm. PSO: c1, c2, w. SA: temp_init, cooling_rate. SwarmSA: max_sub_iter, t0, t1, "
        "move_count, mutation_rate, mutation_step_size, mutation_step_size_damp. "
        "ACOR: sample_count, intent_factor, zeta. "
        "Omit unless the user discussed hyperparameters; never invent other names."
    ),
    "properties": {name: {"type": "number"} for name in _ALGORITHM_PARAMS_PROPERTY_NAMES},
    "additionalProperties": False,
}

_DRIVER_PREFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vehicle_idx": {"type": "integer"},
        "condition": {
            "type": "string",
            "description": (
                "avoid_zone, order_priority, shift_over_limit; legacy: zone_d, express_order, shift_over_hours"
            ),
        },
        "penalty": {"type": "number"},
        "zone": {"type": "integer"},
        "order_priority": {
            "type": "string",
            "enum": ["express", "standard"],
            "description": "Must be exactly express or standard (not low/high synonyms).",
        },
        "limit_minutes": {"type": "number"},
        "hours": {"type": "number"},
        "aggregation": {"type": "string"},
    },
    "required": ["vehicle_idx", "condition", "penalty"],
    "additionalProperties": False,
}

_PROBLEM_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "weights": _WEIGHTS_OBJECT_SCHEMA,
        "only_active_terms": {"type": "boolean"},
        "driver_preferences": {
            "type": "array",
            "items": _DRIVER_PREFERENCE_SCHEMA,
        },
        "shift_hard_penalty": {"type": "number"},
        "locked_assignments": {
            "type": "object",
            "description": "Map task index string to vehicle index integer.",
            "additionalProperties": {"type": "integer"},
        },
        "algorithm": {
            "type": "string",
            "enum": ["GA", "PSO", "SA", "SwarmSA", "ACOR"],
        },
        "algorithm_params": _ALGORITHM_PARAMS_SCHEMA,
        "epochs": {"type": "integer"},
        "pop_size": {"type": "integer"},
        "random_seed": {"type": "integer"},
        "hard_constraints": {"type": "array", "items": {"type": "string"}},
        "soft_constraints": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_PANEL_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "problem": _PROBLEM_PATCH_SCHEMA,
    },
    "additionalProperties": False,
}

CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "PanelPatch",
    "type": "object",
    "properties": {
        "problem": _PROBLEM_PATCH_SCHEMA,
    },
    "required": ["problem"],
    "additionalProperties": False,
}

_PROBLEM_BRIEF_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": ["gathered", "assumption", "system"]},
        "source": {"type": "string", "enum": ["user", "upload", "agent", "system"]},
        "status": {"type": "string", "enum": ["active", "confirmed", "rejected"]},
        "editable": {"type": "boolean"},
    },
    "required": ["id", "text", "kind", "source", "status", "editable"],
}

_PROBLEM_BRIEF_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["id", "text"],
}

_PROBLEM_BRIEF_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal_summary": {"type": "string"},
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
        "solver_scope": {"type": "string"},
        "backend_template": {"type": "string"},
    },
}

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

BRIEF_UPDATE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "title": "ProblemBriefUpdateTurn",
    "type": "object",
    "properties": {
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
    return STUDY_CHAT_WORKFLOW_WATERFALL


def _phase_prompt(phase: WorkflowPhase) -> str:
    if phase == "configuration":
        return STUDY_CHAT_PHASE_CONFIGURATION
    if phase == "structuring":
        return STUDY_CHAT_PHASE_STRUCTURING
    return STUDY_CHAT_PHASE_DISCOVERY


def _run_ack_prompt(workflow_mode: str) -> str:
    wf_addendum = STUDY_CHAT_RUN_ACK_AGILE if workflow_mode == "agile" else STUDY_CHAT_RUN_ACK_WATERFALL
    return f"{STUDY_CHAT_RUN_ACK_BASE}\n{wf_addendum}"


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
        and str(item.get("kind") or "").strip().lower() != "system"
        and str(item.get("status") or "").strip().lower() != "rejected"
        and str(item.get("text") or "").strip()
    ]
    has_panel = bool(current_panel and isinstance(current_panel, dict))
    has_successful_run = any(bool(run.get("ok")) for run in (recent_runs_summary or []))

    if workflow_mode == "agile":
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
) -> str:
    phase = resolve_workflow_phase(
        current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
    brief_blob = (
        json.dumps(current_problem_brief, indent=2, ensure_ascii=False)
        if current_problem_brief
        else "{}"
    )
    parts = [
        STUDY_CHAT_SYSTEM_PROMPT,
        _workflow_prompt(workflow_mode),
        _phase_prompt(phase),
        STUDY_CHAT_STRUCTURED_JSON_RULES,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
    lock_structured = locked_goal_terms_prompt_section(current_panel or {})
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
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
) -> str:
    phase = resolve_workflow_phase(
        current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
    brief_blob = (
        json.dumps(current_problem_brief, indent=2, ensure_ascii=False)
        if current_problem_brief
        else "{}"
    )
    parts = [
        STUDY_CHAT_SYSTEM_PROMPT,
        _workflow_prompt(workflow_mode),
        _phase_prompt(phase),
        STUDY_CHAT_VISIBLE_REPLY_TASK,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
    lock_blob = locked_goal_terms_prompt_section(current_panel or {})
    if lock_blob:
        parts.append(lock_blob)
    if is_run_acknowledgement:
        parts.append(_run_ack_prompt(workflow_mode))
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


def _build_brief_update_system_instruction(
    current_problem_brief: dict[str, Any] | None,
    workflow_mode: str = "waterfall",
    current_panel: dict[str, Any] | None = None,
    recent_runs_summary: list[dict[str, Any]] | None = None,
    researcher_steers: list[str] | None = None,
    cleanup_mode: bool = False,
    is_run_acknowledgement: bool = False,
    is_answered_open_question: bool = False,
) -> str:
    phase = resolve_workflow_phase(
        current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
    )
    brief_blob = (
        json.dumps(current_problem_brief, indent=2, ensure_ascii=False)
        if current_problem_brief
        else "{}"
    )
    parts = [
        STUDY_CHAT_SYSTEM_PROMPT,
        _workflow_prompt(workflow_mode),
        _phase_prompt(phase),
        STUDY_CHAT_BRIEF_UPDATE_TASK,
        STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
    lock_blob = locked_goal_terms_prompt_section(current_panel or {})
    if lock_blob:
        parts.append(lock_blob)
    if cleanup_mode and current_panel and isinstance(current_panel, dict) and current_panel:
        parts.append(
            "Current saved **panel configuration** (authoritative numeric weights, algorithm, "
            "iterations, population, shift hard penalty, `only_active_terms`, algorithm_params, …). "
            "When you rewrite gathered rows (one row per objective or penalty term), **carry these "
            "values through** in plain language (e.g. “… weight is set to N”). The server merges "
            "slot-backed lines from this panel after cleanup, but matching the numbers here avoids "
            "confusing churn."
        )
        parts.append(json.dumps(current_panel, indent=2, ensure_ascii=False))
    if is_run_acknowledgement:
        parts.append(_run_ack_prompt(workflow_mode))
        if workflow_mode == "waterfall":
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
) -> str:
    system = _build_visible_chat_system_instruction(
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
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
) -> str:
    client = genai.Client(api_key=api_key)
    system_instruction = _build_visible_chat_system_instruction(
        current_problem_brief=current_problem_brief,
        workflow_mode=workflow_mode,
        current_panel=current_panel,
        recent_runs_summary=recent_runs_summary,
        researcher_steers=researcher_steers,
        cleanup_mode=cleanup_mode,
        is_run_acknowledgement=is_run_acknowledgement,
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
) -> ProblemBriefUpdateTurn:
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
    )
    history = _history_to_contents(history_lines)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=BRIEF_UPDATE_RESPONSE_JSON_SCHEMA,
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
        log.warning("Brief-update structured call failed (%s); returning empty patch", e)
        return ProblemBriefUpdateTurn()


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


def generate_config_from_brief(
    brief: dict[str, Any] | None,
    current_panel: dict[str, Any] | None,
    api_key: str,
    model_name: str,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
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
    system_instruction = "\n\n".join(
        [
            _workflow_prompt(workflow_mode),
            _phase_prompt(phase),
            STUDY_CHAT_CONFIG_DERIVE_SYSTEM_PROMPT,
        ]
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_json_schema=CONFIG_MODEL_PANEL_RESPONSE_JSON_SCHEMA,
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
