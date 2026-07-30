# 35 — Remove the legacy v1 runtime

**What to build:** After all capabilities and canonical behavior are proven through v2, the backend completes the expand-contract migration by exposing only the v2 runtime and rejecting every legacy format instead of retaining parallel registries, readers, caches, evidence writers, or dispatch paths.

**Blocked by:** 33 — Rewrite repository-owned v2 examples and fixtures; 34 — Re-prove deterministic canonical 3GB1.

**Status:** awaiting-controller

- [x] All production discovery, compilation, run admission, execution, query, and persistence paths consume the one FrozenCatalog and no longer use a parallel Definition Registry, factory dictionary, provider map, implicit Type Registry, or repeated Definition load.
- [x] Migrated capabilities live under the 11 cohesive Module Packages; obsolete one-Node package directories, wrappers, registration helpers, and duplicated provider/readiness glue are removed once no v2 caller remains.
- [x] Legacy Workflow, Manifest, Cache, path-output, score, lifecycle, and evidence schemas are removed from active runtime code and return stable `unsupported_schema_version` errors at public boundaries.
- [x] No v1 migrator, dual reader, Score alias, pLDDT range guessing, silent conversion, automatic relock, or v1 public route fallback remains.
- [x] Old pickle/path Cache data is never interpreted as v2 typed results, and legacy manifests or evidence cannot satisfy a current Run or acceptance gate.
- [x] Echo remains test-only, subject-free cross-Metric confidence aggregation remains removed, and the production Catalog contains exactly the accepted capability surface rather than legacy ID-count compatibility.
- [x] Search and runtime probes demonstrate that Core has no ESM-3, ESMFold2, SimpleFold, ProteinMPNN, SoluProt, Protein-Sol, or package-specific dispatch/readiness branch.
- [x] The complete routine and deterministic public-protocol suites remain green after deleting transitional bridges, proving each migration batch landed cleanly.
- [x] This ticket does not delete or mutate local Project, Cache, Run, credential, model, or provider data; any physical cleanup remains separately authorized.

## Executor evidence

- Implementation commits: `daf8421`, `72e4f33`, `e70796f`, and `a78854e`.
- Dual-axis review at `a78854e`: Standards APPROVE and Spec APPROVE, with no remaining actionable findings.
- Focused cutover and verifier regression: `13 passed`; the exited-group-leader cleanup regression also passed 10 consecutive stress runs.
- Routine verification: `653 passed, 19 deselected`; retained at `verification-results/routine/20260730T151412.934479Z-80901-b6ee21104c5a1c84`.
- Deterministic public-protocol acceptance: `8 passed`; retained at `verification-results/deterministic-acceptance/20260730T151523.471667Z-89197-bd684ae28389f680`.
- Production discovery probe found exactly 11 `modules/*/package.py` entry points. Core provider-name search returned no matches.
- `python -m compileall` and `git diff --check` passed. No repository linter executable was available.
- Verification replaced Project, Cache, output, and Run roots with isolated temporary roots. No local Project, Cache, Run, credential, model, or provider data was deleted or mutated.
- Executor handoff stops here. Controller must run the cumulative Ticket 01–35 joint gate before starting Ticket 36.
