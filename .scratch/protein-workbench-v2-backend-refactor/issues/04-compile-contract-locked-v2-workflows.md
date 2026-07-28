# 04 — Compile contract-locked v2 Workflows

**What to build:** A Workflow author can save and compile an exact v2 Workflow through the public protocol, and the backend either returns an immutable compile receipt bound to the author-approved reachable contract closure or rejects it before any provider or implementation activity.

**Blocked by:** 03 — Discover atomic Module Packages.

**Status:** ready-for-agent

- [ ] Workflow and Node Instance schemas require v2 schema identity, exact Node Type and Binding ID/version, separate Node and Binding parameters, named Ports, and no duplicated Method choice.
- [ ] The Workflow Contract Lock contains exactly the reachable Node, Binding, Method, Metric, Port Type, and Utility contracts with expected digests, in canonical deterministic order.
- [ ] Compilation independently recomputes the reachable closure from the current FrozenCatalog and rejects missing, duplicate, incomplete, stale-extra, or mismatched Lock entries with `contract_digest_mismatch`.
- [ ] Contract mismatch is detected before Availability evaluation, provider probing, implementation construction, or any execution side effect; changes to unreachable Catalog contracts do not invalidate the Workflow.
- [ ] Compilation validates schema, DAG structure, Binding ownership, parameters, exact Port compatibility, Availability, and all currently expressible contract references.
- [ ] Successful compilation produces an immutable private Execution Plan while the public response exposes only the compact Workflow, Catalog, Lock, and plan identities plus structured issues.
- [ ] Explicit relock creates a new Workflow revision; load, save, compile, and Run never silently refresh or repair an existing Lock.
- [ ] Version ranges, `latest`, automatic Binding selection, silent fallback, mixed environment parameters, and v1 Workflow schemas are rejected with stable public errors.
