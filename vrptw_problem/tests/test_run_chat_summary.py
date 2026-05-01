from app.problems.registry import get_study_port


def test_vrptw_run_summary_keeps_routing_metrics():
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
    assert "Travel:" in text
    assert "workload variance" in text.lower()
