# 08 — Cancel and derive Runs without rewriting history

**What to build:** A client can cancel an active Run and intentionally derive a retry or forced recomputation as a new Run, with deterministic race behavior and no mutation or false continuation of the source Run.

**Blocked by:** 07 — Replay events and reconcile backend restart.

**Status:** ready-for-agent

- [ ] Cancel Run is idempotent and reports a deterministic result for repeated requests, already-terminal Runs, and cancellation/completion races using Ledger ordering.
- [ ] Cancellation prevents unscheduled Nodes from starting, requests cleanup of active work, and produces correct Attempt terminals and Node Dispositions without false Invocation success.
- [ ] Process-group termination, child cleanup, temporary-work cleanup, and cleanup-failure precedence preserve the accepted safety invariants.
- [ ] Start Derived Run requires an immutable source Run reference plus an explicit retry or force policy and creates new Run, Attempt, Operation, and Invocation identities.
- [ ] The source Run, its facts, artifacts, and terminal state remain immutable and independently queryable.
- [ ] Derived execution may reuse only valid typed results under the declared policy; it never copies old Readiness, Operation, or Invocation evidence into the new Run.
- [ ] Cancel, derive, event replay, projection, and artifact operations enforce exact Project/Run scope and return the shared structured-error envelope.
- [ ] Public acceptance covers cancel-before-schedule, cancel-during-operation, completion race, retry after failure, and forced recomputation after success.
