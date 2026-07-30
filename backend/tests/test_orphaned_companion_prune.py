"""A companion child carrier is dropped when its parent goal term is removed.

Universal rule (session-73906e05): removing a "complex" goal term in either edit
surface must not leave its structured child dangling. The prune is driven by the
port's ``gate_conditional_companions`` map, so it works for any problem/term and
is a no-op where no companion is declared. Crucially it fires only when the
parent is ACTUALLY absent, so an edit-panel revert (which brings the parent back)
keeps the child.
"""

from app.routers.sessions.router import _prune_orphaned_companions

VRPTW_MAP = {"worker_preference": "driver_preferences", "shift_limit": "max_shift_hours"}


def test_drops_child_when_parent_absent():
    # The exact archive shape: shift_limit removed, max_shift_hours: null dangling.
    problem = {
        "goal_terms": {"travel_time": {"weight": 1.0}, "worker_preference": {"weight": 10}},
        "max_shift_hours": None,
        "driver_preferences": [{"vehicle_idx": 0}],
    }
    dropped = _prune_orphaned_companions(problem, VRPTW_MAP)
    assert dropped == ["max_shift_hours"]  # shift_limit gone -> its child dropped
    assert "max_shift_hours" not in problem
    # worker_preference is still active -> its child survives (revert-safe).
    assert problem["driver_preferences"] == [{"vehicle_idx": 0}]


def test_keeps_child_when_parent_present():
    problem = {
        "goal_terms": {"shift_limit": {"weight": 1.0}},
        "max_shift_hours": 6.5,
    }
    assert _prune_orphaned_companions(problem, VRPTW_MAP) == []
    assert problem["max_shift_hours"] == 6.5


def test_legacy_weights_count_as_active():
    problem = {"weights": {"worker_preference": 10}, "driver_preferences": [{"vehicle_idx": 1}]}
    assert _prune_orphaned_companions(problem, VRPTW_MAP) == []
    assert problem["driver_preferences"] == [{"vehicle_idx": 1}]


def test_no_companion_map_is_noop():
    problem = {"goal_terms": {}, "max_shift_hours": None}
    assert _prune_orphaned_companions(problem, {}) == []
    assert problem["max_shift_hours"] is None  # untouched — no declaration to act on
