# 35 — Remove the legacy v1 runtime

**What to build:** After all capabilities and canonical behavior are proven through v2, the backend completes the expand-contract migration by exposing only the v2 runtime and rejecting every legacy format instead of retaining parallel registries, readers, caches, evidence writers, or dispatch paths.

**Blocked by:** 33 — Rewrite repository-owned v2 examples and fixtures; 34 — Re-prove deterministic canonical 3GB1.

**Status:** ready-for-agent

- [ ] All production discovery, compilation, run admission, execution, query, and persistence paths consume the one FrozenCatalog and no longer use a parallel Definition Registry, factory dictionary, provider map, implicit Type Registry, or repeated Definition load.
- [ ] Migrated capabilities live under the 11 cohesive Module Packages; obsolete one-Node package directories, wrappers, registration helpers, and duplicated provider/readiness glue are removed once no v2 caller remains.
- [ ] Legacy Workflow, Manifest, Cache, path-output, score, lifecycle, and evidence schemas are removed from active runtime code and return stable `unsupported_schema_version` errors at public boundaries.
- [ ] No v1 migrator, dual reader, Score alias, pLDDT range guessing, silent conversion, automatic relock, or v1 public route fallback remains.
- [ ] Old pickle/path Cache data is never interpreted as v2 typed results, and legacy manifests or evidence cannot satisfy a current Run or acceptance gate.
- [ ] Echo remains test-only, subject-free cross-Metric confidence aggregation remains removed, and the production Catalog contains exactly the accepted capability surface rather than legacy ID-count compatibility.
- [ ] Search and runtime probes demonstrate that Core has no ESM-3, ESMFold2, SimpleFold, ProteinMPNN, SoluProt, Protein-Sol, or package-specific dispatch/readiness branch.
- [ ] The complete routine and deterministic public-protocol suites remain green after deleting transitional bridges, proving each migration batch landed cleanly.
- [ ] This ticket does not delete or mutate local Project, Cache, Run, credential, model, or provider data; any physical cleanup remains separately authorized.
