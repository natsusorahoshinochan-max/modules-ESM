---
status: superseded
superseded_by: 0038-candidate-associated-scientific-values-and-deterministic-structure-alignment
---

# Scoring modules: alignment first, then metrics

This historical decision introduced an alignment-first decomposition, but its
built-in `structure.alignment@2.1.0` value was not identity-complete and is no
longer normative. ADR-0038 supersedes its correspondence algorithm, Candidate
association, residue-axis provenance, Method identity, and Metric admission
rules.

The current decomposition still computes alignment once and reuses it, but the
only active comparison evidence contract is the package-owned
`structure_comparison.alignment_evidence@4.0.0`. RMSD and TM-score consume that
exact admitted evidence. The superseded built-in Datatype and Port Type are not
registered and have no compatibility alias or decoder.
