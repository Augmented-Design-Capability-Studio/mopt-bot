from app.services.chat_context_policy import resolve_context_profile


def test_context_profile_cold_without_problem_signals():
    profile = resolve_context_profile(
        user_text="hello",
        current_problem_brief={"goal_summary": "", "items": [], "open_questions": []},
        current_panel=None,
        recent_runs_summary=[],
    )
    assert profile.temperature == "cold"


def test_context_profile_generic_optimize_question_stays_cold_in_reset_state():
    profile = resolve_context_profile(
        user_text="how do you optimize?",
        current_problem_brief={"goal_summary": "", "items": [], "open_questions": []},
        current_panel=None,
        recent_runs_summary=[],
    )
    assert profile.temperature == "cold"


def test_context_profile_warm_when_brief_has_goals():
    profile = resolve_context_profile(
        user_text="Can you help optimize this?",
        current_problem_brief={"goal_summary": "Improve consistency", "items": [], "open_questions": []},
        current_panel=None,
        recent_runs_summary=[],
    )
    assert profile.temperature == "warm"


def test_context_profile_hot_with_saved_panel_or_runs():
    profile = resolve_context_profile(
        user_text="retune algorithm params",
        current_problem_brief={"goal_summary": "", "items": [], "open_questions": []},
        current_panel={"problem": {"algorithm": "GA"}},
        recent_runs_summary=[{"ok": True, "cost": 12.3}],
    )
    assert profile.temperature == "hot"
