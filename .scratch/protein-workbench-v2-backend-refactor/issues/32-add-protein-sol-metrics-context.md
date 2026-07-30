# 32 — Add Protein-Sol Metrics and calibration Context

**What to build:** A Workflow can run Protein-Sol and receive separately typed percent-solubility, scaled-solubility, and pI Observations while preserving population-solubility as calibration Context rather than presenting four unrelated fields as one score.

**Blocked by:** 31 — Add SoluProt Methods.

**Status:** awaiting-controller

- [x] The Workbench adapter is based only on the Protein-Sol dependency repository under the agreed external workspace and does not modify vendor code or reuse unrelated surrounding workflow logic.
- [x] Protein-Sol is registered in the existing `solubility` package with exact Method, Binding, preprocessing/source identity, Availability, Readiness, and result-affecting implementation identity.
- [x] Percent-sol, scaled-sol, and pI are independent Metric Definitions with exact units, ranges, directions, granularities, and validation contracts.
- [x] Population-sol is represented as baseline/calibration Context associated with the Method output and is not published as an equivalent per-Candidate score.
- [x] One Method may produce all declared Metrics through a closed Produced Observation set while each Observation retains complete Candidate/Metric/Method/Context identity.
- [x] Adapter normalization follows the verified upstream semantics and never infers scale from field names or values, silently clamps output, or merges values into a generic `score_id`.
- [x] Invalid sequence, missing field, duplicate/conflicting output, non-finite value, range violation, or incomplete calibration Context fails before publication or Cache write.
- [x] Result Identity and Engine Invocation provenance include exact source/preprocessing/model identities, and Cache replay preserves every Metric and Context without replaying inference evidence.
- [x] Golden upstream cases, one-Method/multiple-Metrics tests, CTK, installed discovery, and required local inference gates prove the complete Protein-Sol contract.

## Executor evidence

- Accepted base: `1972b7d8ff0c15ab63bfc60f2f5bf491d63bf740`.
- Implementation commits: `6e0b422` (`feat: add calibrated Protein-Sol
  metrics`), `5df95a3` (`fix: close Protein-Sol review findings`), and
  `51b999f` (`fix: preserve Protein-Sol diagnostic identity`).
- Dependency boundary: the Adapter reads only the locked Protein-Sol sources
  under
  `/Users/sorachan/Documents/ESM-workflow-NEXT/vendor/protein-sol`, validates
  the exact source-file, Bash, and Perl identities, and stages private copies
  for each invocation. A tracked-file diff against the external vendor path
  remained empty.
- Scientific contract: one exact 2017 Method publishes percent-solubility,
  scaled-solubility, and pI as three independent Metrics. The first two retain
  the exact Niwa population calibration Context; pI is intrinsic.
  Population-sol is never emitted as a Candidate score.
- Ticket-focused/cross-slice tests:
  `uv run --no-sync pytest -q tests/test_solubility_v2.py
  tests/test_protein_sol_v2.py tests/test_port_types_v2.py
  tests/test_scoring_v2.py tests/test_public_protocol_v2.py
  tests/test_verification_tiers.py` → `135 passed`.
- Cumulative v2 tests: `uv run --no-sync pytest -q tests/*_v2.py` →
  `630 passed`.
- Required real-provider batch gate:
  `uv run --no-sync python scripts/verify_backend.py
  protein-sol-v2-local-model` → `1 passed`; its two locked upstream cases
  preserve Candidate order and all three Metric/Context values. Retained at
  `verification-results/protein-sol-v2-local-model/20260730T092809.787625Z-18286-92e56a67dcebf6ec`.
- Routine verification: `1321 passed, 56 deselected`; retained at
  `verification-results/routine/20260730T092835.095198Z-18452-22445d7f9d311776`.
- Deterministic acceptance: `10 passed, 5 deselected`; retained at
  `verification-results/deterministic-acceptance/20260730T093407.116479Z-26253-bef0f09875e5c462`.
- Installed-package verification: `3 passed`; retained at
  `verification-results/installed-package/20260730T093517.464886Z-27010-3105369d60dc1e21`.
- Static/package checks: `git diff --check`, compileall, `uv lock --check`,
  `uv pip check`, and a zero-result provider-name search under `core/*.py`
  passed.
- Parallel `/code-review` at exact code HEAD
  `51b999f18da342285339a46434795018fae68023`: Standards PASS and Spec PASS
  after closing generic calibrated Context selection/public protocol support,
  exact scientific feature count, multi-Candidate golden inference, and
  provider-correct diagnostics.
- Handoff boundary: executor work is complete and awaits the Controller-owned
  joint Ticket 01–32 gate; this ticket must not be marked `completed` until
  that cumulative gate passes.
