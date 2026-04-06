from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.schemas import ChatModelTurn


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
        assert data.get("panel_config") is None
        assert data["problem_brief"]["solver_scope"] == "general_metaheuristic_translation"
        assert any(item["kind"] == "system" for item in data["problem_brief"]["items"])
        sid = data["id"]
        r2 = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-client-session-secret"},
        )
        assert r2.status_code == 200
        assert r2.json().get("panel_config") is None
        assert any(item["kind"] == "system" for item in r2.json()["problem_brief"]["items"])
        assert r2.json()["processing"] == {
            "processing_revision": 0,
            "brief_status": "ready",
            "config_status": "idle",
            "processing_error": None,
        }


def test_message_response_marks_processing_pending_before_background_finishes(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-processing-pending-secret")
    get_settings.cache_clear()

    launched: dict[str, object] = {}

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I have the chat response ready while I rebuild the panels.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: launched.update(kwargs),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-processing-pending-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can you help refine this?", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-processing-pending-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        assert body["messages"][-1]["content"] == "I have the chat response ready while I rebuild the panels."
        assert body["processing"]["brief_status"] == "pending"
        assert body["processing"]["config_status"] == "pending"
        assert body["processing"]["processing_revision"] == 1
        assert launched["session_id"] == sid
        assert launched["revision"] == 1

        session = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-client-processing-pending-secret"},
        )
        assert session.status_code == 200
        assert session.json()["processing"]["brief_status"] == "pending"
        assert session.json()["processing"]["config_status"] == "pending"


