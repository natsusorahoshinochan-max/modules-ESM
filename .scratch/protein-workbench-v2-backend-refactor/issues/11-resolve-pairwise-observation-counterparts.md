# 11 — Resolve pairwise Observation counterparts

**What to build:** A Workflow can score each subject against its exact dynamic counterpart within an explicitly selected Score Collection partition, and both compilation and execution reject ambiguous pairings or cross-objective contamination.

**Blocked by:** 10 — Produce and select intrinsic Observations.

**Status:** ready-for-agent

- [ ] Pairwise Context uses typed participant roles and records subject identity, exact reference Candidate identity/content digest, pairing mode, and result-defining normalization.
- [ ] Produced Observation contracts express fixed sets and controlled pass-through, union, or filter propagation while preserving source partitions and declared multiplicity.
- [ ] Compiler derives the exact observation capability of each relevant output Port without executing arbitrary selector or lineage-query code.
- [ ] Selection Objective binds an explicit Candidate input, Score Collection source partition, Metric, Method, canonical Context profile, and per-subject match cardinality.
- [ ] Runtime resolves the exact generated reference for each subject inside the declared partition; zero matches and multiple matches fail closed by default.
- [ ] Pairing never depends on collection order, free-form suffixes, incidental lineage guessing, or a global reference that is absent from the declared Context.
- [ ] A fixture with fixed-reference and per-subject counterpart objectives proves that the two partitions cannot cross-match even when Metric names and values overlap.
- [ ] Invalid source scope, Context role/profile, normalization, Method, or cardinality fails before provider invocation when statically knowable and otherwise before selection publication.
