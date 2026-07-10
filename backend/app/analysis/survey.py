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
    "confidence": "how confident are you",
    "est_time_minutes": "how many minutes do you expect",
}

_ID_HEADERS = ("participant id", "participant")


def normalize_pid(value: str | None) -> str:
    return (value or "").strip().upper()


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
