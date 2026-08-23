"""Closed Port contract for a three-structure consistency conclusion."""

from __future__ import annotations

import math
import re
from typing import cast

from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import ExactContractReference
from core.catalog.port_contract import (
    _candidate_data_reference_from_canonical,
    _candidate_data_reference_to_canonical,
)

from .contracts import (
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from .domain import (
    ThreeWayComparisonEdge,
    ThreeWayConfidenceEvidence,
    ThreeWayConsistencyEvidence,
    classify_three_way_consistency,
    comparison_is_close,
    confidence_is_eligible,
)


THREE_WAY_CONSISTENCY_VERSION = "3.0.0"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONFIDENCE_ROLES = ("esmfold2", "simplefold")
_CONFIDENCE_METHODS = (
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
)
_EDGE_IDS = (
    "input_esmfold2",
    "input_simplefold",
    "esmfold2_simplefold",
)
_CLASSIFICATIONS = {
    "three_way_consistent",
    "method_disagreement",
    "input_disagreement",
    "all_disagree",
    "insufficient_evidence",
}


def _validate_reference(
    value: object,
    *,
    data_type_id: str,
    name: str,
) -> None:
    if (
        type(value) is not CandidateDataReference
        or value.data_type_id != data_type_id
    ):
        raise ValueError(f"three-way {name} reference is invalid")


def _validate_confidences(value: ThreeWayConsistencyEvidence) -> None:
    if type(value.confidences) is not tuple:
        raise ValueError("three-way confidences must be one exact tuple")
    subjects = (value.esmfold2_structure, value.simplefold_structure)
    if tuple(item.role for item in value.confidences) != _CONFIDENCE_ROLES:
        raise ValueError("three-way confidence roles are not canonical")
    for item, subject, method in zip(
        value.confidences,
        subjects,
        _CONFIDENCE_METHODS,
        strict=True,
    ):
        if (
            type(item) is not ThreeWayConfidenceEvidence
            or item.subject != subject
            or item.method != method
            or isinstance(item.mean_residue_plddt, bool)
            or not isinstance(item.mean_residue_plddt, (int, float))
            or not math.isfinite(float(item.mean_residue_plddt))
            or not 0 <= float(item.mean_residue_plddt) <= 100
            or type(item.eligible) is not bool
            or item.eligible
            != confidence_is_eligible(float(item.mean_residue_plddt))
            or type(item.score_content_digest) is not str
            or _DIGEST.fullmatch(item.score_content_digest) is None
        ):
            raise ValueError("three-way confidence evidence is not canonical")


def _validate_edge(
    edge: object,
    *,
    participants: tuple[CandidateDataReference, CandidateDataReference],
    residue_count: int,
) -> None:
    if (
        type(edge) is not ThreeWayComparisonEdge
        or (edge.subject, edge.reference) != participants
        or edge.alignment_method != SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
        or edge.tm_score_method != TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE
        or edge.rmsd_method != RMSD_FROM_EVIDENCE_METHOD_REFERENCE
        or type(edge.normalization_length) is not int
        or edge.normalization_length != residue_count
        or type(edge.aligned_atom_count) is not int
        or not 1 <= edge.aligned_atom_count <= residue_count
        or isinstance(edge.tm_score, bool)
        or not isinstance(edge.tm_score, (int, float))
        or not math.isfinite(float(edge.tm_score))
        or not 0 <= float(edge.tm_score) <= 1
        or isinstance(edge.rmsd_angstrom, bool)
        or not isinstance(edge.rmsd_angstrom, (int, float))
        or not math.isfinite(float(edge.rmsd_angstrom))
        or float(edge.rmsd_angstrom) < 0
        or type(edge.close) is not bool
        or edge.close
        != comparison_is_close(
            float(edge.tm_score),
            float(edge.rmsd_angstrom),
        )
    ):
        raise ValueError("three-way comparison edge is not canonical")
    digests = (
        edge.alignment_evidence_content_digest,
        edge.tm_score_content_digest,
        edge.rmsd_content_digest,
    )
    if any(
        type(item) is not str or _DIGEST.fullmatch(item) is None
        for item in digests
    ):
        raise ValueError("three-way comparison edge digest is invalid")


def _validate_edges(value: ThreeWayConsistencyEvidence) -> None:
    if type(value.edges) is not tuple:
        raise ValueError("three-way edges must be one exact tuple")
    if tuple(item.edge_id for item in value.edges) != _EDGE_IDS:
        raise ValueError("three-way edge roles are not canonical")
    participants = (
        (value.esmfold2_structure, value.input_structure),
        (value.simplefold_structure, value.input_structure),
        (value.esmfold2_structure, value.simplefold_structure),
    )
    for edge, pair in zip(value.edges, participants, strict=True):
        _validate_edge(edge, participants=pair, residue_count=value.residue_count)


def validate_three_way_consistency(value: object) -> None:
    """Validate one complete, exact three-structure conclusion."""
    if type(value) is not ThreeWayConsistencyEvidence:
        raise ValueError("three-way consistency evidence has the wrong type")
    _validate_reference(
        value.input_structure,
        data_type_id="protein.structure",
        name="input",
    )
    _validate_reference(
        value.sequence_parent,
        data_type_id="protein.sequence",
        name="sequence",
    )
    _validate_reference(
        value.esmfold2_structure,
        data_type_id="protein.structure",
        name="ESMFold2",
    )
    _validate_reference(
        value.simplefold_structure,
        data_type_id="protein.structure",
        name="SimpleFold",
    )
    if (
        value.classification_method != THREE_WAY_CONSISTENCY_METHOD_REFERENCE
        or value.input_b_factor_semantics
        != "uninterpreted_coordinate_temperature_factor"
        or type(value.residue_count) is not int
        or value.residue_count <= 0
        or value.plddt_threshold != 70.0
        or value.tm_score_threshold != 0.8
        or value.rmsd_threshold_angstrom != 2.5
        or value.classification not in _CLASSIFICATIONS
    ):
        raise ValueError("three-way consistency evidence is not canonical")
    _validate_confidences(value)
    _validate_edges(value)
    expected = classify_three_way_consistency(value.confidences, value.edges)
    if (value.classification, value.subreason) != expected:
        raise ValueError("three-way classification contradicts its evidence")


def _candidate_to_wire(value: CandidateDataReference) -> dict[str, object]:
    return _candidate_data_reference_to_canonical(value)


def _method_to_wire(value: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def three_way_consistency_to_wire(value: ThreeWayConsistencyEvidence) -> object:
    """Encode one admitted conclusion to its closed wire representation."""
    return {
        "schema_version": THREE_WAY_CONSISTENCY_VERSION,
        "input_structure": _candidate_to_wire(value.input_structure),
        "sequence_parent": _candidate_to_wire(value.sequence_parent),
        "esmfold2_structure": _candidate_to_wire(value.esmfold2_structure),
        "simplefold_structure": _candidate_to_wire(value.simplefold_structure),
        "classification_method": _method_to_wire(value.classification_method),
        "input_b_factor_semantics": value.input_b_factor_semantics,
        "residue_count": value.residue_count,
        "thresholds": {
            "mean_residue_plddt": value.plddt_threshold,
            "reference_normalized_tm_score": value.tm_score_threshold,
            "ca_rmsd_angstrom": value.rmsd_threshold_angstrom,
        },
        "confidences": [_confidence_to_wire(item) for item in value.confidences],
        "edges": [_edge_to_wire(item) for item in value.edges],
        "classification": value.classification,
        "subreason": value.subreason,
    }


def _confidence_to_wire(value: ThreeWayConfidenceEvidence) -> dict[str, object]:
    return {
        "role": value.role,
        "subject": _candidate_to_wire(value.subject),
        "method": _method_to_wire(value.method),
        "mean_residue_plddt": value.mean_residue_plddt,
        "eligible": value.eligible,
        "score_content_digest": value.score_content_digest,
    }


def _edge_to_wire(value: ThreeWayComparisonEdge) -> dict[str, object]:
    return {
        "edge_id": value.edge_id,
        "subject": _candidate_to_wire(value.subject),
        "reference": _candidate_to_wire(value.reference),
        "alignment_evidence_content_digest": value.alignment_evidence_content_digest,
        "alignment_method": _method_to_wire(value.alignment_method),
        "normalization_length": value.normalization_length,
        "aligned_atom_count": value.aligned_atom_count,
        "tm_score": value.tm_score,
        "rmsd_angstrom": value.rmsd_angstrom,
        "tm_score_method": _method_to_wire(value.tm_score_method),
        "rmsd_method": _method_to_wire(value.rmsd_method),
        "tm_score_content_digest": value.tm_score_content_digest,
        "rmsd_content_digest": value.rmsd_content_digest,
        "close": value.close,
    }


def _method_from_wire(value: object) -> ExactContractReference:
    return ExactContractReference(**value)


def _confidence_from_wire(value: object) -> ThreeWayConfidenceEvidence:
    return ThreeWayConfidenceEvidence(
        **{
            **value,
            "subject": _candidate_data_reference_from_canonical(value["subject"]),
            "method": _method_from_wire(value["method"]),
        }
    )


def _edge_from_wire(value: object) -> ThreeWayComparisonEdge:
    return ThreeWayComparisonEdge(
        **{
            **value,
            "subject": _candidate_data_reference_from_canonical(value["subject"]),
            "reference": _candidate_data_reference_from_canonical(
                value["reference"]
            ),
            "alignment_method": _method_from_wire(value["alignment_method"]),
            "tm_score_method": _method_from_wire(value["tm_score_method"]),
            "rmsd_method": _method_from_wire(value["rmsd_method"]),
        }
    )


def three_way_consistency_from_wire(value: object) -> ThreeWayConsistencyEvidence:
    """Decode only the active closed wire representation."""
    if value["schema_version"] != THREE_WAY_CONSISTENCY_VERSION:
        raise ValueError("three-way consistency schema version is not active")
    thresholds = value["thresholds"]
    if set(thresholds) != {
        "mean_residue_plddt",
        "reference_normalized_tm_score",
        "ca_rmsd_angstrom",
    }:
        raise ValueError("three-way thresholds are not closed")
    return ThreeWayConsistencyEvidence(
        **{
            **{
                key: item
                for key, item in value.items()
                if key not in {"schema_version", "thresholds"}
            },
            "input_structure": _candidate_data_reference_from_canonical(
                value["input_structure"]
            ),
            "sequence_parent": _candidate_data_reference_from_canonical(
                value["sequence_parent"]
            ),
            "esmfold2_structure": _candidate_data_reference_from_canonical(
                value["esmfold2_structure"]
            ),
            "simplefold_structure": _candidate_data_reference_from_canonical(
                value["simplefold_structure"]
            ),
            "classification_method": _method_from_wire(
                value["classification_method"]
            ),
            "plddt_threshold": thresholds["mean_residue_plddt"],
            "tm_score_threshold": thresholds["reference_normalized_tm_score"],
            "rmsd_threshold_angstrom": thresholds["ca_rmsd_angstrom"],
            "confidences": tuple(
                _confidence_from_wire(item) for item in value["confidences"]
            ),
            "edges": tuple(_edge_from_wire(item) for item in value["edges"]),
        }
    )


def _candidate_data_references(
    value: object,
    _candidate_data_port_types: object,
) -> tuple[CandidateDataReference, ...]:
    admitted = cast(ThreeWayConsistencyEvidence, value)
    return (
        admitted.input_structure,
        admitted.sequence_parent,
        admitted.esmfold2_structure,
        admitted.simplefold_structure,
        *(entry.subject for entry in admitted.confidences),
        *(
            reference
            for edge in admitted.edges
            for reference in (edge.subject, edge.reference)
        ),
    )


THREE_WAY_CONSISTENCY_PORT_TYPE = PortTypeDefinition(
    type_id="structure_comparison.three_way_consistency",
    version=THREE_WAY_CONSISTENCY_VERSION,
    validator=BehaviorReference(
        "structure_comparison.three_way_consistency/validate",
        THREE_WAY_CONSISTENCY_VERSION,
        {
            "participants": ["input", "esmfold2", "simplefold"],
            "confidence_threshold": 70.0,
            "close": {
                "reference_normalized_tm_score_minimum": 0.8,
                "ca_rmsd_angstrom_maximum": 2.5,
            },
            "confidence_method_digests": [
                item.contract_digest for item in _CONFIDENCE_METHODS
            ],
            "classification_method_digest": (
                THREE_WAY_CONSISTENCY_METHOD_REFERENCE.contract_digest
            ),
            "alignment_method_digest": (
                SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE.contract_digest
            ),
            "tm_score_method_digest": (
                TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE.contract_digest
            ),
            "rmsd_method_digest": RMSD_FROM_EVIDENCE_METHOD_REFERENCE.contract_digest,
            "input_b_factor": "uninterpreted-coordinate-field",
        },
    ),
    codec=BehaviorReference(
        "structure_comparison.three_way_consistency/codec",
        THREE_WAY_CONSISTENCY_VERSION,
        {
            "canonicalization": "RFC 8785",
            "schema_version": THREE_WAY_CONSISTENCY_VERSION,
        },
    ),
    content_identity=BehaviorReference(
        "structure_comparison.three_way_consistency/content",
        THREE_WAY_CONSISTENCY_VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_three_way_consistency,
    runtime_to_wire=three_way_consistency_to_wire,
    runtime_from_wire=three_way_consistency_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_comparison.three_way_consistency/"
        "candidate_data_projection",
        THREE_WAY_CONSISTENCY_VERSION,
        {
            "fields": [
                "input_structure",
                "sequence_parent",
                "esmfold2_structure",
                "simplefold_structure",
                "confidences[].subject",
                "edges[].subject",
                "edges[].reference",
            ]
        },
    ),
    runtime_candidate_data_projection=_candidate_data_references,
)
