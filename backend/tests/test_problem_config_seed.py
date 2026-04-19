from app.problem_config_seed import derive_problem_panel_from_brief


def test_seed_splits_sentences_and_ignores_negated_objectives():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "Optimize routes, but travel time is not important.",
            "items": [
                {
                    "id": "fact-workload",
                    "text": "Workload balance should be 12. Deadline compliance is the top priority.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                }
            ],
        }
    )

    assert panel is not None
    weights = panel["problem"]["weights"]
    assert "travel_time" not in weights
    assert weights["workload_balance"] == 12.0
    assert weights["deadline_penalty"] == 120.0


def test_seed_parses_search_strategy_line_from_panel_sync():
    """Brief items from the panel use 'max iterations 33' without 'set to …' phrasing."""
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "config-search-strategy",
                    "text": (
                        "Search strategy: PSO (max iterations 33, population size 21, "
                        "c1=1.8, c2=2.2, w=0.55)."
                    ),
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
                {
                    "id": "config-weight-travel_time",
                    "text": "Travel time weight is set to 1.0.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
                {
                    "id": "config-weight-workload_balance",
                    "text": "Workload balance weight is set to 100.0.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
                {
                    "id": "config-weight-shift_limit",
                    "text": "Shift limit weight is set to 88.0.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
            ],
        }
    )
    assert panel is not None
    problem = panel["problem"]
    assert problem["algorithm"] == "PSO"
    assert problem["epochs"] == 33
    assert problem["pop_size"] == 21
    assert problem["weights"]["travel_time"] == 1.0
    assert problem["weights"]["workload_balance"] == 100.0
    assert problem["weights"]["shift_limit"] == 88.0


def test_seed_accepts_broader_numeric_phrasings():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "fact-algorithm",
                    "text": "Use particle swarm optimization. Population size equals 60. Iterations should be 45.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
                {
                    "id": "fact-deadline",
                    "text": "Deadline penalty is 65.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
            ],
        }
    )

    assert panel is not None
    problem = panel["problem"]
    assert problem["algorithm"] == "PSO"
    assert problem["pop_size"] == 60
    assert problem["epochs"] == 45
    assert problem["weights"]["deadline_penalty"] == 65.0


def test_seed_parses_snake_case_alias_terms():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "fact-terms",
                    "text": "Use travel_time weight 1, workload_balance weight 5, capacity_violation weight 100, priority_deadline weight 50, and shift_limit penalty 1000.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                }
            ],
        }
    )
    assert panel is not None
    weights = panel["problem"]["weights"]
    assert weights["travel_time"] == 1.0
    assert weights["workload_balance"] == 5.0
    assert weights["capacity_penalty"] == 100.0
    assert weights["priority_penalty"] == 50.0
    assert panel["problem"]["weights"]["shift_limit"] == 1000.0


def test_seed_does_not_infer_waiting_time_from_on_time_and_priority_language():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "fact-timing",
                    "text": "We care about on-time delivery and priority orders.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                }
            ],
        }
    )

    assert panel is not None
    weights = panel["problem"]["weights"]
    assert weights["deadline_penalty"] == 75.0
    assert weights["priority_penalty"] == 100.0
    assert "waiting_time" not in weights
    assert "early_arrival_threshold_min" not in panel["problem"]


def test_seed_requires_explicit_early_arrival_language_for_waiting_time():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "fact-early-arrival",
                    "text": "Drivers cannot arrive more than 30 minutes early; that early arrival penalty should be 100.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                }
            ],
        }
    )

    assert panel is not None
    problem = panel["problem"]
    assert problem["weights"]["waiting_time"] == 100.0
    assert problem["early_arrival_threshold_min"] == 30.0


def test_seed_ignores_numeric_goal_summary_for_weights():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "Use capacity penalty 500 and workload weight 25.",
            "items": [],
        }
    )
    assert panel is None


def test_seed_operating_time_maps_to_travel_time_not_fuel():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "fact-time",
                    "text": "Primary goal is shorter operating time across the plan.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
            ],
        }
    )
    assert panel is not None
    w = panel["problem"]["weights"]
    assert "travel_time" in w
    assert "fuel_cost" not in w


def test_seed_explicit_fuel_phrase_maps_to_travel_time_not_fuel_cost():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "",
            "items": [
                {
                    "id": "fact-fuel",
                    "text": "We also care about fuel use alongside travel time.",
                    "kind": "gathered",
                    "source": "user",
                    "status": "confirmed",
                    "editable": True,
                },
            ],
        }
    )
    assert panel is not None
    w = panel["problem"]["weights"]
    assert "fuel_cost" not in w
    assert "travel_time" in w
