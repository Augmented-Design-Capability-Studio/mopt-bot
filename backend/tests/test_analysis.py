"""Tests for the session-coding analysis tool.

Covers the three verification points from the plan: (1) load copies match the
source counts, (2) the snapshot diff is change-only, (3) time-since-start is
pause-aware. Kept lean (per test-minimalism): one HTTP round-trip test plus two
pure-function tests.
"""

from __future__ import annotations

import glob
import json
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


@pytest.fixture
def seeded_client(tmp_path):
    """Client with the analysis DB pre-seeded with one bare loaded session, so
    lock/guard behaviour can be tested without a sample export."""
    from app.analysis import models as m

    url = f"sqlite:///{(tmp_path / 'analysis_lock.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    AnalysisBase.metadata.create_all(bind=engine)
    Local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Local()
    loaded = m.LoadedSession(source_session_id="s1", participant_number="P01", workflow_mode="agile")
    db.add(loaded)
    db.commit()
    lid = loaded.id
    db.close()

    def _override():
        d = Local()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_analysis_db] = _override
    yield TestClient(app), lid
    app.dependency_overrides.pop(get_analysis_db, None)


def test_lock_blocks_edits_then_unlock_restores(seeded_client):
    """A locked session rejects every coding mutation (423) but the lock toggle
    and unlock stay reachable; classify-origin skips locked sessions instead of
    erroring."""
    client, lid = seeded_client
    note = {"anno_type": "note", "text": "x"}

    # editable while unlocked
    assert client.post(f"/analysis/loaded/{lid}/annotations", json=note, headers=_auth()).status_code == 200

    # lock it
    r = client.post(f"/analysis/loaded/{lid}/lock", json={"locked": True}, headers=_auth())
    assert r.status_code == 200 and r.json()["session"]["locked"] is True

    # every mutation now rejected with 423 Locked
    assert client.post(f"/analysis/loaded/{lid}/annotations", json=note, headers=_auth()).status_code == 423
    assert client.post(f"/analysis/loaded/{lid}/reset-tags", headers=_auth()).status_code == 423
    assert client.patch(
        f"/analysis/loaded/{lid}/coding-meta", json={"video_filename": "v.mp4"}, headers=_auth()
    ).status_code == 423

    # classify-origin skips locked sessions rather than rewriting their cache
    r = client.post("/analysis/classify-origin", json={"loaded_id": lid}, headers=_auth())
    assert r.status_code == 200 and r.json()["sessions"] == 0 and r.json()["skipped_locked"] == 1

    # unlock re-enables editing
    r = client.post(f"/analysis/loaded/{lid}/lock", json={"locked": False}, headers=_auth())
    assert r.status_code == 200 and r.json()["session"]["locked"] is False
    assert client.post(f"/analysis/loaded/{lid}/annotations", json=note, headers=_auth()).status_code == 200


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


class _FakePort:
    def weight_display_keys(self):
        return ["lateness_penalty", "travel_time", "capacity_penalty"]

    def formulation_quality_for_config(self, panel):
        prob = panel.get("problem") or panel
        gt = prob.get("goal_terms") or {}
        return {"captured_terms": [k for k, v in gt.items() if (v.get("weight") or 0) != 0]}


def test_turn_derivations_emit_composite_changes():
    """A reply's changes are tagged on the exchange that produced them (the diff
    of that reply's pre-state vs its result), as composite {origin, type, term,
    effect} records. Origin comes from the brief's provenance (gathered ⇒ user)."""
    from app.analysis.coding_suggestions import build_turn_derivations

    def msg(i, prob, items=None):
        brief = {"goal_terms": prob["goal_terms"], "items": items or []}
        meta = {"pre_turn_state": {"problem_brief": brief, "panel_config": {"problem": prob}}}
        return SimpleNamespace(id=i, source_id=i, ts_epoch=float(i), meta_json=json.dumps(meta))

    m1 = msg(1, {"algorithm": "GA", "goal_terms": {
        "lateness_penalty": {"weight": 5, "type": "hard", "rank": 1},
        "travel_time": {"weight": 1, "type": "objective", "rank": 2},
    }})
    m2 = msg(2, {"algorithm": "PSO", "goal_terms": {  # search-strategy change
        "lateness_penalty": {"weight": 10, "type": "hard", "rank": 1},  # weight change
        "travel_time": {"weight": 1, "type": "objective", "rank": 2},
        "capacity_penalty": {"weight": 3, "type": "hard", "rank": 3},  # added (user)
    }}, items=[  # the resulting brief records user-gathered provenance
        {"id": "i-cap", "kind": "gathered", "goal_key": "capacity_penalty"},
        {"id": "i-lat", "kind": "gathered", "goal_key": "lateness_penalty"},
    ])

    # The reply at m1 produces the state seen in m2, so its changes are tagged on
    # message:1 (diff of m1's pre-state vs its result m2).
    d = build_turn_derivations([m1, m2], _FakePort())["message:1"]
    changes = d["changes"]
    kinds = {(c["type"], c["term"]) for c in changes}
    assert ("weight", "lateness_penalty") in kinds
    assert ("goal-term", "capacity_penalty") in kinds
    assert ("search-strategy", None) in kinds
    cap = next(c for c in changes if c["term"] == "capacity_penalty")
    assert cap["origin"] == "user" and cap["effect"] == "applied" and cap["captured"]
    assert d["config_change"] is not None and d["definition_change"] is not None


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
