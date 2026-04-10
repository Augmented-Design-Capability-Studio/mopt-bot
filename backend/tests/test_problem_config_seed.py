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
                    "text": "Use travel_time weight 1, workload_balance weight 5, capacity_violation weight 100, priority_deadline weight 50, and shift_hard_penalty penalty 1000.",
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
    assert panel["problem"]["shift_hard_penalty"] == 1000.0


def test_seed_ignores_numeric_goal_summary_for_weights():
    panel = derive_problem_panel_from_brief(
        {
            "goal_summary": "Use capacity penalty 500 and workload weight 25.",
            "items": [],
        }
    )
    assert panel is None
