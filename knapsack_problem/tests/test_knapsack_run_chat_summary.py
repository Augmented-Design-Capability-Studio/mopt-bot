from app.problems.registry import get_study_port


def test_knapsack_run_summary_minimal_visible_message():
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
    assert "Run #1 finished" in text
    assert "panel" in text.lower()
    assert "Travel" not in text
    assert "packed value" not in text.lower()
    assert "items selected" not in text.lower()
