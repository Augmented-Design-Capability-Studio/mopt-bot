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
    locked_goal_terms_prompt_section,
    surface_problem_brief_for_chat_prompt,
)
from app.problems.registry import get_study_port

from app.prompts.study_chat import (
    STUDY_CHAT_BRIEF_UPDATE_TASK,
    STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
    STUDY_CHAT_OQ_CLASSIFY_TASK,
    STUDY_CHAT_PHASE_CONFIGURATION,
    STUDY_CHAT_PHASE_DISCOVERY,
    STUDY_CHAT_PHASE_STRUCTURING,
    STUDY_CHAT_RUN_ACK_AGILE,
    STUDY_CHAT_RUN_ACK_BASE,
    STUDY_CHAT_RUN_ACK_DEMO,
    STUDY_CHAT_RUN_ACK_WATERFALL,
    STUDY_CHAT_STRUCTURED_JSON_RULES,
    STUDY_CHAT_SYSTEM_PROMPT,
    STUDY_CHAT_VISIBLE_REPLY_TASK,
    STUDY_CHAT_WORKFLOW_AGILE,
    STUDY_CHAT_WORKFLOW_DEMO,
    STUDY_CHAT_WORKFLOW_WATERFALL,
)
from app.schemas import (
    ChatModelTurn,
    OpenQuestionClassification,
    OpenQuestionClassifierInput,
    OpenQuestionClassifierTurn,
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

_PROBLEM_BRIEF_PATCH_SCHEMA: dict[str, Any] = {
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
                    "choices": {"type": "array", "items": {"type": "string"}},
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
    },
    "required": ["cleanup_intent", "clear_intent"],
}

_DEFINITION_INTENT_SYSTEM = (
    "You are a lightweight intent classifier for a research optimization chat tool. "
    "Participants are study users writing free-form English messages.\n\n"
    "Classify the message for exactly two intents:\n"
    "- cleanup_intent: true if the user wants to remove, deduplicate, merge, tidy, or reorganize "
    "items in the Definition panel (e.g. 'tidy up the list', 'there are duplicates', "
    "'remove the repeated stuff', 'clean that up', 'consolidate the gathered items').\n"
    "- clear_intent: true if the user wants to wipe all Definition content and start over from "
    "scratch (e.g. 'start over', 'reset everything', 'forget what I told you', 'fresh start', "
    "'wipe the slate', 'begin again from zero').\n\n"
    "Return ONLY valid JSON. Default both to false when the message is ambiguous or off-topic."
)

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
    if api_key and model_name:
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
    if doc_excerpts:
        parts.append("Reference excerpts (participant-safe docs):")
        parts.append("\n\n".join(f"- {excerpt}" for excerpt in doc_excerpts))
    lock_blob = locked_goal_terms_prompt_section(current_panel or {}, test_problem_id=test_problem_id)
    if lock_blob:
        parts.append(lock_blob)
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
        STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
        "Current problem brief (compact authoritative memory for this turn):",
        brief_blob,
    ]
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
        is_config_save=is_config_save,
        is_upload_context=is_upload_context,
        is_tutorial_active=is_tutorial_active,
        test_problem_id=test_problem_id,
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


def classify_definition_intents(content: str, api_key: str, model_name: str) -> tuple[bool, bool]:
    """
    Classify whether a user message requests definition cleanup or a full clear.
    Returns (cleanup_intent, clear_intent). Falls back to regex on any failure.
    """
    from app.routers.sessions import intent as _intent

    if not api_key or not model_name:
        return _intent.is_definition_cleanup_request(content), _intent.is_definition_clear_request(content)
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
        return bool(data.get("cleanup_intent")), bool(data.get("clear_intent"))
    except Exception as e:
        log.warning("Definition intent classification failed (%s); falling back to regex", e)
        return _intent.is_definition_cleanup_request(content), _intent.is_definition_clear_request(content)


def generate_config_from_brief(
    brief: dict[str, Any] | None,
    current_panel: dict[str, Any] | None,
    api_key: str,
    model_name: str,
    workflow_mode: str = "waterfall",
    recent_runs_summary: list[dict[str, Any]] | None = None,
    test_problem_id: str | None = None,
    validation_feedback: list[dict[str, str]] | None = None,
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
    if validation_feedback:
        feedback_blob = json.dumps(validation_feedback, ensure_ascii=False)
        user_prompt += (
            "\nPrevious candidate was rejected by strict validation. "
            "Fix all listed issues and return a corrected `problem` object only.\n"
            f"Validation errors:\n{feedback_blob}\n"
        )
    port = get_study_port(test_problem_id)
    system_instruction = "\n\n".join(
        [
            _workflow_prompt(workflow_mode),
            _phase_prompt(phase),
            port.config_derive_system_prompt(),
        ]
    )
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
