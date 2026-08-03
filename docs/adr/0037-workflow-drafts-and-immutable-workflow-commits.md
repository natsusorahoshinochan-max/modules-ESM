---
status: accepted
---

# Runnable Workflows are immutable Workflow Commits

Authoring and execution use two distinct values. A **Workflow Draft** is one
unlocked, immutable authoring revision that may be scientifically incomplete or
invalid. A **Workflow Commit** is one immutable, exact, runnable publication of
a Draft against the active `FrozenCatalog`. A Run never executes a Draft and
never identifies executable state by an independently supplied Workflow
revision and compile ID.

The authoring owner exposes a shallow autosave operation for Drafts and one
deep commit operation for preparing a Run. The commit operation accepts the
expected active Draft revision and the submitted unlocked Workflow, then under
one Project-scoped lock:

1. publishes the submitted Draft revision;
2. resolves one exact Contract Lock against the active Catalog;
3. validates Workflow topology, exact nominal Port compatibility, parameters,
   Selection consumers, and result-affecting contracts;
4. compiles one immutable Execution Plan; and
5. atomically publishes the closed Workflow Commit record as the active
   runnable state.

If locking, validation, or compilation fails, the submitted Draft remains
available for correction while the previously active Workflow Commit and its
Execution Plan remain unchanged. Repeating the same commit submission is
idempotent, including concurrent retries; a different submission against a
stale Draft revision fails with an explicit revision conflict.

A Workflow Commit records its Project, source Draft revision and digest,
locked Workflow and digest, active Catalog contract digest, Contract Lock
digest, Execution Plan digest, commit revision, and `workflow_commit_id`.
Closed Draft and Commit records are append-only durable artifacts. The
authoring owner alone writes and loads them; Project bootstrap and seed
installation must use that owner rather than write a parallel Workflow file or
manufacture a receipt.

The public protocol exposes only the current authoring resources:

- `GET` and `PUT /api/v2/projects/{project_id}/workflow/draft`;
- `POST /api/v2/projects/{project_id}/workflow:commit`;
- `GET /api/v2/projects/{project_id}/workflow/active-commit`.

Starting a Run supplies the exact active `workflow_commit_id`. The runtime asks
the authoring owner for its compiled Plan. After restart the owner may hydrate
that Plan only by reloading the exact closed Commit, checking every persisted
digest and exact Contract reference against the same active Catalog, and
recompiling to the recorded Execution Plan digest. Catalog drift, an inactive
contract, a mismatched digest, or damaged durable data fails closed. There is
no save-then-relock-then-compile public state machine and no legacy endpoint or
parser for it.

Derived Runs remain stricter: they reuse the source Run's retained in-memory
executable Plan and do not reconstruct a replacement from the active Workflow
Commit after process restart.

The rejected alternatives are independent mutable save, relock, and compile
resources; executing a caller-provided revision/compile pair; allowing Project
bootstrap to write a second Workflow source; rolling back an invalid Draft and
thereby losing the user's submitted work; and silently rebuilding under a
different Catalog. This decision makes the deep commit described in the
current architecture the only runnable authoring seam.
