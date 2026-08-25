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
    """Client with the analysis DB pre-seeded with one loaded session (plus one
    chat exchange), so lock/guard + LLM-tag-cache behaviour can be tested
    without a sample export. Yields ``(client, loaded_id, sessionmaker)``."""
    from app.analysis import models as m

    url = f"sqlite:///{(tmp_path / 'analysis_lock.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    AnalysisBase.metadata.create_all(bind=engine)
    Local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Local()
    loaded = m.LoadedSession(source_session_id="s1", participant_number="P01", workflow_mode="agile")
    db.add(loaded)
    db.flush()
    db.add(m.LoadedMessage(
        loaded_session_id=loaded.id, source_id=1, ts_epoch=1.0,
        role="user", kind="chat", content="please cap the load",
    ))
    db.add(m.LoadedMessage(
        loaded_session_id=loaded.id, source_id=2, ts_epoch=2.0,
        role="assistant", kind="chat", content="Added a capacity limit.",
    ))
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
    yield TestClient(app), lid, Local
    app.dependency_overrides.pop(get_analysis_db, None)


def test_lock_blocks_edits_then_unlock_restores(seeded_client):
    """A locked session rejects every coding mutation (423) but the lock toggle
    and unlock stay reachable; the LLM tagging pass skips locked sessions
    instead of erroring."""
    client, lid, _local = seeded_client
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

    # the LLM tagging pass skips locked sessions rather than rewriting their cache
    r = client.post("/analysis/llm-tags", json={"loaded_id": lid, "api_key": "k"}, headers=_auth())
    assert r.status_code == 200 and r.json()["sessions"] == 0 and r.json()["skipped_locked"] == 1

    # unlock re-enables editing
    r = client.post(f"/analysis/loaded/{lid}/lock", json={"locked": False}, headers=_auth())
    assert r.status_code == 200 and r.json()["session"]["locked"] is False
    assert client.post(f"/analysis/loaded/{lid}/annotations", json=note, headers=_auth()).status_code == 200


