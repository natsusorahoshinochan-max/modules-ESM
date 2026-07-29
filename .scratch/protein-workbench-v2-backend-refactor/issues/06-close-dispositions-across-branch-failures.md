# 06 — Close dispositions across branch failures

**What to build:** A multi-branch Workflow reaches an auditable terminal state in which a failed Node blocks only its dependent branch, unrelated work continues, and every Execution Plan Node has one authoritative disposition with causally closed evidence.

**Blocked by:** 05 — Run a readiness-gated direct Node.

**Status:** awaiting-controller

- [x] Every Plan Node receives exactly one immutable disposition: succeeded, failed, blocked, cancelled, or interrupted; successful dispositions distinguish executed from cache-replayed resolution.
- [x] A scheduled Node creates a Node Execution Attempt, an actual implementation call creates an Operation Attempt, and only crossing a declared scientific engine seam creates an Engine Invocation.
- [x] Blocked and pre-scheduling-cancelled Nodes create dispositions without false Attempts or Invocations and cite their direct causal upstream facts.
- [x] A Node failure blocks only downstream Nodes whose required inputs cannot be satisfied; an unrelated branch continues and may succeed.
- [x] Started Node, Operation, and Invocation records each receive exactly one terminal fact, including failed, cancelled, interrupted, or outcome-unknown states.
- [x] Engine success followed by decode, normalization, validation, or artifact post-processing failure leaves the Invocation successful while the outer Operation and Node fail.
- [x] Evidence is schema-checked, causally validated, redacted, durably persisted, and sequenced before publication; evidence commit failure prevents Node success and any Cache write.
- [x] A Run becomes terminal only after every Plan Node disposition and every started Attempt/Invocation terminal are present and causally closed.
- [x] Public failure diagnostics are bounded and redacted, and Project/Run scope isolation and safe process cleanup are preserved.

## Executor evidence

This records executor completion only. Ticket 07 remains blocked until the
Controller independently runs the cumulative Tickets 01–06 gate and accepts
this state.

- Fixed implementation/review base:
  `f6022113e9418dfc9e4100fc4d8808aa4c843e46`.
- Implementation commits: `10d9dcb`, `a2c7bc0`, and `fd069e6`.
- Focused Run/evidence and public protocol suites:
  `.venv/bin/pytest -q tests/test_run_execution_v2.py
  tests/test_public_protocol_v2.py` → `44 passed`.
- Joint Tickets 01–06 focused regression across Run execution, public
  protocol, Workflow compiler, Module Packages, and Port Types → `192 passed`.
- Cumulative routine gate:
  `.venv/bin/python scripts/verify_backend.py routine` →
  `877 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T024252.889836Z-64190-90e9e849824256db`.
- Deterministic acceptance:
  `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` →
  `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T024426.755622Z-64891-af3d5e72f08ae8af`.
- Installed artifact:
  `.venv/bin/python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T024514.268221Z-65069-d829f8b29707048a`.
- `compileall`, `pip check`, `uv lock --check`, and `git diff --check` passed.
  No standalone mypy/pyright configuration is installed, so no separate
  static-type result is claimed.
- Parallel `/code-review` Standards and Spec reviewers initially found
  output publication before cleanup, incomplete replay-failure closure,
  permissive causal success, private-test mocks, required-input blocking, and
  unconditional one-Invocation conflation. The executor repaired every
  hard/high finding, documented the accepted v2 refinement of ADR-0015, and
  both follow-up review axes returned `APPROVE`.
