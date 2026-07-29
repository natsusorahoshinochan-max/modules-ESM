# 22 — Add the SimpleFold folding Binding

**What to build:** A Workflow can choose SimpleFold as another exact Binding of the shared folding Node Type and obtain reproducible structure Candidates without changing the Node's scientific meaning or sharing unsafe staging state across invocations.

**Blocked by:** 21 — Unify remote and local ESMFold2 folding.

**Status:** in-progress

- [ ] SimpleFold reuses the established folding Node Definition while fixing its own Method, checkpoint/source/featurization identity, implementation identity, parameters, Readiness, determinism, and cacheability.
- [ ] SimpleFold-specific adjustable parameters belong to the Binding contract; model identity, checkpoint path, device, and staging directory are not free Workflow parameters.
- [ ] Availability is lazy and isolated, and failure of SimpleFold dependencies does not hide or block ESMFold2 Bindings.
- [ ] Every invocation receives isolated staging and cleanup so concurrent or successive Runs cannot reuse, overwrite, or observe another invocation's temporary files.
- [ ] High-level SimpleFold pLDDT already in `[0,100]` is preserved without multiplying again or guessing from observed values.
- [ ] Every sample produces a complete validated Candidate with stable producer/output/sample/parent/content identity and exact folding provenance.
- [ ] Readiness verifies the selected folding pipeline assets before Cache lookup, while actual model execution creates truthful Engine Invocation evidence.
- [ ] Tests cover staging collision, cleanup failure, malformed model output, multi-sample lineage, Cache replay, and unavailable sibling behavior.
- [ ] Deterministic, installed-artifact, CTK, and required heavy-model gates prove the Binding without adding a SimpleFold Core branch.