def test_llm_tags_no_key_is_pure_noop(seeded_client):
    """Without an api_key the /llm-tags endpoint must NOT touch the cache (the
    old origin endpoint destructively wrote empty results — this one keeps it)."""
    from app.analysis import models as m

    client, lid, Local = seeded_client
    seeded = json.dumps({"message:2": [
        {"origin": "user", "type": "goal-term", "term": "capacity_penalty",
         "effect": "applied", "rationale": "user asked to cap the load"},
    ]})
    db = Local()
    db.add(m.CodingLlmTags(loaded_session_id=lid, data_json=seeded, model="test"))
    db.commit()
    db.close()

    r = client.post("/analysis/llm-tags", json={"loaded_id": lid}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["ran_llm"] is False and body["sessions"] == 0

    db = Local()
    doc = db.get(m.CodingLlmTags, lid)
    assert doc is not None and doc.data_json == seeded  # cache untouched
    db.close()


def test_timeline_merges_cached_llm_tags(seeded_client):
    """Cached LLM tags surface as suggested_changes (with rationale) on the
    matching codeable exchange row."""
    from app.analysis import models as m

    client, lid, Local = seeded_client
    db = Local()
    db.add(m.CodingLlmTags(loaded_session_id=lid, data_json=json.dumps({
        "message:2": [{"origin": "user", "type": "goal-term", "term": "capacity_penalty",
                       "effect": "applied", "rationale": "user asked to cap the load"}],
    }), model="test"))
    db.commit()
    db.close()

    detail = client.get(f"/analysis/loaded/{lid}/timeline", headers=_auth()).json()
    row = next(r for r in detail["timeline"] if r.get("row_ref") == "message:2")
    assert row["codeable"] is True
    tags = row["suggested_changes"]
    assert any(
        t["term"] == "capacity_penalty" and t["effect"] == "applied"
        and t.get("rationale") == "user asked to cap the load"
        for t in tags
    )

    # Dismissing the suggestion (a persisted `dismiss` annotation) removes it
    # from suggested_changes on subsequent loads — and never renders as a row.
    r = client.post(
        f"/analysis/loaded/{lid}/annotations",
        json={"anno_type": "dismiss", "row_ref": "message:2",
              "text": json.dumps({"origin": "user", "type": "goal-term",
                                  "term": "capacity_penalty", "effect": "applied"})},
        headers=_auth(),
    )
    assert r.status_code == 200
    detail = client.get(f"/analysis/loaded/{lid}/timeline", headers=_auth()).json()
    row = next(r for r in detail["timeline"] if r.get("row_ref") == "message:2")
    assert not any(t["term"] == "capacity_penalty" for t in row["suggested_changes"] or [])
    assert not any(r.get("kind") == "dismiss" for r in detail["timeline"])


def test_llm_tags_purge_relabels_only_on_success(seeded_client, monkeypatch):
    """purge_tags deletes accepted code tags (and old dismissals) ONLY for
    sessions whose LLM run succeeded; notes survive."""
    from app.analysis import models as m
    from app.routers import analysis as ar

    client, lid, Local = seeded_client
    # seed: one accepted tag, one dismissal, one note
    for body in (
        {"anno_type": "code", "row_ref": "message:2",
         "text": json.dumps({"origin": "agent", "type": "weight", "term": "capacity_penalty", "effect": "applied"})},
        {"anno_type": "dismiss", "row_ref": "message:2",
         "text": json.dumps({"origin": "user", "type": "goal-term", "term": "capacity_penalty", "effect": "applied"})},
        {"anno_type": "note", "row_ref": "message:2", "text": "keep me"},
    ):
        assert client.post(f"/analysis/loaded/{lid}/annotations", json=body, headers=_auth()).status_code == 200

    fresh = {"message:2": [{"origin": "user", "type": "goal-term", "term": "capacity_penalty",
                            "effect": "applied", "rationale": "fresh"}]}
    monkeypatch.setattr(ar, "tag_session_changes", lambda *a, **k: fresh)
    r = client.post("/analysis/llm-tags",
                    json={"loaded_id": lid, "api_key": "k", "purge_tags": True}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["purged_tags"] == 2 and body["sessions"] == 1  # code + dismiss gone

    db = Local()
    kinds = [a.anno_type for a in db.query(m.Annotation).filter_by(loaded_session_id=lid).all()]
    assert kinds == ["note"]  # only the note survives
    db.close()

    # failed run purges NOTHING
    assert client.post(f"/analysis/loaded/{lid}/annotations",
                       json={"anno_type": "code", "row_ref": "message:2",
                             "text": json.dumps({"origin": "user", "type": "weight",
                                                 "term": "capacity_penalty", "effect": "applied"})},
                       headers=_auth()).status_code == 200
    monkeypatch.setattr(ar, "tag_session_changes", lambda *a, **k: None)
    r = client.post("/analysis/llm-tags",
                    json={"loaded_id": lid, "api_key": "k", "purge_tags": True}, headers=_auth())
    assert r.json()["failed"] == 1 and r.json()["purged_tags"] == 0
    db = Local()
    assert db.query(m.Annotation).filter_by(loaded_session_id=lid, anno_type="code").count() == 1
    db.close()


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
    # config_change is the STRUCTURED diff (a dict), not a JSON dump; a panel
    # change outside the modeled fields flags "other".
    assert changes[1]["config_change"] == {"other": True}


def test_snapshot_diff_strips_brief_mirror():
    """A brief change confined to goal_terms/runs (the config mirror / run
    history) is NOT a def Δ, and the emitted def Δ never contains goal_terms."""
    def snap(i, brief, panel):
        return SimpleNamespace(
            id=i, ts_epoch=float(i), problem_brief_json=brief, panel_config_json=panel
        )

    b1 = json.dumps({"items": [{"id": "x"}], "goal_terms": {"a": {"weight": 1}}, "runs": []})
    b2 = json.dumps({"items": [{"id": "x"}], "goal_terms": {"a": {"weight": 9}}, "runs": [1]})
    b3 = json.dumps({"items": [{"id": "x"}, {"id": "y"}], "goal_terms": {"a": {"weight": 9}}, "runs": [1]})
    snaps = [snap(1, b1, "{}"), snap(2, b2, "{}"), snap(3, b3, "{}")]
    changes = compute_definition_config_changes(snaps)
    assert "definition_change" in changes[1]
    assert "goal_terms" not in changes[1]["definition_change"]
    assert 2 not in changes  # goal_terms/runs churn only → no def Δ
    assert 3 in changes and "definition_change" in changes[3]  # items changed → fires


class _FakePort:
    def weight_display_keys(self):
        return ["lateness_penalty", "travel_time", "capacity_penalty"]

    def formulation_quality_for_config(self, panel):
        prob = panel.get("problem") or panel
        gt = prob.get("goal_terms") or {}
        return {"captured_terms": [k for k, v in gt.items() if (v.get("weight") or 0) != 0]}


def test_turn_derivations_emit_search_tags_and_structured_diff():
    """A reply's result is the NEXT turn's pre-state. Deterministic suggestions
    are now ONLY the search tags (goal-term tags come from the LLM pass); the
    goal-term facts land in the structured config diff, and the def Δ is the
    stripped brief (no goal_terms mirror)."""
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
        "capacity_penalty": {"weight": 3, "type": "hard", "rank": 3},  # added
    }}, items=[
        {"id": "i-cap", "kind": "gathered", "goal_key": "capacity_penalty"},
        {"id": "i-lat", "kind": "gathered", "goal_key": "lateness_penalty"},
    ])

    d = build_turn_derivations([m1, m2], _FakePort())["message:1"]
    # Deterministic suggestions: search tags ONLY — no mechanical goal-term tags.
    assert [(c["type"], c["term"]) for c in d["changes"]] == [("search-strategy", None)]
    # The goal-term facts live in the structured config diff instead.
    diff = d["config_change"]
    assert diff["algorithm"] == {"from": "GA", "to": "PSO"}
    assert diff["added"] == [{"term": "capacity_penalty", "weight": 3, "type": "hard", "rank": 3}]
    lat = next(t for t in diff["terms"] if t["term"] == "lateness_penalty")
    assert {"field": "weight", "from": 5, "to": 10} in lat["changes"]
    assert "params" not in diff  # param churn suppressed on an algorithm switch
    # Def Δ fires (items changed) but never carries the goal_terms mirror.
    assert d["definition_change"] is not None and "goal_terms" not in d["definition_change"]
    assert "capacity_penalty" in d["captured_terms"]


