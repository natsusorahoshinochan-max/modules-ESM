# 22 — Add the SimpleFold folding Binding

**What to build:** A Workflow can choose SimpleFold as another exact Binding of the shared folding Node Type and obtain reproducible structure Candidates without changing the Node's scientific meaning or sharing unsafe staging state across invocations.

**Blocked by:** 21 — Unify remote and local ESMFold2 folding.

**Status:** awaiting-controller

- [x] SimpleFold reuses the established folding Node Definition while fixing its own Method, checkpoint/source/featurization identity, implementation identity, parameters, Readiness, determinism, and cacheability.
- [x] SimpleFold-specific adjustable parameters belong to the Binding contract; model identity, checkpoint path, device, and staging directory are not free Workflow parameters.
- [x] Availability is lazy and isolated, and failure of SimpleFold dependencies does not hide or block ESMFold2 Bindings.
- [x] Every invocation receives isolated staging and cleanup so concurrent or successive Runs cannot reuse, overwrite, or observe another invocation's temporary files.
- [x] High-level SimpleFold pLDDT already in `[0,100]` is preserved without multiplying again or guessing from observed values.
- [x] Every sample produces a complete validated Candidate with stable producer/output/sample/parent/content identity and exact folding provenance.
- [x] Readiness verifies the selected folding pipeline assets before Cache lookup, while actual model execution creates truthful Engine Invocation evidence.
- [x] Tests cover staging collision, cleanup failure, malformed model output, multi-sample lineage, Cache replay, and unavailable sibling behavior.
- [x] Deterministic, installed-artifact, CTK, and required heavy-model gates prove the Binding without adding a SimpleFold Core branch.

## Executor evidence

This records executor completion only. Ticket 23 must not start until the
Controller independently runs the cumulative Tickets 01–22 gate and accepts
this state. Any joint-test regression must be returned to this Ticket 22
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `e0e8034b79d6940e81b6ff892824276a6a48f035`.
- Implementation and review-fix commits span `ece7885` through `8d3affb`.
- All retained runtime gates below are bound to the clean implementation SHA
  `8d3affb18b0a1dcb05b9ec350a9b5b9e762dbd5e`. The final evidence commit
  changes only this issue record; the Controller will rerun every required
  gate against that final clean revision.
- Joint Tickets 01–22 v2 regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `471 passed`.
- Focused folding/contract regression:
  `uv run --no-sync pytest -q tests/test_simplefold_folding_v2.py
  tests/test_folding_v2.py tests/test_port_types_v2.py
  tests/test_module_packages_v2.py` → `85 passed`.
- Focused SimpleFold provider-evidence regression:
  `uv run --no-sync pytest -q tests/test_provider_evidence.py -k
  simplefold` → `13 passed, 27 deselected`.
- Verification-tier regression:
  `uv run --no-sync pytest -q tests/test_verification_tiers.py` →
  `25 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1159 passed, 49 deselected`; retained result
  `verification-results/routine/20260729T204231.846347Z-71908-1ed54662a402cd69`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T203908.292255Z-70651-ae8361d7c601b39b`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T204021.416144Z-71703-6d7b1224ebbabb98`.
- Required clean-source SimpleFold entity gate:
  `PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION=8d3affb18b0a1dcb05b9ec350a9b5b9e762dbd5e
  uv run --no-sync python scripts/verify_backend.py
  simplefold-v2-heavy-model` → `1 passed, 0 skipped`; retained result
  `verification-results/simplefold-v2-heavy-model/20260729T205158.807245Z-78554-b215920beeab92a3`.
  Its retained `provider-summary.json` has `complete: true`, one ready
  SimpleFold observation, and exactly one successful `fold_sequence` call
  using the declared four-file folding closure plus exact ESM2 source and
  checkpoint identities.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and
  the zero-`core/` diff check passed.
- Parallel `/code-review` Standards and Spec axes both returned `APPROVE`
  after repairs for exact folding-only provider identity, actual Cache
  replay, process-global SimpleFold concurrency isolation, supported evidence
  gate aliasing, and truthful post-Invocation decode failure.
- Ticket 23 has not started.
