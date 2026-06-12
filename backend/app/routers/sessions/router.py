"""Sessions API router."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from threading import Thread
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import Principal, require_any_study_user, require_client, require_researcher
from app.config import get_settings
from app.crypto_util import encrypt_secret
from app.database import SessionLocal, _resolve_sqlite_url, get_db
from app.problems.registry import DEFAULT_PROBLEM_ID, get_study_port as _get_study_port, register_study_ports
from app.models import ChatMessage, OptimizationRun, SessionSnapshot, StudySession
from app.optimization_gate import can_run_optimization
from app.problem_brief import (
    coerce_problem_brief_for_workflow,
    default_problem_brief,
    merge_problem_brief_patch,
    normalize_problem_brief,
    resolve_upload_open_questions_after_upload,
)
from app.schemas import (
    CleanupOpenQuestionsBody,
    MessageCreate,
    MessageOut,
    ModelSettingsBody,
    OpenQuestionClassifierInput,
    ParticipantPanelUpdate,
    ParticipantProblemBriefUpdate,
    ParticipantTutorialUpdate,
    PostMessagesResponse,
    ResearcherSimulateParticipantUploadBody,
    RunEvaluateEditBody,
    RunOut,
    SessionCreate,
    SessionProcessingState,
    SessionOut,
    SessionPatch,
    SnapshotOut,
    SolveRunCreate,
    SteerCreate,
    serialize_utc_datetime,
)
from app.session_export import EXPORT_SCHEMA_VERSION, build_export_timeline
from app.session_snapshots import EVENT_BEFORE_RUN, EVENT_BOOKMARK, EVENT_MANUAL_SAVE, create_snapshot

from . import context, derivation, helpers, intent, sync

router = APIRouter(prefix="/sessions", tags=["sessions"])
log = logging.getLogger(__name__)
SIMULATED_UPLOAD_MESSAGE_PREFIX = "I'm uploading the following file(s): "


def _route_oq_answers_through_classifier(
    *,
    incoming_brief: dict[str, Any],
    persisted_open_questions: list[dict[str, Any]],
    workflow_mode: str,
    api_key: str | None,
    model_name: str,
    test_problem_id: str | None,
) -> dict[str, Any]:
    """Mutate `incoming_brief` so newly-answered OQs are rephrased + bucketed by the LLM.

    For each OQ that flipped to status="answered" with non-empty answer_text:
    - bucket="gathered": drop the OQ, append a `gathered` item with the rephrased text.
    - bucket="assumption" (agile/demo only): drop the OQ, append an `assumption` item.
    - bucket="new_open_question" (waterfall only): replace the OQ with a simpler plain-text
      re-ask of the same decision.
    Inputs the classifier doesn't return (or that fail mode-gating) stay as answered OQs
    so the legacy `_promote_answered_open_questions_to_gathered` step in normalization
    handles them as fallback.
    """
    if not api_key:
        return incoming_brief
    open_questions = incoming_brief.get("open_questions") or []
    if not isinstance(open_questions, list):
        return incoming_brief

    persisted_by_id = {
        str(q.get("id") or ""): q
        for q in persisted_open_questions
        if isinstance(q, dict)
    }

    inputs: list[OpenQuestionClassifierInput] = []
    for q in open_questions:
        if not isinstance(q, dict):
            continue
        if str(q.get("status") or "").strip().lower() != "answered":
            continue
        answer = str(q.get("answer_text") or "").strip()
        if not answer:
            continue
        qid = str(q.get("id") or "").strip()
        prior = persisted_by_id.get(qid)
        already_answered = (
            prior is not None
            and str(prior.get("status") or "open").strip().lower() == "answered"
        )
        if already_answered:
            continue
        text = str(q.get("text") or "").strip()
        if not text:
            continue
        inputs.append(
            OpenQuestionClassifierInput(
                question_id=qid or text,
                question_text=text,
                answer_text=answer,
            )
        )

    if not inputs:
        return incoming_brief

    from app.services.llm import classify_answered_open_questions

    classifications = classify_answered_open_questions(
        inputs=inputs,
        workflow_mode=workflow_mode,
        current_problem_brief=incoming_brief,
        api_key=api_key,
        model_name=model_name,
        test_problem_id=test_problem_id,
    )
    if not classifications:
        return incoming_brief

    classified_by_id: dict[str, Any] = {}
    for entry in classifications:
        classified_by_id[str(entry.question_id)] = entry

    from app.problem_brief import FOUNDATIONAL_OQ_TOPICS

    mode = (workflow_mode or "").strip().lower()
    next_questions: list[dict[str, Any]] = []
    items = list(incoming_brief.get("items") or [])
    seeded_goal_term = False

    def _reset_oq_to_open(parent_q: dict[str, Any]) -> dict[str, Any]:
        """Revert an OQ to its open state when the user's answer was
        hedged / a counter-question / a request for explanation. The
        OQ's original text stays unchanged — the user can answer it
        properly after seeing the agent's explanation. The synthetic
        chat note quotes what the participant typed, and the main-turn
        LLM picks it up via ``STUDY_CHAT_ANSWERED_OQ_CONTEXT``.
        """
        cleared = dict(parent_q)
        cleared["status"] = "open"
        cleared["answer_text"] = None
        return cleared

    for q in open_questions:
        if not isinstance(q, dict):
            next_questions.append(q)
            continue
        qid = str(q.get("id") or "").strip()
        c = classified_by_id.get(qid) or classified_by_id.get(str(q.get("text") or "").strip())
        if c is None:
            next_questions.append(q)
            continue

        parent_topic = str(q.get("topic") or "other").strip() or "other"
        parent_is_foundational = parent_topic in FOUNDATIONAL_OQ_TOPICS

        if c.bucket == "new_open_question" and mode == "waterfall":
            # Counter-question / unresolved hedge: reset the OQ to open
            # regardless of topic. We used to create a `*-followup` OQ
            # with classifier-generated text — that drift produced:
            #  (a) for foundational parents: a duplicate alongside the
            #      canonical monitor row
            #  (b) for any parent: a long explanation-style OQ text that
            #      kept the participant from re-answering cleanly
            # The synthetic chat note quotes the participant's hedge text
            # and `STUDY_CHAT_ANSWERED_OQ_CONTEXT` instructs the LLM to
            # explain in chat. The OQ's original text is preserved so the
            # user can answer the same question after reading.
            next_questions.append(_reset_oq_to_open(q))
            continue

        if c.bucket == "assumption" and mode in ("agile", "demo"):
            # Foundational + hedged: don't auto-promote a counter-question
            # into an algorithm/upload/goal assumption row. Reset and let
            # the chat explanation flow handle it.
            if parent_is_foundational:
                next_questions.append(_reset_oq_to_open(q))
                continue
            assumption_text = (c.assumption_text or "").strip()
            if not assumption_text:
                next_questions.append(q)
                continue
            items.append(
                {
                    "id": f"item-assumption-from-question-{qid}" if qid else f"item-assumption-{len(items)}",
                    "text": assumption_text,
                    "kind": "assumption",
                    "source": "agent",
                }
            )
            continue

        if c.bucket == "gathered":
            rephrased = (c.rephrased_text or "").strip()
            if not rephrased:
                next_questions.append(q)
                continue
            # Foundational search-strategy answer → commit the STRUCTURED carrier,
            # not a free-text row. The algorithm choice's canonical home is
            # ``goal_terms.search_strategy.properties.algorithm`` (mirrored to the
            # panel + the synthesized ``config-search-strategy`` row). Recorded as
            # a prose ``item-gathered-from-question-*`` row it would be swept by the
            # structured-items whitelist on the very next chat turn, flipping
            # ``brief_mentions_search_strategy`` False and bouncing the OQ back open
            # — so "Use GA" never stuck (P_lk). Resolve the OQ once the carrier is
            # set; an answer naming no recognizable method stays open for a retry.
            if parent_topic == "search_strategy":
                from app.routers.sessions.derivation import (
                    _set_search_strategy_algorithm,
                    _validated_algorithm_name,
                )

                algo = _validated_algorithm_name(q.get("answer_text")) or _validated_algorithm_name(
                    rephrased
                )
                if algo:
                    incoming_brief = _set_search_strategy_algorithm(incoming_brief, algo)
                    continue
                next_questions.append(_reset_oq_to_open(q))
                continue
            proposal = getattr(c, "goal_term_proposal", None)
            proposal_key = (
                proposal.key.strip()
                if proposal is not None and isinstance(proposal.key, str)
                else ""
            )
            # The answer is "about a goal term" when the classifier proposes one
            # OR the answered OQ was anchored to one (its ``goal_key``). Either
            # way the term's single record is its canonical
            # ``config-weight-<key>`` row — we never mint a separate
            # "from-question" prose row beside it. That covers BOTH a tuning
            # answer ("yes, raise it") AND a DECLINE ("not now"), which used to
            # leave a no-op "Capacity penalty remains at weight 1.0 …" row next
            # to the real weight row (P_0602).
            term_key = proposal_key or str(q.get("goal_key") or "").strip()
            if term_key:
                goal_terms = incoming_brief.get("goal_terms")
                if not isinstance(goal_terms, dict):
                    goal_terms = {}
                has_main_entry = term_key in goal_terms or any(
                    isinstance(it, dict)
                    and (
                        str(it.get("id") or "") == f"config-weight-{term_key}"
                        or str(it.get("goal_key") or "").strip() == term_key
                    )
                    for it in items
                )
                if proposal_key and proposal_key not in goal_terms:
                    # A brand-new term was endorsed: seed it and anchor it to its
                    # canonical row (synthesized at the end of this function);
                    # the brief → panel sync then attaches the weight. (The
                    # panel-derive prompt can't invent keys from prose, so this
                    # bridge is what gets a newly-endorsed term onto the panel.)
                    existing_ranks = [
                        int(entry.get("rank"))
                        for entry in goal_terms.values()
                        if isinstance(entry, dict)
                        and isinstance(entry.get("rank"), (int, float))
                        and not isinstance(entry.get("rank"), bool)
                    ]
                    next_rank = (max(existing_ranks) + 1) if existing_ranks else 1
                    goal_terms[proposal_key] = {
                        "weight": 1.0,
                        "type": proposal.type,
                        "rank": next_rank,
                        "evidence_item_ids": [f"config-weight-{proposal_key}"],
                    }
                    incoming_brief["goal_terms"] = goal_terms
                    seeded_goal_term = True
                    has_main_entry = True
                if has_main_entry:
                    continue  # canonical row is the record — no prose row
            # No goal-term link — a genuine standalone fact (not about a
            # weighted term), so keep it as a gathered row.
            gathered_item_id = (
                f"item-gathered-from-question-{qid}" if qid else f"item-gathered-{len(items)}"
            )
            items.append(
                {
                    "id": gathered_item_id,
                    "text": rephrased,
                    "kind": "gathered",
                    "source": "user",
                }
            )
            continue

        # Mode mismatch (e.g. classifier emitted assumption for waterfall) — leave the OQ
        # answered so legacy normalization promotes it the old way.
        next_questions.append(q)

    incoming_brief["items"] = items
    incoming_brief["open_questions"] = next_questions
    if seeded_goal_term:
        # Materialize the canonical ``config-weight-<key>`` row for each
        # endorsed term NOW so it exists when the brief → panel anchor check
        # runs — otherwise the freshly-seeded term (whose evidence points at
        # that row) would look unanchored and get dropped. Idempotent
        # drop-and-replace by id, so existing rows just refresh.
        from app.routers.sessions.derivation import _synthesize_canonical_weight_items

        incoming_brief = _synthesize_canonical_weight_items(
            incoming_brief, test_problem_id
        )
    return incoming_brief


def _structure_companion_rule_edits(
    *,
    incoming_brief: dict[str, Any],
    test_problem_id: str | None,
    api_key: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Deterministically structure companion rules the participant typed into a
    goal term's ``config-weight-<key>`` "Rules —" summary on the definition panel.

    That row is server-synthesized, so a free-text edit to it ("…and Carol skips
    express orders") never reaches the structured carrier on its own. Here, at the
    save, we detect an edited companion row (its text differs from what the current
    carrier would synthesize) and run the focused structured extractor to populate
    the carrier. Generic (port ``gate_conditional_companions`` + extraction
    instructions); fail-safe (any error leaves the brief untouched).
    """
    if not test_problem_id or not api_key or not model_name:
        return incoming_brief
    try:
        from app.problems.registry import get_study_port
        from app.problem_brief import synthesize_canonical_goal_term_items
        from app.services import llm

        port = get_study_port(test_problem_id)
        gate = port.gate_conditional_companions() or {}
        if not gate:
            return incoming_brief
    except Exception:  # pragma: no cover — never block the save
        return incoming_brief

    gt = incoming_brief.get("goal_terms") if isinstance(incoming_brief.get("goal_terms"), dict) else {}
    if not gt:
        return incoming_brief
    row_text = {
        str(it.get("id") or ""): str(it.get("text") or "")
        for it in (incoming_brief.get("items") or [])
        if isinstance(it, dict)
    }
    try:
        baseline = {
            str(r.get("id") or ""): str(r.get("text") or "")
            for r in synthesize_canonical_goal_term_items(incoming_brief, test_problem_id)
        }
    except Exception:  # pragma: no cover
        baseline = {}

    out = incoming_brief
    for key, field in gate.items():
        if key not in gt:
            continue
        rid = f"config-weight-{key}"
        edited = row_text.get(rid, "").strip()
        # Only fire when the participant actually changed the summary's text (so an
        # unrelated def-panel save doesn't burn an extraction call).
        if not edited or edited == baseline.get(rid, "").strip():
            continue
        entry = gt.get(key) if isinstance(gt.get(key), dict) else {}
        props = entry.get("properties") if isinstance(entry.get("properties"), dict) else {}
        current = props.get(field) if isinstance(props.get(field), list) else []
        new_rules = llm.extract_companion_rules(
            test_problem_id=test_problem_id,
            goal_term_key=key,
            companion_field=field,
            source_text=edited,
            current_rules=current,
            api_key=api_key,
            model_name=model_name,
        )
        if not isinstance(new_rules, list) or new_rules == current:
            continue
        out = dict(out)
        ngt = dict(out.get("goal_terms") or {})
        nentry = dict(ngt.get(key) or {})
        nprops = dict(nentry.get("properties") or {})
        nprops[field] = new_rules
        nentry["properties"] = nprops
        # Drop the agent's stale narration so the synthesized row falls back to the
        # port's real rationale instead of "Mapped … to the worker_preference module".
        nentry.pop("ambiguity_note", None)
        ngt[key] = nentry
        out["goal_terms"] = ngt
        gt = ngt
    return out


