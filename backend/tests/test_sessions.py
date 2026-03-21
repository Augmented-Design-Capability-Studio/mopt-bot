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
        sid = data["id"]
        r2 = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": "Bearer test-client-session-secret"},
        )
        assert r2.status_code == 200
        assert r2.json().get("panel_config") is None


def test_steer_messages_hidden_and_forwarded_to_next_model_turn(monkeypatch):
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-steer-secret")
    monkeypatch.setenv("MOPT_RESEARCHER_SECRET", "test-researcher-steer-secret")
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    def fake_generate_chat_turn(*args, **kwargs):
        captured["researcher_steers"] = kwargs.get("researcher_steers")
        return ChatModelTurn(
            assistant_message="I can shift strategy on the next iteration while keeping the same thread.",
            panel_patch=None,
        )

    monkeypatch.setattr("app.routers.sessions.decrypt_secret", lambda _: "fake-key")
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

        visible_msgs = client.get(
            f"/sessions/{sid}/messages?after_id=0",
            headers={"Authorization": "Bearer test-client-steer-secret"},
        )
        assert visible_msgs.status_code == 200
        roles = [m["role"] for m in visible_msgs.json()]
        assert "researcher" not in roles
