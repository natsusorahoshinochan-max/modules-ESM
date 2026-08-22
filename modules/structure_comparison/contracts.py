"""Exact v3 Method contracts for resolved-axis structure alignment."""

from __future__ import annotations

from importlib.metadata import version

from core.catalog.declarations import (
    CatalogContract,
    MethodDefinition,
)
from datatypes.exact_reference import ExactContractReference


VERSION = "3.0.0"


def method_reference(method: MethodDefinition) -> ExactContractReference:
    """Return the exact reference carried by scientific evidence."""
    digest = CatalogContract(
        contract_kind="method",
        contract_id=method.method_id,
        contract_version=method.version,
        descriptor=method.descriptor_template(),
        dependencies=(),
    ).contract_digest
    return ExactContractReference(
        contract_kind="method",
        contract_id=method.method_id,
        contract_version=method.version,
        contract_digest=digest,
    )


REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE = ExactContractReference(
    contract_kind="method",
    contract_id="folding.fold.esmfold2_fast_biohub_2026_05",
    contract_version="4.0.0",
    contract_digest=(
        "sha256:96ba1f830ca71c844cc1ea506e6b60a3"
        "27b5cf4c17bd0bfc2143b25bf669bee8"
    ),
)


def _reference_descriptor(
    reference: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


SEQUENCE_PRIMARY_AFFINE_METHOD = MethodDefinition(
    method_id="structure_comparison.sequence_primary_affine_svd.method",
    version=VERSION,
    algorithm_identity={
        "name": "resolved-axis-sequence-primary-affine-global-svd",
        "residue_correspondence": {
            "algorithm": "exact-global-affine-dynamic-programming",
            "substitution_matrix": "BLOSUM62",
            "integer_scale": 2,
            "gap_open": -6,
            "gap_extend": -1,
            "terminal_gap_open": -4,
            "terminal_gap_extend": -1,
            "objective_order": [
                "maximum_score",
                "maximum_paired_residue_count",
                "lexicographically_smallest_CIGAR_under_M_D_I",
            ],
            "solver": "iterative-three-state-suffix-table-and-backtrace",
            "gap_state_transitions": "M-to-MDI; D-to-MDI; I-to-MDI",
            "minimum_paired_residue_count": 0,
            "enumerates_alignments": False,
        },
        "segment_assignment": {
            "algorithm": "polynomial-linear-sum-assignment",
            "objective_order": [
                "maximum_total_sequence_score",
                "maximum_total_paired_residue_count",
                "lexicographically_smallest_segment_index_map",
            ],
            "threshold": None,
            "enumerates_assignments": False,
            "lexicographic_map": (
                "subject-segment-index vector of reference-segment-index; "
                "unmatched sentinel sorts after every reference index"
            ),
            "default_chain_id_semantics": "ignored",
            "explicit_chain_pin_policy": (
                "pin_unique-identically-named-segments-before-assignment"
            ),
        },
        "superposition": "one-global-Kabsch-SVD-after-correspondence",
        "atom_selection": "resolved-axis-CA-mask",
        "evidence_counts": {
            "paired_residue_count": "CIGAR-M-count-before-CA-mask",
            "aligned_atom_count": "paired-residues-with-CA-on-both-axes",
            "coverage": (
                "aligned_atom_count/max(subject_axis_residue_count,"
                "reference_axis_residue_count)"
            ),
        },
    },
    model_identity={"kind": "none"},
    checkpoint_identity={"kind": "none"},
    featurization_identity={
        "input": "structure_transform.resolved_residue_axis@4.0.0",
        "sequence": "resolved-axis-canonical-sequence",
        "coordinates": "resolved-axis-CA-coordinates",
    },
    source_identity={
        "kind": "repository-owned",
        "biopython_version": version("biopython"),
        "numpy_version": version("numpy"),
        "scipy_version": version("scipy"),
    },
    scale_contract={
        "coordinate_unit": "angstrom",
        "transform": "subject-to-reference-row-vector",
    },
)


STRUCTURE_FIRST_TM_ALIGN_METHOD = MethodDefinition(
    method_id="structure_comparison.structure_first_tm_align.method",
    version=VERSION,
    algorithm_identity={
        "name": "resolved-axis-single-segment-structure-first-tm-align",
        "segment_requirement": "exactly-one-segment-per-axis",
        "chain_id_semantics": (
            "ignored-by-default; explicit pin records and pins an identical "
            "unique segment name when present"
        ),
        "atom_selection": "resolved-axis-CA-mask",
        "engine_call": (
            "tm_align(subject_coordinates,reference_coordinates,"
            "subject_sequence,reference_sequence,alignment=None)"
        ),
        "seed_alignment": None,
        "fallback": None,
        "transform_direction": "subject-to-reference-row-vector",
        "evidence_counts": {
            "paired_residue_count": "TM-align-CIGAR-M-count",
            "aligned_atom_count": "TM-align-paired-CA-count",
            "coverage": (
                "aligned_atom_count/max(subject_axis_residue_count,"
                "reference_axis_residue_count)"
            ),
        },
    },
    model_identity={"kind": "none"},
    checkpoint_identity={"kind": "none"},
    featurization_identity={
        "input": "structure_transform.resolved_residue_axis@4.0.0",
        "sequence": "CA-admitted-resolved-axis-subsequence",
        "coordinates": "resolved-axis-CA-coordinates",
    },
    source_identity={
        "kind": "repository-owned",
        "engine_api": "tmtools.tm_align",
        "tmtools_version": version("tmtools"),
        "numpy_version": version("numpy"),
    },
    scale_contract={
        "coordinate_unit": "angstrom",
        "transform": "subject-to-reference-row-vector",
    },
)


RMSD_FROM_EVIDENCE_METHOD = MethodDefinition(
    method_id="structure_comparison.rmsd.from_alignment_evidence.method",
    version="4.0.0",
    algorithm_identity={
        "name": "alignment-evidence-rmsd-projection",
        "source": "StructureAlignmentEvidence.rmsd",
        "validation_formula": (
            "sqrt(fsum(residual_distance^2)/aligned_atom_count)"
        ),
        "recomputes_alignment": False,
    },
    model_identity={"kind": "none"},
    checkpoint_identity={"kind": "none"},
    featurization_identity={
        "input": "structure_comparison.alignment_evidence@5.0.0",
        "atom_selection": "evidence-correspondence-CA",
    },
    source_identity={"kind": "repository-owned"},
    scale_contract={
        "unit": "angstrom",
        "normalization": "aligned-CA-mean-square-distance",
    },
)


TM_SCORE_FROM_EVIDENCE_METHOD = MethodDefinition(
    method_id=(
        "structure_comparison.tm_score.reference_axis_normalized.method"
    ),
    version="4.0.0",
    algorithm_identity={
        "name": "alignment-evidence-reference-axis-normalized-tm-score",
        "source": "StructureAlignmentEvidence.residual_distance",
        "formula": (
            "sum(1/(1+(residual_distance/d0)^2))/"
            "reference_axis_residue_count"
        ),
        "d0": (
            "0.5 when reference_axis_residue_count<=15; otherwise "
            "max(0.5,1.24*(reference_axis_residue_count-15)^(1/3)-1.8)"
        ),
        "recomputes_alignment": False,
        "optimization_engine": None,
    },
    model_identity={"kind": "none"},
    checkpoint_identity={"kind": "none"},
    featurization_identity={
        "input": "structure_comparison.alignment_evidence@5.0.0",
        "atom_selection": "evidence-correspondence-CA",
    },
    source_identity={"kind": "repository-owned"},
    scale_contract={
        "unit": "dimensionless",
        "canonical_range": [0, 1],
        "normalization": "exact-reference-axis-residue-count",
    },
)


THREE_WAY_CONSISTENCY_METHOD = MethodDefinition(
    method_id="structure_comparison.three_way_consistency.threshold_graph",
    version="2.0.0",
    algorithm_identity={
        "name": "input-esmfold2-simplefold-threshold-graph",
        "confidence_eligibility": {
            "metric": "structure.plddt.mean_residue@3.0.0",
            "minimum": 70.0,
            "methods": [
                "folding.fold.esmfold2_fast_biohub_2026_05@4.0.0",
                "folding.fold.simplefold_100m_c7a5570@5.0.0",
            ],
        },
        "close": {
            "reference_normalized_tm_score_minimum": 0.8,
            "ca_rmsd_angstrom_maximum": 2.5,
        },
        "edge_roles": [
            "input_esmfold2",
            "input_simplefold",
            "esmfold2_simplefold",
        ],
        "classifications": [
            "three_way_consistent",
            "method_disagreement",
            "input_disagreement",
            "all_disagree",
            "insufficient_evidence",
        ],
        "two_close_edge_subreason": "threshold_boundary_nontransitive",
        "input_b_factor": "uninterpreted-coordinate-field",
    },
    model_identity={"kind": "none"},
    checkpoint_identity={"kind": "none"},
    featurization_identity={
        "candidate_association": "exact-CandidateDataReference",
        "pairing": "explicit-common-parent-sibling-pairing",
        "comparison": "exact-alignment-evidence-provenanced-scores",
    },
    source_identity={"kind": "repository-owned"},
    scale_contract={
        "plddt": "zero-to-100",
        "tm_score": "dimensionless-reference-axis-normalized",
        "rmsd": "angstrom",
    },
)


INSERTED_LOOP_EVALUATION_METHOD = MethodDefinition(
    method_id="structure_comparison.inserted_loop.exact_evidence_gate",
    version="2.0.0",
    algorithm_identity={
        "name": "inserted-loop-exact-evidence-gate",
        "subject_mapping": {
            "prediction_axis": "folding-confidence-prediction-input-axis",
            "structure_axis": "exact-subject-resolved-structure-axis",
            "correspondence": "one-to-one-residue-order",
            "collection_join": "CandidateDataReference",
        },
        "resolved_core": {
            "identity_source": "declared-chain-qualified-residue-identities",
            "comparison": "exact-fixed-reference-alignment-evidence",
            "plddt": (
                "require-all-scoped-values;fsum(scoped-values)/"
                "scoped-residue-count"
            ),
        },
        "inserted_loop": {
            "identity_source": "declared-chain-qualified-residue-identities",
            "plddt": (
                "require-all-scoped-values;fsum(scoped-values)/"
                "scoped-residue-count"
            ),
        },
        "junctions": {
            "left": "left-flank-C-to-first-loop-N",
            "right": "last-loop-C-to-right-flank-N",
            "distance": "Euclidean",
        },
        "loop_core_clash": {
            "atom_population": "resolved-axis-non-hydrogen-named-atoms",
            "distance": "minimum-Euclidean-loop-to-resolved-core",
            "excluded_pairs": "two-direct-junction-peptide-C-N-bonds",
        },
        "counterpart": "exact-per-subject-CandidateDataReference-pairing",
        "confidence_method": _reference_descriptor(
            REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE
        ),
        "missing_scoped_evidence": "fail",
        "acceptance": "logical-and-of-five-declared-gates",
    },
    model_identity={"kind": "none"},
    checkpoint_identity={"kind": "none"},
    featurization_identity={
        "candidate_association": "exact-CandidateDataReference",
        "prediction_axis": (
            "structure_prediction.prediction_residue_axis@2.0.0"
        ),
        "structure_axis": "structure_transform.resolved_residue_axis@4.0.0",
        "alignment_evidence": (
            "structure_comparison.alignment_evidence@5.0.0"
        ),
        "confidence": {
            "metric": "structure.plddt.per_residue@3.0.0",
            "method": _reference_descriptor(
                REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE
            ),
        },
    },
    source_identity={"kind": "repository-owned"},
    scale_contract={
        "tm_score": "dimensionless-reference-axis-normalized",
        "rmsd": "angstrom",
        "plddt": "zero-to-100",
        "junction_distance": "angstrom",
        "nonbonded_distance": "angstrom",
    },
)


ALIGNMENT_METHODS = (
    SEQUENCE_PRIMARY_AFFINE_METHOD,
    STRUCTURE_FIRST_TM_ALIGN_METHOD,
)

METRIC_METHODS = (
    RMSD_FROM_EVIDENCE_METHOD,
    TM_SCORE_FROM_EVIDENCE_METHOD,
)


SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE = method_reference(
    SEQUENCE_PRIMARY_AFFINE_METHOD
)
STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE = method_reference(
    STRUCTURE_FIRST_TM_ALIGN_METHOD
)
RMSD_FROM_EVIDENCE_METHOD_REFERENCE = method_reference(
    RMSD_FROM_EVIDENCE_METHOD
)
TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE = method_reference(
    TM_SCORE_FROM_EVIDENCE_METHOD
)
THREE_WAY_CONSISTENCY_METHOD_REFERENCE = method_reference(
    THREE_WAY_CONSISTENCY_METHOD
)
INSERTED_LOOP_EVALUATION_METHOD_REFERENCE = method_reference(
    INSERTED_LOOP_EVALUATION_METHOD
)
SIMPLEFOLD_FOLD_METHOD_REFERENCE = ExactContractReference(
    contract_kind="method",
    contract_id="folding.fold.simplefold_100m_c7a5570",
    contract_version="5.0.0",
    contract_digest=(
        "sha256:010f5170d530d8b72445dc7a52295233"
        "4853f263c3b6ac9d0f3eb414f6fb2b5e"
    ),
)
