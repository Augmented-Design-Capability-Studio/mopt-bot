import pytest

from app.adapter import parse_problem_config, run_evaluate_routes, sanitize_panel_weights


def test_parse_defaults():
    cfg = parse_problem_config({})
    assert cfg["algorithm"] == "GA"
    assert cfg["epochs"] == 500
    assert "w1" in cfg["weights"]


def test_parse_swarmsa_alias():
    cfg = parse_problem_config({"algorithm": "swarmsa"})
    assert cfg["algorithm"] == "SwarmSA"


def test_parse_invalid_algo():
    with pytest.raises(ValueError, match="Unknown algorithm"):
        parse_problem_config({"algorithm": "INVALID"})


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
