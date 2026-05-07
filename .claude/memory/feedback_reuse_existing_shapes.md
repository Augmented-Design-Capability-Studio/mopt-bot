---
name: Reuse existing JSON shapes over parallel containers
description: When extending a data layer, prefer the structured shape that already exists elsewhere in the system over inventing a new container.
type: feedback
---

When extending a data layer (e.g. adding a field to the brief that already has a structured representation in the panel), prefer reusing the existing nested shape — including `goal_terms[key].properties` — over inventing a new parallel container.

**Why:** During the driver_preferences plan, I proposed adding a top-level `structured_companions` field to the brief. The user pushed back: `goal_terms.worker_preference.properties.driver_preferences` is already the established shape on the panel side, with `_apply_goal_terms_overlay` and `_rebuild_goal_terms_metadata` already round-tripping it. A new `structured_companions` container would duplicate concept-space and force every consumer to learn a second pattern.

**How to apply:** Before introducing a new top-level field or wrapper for cross-layer data, search for the canonical shape on the side that already stores it (often the panel's `goal_terms` for solver config, or `problem_brief.items` for participant prose). If a nested location already exists and round-trip helpers operate on it, extend the brief or LLM patch schema to carry that same nested shape. New top-level wrappers are warranted only when the existing shape genuinely doesn't fit — not for ergonomics or naming preferences.
