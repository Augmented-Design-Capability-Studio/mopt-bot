"""Tests for the session-coding analysis tool.

Covers the three verification points from the plan: (1) load copies match the
source counts, (2) the snapshot diff is change-only, (3) time-since-start is
pause-aware. Kept lean (per test-minimalism): one HTTP round-trip test plus two
pure-function tests.
"""

from __future__ import annotations

import glob
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analysis.diffing import compute_definition_config_changes
from app.analysis.rows import CSV_COLUMNS, build_coding_rows
from app.analysis_db import AnalysisBase, get_analysis_db
from app.config import get_settings
from app.main import app

_DATA = Path(__file__).resolve().parent.parent / "data"


def _newest(pattern: str) -> Path:
    """Pick the most recently modified matching data file so tests track the
    current export (filenames change as more sessions are collected)."""
    cands = glob.glob(str(_DATA / pattern))
    return Path(max(cands, key=os.path.getmtime)) if cands else _DATA / "__missing__"


# Prefer a multi-session export (…-NN-MM.db) over the tiny -1/-2 fixtures.
_EXPORT_DB = _newest("mopt-sessions-*[0-9]-*.db")
if not _EXPORT_DB.exists():
    _EXPORT_DB = _newest("mopt-sessions-*.db")
_PRE_CSV = _newest("*- Pre-Task-*.csv")  # not the "…- Post-Task-…" file
_TOKEN = get_settings().researcher_secret


@pytest.fixture
def client(tmp_path):
    """TestClient with the analysis DB pointed at an isolated temp file."""
    url = f"sqlite:///{(tmp_path / 'analysis.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    AnalysisBase.metadata.create_all(bind=engine)
    Local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override():
        db = Local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_analysis_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_analysis_db, None)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


