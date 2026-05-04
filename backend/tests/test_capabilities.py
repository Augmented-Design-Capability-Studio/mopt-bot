from app.services.capabilities import build_capabilities_block


def test_capabilities_block_uses_neutral_language_and_sections():
    block = build_capabilities_block(test_problem_id="vrptw", mention_mealpy=False, temperature="warm")
    assert "Capabilities" in block
    assert "Solver families available" in block
    assert "Goal terms you can adjust" in block
    assert "Visualizations I've set up for this task" in block


def test_capabilities_block_mentions_mealpy_when_requested():
    block = build_capabilities_block(test_problem_id="knapsack", mention_mealpy=True, temperature="warm")
    assert "MEALpy" in block


def test_capabilities_block_cold_is_domain_agnostic():
    block = build_capabilities_block(test_problem_id="vrptw", mention_mealpy=False, temperature="cold")
    assert "Goal terms you can adjust" not in block
    assert "Visualizations I've set up for this task" not in block
