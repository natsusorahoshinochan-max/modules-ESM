# 32 — Add Protein-Sol Metrics and calibration Context

**What to build:** A Workflow can run Protein-Sol and receive separately typed percent-solubility, scaled-solubility, and pI Observations while preserving population-solubility as calibration Context rather than presenting four unrelated fields as one score.

**Blocked by:** 31 — Add SoluProt Methods.

**Status:** ready-for-agent

- [ ] The Workbench adapter is based only on the Protein-Sol dependency repository under the agreed external workspace and does not modify vendor code or reuse unrelated surrounding workflow logic.
- [ ] Protein-Sol is registered in the existing `solubility` package with exact Method, Binding, preprocessing/source identity, Availability, Readiness, and result-affecting implementation identity.
- [ ] Percent-sol, scaled-sol, and pI are independent Metric Definitions with exact units, ranges, directions, granularities, and validation contracts.
- [ ] Population-sol is represented as baseline/calibration Context associated with the Method output and is not published as an equivalent per-Candidate score.
- [ ] One Method may produce all declared Metrics through a closed Produced Observation set while each Observation retains complete Candidate/Metric/Method/Context identity.
- [ ] Adapter normalization follows the verified upstream semantics and never infers scale from field names or values, silently clamps output, or merges values into a generic `score_id`.
- [ ] Invalid sequence, missing field, duplicate/conflicting output, non-finite value, range violation, or incomplete calibration Context fails before publication or Cache write.
- [ ] Result Identity and Engine Invocation provenance include exact source/preprocessing/model identities, and Cache replay preserves every Metric and Context without replaying inference evidence.
- [ ] Golden upstream cases, one-Method/multiple-Metrics tests, CTK, installed discovery, and required local inference gates prove the complete Protein-Sol contract.
