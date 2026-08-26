---
status: accepted
---

# Runnable Workflows are immutable Workflow Commits

Authoring and execution use two distinct values. A **Workflow Draft** is one
unlocked authoring revision that may be scientifically incomplete or invalid.
A **Workflow Commit** is one immutable runnable publication of an admitted Draft
against the current stable-ID Catalog. A Run never executes a Draft.

The authoring owner exposes Draft save and one commit boundary. Commit resolves
stable Node Type and Binding IDs, validates topology, scientific Port
compatibility, parameters, Selection consumers, and result-affecting scientific
relationships, then compiles the in-process Execution Plan and publishes the
Commit. The trusted single-user application does not add Project-lock,
concurrent-retry, stale-revision, or idempotency state machines around it.

A Workflow Commit records its Project, source Draft revision, admitted Workflow,
minimum Node/Method/Metric scientific definition snapshots, and
`workflow_commit_id`. It does not store an Execution Plan, Contract Lock,
internal contract semver, Catalog descriptor digest, Workflow digest, Contract
Lock digest, or Execution Plan digest. The authoring owner alone writes and
loads Draft and Commit records; Project bootstrap and seed installation use
that owner rather than a parallel Workflow file.

The public protocol exposes only the current authoring resources:

- `GET` and `PUT /api/v2/projects/{project_id}/workflow/draft`;
- `POST /api/v2/projects/{project_id}/workflow:commit`;
- `GET /api/v2/projects/{project_id}/workflow/active-commit`.

Save and commit submissions contain the unlocked Workflow, not a caller-owned
expected revision. The authoring owner assigns the next Draft revision and
stores each Commit in the normal sequential flow.

Starting a Run supplies the active `workflow_commit_id`. The runtime loads that
Commit and uses its admitted Workflow. When in-memory compilation state is
absent, the authoring owner compiles that Workflow against the current Catalog
rather than reloading the source Draft or re-resolving a historical Contract
Lock. The compiled plan must have the same scientific definition snapshots as
the Commit; otherwise that development Commit is invalid under the current
checkout and fails fast. The Commit's embedded snapshots remain the
interpretation record for the completed Run. Parse or scientific admission
failures fail fast; there is no compatibility reader, damage taxonomy, or
recovery protocol.
