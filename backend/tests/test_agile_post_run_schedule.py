"""Tests for the agile post-run OQ/assumption blocked-randomization lever."""

from app.services.agile_post_run_schedule import post_run_oq_directive


def _seq(session_id: str, n: int, runs: int) -> list[str | None]:
    return [
        post_run_oq_directive(
            session_id=session_id, run_number=r, every_n_runs=n, workflow_mode="agile"
        )
        for r in range(1, runs + 1)
    ]


def test_exactly_one_oq_per_block():
    """Blocked ratio: every complete block of N runs contains EXACTLY one OQ."""
    n = 5
    seq = _seq("sess-A", n, 30)  # 6 full blocks
    for b in range(6):
        block = seq[b * n : (b + 1) * n]
        assert block.count("open_question") == 1, (b, block)
        assert block.count("assumption") == n - 1, (b, block)


def test_oq_position_is_random_within_blocks_not_fixed():
    """The OQ must NOT always land on the same index in every block (that would
    confound OQ with run-position). Across several blocks the OQ position varies."""
    n = 5
    seq = _seq("sess-position", n, 50)  # 10 blocks
    positions = {
        next(i for i, d in enumerate(seq[b * n : (b + 1) * n]) if d == "open_question")
        for b in range(10)
    }
    assert len(positions) > 1, f"OQ pinned to a single position: {positions}"


def test_reproducible_for_same_inputs():
    """Same (session, N, run) always yields the same directive — auditable."""
    a = _seq("sess-repro", 4, 20)
    b = _seq("sess-repro", 4, 20)
    assert a == b


def test_different_sessions_can_differ():
    """Different participants get independently-seeded schedules."""
    a = _seq("participant-1", 5, 25)
    b = _seq("participant-2", 5, 25)
    assert a != b  # extremely unlikely to coincide across 5 blocks


def test_waterfall_and_off_yield_no_directive():
    assert post_run_oq_directive(
        session_id="s", run_number=3, every_n_runs=5, workflow_mode="waterfall"
    ) is None
    assert post_run_oq_directive(
        session_id="s", run_number=3, every_n_runs=None, workflow_mode="agile"
    ) is None


def test_never_is_all_assumptions_and_every_is_all_oqs():
    assert _seq("s", 0, 6) == ["assumption"] * 6
    assert _seq("s", 1, 6) == ["open_question"] * 6


def test_invalid_run_number_yields_none():
    assert post_run_oq_directive(
        session_id="s", run_number=0, every_n_runs=5, workflow_mode="agile"
    ) is None
