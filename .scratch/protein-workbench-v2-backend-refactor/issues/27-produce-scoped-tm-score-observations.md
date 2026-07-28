# 27 — Produce scoped TM-score Observations

**What to build:** A Workflow can compute single or batch TM-score Observations with standard reference normalization and use separate fixed-reference and per-subject counterpart scopes without cross-matching or ambiguous score IDs.

**Blocked by:** 26 — Consolidate alignment and RMSD.

**Status:** ready-for-agent

- [ ] Single and batch TM-score each have one v2 Node Definition in the existing `structure_comparison` package and consume the explicit alignment evidence contract.
- [ ] TM-score is a declared pairwise Metric with exact Method, canonical range, direction, context roles, and reference-normalization semantics rather than a caller-provided `score_id`.
- [ ] Every Observation identifies the subject Candidate and exact reference Candidate identity/content digest and preserves the alignment and normalization provenance that determined the value.
- [ ] Batch output retains one declared source partition and the exact per-subject pairing cardinality needed by compiler capability analysis and selection.
- [ ] A fixed canonical reference may match every subject only in its declared objective, while each folded ESM-3 subject matches exactly one distinct paired counterpart in the other objective.
- [ ] Collection order, name suffixes, incidental lineage, and first-match behavior cannot determine reference selection.
- [ ] Non-finite scores, missing references, duplicate matches, wrong role orientation, conflicting normalization, or undeclared multiplicity fail closed before Score Collection publication.
- [ ] Deterministic regressions prove standard reference normalization, the two isolated canonical objective scopes, nested engine evidence, and Cache-stable Observation identities.
- [ ] Both Nodes pass CTK, public protocol, and installed-artifact tests without a structure-comparison Core special case.
