from app.services.panel_merge import deep_merge


def test_deep_merge_nested_weights():
    base = {"problem": {"weights": {"w1": 1.0, "w2": 0.15}, "epochs": 80}}
    patch = {"problem": {"weights": {"w1": 1.5}}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"]["w1"] == 1.5
    assert "w2" not in out["problem"]["weights"]
    assert out["problem"]["epochs"] == 80


def test_deep_merge_parses_stringified_nested_json_objects():
    base = {"problem": {"epochs": 80}}
    patch = {
        "problem": {
            "weights": '{"term_a": 1.0, "term_b": 50.0}',
            "goal_terms": '{"term_a":{"weight":1.0,"type":"objective"},"term_b":{"weight":50.0,"type":"hard"}}',
        }
    }
    out = deep_merge(base, patch)
    assert out["problem"]["weights"]["term_a"] == 1.0
    assert out["problem"]["weights"]["term_b"] == 50.0
    assert out["problem"]["goal_terms"]["term_a"]["type"] == "objective"
    assert out["problem"]["goal_terms"]["term_b"]["type"] == "hard"


def test_deep_merge_preserves_existing_weights_when_patch_sets_null():
    base = {"problem": {"weights": {"term_a": 1.0}, "epochs": 80}}
    patch = {"problem": {"weights": None, "epochs": 500}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"] == {"term_a": 1.0}
    assert out["problem"]["epochs"] == 500


def test_deep_merge_drops_invalid_weights_when_no_base_weights_exist():
    base = {"problem": {"epochs": 80}}
    patch = {"problem": {"weights": None, "epochs": 500}}
    out = deep_merge(base, patch)
    assert "weights" not in out["problem"]
    assert out["problem"]["epochs"] == 500


def test_deep_merge_preserves_existing_weights_when_patch_has_broken_json_fragment():
    base = {"problem": {"weights": {"term_a": 1.0}, "epochs": 80}}
    patch = {"problem": {"weights": "{", "epochs": 500}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"] == {"term_a": 1.0}
    assert out["problem"]["epochs"] == 500


def test_deep_merge_drops_broken_json_fragment_when_no_base_weights_exist():
    base = {"problem": {"epochs": 80, "weights": None}}
    patch = {"problem": {"weights": "{", "epochs": 500}}
    out = deep_merge(base, patch)
    assert "weights" not in out["problem"]
    assert out["problem"]["epochs"] == 500


def test_deep_merge_replaces_algorithm_params_object():
    base = {"problem": {"algorithm": "GA", "algorithm_params": {"pc": 0.9, "pm": 0.05}}}
    patch = {"problem": {"algorithm": "PSO", "algorithm_params": {"c1": 2.0, "c2": 2.0, "w": 0.4}}}
    out = deep_merge(base, patch)
    assert out["problem"]["algorithm"] == "PSO"
    assert out["problem"]["algorithm_params"] == {"c1": 2.0, "c2": 2.0, "w": 0.4}
