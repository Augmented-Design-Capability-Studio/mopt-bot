from fastapi.testclient import TestClient
import importlib

import pytest

from app.config import get_settings
from app.main import create_app
from app.schemas import ChatModelTurn, ProblemBriefUpdateTurn, RunTriggerIntentTurn


def test_create_session_returns_null_panel_config(monkeypatch):
    """New participant sessions must not ship default problem JSON."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-session-secret")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        r = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-session-secret"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("optimization_allowed") is False
        assert data.get("optimization_runs_blocked_by_researcher") is False
        assert data.get("participant_tutorial_enabled") is False
        assert data.get("panel_config") is None
        assert data["problem_brief"]["solver_scope"] == "general_metaheuristic_translation"
        assert data.get("test_problem_id") == "vrptw"
        sid = data["id"]
        r2 = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-client-session-secret"},
        )
        assert r2.status_code == 200
        assert r2.json().get("panel_config") is None
        assert r2.json()["processing"] == {
            "processing_revision": 0,
            "brief_status": "ready",
            "config_status": "idle",
            "processing_error": None,
        }


def test_create_session_unknown_test_problem_id_400(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-create-2")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        r = client.post(
            "/sessions",
            json={"test_problem_id": "not_a_real_problem"},
            headers={"Authorization": "Bearer test-client-create-2"},
        )
        assert r.status_code == 400


def test_run_ack_message_does_not_trigger_post_run_even_if_classifier_says_run(monkeypatch):
    """Auto-posted run-complete lines must not start optimization in the same request."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-run-ack-no-autorun-secret")
    get_settings.cache_clear()

    called = {"post_run": False}

    def fake_post_run(*args, **kwargs):
        called["post_run"] = True
        return None

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Here is my interpretation of the run.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.llm.classify_run_trigger_intent",
        lambda *args, **kwargs: RunTriggerIntentTurn(
            should_trigger_run=True,
            intent_type="direct_request",
            confidence=0.99,
            rationale="Misclassified.",
        ),
    )
    router_module = importlib.import_module("app.routers.sessions.router")
    monkeypatch.setattr(router_module, "post_run", fake_post_run)
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    run_ack_text = (
        "Run #1 just completed - cost 123.45 (5 time-window stops late). "
        "Please interpret these results, compare to any previous runs, and suggest what to adjust next."
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"workflow_mode": "agile"},
            headers={"Authorization": "Bearer test-run-ack-no-autorun-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={"panel_config": {"problem": {"weights": {"travel_time": 1}, "algorithm": "GA"}}},
            headers={"Authorization": "Bearer test-run-ack-no-autorun-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": run_ack_text, "invoke_model": True},
            headers={"Authorization": "Bearer test-run-ack-no-autorun-secret"},
        )
        assert send.status_code == 200
        assert called["post_run"] is False


