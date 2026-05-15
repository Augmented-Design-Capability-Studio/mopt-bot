"""Per-message pipeline-status persistence.

The status checklist attached to an assistant chat bubble lives in the
message row's ``meta_json`` blob under key ``pipeline`` so the existing
``meta.verifying`` polling pattern (frontend
``useClientSessionSync.verifyingMessageIds``) picks up status updates
automatically.

Shape (mirrors ``app.schemas.PipelineStatus``):

::

    {
      "verifying": true,  // existing flag — set false when pipeline settles
      "pipeline": {
        "flavor": "chat",
        "stages": [
          {"name": "drafting",         "state": "success", "label": "Drafting reply"},
          {"name": "verifying_brief",  "state": "in_progress", "label": "Verifying intent & definition"},
          {"name": "applying",         "state": "pending",     "label": "Applying patch"},
          {"name": "deriving_config",  "state": "pending",     "label": "Deriving config",
           "substages": ["goal terms", "algorithm"]},
          {"name": "verifying_config", "state": "pending",     "label": "Verifying config"}
        ],
        "paused_stage": null
      }
    }

Stage state transitions:
    pending → in_progress → (success | skipped | failed)
    failed (first time) → in_progress (retried=true)
    failed (second time) → paused
    paused → in_progress (on manual Retry)

Backend writes are best-effort: a row that no longer exists is silently
ignored. The frontend treats a missing ``pipeline`` field as "no
checklist" (legacy behavior).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from sqlalchemy.orm import Session as OrmSession

from app.database import SessionLocal
from app.models import ChatMessage

log = logging.getLogger(__name__)


PipelineFlavor = Literal["chat", "brief_edit_ack", "config_edit_ack", "run_ack"]
StageName = Literal[
    "drafting",
    "verifying_brief",
    "applying",
    "deriving_config",
    "verifying_config",
]
StageState = Literal["pending", "in_progress", "success", "failed", "skipped", "paused"]


# Canonical per-flavor stage layout. Frontend renders these labels verbatim
# unless overridden inline. Sub-stages on deriving/verifying config reflect
# the two halves of the panel-verification surface (goal_terms + algorithm).
_STAGE_TEMPLATES: dict[PipelineFlavor, list[dict[str, Any]]] = {
    "chat": [
        {"name": "drafting", "label": "Drafting reply"},
        {"name": "verifying_brief", "label": "Verifying intent & definition"},
        {"name": "applying", "label": "Applying changes"},
        {
            "name": "deriving_config",
            "label": "Deriving config",
            "substages": ["goal terms", "algorithm"],
        },
        {
            "name": "verifying_config",
            "label": "Verifying config",
            "substages": ["goal terms", "algorithm"],
        },
    ],
    "brief_edit_ack": [
        {"name": "drafting", "label": "Acknowledging edit"},
        {"name": "verifying_brief", "label": "Verifying definition"},
        {"name": "applying", "label": "Applying changes"},
        {
            "name": "deriving_config",
            "label": "Deriving config",
            "substages": ["goal terms", "algorithm"],
        },
        {
            "name": "verifying_config",
            "label": "Verifying config",
            "substages": ["goal terms", "algorithm"],
        },
    ],
    "config_edit_ack": [
        {"name": "drafting", "label": "Acknowledging config edit"},
        {"name": "verifying_brief", "label": "Verifying brief ↔ config"},
        {"name": "applying", "label": "Applying changes"},
        # Config-edit skips derive_config since the config IS ground truth.
        {
            "name": "verifying_config",
            "label": "Verifying brief ↔ config",
            "substages": ["goal terms", "algorithm"],
        },
    ],
    "run_ack": [
        {"name": "drafting", "label": "Acknowledging run"},
        {"name": "verifying_brief", "label": "Verifying intent & definition"},
        {"name": "applying", "label": "Applying changes"},
        {
            "name": "deriving_config",
            "label": "Deriving config",
            "substages": ["goal terms", "algorithm"],
        },
        {
            "name": "verifying_config",
            "label": "Verifying config",
            "substages": ["goal terms", "algorithm"],
        },
    ],
}


def initial_pipeline_status(flavor: PipelineFlavor) -> dict[str, Any]:
    """Return the canonical initial ``meta.pipeline`` payload for a flavor.

    All stages start ``pending``; the caller flips the first one to
    ``in_progress`` when it begins work. Frontend can render the
    checklist with greyed pending rows immediately.
    """
    template = _STAGE_TEMPLATES.get(flavor, _STAGE_TEMPLATES["chat"])
    stages = []
    for entry in template:
        stage = {
            "name": entry["name"],
            "state": "pending",
            "label": entry["label"],
            "retried": False,
            "issues": [],
        }
        if "substages" in entry:
            stage["substages"] = list(entry["substages"])
        stages.append(stage)
    return {
        "flavor": flavor,
        "stages": stages,
        "paused_stage": None,
    }


def _read_meta(msg: ChatMessage) -> dict[str, Any]:
    if not msg.meta_json:
        return {}
    try:
        parsed = json.loads(msg.meta_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_meta(db: OrmSession, msg: ChatMessage, meta: dict[str, Any]) -> None:
    msg.meta_json = json.dumps(meta, ensure_ascii=False)
    db.commit()


def set_initial_status(
    *,
    message_id: int,
    flavor: PipelineFlavor,
) -> None:
    """Initialize ``meta.pipeline`` and flip ``meta.verifying`` on for an
    assistant message that just got persisted as a pipeline draft.

    Idempotent: re-running on a message that already has a pipeline
    payload overwrites it with a fresh template — useful for the
    pipeline-status reset that fires on a participant-triggered Retry.
    """
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = _read_meta(msg)
        meta["verifying"] = True
        meta["pipeline"] = initial_pipeline_status(flavor)
        _write_meta(db, msg, meta)


def _find_stage(pipeline: dict[str, Any], stage_name: StageName) -> dict[str, Any] | None:
    if not isinstance(pipeline, dict):
        return None
    for entry in pipeline.get("stages") or []:
        if isinstance(entry, dict) and entry.get("name") == stage_name:
            return entry
    return None


def update_stage(
    *,
    message_id: int,
    stage_name: StageName,
    state: StageState,
    issues: list[dict[str, Any]] | None = None,
    bump_retried: bool = False,
) -> None:
    """Update one stage row on the message's pipeline status.

    - ``state`` is the new stage state.
    - ``issues`` (if non-empty) is recorded on the stage so the frontend
      can render plain-English failure reasons. Passing ``None`` leaves
      existing issues untouched; passing ``[]`` clears them (e.g. after
      a successful retry).
    - ``bump_retried`` marks the stage as having used its single retry.

    When a stage transitions to ``paused``, also sets
    ``pipeline.paused_stage`` so the frontend can render the action row.
    """
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = _read_meta(msg)
        pipeline = meta.get("pipeline")
        if not isinstance(pipeline, dict):
            log.debug("update_stage on message %s with no pipeline meta", message_id)
            return
        stage = _find_stage(pipeline, stage_name)
        if stage is None:
            log.debug("update_stage: stage %s not found on message %s", stage_name, message_id)
            return
        stage["state"] = state
        if issues is not None:
            stage["issues"] = list(issues)
        if bump_retried:
            stage["retried"] = True
        if state == "paused":
            pipeline["paused_stage"] = stage_name
        elif state == "in_progress" and pipeline.get("paused_stage") == stage_name:
            pipeline["paused_stage"] = None
        _write_meta(db, msg, meta)


def settle_pipeline(*, message_id: int) -> None:
    """Mark the pipeline complete: clear ``meta.verifying`` so polling
    can stop. Stages with state ``pending`` flip to ``skipped`` so the
    frontend can render the final checklist correctly (rather than a
    forever-pending row)."""
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = _read_meta(msg)
        meta["verifying"] = False
        pipeline = meta.get("pipeline")
        if isinstance(pipeline, dict):
            for stage in pipeline.get("stages") or []:
                if isinstance(stage, dict) and stage.get("state") == "pending":
                    stage["state"] = "skipped"
        _write_meta(db, msg, meta)


def fail_pipeline(*, message_id: int, paused_stage: StageName) -> None:
    """Hard-fail the pipeline on a specific stage. Keeps ``meta.verifying``
    true (the frontend uses it to keep polling for a participant-triggered
    Retry / Revert action). Subsequent ``update_stage`` calls re-flip
    ``paused_stage`` if needed.
    """
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = _read_meta(msg)
        pipeline = meta.get("pipeline")
        if not isinstance(pipeline, dict):
            return
        pipeline["paused_stage"] = paused_stage
        _write_meta(db, msg, meta)


def append_inline_followup(*, message_id: int, text: str) -> None:
    """Persist the LLM-emitted ``inline_followup`` so the frontend can
    render it next to the action row on a paused pipeline. Optional —
    only emitted when the LLM thought verification would flag the turn.
    """
    text = (text or "").strip()
    if not text:
        return
    with SessionLocal() as db:
        msg = db.get(ChatMessage, message_id)
        if msg is None:
            return
        meta = _read_meta(msg)
        pipeline = meta.get("pipeline")
        if not isinstance(pipeline, dict):
            return
        pipeline["inline_followup"] = text
        _write_meta(db, msg, meta)
