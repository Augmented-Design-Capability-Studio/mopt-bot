"""Safe server-side ingestion of the pre/post-task survey CSVs.

Parsing happens in Python (stdlib ``csv``) so raw survey rows — and any PII —
never reach the browser; only derived aggregate numbers are exposed. Any column
whose header mentions "email" is dropped before storage as a belt-and-braces
guard (the pre-task CSV has none; the post-task CSV does).
"""

from __future__ import annotations

import csv
import io
from typing import Any

# Substrings identifying the five self-rated expertise Likert items in the
# pre-task CSV. Structured-CSV header matching (not natural-language parsing).
EXPERTISE_KEYWORDS = [
    "overall expertise",
    "familiar are you with optimization",
    "using optimization tools",
    "coding optimization tools",
    "understand optimization methods",
]

# Single-column pre-task metrics, exposed under short canonical names so the
# notebook can reference them directly (surveys.confidence, surveys.est_time_minutes).
NAMED_FIELDS: dict[str, str] = {
    # pre-task
    "confidence": "how confident are you",
    "est_time_minutes": "how many minutes do you expect",
    # post-task Likert (1–7)
    "viz_clarity": "visualizations provided a clear understanding",
    "comm_accuracy": "accurately represented my formulation",
    "solution_confidence": "confident in the quality of the final solution",
}

_ID_HEADERS = ("participant id", "participant")

# The five warm-up quiz MCQs in the pre-task CSV: (question-header substring,
# correct-option substring), both matched lowercased. Fixed Google-Form option
# strings — structured matching, not free-text interpretation.
QUIZ_ITEMS: list[tuple[str, str]] = [
    ("is the solution valid", "required constraint is violated"),
    ("better than the previous one", "prioritized against each other"),
    ("what can you conclude", "may still be improved further"),
    ("identical inputs and identical settings", "randomness"),
    ("may still not work well", "may not fully capture"),
]

# The pre-task free-text experience question ("Have you ever studied or worked with
# optimization, operations research, …"). We surface only its WORD COUNT — a
# de-identified number, a rough "how much did they elaborate" proxy — never the text.
_EXPERIENCE_KEYWORD = "studied or worked"


def normalize_pid(value: str | None) -> str:
    return (value or "").strip().upper()


def experience_word_count(row: dict[str, str]) -> int | None:
    """Word count of the free-text 'Have you ever studied or worked with
    optimization…' answer. None if that column is absent."""
    for key, val in row.items():
        if _EXPERIENCE_KEYWORD in key.lower():
            return len((val or "").split())
    return None


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def compute_expertise(row: dict[str, str]) -> float | None:
    """Mean of the matched expertise Likert items (1–7). None if none match."""
    lowered = {k.lower(): v for k, v in row.items()}
    vals: list[float] = []
    for kw in EXPERTISE_KEYWORDS:
        for key, val in lowered.items():
            if kw in key:
                num = _to_float(val)
                if num is not None:
                    vals.append(num)
                break
    if not vals:
        return None
    return round(sum(vals) / len(vals), 3)


def extract_named_metrics(row: dict[str, str]) -> dict[str, float | None]:
    """Pull the short-named single-column metrics (confidence, est time)."""
    lowered = {k.lower(): v for k, v in row.items()}
    out: dict[str, float | None] = {}
    for name, kw in NAMED_FIELDS.items():
        value = None
        for key, val in lowered.items():
            if kw in key:
                value = _to_float(val)
                break
        out[name] = value
    return out


def quiz_score(row: dict[str, str]) -> int | None:
    """Number of correct warm-up quiz answers (0–5). None when the quiz is
    absent or entirely blank (post-task rows, pilot rows) so missing ≠ 0."""
    lowered = {k.lower(): (v or "") for k, v in row.items()}
    answered = correct = 0
    for q_kw, a_kw in QUIZ_ITEMS:
        for key, val in lowered.items():
            if q_kw in key:
                if val.strip():
                    answered += 1
                    correct += a_kw in val.lower()
                break
    return correct if answered else None


def _find_id(row: dict[str, str]) -> str | None:
    for key, val in row.items():
        kl = key.lower()
        if any(h in kl for h in _ID_HEADERS):
            pid = normalize_pid(val)
            if pid:
                return pid
    return None


def parse_survey_csv(data: bytes, phase: str) -> list[dict[str, Any]]:
    """Return one record per CSV row: participant_id, expertise_score, data
    (row minus any email column). Rows without an identifiable id are skipped."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for raw in reader:
        pid = _find_id(raw)
        if not pid:
            continue
        safe = {k: v for k, v in raw.items() if k and "email" not in k.lower()}
        out.append(
            {
                "participant_id": pid,
                "phase": phase,
                "expertise_score": compute_expertise(safe) if phase == "pre" else None,
                "data": safe,
            }
        )
    return out