def test_run_ack_agile_allows_one_assumption_patch_item(monkeypatch):
    """Agile run-ack patches may include one non-slot assumption row (bounded)."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-run-ack-assumption-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    # Return a run-ack turn with a single assumption item (non-slot) plus no panel patch.
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Noted. I'll treat that as a provisional assumption for the next iteration.",
            panel_patch=None,
            problem_brief_patch={
                "items": [
                    {
                        "id": "assumption-next-step",
                        "text": "Assume minimizing time-window misses is now the top priority.",
                        "kind": "assumption",
                        "source": "agent",
                        "status": "active",
                        "editable": True,
                    }
                ]
            },
        ),
    )
    # Ensure classifier is not called for run-ack (but even if it were, should not matter here).
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    run_ack_text = (
        "Run #1 just completed - cost 123.45 (5 time-window stops late). "
        "Please interpret these results and suggest what to adjust next."
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"workflow_mode": "agile"},
            headers={"Authorization": "Bearer test-run-ack-assumption-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": run_ack_text, "invoke_model": True},
            headers={"Authorization": "Bearer test-run-ack-assumption-secret"},
        )
        assert send.status_code == 200

        session = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-run-ack-assumption-secret"},
        )
        assert session.status_code == 200
        items = (session.json().get("problem_brief") or {}).get("items") or []
        assert any(str(i.get("id")) == "assumption-next-step" for i in items)


def test_direct_run_request_with_closed_gate_returns_guidance(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-chat-autorun-closed-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Acknowledged.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.llm.classify_run_trigger_intent",
        lambda *args, **kwargs: RunTriggerIntentTurn(
            should_trigger_run=True,
            intent_type="direct_request",
            confidence=0.93,
            rationale="User asked to start a run.",
        ),
    )
    called = {"ran": False}

    def fake_post_run(*args, **kwargs):
        called["ran"] = True
        return None

    router_module = importlib.import_module("app.routers.sessions.router")
    monkeypatch.setattr(router_module, "post_run", fake_post_run)

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"workflow_mode": "waterfall"},
            headers={"Authorization": "Bearer test-client-chat-autorun-closed-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch_brief = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Need one unresolved clarification.",
                    "items": [],
                    "open_questions": [
                        {
                            "id": "oq-block",
                            "text": "Do we allow overtime?",
                            "status": "open",
                            "answer_text": None,
                        }
                    ],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-chat-autorun-closed-secret"},
        )
        assert patch_brief.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please run optimization now.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-chat-autorun-closed-secret"},
        )
        assert send.status_code == 200
        messages = send.json()["messages"]
        assert messages[-1]["role"] == "assistant"
        assert "start a run" in messages[-1]["content"].lower()
        assert called["ran"] is False


def test_inline_sync_failure_marks_processing_failed(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-inline-sync-fail-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I will update the config.",
            panel_patch=None,
            problem_brief_patch={"goal_summary": "new"},
        ),
    )
    monkeypatch.setattr(
        "app.routers.sessions.sync.sync_panel_from_problem_brief",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("sync failed")),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-inline-sync-fail-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "please update definition", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-inline-sync-fail-secret"},
        )
        assert send.status_code == 200
        processing = send.json()["processing"]
        assert processing["brief_status"] == "failed"
        assert processing["config_status"] == "failed"
        assert "Inline problem-config sync failed" in (processing["processing_error"] or "")


def test_participant_can_patch_problem_brief(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-brief-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-brief-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Minimize lateness while keeping workload balanced.",
                    "items": [
                        {
                            "id": "fact-1",
                            "text": "On-time delivery is important.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        }
                    ],
                    "open_questions": ["How severe should overtime be?"],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                },
                "acknowledgement": "Problem definition saved.",
            },
            headers={"Authorization": "Bearer test-client-brief-secret"},
        )
        assert patch.status_code == 200
        data = patch.json()
        assert data["problem_brief"]["goal_summary"] == "Minimize lateness while keeping workload balanced."
        assert data["problem_brief"]["run_summary"] == ""
        assert any(item["kind"] == "gathered" for item in data["problem_brief"]["items"])


def test_chat_brief_patch_replaces_conflicting_population_size_fact(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-chat-pop-size-reconcile-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I removed the earlier population-size setting and kept the updated one.",
            panel_patch=None,
            problem_brief_patch={
                "items": [
                    {
                        "id": "fact-pop-size-150",
                        "text": "Population size is set to 150.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    }
                ]
            },
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-chat-pop-size-reconcile-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Tune the search effort carefully.",
                    "items": [
                        {
                            "id": "fact-pop-size-100",
                            "text": "Population size is set to 100.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        }
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-chat-pop-size-reconcile-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Actually use population size 150 and remove the old one.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-chat-pop-size-reconcile-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        brief_texts = [item["text"] for item in body["problem_brief"]["items"] if item["kind"] != "system"]
        assert "Population size is set to 150." in brief_texts
        assert "Population size is set to 100." not in brief_texts
        # The downstream `panel_config.problem.pop_size == 150` assertion was
        # dropped: with the regex/marker NLP brief-seed removed, free-text rows
        # (no `config-pop-size` ID) no longer flow into the panel via the
        # structural-only fallback.  The LLM path is the canonical route for
        # that; tested separately under sync coverage.


def test_cleanup_request_replaces_editable_brief_items(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-cleanup-replace-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I consolidated the definition and removed overlaps.",
            problem_brief_patch={
                "items": [
                    {
                        "id": "fact-single-source",
                        "text": "Use one consolidated requirement for deadline compliance.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    }
                ],
            },
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-cleanup-replace-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Clean and consistent definition.",
                    "items": [
                        {
                            "id": "fact-old-1",
                            "text": "Old gathered requirement to be removed.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "assumption-old-2",
                            "text": "Old assumption to be removed.",
                            "kind": "assumption",
                            "source": "agent",
                            "status": "active",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-cleanup-replace-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please clean up and consolidate gathered info and assumptions.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-cleanup-replace-secret"},
        )
        assert send.status_code == 200
        brief = send.json()["problem_brief"]
        non_system_ids = [item["id"] for item in brief["items"] if item["kind"] != "system"]
        assert non_system_ids == ["fact-single-source"]


def test_visible_assistant_reply_strips_hidden_patch_json(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-strip-visible-json-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message=(
                "I captured your latest answer and will keep this question open for now.\n\n"
                '{"problem_brief_patch":{"items":[{"id":"fact-1","text":"x","kind":"gathered","source":"user","status":"confirmed","editable":true}]}}'
            ),
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-strip-visible-json-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please acknowledge this answer.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-strip-visible-json-secret"},
        )
        assert send.status_code == 200
        reply = send.json()["messages"][-1]["content"]
        assert "problem_brief_patch" not in reply
        assert "I captured your latest answer" in reply


def test_upload_message_auto_clears_upload_open_question(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-upload-open-question-sync")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-upload-open-question-sync")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"workflow_mode": "waterfall"},
            headers={"Authorization": "Bearer test-client-upload-open-question-sync"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch_brief = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Need files before confirming details.",
                    "items": [],
                    "open_questions": [
                        {
                            "id": "oq-upload",
                            "text": "Please upload ORDERS.csv and DRIVER_INFO.csv before we proceed.",
                            "status": "open",
                            "answer_text": None,
                        },
                        {
                            "id": "oq-policy",
                            "text": "Should overtime be capped at 8h?",
                            "status": "open",
                            "answer_text": None,
                        },
                    ],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-upload-open-question-sync"},
        )
        assert patch_brief.status_code == 200

        upload = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "I'm uploading the following file(s): ORDERS.csv, DRIVER_INFO.csv", "invoke_model": False},
            headers={"Authorization": "Bearer test-client-upload-open-question-sync"},
        )
        assert upload.status_code == 200
        body = upload.json()
        assert body["problem_brief"] is not None
        remaining = body["problem_brief"]["open_questions"]
        assert len(remaining) == 1
        assert remaining[0]["id"] == "oq-policy"
        gathered_items = [item for item in body["problem_brief"]["items"] if item.get("kind") == "gathered"]
        upload_markers = [item for item in gathered_items if item.get("source") == "upload"]
        # Upload contributes one canonical marker row; no verbose "<question> — Uploaded file(s)
        # received: …" promotion (which used to overlap with anything else describing the upload).
        assert len(upload_markers) == 1
        assert upload_markers[0]["id"] == "item-gathered-upload"
        assert upload_markers[0]["text"] == "Source data file(s) uploaded: ORDERS.csv, DRIVER_INFO.csv."


def test_researcher_reset_session_clears_activity_but_keeps_identity_and_model(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-reset-session")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-reset-session")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"workflow_mode": "agile", "participant_number": "007"},
            headers={"Authorization": "Bearer test-client-reset-session"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch_settings = client.patch(
            f"/sessions/{sid}",
            json={"gemini_model": "gemini-3.1-flash-lite-preview", "gemini_api_key": "abc123"},
            headers={"Authorization": "Bearer test-researcher-reset-session"},
        )
        assert patch_settings.status_code == 200
        assert patch_settings.json()["gemini_key_configured"] is True

        patch_panel = client.patch(
            f"/sessions/{sid}/panel",
            json={"panel_config": {"problem": {"weights": {"travel_time": 1}, "algorithm": "GA"}}},
            headers={"Authorization": "Bearer test-client-reset-session"},
        )
        assert patch_panel.status_code == 200

        upload = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "I'm uploading the following file(s): ORDERS.csv", "invoke_model": False},
            headers={"Authorization": "Bearer test-client-reset-session"},
        )
        assert upload.status_code == 200

        run = client.post(
            f"/sessions/{sid}/runs",
            json={"type": "optimize", "problem": {"weights": {"travel_time": 1}, "algorithm": "GA"}},
            headers={"Authorization": "Bearer test-client-reset-session"},
        )
        assert run.status_code == 200

        terminate = client.post(
            f"/sessions/{sid}/terminate",
            headers={"Authorization": "Bearer test-researcher-reset-session"},
        )
        assert terminate.status_code == 200
        assert terminate.json()["status"] == "terminated"

        reset = client.post(
            f"/sessions/{sid}/reset",
            headers={"Authorization": "Bearer test-researcher-reset-session"},
        )
        assert reset.status_code == 200
        body = reset.json()
        assert body.get("content_reset_revision", 0) >= 1
        assert body["status"] == "active"
        assert body["participant_number"] == "007"
        assert body["gemini_key_configured"] is True
        assert body["gemini_model"] == "gemini-3.1-flash-lite-preview"
        assert body["panel_config"] is None
        assert body["problem_brief"]["items"] == []
        assert body["problem_brief"]["open_questions"] == []
        assert body["optimization_allowed"] is False
        assert body["optimization_runs_blocked_by_researcher"] is False
        assert body["participant_tutorial_enabled"] is False
        assert body["optimization_gate_engaged"] is False

        msgs = client.get(
            f"/sessions/{sid}/messages/researcher?after_id=0",
            headers={"Authorization": "Bearer test-researcher-reset-session"},
        )
        assert msgs.status_code == 200
        assert msgs.json() == []

        runs = client.get(
            f"/sessions/{sid}/runs",
            headers={"Authorization": "Bearer test-researcher-reset-session"},
        )
        assert runs.status_code == 200
        assert runs.json() == []

        snaps = client.get(
            f"/sessions/{sid}/snapshots",
            headers={"Authorization": "Bearer test-client-reset-session"},
        )
        assert snaps.status_code == 200
        assert snaps.json() == []


def test_panel_save_with_goal_terms_change_does_not_crash_on_missing_markers(monkeypatch):
    """Regression: when the participant edits goal-term type/weight and saves,
    the validator path used to call ``port.weight_slot_markers()`` even on
    user-driven saves. The per-problem ports (knapsack, vrptw) dropped that
    method when the marker tables were retired, so the call raised
    AttributeError mid-request and the panel save 500'd. The validator already
    ignores the kwarg (``**_unused``); the call site shouldn't fetch a value
    just to throw it away.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-panel-save-markers-secret")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"workflow_mode": "agile"},
            headers={"Authorization": "Bearer test-panel-save-markers-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        # Save a panel that exercises the goal_terms-changed branch (this is
        # the path that called port.weight_slot_markers()).
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "travel_time": {"weight": 2.0, "type": "objective", "rank": 1},
                            "lateness_penalty": {"weight": 50.0, "type": "soft", "rank": 2},
                        },
                        "goal_term_order": ["travel_time", "lateness_penalty"],
                        "algorithm": "GA",
                    }
                }
            },
            headers={"Authorization": "Bearer test-panel-save-markers-secret"},
        )
        assert patch.status_code == 200, (
            f"Expected 200, got {patch.status_code}: {patch.text}"
        )
        # The saved panel round-trips with the new goal_terms intact.
        body = patch.json()
        saved = body.get("panel_config", {}).get("problem", {})
        assert "goal_terms" in saved
        assert "lateness_penalty" in saved["goal_terms"]
        assert saved["goal_terms"]["lateness_penalty"]["weight"] == 50.0
        assert saved["goal_terms"]["lateness_penalty"]["type"] == "soft"


