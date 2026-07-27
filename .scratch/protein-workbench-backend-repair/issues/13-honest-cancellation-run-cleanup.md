# 13 — Cancel and clean up active runs honestly

**What to build:** A protein engineer can request cancellation without the backend claiming success prematurely, and concurrent or finished work cannot leak or collide in a long-lived backend process.

**Blocked by:** 12 — Emit ordered run-scoped lifecycle events and trustworthy terminal states.

**Status:** ready-for-agent

- [ ] A project rejects a second active run until complete run isolation is explicitly supported.
- [ ] A cancellation request is visible immediately but does not become terminal until active work has stopped.
- [ ] Blocking provider or subprocess work uses a controllable boundary, or a documented cancellation timeout ends as a failed run rather than false cancellation.
- [ ] Cancelled, failed, and completed runs produce distinct terminal events and manifest states.
- [ ] Active-run tracking is cleaned up in a guaranteed path after every terminal outcome.
- [ ] Cancellation and cleanup leave no mutable run state that can affect a later run.
