---
status: accepted
---

# Runnable Workflows are immutable Workflow Commits

Authoring and execution use two distinct values. A **Workflow Draft** is one
unlocked authoring revision that may be scientifically incomplete or invalid.
A **Workflow Commit** is one immutable, exact, runnable publication of a Draft
against the active `FrozenCatalog`. A Run never executes a Draft.

The authoring owner exposes Draft save and one commit boundary. Commit resolves
the exact Contract Lock, validates topology, scientific Port compatibility,
parameters, Selection consumers, and result-affecting contracts, compiles the
Execution Plan, then publishes the Commit. This is the only scientific
admission seam. The trusted single-user application does not add Project-lock,
concurrent-retry, stale-revision, or idempotency state machines around it.

A Workflow Commit records its Project, source Draft revision and digest,
locked Workflow and digest, active Catalog contract digest, Contract Lock
digest, Execution Plan digest, commit revision, and `workflow_commit_id`.
The authoring owner alone writes and loads Draft and Commit records; Project
bootstrap and seed installation use that owner rather than a parallel Workflow
file.

The public protocol exposes only the current authoring resources:

- `GET` and `PUT /api/v2/projects/{project_id}/workflow/draft`;
- `POST /api/v2/projects/{project_id}/workflow:commit`;
- `GET /api/v2/projects/{project_id}/workflow/active-commit`.

Save and commit submissions contain the unlocked Workflow, not a caller-owned
expected revision. The authoring owner assigns the next Draft and Commit
revisions in the normal sequential flow.

Starting a Run supplies the active `workflow_commit_id`; the runtime asks the
authoring owner for its compiled Plan. The owner trusts the Commit it wrote.
When in-memory compilation state is absent, it parses the record and compiles
the contained locked Workflow normally. The resulting Execution Plan digest
must still equal the public Commit identity, because executing another Plan
under that identity would be scientifically incorrect. It does not reload the
source Draft, relock it, or build a storage-integrity proof. A parse, compile,
or Plan-identity failure fails fast; there is no damage taxonomy or recovery
protocol.

The rejected alternatives are independent mutable save, relock, and compile
resources; executing a caller-provided revision/compile pair; allowing Project
bootstrap to write a second Workflow source; repeated internal validation of
owner-written records; and concurrency machinery for uses outside the expected
single-user flow.
