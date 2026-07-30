# 25 — Expose ProteinMPNN scoring Observations

**What to build:** A Workflow can score a sequence against a structure with the exact ProteinMPNN Method and receive formally identified Candidate Observations rather than an untyped score collection or mutable model choice.

**Blocked by:** 24 — Consolidate ProteinMPNN constraints and design.

**Status:** awaiting-controller

- [x] ProteinMPNN scoring has one independent Node Definition in the existing package and reuses the package's model-loading, input normalization, Readiness, and evidence infrastructure.
- [x] The scoring Method fixes exact model/checkpoint/source/featurization identity, and the Binding does not expose a mutable `model_name`, checkpoint path, or device as Workflow data.
- [x] Structure and sequence inputs identify one unambiguous subject Candidate or fail closed before engine execution.
- [x] Every output is a declared Metric/Method/intrinsic Context Observation with exact shape, unit, direction, range, subject grain, and multiplicity.
- [x] Produced Observation capability is visible to the Compiler, so a mismatched Method, Metric, Context, or output scope is rejected before provider invocation.
- [x] Provider-native values are validated without implicit range guessing, silent clamp, or dataset-relative normalization.
- [x] Actual scoring creates truthful Operation and Engine Invocation evidence; post-processing failure cannot turn an engine result into a published Observation or Cache entry.
- [x] Candidate and Observation identities survive Cache replay without copying historical Readiness or Invocation facts.
- [x] CTK, deterministic fixtures, installed-artifact tests, and a required model-backed gate prove the scoring contract and sibling design behavior.

## Executor evidence

- Starting Controller gate: `a42608833d31dce920182a8ec64e07f5a67df263`.
- TDD RED: the initial scoring contract tests failed because the package had no independent v2 score Node, exact Method/Metric, Produced Observation declaration, or typed implementation. Later RED cases proved that non-binary32 Python floats and malformed replayed Observations were accepted before exact native-format validation was added.
- Implementation commits: `a2b4a33`, `af21682`, `ab9a3e4`, and `8dbcd3c`.
- Focused final gate on clean implementation SHA `8dbcd3ce21c43559558606c9c6eb592e16f32f1e`: `uv run --no-sync pytest -q tests/test_proteinmpnn_v2.py tests/test_proteinmpnn.py tests/test_scoring_v2.py tests/test_module_packages_v2.py tests/test_contract_test_kit_v2.py tests/test_workflow_compiler_v2.py tests/test_verification_tiers.py` — `289 passed`.
- Tickets 01–25 v2 joint regression on the same SHA: `uv run --no-sync pytest -q tests/*_v2.py` — `516 passed`.
- Full routine gate on the same SHA: `1205 passed, 52 deselected`; retained result: `verification-results/routine/20260730T002831.360447Z-4103-307b1313edb1ced8`.
- Deterministic acceptance on the same SHA: `10 passed, 5 deselected`; retained result: `verification-results/deterministic-acceptance/20260730T002721.435653Z-3466-1ea460d4ab70d991`.
- Installed-package gate on the same SHA: `3 passed`; retained result: `verification-results/installed-package/20260730T002637.050731Z-3328-f3a117529a2dddbc`.
- Required source-bound model gate used `/Users/sorachan/Documents/ESM-workflow/third_party/ProteinMPNN` and `PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION=8dbcd3ce21c43559558606c9c6eb592e16f32f1e`: `2 passed`, zero skipped. It pins the exact native score, sibling design sequence SHA-256, and parent Candidate lineage. Retained result: `verification-results/proteinmpnn-scoring-v2-heavy-model/20260730T002328.242400Z-99373-01242e1b302dc6e3`.
- CTK coverage is included in the focused gate and proves package discovery, execution, and observation-contract behavior.
- `/code-review` Standards found no documented-standard violation. Spec initially reported two HIGH findings: incomplete binary32-domain validation and insufficiently exact real-model assertions. Commit `8dbcd3c` closed both; final Standards and Spec re-reviews found no remaining or newly introduced CRITICAL/HIGH findings.
- `git diff --check a42608833d31dce920182a8ec64e07f5a67df263..HEAD` passes. The only Core change is the Metric-declared exact-binary32 validation in `core/scoring_v2.py`, which is required to reject malformed Produced Observations during both execution and Cache replay.
- Ticket 26 was not started. Ticket 25 remains `awaiting-controller` until the Controller independently runs the cumulative multi-ticket gate.
