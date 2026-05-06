---
name: Test minimalism
description: Don't add trivial tests; consolidate the suite during refactors. Tests cost tokens to read and maintain.
type: feedback
---

Don't add many trivial tests. One focused test per behavior is enough; cover the surprising cases, skip the obvious ones. When refactoring, prefer **deleting redundant tests** over keeping them around "just in case."

**Why:** Tests cost tokens to read on every session, and a fat suite of small assertions is harder to scan than a tight suite that pins the load-bearing invariants. The user has explicitly flagged that I tend to over-test (e.g. the per-problem cost-breakdown specs each got their own redundant assertion file before I extracted the shared builder; same energy applied to validator changes that already had structural-error coverage).

**How to apply:**
- Before adding a test, ask "is this behavior already pinned by another test?" — if yes, skip.
- When refactoring, audit existing tests for ones that are now redundant or that test deleted behavior. Delete them in the same change.
- Skip tests that are pure tautologies of the implementation (e.g. asserting a TypedDict's keys are present).
- Prefer one end-to-end test that exercises the integration over many tiny mocked-out unit tests for the same path.
- One focused test per genuinely distinct surprising case; merge similar cases via parametrize when they share scaffolding.
