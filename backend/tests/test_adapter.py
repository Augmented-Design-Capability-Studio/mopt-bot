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


def test_parse_weights_generic_cost_key_not_mapped_to_fuel():
    """Vague 'cost' must not fuzzy-match to fuel_cost (user may only care about time)."""
    cfg = parse_problem_config({"weights": {"cost": 2.0, "travel_time": 1.0}})
    w = cfg["weights"]
    assert w.get("w2", 0) != 2.0
    assert not any("interpreted" in m.lower() and "fuel" in m.lower() for m in cfg["weight_warnings"])
    assert any("'cost'" in m and "ignored" in m.lower() for m in cfg["weight_warnings"])


def test_parse_driver_preferences_validates_vehicle_idx():
    with pytest.raises(ValueError, match="vehicle_idx"):
        parse_problem_config(
            {
                "driver_preferences": [{"vehicle_idx": 9, "condition": "zone_d", "penalty": 1}],
            }
        )


def test_parse_driver_preferences_normalizes_order_priority_synonyms():
    cfg = parse_problem_config(
        {
            "driver_preferences": [
                {
                    "vehicle_idx": 0,
                    "condition": "order_priority",
                    "penalty": 1,
                    "order_priority": "low",
                    "aggregation": "per_stop",
                },
                {
                    "vehicle_idx": 1,
                    "condition": "express_order",
                    "penalty": 1,
                    "order_priority": "VIP",
                    "aggregation": "per_stop",
                },
            ],
        }
    )
    assert cfg["driver_preferences"][0]["order_priority"] == "standard"
    assert cfg["driver_preferences"][1]["order_priority"] == "express"


def test_parse_driver_preferences_accepts_zone_letters():
    cfg = parse_problem_config(
        {
            "driver_preferences": [
                {"vehicle_idx": 0, "condition": "avoid_zone", "zone": "D", "penalty": 1.5},
            ]
        }
    )
    assert cfg["driver_preferences"][0]["zone"] == 4


def test_parse_driver_preferences_rejects_bad_shift_limit():
    with pytest.raises(ValueError, match="limit_minutes must be > 0"):
        parse_problem_config(
            {
                "driver_preferences": [
                    {"vehicle_idx": 0, "condition": "shift_over_limit", "limit_minutes": 0, "penalty": 1},
                ]
            }
        )


def test_parse_driver_preferences_normalizes_priority_case():
    cfg = parse_problem_config(
        {
            "driver_preferences": [
                {"vehicle_idx": 1, "condition": "order_priority", "order_priority": "Express", "penalty": 2},
            ]
        }
    )
    assert cfg["driver_preferences"][0]["order_priority"] == "express"


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


def test_parse_problem_config_filters_algorithm_params():
    cfg = parse_problem_config(
        {
            "algorithm": "GA",
            "algorithm_params": {"pc": 0.85, "w": 9, "pm": 0.05},
        }
    )
    assert cfg["algorithm_params"] == {"pc": 0.85, "pm": 0.05}
    assert any("w" in msg.lower() for msg in cfg["weight_warnings"])


def test_sanitize_panel_weights_strips_algorithm_params_foreign_keys():
    panel, warnings = sanitize_panel_weights(
        {
            "problem": {
                "algorithm": "PSO",
                "algorithm_params": {"pc": 0.9, "c1": 1.5, "c2": 2.0, "w": 0.4},
            },
        }
    )
    assert panel["problem"]["algorithm_params"] == {"c1": 1.5, "c2": 2.0, "w": 0.4}
    assert any("pc" in w.lower() for w in warnings)


def test_sanitize_panel_weights_removes_params_when_algorithm_invalid():
    panel, warnings = sanitize_panel_weights(
        {
            "problem": {
                "algorithm": "NOT_AN_ALGO",
                "algorithm_params": {"pc": 0.9},
            },
        }
    )
    assert "algorithm_params" not in panel["problem"]
    assert warnings
