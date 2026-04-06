from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4


SYSTEM_ITEM_IDS = {
    "backend-template": "system-backend-template",
    "translation-layer": "system-translation-layer",
    "schema-scope": "system-schema-scope",
}

CONFIG_ITEM_PREFIX = "config-"

_WEIGHT_ITEM_LABELS = {
    "travel_time": "Travel time",
    "fuel_cost": "Fuel and operating cost",
    "deadline_penalty": "On-time delivery",
    "capacity_penalty": "Load capacity limits",
    "workload_balance": "Workload balance",
    "worker_preference": "Worker preferences",
    "priority_penalty": "Priority-order deadlines",
}
_EXPLICIT_VALUE_RE = re.compile(
    r"\b(?:set to|weight(?:ed)? to|weight(?:ed)? at|target(?:ed)? at|target(?:ed)? of|target of|penalty of)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_ALGORITHM_PARAM_RE = re.compile(
    r"\balgorithm parameter\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+is set to\s+([^\s]+)",
    re.IGNORECASE,
)
_WEIGHT_SLOT_MARKERS: dict[str, tuple[str, ...]] = {
    "travel_time": ("travel time",),
    "fuel_cost": ("fuel and operating cost", "fuel cost", "operating cost"),
    "deadline_penalty": ("on-time delivery", "deadline penalty", "lateness penalty"),
    "capacity_penalty": ("load capacity limits", "capacity penalty"),
    "workload_balance": ("workload balance",),
    "worker_preference": ("worker preferences", "worker preference", "driver preference"),
    "priority_penalty": ("priority-order deadlines", "priority deadline", "priority order"),
}

# Model sometimes emits fake "open questions" like "Cap shifts? (Answered: 8h)." — fold into gathered instead.
_ANSWERED_SUFFIX_IN_OPQ_RE = re.compile(
    r"^(?P<q>.+?)\s*\(\s*answered\s*:\s*(?P<a>.+?)\)\s*\.?\s*\Z",
    re.IGNORECASE | re.DOTALL,
)


def _system_item(item_id: str, text: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "text": text,
        "kind": "system",
        "source": "system",
        "status": "confirmed",
        "editable": False,
    }


def default_problem_brief() -> dict[str, Any]:
    return {
        "goal_summary": "",
        "items": [
            _system_item(
                SYSTEM_ITEM_IDS["backend-template"],
                "Current backend template uses a routing and time-window optimization schema.",
            ),
            _system_item(
                SYSTEM_ITEM_IDS["translation-layer"],
                "The assistant may discuss the task in general optimization terms and translate that intent into the active solver configuration.",
            ),
            _system_item(
                SYSTEM_ITEM_IDS["schema-scope"],
                "Final configuration fields map onto the currently supported backend rather than an arbitrary custom codebase.",
            ),
        ],
        "open_questions": [],
        "solver_scope": "general_metaheuristic_translation",
        "backend_template": "routing_time_windows",
    }


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
        question_id = str(raw.get("id") or uuid4())
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
    return {"id": str(uuid4()), "text": text, "status": "open", "answer_text": None}


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


