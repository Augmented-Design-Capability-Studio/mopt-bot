from app.services.panel_merge import deep_merge


def test_deep_merge_nested_weights():
    base = {"problem": {"weights": {"w1": 1.0, "w2": 0.15}, "epochs": 80}}
    patch = {"problem": {"weights": {"w1": 1.5}}}
    out = deep_merge(base, patch)
    assert out["problem"]["weights"]["w1"] == 1.5
    assert out["problem"]["weights"]["w2"] == 0.15
    assert out["problem"]["epochs"] == 80
