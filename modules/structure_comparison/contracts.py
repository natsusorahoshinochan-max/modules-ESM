"""Stable Method contracts for resolved-axis structure alignment."""

from __future__ import annotations

from core.catalog.declarations import MethodDefinition
from core.catalog.definition_resource import load_method_definitions
from datatypes.exact_reference import ExactContractReference




def method_reference(method: MethodDefinition) -> ExactContractReference:
    """Return the stable reference carried by scientific evidence."""
    return ExactContractReference(
        contract_kind="method",
        contract_id=method.method_id,
    )


REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE = ExactContractReference(
    contract_kind="method",
    contract_id="folding.fold.esmfold2_fast_biohub_2026_05",
)
LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE = ExactContractReference(
    contract_kind="method",
    contract_id="folding.fold.esmfold2_hf_1ebf0e3",
)
ESMFOLD2_FOLD_METHOD_REFERENCES = (
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    LOCAL_ESMFOLD2_FOLD_METHOD_REFERENCE,
)


SEQUENCE_PRIMARY_AFFINE_METHOD = MethodDefinition(
    method_id="structure_comparison.sequence_primary_affine_svd.method",
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
    featurization_identity={
        "input": "structure_transform.resolved_residue_axis",
        "sequence": "resolved-axis-canonical-sequence",
        "coordinates": "resolved-axis-CA-coordinates",
    },
    scale_contract={
        "coordinate_unit": "angstrom",
        "transform": "subject-to-reference-row-vector",
    },
)


STRUCTURE_FIRST_TM_ALIGN_METHOD = MethodDefinition(
    method_id="structure_comparison.structure_first_tm_align.method",
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
    featurization_identity={
        "input": "structure_transform.resolved_residue_axis",
        "sequence": "CA-admitted-resolved-axis-subsequence",
        "coordinates": "resolved-axis-CA-coordinates",
    },
    scale_contract={
        "coordinate_unit": "angstrom",
        "transform": "subject-to-reference-row-vector",
    },
)


STATIC_METHODS = load_method_definitions(
    __package__,
    "definitions/methods.yaml",
)
_STATIC_METHOD_BY_ID = {
    method.method_id: method
    for method in STATIC_METHODS
}
RMSD_FROM_EVIDENCE_METHOD = _STATIC_METHOD_BY_ID[
    "structure_comparison.rmsd.from_alignment_evidence.method"
]
TM_SCORE_FROM_EVIDENCE_METHOD = _STATIC_METHOD_BY_ID[
    "structure_comparison.tm_score.reference_axis_normalized.method"
]
THREE_WAY_CONSISTENCY_METHOD = _STATIC_METHOD_BY_ID[
    "structure_comparison.three_way_consistency.threshold_graph"
]
INSERTED_LOOP_EVALUATION_METHOD = _STATIC_METHOD_BY_ID[
    "structure_comparison.inserted_loop.exact_evidence_gate"
]

ALIGNMENT_METHODS = (
    SEQUENCE_PRIMARY_AFFINE_METHOD,
    STRUCTURE_FIRST_TM_ALIGN_METHOD,
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
)