def test_turn_derivations_def_delta_ignores_mirror_churn():
    """A brief change confined to goal_terms (config mirror) produces NO def Δ —
    that change belongs to the cfg Δ."""
    from app.analysis.coding_suggestions import build_turn_derivations

    def msg(i, weight, items):
        prob = {"algorithm": "GA", "goal_terms": {"lateness_penalty": {"weight": weight, "type": "hard", "rank": 1}}}
        brief = {"goal_terms": prob["goal_terms"], "items": items}
        meta = {"pre_turn_state": {"problem_brief": brief, "panel_config": {"problem": prob}}}
        return SimpleNamespace(id=i, source_id=i, ts_epoch=float(i), meta_json=json.dumps(meta))

    items = [{"id": "x", "kind": "gathered"}]
    d = build_turn_derivations([msg(1, 5, items), msg(2, 10, items)], _FakePort())["message:1"]
    assert d["definition_change"] is None  # only the goal_terms mirror moved
    assert d["config_change"] is not None  # …and that's a cfg Δ (weight 5→10)


def test_reason_suggestions_and_annotation_fold(seeded_client):
    """Run rows get deterministic reason suggestions from the between-run window;
    an accepted `reason` annotation folds onto its row; /llm-reasons without a
    key is a pure no-op that keeps the cache."""
    from app.analysis import models as m
    from app.analysis.reason_llm import reasons_from_diffs

    # deterministic mapping sanity (pure function)
    assert reasons_from_diffs([]) == ["stochastic-rerun"]
    assert reasons_from_diffs([{"added": [{"term": "x"}]}]) == ["new-goal-term"]
    assert reasons_from_diffs([{"terms": [{"term": "x", "changes": [{"field": "weight"}]}],
                               "algorithm": {"from": "GA", "to": "PSO"}}]) == [
        "weight-rebalance", "algorithm-switch"]
    # soft↔custom is the weight-unlock mechanic, NOT a semantic type change…
    assert reasons_from_diffs([{"terms": [{"term": "x", "changes": [
        {"field": "type", "from": "soft", "to": "custom"}]}]}]) == []
    # …but a transition involving hard/objective counts.
    assert reasons_from_diffs([{"terms": [{"term": "x", "changes": [
        {"field": "type", "from": "custom", "to": "hard"}]}]}]) == ["term-type-change"]
    assert reasons_from_diffs([{"params": [{"field": "epochs"}, {"field": "pc"}]}]) == [
        "search-budget", "knob-tuning"]

    client, lid, Local = seeded_client
    # reason annotation folds onto its row_ref
    r = client.post(
        f"/analysis/loaded/{lid}/annotations",
        json={"anno_type": "reason", "row_ref": "message:2",
              "text": json.dumps({"reasons": ["weight-rebalance"], "note": "test"})},
        headers=_auth(),
    )
    assert r.status_code == 200
    detail = client.get(f"/analysis/loaded/{lid}/timeline", headers=_auth()).json()
    row = next(x for x in detail["timeline"] if x.get("row_ref") == "message:2")
    assert row["reasons"] == {"id": r.json()["id"], "reasons": ["weight-rebalance"], "note": "test"}
    # never a standalone row
    assert not any(x.get("kind") == "reason" for x in detail["timeline"])

    # /llm-reasons no-key no-op keeps a pre-seeded cache
    db = Local()
    db.add(m.CodingLlmReasons(loaded_session_id=lid, data_json='{"run:1": []}', model="t"))
    db.commit(); db.close()
    res = client.post("/analysis/llm-reasons", json={"loaded_id": lid}, headers=_auth())
    assert res.status_code == 200 and res.json()["ran_llm"] is False
    db = Local()
    assert db.get(m.CodingLlmReasons, lid).data_json == '{"run:1": []}'
    db.close()

    # reset-reasons deletes ONLY the reason layer (labels + reason dismissals);
    # change tags survive.
    assert client.post(
        f"/analysis/loaded/{lid}/annotations",
        json={"anno_type": "code", "row_ref": "message:2",
              "text": json.dumps({"origin": "user", "type": "weight",
                                  "term": "capacity_penalty", "effect": "applied"})},
        headers=_auth(),
    ).status_code == 200
    assert client.post(
        f"/analysis/loaded/{lid}/annotations",
        json={"anno_type": "dismiss-reason", "row_ref": "run:1",
              "text": json.dumps({"reason": "knob-tuning"})},
        headers=_auth(),
    ).status_code == 200
    res = client.post(f"/analysis/loaded/{lid}/reset-reasons", headers=_auth())
    assert res.status_code == 200 and res.json()["deleted"] == 2  # reason + dismiss-reason
    db = Local()
    kinds = sorted(a.anno_type for a in db.query(m.Annotation).filter_by(loaded_session_id=lid).all())
    assert "reason" not in kinds and "dismiss-reason" not in kinds and "code" in kinds
    db.close()


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
