# 01 — Freeze the v2 public protocol contract

**What to build:** Backend clients and acceptance tests share one versioned, machine-readable `protein-workbench-public/v2` contract for every supported REST operation, Run Event Stream message, artifact response, and structured error, whether the backend is launched from source or from an installed artifact.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The contract bundle is closed-field and defines Catalog Snapshot, Project/Workflow Snapshot, Workflow Compile, Start Run, Start Derived Run, Cancel Run, Run Projection, Run Event Stream, and Artifact Retrieval.
- [ ] One source definition drives backend validation, REST schemas, event and error envelopes, and the acceptance client; no independently maintained payload model is introduced.
- [ ] The bundle defines method, route, request, response, status mapping, cursor/replay semantics, event unions, close behavior, and the versioned structured-error vocabulary.
- [ ] Bundle identity uses I-JSON values, RFC 8785 canonical JSON, UTF-8, SHA-256, and the public `sha256:` digest representation.
- [ ] Source-checkout and installed-artifact probes resolve byte-identical bundles and digests, and the production artifact contains every required schema resource.
- [ ] The public acceptance harness validates responses only through the bundle and never imports backend internals or falls back to a v1 route or payload.
- [ ] Routine verification of the bundle is deterministic, isolated, and requires no provider credential, network call, or heavy model.
