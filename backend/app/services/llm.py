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
from app.problems.registry import get_study_port
from app.problems.schema_shared import goal_terms_schema

from app.prompts.study_chat import (
    STUDY_CHAT_AMBIGUITY_DISCIPLINE,
    STUDY_CHAT_BRIEF_UPDATE_TASK,
    STUDY_CHAT_GROUNDING_DISCIPLINE,
    STUDY_CHAT_HARD_CONSTRAINT_DISCIPLINE,
    STUDY_CHAT_HIDDEN_BRIEF_ITEMS_RULES,
    STUDY_CHAT_ITEMS_DISCIPLINE,
    STUDY_CHAT_OQ_CLASSIFY_TASK,
    STUDY_CHAT_OUT_OF_SCOPE_DISCIPLINE,
    STUDY_CHAT_SANDBOX_RULES,
    STUDY_CHAT_SEARCH_STRATEGY_ANCHORING,
    STUDY_CHAT_SYSTEM_PROMPT,
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
    },
    "required": ["id", "text"],
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
            "run_summary": {"type": "string"},
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
    commit_audit_note: str | None = None,
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
    # Pre-release gate audit (retry-only): when an earlier draft of this turn
    # committed to a run-CTA but the deterministic post-commit gate check
    # showed the Run button would still be DISABLED, the router rejects the
    # draft and re-prompts the LLM with this audit block. Two valid
    # resolutions: (1) fix the structural gap so the gate actually opens, or
    # (2) soften the visible reply so it stops inviting the participant to
    # click Run.
    if commit_audit_note and commit_audit_note.strip():
        parts.append(
            "## Pre-release gate audit (revise this draft)\n\n"
            + commit_audit_note.strip()
            + "\n\n"
            "Pick exactly one resolution:\n"
            "- **Fix the gap**: emit the missing structured carrier in `problem_brief_patch` "
            "(the items[] row that anchors the commitment, plus the matching "
            "`goal_terms` / algorithm assumption as the gap requires).\n"
            "- **Soften the visible reply**: do not invite the participant to click "
            "**Run optimization**; instead, state what's still missing and ask one focused "
            "question (or commit the missing piece on this turn).\n"
            "Do NOT keep the run-invitation phrasing while leaving the gap open."
        )
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
            "change_clause": {"type": "string"},
            "question_clause": {"type": "string"},
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
                    "exist there). Use `promote_to_gathered` when the user "
                    "confirmed the assumption; `drop` when the user invalidated "
                    "it; `rephrase` for wording corrections; `keep` is the default."
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
        },
        "required": ["assistant_message"],
    }


_MAIN_TURN_OUTPUT_RULES = (
    "## Output rules\n\n"
    "You emit ONE structured response carrying everything the server needs for "
    "this turn — visible reply, intent flags, brief patch, and (agile/demo only) "
    "per-row assumption decisions. The server does NOT call a separate brief LLM. "
    "Plan the patch in lockstep with the visible reply so claims and structural "
    "deltas stay consistent — the server's verification step will flag mismatches "
    "and force a retry that costs an extra round-trip.\n\n"
    "Algorithm carrier: when your visible reply commits to a search-strategy "
    "algorithm (agile starting default, user-named choice, post-result switch), "
    "ALSO populate `problem_brief_patch.goal_terms.search_strategy.properties."
    "algorithm` with one of: GA, PSO, SA, SwarmSA, ACOR. The panel-derive step "
    "reads this structured field — don't rely on items[] prose extraction.\n\n"
    "Maintenance: include the full new open_questions list when you intend a "
    "replacement (set `replace_open_questions=true`); otherwise emit only the "
    "rows you are adding/keeping. Use `assumption_actions` for explicit "
    "per-row decisions on existing assumption rows in agile/demo."
)


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
            "Acknowledge the change in your visible reply and, where the user's "
            "edit implies further structural updates (rephrasing related rows, "
            "adjusting goal terms / weights / algorithm to fit, asking about "
            "consequences), emit those updates in `problem_brief_patch`. Do NOT "
            "echo back what the user just typed verbatim."
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
        parts.append(
            "## Answered-open-question context\n\n"
            "The participant just answered an open question. Promote the "
            "Q+A into a `gathered` items[] row (agile/demo) or refresh the "
            "OQ with a concrete answer-record (waterfall). Set "
            "`replace_open_questions=true` only if your full list "
            "consolidates the change."
        )
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
            + "\n".join(issue_lines)
        )

    system_instruction = "\n\n".join(parts)
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