def _session_has_uploaded_data(db: Session, session_id: str) -> bool:
    return (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
            ChatMessage.content.like(f"{SIMULATED_UPLOAD_MESSAGE_PREFIX}%"),
        )
        .first()
        is not None
    )


def _parse_simulated_upload_file_names(content: str) -> list[str]:
    if not content.startswith(SIMULATED_UPLOAD_MESSAGE_PREFIX):
        return []
    return [name.strip() for name in content[len(SIMULATED_UPLOAD_MESSAGE_PREFIX) :].split(",") if name.strip()]


def _run_gate_blocked_message(row: StudySession, brief_obj: dict[str, Any], has_uploaded_data: bool) -> str:
    mode = str(row.workflow_mode or "").strip().lower()
    if bool(row.optimization_runs_blocked_by_researcher):
        return "I can run optimization once the researcher re-enables runs for this session."
    # Uniform across all modes: upload required.
    if not has_uploaded_data:
        return (
            "I can start a run after you add a simulated upload using the **Upload file(s)...** "
            "button in the chat footer (exact label)."
        )
    # Uniform across all modes: gate must have been engaged (first chat message
    # OR a meaningful panel/definition edit).
    if not bool(getattr(row, "optimization_gate_engaged", False)):
        return (
            "I can start a run after we engage — either send your first chat message or "
            "save a change in the Problem Config panel."
        )
    # Waterfall-only: open questions must be resolved.
    if mode == "waterfall":
        open_questions = brief_obj.get("open_questions") or []
        if any(isinstance(q, dict) and str(q.get("status") or "").strip().lower() == "open" for q in open_questions):
            return "I can start a run after all open questions in the Definition tab are answered."
    return (
        "I can start a run once the configuration includes at least one objective weight "
        "(or its companion property, like driver preferences) and a selected search algorithm."
    )


