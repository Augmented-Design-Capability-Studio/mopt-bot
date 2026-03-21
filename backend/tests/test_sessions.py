from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_create_session_returns_null_panel_config(monkeypatch):
    """New participant sessions must not ship default problem JSON."""
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-client-session-secret")
    get_settings.cache_clear()
    client = TestClient(create_app())
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
