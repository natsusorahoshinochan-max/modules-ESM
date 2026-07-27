# 13 — Cancel and clean up active runs honestly

**What to build:** A protein engineer can request cancellation without the backend claiming success prematurely, and concurrent or finished work cannot leak or collide in a long-lived backend process.

**Blocked by:** 12 — Emit ordered run-scoped lifecycle events and trustworthy terminal states.

**Status:** completed

- [x] A project rejects a second active run until complete run isolation is explicitly supported.
- [x] A cancellation request is visible immediately but does not become terminal until active work has stopped.
- [x] Blocking provider or subprocess work uses a controllable boundary, or a documented cancellation timeout ends as a failed run rather than false cancellation.
- [x] Cancelled, failed, and completed runs produce distinct terminal events and manifest states.
- [x] Active-run tracking is cleaned up in a guaranteed path after every terminal outcome.
- [x] Cancellation and cleanup leave no mutable run state that can affect a later run.

## Cancellation timeout contract

The backend gives active Module work 5,000 ms to stop after a cancellation
request. The request is immediately observable as `cancellation_requested`,
which is not terminal. If the isolated worker does not stop within that grace
period, the backend force-stops its process group and records a failed run with
`error.kind = "cancellation_timeout"` and `error.timeout_ms = 5000`; it never
reports that run as cancelled. A terminal run event is published only after the
worker boundary has stopped and the manifest has reached its matching terminal
state. Every terminal worker outcome also receives a bounded one-second exit
window followed by process-group cleanup, so descendant processes cannot outlive
their run.
