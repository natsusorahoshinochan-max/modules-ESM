# 08 — Cancel and derive Runs without rewriting history

**What to build:** A client can cancel an active Run and intentionally derive a retry or forced recomputation as a new Run, with deterministic race behavior and no mutation or false continuation of the source Run.

**Blocked by:** 07 — Replay events and reconcile backend restart.

**Status:** awaiting-controller

- [x] Cancel Run is idempotent and reports a deterministic result for repeated requests, already-terminal Runs, and cancellation/completion races using Ledger ordering.
- [x] Cancellation prevents unscheduled Nodes from starting, requests cleanup of active work, and produces correct Attempt terminals and Node Dispositions without false Invocation success.
- [x] Process-group termination, child cleanup, temporary-work cleanup, and cleanup-failure precedence preserve the accepted safety invariants.
- [x] Start Derived Run requires an immutable source Run reference plus an explicit retry or force policy and creates new Run, Attempt, Operation, and Invocation identities.
- [x] The source Run, its facts, artifacts, and terminal state remain immutable and independently queryable.
- [x] Derived execution may reuse only valid typed results under the declared policy; it never copies old Readiness, Operation, or Invocation evidence into the new Run.
- [x] Cancel, derive, event replay, projection, and artifact operations enforce exact Project/Run scope and return the shared structured-error envelope.
- [x] Public acceptance covers cancel-before-schedule, cancel-during-operation, completion race, retry after failure, and forced recomputation after success.

## Executor evidence

This records executor completion only. Ticket 09 must not start until the
Controller independently runs the cumulative Tickets 01–08 gate and accepts
this state.

- Fixed implementation/review base:
  `8bd3362e9178d55f5d1d13ce9b9cfbb41001ac4e`.
- Implementation and review-fix commits: `56db2b0`, `646d33b`, `63e8b1d`,
  and `f8f84cb`.
- Focused cancellation/derivation acceptance:
  `uv run --no-sync python -m pytest -q
  tests/test_run_cancel_derive_v2.py` → `16 passed`.
- Joint Tickets 01–08 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation, and
  derivation → `221 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `907 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T043522.535300Z-88492-91efd4ff48ffff95`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T043734.609164Z-89342-03149701ecd2c489`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T043827.221425Z-89579-70bf3bdf153a57e3`.
- `compileall`, `pip check`, `uv lock --check`, and
  `git diff --check 8bd3362...HEAD` passed. No standalone mypy/pyright
  configuration is installed, so no separate static-type result is claimed.
- Parallel `/code-review` Standards and Spec reviewers initially found
  cancellation-cleanup races, late process-group escalation gaps, uncommitted
  artifact cleanup gaps, and an artifact retrieval visibility window. The
  executor repaired all findings, added focused regressions, and both final
  review axes returned `APPROVE` at `f8f84cb`.
