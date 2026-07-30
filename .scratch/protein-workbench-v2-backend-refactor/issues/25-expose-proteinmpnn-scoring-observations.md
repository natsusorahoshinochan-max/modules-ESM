# 25 — Expose ProteinMPNN scoring Observations

**What to build:** A Workflow can score a sequence against a structure with the exact ProteinMPNN Method and receive formally identified Candidate Observations rather than an untyped score collection or mutable model choice.

**Blocked by:** 24 — Consolidate ProteinMPNN constraints and design.

**Status:** in-progress

- [ ] ProteinMPNN scoring has one independent Node Definition in the existing package and reuses the package's model-loading, input normalization, Readiness, and evidence infrastructure.
- [ ] The scoring Method fixes exact model/checkpoint/source/featurization identity, and the Binding does not expose a mutable `model_name`, checkpoint path, or device as Workflow data.
- [ ] Structure and sequence inputs identify one unambiguous subject Candidate or fail closed before engine execution.
- [ ] Every output is a declared Metric/Method/intrinsic Context Observation with exact shape, unit, direction, range, subject grain, and multiplicity.
- [ ] Produced Observation capability is visible to the Compiler, so a mismatched Method, Metric, Context, or output scope is rejected before provider invocation.
- [ ] Provider-native values are validated without implicit range guessing, silent clamp, or dataset-relative normalization.
- [ ] Actual scoring creates truthful Operation and Engine Invocation evidence; post-processing failure cannot turn an engine result into a published Observation or Cache entry.
- [ ] Candidate and Observation identities survive Cache replay without copying historical Readiness or Invocation facts.
- [ ] CTK, deterministic fixtures, installed-artifact tests, and a required model-backed gate prove the scoring contract and sibling design behavior.
