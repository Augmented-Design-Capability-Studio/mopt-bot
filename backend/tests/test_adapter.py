import pytest

from app.adapter import parse_problem_config, run_evaluate_routes, sanitize_panel_weights


def test_parse_defaults():
    cfg = parse_problem_config({})
    assert cfg["algorithm"] == "GA"
    assert cfg["epochs"] == 500
    assert "w1" in cfg["weights"]
    assert cfg["early_stop"] is True
    assert cfg["early_stop_patience"] == 20
    assert cfg["early_stop_epsilon"] == 1e-4


def test_parse_early_stop_disabled():
    cfg = parse_problem_config({"early_stop": False})
    assert cfg["early_stop"] is False


def test_parse_early_stop_custom():
    cfg = parse_problem_config({"early_stop_patience": 40, "early_stop_epsilon": 0.5})
    assert cfg["early_stop_patience"] == 40
    assert cfg["early_stop_epsilon"] == 0.5


def test_parse_early_stop_patience_bounds():
    with pytest.raises(ValueError, match="early_stop_patience"):
        parse_problem_config({"early_stop_patience": 0})
    with pytest.raises(ValueError, match="early_stop_patience"):
        parse_problem_config({"early_stop_patience": 6000})


def test_parse_early_stop_epsilon_positive():
    with pytest.raises(ValueError, match="early_stop_epsilon"):
        parse_problem_config({"early_stop_epsilon": 0})


def test_parse_early_stop_must_be_boolean():
    with pytest.raises(ValueError, match="early_stop must be a boolean"):
        parse_problem_config({"early_stop": "yes"})


def test_parse_swarmsa_alias():
    cfg = parse_problem_config({"algorithm": "swarmsa"})
    assert cfg["algorithm"] == "SwarmSA"


def test_parse_invalid_algo():
    with pytest.raises(ValueError, match="Unknown algorithm"):
        parse_problem_config({"algorithm": "INVALID"})


def test_parse_driver_preferences_validates_vehicle_idx():
    with pytest.raises(ValueError, match="vehicle_idx"):
        parse_problem_config(
            {
                "driver_preferences": [{"vehicle_idx": 9, "condition": "zone_d", "penalty": 1}],
            }
        )


def test_parse_locked_assignments_validates_range():
    with pytest.raises(ValueError, match="task index"):
        parse_problem_config({"locked_assignments": {"99": 0}})


def test_evaluate_routes_roundtrip():
    routes = [
        list(range(0, 6)),
        list(range(6, 12)),
        list(range(12, 18)),
        list(range(18, 24)),
        list(range(24, 30)),
    ]
    cfg = parse_problem_config({"random_seed": 42})
    out = run_evaluate_routes(routes, cfg)
    assert "cost" in out
    assert out["algorithm"] == "evaluate"
    assert len(out["schedule"]["routes"]) == 5
    assert len(out["schedule"]["vehicle_summaries"]) == 5
    assert out["schedule"]["time_bounds"]["end_minutes"] >= out["schedule"]["time_bounds"]["start_minutes"]
    first_stop = out["schedule"]["stops"][0]
    assert "arrival_minutes" in first_stop
    assert "load_after_stop" in first_stop
    assert "capacity_limit" in first_stop
    assert "time_window_minutes_over" in first_stop


def test_sanitize_panel_weights_drops_malformed_weights():
    panel, warnings = sanitize_panel_weights({"problem": {"weights": "{", "epochs": 500}})
    assert "weights" not in panel["problem"]
    assert warnings == ["Ignored malformed `problem.weights`; expected an object."]
