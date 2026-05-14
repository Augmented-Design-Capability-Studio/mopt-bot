"""Integration tests for the deterministic algorithm-commit safety net and
the pre-release gate probe.

These cover the GA-bug failure mode described in the user report: agent's
visible reply commits "I've set the search strategy to genetic search (GA)"
but the brief patch doesn't carry the matching assumption row, so the
panel-derive can't pick up `algorithm=GA` and the Run button stays greyed
out.

Two layers:

1. **Layer 1 (deterministic safety net, in BG derivation).** If the visible
   reply names an algorithm but the brief patch lacks the items[] row, the
   BG pipeline synthesizes the row before merge. This test exercises the
   end-to-end path through the API.
2. **Layer 2 (pre-release probe in router).** If the visible reply invites
   the participant to click **Run optimization** but the speculative gate
   check (after layer 1's algorithm injection) shows the run button would
   still be DISABLED, the router re-calls the consolidated chat turn once
   with an audit block injected. This test mocks the consolidated helper to
   observe the retry.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.schemas import ChatModelTurn, ConsolidatedChatTurn


_AUTH_HEADER = {"Authorization": "Bearer test-gate-aware-secret"}


def _create_agile_session(client: TestClient) -> str:
    create = client.post(
        "/sessions",
        json={"workflow_mode": "agile"},
        headers=_AUTH_HEADER,
    )
    assert create.status_code == 200
    return create.json()["id"]


def test_layer1_bg_safety_net_injects_algorithm_assumption(monkeypatch: pytest.MonkeyPatch):
    """GA-bug scenario, end-to-end: agile session with a goal-term weight
    already on the panel; visible reply commits to GA but the (mocked)
    chat-turn returns NO problem_brief_patch. The BG safety net must add
    the algorithm assumption row to the brief so panel-derive picks up
    `algorithm=GA` and the gate opens.

    Note: the consolidated helper is stubbed to None (conftest default),
    so the router falls through to the multi-call `generate_chat_turn`
    path. We mock that to produce the GA visible reply with an empty
    brief patch, which is exactly the failure mode the safety net targets.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    # Chat-turn commits to GA but emits no brief patch — exactly the
    # failure pattern reported by the user.
    monkeypatch.setattr(
        "app.services.llm.generate_chat_turn",
        lambda *args, **kwargs: ChatModelTurn(
            assistant_message=(
                "I've set the search strategy to genetic search (GA) as a starting point. "
                "Click Run optimization for a baseline."
            ),
            panel_patch=None,
            problem_brief_patch=None,
        ),
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)

        # Seed the session with a goal-term weight on the panel (mimicking
        # what the participant set in earlier turns). Without this, gate
        # would block on both goal_term AND algorithm — we want to isolate
        # the algorithm-injection path.
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "lateness_penalty": {
                                "weight": 10.0,
                                "type": "soft",
                                "rank": 1,
                            }
                        },
                        "goal_term_order": ["lateness_penalty"],
                        "algorithm": "",
                    }
                }
            },
            headers=_AUTH_HEADER,
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Maybe time window?", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200

        # The BG safety net runs in a daemon thread launched from the chat
        # handler. Poll until the algorithm assumption row lands or we hit
        # a generous timeout (CI variance on Windows).
        import time
        algo_rows: list[dict] = []
        last_items: list[dict] = []
        deadline = time.time() + 5.0
        while time.time() < deadline:
            session = client.get(f"/sessions/{sid}", headers=_AUTH_HEADER)
            assert session.status_code == 200
            last_items = (session.json().get("problem_brief") or {}).get("items") or []
            algo_rows = [
                item for item in last_items
                if (item.get("kind") == "assumption"
                    and "ga" in str(item.get("text") or "").lower())
            ]
            if algo_rows:
                break
            time.sleep(0.1)
        assert algo_rows, (
            "Expected the BG safety net to inject an assumption row "
            f"naming GA within 5s; last items={last_items!r}"
        )


