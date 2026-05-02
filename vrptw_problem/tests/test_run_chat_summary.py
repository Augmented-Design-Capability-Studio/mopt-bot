from app.problems.registry import get_study_port


def test_vrptw_run_summary_minimal_visible_message():
    port = get_study_port("vrptw")
    result = {
        "cost": 1.0,
        "violations": {"time_window_stop_count": 0, "time_window_minutes_over": 0.0},
        "metrics": {"total_travel_minutes": 120.5, "workload_variance": 2.1},
    }
    text = port.format_optimization_run_chat_summary(
        session_run_number=2,
        run_ok=True,
        cost=99.0,
        result=result,
        error_message=None,
    )
    assert "Run #2 finished" in text
    assert "panel" in text.lower()
    assert "Travel:" not in text
    assert "workload variance" not in text.lower()
    assert "violations" not in text.lower()


def test_vrptw_run_summary_failed():
    port = get_study_port("vrptw")
    text = port.format_optimization_run_chat_summary(
        session_run_number=1,
        run_ok=False,
        cost=None,
        result=None,
        error_message="timed out",
    )
    assert "Run #1 failed" in text
    assert "timed out" in text
