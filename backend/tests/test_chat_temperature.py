import pytest

from app.problem_brief import default_problem_brief
from app.services import llm


def test_visible_instruction_uses_model_temperature_when_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "classify_chat_temperature", lambda **_: "warm")
    system = llm._build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=default_problem_brief("vrptw"),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
    )
    assert "Conversation temperature: WARM" in system
    assert "Goal terms you can adjust:" in system


def test_visible_instruction_falls_back_when_model_temperature_fails(monkeypatch: pytest.MonkeyPatch):
    def _boom(**_kwargs):
        raise RuntimeError("classifier failed")

    monkeypatch.setattr(llm, "classify_chat_temperature", _boom)
    system = llm._build_visible_chat_system_instruction(
        user_text="how do you optimize?",
        current_problem_brief=default_problem_brief("vrptw"),
        workflow_mode="waterfall",
        test_problem_id="vrptw",
        api_key="fake-key",
        model_name="fake-model",
    )
    assert "Conversation temperature: COLD" in system
    assert "Goal terms you can adjust:" not in system