def test_mediocre_push_mirrors_into_brief_and_stays_cold(monkeypatch):
    """Researcher-pushed mediocre baseline mirrors into the brief so the drift
    banner stays empty, but does NOT flip ``topic_engaged`` — the next chat
    turn still gets the cold-start prompt (upload OQ, neutral framing)."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-mediocre-push")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-mediocre-push")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-mediocre-push"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        push = client.post(
            f"/sessions/{sid}/participant-starter-panel",
            headers={"Authorization": "Bearer test-researcher-mediocre-push"},
        )
        assert push.status_code == 200
        out = push.json()
        panel_goal_terms = out["panel_config"]["problem"].get("goal_terms") or {}
        assert "travel_time" in panel_goal_terms
        assert "workload_balance" in panel_goal_terms
        assert out["brief_panel_drift"] == [], out["brief_panel_drift"]
        brief_item_ids = {item["id"] for item in out["problem_brief"]["items"]}
        assert "config-weight-travel_time" in brief_item_ids
        assert "config-weight-workload_balance" in brief_item_ids


def test_resync_brief_from_panel_idempotent_on_aligned_session(monkeypatch):
    """POST /resync-brief-from-panel is idempotent — repeating it on an
    already-aligned session leaves drift empty."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-resync-brief")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-resync-brief")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-resync-brief"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        client.post(
            f"/sessions/{sid}/participant-starter-panel",
            headers={"Authorization": "Bearer test-researcher-resync-brief"},
        )
        resync = client.post(
            f"/sessions/{sid}/resync-brief-from-panel",
            headers={"Authorization": "Bearer test-client-resync-brief"},
        )
        assert resync.status_code == 200
        assert resync.json()["brief_panel_drift"] == []
