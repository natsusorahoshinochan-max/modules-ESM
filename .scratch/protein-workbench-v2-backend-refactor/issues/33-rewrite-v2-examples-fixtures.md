# 33 — Rewrite repository-owned v2 examples and fixtures

**What to build:** Maintainers receive a coherent set of repository-owned v2 examples, seeds, fixtures, and capability checks that use exact contracts from the 11 cohesive Module Packages and no longer preserve accidental v1 Node IDs or payload shapes.

**Blocked by:** 13 — Consolidate protein I/O; 15 — Assemble and update ProteinPrompts; 16 — Make stochastic prompt authoring reproducible; 17 — Consolidate structure transforms; 18 — Consolidate structure annotations; 20 — Add local ESM-3 Bindings; 23 — Fix existing-structure SimpleFold confidence; 25 — Expose ProteinMPNN scoring Observations; 27 — Produce scoped TM-score Observations; 28 — Preserve partitions in collection operations; 30 — Migrate explicit multi-objective selection; 32 — Add Protein-Sol Metrics and calibration Context.

**Status:** ready-for-agent

- [ ] Every maintained example, seed other than the separately accepted canonical 3GB1 seed, and reusable fixture uses v2 Workflow schema, exact Node/Binding versions, separate parameter maps, and a valid reachable Contract Lock.
- [ ] Examples choose Bindings explicitly and never depend on Availability-driven selection, `latest`, mutable `model_name`, credential/path Workflow parameters, or silent fallback.
- [ ] Score examples use exact Metric/Method/Context Observations, source-scoped objectives, versioned Utilities, and explicit missing-value policies rather than `score_id`.
- [ ] Examples cover the accepted scientific capabilities of all 11 Module Packages without requiring preservation of all legacy Node IDs or the old 43-directory layout.
- [ ] `stub.echo` appears only as Contract Test Kit support, the subject-free confidence aggregation is absent, and superseded wrapper/helper capabilities are not advertised as production Nodes.
- [ ] Fixture construction consumes public or CTK contracts rather than importing private runtime registries, factory maps, provider maps, or manually instantiating a parallel module universe.
- [ ] Capability inventory compares source and installed Catalogs by canonical contract identity and confirms package-local tests and fixtures are absent from the production artifact.
- [ ] Legacy Workflow/Manifest/Cache samples remain only where explicitly required to test `unsupported_schema_version`; they are never silently rewritten or executed.
- [ ] Routine example verification is deterministic, isolated, provider-free, and leaves existing local Projects, Cache, and Run records untouched.