def test_layer2_pre_release_probe_retries_when_gate_would_stay_closed(monkeypatch: pytest.MonkeyPatch):
    """Pre-release probe scenario: agile session with NO goal-term weight
    set anywhere; consolidated chat-turn returns is_run_invitation=True
    with no brief patch. Speculative gate stays closed (missing goal_term
    even after algorithm injection), so the router must re-call the
    consolidated helper once with an audit block.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        # First call: a run-invitation that would leave the gate closed.
        if len(call_log) == 1:
            return ConsolidatedChatTurn(
                assistant_message=(
                    "I'm starting from genetic search — click Run optimization for a baseline."
                ),
                cleanup_intent=False,
                clear_intent=False,
                is_change_intent=True,
                should_trigger_run=False,
                intent_type="none",
                confidence=0.0,
                is_run_invitation=True,
            )
        # Retry: agent softened the reply per the audit instructions.
        return ConsolidatedChatTurn(
            assistant_message=(
                "Before I can run, I still need to know what to prioritize "
                "(e.g. on-time delivery vs. travel time). Which matters more?"
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Can you start an optimization?", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200
        out = send.json()
        assistant_msgs = [
            m for m in (out.get("messages") or []) if m.get("role") == "assistant"
        ]
        assert assistant_msgs, f"no assistant message in response: {out!r}"
        # Async-verification path: the POST response carries the DRAFT with
        # `meta.verifying=true`. The retry rewrites the message in place via
        # the background pipeline, so we poll the single-message endpoint
        # until verifying clears (or the timeout trips).
        assert assistant_msgs[-1].get("meta", {}).get("verifying") is True, (
            f"expected draft to ship with verifying=true, got {assistant_msgs[-1]!r}"
        )
        msg_id = assistant_msgs[-1]["id"]
        final_msg: dict | None = None
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline:
            poll = client.get(
                f"/sessions/{sid}/messages/{msg_id}", headers=_AUTH_HEADER
            )
            assert poll.status_code == 200
            polled = poll.json()
            if not (polled.get("meta") or {}).get("verifying"):
                final_msg = polled
                break
            time.sleep(0.1)
        assert final_msg is not None, (
            f"verifying flag never cleared within 5s for message {msg_id}"
        )
        assert "still need to know" in (final_msg.get("content") or ""), (
            f"expected softened reply, got {final_msg!r}"
        )

    # Two calls total: original draft + one retry with the audit block.
    assert len(call_log) == 2, f"expected 2 calls, got {len(call_log)}: {call_log!r}"
    assert call_log[0]["commit_audit_note"] is None
    assert call_log[1]["commit_audit_note"] is not None
    # Audit block should name the gap explicitly so the agent has context.
    assert "DISABLED" in str(call_log[1]["commit_audit_note"])


def test_layer2_pre_release_probe_does_not_retry_when_gate_would_open(monkeypatch: pytest.MonkeyPatch):
    """Happy path: visible reply commits to GA AND the brief already carries
    a goal-term weight (panel-side). Speculative probe should find the gate
    would open after algorithm injection, so no retry fires.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        return ConsolidatedChatTurn(
            assistant_message=(
                "I've set the search strategy to genetic search (GA) as a starting point. "
                "Click Run optimization for a baseline."
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=True,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=True,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        # Seed a goal-term weight so layer-1 algorithm injection is
        # sufficient to open the gate speculatively.
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "lateness_penalty": {
                                "weight": 10.0,
                                "type": "soft",
                                "rank": 1,
                            }
                        },
                        "goal_term_order": ["lateness_penalty"],
                        "algorithm": "",
                    }
                }
            },
            headers=_AUTH_HEADER,
        )
        assert patch.status_code == 200

        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "Let's use GA", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200

    # Exactly one call: layer-1 injection covers the gap, no retry needed.
    assert len(call_log) == 1, (
        f"expected 1 call (no retry); got {len(call_log)}: {call_log!r}"
    )
    assert call_log[0]["commit_audit_note"] is None