def _resolve_new_session_test_problem_id(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return DEFAULT_PROBLEM_ID
    pid = str(raw).strip().lower()
    if pid not in register_study_ports():
        raise HTTPException(status_code=400, detail=f"Unknown test_problem_id: {pid}")
    return pid


@router.post("", response_model=SessionOut)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_any_study_user),
):
    tpid = _resolve_new_session_test_problem_id(body.test_problem_id)
    row = StudySession(
        id=str(uuid.uuid4()),
        workflow_mode=body.workflow_mode,
        participant_number=helpers.clean_participant_number(body.participant_number),
        test_problem_id=tpid,
        status="active",
        panel_config_json=None,
        problem_brief_json=json.dumps(default_problem_brief(tpid)),
        processing_revision=0,
        brief_status="ready",
        config_status="idle",
        processing_error=None,
        optimization_allowed=False,
        participant_tutorial_enabled=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.get("/for-participant", response_model=list[SessionOut])
def list_sessions_for_participant(
    participant_number: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """List sessions for the given participant number (participant-facing, safe filter)."""
    cleaned = helpers.clean_participant_number(participant_number)
    if not cleaned:
        raise HTTPException(status_code=400, detail="participant_number required")
    lower_val = cleaned.lower()
    rows = (
        db.query(StudySession)
        .filter(
            StudySession.participant_number.isnot(None),
            func.lower(StudySession.participant_number) == lower_val,
        )
        .order_by(StudySession.updated_at.desc())
        .limit(30)
        .all()
    )
    return [helpers.session_to_out(r) for r in rows]


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    rows = db.query(StudySession).order_by(StudySession.updated_at.desc()).all()
    return [helpers.session_to_out(r) for r in rows]


@router.post("/{session_id}/participant-starter-panel", response_model=SessionOut)
def push_participant_starter_panel(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Apply a mediocre default problem JSON so the participant can see panel 2 / run the solver."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    port = _get_study_port(row.test_problem_id)
    # Sanitize first so the stored panel uses the canonical `goal_terms` map
    # (not just legacy `weights` / `constraint_types`). Drift detection and
    # mirror-aware checks both read the canonical form.
    starter_panel, _starter_warnings = port.sanitize_panel_config(
        port.mediocre_participant_starter_config()
    )
    row.panel_config_json = json.dumps(starter_panel)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    # Mirror the (sanitized) starter panel into the brief so every panel
    # goal term has a matching definition row. The mirror only touches
    # brief.items[] / brief.goal_terms — it does NOT set `topic_engaged`,
    # which only flips when the brief-update LLM judges the conversation has
    # arrived at the problem-module's topic. That keeps the cold-start
    # prompt path (upload OQ, neutral framing, sandbox rules) firing on the
    # first participant turn while still leaving the drift banner quiet.
    sync.sync_problem_brief_from_panel(row, db, starter_panel)
    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)
    return helpers.session_to_out(row)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    return helpers.session_to_out(row)


@router.get("/{session_id}/researcher", response_model=SessionOut)
def get_session_researcher(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return helpers.session_to_out(row)


def _snapshot_to_out(snap: SessionSnapshot) -> SnapshotOut:
    """Build SnapshotOut from a SessionSnapshot row."""
    brief: dict[str, Any] | None = None
    panel: dict[str, Any] | None = None
    items_count = 0
    questions_count = 0
    has_config = False
    if snap.problem_brief_json:
        try:
            brief = json.loads(snap.problem_brief_json)
            items_count = len(brief.get("items") or [])
            questions_count = len(brief.get("open_questions") or [])
        except (json.JSONDecodeError, TypeError):
            pass
    if snap.panel_config_json:
        try:
            panel = json.loads(snap.panel_config_json)
            has_config = bool(panel and panel.get("problem"))
        except (json.JSONDecodeError, TypeError):
            pass
    return SnapshotOut(
        id=snap.id,
        created_at=snap.created_at,
        event_type=snap.event_type or "before_run",
        items_count=items_count,
        questions_count=questions_count,
        has_config=has_config,
        problem_brief=brief,
        panel_config=panel,
    )


@router.get("/{session_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_client),
):
    """List snapshots for the session (brief+panel history)."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    snaps = (
        db.query(SessionSnapshot)
        .filter(SessionSnapshot.session_id == session_id)
        .order_by(SessionSnapshot.created_at.desc())
        .all()
    )
    return [_snapshot_to_out(s) for s in snaps]


@router.post("/{session_id}/snapshots", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED)
def post_session_snapshot_bookmark(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Bookmark current saved brief+panel as a snapshot without PATCHing session (no chat message)."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    snap = create_snapshot(db, session_id, EVENT_BOOKMARK)
    if snap is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _snapshot_to_out(snap)


@router.patch("/{session_id}", response_model=SessionOut)
def patch_session(
    session_id: str,
    body: SessionPatch,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.workflow_mode is not None:
        row.workflow_mode = body.workflow_mode
    if body.test_problem_id is not None:
        row.test_problem_id = str(body.test_problem_id).strip().lower()[:64] or DEFAULT_PROBLEM_ID
    if "participant_number" in body.model_fields_set:
        row.participant_number = helpers.clean_participant_number(body.participant_number)
    if body.panel_config is not None:
        row.panel_config_json = json.dumps(body.panel_config)
    if body.problem_brief is not None:
        row.problem_brief_json = json.dumps(
            coerce_problem_brief_for_workflow(body.problem_brief, row.workflow_mode)
        )
    if body.optimization_allowed is not None:
        row.optimization_allowed = body.optimization_allowed
    if body.optimization_runs_blocked_by_researcher is not None:
        row.optimization_runs_blocked_by_researcher = body.optimization_runs_blocked_by_researcher
    if body.allow_agent_autorun is not None:
        row.allow_agent_autorun = body.allow_agent_autorun
    if "agile_oq_every_n_runs" in body.model_fields_set:
        # ``null`` clears to off; a number sets the cadence (0 never, 1 every,
        # N≥2 = one OQ per N runs).
        row.agile_oq_every_n_runs = body.agile_oq_every_n_runs
    if body.participant_tutorial_enabled is not None:
        row.participant_tutorial_enabled = body.participant_tutorial_enabled
    if "tutorial_step_override" in body.model_fields_set:
        row.tutorial_step_override = body.tutorial_step_override
        helpers.rewind_tutorial_tracking_from_step(row, row.tutorial_step_override)
    if body.gemini_model is not None:
        row.gemini_model = body.gemini_model
    if body.embedding_model is not None:
        row.embedding_model = body.embedding_model
    if body.gemini_api_key is not None:
        row.gemini_key_encrypted = encrypt_secret(body.gemini_api_key)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/{session_id}/terminate", response_model=SessionOut)
def terminate_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    row.status = "terminated"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/{session_id}/reset", response_model=SessionOut)
def reset_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Clear session activity while preserving participant id and model/key settings."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.query(OptimizationRun).filter(OptimizationRun.session_id == session_id).delete()
    db.query(SessionSnapshot).filter(SessionSnapshot.session_id == session_id).delete()
    row.status = "active"
    row.panel_config_json = None
    pid = str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID)
    row.problem_brief_json = json.dumps(default_problem_brief(pid))
    row.content_reset_revision = int(getattr(row, "content_reset_revision", 0) or 0) + 1
    row.optimization_allowed = False
    row.optimization_runs_blocked_by_researcher = False
    row.optimization_gate_engaged = False
    row.tutorial_step_override = None
    row.tutorial_chat_started = False
    row.tutorial_uploaded_files = False
    row.tutorial_definition_tab_visited = False
    row.tutorial_definition_saved = False
    row.tutorial_config_tab_visited = False
    row.tutorial_config_first_saved = False
    row.tutorial_config_saved = False
    row.tutorial_first_run_done = False
    row.tutorial_second_run_done = False
    row.tutorial_run_summary_read = False
    row.tutorial_results_inspected = False
    row.tutorial_explain_used = False
    row.tutorial_candidate_marked = False
    row.tutorial_third_run_done = False
    row.tutorial_completed = False
    helpers.settle_processing_state(row, cancel_revision=True)
    row.config_status = "idle"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/export-db")
def export_sessions_db(
    background_tasks: BackgroundTasks,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Export a subset of sessions (and their child rows) into a fresh
    SQLite file the researcher can download. Used as a "save before
    delete" step — the UI selects sessions, downloads them as a
    standalone .db, then deletes them from the live DB.

    Only SQLite source DBs are supported; the response is the raw
    SQLite file (octet-stream).
    """
    session_ids = body.get("session_ids") or []
    if not isinstance(session_ids, list) or not all(isinstance(x, str) for x in session_ids):
        raise HTTPException(status_code=400, detail="session_ids must be a list of strings")
    if not session_ids:
        raise HTTPException(status_code=400, detail="session_ids is empty")

    settings = get_settings()
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise HTTPException(
            status_code=501,
            detail="export-db only supports SQLite source databases",
        )
    # Resolve through the same backend-anchored helper the engine uses so we
    # read the real study DB regardless of the server's cwd (otherwise a
    # relative URL points at a stray /data file under the process cwd).
    src_path = _resolve_sqlite_url(url)[len("sqlite:///"):]

    # Subset to ids that actually exist — silently skip phantoms so the
    # researcher gets a clean file even if the UI's list drifted from
    # the DB by a row or two.
    existing = {
        r[0]
        for r in db.query(StudySession.id).filter(StudySession.id.in_(session_ids)).all()
    }
    keep = [sid for sid in session_ids if sid in existing]
    if not keep:
        raise HTTPException(
            status_code=404,
            detail="None of the requested session_ids exist in the DB",
        )

    fd, out_path = tempfile.mkstemp(prefix="mopt-sessions-", suffix=".db")
    os.close(fd)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(out_path)
    try:
        # Defer FK enforcement so we can insert child rows even if
        # they're loaded before their parent (table copy order is
        # alphabetical via sqlite_master; doesn't matter for correctness).
        dst.execute("PRAGMA foreign_keys=OFF")
        # Copy schema (tables + indexes; views/triggers not used here).
        for (sql,) in src.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type IN ('table','index') AND sql IS NOT NULL "
            "  AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            dst.execute(sql)
        # Copy the chosen sessions and their child rows. SQLite caps
        # bound parameters at 999 per statement; chunk to stay safe.
        chunk = 500

        def _copy_filtered(table: str, id_column: str) -> None:
            cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 0").description]
            col_list = ",".join(cols)
            ph = ",".join("?" * len(cols))
            for i in range(0, len(keep), chunk):
                batch = keep[i : i + chunk]
                placeholders = ",".join("?" * len(batch))
                rows = src.execute(
                    f"SELECT {col_list} FROM {table} WHERE {id_column} IN ({placeholders})",
                    batch,
                ).fetchall()
                if rows:
                    dst.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({ph})", rows)

        _copy_filtered("sessions", "id")
        _copy_filtered("messages", "session_id")
        _copy_filtered("runs", "session_id")
        _copy_filtered("session_snapshots", "session_id")
        dst.commit()
    finally:
        src.close()
        dst.close()

    # Best-effort cleanup once the response has finished streaming.
    background_tasks.add_task(_safe_unlink, out_path)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"mopt-sessions-{len(keep)}-{ts}.db"
    return FileResponse(
        out_path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"X-Exported-Session-Count": str(len(keep))},
    )


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Hard-delete a session and its cascaded children (messages, runs,
    snapshots). Idempotent — a missing row returns 204 (success), not 404.

    The 404-on-missing behaviour bricked the researcher's bulk-delete loop:
    if any one ID had already been removed (e.g. duplicate click, stale
    sidebar list after a manual DB wipe), the frontend's per-iteration
    `await apiFetch(...)` threw, aborted the rest of the batch, and the
    refresh-list call after the loop never ran — so the UI kept showing
    sessions that were already gone from the DB.
    """
    row = db.get(StudySession, session_id)
    if row is None:
        return None  # treat missing as already-deleted (idempotent)
    db.delete(row)
    db.commit()
    return None


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def list_messages(
    session_id: str,
    after_id: int = 0,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    q = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.visible_to_participant.is_(True),
            ChatMessage.id > after_id,
        )
        .order_by(ChatMessage.id.asc())
    )
    return list(q.all())


@router.get("/{session_id}/messages/researcher", response_model=list[MessageOut])
def list_messages_researcher(
    session_id: str,
    after_id: int = 0,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    q = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id, ChatMessage.id > after_id)
        .order_by(ChatMessage.id.asc())
    )
    return list(q.all())


@router.get("/{session_id}/messages/{message_id}", response_model=MessageOut)
def get_single_message(
    session_id: str,
    message_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Fetch a single message by id. Used by the frontend to refresh messages
    whose ``meta.verifying`` flag is still set - the standard list endpoint's
    ``after_id`` filter excludes already-seen ids, so verification updates that
    rewrite content / clear flags need a direct refetch path."""
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    msg = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.id == message_id,
            ChatMessage.visible_to_participant.is_(True),
        )
        .first()
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg



def _handle_post_participant_message(session_id: str, db: Session, body: MessageCreate) -> PostMessagesResponse:
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    out: list[MessageOut] = []
    # Typed context discriminator from the frontend (set on synthetic posts —
    # run-ack, config-save, etc.). When present it short-circuits the legacy
    # regex classifiers below; when absent we still fall back to content
    # matching for older sessions / programmatic posts.
    context_kind = body.context_kind
    is_run_ack = intent.is_run_acknowledgement_message(body.content, context_kind)
    user_visible = not is_run_ack
    um = derivation.append_message(db, session_id, "user", body.content, user_visible)
    if user_visible:
        out.append(MessageOut.model_validate(um))
    updated_panel: dict | None = None
    updated_problem_brief: dict | None = None
    proc_state: SessionProcessingState | None = None
    uploaded_file_names = _parse_simulated_upload_file_names(body.content)
    if uploaded_file_names:
        row.tutorial_uploaded_files = True
        current_problem_brief = helpers.problem_brief_dict(row)
        next_problem_brief = resolve_upload_open_questions_after_upload(current_problem_brief, uploaded_file_names)
        if next_problem_brief != current_problem_brief:
            row.problem_brief_json = json.dumps(next_problem_brief)
            updated_problem_brief = next_problem_brief
        helpers.touch_session(row)
        db.commit()
        db.refresh(row)

    if body.invoke_model:
        from app.crypto_util import decrypt_secret

        key = decrypt_secret(row.gemini_key_encrypted)
        model = row.gemini_model or get_settings().default_gemini_model
        if not key:
            am = derivation.append_message(
                db,
                session_id,
                "assistant",
                "No model API key is configured. Open settings and add a key, or continue without AI.",
                True,
            )
            out.append(MessageOut.model_validate(am))
            proc_state = helpers.processing_state(db.get(StudySession, session_id) or row)
        else:
            # Mark processing pending BEFORE the (potentially multi-second) model call so any
            # client polling during the call window sees the in-flight state and shows a
            # response-spinner bubble. Without this, researcher-driven posts (e.g. simulated
            # uploads via /researcher/simulate-participant-upload) and any other path where
            # the participant frontend has no local aiPending hook would have no indication
            # that an AI reply is being prepared until the assistant message itself arrives.
            # The patch / else / interpret-only branches below still set the final state
            # (settle to "ready" or keep "pending" if background derivation was launched).
            helpers.mark_processing_pending(row)
            db.commit()
            db.refresh(row)
            hist, researcher_steers, recent_runs_summary = context.load_turn_context(db, session_id, um.id)
            text = "The model request failed. Try again or continue without AI."
            current = helpers.panel_dict(row)
            current_problem_brief = helpers.problem_brief_dict(row)
            updated_panel = current
            is_answer_save = intent.is_answered_open_question_message(
                body.content, context_kind
            )
            is_config_save = intent.is_config_save_context_message(
                body.content, context_kind
            )
            is_brief_edit_ack = intent.is_brief_edit_context_message(
                body.content, context_kind
            )
            # Set when the participant message is the synthetic "I'm uploading the
            # following file(s): …" line. The brief already grew a canonical
            # `item-gathered-upload` row in the upload-OQ block above; signaling
            # this to the LLM keeps it from emitting a parallel upload-tracking
            # gathered row that would visually duplicate the marker.
            is_upload_context = bool(uploaded_file_names)
            # Demo mode reuses tutorial guardrails to keep agent output narrow
            # for screen recordings, even though no bubbles are shown to the
            # participant. See plans note: "demo mode = guardrails on, bubbles
            # off".
            is_demo_mode = str(row.workflow_mode or "").strip().lower() == "demo"
            is_tutorial_active = bool(
                is_demo_mode
                or (
                    getattr(row, "participant_tutorial_enabled", False)
                    and not getattr(row, "tutorial_completed", False)
                )
            )
            # Run-button awareness: tell the chat turn whether the participant
            # can actually click **Run optimization** right now, so the agent
            # doesn't promise to start a run that isn't yet permitted. Pairs
            # with the "## Run-button awareness" section in the system prompt.
            try:
                _has_upload = _session_has_uploaded_data(db, session_id)
                run_button_enabled_for_chat = can_run_optimization(
                    row.workflow_mode,
                    row.optimization_allowed,
                    row.optimization_runs_blocked_by_researcher,
                    current,
                    current_problem_brief,
                    has_uploaded_data=_has_upload,
                    optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
                    problem_id=str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
                )
                run_disabled_reason_for_chat = (
                    None
                    if run_button_enabled_for_chat
                    else _run_gate_blocked_message(row, current_problem_brief, _has_upload)
                )
                from app.optimization_gate import gate_status as _gate_status_fn
                gate_status_for_chat = _gate_status_fn(
                    row.workflow_mode,
                    current,
                    current_problem_brief,
                    optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
                    problem_id=str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
                )
            except Exception:
                log.exception("Run-readiness probe failed for session %s; omitting from chat prompt", session_id)
                run_button_enabled_for_chat = None
                run_disabled_reason_for_chat = None
                gate_status_for_chat = None

            # The main-turn LLM owns the visible reply, intent flags, brief
            # patch, and OQ/assumption maintenance in one structured call.
            # The router persists a placeholder assistant message immediately
            # and hands off to ``chat_pipeline_runner.run_chat_pipeline`` which
            # fills the bubble (and the per-stage status checklist)
            # asynchronously.
            from app.services import pipeline_status as _ps_module
            from app.services.chat_pipeline_runner import run_chat_pipeline

            flavor: _ps_module.PipelineFlavor
            if is_run_ack:
                flavor = "run_ack"
            elif is_config_save:
                flavor = "config_edit_ack"
            elif is_brief_edit_ack:
                flavor = "brief_edit_ack"
            else:
                flavor = "chat"

            placeholder_meta: dict[str, Any] = {
                "verifying": True,
                "pipeline": _ps_module.initial_pipeline_status(flavor),
            }
            placeholder = derivation.append_message(
                db,
                session_id,
                "assistant",
                # Visible while S1 runs. The runner overwrites this with the
                # LLM's reply on success, or with a clear failure message on
                # transport / parse failure. The dimmed ``bubble--verifying``
                # CSS class on the frontend further signals the in-flight state.
                "Drafting a reply…",
                True,
                kind="chat",
                meta=placeholder_meta,
            )
            # Bump revision so any prior background job aborts.
            revision = helpers.mark_processing_pending(row)
            db.commit()
            db.refresh(row)

            # Controlled-study lever (agile): on a post-run turn, the server
            # pre-decides via blocked randomization whether THIS turn raises an
            # open question or commits an assumption, per the researcher-set
            # cadence. Returns None (no directive → soft bias) off-study.
            post_run_directive = None
            if is_run_ack:
                from app.services.agile_post_run_schedule import post_run_oq_directive

                _completed_run_number = max(
                    (int(r.get("run_number") or 0) for r in (recent_runs_summary or [])),
                    default=0,
                )
                post_run_directive = post_run_oq_directive(
                    session_id=session_id,
                    run_number=_completed_run_number,
                    every_n_runs=getattr(row, "agile_oq_every_n_runs", None),
                    workflow_mode=row.workflow_mode,
                )

            run_chat_pipeline(
                session_id=session_id,
                revision=revision,
                message_id=placeholder.id,
                flavor=flavor,
                user_text=body.content,
                workflow_mode=row.workflow_mode,
                api_key=key,
                model_name=model,
                history_lines=hist,
                researcher_steers=researcher_steers,
                recent_runs_summary=recent_runs_summary,
                base_problem_brief=current_problem_brief,
                base_panel=current,
                is_run_acknowledgement=is_run_ack,
                is_brief_edit_ack=is_brief_edit_ack,
                is_config_save=is_config_save,
                is_upload_context=is_upload_context,
                is_answered_open_question=is_answer_save,
                is_tutorial_active=is_tutorial_active,
                test_problem_id=row.test_problem_id,
                gate_status=gate_status_for_chat,
                skip_derive_config=is_config_save,
                post_run_directive=post_run_directive,
            )

            # Return immediately — the frontend polls the placeholder
            # message until its ``meta.verifying`` clears.
            out.append(MessageOut.model_validate(placeholder))
            proc_state = helpers.processing_state(
                db.get(StudySession, session_id) or row
            )
            return PostMessagesResponse(
                messages=out,
                panel_config=helpers.panel_dict(row),
                problem_brief=helpers.problem_brief_dict(row),
                processing=proc_state,
            )


@router.post("/{session_id}/messages", response_model=PostMessagesResponse)
def post_message(
    session_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    return _handle_post_participant_message(session_id, db, body)


@router.post("/{session_id}/researcher/simulate-participant-upload", response_model=PostMessagesResponse)
def researcher_simulate_participant_upload(
    session_id: str,
    body: ResearcherSimulateParticipantUploadBody | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Post the same user-visible message as a simulated upload (for demos / dry runs)."""
    b = body or ResearcherSimulateParticipantUploadBody()
    names = list(b.file_names) if b.file_names else ["DRIVER_INFO.csv", "ORDERS.csv"]
    cleaned = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_names must not be empty")
    content = f"I'm uploading the following file(s): {', '.join(cleaned)}"
    return _handle_post_participant_message(
        session_id,
        db,
        MessageCreate(
            content=content,
            invoke_model=b.invoke_model,
            skip_hidden_brief_update=False,
            context_kind="simulated_upload",
        ),
    )


@router.post("/{session_id}/steer", response_model=MessageOut)
def post_steer(
    session_id: str,
    body: SteerCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    m = derivation.append_message(db, session_id, "researcher", body.content, False)
    return MessageOut.model_validate(m)


def _post_optimization_cancel(session_id: str, db: Session) -> dict[str, bool]:
    """Signal an in-flight optimize (same session) to stop early; no-op if none running."""
    from app.solve_cancel import request_cancel

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"signalled": request_cancel(session_id)}


@router.post("/{session_id}/runs/cancel")
def post_cancel_optimization_runs_cancel(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    return _post_optimization_cancel(session_id, db)


@router.post("/{session_id}/optimization/cancel")
def post_cancel_optimization_alt_path(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Same as POST .../runs/cancel; alternate path for proxies that mishandle `/runs/cancel`."""
    return _post_optimization_cancel(session_id, db)


@router.post("/{session_id}/runs/reset-stuck")
def post_reset_stuck_runs(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    """Researcher recovery: clear a hung/stuck in-progress run so the
    participant UI stops showing a permanent spinner. Signals any still-live
    solver to stop and marks non-terminal placeholder run rows as failed."""
    from app.solve_cancel import request_cancel

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    signalled = request_cancel(session_id)
    cleared = helpers.terminate_stuck_runs(db, session_id, "Run reset by researcher")
    if cleared:
        db.commit()
    return {"signalled": signalled, "cleared": cleared}


@router.post("/{session_id}/runs", response_model=RunOut)
def post_run(
    session_id: str,
    body: SolveRunCreate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    from app.problems.exceptions import RunCancelled
    from app.problems.registry import get_study_port
    from app.solve_cancel import clear_cancel_event, register_cancel_event

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    panel_obj: dict[str, Any] | None = None
    if row.panel_config_json:
        try:
            parsed = json.loads(row.panel_config_json)
            panel_obj = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            panel_obj = None
    try:
        brief_obj = json.loads(row.problem_brief_json) if row.problem_brief_json else default_problem_brief()
    except json.JSONDecodeError:
        brief_obj = default_problem_brief()

    run_type = str(body.type).lower()
    if run_type == "optimize":
        if not can_run_optimization(
            row.workflow_mode,
            row.optimization_allowed,
            row.optimization_runs_blocked_by_researcher,
            panel_obj,
            brief_obj,
            has_uploaded_data=_session_has_uploaded_data(db, session_id),
            optimization_gate_engaged=bool(getattr(row, "optimization_gate_engaged", False)),
            problem_id=str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Optimization is not allowed (researcher block, or intrinsic readiness not met and no permit)",
            )

    payload = {
        "type": body.type,
        "problem": body.problem,
        "routes": body.routes,
        "candidate_seed_run_ids": body.candidate_seed_run_ids,
        "candidate_seeds": body.candidate_seeds,
    }
    session_run_number = helpers.next_session_run_number(db, session_id)
    run_row = OptimizationRun(
        session_run_index=session_run_number,
        session_id=session_id,
        run_type=body.type,
        request_json=json.dumps(payload),
        ok=False,
    )
    db.add(run_row)
    db.commit()
    db.refresh(run_row)

    create_snapshot(db, session_id, EVENT_BEFORE_RUN)

    cancel_ev = register_cancel_event(session_id) if run_type == "optimize" else None
    try:
        timeout = get_settings().solve_timeout_sec
        port = get_study_port(row.test_problem_id)
        result = port.solve_request_to_result(payload, timeout, cancel_event=cancel_ev)
        run_row.ok = True
        run_row.cost = float(result["cost"])
        run_row.reference_cost = (
            float(result["reference_cost"]) if result.get("reference_cost") is not None else None
        )
        run_row.result_json = json.dumps(result)
        run_row.error_message = None
    except RunCancelled:
        run_row.error_message = "Optimization cancelled"
    except TimeoutError:
        run_row.error_message = "Optimization timed out"
    except ValueError as e:
        run_row.error_message = str(e)
    except ImportError as e:
        log.exception("Optimization import error for session %s", session_id)
        run_row.error_message = f"Solver import error: {e}"
    except Exception:
        log.exception("Optimization run failed for session %s", session_id)
        run_row.error_message = "Optimization failed"
    finally:
        if cancel_ev is not None:
            clear_cancel_event(session_id)

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run_row)

    result_dict: dict[str, Any] | None = None
    if run_row.result_json:
        try:
            parsed = json.loads(run_row.result_json)
            result_dict = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            result_dict = None
    summary_port = get_study_port(row.test_problem_id)
    summary = summary_port.format_optimization_run_chat_summary(
        session_run_number=session_run_number,
        run_ok=bool(run_row.ok),
        cost=float(run_row.cost) if run_row.cost is not None else None,
        result=result_dict,
        error_message=run_row.error_message,
    )
    derivation.append_message(db, session_id, "assistant", summary, True, kind="run")
    return helpers.run_to_out(run_row)


def _normalize_routes_for_compare(raw: Any) -> list[list[int]] | None:
    if not isinstance(raw, list):
        return None
    if all(isinstance(row, dict) and isinstance(row.get("task_indices"), list) for row in raw):
        out_obj: list[list[int]] = []
        for row in raw:
            task_indices = row.get("task_indices")
            if not isinstance(task_indices, list):
                return None
            vals_obj: list[int] = []
            for value in task_indices:
                try:
                    vals_obj.append(int(value))
                except (TypeError, ValueError):
                    return None
            out_obj.append(vals_obj)
        return out_obj
    out: list[list[int]] = []
    for row in raw:
        if not isinstance(row, list):
            return None
        vals: list[int] = []
        for value in row:
            try:
                vals.append(int(value))
            except (TypeError, ValueError):
                return None
        out.append(vals)
    return out


def _routes_equal(a: Any, b: Any) -> bool:
    na = _normalize_routes_for_compare(a)
    nb = _normalize_routes_for_compare(b)
    return na is not None and nb is not None and na == nb


@router.post("/{session_id}/runs/{run_id}/evaluate-edit", response_model=RunOut)
def post_evaluate_edit_run(
    session_id: str,
    run_id: int,
    body: RunEvaluateEditBody,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    from app.problems.registry import get_study_port

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    run_row = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id, OptimizationRun.id == run_id)
        .first()
    )
    if run_row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    payload = {"type": "evaluate", "problem": body.problem, "routes": body.routes}
    timeout = get_settings().solve_timeout_sec
    port = get_study_port(row.test_problem_id)

    try:
        result = port.solve_request_to_result(payload, timeout, cancel_event=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        log.exception("Run edit-evaluate failed for session %s run %s", session_id, run_id)
        raise HTTPException(status_code=500, detail="Evaluate failed") from None

    req_old: dict[str, Any] | None = None
    if run_row.request_json:
        try:
            parsed = json.loads(run_row.request_json)
            req_old = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            req_old = None
    res_old: dict[str, Any] | None = None
    if run_row.result_json:
        try:
            parsed = json.loads(run_row.result_json)
            res_old = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            res_old = None

    original_snapshot = (
        res_old.get("original_snapshot")
        if isinstance(res_old, dict) and isinstance(res_old.get("original_snapshot"), dict)
        else {
            "request": req_old,
            "result": res_old,
            "cost": run_row.cost,
            "reference_cost": run_row.reference_cost,
            "ok": bool(run_row.ok),
            "error_message": run_row.error_message,
        }
    )

    original_result = original_snapshot.get("result") if isinstance(original_snapshot, dict) else None
    original_schedule = original_result.get("schedule") if isinstance(original_result, dict) else None
    original_routes = original_schedule.get("routes") if isinstance(original_schedule, dict) else None

    if _routes_equal(body.routes, original_routes):
        if not isinstance(original_result, dict):
            raise HTTPException(status_code=500, detail="Original run snapshot missing; cannot restore")
        restored_result = dict(original_result)
        restored_result.pop("edited_evaluation", None)
        restored_result.pop("original_snapshot", None)
        run_row.ok = bool(original_snapshot.get("ok", True))
        run_row.cost = (
            float(original_snapshot["cost"])
            if original_snapshot.get("cost") is not None
            else None
        )
        run_row.reference_cost = (
            float(original_snapshot["reference_cost"])
            if original_snapshot.get("reference_cost") is not None
            else None
        )
        run_row.result_json = json.dumps(restored_result)
        run_row.error_message = (
            str(original_snapshot.get("error_message"))
            if original_snapshot.get("error_message") is not None
            else None
        )
    else:
        result_out: dict[str, Any] = dict(result)
        result_out["original_snapshot"] = original_snapshot
        result_out["edited_evaluation"] = {
            "edited_at": serialize_utc_datetime(datetime.now(timezone.utc)),
            "request": payload,
            "cost": float(result["cost"]),
            "reference_cost": float(result["reference_cost"]) if result.get("reference_cost") is not None else None,
        }

        run_row.ok = True
        run_row.cost = float(result["cost"])
        run_row.reference_cost = float(result["reference_cost"]) if result.get("reference_cost") is not None else None
        run_row.result_json = json.dumps(result_out)
        run_row.error_message = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run_row)
    return helpers.run_to_out(run_row)


@router.get("/{session_id}/runs", response_model=list[RunOut])
def list_runs(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_any_study_user),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if principal == Principal.client and row.status == "deleted":
        raise HTTPException(status_code=410, detail="Session removed")
    rows = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id)
        .order_by(OptimizationRun.id.asc())
        .all()
    )
    return [helpers.run_to_out(r) for r in rows]


@router.delete("/{session_id}/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(
    session_id: str,
    run_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    run = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.session_id == session_id, OptimizationRun.id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return None


@router.patch("/{session_id}/settings", response_model=SessionOut)
def patch_participant_model_settings(
    session_id: str,
    body: ModelSettingsBody,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    if body.gemini_model is not None:
        row.gemini_model = body.gemini_model
    if body.embedding_model is not None:
        row.embedding_model = body.embedding_model
    if body.gemini_api_key is not None:
        row.gemini_key_encrypted = encrypt_secret(body.gemini_api_key)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.patch("/{session_id}/panel", response_model=SessionOut)
def patch_participant_panel(
    session_id: str,
    body: ParticipantPanelUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    from app.problems.registry import get_study_port

    port = get_study_port(row.test_problem_id)

    # Only validate goal_terms when the participant actually changed them.
    # A pre-existing mismatch (e.g. a stale LLM-hallucinated key) shouldn't
    # block a save that only edits unrelated fields like algorithm or epochs;
    # the Recover banner is the path to clean that up.
    submitted_problem = (
        body.panel_config.get("problem")
        if isinstance(body.panel_config.get("problem"), dict)
        else body.panel_config
    )
    submitted_goal_terms = (
        submitted_problem.get("goal_terms") if isinstance(submitted_problem, dict) else None
    )
    current_panel = helpers.panel_dict(row)
    current_problem = (
        current_panel.get("problem")
        if isinstance(current_panel, dict) and isinstance(current_panel.get("problem"), dict)
        else current_panel
    )
    current_goal_terms = (
        current_problem.get("goal_terms") if isinstance(current_problem, dict) else None
    )
    goal_terms_changed = submitted_goal_terms != current_goal_terms

    if goal_terms_changed:
        try:
            # Reverse validation on a participant-driven panel save: the user
            # is authoritative, so the validator only enforces structural
            # invariants (shape / type enum / goal_term_order). The legacy
            # `weight_slot_markers` and `check_grounding` kwargs are now
            # `**_unused` on validate_problem_goal_terms — they were the
            # marker-based hallucination check, removed when the
            # structured-output schema became the primary defense. Don't call
            # `port.weight_slot_markers()` here either; the per-problem ports
            # no longer expose it (knapsack and vrptw dropped the method when
            # the markers tables were retired).
            sync.validate_problem_goal_terms(
                problem=submitted_problem,
                problem_brief=helpers.problem_brief_dict(row),
            )
        except sync.GoalTermValidationError as exc:
            # Set processing_error so the Recover banner appears on the next
            # session refresh; still 422 because the submitted goal_terms are
            # rejected and not persisted.
            helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
            db.commit()
            db.refresh(row)
            raise HTTPException(status_code=422, detail=exc.detail_text()) from exc
    sanitized_config, weight_warnings = port.sanitize_panel_config(body.panel_config)

    # Detect goal-term removals BEFORE the panel→brief mirror runs so we can
    # report any item-cascade back to the participant. ``current_goal_terms`` was
    # captured above for the goal-term-change gate; here we just resolve the
    # post-sanitize new map and diff the key sets.
    sanitized_problem = (
        sanitized_config.get("problem")
        if isinstance(sanitized_config.get("problem"), dict)
        else sanitized_config
    )
    new_goal_terms = (
        sanitized_problem.get("goal_terms")
        if isinstance(sanitized_problem, dict)
        else None
    )
    removed_goal_term_keys: set[str] = set()
    cascade_strip_count = 0
    if isinstance(current_goal_terms, dict) and isinstance(new_goal_terms, dict):
        removed_goal_term_keys = {
            k for k in current_goal_terms.keys() if k not in new_goal_terms
        }
        if removed_goal_term_keys:
            prior_brief = helpers.problem_brief_dict(row)
            prior_items = (
                prior_brief.get("items") if isinstance(prior_brief, dict) else None
            )
            try:
                cascade_strip_count = len(
                    port.brief_item_ids_to_strip_on_goal_term_removal(
                        removed_keys=removed_goal_term_keys,
                        prior_goal_terms=current_goal_terms,
                        brief_items=list(prior_items or []),
                    )
                )
            except Exception:  # pragma: no cover — never block the save on a cascade hiccup
                cascade_strip_count = 0

    row.panel_config_json = json.dumps(sanitized_config)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    sync.sync_problem_brief_from_panel(row, db, sanitized_config)
    helpers.settle_processing_state(row)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)

    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)

    # Deterministic ack now carries server-side warnings only — the user-
    # facing change summary lives in the LLM-generated reply triggered by
    # the `context_kind: "config_save"` chat post (see saveConfig in
    # useClientSessionActions.ts + STUDY_CHAT_CONFIG_SAVE_RATIONALE). Format
    # as a bullet list so the bubble matches the LLM reply visually.
    ack_lines: list[str] = []
    if body.acknowledgement:
        ack_lines.append(body.acknowledgement.strip())
    for w in weight_warnings:
        ack_lines.append(f"- {w}")
    if cascade_strip_count > 0:
        labels = port.weight_item_labels()
        removed_labels = sorted(labels.get(k, k) for k in removed_goal_term_keys)
        joined = ", ".join(removed_labels)
        plural = "row" if cascade_strip_count == 1 else "rows"
        ack_lines.append(
            f"- Removed {joined}; cleared {cascade_strip_count} related brief {plural}."
        )
    ack = "\n".join(line for line in ack_lines if line).strip()
    if ack:
        derivation.append_message(db, session_id, "assistant", ack, True, kind="panel")
    return helpers.session_to_out(row)


@router.patch("/{session_id}/problem-brief", response_model=SessionOut)
def patch_participant_problem_brief(
    session_id: str,
    body: ParticipantProblemBriefUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    from app.crypto_util import decrypt_secret

    # Capture persisted open questions BEFORE we coerce the incoming brief so we can
    # diff and route just-answered OQs through the LLM classifier.
    persisted_brief_raw: dict[str, Any]
    try:
        persisted_brief_raw = json.loads(row.problem_brief_json) if row.problem_brief_json else {}
    except json.JSONDecodeError:
        persisted_brief_raw = {}
    persisted_open_questions = persisted_brief_raw.get("open_questions") or []
    if not isinstance(persisted_open_questions, list):
        persisted_open_questions = []

    incoming_brief = body.problem_brief.model_dump()
    incoming_brief = _route_oq_answers_through_classifier(
        incoming_brief=incoming_brief,
        persisted_open_questions=[q for q in persisted_open_questions if isinstance(q, dict)],
        workflow_mode=row.workflow_mode or "waterfall",
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
        test_problem_id=row.test_problem_id,
    )
    # Structure any companion rules the participant typed into a goal term's
    # "Rules —" summary on the definition panel (e.g. VRPTW driver preferences)
    # right here at the save — deterministic, independent of the follow-up chat
    # turn's classification or the agent's behaviour. The synthesized row regen
    # and panel sync below then reflect the populated carrier.
    incoming_brief = _structure_companion_rule_edits(
        incoming_brief=incoming_brief,
        test_problem_id=row.test_problem_id,
        api_key=decrypt_secret(row.gemini_key_encrypted),
        model_name=row.gemini_model or get_settings().default_gemini_model,
    )

    next_problem_brief = coerce_problem_brief_for_workflow(
        incoming_brief,
        row.workflow_mode,
    )
    # Stage the brief on the row but DON'T commit yet — we want brief + panel
    # to land atomically when the LLM derivation produces a structurally clean
    # panel. If structural validation on the derived panel fails, we fall back
    # to the deterministic per-port seed (which is hand-written and always
    # structurally valid). Only if the seed itself is inconsistent with the
    # current panel's locked state do we accept the brief alone and surface a
    # Recover banner — preserving the participant's typed input across the
    # rare derivation failure rather than rolling it back.
    row.problem_brief_json = json.dumps(next_problem_brief)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)

    panel_sync_failed = False
    try:
        sync.sync_panel_from_problem_brief(
            row,
            db,
            next_problem_brief,
            api_key=decrypt_secret(row.gemini_key_encrypted),
            model_name=row.gemini_model or get_settings().default_gemini_model,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=True,
            commit=False,
        )
        helpers.settle_processing_state(row)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    except sync.GoalTermValidationError as exc:
        # The LLM-derived panel didn't validate structurally. Retry once with
        # the deterministic seed (no LLM, no managed-field preservation) — the
        # seed is hand-written per port and should always validate. If even
        # that fails we accept the brief alone and surface a Recover banner;
        # the participant's typed brief is preserved either way.
        db.rollback()
        db.refresh(row)
        row.problem_brief_json = json.dumps(next_problem_brief)
        helpers.settle_processing_state(row, cancel_revision=True)
        row.updated_at = datetime.now(timezone.utc)
        try:
            sync.sync_panel_from_problem_brief(
                row,
                db,
                next_problem_brief,
                api_key=None,
                model_name=None,
                workflow_mode=row.workflow_mode,
                preserve_missing_managed_fields=False,
                commit=False,
            )
            helpers.settle_processing_state(row)
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(row)
            log.warning(
                "Brief PATCH for session %s recovered from goal-term validation via deterministic seed",
                session_id,
            )
        except sync.GoalTermValidationError as exc2:
            # Even the seed was rejected — accept the brief alone, leave panel
            # stale, surface Recover banner.
            db.rollback()
            db.refresh(row)
            row.problem_brief_json = json.dumps(next_problem_brief)
            helpers.fail_processing_state(row, exc2.processing_error_text(), cancel_revision=True)
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(row)
            panel_sync_failed = True
            derivation.append_message(
                db,
                session_id,
                "assistant",
                "Saved your Definition, but I couldn't re-derive Problem Config — the goal-term keys are "
                "out of sync. Use the **Recover** button in the banner above the tabs to clear the "
                "conflicting goal terms and re-derive a clean Problem Config.",
                True,
                kind="panel",
            )

    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)

    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)

    if body.acknowledgement and not panel_sync_failed:
        derivation.append_message(db, session_id, "assistant", body.acknowledgement, True, kind="panel")
    return helpers.session_to_out(row)


