# 12 — Prove the zero-Core extension journey

**What to build:** A repository maintainer can add one conforming test Module Package, validate it with the shared Contract Test Kit, and use it through startup discovery and the complete installed-backend public journey without modifying Core dispatch or inventing package-specific test infrastructure.

**Blocked by:** 08 — Cancel and derive Runs without rewriting history; 11 — Resolve pairwise Observation counterparts.

**Status:** awaiting-controller

- [x] Contract Test Kit consumes the production Module Package registration plus independent test cases and fixtures rather than embedding test data in the registration.
- [x] The kit builds an isolated temporary FrozenCatalog and exercises registration, Definitions, Port Types, parameters, Availability, Readiness, provenance, Result Identity, Candidates, Metrics, and produced observations through the unified execution interface.
- [x] A conforming synthetic package is discovered at startup, appears in Catalog Snapshot, compiles, executes, replays, and retrieves output through the public protocol with no Core dispatch edit.
- [x] Negative conformance cases cover malformed resources, unknown fields/schema, eager optional dependencies, duplicate or conflicting identities, dangling/cyclic references, invalid codecs, false readiness, and incomplete provenance.
- [x] Source checkout and installed artifact discover equivalent contracts and behavior identities for the extension, and package-local tests and fixtures are excluded from the production wheel.
- [x] The production FrozenCatalog does not expose the synthetic echo capability; it remains test support only.
- [x] Routine CTK and public journey tests are deterministic, isolated, provider-free, and prove no secret, private path, or unsafe diagnostic is published.
- [x] The resulting maintainer workflow is documented by executable contracts rather than a second package template or Core-specific registration path.

## Executor evidence

This records executor completion only. Ticket 13 must not start until the
Controller independently runs the cumulative Tickets 01–12 gate and accepts
this state.

- Fixed implementation/review base:
  `13928834520ae32c2189a03ad2a637bdbdf1fe75`.
- Implementation and review-fix commits: `f8c0e7e`, `1057aec`, and
  `7872479`.
- Joint Tickets 01–12 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, pairwise scoring, and the Contract Test
  Kit:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py` → `299 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `985 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T090637.892433Z-38217-f999aa34c64c4b3e`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T090842.787610Z-38950-bce6c094dbd21f5f`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T090543.575363Z-37835-c5cb85b79d122a1c`.
- `compileall`, `uv lock --check`, `uv pip check`, and `git diff --check`
  passed at clean implementation HEAD
  `78724793832e84b6abd5862b4ca9587a49bf36e3`.
- Parallel `/code-review` Standards and Spec reviewers drove fixes for unsafe
  case identifiers, incomplete package-owned contract coverage, an internal
  test double, omitted Derived Run acceptance, and REST/WebSocket routes not
  fully derived from the public bundle. All findings were repaired with
  regressions; both final review axes returned `APPROVE` at `7872479`.
