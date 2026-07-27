# 12 — Emit ordered run-scoped lifecycle events and trustworthy terminal states

**What to build:** A backend client can follow one run through its project/run-scoped WebSocket stream and trust that ordered Node facts fully explain the distinct terminal result.

**Blocked by:** 11 — Persist a source-bound run manifest and Cache provenance.

**Status:** completed

- [x] Every run event includes project ID, run ID, monotonic sequence number, timestamp, and Node ID where relevant.
- [x] A run-scoped subscriber receives no events from another project or run.
- [x] Node terminal events and their persisted manifest updates precede the run terminal event.
- [x] `completed` is emitted only when every required Node completed successfully, including valid Cache hits.
- [x] Failed, blocked, cancelled, and completed outcomes remain distinct and carry safe structured diagnostics or blocking reasons.
- [x] A failed Node blocks dependent Nodes exactly once while unrelated branches may still complete.
- [x] Fresh and Cache-backed runs obey the same event-ordering contract.
