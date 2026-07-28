# 03 — Discover atomic Module Packages

**What to build:** A repository maintainer can add one explicit Module Package registration and have its public contracts and Binding Availability appear atomically in the same FrozenCatalog consumed by the v2 public Catalog Snapshot, without adding Core dispatch logic.

**Blocked by:** 02 — Publish canonical nominal Port Types.

**Status:** implementation-complete-awaiting-controller-gate

- [x] One immutable Module Package registration can explicitly contribute Node and Metric resources, Methods, Bindings, Port Types, Utility Transforms, lazy factories, and Availability/Readiness declarations.
- [x] Startup discovery reads only first-level Module Packages through their single production registration and does not use recursive Definition scans, globs, helper enumeration, per-Node registration, or import side effects.
- [x] Package import remains safe when optional provider dependencies are absent; each affected Binding remains queryable with a structured unavailable reason and does not hide an available sibling.
- [x] Catalog construction validates closed schemas, resource ownership, exact references, versions, canonical digests, duplicate identities, conflicts, dangling references, and cycles before publication.
- [x] Construction occurs in temporary state and publishes one immutable FrozenCatalog only after every package succeeds; every failure leaves no partial Catalog visible.
- [x] Node, Metric, Method, Binding, and Utility descriptors follow the same canonical byte rules and use explicit behavior identities for factories, probes, adapters, observation propagation, and transforms.
- [x] Catalog Snapshot separates stable contract identity from observed Binding Availability identity and observation time.
- [x] A conforming synthetic registration proves discovery and public query without becoming a production scientific capability.

## Executor evidence

This status records executor completion only. Controller cumulative multi-ticket
acceptance is still required before Ticket 04 may start.

- Fixed review base:
  `9b7626f2a40f7312ee8ee78b1e3dd76d05d4e55a`.
- Implementation commits:
  `8ec282a` (`feat: discover atomic module packages`) and `e210035`
  (`fix: close module package review gaps`).
- Focused Module Package, public protocol, and Port Type suites:
  `.venv/bin/pytest -q tests/test_module_packages_v2.py
  tests/test_public_protocol_v2.py tests/test_port_types_v2.py` →
  `71 passed`.
- Routine backend gate:
  `.venv/bin/python scripts/verify_backend.py routine` →
  `756 passed, 44 deselected`; retained result
  `verification-results/routine/20260728T231339.941343Z-20935-65ab8f388bf2e4b0`.
- Deterministic acceptance gate:
  `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` →
  `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260728T231512.526118Z-21513-37f96f147829a103`.
  Every test selected by this required tier passed; none was skipped.
- Installed-package gate:
  `.venv/bin/python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260728T231559.593426Z-21635-0becbce2958ead42`.
  Source, wheel, and installed API compare the same discovered Catalog
  canonical bytes/digests; production wheels exclude package-local
  `test(s)` and `fixture(s)` resources.
- `compileall`, `pip check`, `uv lock --check`, and `git diff --check`
  passed. No standalone static type checker is installed/configured, so
  this evidence does not claim a separate mypy/pyright result.
- Mandatory parallel Standards and Spec review initially found
  implementation-coupled/tautological tests, a Node Definition vocabulary
  error, missing Produced Observation Context validation, collapsed
  `parameter_groups`, and inconsistent Availability override timestamps.
  The executor repaired each item and both reviewers passed follow-up with
  no remaining hard/high finding. The Standards reviewer retained only
  non-blocking judgement smells about identity tuples and duplicated
  contract-reference presentation.
