# 07 — Replay events and reconcile backend restart

**What to build:** A client can disconnect from a running Workflow, reconnect with an opaque cursor, and recover an ordered public event history even across backend restart, while incomplete work is closed conservatively without invented success.

**Blocked by:** 06 — Close dispositions across branch failures.

**Status:** ready-for-agent

- [ ] Durable Ledger facts receive monotonic sequence identities before any public projection or event publication.
- [ ] Run Event Stream switches from replay to live delivery without omitting or duplicating a public event and rejects malformed, stale, or cross-scope cursors safely.
- [ ] Manifest-equivalent data, persisted lifecycle output, WebSocket events, and Run Projection are demonstrably consistent projections of the same Ledger facts.
- [ ] Restart with a started but non-terminal Node, Operation, or Invocation appends conservative interrupted or outcome-unknown facts and completes every required Node Disposition.
- [ ] Restart reconciliation never publishes unproved output, writes Cache, guesses a provider result, or silently resumes the original Run.
- [ ] Reconciliation is idempotent: a second restart does not append a second terminal fact or change an already closed outcome.
- [ ] Projection failure does not rewrite durable facts, and the public event stream can be reconstructed after process restart.
- [ ] Acceptance asserts causal closure and actual invocation relationships rather than a fixed historical event or call count.
