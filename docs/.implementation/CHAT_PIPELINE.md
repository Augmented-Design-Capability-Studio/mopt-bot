# Chat pipeline

> Canonical doc for the agentic chat pipeline. Pipeline shape is identical
> across agile/waterfall/demo — workflow differences live ONLY in
> ``_workflow_prompt(mode)``, ``_run_ack_prompt(mode)``, schema-enum
> constraints (``assumption_actions`` agile/demo only), and S2/S3
> invariants.

## Stages

| Stage | Job | LLM? | Failure (1st) | Failure (2nd) |
|---|---|---|---|---|
| S1 Main turn | visible reply + intents + brief patch (incl. OQ + assumption maintenance) | yes (`generate_main_turn`) | retry once with raw error | pause + 3-button row |
| S2 Verify brief | deterministic check (`pipeline_verification.verify_brief_consistency`); LLM-fix only if issues | mostly deterministic | retry S1 with issues feedback | pause |
| S3 Apply patch | `derivation.apply_brief_patch_with_cleanup` — merge, port prose-synth, anchor filter, monitors | no | n/a | n/a |
| S4 Derive config | `generate_config_from_brief` | yes | retry once | pause |
| S5 Verify config | `pipeline_verification.verify_panel_consistency` — brief↔panel mapping + structured carriers + algorithm | mostly deterministic | retry S4 with feedback | pause |
| S6 Persist | commit row | no | n/a | n/a |

Failure floor: never auto-revert, never silently commit. Show issues, surface 3 buttons (Retry / Revert / Keep chatting), append inline assistant follow-up that spells out the issue in plain English.

## Trigger flavors

The same `chat_pipeline_runner.run_chat_pipeline` is used for every trigger; the
flavor only changes the checklist labels and a small set of prompt context flags.

| Trigger | S1 flavor flag | S4 | S5 |
|---|---|---|---|
| Chat turn (edit) | normal | yes | yes |
| Chat turn (concept-only, `is_change_intent=false`) | normal | skipped | n/a |
| Run-ack | `is_run_acknowledgement=true`; agile→assumption row, waterfall→OQ | yes (if brief moved) | yes |
| Post-brief-edit ack | `is_brief_edit_ack=true` | yes | yes |
| Post-config-edit ack | `is_config_save=true` (inverse: brief mirrors panel) | **skipped** | yes (brief↔panel agreement) |

## Modules

- `app/services/llm.py` — `generate_main_turn`, `generate_config_from_brief`, `classify_chat_temperature`, `classify_answered_open_questions`.
- `app/services/pipeline_verification.py` — deterministic S2/S5 checks with plain-English `PipelineIssue.message` for both LLM-retry feedback and the participant bubble.
- `app/services/pipeline_status.py` — per-message `meta.pipeline` writer.
- `app/services/chat_pipeline_runner.py` — S1→S2→S3→S4→S5 orchestration.
- `app/routers/sessions/derivation.py` — deterministic apply helpers (`apply_brief_patch_with_cleanup`, `_apply_assumption_actions`, `_enforce_session_monitors`, `consolidate_run_summary`).
- `app/routers/sessions/router.py` — `/messages` entry point, `/messages/{id}/pipeline/retry`, `/messages/{id}/pipeline/revert`.
- Frontend: `shared/chat/PipelineStatusChecklist.tsx`, `shared/styles.css` (pipeline status rules), `MessageMeta.pipeline` in `shared/api.ts`.

## Symmetry contract (DO NOT VIOLATE)

Mode differences are strictly confined to:
1. `_workflow_prompt(mode)` block in S1's system prompt
2. `_run_ack_prompt(mode)` for run-ack turns
3. Schema-enum: `assumption_actions` valid only when mode ∈ (agile, demo)
4. S2 invariant rules: waterfall→no assumption rows, agile→assumption-row allowed, agile run-ack must add assumption row, waterfall run-ack must add OQ
5. S3 workflow coercion (existing): waterfall assumption→OQ, demo drops assumption

Pipeline shape, status checklist labels, retry budget, failure UX — all identical across modes.

## Issue type taxonomy (S2 / S5 verification + LLM feedback)

```
IssueCategory:
  schema_invalid                            # patch shape failed validation
  claim_without_delta                       # reply claims a change but patch is empty for the claimed surface
  delta_without_claim                       # patch has content not justified by the reply
  unanchored_goal_term                      # new goal_term key lacks evidence_item_ids / properties / cosine anchor
  algorithm_committed_missing_carrier       # reply names algorithm but goal_terms.search_strategy.properties.algorithm empty
  algorithm_carrier_without_commit          # carrier set but reply doesn't surface it
  workflow_invariant_violation              # waterfall has assumption row, etc.
  runack_invariant_violation                # agile run-ack missing assumption, waterfall missing OQ
  port_companion                            # per-port structural concern (e.g. VRPTW driver-pref structured/prose mismatch)
  brief_panel_mismatch                      # S5 only: goal_terms key set or weight mismatch
  brief_panel_algorithm_mismatch            # S5 only: panel algorithm != brief algorithm
```

Each issue carries: `category`, `severity` (error|warn), `subject` (the key/field involved), `message` (plain-English explanation for both LLM feedback AND participant display).

## Problem-agnostic surface

The runner, verifier, schemas, and pipeline-status writer touch no
problem-specific code. Every problem-specific concern flows through
`StudyProblemPort` hooks:

- `goal_term_properties_schema()` — per-port typing for `goal_terms[*].properties`.
- `synthesize_brief_items_from_goal_terms(goal_terms)` — port-specific prose mirrors of structured rules.
- `verify_brief_companion(brief, *, visible_reply=None)` — port-level structural checks (returns `PipelineIssue`-shaped dicts).
- `is_goal_term_self_anchored(key, entry)` — whether structured properties self-justify a goal-term key.
- `auto_anchored_goal_term_keys()` — closed-vocabulary keys that bypass the anchor check.
- `prose_id_prefixes_for_goal_term(key)` — synthesizer namespace reserved against LLM emission.
- `panel_patch_response_json_schema()` + `config_derive_system_prompt()` — per-port panel-derive surfaces.
- `format_run_context_violation_details(violations)` — port-specific run-ack details for the rolling summary.
- `brief_item_ids_to_strip_on_goal_term_removal(...)` — port-specific cascade on goal-term removal.

Adding a new port means implementing these — no edits to the runner, the
verifier, or the schemas.
