# 33 — Rewrite repository-owned v2 examples and fixtures

**What to build:** Maintainers receive a coherent set of repository-owned v2 examples, seeds, fixtures, and capability checks that use exact contracts from the 11 cohesive Module Packages and no longer preserve accidental v1 Node IDs or payload shapes.

**Blocked by:** 13 — Consolidate protein I/O; 15 — Assemble and update ProteinPrompts; 16 — Make stochastic prompt authoring reproducible; 17 — Consolidate structure transforms; 18 — Consolidate structure annotations; 20 — Add local ESM-3 Bindings; 23 — Fix existing-structure SimpleFold confidence; 25 — Expose ProteinMPNN scoring Observations; 27 — Produce scoped TM-score Observations; 28 — Preserve partitions in collection operations; 30 — Migrate explicit multi-objective selection; 32 — Add Protein-Sol Metrics and calibration Context.

**Status:** completed

- [x] Every maintained example, seed other than the separately accepted canonical 3GB1 seed, and reusable fixture uses v2 Workflow schema, exact Node/Binding versions, separate parameter maps, and a valid reachable Contract Lock.
- [x] Examples choose Bindings explicitly and never depend on Availability-driven selection, `latest`, mutable `model_name`, credential/path Workflow parameters, or silent fallback.
- [x] Score examples use exact Metric/Method/Context Observations, source-scoped objectives, versioned Utilities, and explicit missing-value policies rather than `score_id`.
- [x] Examples cover the accepted scientific capabilities of all 11 Module Packages without requiring preservation of all legacy Node IDs or the old 43-directory layout.
- [x] `stub.echo` appears only as Contract Test Kit support, the subject-free confidence aggregation is absent, and superseded wrapper/helper capabilities are not advertised as production Nodes.
- [x] Fixture construction consumes public or CTK contracts rather than importing private runtime registries, factory maps, provider maps, or manually instantiating a parallel module universe.
- [x] Capability inventory compares source and installed Catalogs by canonical contract identity and confirms package-local tests and fixtures are absent from the production artifact.
- [x] Legacy Workflow/Manifest/Cache samples remain only where explicitly required to test `unsupported_schema_version`; they are never silently rewritten or executed.
- [x] Routine example verification is deterministic, isolated, provider-free, and leaves existing local Projects, Cache, and Run records untouched.

## Executor evidence

- Accepted base: `49dacefd6505cc1a5c0c27cb41fe923218a1ea13`.
- Implementation commits: `32ba5e0b5642cd5bf3afefc42c7871e24792bd28`, `f3b1111d87b2f63c82b047e85c65a16c75ceb6d5`, and `544387a341e8b8b79024484564aa072fa0061525`.
- TDD red gate: the new repository-example contract initially failed because `examples.v2_suite` did not exist.
- The production Workflow plus two locked CTK Workflows cover exactly all 44 production Node Types and all 57 production Execution Bindings from all 11 Module Packages. The capability inventory additionally fixes all 165 canonical Node Type, Execution Binding, Method, and Metric references.
- The accepted canonical 3GB1 seed remains unchanged for its separately accepted contract.
- Focused Ticket 33 suite: `11 passed`.
- Repository example tier: `11 passed`; retained result `/Users/sorachan/Documents/modules-ESM/verification-results/examples-v2/20260730T104141.857678Z-88156-0ca78d8be90540c3`.
- Installed-package tier: `3 passed`; retained result `/Users/sorachan/Documents/modules-ESM/verification-results/installed-package/20260730T104141.857678Z-88157-1615472c0ed1870d`.
- Deterministic-acceptance tier: `10 passed, 5 deselected`; retained result `/Users/sorachan/Documents/modules-ESM/verification-results/deterministic-acceptance/20260730T104141.857675Z-88155-66fa2b6dd447ee5e`.
- Routine tier: `1333 passed, 56 deselected`; retained result `/Users/sorachan/Documents/modules-ESM/verification-results/routine/20260730T104313.247265Z-91300-7f27038b0daea728`.
- `compileall` and `git diff --check` passed.
- Final dual-axis review: Standards `0 CRITICAL / 0 HIGH / 0 MEDIUM`; Spec `0 CRITICAL / 0 HIGH / 0 MEDIUM`.

## Controller joint-test evidence

- Previous accepted multi-ticket gate:
  `49dacefd6505cc1a5c0c27cb41fe923218a1ea13`; independently tested Ticket 33
  executor SHA: `5f8df75d04f9a0228dc274c23ac929ac6db5164d`.
- Repository-owned v2 examples and capability inventory:
  `uv run --no-sync python scripts/verify_backend.py examples-v2` →
  `11 passed`; retained result
  `verification-results/examples-v2/20260730T105024.452968Z-1600-5b5977a6b3d375b5`.
- Tickets 01–33 cumulative v2 gate:
  `uv run --no-sync pytest -q tests/*_v2.py` →
  `641 passed`.
- Full routine joint gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1333 passed, 56 deselected`; retained result
  `verification-results/routine/20260730T105335.846416Z-6431-7a7ff022f3029ed8`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` →
  `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260730T105929.654887Z-15250-37ec2d2b96749a0b`.
- Installed-package isolation:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260730T110044.740385Z-15959-cfdff9e3b21782e8`.
- All four retained Controller records report
  `project_revision=5f8df75d04f9a0228dc274c23ac929ac6db5164d` and
  `project_dirty=false`. The worktree was clean before this evidence-only
  status update, and no cross-ticket or repository-example isolation
  regression was found.
