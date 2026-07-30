# 35 — Remove the legacy v1 runtime

**What to build:** After all capabilities and canonical behavior are proven through v2, the backend completes the expand-contract migration by exposing only the v2 runtime and rejecting every legacy format instead of retaining parallel registries, readers, caches, evidence writers, or dispatch paths.

**Blocked by:** 33 — Rewrite repository-owned v2 examples and fixtures; 34 — Re-prove deterministic canonical 3GB1.

**Status:** completed

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

## Controller joint-test evidence

- Previous accepted multi-ticket gate:
  `814bae0abb1c8e802120bb3de96a1d806ebe61ad`; independently tested Ticket 35
  executor SHA: `b12fa4141ade82cadae173dbf122b130a99f8f69`.
- Cutover/public/cache/run focused gate:
  `uv run --no-sync pytest -q tests/test_v1_runtime_cutover.py
  tests/test_verification_tiers.py tests/test_contract_test_kit_v2.py
  tests/test_public_protocol_v2.py tests/test_result_cache_v2.py
  tests/test_run_execution_v2.py` →
  `106 passed, 1 deselected`.
- Tickets 01–35 surviving ordinary v2 gate:
  `uv run --no-sync pytest -q tests/*_v2.py` →
  `639 passed, 7 deselected`; canonical-tier cases are exercised by the
  deterministic gate below.
- Repository examples:
  `uv run --no-sync python scripts/verify_backend.py examples-v2` →
  `11 passed`; retained result
  `verification-results/examples-v2/20260730T152011.503729Z-96179-c73de8f522872d7f`.
- Full post-cutover routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `653 passed, 19 deselected`; retained result
  `verification-results/routine/20260730T152305.910768Z-96565-41eefe694c90b934`.
- Deterministic v2 public-protocol acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` →
  `8 passed`; retained result
  `verification-results/deterministic-acceptance/20260730T152419.526848Z-1520-6c690b658bf9aa9a`.
- Scientific reproduction:
  `uv run --no-sync python scripts/verify_backend.py scientific-repro` →
  `1 passed`; retained result
  `verification-results/scientific-repro/20260730T152428.807697Z-1894-04b6678008928508`.
- Local ESMFold2 source contract:
  `uv run --no-sync python scripts/verify_backend.py
  local-esmfold2-v2-contract` →
  `5 passed`; retained result
  `verification-results/local-esmfold2-v2-contract/20260730T152442.242059Z-1922-efbf3254ea53ef3b`.
- All five retained Controller records report
  `project_revision=b12fa4141ade82cadae173dbf122b130a99f8f69` and
  `project_dirty=false`. Production discovery independently found exactly 11
  package entry points and the Core provider-name search returned no matches.
  The worktree was clean before this evidence-only status update, and no
  post-cutover cross-ticket regression was found.
