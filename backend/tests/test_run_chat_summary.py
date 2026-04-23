"""Per-benchmark run completion lines for participant chat."""

from app.problems.registry import get_study_port


def test_knapsack_run_summary_avoids_vrptw_vocabulary():
    port = get_study_port("knapsack")
    result = {
        "cost": 12.3,
        "violations": {"capacity_units_over": 0},
        "metrics": {
            "workload_variance": 42.0,
            "driver_preference_units": 3,
            "knapsack_overflow": 0.0,
            "knapsack_feasible": True,
        },
        "visualization": {
            "payload": {
                "total_value": 100.0,
                "total_weight": 42.0,
                "capacity": 50.0,
                "feasible": True,
            }
        },
    }
    text = port.format_optimization_run_chat_summary(
        session_run_number=1,
        run_ok=True,
        cost=12.3,
        result=result,
        error_message=None,
    )
    assert "Travel" not in text
    assert "workload variance" not in text.lower()
    assert "packed value" in text.lower()
    assert "items selected" in text.lower()


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