@router.post("/{session_id}/cleanup-open-questions", response_model=SessionOut)
def cleanup_participant_open_questions(
    session_id: str,
    body: CleanupOpenQuestionsBody,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Deterministic open-question cleanup.

    The main chat pipeline owns OQ lifecycle (add/drop/keep/rephrase) on
    every turn, so a participant-triggered cleanup just runs the
    deterministic pass: strip duplicates, prune empties, then re-coerce
    for the active workflow mode. Anything semantic that requires the
    LLM should arrive via a chat message instead.
    """
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    from app.problem_brief import cleanup_open_questions

    current_problem_brief = helpers.problem_brief_dict(row)
    cleaned_brief, meta = cleanup_open_questions(current_problem_brief)
    # The brief-cleanup endpoint used to migrate run-related items[] rows
    # into the legacy ``run_summary`` rolling string. ``brief.runs`` is now
    # server-managed via ``consolidate_runs`` and doesn't need a cleanup hook;
    # this call is now a no-op on a non-run-ack turn. Kept for symmetry with
    # the brief-cleanup flow (any future per-turn invariants ride here).
    cleaned_brief, run_meta = derivation.consolidate_runs(
        cleaned_brief,
        recent_runs_summary=[],
        is_run_acknowledgement=False,
        test_problem_id=row.test_problem_id,
    )
    cleaned_brief = coerce_problem_brief_for_workflow(cleaned_brief, row.workflow_mode)
    if cleaned_brief != current_problem_brief:
        row.problem_brief_json = json.dumps(cleaned_brief)
        helpers.touch_session(row)
        db.commit()
        db.refresh(row)
    log.info(
        "Deterministic open-question cleanup metadata for session %s: %s",
        session_id,
        {**meta, **run_meta, "infer_resolved": bool(body.infer_resolved)},
    )
    return helpers.session_to_out(row)


@router.patch("/{session_id}/participant-tutorial", response_model=SessionOut)
def patch_participant_tutorial(
    session_id: str,
    body: ParticipantTutorialUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    if "participant_tutorial_enabled" in body.model_fields_set:
        row.participant_tutorial_enabled = bool(body.participant_tutorial_enabled)
    if "tutorial_step_override" in body.model_fields_set:
        row.tutorial_step_override = body.tutorial_step_override
    if "tutorial_chat_started" in body.model_fields_set and body.tutorial_chat_started is not None:
        row.tutorial_chat_started = bool(body.tutorial_chat_started)
    if "tutorial_uploaded_files" in body.model_fields_set and body.tutorial_uploaded_files is not None:
        row.tutorial_uploaded_files = bool(body.tutorial_uploaded_files)
    if "tutorial_definition_tab_visited" in body.model_fields_set and body.tutorial_definition_tab_visited is not None:
        row.tutorial_definition_tab_visited = bool(body.tutorial_definition_tab_visited)
    if "tutorial_definition_saved" in body.model_fields_set and body.tutorial_definition_saved is not None:
        row.tutorial_definition_saved = bool(body.tutorial_definition_saved)
    if "tutorial_config_tab_visited" in body.model_fields_set and body.tutorial_config_tab_visited is not None:
        row.tutorial_config_tab_visited = bool(body.tutorial_config_tab_visited)
    if "tutorial_config_first_saved" in body.model_fields_set and body.tutorial_config_first_saved is not None:
        row.tutorial_config_first_saved = bool(body.tutorial_config_first_saved)
    if "tutorial_config_saved" in body.model_fields_set and body.tutorial_config_saved is not None:
        row.tutorial_config_saved = bool(body.tutorial_config_saved)
    if "tutorial_first_run_done" in body.model_fields_set and body.tutorial_first_run_done is not None:
        row.tutorial_first_run_done = bool(body.tutorial_first_run_done)
    if "tutorial_second_run_done" in body.model_fields_set and body.tutorial_second_run_done is not None:
        row.tutorial_second_run_done = bool(body.tutorial_second_run_done)
    if "tutorial_run_summary_read" in body.model_fields_set and body.tutorial_run_summary_read is not None:
        row.tutorial_run_summary_read = bool(body.tutorial_run_summary_read)
    if "tutorial_results_inspected" in body.model_fields_set and body.tutorial_results_inspected is not None:
        row.tutorial_results_inspected = bool(body.tutorial_results_inspected)
    if "tutorial_explain_used" in body.model_fields_set and body.tutorial_explain_used is not None:
        row.tutorial_explain_used = bool(body.tutorial_explain_used)
    if "tutorial_candidate_marked" in body.model_fields_set and body.tutorial_candidate_marked is not None:
        row.tutorial_candidate_marked = bool(body.tutorial_candidate_marked)
    if "tutorial_third_run_done" in body.model_fields_set and body.tutorial_third_run_done is not None:
        row.tutorial_third_run_done = bool(body.tutorial_third_run_done)
    if "tutorial_completed" in body.model_fields_set and body.tutorial_completed is not None:
        row.tutorial_completed = bool(body.tutorial_completed)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/{session_id}/sync-panel", response_model=SessionOut)
def sync_panel_from_problem_brief_route(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    from app.crypto_util import decrypt_secret

    problem_brief = helpers.problem_brief_dict(row)
    helpers.settle_processing_state(row, cancel_revision=True)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    sync_failed = False
    try:
        updated_panel, _ = sync.sync_panel_from_problem_brief(
            row,
            db,
            problem_brief,
            api_key=decrypt_secret(row.gemini_key_encrypted),
            model_name=row.gemini_model or get_settings().default_gemini_model,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=True,
        )
    except sync.GoalTermValidationError as exc:
        # Structural validator errors only (shape/type/order).
        sync_failed = True
        updated_panel = None
        helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
        db.commit()
        db.refresh(row)
        derivation.append_message(
            db,
            session_id,
            "assistant",
            "I couldn't sync Problem Config from the Definition — the structured panel data is "
            "invalid. Use the **Recover** button in the banner above the tabs to reset.",
            True,
            kind="panel",
        )
    if updated_panel is None and not sync_failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Problem definition is not specific enough to sync a solver configuration yet",
        )
    if not sync_failed:
        helpers.settle_processing_state(row)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/{session_id}/recover-goal-terms", response_model=SessionOut)
def post_recover_goal_terms(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    """Reset goal terms after a structural validator failure.

    Hallucination-style mismatches no longer block saves (they surface as
    advisory warnings — see ``validate_problem_goal_terms``).  This endpoint
    remains for the rare structural-error case (shape / type / order) where
    the panel is genuinely malformed.  It:

      1. Clears `panel.problem.{goal_terms, weights, constraint_types, locked_goal_terms}`
         so the next sync starts from an empty term set.
      2. Resets the session processing state (clears `processing_error`).
      3. Re-derives the panel from the existing brief using the deterministic
         seed only (no LLM), guaranteeing keys grounded in brief items.

    Brief content is preserved — the user's stated goals are not lost.
    """
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    panel = helpers.panel_dict(row)
    if isinstance(panel, dict) and isinstance(panel.get("problem"), dict):
        problem = panel["problem"]
        for key in ("goal_terms", "weights", "constraint_types", "locked_goal_terms"):
            problem.pop(key, None)
        row.panel_config_json = json.dumps(panel)

    helpers.settle_processing_state(row, cancel_revision=True)
    helpers.touch_session(row)
    db.commit()
    db.refresh(row)

    problem_brief = helpers.problem_brief_dict(row)
    try:
        sync.sync_panel_from_problem_brief(
            row,
            db,
            problem_brief,
            api_key=None,
            model_name=None,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=False,
        )
    except sync.GoalTermValidationError:
        # Structural error from the deterministic seed itself — should be vanishingly
        # rare. Leave the panel cleared and the error reset; the participant
        # can edit Definition or chat to articulate goals again.
        row = db.get(StudySession, session_id) or row
        helpers.settle_processing_state(row, cancel_revision=True)
        helpers.touch_session(row)
        db.commit()
        db.refresh(row)

    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)
    return helpers.session_to_out(row)


@router.post("/{session_id}/resync-panel-from-brief", response_model=SessionOut)
def post_resync_panel_from_brief(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_any_study_user),
):
    """Re-derive the panel from the brief without clearing it.

    Unlike ``recover-goal-terms`` (which wipes weights / goal_terms /
    constraint_types / locked_goal_terms before re-deriving from a
    deterministic seed), this endpoint runs the standard sync path with
    ``preserve_missing_managed_fields=True``, so:

    - LLM derivation is used when a Gemini key is available, falling back to
      the deterministic seed otherwise — same as a normal participant turn.
    - Locked goal terms and their companion fields are honoured.
    - Researcher-controlled switches (e.g. ``only_active_terms``) and panel
      values without brief evidence are left intact.

    Available to both researcher and participant: both UIs surface this as the
    "Sync to config" button (def → panel direction). The researcher panel also
    exposes it in the drift banner alongside its "Sync to def." counterpart.
    """
    from app.crypto_util import decrypt_secret

    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    problem_brief = helpers.problem_brief_dict(row)
    try:
        sync.sync_panel_from_problem_brief(
            row,
            db,
            problem_brief,
            api_key=decrypt_secret(row.gemini_key_encrypted)
            if row.gemini_key_encrypted
            else None,
            model_name=row.gemini_model or get_settings().default_gemini_model,
            workflow_mode=row.workflow_mode,
            preserve_missing_managed_fields=True,
        )
    except sync.GoalTermValidationError as exc:
        helpers.fail_processing_state(row, exc.processing_error_text(), cancel_revision=True)
        db.commit()
        db.refresh(row)
        raise HTTPException(status_code=422, detail=exc.detail_text()) from exc

    helpers.settle_processing_state(row, cancel_revision=True)
    helpers.touch_session(row)
    db.commit()
    db.refresh(row)
    if helpers.sync_optimization_allowed_after_participant_mutation(row):
        db.commit()
        db.refresh(row)
    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)
    return helpers.session_to_out(row)


@router.post("/{session_id}/resync-brief-from-panel", response_model=SessionOut)
def post_resync_brief_from_panel(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_any_study_user),
):
    """Mirror the current panel state into the brief — the panel→brief counterpart
    of ``resync-panel-from-brief``.

    Closes drift where the panel holds a goal term, constraint type, or mirror
    field that the brief never picked up (most often after a starter panel
    push, a researcher-side direct panel edit, or a botched LLM merge). The
    work is delegated to ``sync.sync_problem_brief_from_panel`` which is the
    same function called on every participant panel PATCH — running it
    standalone here just lets the user request the mirror without making an
    edit.

    Idempotent when already aligned: returns the session unchanged. Snapshot
    is recorded so researchers can see when a manual mirror was triggered.
    """
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")

    current_panel = helpers.panel_dict(row)
    sync.sync_problem_brief_from_panel(row, db, current_panel)
    helpers.settle_processing_state(row, cancel_revision=True)
    helpers.touch_session(row)
    db.commit()
    db.refresh(row)
    create_snapshot(db, session_id, EVENT_MANUAL_SAVE)
    return helpers.session_to_out(row)


@router.post("/{session_id}/simulate-upload", status_code=status.HTTP_204_NO_CONTENT)
def simulate_upload(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "active":
        raise HTTPException(status_code=410, detail="Session ended")
    return None


def _parse_json_field(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@router.get("/{session_id}/export")
def export_session(
    session_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_researcher),
):
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = (
        db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.id.asc()).all()
    )
    runs = (
        db.query(OptimizationRun).filter(OptimizationRun.session_id == session_id).order_by(OptimizationRun.id.asc()).all()
    )
    snapshots = (
        db.query(SessionSnapshot)
        .filter(SessionSnapshot.session_id == session_id)
        .order_by(SessionSnapshot.id.asc())
        .all()
    )
    exported_at = datetime.now(timezone.utc)
    timeline = build_export_timeline(messages, runs, snapshots, run_number=helpers.run_number)
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": serialize_utc_datetime(exported_at),
        "timeline": timeline,
        "session": {
            "id": row.id,
            "created_at": serialize_utc_datetime(row.created_at),
            "updated_at": serialize_utc_datetime(row.updated_at),
            "workflow_mode": row.workflow_mode,
            "participant_number": row.participant_number,
            "test_problem_id": str(getattr(row, "test_problem_id", None) or DEFAULT_PROBLEM_ID),
            "status": row.status,
            "panel_config": helpers.panel_dict(row),
            "problem_brief": helpers.problem_brief_dict(row),
            "processing_revision": int(row.processing_revision or 0),
            "brief_status": row.brief_status,
            "config_status": row.config_status,
            "processing_error": row.processing_error,
            "optimization_allowed": row.optimization_allowed,
            "optimization_runs_blocked_by_researcher": row.optimization_runs_blocked_by_researcher,
            "allow_agent_autorun": bool(getattr(row, "allow_agent_autorun", False)),
            "agile_oq_every_n_runs": getattr(row, "agile_oq_every_n_runs", None),
            "participant_tutorial_enabled": bool(getattr(row, "participant_tutorial_enabled", False)),
            "tutorial_step_override": getattr(row, "tutorial_step_override", None),
            "tutorial_chat_started": bool(getattr(row, "tutorial_chat_started", False)),
            "tutorial_uploaded_files": bool(getattr(row, "tutorial_uploaded_files", False)),
            "tutorial_definition_tab_visited": bool(getattr(row, "tutorial_definition_tab_visited", False)),
            "tutorial_definition_saved": bool(getattr(row, "tutorial_definition_saved", False)),
            "tutorial_config_tab_visited": bool(getattr(row, "tutorial_config_tab_visited", False)),
            "tutorial_config_first_saved": bool(getattr(row, "tutorial_config_first_saved", False)),
            "tutorial_config_saved": bool(getattr(row, "tutorial_config_saved", False)),
            "tutorial_first_run_done": bool(getattr(row, "tutorial_first_run_done", False)),
            "tutorial_second_run_done": bool(getattr(row, "tutorial_second_run_done", False)),
            "tutorial_run_summary_read": bool(getattr(row, "tutorial_run_summary_read", False)),
            "tutorial_results_inspected": bool(getattr(row, "tutorial_results_inspected", False)),
            "tutorial_explain_used": bool(getattr(row, "tutorial_explain_used", False)),
            "tutorial_candidate_marked": bool(getattr(row, "tutorial_candidate_marked", False)),
            "tutorial_third_run_done": bool(getattr(row, "tutorial_third_run_done", False)),
            "tutorial_completed": bool(getattr(row, "tutorial_completed", False)),
            "optimization_gate_engaged": bool(getattr(row, "optimization_gate_engaged", False)),
            "gemini_model": row.gemini_model,
            "embedding_model": row.embedding_model,
            "gemini_key_configured": bool(row.gemini_key_encrypted),
            "content_reset_revision": int(getattr(row, "content_reset_revision", 0) or 0),
        },
        "messages": [
            {
                "id": m.id,
                "created_at": serialize_utc_datetime(m.created_at),
                "role": m.role,
                "content": m.content,
                "visible_to_participant": m.visible_to_participant,
                "kind": m.kind,
                "meta": _parse_json_field(m.meta_json),
            }
            for m in messages
        ],
        "runs": [
            {
                "id": r.id,
                "session_run_index": r.session_run_index,
                "run_number": helpers.run_number(r),
                "created_at": serialize_utc_datetime(r.created_at),
                "run_type": r.run_type,
                "ok": r.ok,
                "cost": r.cost,
                "reference_cost": r.reference_cost,
                "error_message": r.error_message,
                "request": json.loads(r.request_json) if r.request_json else None,
                "result": json.loads(r.result_json) if r.result_json else None,
            }
            for r in runs
        ],
        "snapshots": [
            {
                "id": s.id,
                "created_at": serialize_utc_datetime(s.created_at),
                "event_type": s.event_type,
                "problem_brief": _parse_json_field(s.problem_brief_json),
                "panel_config": _parse_json_field(s.panel_config_json),
            }
            for s in snapshots
        ],
    }


# ============================================================================
# Chat pipeline control endpoints (Retry / Revert / settle)
# ============================================================================


@router.post("/{session_id}/messages/{message_id}/pipeline/retry")
def retry_pipeline_stage(
    session_id: str,
    message_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
) -> dict[str, Any]:
    """Resume a paused pipeline run from its paused stage.

    Body is empty — the paused stage is read from
    ``messages[message_id].meta.pipeline.paused_stage``. Re-bumps
    ``processing_revision`` so any concurrent background job for this
    session bows out, then re-launches the pipeline starting from the
    paused stage (with retried=true on that stage).
    """
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    msg = db.get(ChatMessage, message_id)
    if msg is None or msg.session_id != session_id:
        raise HTTPException(status_code=404, detail="Message not found")
    from app.services.chat_pipeline_runner import resume_pipeline_from_pause

    try:
        result = resume_pipeline_from_pause(session_id=session_id, message_id=message_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Paused pipeline not found")
    return {"ok": True, "resumed_from": result.get("resumed_from")}


@router.post("/{session_id}/messages/{message_id}/pipeline/revert")
def revert_pipeline(
    session_id: str,
    message_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_client),
) -> dict[str, Any]:
    """Discard the paused pipeline's in-flight derivation and restore the
    pre-turn brief/panel state.

    Effects:
    - Settles the message's pipeline status (verifying=false, paused
      stages marked failed with the existing issues retained).
    - Cancels any in-flight background derivation for the session.
    - Appends an inline assistant note: "Reverted — let me know how
      you'd like to try again."
    """
    row = db.get(StudySession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    msg = db.get(ChatMessage, message_id)
    if msg is None or msg.session_id != session_id:
        raise HTTPException(status_code=404, detail="Message not found")
    from app.services.chat_pipeline_runner import revert_paused_pipeline

    try:
        revert_paused_pipeline(session_id=session_id, message_id=message_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Paused pipeline not found")
    return {"ok": True}
