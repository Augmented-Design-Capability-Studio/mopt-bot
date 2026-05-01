from app import problem_config_seed


def test_derive_problem_panel_from_brief_delegates_to_selected_port(monkeypatch):
    captured = {}

    class _FakePort:
        def derive_problem_panel_from_brief(self, brief):
            captured["brief"] = brief
            return {"problem": {"weights": {"x": 1}}}

    monkeypatch.setattr(problem_config_seed, "get_study_port", lambda problem_id=None: _FakePort(), raising=False)
    monkeypatch.setattr("app.problems.registry.get_study_port", lambda problem_id=None: _FakePort())

    brief = {"goal_summary": "anything", "items": []}
    out = problem_config_seed.derive_problem_panel_from_brief(brief, test_problem_id="custom")

    assert out == {"problem": {"weights": {"x": 1}}}
    assert captured["brief"] == brief


def test_derive_problem_panel_from_brief_uses_default_port_when_problem_id_omitted(monkeypatch):
    called = {"problem_id": None}

    class _FakePort:
        def derive_problem_panel_from_brief(self, brief):
            return {"problem": {"weights": {"x": len(brief.get("items", []))}}}

    def _fake_get(problem_id=None):
        called["problem_id"] = problem_id
        return _FakePort()

    monkeypatch.setattr("app.problems.registry.get_study_port", _fake_get)

    out = problem_config_seed.derive_problem_panel_from_brief({"items": [{}]}, test_problem_id=None)
    assert called["problem_id"] is None
    assert out == {"problem": {"weights": {"x": 1}}}