def test_skip_hidden_brief_update_skips_background_and_settles_processing(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-skip-hidden-brief-secret")
    get_settings.cache_clear()

    launched: dict[str, object] = {}

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Acknowledged your manual definition save.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: launched.update(kwargs),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-skip-hidden-brief-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        send = client.post(
            f"/sessions/{sid}/messages",
            json={
                "content": "I just manually updated the problem definition. Summary: goal.",
                "invoke_model": True,
                "skip_hidden_brief_update": True,
            },
            headers={"Authorization": "Bearer test-client-skip-hidden-brief-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        assert body["messages"][-1]["content"] == "Acknowledged your manual definition save."
        assert body["processing"]["brief_status"] == "ready"
        assert body["processing"]["config_status"] == "idle"
        assert launched == {}

        session = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-client-skip-hidden-brief-secret"},
        )
        assert session.status_code == 200
        assert session.json()["processing"]["brief_status"] == "ready"


def test_post_message_without_model_returns_current_processing_state(monkeypatch):
    """invoke_model false must still return processing so the client can clear stale pending UI."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-no-model-proc-secret")
    get_settings.cache_clear()

    from app.database import SessionLocal
    from app.models import StudySession

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-no-model-proc-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        with SessionLocal() as db:
            row = db.get(StudySession, sid)
            assert row is not None
            row.brief_status = "pending"
            row.config_status = "pending"
            row.processing_revision = 5
            db.commit()

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "User note only", "invoke_model": False},
            headers={"Authorization": "Bearer test-client-no-model-proc-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        assert body["processing"] is not None
        assert body["processing"]["brief_status"] == "pending"
        assert body["processing"]["config_status"] == "pending"
        assert body["processing"]["processing_revision"] == 5


def test_steer_messages_hidden_and_forwarded_to_next_model_turn(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-steer-secret")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-steer-secret")
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    def fake_generate_chat_turn(*args, **kwargs):
        captured["researcher_steers"] = kwargs.get("researcher_steers")
        captured["current_problem_brief"] = args[4] if len(args) > 4 else None
        return ChatModelTurn(
            assistant_message="I can shift strategy on the next iteration while keeping the same thread.",
            panel_patch=None,
            problem_brief_patch=None,
        )

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr("app.services.llm.generate_chat_turn", fake_generate_chat_turn)

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-steer-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        steer = client.post(
            f"/sessions/{sid}/steer",
            json={"content": "Prioritize deadline reliability and avoid abrupt tone shifts."},
            headers={"Authorization": "Bearer test-researcher-steer-secret"},
        )
        assert steer.status_code == 200
        assert steer.json()["visible_to_participant"] is False

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can we tune this further?", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-steer-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        assert len(body["messages"]) == 2
        assert body["messages"][-1]["role"] == "assistant"
        assert captured["researcher_steers"] == [
            "Prioritize deadline reliability and avoid abrupt tone shifts."
        ]
        assert captured["current_problem_brief"] is not None

        visible_msgs = client.get(
            f"/sessions/{sid}/messages?after_id=0",
            headers={"Authorization": "Bearer test-client-steer-secret"},
        )
        assert visible_msgs.status_code == 200
        roles = [m["role"] for m in visible_msgs.json()]
        assert "researcher" not in roles


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
        assert any(item["kind"] == "gathered" for item in data["problem_brief"]["items"])
        assert any(item["kind"] == "system" for item in data["problem_brief"]["items"])


def test_problem_brief_open_questions_are_split(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-brief-split-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-brief-split-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Clarify unresolved trade-offs.",
                    "items": [],
                    "open_questions": [
                        "How strict should lateness be? Should overtime be capped?",
                        "1. Do we need balanced workloads?\n2. Are fixed assignments required?",
                    ],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-brief-split-secret"},
        )
        assert patch.status_code == 200
        questions = [q["text"] for q in patch.json()["problem_brief"]["open_questions"]]
        assert questions == [
            "How strict should lateness be?",
            "Should overtime be capped?",
            "Do we need balanced workloads?",
            "Are fixed assignments required?",
        ]


def test_problem_brief_answered_open_question_promoted_to_gathered(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-open-question-answer-roundtrip-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-open-question-answer-roundtrip-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Track unanswered clarifications with explicit answers.",
                    "items": [],
                    "open_questions": [
                        {
                            "id": "oq-answered",
                            "text": "What overtime cap should we enforce?",
                            "status": "answered",
                            "answer_text": "Cap overtime at 30 minutes per shift.",
                        },
                        "Which deliveries are highest priority?",
                    ],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-open-question-answer-roundtrip-secret"},
        )
        assert patch.status_code == 200
        brief = patch.json()["problem_brief"]
        questions = brief["open_questions"]
        assert len(questions) == 1
        assert questions[0]["text"] == "Which deliveries are highest priority?"
        assert questions[0]["status"] == "open"
        assert questions[0]["answer_text"] is None
        gathered_texts = [item["text"] for item in brief["items"] if item["kind"] == "gathered"]
        assert any(
            "overtime cap" in t.lower() and "30 minutes" in t.lower() for t in gathered_texts
        )


def test_waterfall_can_infer_first_panel_from_complete_problem_brief(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-waterfall-infer-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I have enough detail to set up the run.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-waterfall-infer-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery driver scheduling for fuel efficiency and travel time.",
                    "items": [
                        {
                            "id": "fact-capacity-hard",
                            "text": "Capacity limits are a hard requirement.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-deadline-soft",
                            "text": "Late arrivals should incur a moderate penalty.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-algorithm-pso",
                            "text": "User selected Particle Swarm Optimization as the search strategy.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-waterfall-infer-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can you generate the problem config again?", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-waterfall-infer-secret"},
        )
        assert send.status_code == 200
        body = send.json()

        assert body["panel_config"] is not None
        assert body["panel_config"]["problem"]["algorithm"] == "PSO"
        assert body["panel_config"]["problem"]["weights"]["capacity_penalty"] == 1000.0
        assert body["panel_config"]["problem"]["weights"]["deadline_penalty"] == 50.0

        session = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-client-waterfall-infer-secret"},
        )
        assert session.status_code == 200
        assert session.json()["panel_config"]["problem"]["algorithm"] == "PSO"


def test_problem_brief_save_reconciles_panel_from_brief(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-brief-reconcile-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-brief-reconcile-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery driver scheduling for fuel efficiency and travel time.",
                    "items": [
                        {
                            "id": "fact-capacity-hard",
                            "text": "Capacity limits are a hard requirement.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-deadline-soft",
                            "text": "Late arrivals should incur a moderate penalty.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-algorithm-pso",
                            "text": "User selected Particle Swarm Optimization as the search strategy.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-brief-reconcile-secret"},
        )
        assert patch.status_code == 200
        panel = patch.json()["panel_config"]["problem"]
        assert panel["algorithm"] == "PSO"
        assert panel["weights"] == {
            "travel_time": 1.0,
            "fuel_cost": 1.0,
            "capacity_penalty": 1000.0,
            "deadline_penalty": 50.0,
        }


def test_chat_can_override_pushed_starter_panel(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-override-starter-secret")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-override-starter-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I can align the configuration with the chosen search strategy.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-override-starter-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        push = client.post(
            f"/sessions/{sid}/participant-starter-panel",
            headers={"Authorization": "Bearer test-researcher-override-starter-secret"},
        )
        assert push.status_code == 200
        assert push.json()["panel_config"]["problem"]["algorithm"] == "SA"

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery driver scheduling for fuel efficiency and travel time.",
                    "items": [
                        {
                            "id": "fact-capacity-hard",
                            "text": "Capacity limits are a hard requirement.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-deadline-soft",
                            "text": "Late arrivals should incur a moderate penalty.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-algorithm-pso",
                            "text": "User selected Particle Swarm Optimization as the search strategy.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-override-starter-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please generate the problem config again and get it ready to run.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-override-starter-secret"},
        )
        assert send.status_code == 200
        panel = send.json()["panel_config"]["problem"]
        assert panel["algorithm"] == "PSO"
        assert panel["weights"] == {
            "travel_time": 1.0,
            "fuel_cost": 1.0,
            "capacity_penalty": 1000.0,
            "deadline_penalty": 50.0,
        }
        assert panel["algorithm_params"] == {"c1": 2.0, "c2": 2.0, "w": 0.4}


def test_completed_delivery_brief_syncs_config_without_model_panel_patch(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-delivery-brief-sync-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I've wired up the solver configuration based on our plan.",
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-delivery-brief-sync-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery fleet operations focusing on punctuality and strict resource limits using uploaded data and traffic patterns.",
                    "items": [
                        {
                            "id": "fact-domain-delivery",
                            "text": "The problem domain is logistics and delivery fleet routing.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-data-uploaded",
                            "text": "Order data and driver/vehicle information have been provided via file upload.",
                            "kind": "gathered",
                            "source": "upload",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-punctuality-confirmed",
                            "text": "Deadline compliance is the top priority for the objective function.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-hard-constraints-confirmed",
                            "text": "Vehicle capacity and driver shift limits are treated as strict constraints.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-workload-secondary",
                            "text": "Workload balance across drivers is set to 50.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": ["Which drivers should receive the shortest shifts?"],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-delivery-brief-sync-secret"},
        )
        assert patch.status_code == 200
        panel = patch.json()["panel_config"]["problem"]
        assert panel["algorithm"] == "GA"
        assert panel["weights"]["deadline_penalty"] == 120.0
        assert panel["weights"]["capacity_penalty"] == 1000.0
        assert panel["weights"]["workload_balance"] == 50.0
        assert panel["shift_hard_penalty"] == 1000.0

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Great. Now you may generate some config", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-delivery-brief-sync-secret"},
        )
        assert send.status_code == 200
        assert send.json()["panel_config"]["problem"]["algorithm"] == "GA"


def test_chat_brief_patch_rebuilds_config_from_definition(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-chat-brief-config-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Switching the search strategy and raising workload balance.",
            panel_patch=None,
            problem_brief_patch={
                "items": [
                    {
                        "id": "fact-deadline",
                        "text": "Deadline compliance matters.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    },
                    {
                        "id": "fact-capacity",
                        "text": "Vehicle capacity is a strict constraint.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    },
                    {
                        "id": "fact-algorithm-ga",
                        "text": "Genetic Algorithm (GA) is selected for the search strategy.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    },
                    {
                        "id": "fact-workload-balance",
                        "text": "Workload balance is set to 50 to ensure equitable shift durations.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    },
                ]
            },
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-chat-brief-config-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery routes with strict capacity and deadline handling.",
                    "items": [
                        {
                            "id": "fact-deadline",
                            "text": "Deadline compliance matters.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-capacity",
                            "text": "Vehicle capacity is a strict constraint.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-chat-brief-config-secret"},
        )
        assert patch.status_code == 200
        assert patch.json()["panel_config"]["problem"]["algorithm"] == "GA"

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please change the algorithm to GA and set workload balance to 50.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-chat-brief-config-secret"},
        )
        assert send.status_code == 200
        assert send.json()["panel_config"]["problem"]["algorithm"] == "GA"
        assert send.json()["panel_config"]["problem"]["weights"]["workload_balance"] == 50.0


def test_partial_problem_brief_patch_preserves_prior_facts_for_config_derivation(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-partial-brief-patch-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I've switched the solver over to the SwarmSA algorithm.",
            panel_patch=None,
            problem_brief_patch={
                "items": [
                    {
                        "id": "goal-delivery-scheduling",
                        "text": "User wants to optimize scheduling for a delivery fleet.",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    },
                    {
                        "id": "fact-algorithm-swarmsa",
                        "text": "Use Swarm-based Simulated Annealing (SwarmSA)",
                        "kind": "gathered",
                        "source": "user",
                        "status": "confirmed",
                        "editable": True,
                    },
                ],
                "open_questions": [
                    "What are the specific vehicle capacity limits?",
                    "What is the preferred balance between travel time and workload fairness?",
                ],
            },
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-partial-brief-patch-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery fleet operations.",
                    "items": [
                        {
                            "id": "fact-domain-delivery",
                            "text": "The problem domain is logistics and delivery fleet routing.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-punctuality-confirmed",
                            "text": "Deadline compliance is the top priority for the objective function.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-hard-constraints-confirmed",
                            "text": "Vehicle capacity and driver shift limits are treated as strict constraints.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-workload-fairness",
                            "text": "Workload balance is set to 50 to ensure equitable shift durations.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-partial-brief-patch-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can you switch to SwarmSA?", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-partial-brief-patch-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        assert body["panel_config"]["problem"]["algorithm"] == "SwarmSA"
        assert body["panel_config"]["problem"]["weights"]["deadline_penalty"] == 120.0
        assert body["panel_config"]["problem"]["weights"]["capacity_penalty"] == 1000.0
        assert body["panel_config"]["problem"]["weights"]["workload_balance"] == 50.0
        gathered_texts = [item["text"] for item in body["problem_brief"]["items"] if item["kind"] != "system"]
        assert "Vehicle capacity and driver shift limits are treated as strict constraints." in gathered_texts


def test_partial_problem_brief_patch_preserves_answered_open_question_state(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-partial-open-question-merge-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Added a new clarification request.",
            panel_patch=None,
            problem_brief_patch={
                "open_questions": [
                    "Should any vehicle assignments remain fixed?",
                ]
            },
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-partial-open-question-merge-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Preserve answered clarifications across additive updates.",
                    "items": [],
                    "open_questions": [
                        {
                            "id": "oq-overtime-cap",
                            "text": "What overtime cap should we enforce?",
                            "status": "answered",
                            "answer_text": "Cap overtime at 30 minutes per shift.",
                        }
                    ],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-partial-open-question-merge-secret"},
        )
        assert patch.status_code == 200
        patched = patch.json()["problem_brief"]
        assert patched["open_questions"] == []
        gathered_texts = [item["text"] for item in patched["items"] if item["kind"] == "gathered"]
        assert any(
            "overtime cap" in t.lower() and "30 minutes" in t.lower() for t in gathered_texts
        )

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Any follow-up questions?", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-partial-open-question-merge-secret"},
        )
        assert send.status_code == 200
        questions = send.json()["problem_brief"]["open_questions"]
        assert not any(q["text"] == "What overtime cap should we enforce?" for q in questions)
        assert any(q["text"] == "Should any vehicle assignments remain fixed?" for q in questions)
        gathered_after = [
            item["text"] for item in send.json()["problem_brief"]["items"] if item["kind"] == "gathered"
        ]
        assert any(
            "overtime cap" in t.lower() and "30 minutes" in t.lower() for t in gathered_after
        )


def test_panel_save_updates_problem_brief_and_round_trips_back_to_config(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-panel-brief-sync-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-panel-brief-sync-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        save_panel = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "weights": {"travel_time": 1.0, "workload_balance": 100.0},
                        "algorithm": "PSO",
                        "algorithm_params": {"c1": 1.8, "c2": 2.2, "w": 0.55},
                        "epochs": 33,
                        "pop_size": 21,
                        "shift_hard_penalty": 88.0,
                    }
                }
            },
            headers={"Authorization": "Bearer test-client-panel-brief-sync-secret"},
        )
        assert save_panel.status_code == 200
        body = save_panel.json()
        problem = body["panel_config"]["problem"]
        assert problem["algorithm"] == "PSO"
        assert problem["epochs"] == 33
        assert problem["pop_size"] == 21
        brief_texts = [item["text"] for item in body["problem_brief"]["items"] if item["kind"] != "system"]
        assert "Solver algorithm is PSO." in brief_texts
        assert "Workload balance weight is set to 100.0." in brief_texts
        assert "Search epochs are set to 33." in brief_texts
        assert "Population size is set to 21." in brief_texts
        assert "Algorithm parameter c1 is set to 1.8." in brief_texts

        save_brief = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={"problem_brief": body["problem_brief"]},
            headers={"Authorization": "Bearer test-client-panel-brief-sync-secret"},
        )
        assert save_brief.status_code == 200
        round_tripped = save_brief.json()["panel_config"]["problem"]
        assert round_tripped["algorithm"] == "PSO"
        assert round_tripped["epochs"] == 33
        assert round_tripped["pop_size"] == 21
        assert round_tripped["algorithm_params"] == {"c1": 1.8, "c2": 2.2, "w": 0.55}
        assert round_tripped["weights"]["workload_balance"] == 100.0
        assert round_tripped["shift_hard_penalty"] == 88.0


def test_chat_ignores_panel_patch_and_relies_on_brief_patch(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-chat-panel-brief-sync-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I updated the solver settings to PSO with stronger balance pressure.",
            panel_patch={
                "problem": {
                    "weights": {"travel_time": 1.0, "workload_balance": 75.0},
                    "algorithm": "PSO",
                    "algorithm_params": {"c1": 1.5, "c2": 2.5, "w": 0.6},
                    "epochs": 24,
                    "pop_size": 18,
                }
            },
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-chat-panel-brief-sync-secret"},
        )
        sid = create.json()["id"]

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please switch to PSO and increase workload balance.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-chat-panel-brief-sync-secret"},
        )
        assert send.status_code == 200
        body = send.json()
        assert body["problem_brief"] is None
        assert body["panel_config"] is None


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
        assert body["panel_config"]["problem"]["pop_size"] == 150


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


def test_non_cleanup_request_keeps_additive_merge_behavior(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-non-cleanup-additive-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I added one more fact.",
            problem_brief_patch={
                "items": [
                    {
                        "id": "fact-new",
                        "text": "New fact added without cleanup intent.",
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
            headers={"Authorization": "Bearer test-client-non-cleanup-additive-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Keep additive behavior in normal turns.",
                    "items": [
                        {
                            "id": "fact-existing",
                            "text": "Existing gathered fact should remain.",
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
            headers={"Authorization": "Bearer test-client-non-cleanup-additive-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Add one more fact about deadlines.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-non-cleanup-additive-secret"},
        )
        assert send.status_code == 200
        brief = send.json()["problem_brief"]
        non_system_ids = {item["id"] for item in brief["items"] if item["kind"] != "system"}
        assert "fact-existing" in non_system_ids
        assert "fact-new" in non_system_ids


def test_clear_definition_request_clears_editable_items_when_model_omits_patch(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-clear-definition-fallback-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="I've cleared the definition and reset everything.",
            problem_brief_patch=None,
            cleanup_mode=True,
            replace_editable_items=True,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-clear-definition-fallback-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Temporary definition to clear.",
                    "items": [
                        {
                            "id": "fact-old",
                            "text": "Old gathered fact to remove.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "assumption-old",
                            "text": "Old assumption to remove.",
                            "kind": "assumption",
                            "source": "agent",
                            "status": "active",
                            "editable": True,
                        },
                    ],
                    "open_questions": [{"id": "oq-1", "text": "Old question?"}],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-clear-definition-fallback-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can you clear every definition? I want to restart.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-clear-definition-fallback-secret"},
        )
        assert send.status_code == 200
        brief = send.json()["problem_brief"]
        assert brief is not None
        assert [item for item in brief["items"] if item["kind"] != "system"] == []
        assert brief["open_questions"] == []


def test_cleanup_replace_flag_without_items_clears_editable_rows(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-cleanup-replace-no-items-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Cleanup done.",
            problem_brief_patch={"goal_summary": "Cleaned up"},
            cleanup_mode=True,
            replace_editable_items=True,
            replace_open_questions=True,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-cleanup-replace-no-items-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Before cleanup.",
                    "items": [
                        {
                            "id": "fact-a",
                            "text": "Keep for now.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        }
                    ],
                    "open_questions": [{"id": "oq-a", "text": "Question A?"}],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-cleanup-replace-no-items-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please clean up and consolidate the definition.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-cleanup-replace-no-items-secret"},
        )
        assert send.status_code == 200
        brief = send.json()["problem_brief"]
        assert brief is not None
        assert [item for item in brief["items"] if item["kind"] != "system"] == []
        assert brief["open_questions"] == []
        assert brief["goal_summary"] == "Cleaned up"


def test_replace_open_questions_round_trips_answer_fields(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-replace-open-question-answer-secret")
    get_settings.cache_clear()

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message="Replaced open questions with the cleaned set.",
            panel_patch=None,
            problem_brief_patch={
                "open_questions": [
                    {
                        "id": "oq-new",
                        "text": "What target service level should we optimize for?",
                        "status": "answered",
                        "answer_text": "Target 95% on-time deliveries.",
                    }
                ]
            },
            replace_open_questions=True,
        ),
    )

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-replace-open-question-answer-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Start with an open question list to replace.",
                    "items": [],
                    "open_questions": [
                        {
                            "id": "oq-old",
                            "text": "Old question to replace?",
                            "status": "open",
                            "answer_text": None,
                        }
                    ],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-replace-open-question-answer-secret"},
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Please replace the clarification list.", "invoke_model": True},
            headers={"Authorization": "Bearer test-client-replace-open-question-answer-secret"},
        )
        assert send.status_code == 200
        brief = send.json()["problem_brief"]
        assert brief["open_questions"] == []
        gathered_texts = [item["text"] for item in brief["items"] if item["kind"] == "gathered"]
        assert any(
            "service level" in t.lower() and "95%" in t and "on-time" in t.lower() for t in gathered_texts
        )


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


def test_definition_sync_uses_brief_only_not_existing_panel(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-brief-only-sync-secret")
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    def fake_generate_config_from_brief(brief, current_panel, api_key, model_name):
        captured["current_panel"] = current_panel
        return {
            "problem": {
                "weights": {"deadline_penalty": 80.0},
                "algorithm": "GA",
            }
        }

    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")
    monkeypatch.setattr("app.services.llm.generate_config_from_brief", fake_generate_config_from_brief)

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-brief-only-sync-secret"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        save_panel = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "weights": {
                            "travel_time": 1.0,
                            "fuel_cost": 1.0,
                            "deadline_penalty": 60.0,
                            "capacity_penalty": 100.0,
                            "workload_balance": 15.0,
                        },
                        "algorithm": "PSO",
                    }
                }
            },
            headers={"Authorization": "Bearer test-client-brief-only-sync-secret"},
        )
        assert save_panel.status_code == 200

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Focus heavily on on-time delivery only.",
                    "items": [
                        {
                            "id": "fact-deadline",
                            "text": "Deadline penalty is set to 80.",
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
            headers={"Authorization": "Bearer test-client-brief-only-sync-secret"},
        )
        assert patch.status_code == 200
        assert captured["current_panel"] is None
        weights = patch.json()["panel_config"]["problem"]["weights"]
        assert set(weights) == {"deadline_penalty"}
        assert weights["deadline_penalty"] == 80.0


def test_definition_save_collapses_conflicting_config_linked_facts(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-definition-reconcile-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-definition-reconcile-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Keep the definition coherent.",
                    "items": [
                        {
                            "id": "fact-pop-size-100",
                            "text": "Population size is set to 100.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-pop-size-150",
                            "text": "Population size is set to 150.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-workload-balance-10",
                            "text": "Workload balance is set to 10.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-workload-balance-50",
                            "text": "Workload balance is set to 50.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-definition-reconcile-secret"},
        )
        assert patch.status_code == 200
        body = patch.json()
        brief_texts = [item["text"] for item in body["problem_brief"]["items"] if item["kind"] != "system"]
        assert "Population size is set to 150." in brief_texts
        assert "Population size is set to 100." not in brief_texts
        assert "Workload balance is set to 50." in brief_texts
        assert "Workload balance is set to 10." not in brief_texts
        assert body["panel_config"]["problem"]["pop_size"] == 150
        assert body["panel_config"]["problem"]["weights"]["workload_balance"] == 50.0


def test_sync_panel_endpoint_rebuilds_saved_config(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-sync-panel-secret")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-sync-panel-secret"},
        )
        sid = create.json()["id"]

        patch = client.patch(
            f"/sessions/{sid}/problem-brief",
            json={
                "problem_brief": {
                    "goal_summary": "Optimize delivery routes while respecting strict capacities.",
                    "items": [
                        {
                            "id": "fact-capacity",
                            "text": "Vehicle capacity is a strict constraint.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                        {
                            "id": "fact-algorithm-pso",
                            "text": "Use PSO as the search strategy.",
                            "kind": "gathered",
                            "source": "user",
                            "status": "confirmed",
                            "editable": True,
                        },
                    ],
                    "open_questions": [],
                    "solver_scope": "general_metaheuristic_translation",
                    "backend_template": "routing_time_windows",
                }
            },
            headers={"Authorization": "Bearer test-client-sync-panel-secret"},
        )
        assert patch.status_code == 200

        save_panel = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "weights": {"travel_time": 1.0},
                        "algorithm": "GA",
                        "epochs": 10,
                        "pop_size": 10,
                    }
                }
            },
            headers={"Authorization": "Bearer test-client-sync-panel-secret"},
        )
        assert save_panel.status_code == 200
        assert save_panel.json()["panel_config"]["problem"]["algorithm"] == "GA"
        brief_texts = [item["text"] for item in save_panel.json()["problem_brief"]["items"] if item["kind"] != "system"]
        assert "Solver algorithm is GA." in brief_texts

        sync = client.post(
            f"/sessions/{sid}/sync-panel",
            headers={"Authorization": "Bearer test-client-sync-panel-secret"},
        )
        assert sync.status_code == 200
        problem = sync.json()["panel_config"]["problem"]
        assert problem["algorithm"] == "GA"
        assert problem["weights"]["travel_time"] == 1.0


def test_participant_number_round_trip_and_researcher_edit(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-participant-number")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-participant-number")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={"participant_number": " 007 "},
            headers={"Authorization": "Bearer test-client-participant-number"},
        )
        assert create.status_code == 200
        created = create.json()
        assert created["participant_number"] == "007"
        sid = created["id"]

        patch = client.patch(
            f"/sessions/{sid}",
            json={"participant_number": "12"},
            headers={"Authorization": "Bearer test-researcher-participant-number"},
        )
        assert patch.status_code == 200
        assert patch.json()["participant_number"] == "12"

        clear = client.patch(
            f"/sessions/{sid}",
            json={"participant_number": None},
            headers={"Authorization": "Bearer test-researcher-participant-number"},
        )
        assert clear.status_code == 200
        assert clear.json()["participant_number"] is None


def test_post_snapshot_bookmark_creates_row(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-snapshot-bookmark")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        create = client.post(
            "/sessions",
            json={},
            headers={"Authorization": "Bearer test-client-snapshot-bookmark"},
        )
        assert create.status_code == 200
        sid = create.json()["id"]

        before = client.get(
            f"/sessions/{sid}/snapshots",
            headers={"Authorization": "Bearer test-client-snapshot-bookmark"},
        )
        assert before.status_code == 200
        n_before = len(before.json())

        post = client.post(
            f"/sessions/{sid}/snapshots",
            headers={"Authorization": "Bearer test-client-snapshot-bookmark"},
        )
        assert post.status_code == 201
        body = post.json()
        assert body["event_type"] == "bookmark"
        assert body["id"] > 0

        after = client.get(
            f"/sessions/{sid}/snapshots",
            headers={"Authorization": "Bearer test-client-snapshot-bookmark"},
        )
        assert after.status_code == 200
        assert len(after.json()) == n_before + 1
