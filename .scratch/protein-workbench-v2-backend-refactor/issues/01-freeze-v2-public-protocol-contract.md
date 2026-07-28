# 01 — Freeze the v2 public protocol contract

**What to build:** Backend clients and acceptance tests share one versioned, machine-readable `protein-workbench-public/v2` contract for every supported REST operation, Run Event Stream message, artifact response, and structured error, whether the backend is launched from source or from an installed artifact.

**Blocked by:** None — can start immediately.

**Status:** implementation-complete-awaiting-controller-gate

- [x] The contract bundle is closed-field and defines Catalog Snapshot, Project/Workflow Snapshot, Workflow Compile, Start Run, Start Derived Run, Cancel Run, Run Projection, Run Event Stream, and Artifact Retrieval.
- [x] One source definition drives backend validation, REST schemas, event and error envelopes, and the acceptance client; no independently maintained payload model is introduced.
- [x] The bundle defines method, route, request, response, status mapping, cursor/replay semantics, event unions, close behavior, and the versioned structured-error vocabulary.
- [x] Bundle identity uses I-JSON values, RFC 8785 canonical JSON, UTF-8, SHA-256, and the public `sha256:` digest representation.
- [x] Source-checkout and installed-artifact probes resolve byte-identical bundles and digests, and the production artifact contains every required schema resource.
- [x] The public acceptance harness validates responses only through the bundle and never imports backend internals or falls back to a v1 route or payload.
- [x] Routine verification of the bundle is deterministic, isolated, and requires no provider credential, network call, or heavy model.

## Executor evidence

This evidence records executor completion only; Controller cumulative acceptance
is still required before the next ticket starts.

- Focused public contract: `.venv/bin/pytest -q tests/test_public_protocol_v2.py`
  — `11 passed`.
- Compile/lock checks:
  `.venv/bin/python -m compileall -q core protein_workbench_public
  tests/test_public_protocol_v2.py tests/test_installable_backend.py`,
  `uv lock --check`, and `git diff --check` — passed.
- Installed artifact: `.venv/bin/python scripts/verify_backend.py
  installed-package` — `3 passed`; source, wheel, and installed backend returned
  byte-identical canonical bundles and digests.
- Cumulative routine: `.venv/bin/python scripts/verify_backend.py routine` —
  `696 passed, 44 deselected`.
- Fixed-point Standards/Spec review against
  `21810a494fe66ed3d8cf7bb47c59a1c29d735dcf` found and repaired missing
  `unsupported_schema_version`, incomplete unavailable-Binding reasons, an open
  Catalog descriptor, and invalid Node Disposition outcome/resolution
  combinations. Both review axes passed their follow-up review with no new hard
  or high findings.