def test_layer2_probe_retries_on_claims_brief_change_without_run_invite(
    monkeypatch: pytest.MonkeyPatch,
):
    """Compliance trigger: agent CLAIMS a brief change ("Added X") but does
    NOT invite a run. The previous probe gated only on is_run_invitation, so
    this slipped through and surfaced only as a post-derivation compliance
    warning. The expanded probe must fire when ``claims_brief_change`` is
    true and the speculative gate stays closed, retrying once with an
    audit block that names the gap.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        if len(call_log) == 1:
            # Claims a change, NOT inviting a run. Patch is empty (no goal_term,
            # no algorithm injected), so speculative gate stays closed.
            return ConsolidatedChatTurn(
                assistant_message=(
                    "Changes I made: Added a travel time efficiency objective "
                    "(weight 1.0, soft constraint) to minimize total transit "
                    "duration. They will populate once you hit Run optimization."
                ),
                cleanup_intent=False,
                clear_intent=False,
                is_change_intent=True,
                should_trigger_run=False,
                intent_type="none",
                confidence=0.0,
                is_run_invitation=False,
                claims_brief_change=True,
                asks_user_question=False,
            )
        # Retry: softer reply, doesn't claim a change it can't deliver.
        return ConsolidatedChatTurn(
            assistant_message=(
                "To minimize travel time I still need an algorithm choice and "
                "a confirmed goal weight. Which would you like to start with?"
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
            claims_brief_change=False,
            asks_user_question=True,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "yes, minimize travel time", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200
        out = send.json()
        assistant_msgs = [
            m for m in (out.get("messages") or []) if m.get("role") == "assistant"
        ]
        assert assistant_msgs, f"no assistant message in response: {out!r}"
        # Async-verification path: POST returns the draft with verifying=true;
        # the retry rewrites it via the background pipeline. Poll for the
        # final state via the single-message endpoint.
        assert assistant_msgs[-1].get("meta", {}).get("verifying") is True, (
            f"expected draft to ship with verifying=true, got {assistant_msgs[-1]!r}"
        )
        msg_id = assistant_msgs[-1]["id"]
        final_msg: dict | None = None
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline:
            poll = client.get(
                f"/sessions/{sid}/messages/{msg_id}", headers=_AUTH_HEADER
            )
            assert poll.status_code == 200
            polled = poll.json()
            if not (polled.get("meta") or {}).get("verifying"):
                final_msg = polled
                break
            time.sleep(0.1)
        assert final_msg is not None, (
            f"verifying flag never cleared within 5s for message {msg_id}"
        )
        assert "I still need an algorithm choice" in (final_msg.get("content") or ""), (
            f"expected softened retry reply, got {final_msg!r}"
        )
        # The retry produced a softened reply that doesn't supply the missing
        # goal_term or algorithm, so the post-merge gate stays closed and
        # ``verified_after_retry`` MUST NOT be set. The badge means "we
        # re-checked and the gate now opens" — softening alone doesn't qualify.
        assert not (final_msg.get("meta") or {}).get("verified_after_retry"), (
            "verified_after_retry should be unset when the post-retry gate "
            f"is still closed, got {final_msg!r}"
        )

    assert len(call_log) == 2, f"expected 2 calls, got {len(call_log)}: {call_log!r}"
    assert call_log[0]["commit_audit_note"] is None
    assert call_log[1]["commit_audit_note"] is not None
    # Audit lead for claim-only trigger must NOT say "invited the participant
    # to click Run" (that's the run-invite-only lead). It must name the
    # commitment gap explicitly.
    note = str(call_log[1]["commit_audit_note"])
    assert "claimed a brief change" in note
    assert "DISABLED" in note


def test_layer2_probe_does_not_retry_when_no_claim_and_no_invite(
    monkeypatch: pytest.MonkeyPatch,
):
    """Negative control: a plain informational reply (no run invite, no claim
    of a brief change) MUST NOT trigger the probe — even when the
    speculative gate is closed for unrelated reasons. The probe is meant to
    catch over-promising; it should stay quiet on pure-question turns.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        return ConsolidatedChatTurn(
            assistant_message="Sure — what would you like to prioritize?",
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
            claims_brief_change=False,
            asks_user_question=True,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        send = client.post(
            f"/sessions/{sid}/messages",
            json={"content": "hello", "invoke_model": True},
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200

    # Single call: no retry budget consumed for a pure question turn.
    assert len(call_log) == 1, (
        f"expected 1 call (no retry), got {len(call_log)}: {call_log!r}"
    )
    assert call_log[0]["commit_audit_note"] is None


def test_layer2_probe_retries_on_run_ack_claim_without_brief_delta(
    monkeypatch: pytest.MonkeyPatch,
):
    """Run-ack failure mode: agent's post-run analysis CLAIMS new goal-term
    additions ("I have added a lateness penalty…") but the synchronous
    brief-update produces no editable-state delta. Gate is already open
    (the run succeeded), so the gate-closed check alone misses it — the
    new ``claim_unsupported`` trigger must fire the retry so the agent
    either emits the structural patch or downgrades the claim.

    Mocks ``compute_brief_after_user_turn`` directly so we don't have to
    wire a real Gemini brief-update call. First call returns the
    unchanged base brief (no delta) — that's what the LLM does in the
    failure scenario the user reported. Retry returns a brief with the
    goal_term actually landed.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    from app.schemas import ProblemBriefUpdateTurn

    call_log: list[dict] = []

    def fake_consolidated(*args, **kwargs):
        call_log.append({"commit_audit_note": kwargs.get("commit_audit_note")})
        if len(call_log) == 1:
            # The over-promising run-ack reply.
            return ConsolidatedChatTurn(
                assistant_message=(
                    "The first run shows pressure on time-window compliance and "
                    "capacity. To improve feasibility, I have added a lateness "
                    "penalty (soft, weight 10) and a capacity penalty (soft, "
                    "weight 15) to push for better service quality."
                ),
                cleanup_intent=False,
                clear_intent=False,
                is_change_intent=True,
                should_trigger_run=False,
                intent_type="none",
                confidence=0.0,
                is_run_invitation=False,
                claims_brief_change=True,
                asks_user_question=False,
            )
        # Retry: softened, no unsupported claim.
        return ConsolidatedChatTurn(
            assistant_message=(
                "Time-window compliance and capacity look tight. If you'd like, "
                "I can add explicit penalties for those next — say the word and "
                "I'll wire them into the goal terms."
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=False,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
            claims_brief_change=False,
            asks_user_question=False,
        )

    # Mock brief-update so call 1 produces no editable-state delta (the bug),
    # call 2 (the retry) produces a real delta so the retry is acknowledged
    # as ``probe_retry_fired``.
    brief_call_log: list[str] = []

    def fake_compute_brief(*args, **kwargs):
        visible = kwargs.get("visible_assistant_message") or ""
        base = kwargs.get("base_problem_brief") or {}
        brief_call_log.append(visible[:40])
        if "have added a lateness" in visible:
            # Failure mode: brief-update returns the base brief unchanged.
            return (base, None, ProblemBriefUpdateTurn(problem_brief_patch=None))
        # Retry's softened reply produces no structural change either, but
        # that's OK because retry's claims_brief_change=False — no delta is
        # required to satisfy the post-retry verifier.
        return (base, None, ProblemBriefUpdateTurn(problem_brief_patch=None))

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.compute_brief_after_user_turn",
        fake_compute_brief,
    )
    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        lambda **kwargs: None,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        # Seed a goal-term + algorithm so the gate is already OPEN (matching
        # the post-run state in the user's report). That's what makes this
        # case distinct from the gate-closed scenario.
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "travel_time": {"weight": 1.0, "type": "soft", "rank": 1}
                        },
                        "goal_term_order": ["travel_time"],
                        "algorithm": "GA",
                    }
                }
            },
            headers=_AUTH_HEADER,
        )
        assert patch.status_code == 200
        # Auto-posted run-ack context. Matches ``_RUN_ACK_PATTERNS`` so the
        # router flags ``is_run_ack=True`` and the previously-excluded probe
        # path runs.
        send = client.post(
            f"/sessions/{sid}/messages",
            json={
                "content": "Run #1 just completed. Please interpret these results.",
                "invoke_model": True,
            },
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200
        # Async-verification path: the retry runs in a background thread, so
        # the second consolidated call may not have happened by the time the
        # POST returns. Poll until the call log has both entries (or timeout).
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline and len(call_log) < 2:
            time.sleep(0.1)

    # Two calls: original draft + one retry for the unsupported claim.
    assert len(call_log) == 2, (
        f"expected 2 calls (probe retry on run-ack), got {len(call_log)}: {call_log!r}"
    )
    assert call_log[0]["commit_audit_note"] is None
    audit = call_log[1]["commit_audit_note"]
    assert audit is not None
    # The new ``claim_unsupported`` audit lead must surface — gate is open so
    # we should NOT see the "DISABLED" framing here.
    assert "NO delta" in audit, audit
    assert "DISABLED" not in audit, audit


def test_run_ack_pipeline_runs_when_agent_claims_brief_change(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression for the run-ack persistence bug:

    Frontend posts the synthetic run-complete message with
    ``skip_hidden_brief_update=true``, AND the content matches the backend's
    interpret-only regex. Both gates feed into ``hard_skip_pipeline``, which
    used to drop the background derivation entirely — meaning a visible reply
    like *"I've added a capacity penalty…"* would never land structurally,
    even though the probe's synchronous brief-update produced a patch.

    The override is: when the consolidated turn flags
    ``claims_brief_change=True``, the agent's own commitment supersedes the
    interpret-only / skip hints — the pipeline runs and the precomputed
    patch is applied.
    """
    monkeypatch.setenv("MOPT_CLIENT_SECRET", "test-gate-aware-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.crypto_util.decrypt_secret", lambda _: "fake-key")

    def fake_consolidated(*args, **kwargs):
        return ConsolidatedChatTurn(
            assistant_message=(
                "I've added a capacity penalty (soft, weight 20) as an "
                "assumption to push for feasibility."
            ),
            cleanup_intent=False,
            clear_intent=False,
            is_change_intent=True,
            should_trigger_run=False,
            intent_type="none",
            confidence=0.0,
            is_run_invitation=False,
            claims_brief_change=True,
            asks_user_question=False,
        )

    monkeypatch.setattr(
        "app.services.llm.generate_consolidated_chat_turn", fake_consolidated
    )

    launch_log: list[dict] = []

    def fake_launch_bg(**kwargs):
        # Capture the launch — if the run-ack regression is back, this never
        # gets called because hard_skip_pipeline=True drops the pipeline.
        launch_log.append(
            {
                "user_text": kwargs.get("user_text"),
                "chat_turn_brief_patch": kwargs.get("chat_turn_brief_patch"),
            }
        )

    monkeypatch.setattr(
        "app.routers.sessions.derivation.launch_background_derivation",
        fake_launch_bg,
    )

    with TestClient(create_app()) as client:
        sid = _create_agile_session(client)
        # Seed gate-open so the probe doesn't retry on gate-closed grounds —
        # we're specifically isolating the persistence path.
        patch = client.patch(
            f"/sessions/{sid}/panel",
            json={
                "panel_config": {
                    "problem": {
                        "goal_terms": {
                            "travel_time": {"weight": 1.0, "type": "soft", "rank": 1}
                        },
                        "goal_term_order": ["travel_time"],
                        "algorithm": "GA",
                    }
                }
            },
            headers=_AUTH_HEADER,
        )
        assert patch.status_code == 200
        # Exact frontend payload for a run-ack turn: skip_hidden_brief_update
        # is set true AND the content matches _INTERPRET_ONLY regex. Both
        # gates would have skipped the pipeline before the fix.
        send = client.post(
            f"/sessions/{sid}/messages",
            json={
                "content": "Run #1 just completed - cost 123.45 (5 stops late). Please interpret these results.",
                "invoke_model": True,
                "skip_hidden_brief_update": True,
            },
            headers=_AUTH_HEADER,
        )
        assert send.status_code == 200
        # Async-verification path: the launch happens from the background
        # thread (after the probe completes). Poll until it lands, or 5s.
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline and not launch_log:
            time.sleep(0.1)

    # The override must let background derivation launch even though the
    # request matched BOTH skip conditions, because the consolidated turn
    # self-declared claims_brief_change=True.
    assert launch_log, (
        "expected background derivation to launch when the agent claimed a "
        "brief change on a run-ack turn; the run-ack regression is back."
    )
