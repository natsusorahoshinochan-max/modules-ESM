# 18 — Consolidate structure annotations

**What to build:** A Workflow can compute secondary structure, SASA, and secondary-structure agreement through one `structure_annotation` Module Package with shared residue mapping, truthful binary readiness, and formally typed annotation or scoring outputs.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** ready-for-agent

- [ ] DSSP computation, secondary-structure extraction, SASA calculation, and secondary-structure agreement each have one v2 Node Definition under one package registration.
- [ ] Duplicate DSSP invocation, structure parsing, residue correspondence, and annotation conversion logic is consolidated behind package-local implementation or adapters.
- [ ] The DSSP binary identity and runtime path belong to the Binding and trusted Environment Configuration, with startup Availability and per-Run Readiness instead of Workflow path parameters.
- [ ] Annotation outputs preserve exact residue layout, chain boundaries, missing residues, and nullable values and fail closed on an irreconcilable correspondence.
- [ ] ESM-3 SS8 legal symbols `GHITEBSC` are preserved, unsupported DSSP `-` maps to `C`, and absent values remain `_`; no implicit SS8-to-SS3 conversion is introduced.
- [ ] Secondary-structure agreement is a declared Metric/Method/Context Observation with validated range, direction, multiplicity, and subject identity rather than a free-form score.
- [ ] Readiness failure occurs before binary invocation or Cache lookup, while actual DSSP execution creates truthful Operation and Engine Invocation evidence.
- [ ] Regression fixtures cover the accepted layout-shift defect, multi-chain structures, missing residues, malformed DSSP output, and post-processing failure.
- [ ] The package passes CTK, deterministic public acceptance, and installed discovery without Core provider maps.
