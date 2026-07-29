# 23 — Fix existing-structure SimpleFold confidence

**What to build:** A Workflow can evaluate an existing structure with one fixed SimpleFold confidence Method that declares and loads exactly the assets that affect the computation, emits canonical pLDDT Observations, and never performs an implicit refold.

**Blocked by:** 22 — Add the SimpleFold folding Binding.

**Status:** awaiting-controller

- [x] Existing-structure confidence is a separate Node Type from folding and accepts an existing structure without invoking the folding Node or a folding checkpoint.
- [x] The Method identity fixes `simplefold_1.6B.ckpt`, `plddt_module_1.6B.ckpt`, `esm2_t36_3B_UR50D.pt`, versioned structure featurization, `ccd.pkl`, upstream scientific source, and native-to-canonical scale.
- [x] Declared immutable asset digests enter Method identity where required; resolved asset digests enter Binding Readiness, Result Identity, and Engine Invocation provenance.
- [x] `esm2_t36_3B_UR50D-contact-regression.pt`, `boltz1_conf.ckpt`, and unused folding checkpoints are neither probed nor loaded and do not appear in identity, readiness, or provenance.
- [x] Missing or mismatched required assets fail Readiness before Cache lookup; replacing any required model/data artifact invalidates a prior attestation.
- [x] Direct confidence-head `[0,1]` output is statically multiplied by 100, and public per-residue and mean-residue pLDDT obey valid-residue masking without range guessing.
- [x] Produced Observation contracts declare exact pLDDT Metrics, Method, intrinsic Context, output Port, subject grain, and multiplicity.
- [x] Any result-affecting checkpoint, head, encoder, featurization, source, adapter, or scale change requires a new Method/Binding identity.
- [x] Deterministic native fixtures and a required heavy-model test prove the exact asset closure, no-refold behavior, invocation evidence, pLDDT values, CTK conformance, and installed discovery.

## Executor evidence

- Starting Controller gate: `aa236fa90ef1409412b612c30aa59f5c5cf7ea37`.
- TDD RED: the initial Ticket 23 contract suite failed in 7 places because the confidence Node Type, Method, Binding, and Adapter did not yet exist.
- Implementation commits: `137605b`, `dc08796`, `ad05617`, `986adf6`, `20427fe`, and `6a1ee92`.
- Focused final gate: `uv run --no-sync pytest -q tests/test_folding_v2.py tests/test_simplefold_folding_v2.py tests/test_simplefold_confidence_v2.py tests/test_module_packages_v2.py tests/test_contract_test_kit_v2.py` — `82 passed`.
- Full routine gate on implementation SHA `6a1ee9245a99eaacba42fd77a091c8fbc72e130a`: `1171 passed, 50 deselected`; retained result: `verification-results/routine/20260729T221722.061028Z-18381-0c0b1f11a0f30164`.
- Deterministic acceptance on the same SHA: `10 passed, 5 deselected`; retained result: `verification-results/deterministic-acceptance/20260729T222156.537949Z-25257-206cc01ceb3a4d45`.
- Installed-package gate on the same SHA: `3 passed`; retained result: `verification-results/installed-package/20260729T222311.468578Z-25968-692b549d84a3b3f0`.
- Required source-bound heavy gate on approved source revision `6a1ee9245a99eaacba42fd77a091c8fbc72e130a`: `1 passed, 0 skipped`. It executed the native 3GB1 confidence path, emitted 56 residue pLDDT values, guarded every forbidden checkpoint/contact-regression file operation, guarded provider refold entry points, and retained exact resolved asset/Invocation evidence. Retained result: `verification-results/simplefold-confidence-v2-heavy-model/20260729T221311.424944Z-17446-fd10679f70248ab8`.
- `/code-review` Standards initially reported three LOW smells; Spec reported two HIGH findings (multi-chain featurization and resolved-digest provenance) plus one MEDIUM heavy-gate proof gap. The executor fixed all findings and added chain-aware/blank-chain regression coverage, digest-bound identities, exact access guards, and refold guards. Final Standards and Spec reviews both returned `APPROVE` on `6a1ee92`.
- `git diff --check aa236fa90ef1409412b612c30aa59f5c5cf7ea37..HEAD` passes; `git diff aa236fa90ef1409412b612c30aa59f5c5cf7ea37..HEAD -- core` is empty.
- Ticket 24 was not started. Ticket 23 remains `awaiting-controller` until the Controller independently runs the cumulative multi-ticket gate.
