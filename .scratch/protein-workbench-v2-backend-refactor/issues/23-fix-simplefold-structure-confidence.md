# 23 — Fix existing-structure SimpleFold confidence

**What to build:** A Workflow can evaluate an existing structure with one fixed SimpleFold confidence Method that declares and loads exactly the assets that affect the computation, emits canonical pLDDT Observations, and never performs an implicit refold.

**Blocked by:** 22 — Add the SimpleFold folding Binding.

**Status:** in-progress

- [ ] Existing-structure confidence is a separate Node Type from folding and accepts an existing structure without invoking the folding Node or a folding checkpoint.
- [ ] The Method identity fixes `simplefold_1.6B.ckpt`, `plddt_module_1.6B.ckpt`, `esm2_t36_3B_UR50D.pt`, versioned structure featurization, `ccd.pkl`, upstream scientific source, and native-to-canonical scale.
- [ ] Declared immutable asset digests enter Method identity where required; resolved asset digests enter Binding Readiness, Result Identity, and Engine Invocation provenance.
- [ ] `esm2_t36_3B_UR50D-contact-regression.pt`, `boltz1_conf.ckpt`, and unused folding checkpoints are neither probed nor loaded and do not appear in identity, readiness, or provenance.
- [ ] Missing or mismatched required assets fail Readiness before Cache lookup; replacing any required model/data artifact invalidates a prior attestation.
- [ ] Direct confidence-head `[0,1]` output is statically multiplied by 100, and public per-residue and mean-residue pLDDT obey valid-residue masking without range guessing.
- [ ] Produced Observation contracts declare exact pLDDT Metrics, Method, intrinsic Context, output Port, subject grain, and multiplicity.
- [ ] Any result-affecting checkpoint, head, encoder, featurization, source, adapter, or scale change requires a new Method/Binding identity.
- [ ] Deterministic native fixtures and a required heavy-model test prove the exact asset closure, no-refold behavior, invocation evidence, pLDDT values, CTK conformance, and installed discovery.