@pytest.mark.skipif(not _EXPORT_DB.exists(), reason="sample export DB not present")
def test_upload_counts_timeline_and_csv(client: TestClient):
    data = _EXPORT_DB.read_bytes()
    res = client.post(
        "/analysis/upload?filename=mopt-sessions-12.db",
        content=data,
        headers={**_auth(), "Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200, res.text
    loaded = res.json()["loaded"]
    assert loaded, "expected at least one loaded session"

    first = loaded[0]
    sid = first["source_session_id"]
    src = sqlite3.connect(_EXPORT_DB)
    try:
        def scount(table: str) -> int:
            return src.execute(
                f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (sid,)
            ).fetchone()[0]

        assert first["counts"]["messages"] == scount("messages")
        assert first["counts"]["runs"] == scount("runs")
        assert first["counts"]["snapshots"] == scount("session_snapshots")
    finally:
        src.close()

    detail = client.get(f"/analysis/loaded/{first['id']}/timeline", headers=_auth()).json()
    assert detail["timeline"], "timeline should not be empty"

    csv_res = client.get(f"/analysis/loaded/{first['id']}/export.csv", headers=_auth())
    assert csv_res.status_code == 200
    text = csv_res.text
    assert text.splitlines()[0] == ",".join(CSV_COLUMNS)
    assert len(text.splitlines()) > 1


@pytest.mark.skipif(
    not (_EXPORT_DB.exists() and _PRE_CSV.exists()), reason="sample data not present"
)
def test_aggregate_joins_survey_expertise(client: TestClient):
    client.post(
        "/analysis/upload?filename=mopt-sessions-12.db",
        content=_EXPORT_DB.read_bytes(),
        headers={**_auth(), "Content-Type": "application/octet-stream"},
    )
    sres = client.post(
        "/analysis/surveys/upload?phase=pre",
        content=_PRE_CSV.read_bytes(),
        headers={**_auth(), "Content-Type": "text/csv"},
    )
    assert sres.status_code == 200, sres.text

    agg = client.get("/analysis/aggregate", headers=_auth()).json()
    assert agg["expertise_available"] is True
    rows = agg["rows"]
    assert rows, "expected aggregate rows"
    # At least one session joins to an expertise score in the valid 1–7 range
    # and has a computed initial-prompt word count. (Values not hard-coded —
    # the sample export grows as more sessions are collected.)
    joined = [r for r in rows if r["expertise_score"] is not None]
    assert joined, "no session joined to a pre-task expertise score"
    r = joined[0]
    assert 1.0 <= r["expertise_score"] <= 7.0
    assert any(isinstance(x["initial_prompt_words"], int) for x in rows)


@pytest.mark.skipif(not _EXPORT_DB.exists(), reason="sample export DB not present")
def test_dataset_has_canonical_cost(client: TestClient):
    client.post(
        "/analysis/upload?filename=export.db",
        content=_EXPORT_DB.read_bytes(),
        headers={**_auth(), "Content-Type": "application/octet-stream"},
    )
    ds = client.get("/analysis/dataset", headers=_auth()).json()
    runs = ds["runs"]
    assert runs, "expected run rows"
    scored = [x for x in runs if x.get("canonical_cost") is not None]
    # VRPTW sessions should re-score most runs under the canonical objective.
    assert scored, "no runs got a canonical cost"
    assert all(x["canonical_cost"] > 0 for x in scored)


@pytest.mark.skipif(not _EXPORT_DB.exists(), reason="sample export DB not present")
def test_bulk_delete_loaded(client: TestClient):
    client.post(
        "/analysis/upload?filename=mopt-sessions-12.db",
        content=_EXPORT_DB.read_bytes(),
        headers={**_auth(), "Content-Type": "application/octet-stream"},
    )
    loaded = client.get("/analysis/loaded", headers=_auth()).json()["loaded"]
    ids = [s["id"] for s in loaded[:3]]
    res = client.post("/analysis/delete-loaded", json={"ids": ids}, headers=_auth())
    assert res.status_code == 200
    assert res.json()["deleted"] == 3
    remaining = client.get("/analysis/loaded", headers=_auth()).json()["loaded"]
    assert len(remaining) == len(loaded) - 3


@pytest.mark.skipif(
    not (_EXPORT_DB.exists() and _PRE_CSV.exists()), reason="sample data not present"
)
def test_dataset_is_deidentified(client: TestClient):
    client.post(
        "/analysis/upload?filename=mopt-sessions-12.db",
        content=_EXPORT_DB.read_bytes(),
        headers={**_auth(), "Content-Type": "application/octet-stream"},
    )
    client.post(
        "/analysis/surveys/upload?phase=pre",
        content=_PRE_CSV.read_bytes(),
        headers={**_auth(), "Content-Type": "text/csv"},
    )
    ds = client.get("/analysis/dataset", headers=_auth()).json()
    assert {"sessions", "messages", "runs", "annotations", "surveys"} <= ds.keys()
    assert len(ds["sessions"]) >= 1
    assert ds["messages"], "expected message rows"
    # Surveys expose only numeric fields — no free-text (e.g. the "describe your
    # experience" column) and no email leaks into the browser payload.
    for row in ds["surveys"]:
        for key, val in row.items():
            if key in ("participant_id", "phase"):
                continue
            assert isinstance(val, (int, float)) or val is None
            assert "email" not in key.lower()
            assert "describe" not in key.lower()


def test_notebook_persist_roundtrip(client: TestClient):
    assert client.get("/analysis/notebook", headers=_auth()).json()["cells"] is None
    client.put("/analysis/notebook", json={"cells": ["print(1)", "print(2)"]}, headers=_auth())
    got = client.get("/analysis/notebook", headers=_auth()).json()
    assert got["cells"] == ["print(1)", "print(2)"]
    # overwrite (single shared doc)
    client.put("/analysis/notebook", json={"cells": ["print(3)"]}, headers=_auth())
    assert client.get("/analysis/notebook", headers=_auth()).json()["cells"] == ["print(3)"]


def test_diff_is_change_only():
    def snap(i, brief, panel):
        return SimpleNamespace(
            id=i, ts_epoch=float(i), problem_brief_json=brief, panel_config_json=panel
        )

    snaps = [
        snap(1, '{"a": 1}', '{"p": 1}'),
        snap(2, '{"a": 1}', '{"p": 1}'),   # identical → no entry
        snap(3, '{"a": 2}', '{"p": 1}'),   # brief changed only
    ]
    changes = compute_definition_config_changes(snaps)
    assert 1 in changes and "definition_change" in changes[1] and "config_change" in changes[1]
    assert 2 not in changes
    assert 3 in changes and "definition_change" in changes[3] and "config_change" not in changes[3]


def test_time_since_start_is_pause_aware():
    loaded = SimpleNamespace(
        clock_offset_sec=0.0, t0_epoch=0.0, t0_iso=None, t0_video_pos=0.0
    )

    def msg(i, epoch):
        return SimpleNamespace(
            source_id=i, id=i, ts_epoch=float(epoch), role="user", kind="chat", content=f"m{i}"
        )

    messages = [msg(1, 0), msg(2, 100)]
    pauses = [SimpleNamespace(start_video_pos=10.0, end_video_pos=70.0)]  # 60s break

    rows = build_coding_rows(loaded, messages, [], [], [], pauses)
    after = next(r for r in rows if r["kind"] == "message" and r["epoch"] == 100.0)
    assert after["time_since_start_raw"] == 100.0
    assert after["time_since_start"] == 40.0  # 100 raw − 60 paused
