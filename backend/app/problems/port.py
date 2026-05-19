from __future__ import annotations

from typing import Any, Protocol

from app.problems.types import TestProblemMeta, WeightDefinition


class StudyProblemPort(Protocol):
    """Backend integration surface for one metaheuristic benchmark."""

    id: str
    label: str

    def meta(self) -> TestProblemMeta: ...

    def sanitize_panel_config(self, panel_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Deep-copy safe sanitize of panel_config (typically problem.weights + algorithm_params)."""

    def parse_problem_config(self, raw: dict[str, Any]) -> dict[str, Any]: ...

    def solve_request_to_result(
        self,
        body: dict[str, Any],
        timeout_sec: float,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        """Same contract as historical solve_request_to_result (optimize / evaluate)."""

    def format_optimization_run_chat_summary(
        self,
        *,
        session_run_number: int,
        run_ok: bool,
        cost: float | None,
        result: dict[str, Any] | None,
        error_message: str | None,
    ) -> str:
        """Participant-visible assistant line after an optimization run (chat kind ``run``)."""

    def derive_problem_panel_from_brief(self, problem_brief: dict[str, Any]) -> dict[str, Any] | None: ...

    def visualization_capabilities(self) -> list[str]:
        """Participant-facing visual summaries shown after runs."""

    def weight_item_labels(self) -> dict[str, str]:
        """Human labels for problem_brief / panel sync (goal term keys)."""

    def goal_term_rationales(self) -> dict[str, str]:
        """Short rationale phrases per goal-term key, used by the
        synthesizer that renders ``config-weight-<key>`` brief rows.

        Each entry maps a weight key to a short clause like
        ``"to minimize total driving minutes"`` or ``"to discourage
        overloading vehicles"``. The rationale is appended to the
        synthesized text so participants see WHY the term exists, not
        just its name + type + weight. Keys without a rationale fall
        back to the bare "X is a <role> term (weight N)." format.

        Default returns ``{}``. Ports populate per-key.
        """
        return {}

    def weight_display_keys(self) -> list[str]:
        """Ordered weight keys used for the agile-mode gate check and config-panel display order.

        Keys that appear in the saved panel weights and in this list count toward the 'at least one
        goal term' requirement for agile optimization readiness.  The list should exclude purely
        parametric keys (e.g. VRPTW ``waiting_time`` which is threshold-driven) that should not
        independently satisfy the gate.  If the list is empty the gate falls back to any-weight
        logic (same as demo mode).
        """

    def gate_conditional_companions(self) -> dict[str, str]:
        """Map of goal-term key → companion panel field name.

        Each entry declares that the goal term carries a structured
        companion (a top-level panel field — list, scalar, or whatever the
        problem needs) whose presence is what makes the goal term
        meaningful. The unified gate uses the map to decide which keys
        contribute toward "at least one goal term present": a companion-
        having key contributes iff its companion is present (per
        ``companion_present`` below); its weight alone does **not** open
        the gate. A non-companion key contributes iff its weight is set,
        unchanged.

        Default: ``{}`` (no coupled companions). VRPTW returns both
        ``worker_preference`` (companion ``driver_preferences``, list)
        and ``shift_limit`` (companion ``max_shift_hours``, scalar). The
        gate handles arbitrary ``N`` without further changes.
        """
        return {}

    def companion_present(self, goal_term_key: str, value: Any) -> bool:
        """Return True iff ``value`` (read from the panel's companion field
        for ``goal_term_key``) counts as "defined" for the unified gate.

        Default treats list-typed companions as present-iff-non-empty and
        everything else as ``bool(value)``. Ports override per-key when
        the "is defined" predicate needs domain knowledge (e.g. VRPTW's
        ``shift_limit`` companion ``max_shift_hours`` requires ``> 0`` —
        zero is not a meaningful shift cap).
        """
        if isinstance(value, list):
            return len(value) > 0
        return bool(value)

    def study_prompt_appendix(self) -> str | None:
        """Extra structured-prompt text for the study chat model (problem-specific)."""

    def config_derive_system_prompt(self) -> str:
        """System instructions for LLM structured derivation of ``problem`` from the brief."""

    def panel_patch_response_json_schema(self) -> dict[str, Any]:
        """Gemini ``response_json_schema`` for a ``{ "problem": ... }`` object."""

    def locked_companion_fields(self) -> dict[str, str]:
        """Map of weight key → companion field preserved when that key is locked.

        When a weight key is in ``locked_goal_terms``, the corresponding companion
        field (if any) should also be copied from the current config into the derived
        config so the lock is effective end-to-end.

        Return an empty dict for problems without weight-companion coupling.
        Example: VRPTW returns ``{"worker_preference": "driver_preferences"}``.
        """

    def prose_id_prefixes_for_goal_term(self, goal_term_key: str) -> tuple[str, ...]:
        """Brief item-id prefixes that must be deduped when the same goal term
        is being patched via the structured `goal_terms` carrier.

        Default returns ``()`` — no prose ids are coupled to any goal term.
        A port can opt in by returning prefixes such as
        ``("config-driver-pref-",)`` when it expects the same data to live as
        prose items elsewhere; the brief-patch merge will then drop incoming
        items whose ``id`` starts with any of those prefixes when a structured
        ``goal_terms[goal_term_key]`` change arrives in the same patch.

        This is id-only filtering — it never inspects item text. The intent is
        to keep the mechanism in place without leaning on prose parsing.
        """
        return ()

    def goal_term_properties_schema(self) -> dict[str, Any] | None:
        """Per-problem JSON schema for `goal_terms[key].properties`.

        Returned schema is slotted into the shared `goal_terms_schema(...)`
        factory at brief-patch / panel-patch construction time so problem-
        specific child fields (e.g. VRPTW's `driver_preferences`,
        `max_shift_hours`) are typed for Gemini structured output without
        polluting `app.problems.schema_shared`.

        Return ``None`` (default) for problems with no typed child fields —
        callers fall back to a permissive open-object schema.
        """
        return None

    def normalize_goal_term_property(
        self, prop_key: str, prop_val: Any
    ) -> tuple[bool, Any] | None:
        """Port hook for validating one ``goal_terms[<any>].properties[<prop_key>]`` value.

        The main backend iterates registered ports for each property key it
        encounters during brief normalization. Contract:

        - Return ``None`` when this port doesn't own the property key —
          caller will try other ports, then fall back to generic pass-
          through (deepcopy the value).
        - Return ``(True, normalized_value)`` to keep the key with the
          normalized value.
        - Return ``(False, None)`` to drop the key (validation failed).

        Default returns ``None``. VRPTW overrides for ``driver_preferences``
        and ``max_shift_hours``; future ports can opt in for their own
        structured property fields without coordinating with the backend.
        """
        return None

    def problem_brief_item_slot(self, item: dict[str, Any]) -> str | None:
        """Problem-specific slot key for a brief item, or None to defer to the
        neutral slot detector.

        Slots are how the brief-merge pipeline collapses duplicate rows that
        represent the same setting (e.g. two prose rows both describing the
        capacity weight should reconcile to one). The main backend handles
        neutral slots — generic ``config-weight-<key>``, search strategy,
        algorithm, epochs, pop_size, only_active_terms,
        ``config-algorithm-param-*``. Ports return slot keys for their own
        item-id prefixes (e.g. VRPTW maps ``config-shift-hard-penalty`` to
        ``weight:shift_limit`` and ``config-driver-pref-*`` rows to
        ``driver_pref:<suffix>``).

        Default returns None. Ports override only for their own prefixes.
        """
        return None

    def brief_item_ids_to_strip_on_goal_term_removal(
        self,
        removed_keys: set[str],
        prior_goal_terms: dict[str, Any],
        brief_items: list[dict[str, Any]],
    ) -> set[str]:
        """Brief-item ids that should be dropped when these goal-term keys are
        removed from the panel.

        Without this cascade, a removed goal term's supporting prose (and the
        evidence cites the LLM made) lingers in ``brief.items[]``. On the next
        chat turn the LLM re-derives the term from that prose and the
        self-anchor check passes, so the removal silently reverts.

        Default strategy: strip any items whose ids appear in
        ``prior_goal_terms[key].evidence_item_ids`` — these are the rows the
        LLM explicitly cited as justifying the term, so they were added in
        service of it. Ports override to extend with their own prefix-based
        auto-rows (e.g. VRPTW also strips ``config-driver-pref-*`` rows when
        ``worker_preference`` is removed).
        """
        ids: set[str] = set()
        for key in removed_keys:
            entry = prior_goal_terms.get(key) if isinstance(prior_goal_terms, dict) else None
            if not isinstance(entry, dict):
                continue
            evidence = entry.get("evidence_item_ids")
            if isinstance(evidence, list):
                for eid in evidence:
                    if isinstance(eid, str) and eid:
                        ids.add(eid)
        return ids

    def format_run_context_violation_details(
        self, violations: dict[str, Any]
    ) -> list[str]:
        """Translate the run-result ``violations`` dict into short detail strings
        appended to a run-context summary line.

        Used by the brief-update pipeline's rolling run summary. The neutral
        backend already includes run number, status, cost, and algorithm —
        each port adds problem-specific violation phrasing here. VRPTW
        emits time-window / capacity counts; knapsack returns nothing
        (capacity overflow already shows up via its weight).
        """
        return []

    def extra_managed_problem_fields(self) -> tuple[str, ...]:
        """Problem-specific top-level panel fields that participate in
        derive-from-brief management alongside the neutral set
        (goal_terms, weights, constraint_types, only_active_terms,
        algorithm, algorithm_params, epochs, pop_size, early_stop*,
        use_greedy_init).

        Used by ``sync.py``'s managed-fields list. Default is empty.
        VRPTW returns its top-level fields like ``driver_preferences``,
        ``max_shift_hours``, ``locked_assignments``.
        """
        return ()

    def goal_term_property_field_mirrors(self) -> dict[str, str]:
        """Mapping of `goal_term_key → top_level_panel_field` for properties
        that are mirrored between `goal_terms[key].properties[<top_field>]`
        and the panel's top-level `<top_field>` (e.g. VRPTW mirrors
        `goal_terms.worker_preference.properties.driver_preferences` ↔
        panel `driver_preferences`).

        Used by the panel-derive merge: when the LLM derived a fresh
        top-level `<top_field>` value, the stale nested copy under
        `properties` must be dropped before the goal-terms overlay would
        otherwise re-project the old value back. Default is empty (no
        mirroring); ports opt in by listing their pairs.
        """
        return {}

    def is_goal_term_self_anchored(self, key: str, entry: dict[str, Any]) -> bool:
        """Return True iff this goal-term entry's own `properties` self-justify it.

        Used by the brief-anchor check to skip evidence requirements for terms
        whose structured rule list **is** the justification. Example: VRPTW's
        `worker_preference` entry with `properties.driver_preferences=[…]`
        carries every user-stated preference rule directly — there is no
        separate prose row to cite, so the term is implicitly anchored.

        Default returns False. Ports override to whitelist their own
        property-anchor pairs. Keep the check shallow (key + presence/non-
        emptiness of a known property field); semantic similarity belongs in
        the embedding fallback inside the anchoring service.
        """
        return False

    def auto_anchored_goal_term_keys(self) -> frozenset[str]:
        """Goal-term keys that bypass the brief-anchor check.

        The anchor check (`backend.app.services.goal_term_anchoring`) is
        intended to catch *semantic misuse* of valid keys — e.g. an LLM
        introducing VRPTW's `worker_preference` when no brief item mentions
        drivers. For problems whose closed key set is small and tightly
        scoped enough that misuse is implausible (every key is intrinsic to
        the problem, not an optional add-on), the anchor check is friction
        without a real signal. Such ports can return their full
        `weight_display_keys()` here to opt out.

        Default is empty: the anchor check applies. Knapsack overrides this
        to return all three of its keys; VRPTW keeps the default so its
        worker/shift-style add-ons stay gated.
        """
        return frozenset()

    def synthesize_brief_items_from_goal_terms(
        self, goal_terms: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Synthesize participant-visible prose `gathered` items from the
        structured `goal_terms` map.

        VRPTW uses this to render one ``config-driver-pref-*`` item per
        driver-preference rule (so the Definition tab shows "Alice avoids
        Zone D…" alongside the structured rule the solver consumes). Each
        returned item must use a stable id under the ``config-`` prefix so
        the brief-merge slot reconciler can dedupe/refresh on every sync.

        Default returns ``[]`` — problems with no structured child fields
        contribute no extra prose rows.
        """
        return []

    def verify_brief_companion(
        self,
        brief: dict[str, Any],
        *,
        visible_reply: str | None = None,
    ) -> list[dict[str, Any]]:
        """Port-specific structural verification for the merged brief.

        Returns a list of issue dicts shaped like
        ``{"category": "port_companion", "severity": "error"|"warn",
        "subject": str, "message": str}``. Empty list means the brief
        passes port-level invariants.

        Verification (S2) calls this AFTER the deterministic
        cross-port checks (claim/delta consistency, anchoring, algorithm
        carrier, workflow invariants) so port hooks see the already-merged
        brief and only flag domain-specific concerns. Default returns
        ``[]`` — VRPTW overrides to flag prose driver-pref rows that lack
        a structured rule object (and vice versa), and similar cases.
        """
        return []

    def mediocre_participant_starter_config(self) -> dict:
        """Return a deliberately sparse panel config for new study sessions.

        Should leave obvious room for improvement so participants can explore
        meaningful changes through chat.  Returned dict is a deep-copy (safe to mutate).
        """

    def problem_brief_template_fields(self) -> dict[str, str]:
        """solver_scope, backend_template, etc. for new sessions."""

    def goal_term_extraction_schema(self) -> dict[str, Any] | None:
        """Gemini ``response_json_schema`` for the canonical goal-term
        extraction LLM call (see ``app.services.goal_term_extraction``).

        Returned schema must describe a top-level object with a ``concepts``
        map whose keys are the port's canonical weight keys; each entry is
        ``{"named": bool, "rationale_phrase": str}``. Only keys with
        ``named=true`` get seeded into ``brief.goal_terms`` from the extractor.

        Returning ``None`` (default) skips extraction entirely — the
        cold-start seed step is a no-op for that port.
        """
        return None

    def seed_goal_term_defaults(self, key: str) -> dict[str, Any] | None:
        """Given a canonical goal-term key the extractor identified as
        ``named``, return the seed entry written into ``brief.goal_terms[key]``.

        The shape must satisfy the brief-merge contract: at minimum
        ``weight`` (numeric), ``type`` (one of objective/soft/hard/custom),
        and ``rank`` (positive int). The extractor service tacks on
        ``ambiguity_note.chosen_rationale`` from the LLM's response.

        Return ``None`` (default) when the key is unknown to the port — the
        extractor service treats that as "skip this concept".
        """
        return None


def all_synthesized_id_prefixes(port: Any) -> frozenset[str]:
    """Aggregate of every id-prefix the given port's synthesizer owns.

    The brief-patch JSON schema rejects LLM-emitted ``items[]`` whose ``id``
    starts with any of these prefixes, so the synthesizer's id namespace is
    reserved — preventing the LLM from authoring rows that would collide with
    auto-generated ones (e.g. VRPTW's ``config-driver-pref-*``).

    Aggregates from ``port.prose_id_prefixes_for_goal_term`` over
    ``port.weight_display_keys``. Free function (rather than a port method)
    because ``StudyProblemPort`` is a structural Protocol and per-port classes
    don't inherit defaults.
    """
    out: set[str] = set()
    try:
        keys = port.weight_display_keys()
    except Exception:  # pragma: no cover — defensive
        return frozenset()
    for key in keys:
        if not isinstance(key, str):
            continue
        try:
            prefixes = port.prose_id_prefixes_for_goal_term(key)
        except Exception:  # pragma: no cover — defensive
            continue
        for prefix in prefixes:
            if isinstance(prefix, str) and prefix:
                out.add(prefix)
    return frozenset(out)
