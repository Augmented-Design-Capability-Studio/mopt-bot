from app.services.panel_merge import deep_merge


def test_deep_merge_nested_weights():
    base = {"problem": {"weights": {"w1": 1.0, "w2": 0.15}, "epochs": 80}}
    patch = {"problem": {"weights": {"w1": 1.5}}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"]["w1"] == 1.5
    assert out["problem"]["weights"]["w2"] == 0.15
    assert out["problem"]["epochs"] == 80


def test_deep_merge_parses_stringified_nested_json_objects():
    base = {"problem": {"epochs": 80}}
    patch = {
        "problem": {
            "weights": '{"travel_time": 1.0, "deadline_penalty": 50.0}',
            "soft_constraints": '["deadline_penalty", "capacity_penalty"]',
        }
    }
    out = deep_merge(base, patch)
    assert out["problem"]["weights"]["travel_time"] == 1.0
    assert out["problem"]["weights"]["deadline_penalty"] == 50.0
    assert out["problem"]["soft_constraints"] == [
        "deadline_penalty",
        "capacity_penalty",
    ]


def test_deep_merge_preserves_existing_weights_when_patch_sets_null():
    base = {"problem": {"weights": {"travel_time": 1.0}, "epochs": 80}}
    patch = {"problem": {"weights": None, "epochs": 500}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"] == {"travel_time": 1.0}
    assert out["problem"]["epochs"] == 500


def test_deep_merge_drops_invalid_weights_when_no_base_weights_exist():
    base = {"problem": {"epochs": 80}}
    patch = {"problem": {"weights": None, "epochs": 500}}
    out = deep_merge(base, patch)
    assert "weights" not in out["problem"]
    assert out["problem"]["epochs"] == 500


def test_deep_merge_preserves_existing_weights_when_patch_has_broken_json_fragment():
    base = {"problem": {"weights": {"travel_time": 1.0}, "epochs": 80}}
    patch = {"problem": {"weights": "{", "epochs": 500}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"] == {"travel_time": 1.0}
    assert out["problem"]["epochs"] == 500


def test_deep_merge_drops_broken_json_fragment_when_no_base_weights_exist():
    base = {"problem": {"epochs": 80, "weights": None}}
    patch = {"problem": {"weights": "{", "epochs": 500}}
    out = deep_merge(base, patch)
    assert "weights" not in out["problem"]
    assert out["problem"]["epochs"] == 500