def _coerce_question_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in value:
        normalized = _normalize_question(entry)
        if normalized is None:
            continue
        fragments: list[str] = []
        for raw_line in normalized["text"].splitlines():
            line = _clean_question_fragment(raw_line)
            if not line:
                continue
            # Do not split before a parenthesis (e.g. "Shift cap? (Answered: 8h).") — keeps
            # merge-time sanitization of fake answered questions reliable.
            for part in re.split(r"(?<=[?!])\s+(?!\()", line):
                cleaned = _clean_question_fragment(part)
                if cleaned:
                    fragments.append(cleaned)
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
        combined = f"{qtext} — {at}"
        key = _gathered_text_key(combined)
        if key not in seen:
            seen.add(key)
            qid = str(q.get("id") or uuid4())
            new_items.append(
                {
                    "id": f"gathered-oq-{qid}",
                    "text": combined,
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
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
        combined = f"{q_part} — {a_part}" if q_part else a_part
        qid = str(q.get("id") or uuid4())
        gathered_out.append(
            {
                "id": f"gathered-oq-{qid}",
                "text": combined,
                "kind": "gathered",
                "source": "user",
                "status": "confirmed",
                "editable": True,
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


def _normalize_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    kind = str(raw.get("kind", "assumption")).strip().lower()
    if kind not in {"gathered", "assumption", "system"}:
        kind = "assumption"
    source = str(raw.get("source", "agent")).strip().lower()
    if source not in {"user", "upload", "agent", "system"}:
        source = "agent"
    status = str(raw.get("status", "active")).strip().lower()
    if status not in {"active", "confirmed", "rejected"}:
        status = "active"
    editable = bool(raw.get("editable", kind != "system"))
    return {
        "id": str(raw.get("id") or uuid4()),
        "text": text,
        "kind": kind,
        "source": source,
        "status": status,
        "editable": False if kind == "system" else editable,
    }


def normalize_problem_brief(raw: Any) -> dict[str, Any]:
    base = default_problem_brief()
    if not isinstance(raw, dict):
        return base

    goal_summary = str(raw.get("goal_summary", "")).strip()
    solver_scope = str(raw.get("solver_scope") or base["solver_scope"]).strip() or base["solver_scope"]
    backend_template = (
        str(raw.get("backend_template") or base["backend_template"]).strip() or base["backend_template"]
    )

    system_items = {
        item["id"]: deepcopy(item)
        for item in base["items"]
        if isinstance(item, dict) and item.get("kind") == "system"
    }

    normalized_items: list[dict[str, Any]] = []
    for entry in raw.get("items", []):
        item = _normalize_item(entry)
        if item is None:
            continue
        if item["kind"] == "system" and item["id"] in system_items:
            normalized_items.append(system_items.pop(item["id"]))
        else:
            normalized_items.append(item)

    normalized_items.extend(system_items.values())
    normalized_items = _reconcile_problem_brief_items(normalized_items)
    questions = _coerce_question_list(raw.get("open_questions"))
    promoted_items, questions = _promote_answered_open_questions_to_gathered(normalized_items, questions)
    promoted_items = _reconcile_problem_brief_items(promoted_items)
    return {
        "goal_summary": goal_summary,
        "items": promoted_items,
        "open_questions": questions,
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
        merged["goal_summary"] = str(patch.get("goal_summary") or "").strip()
    if replace_open_questions and "open_questions" not in patch:
        merged["open_questions"] = []
    elif "open_questions" in patch:
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

    if replace_editable_items and "items" not in patch:
        preserved_system = [
            deepcopy(item)
            for item in merged["items"]
            if isinstance(item, dict) and str(item.get("kind") or "").strip().lower() == "system"
        ]
        merged["items"] = preserved_system
        return normalize_problem_brief(merged)
    if "items" in patch and isinstance(patch.get("items"), list):
        incoming_items = [item for raw in patch["items"] if (item := _normalize_item(raw)) is not None]
        if replace_editable_items:
            preserved_system = [
                deepcopy(item)
                for item in merged["items"]
                if isinstance(item, dict) and str(item.get("kind") or "").strip().lower() == "system"
            ]
            merged["items"] = preserved_system + [
                item for item in incoming_items if str(item.get("kind") or "").strip().lower() != "system"
            ]
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

    return normalize_problem_brief(merged)


def sync_problem_brief_from_panel(base_brief: Any, panel_config: Any) -> dict[str, Any]:
    """Mirror saved config choices back into the editable problem brief."""
    base = normalize_problem_brief(base_brief)
    merged = deepcopy(base)
    panel_items = _brief_items_from_panel(panel_config)
    panel_slots = {
        slot
        for item in panel_items
        if (slot := _problem_brief_item_slot(item)) is not None
    }
    merged["items"] = [
        deepcopy(item)
        for item in merged["items"]
        if isinstance(item, dict)
        and not str(item.get("id") or "").startswith(CONFIG_ITEM_PREFIX)
        and _problem_brief_item_slot(item) not in panel_slots
    ]
    merged["items"].extend(panel_items)
    return normalize_problem_brief(merged)


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
        "status": "confirmed",
        "editable": True,
    }


def _problem_brief_item_slot(item: dict[str, Any]) -> str | None:
    item_id = str(item.get("id") or "")
    slot = _slot_from_item_id(item_id)
    if slot is not None:
        return slot
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    return _slot_from_text(text)


def _slot_from_item_id(item_id: str) -> str | None:
    if item_id == "config-algorithm":
        return "algorithm"
    if item_id == "config-epochs":
        return "epochs"
    if item_id == "config-pop-size":
        return "pop_size"
    if item_id == "config-only-active-terms":
        return "only_active_terms"
    if item_id == "config-shift-hard-penalty":
        return "shift_hard_penalty"
    if item_id.startswith("config-weight-"):
        return f"weight:{item_id.removeprefix('config-weight-')}"
    if item_id.startswith("config-algorithm-param-"):
        return f"algorithm_param:{item_id.removeprefix('config-algorithm-param-')}"
    return None


def _slot_from_text(text: str) -> str | None:
    lowered = text.lower()
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
    if "shift duration hard penalty" in lowered and _EXPLICIT_VALUE_RE.search(text):
        return "shift_hard_penalty"
    for weight_key, markers in _WEIGHT_SLOT_MARKERS.items():
        if any(marker in lowered for marker in markers) and _EXPLICIT_VALUE_RE.search(text):
            return f"weight:{weight_key}"
    return None


def _reconcile_problem_brief_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_index_by_slot: dict[str, int] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or str(item.get("kind") or "").strip().lower() == "system":
            continue
        slot = _problem_brief_item_slot(item)
        if slot is not None:
            last_index_by_slot[slot] = index

    reconciled: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() == "system":
            reconciled.append(item)
            continue
        slot = _problem_brief_item_slot(item)
        if slot is not None and last_index_by_slot.get(slot) != index:
            continue
        reconciled.append(item)
    return reconciled


def _brief_items_from_panel(panel_config: Any) -> list[dict[str, Any]]:
    if not isinstance(panel_config, dict):
        return []

    problem = panel_config.get("problem") if isinstance(panel_config.get("problem"), dict) else panel_config
    if not isinstance(problem, dict):
        return []

    items: list[dict[str, Any]] = []

    algorithm = str(problem.get("algorithm") or "").strip()
    if algorithm:
        items.append(_config_item("config-algorithm", f"Solver algorithm is {algorithm}."))

    epochs = problem.get("epochs")
    if isinstance(epochs, (int, float)) and not isinstance(epochs, bool):
        items.append(_config_item("config-epochs", f"Search epochs are set to {epochs}."))

    pop_size = problem.get("pop_size")
    if isinstance(pop_size, (int, float)) and not isinstance(pop_size, bool):
        items.append(_config_item("config-pop-size", f"Population size is set to {pop_size}."))

    if "only_active_terms" in problem and isinstance(problem.get("only_active_terms"), bool):
        items.append(
            _config_item(
                "config-only-active-terms",
                "Only active objective terms should be applied."
                if problem["only_active_terms"]
                else "Inactive objective terms may also remain available.",
            )
        )

    weights = problem.get("weights")
    if isinstance(weights, dict):
        for key in sorted(weights):
            value = weights.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            label = _WEIGHT_ITEM_LABELS.get(str(key), str(key).replace("_", " ").capitalize())
            items.append(_config_item(f"config-weight-{key}", f"{label} weight is set to {value}."))

    shift_hard_penalty = problem.get("shift_hard_penalty")
    if isinstance(shift_hard_penalty, (int, float)) and not isinstance(shift_hard_penalty, bool):
        items.append(
            _config_item(
                "config-shift-hard-penalty",
                f"Shift duration hard penalty is set to {shift_hard_penalty}.",
            )
        )

    from app.algorithm_catalog import (
        allowed_param_keys,
        canonical_algorithm_stored,
        param_value_is_default,
    )

    algorithm_params = problem.get("algorithm_params")
    algo_key = canonical_algorithm_stored(algorithm) if algorithm else None
    allowed_ap = allowed_param_keys(algo_key) if algo_key else frozenset()
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
            items.append(
                _config_item(
                    f"config-algorithm-param-{key}",
                    f"Algorithm parameter {key} is set to {rendered}.",
                )
            )

    return items
