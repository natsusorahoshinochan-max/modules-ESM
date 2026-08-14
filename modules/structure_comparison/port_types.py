"""Closed v4 evidence codec for resolved-axis structure alignment."""

from __future__ import annotations

import math
import re
from typing import Any

from core import BehaviorReference, PortTypeDefinition
from datatypes import CandidateDataReference, ExactContractReference

from .contracts import (
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from .domain import (
    AlignmentAtomCorrespondence,
    AlignmentCorrespondencePolicy,
    AlignmentSegmentMapEntry,
    StructureAlignmentEvidence,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
    ThreeWayComparisonEdge,
    ThreeWayConfidenceEvidence,
    ThreeWayConsistencyEvidence,
    classify_three_way_consistency,
)


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_VERSION = "4.0.0"
_METHOD_BY_POLICY = {
    "sequence_primary_affine": SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    "structure_first_tm_align": STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE,
}


def _finite_vector(value: object, *, name: str) -> tuple[float, float, float]:
    if (
        type(value) is not tuple
        or len(value) != 3
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in value
        )
    ):
        raise ValueError(f"{name} must be one finite 3-vector")
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _validate_candidate_reference(value: object, *, role: str) -> None:
    if (
        type(value) is not CandidateDataReference
        or type(value.candidate_id) is not str
        or not value.candidate_id
        or value.data_type_id != "protein.structure"
        or type(value.content_digest) is not str
        or _DIGEST.fullmatch(value.content_digest) is None
    ):
        raise ValueError(f"alignment {role} Candidate reference is invalid")


def _validate_policy(value: object) -> AlignmentCorrespondencePolicy:
    if (
        type(value) is not AlignmentCorrespondencePolicy
        or type(value.kind) is not str
        or value.kind not in _METHOD_BY_POLICY
        or type(value.pin_matching_chain_ids) is not bool
    ):
        raise ValueError("alignment correspondence policy is invalid")
    return value


def _validate_segment_map(
    value: object,
    *,
    policy: AlignmentCorrespondencePolicy,
) -> int:
    if type(value) is not tuple or not value:
        raise ValueError("alignment segment map must be non-empty")
    subject_indices: set[int] = set()
    reference_indices: set[int] = set()
    previous_subject_index = -1
    for entry in value:
        if type(entry) is not AlignmentSegmentMapEntry:
            raise ValueError("alignment segment map entry is invalid")
        sequence_score_valid = (
            type(entry.sequence_score) is int
            if policy.kind == "sequence_primary_affine"
            else entry.sequence_score is None
        )
        if (
            type(entry.subject_segment_index) is not int
            or entry.subject_segment_index < 0
            or type(entry.reference_segment_index) is not int
            or entry.reference_segment_index < 0
            or entry.subject_segment_index <= previous_subject_index
            or type(entry.subject_chain_id) is not str
            or not entry.subject_chain_id
            or type(entry.reference_chain_id) is not str
            or not entry.reference_chain_id
            or not sequence_score_valid
            or type(entry.paired_residue_count) is not int
            or entry.paired_residue_count < 0
            or type(entry.cigar) is not str
            or not entry.cigar
            or set(entry.cigar) - {"M", "D", "I"}
            or entry.cigar.count("M") != entry.paired_residue_count
            or entry.subject_segment_index in subject_indices
            or entry.reference_segment_index in reference_indices
        ):
            raise ValueError("alignment segment map entry is invalid")
        subject_indices.add(entry.subject_segment_index)
        reference_indices.add(entry.reference_segment_index)
        previous_subject_index = entry.subject_segment_index
    if policy.kind == "structure_first_tm_align" and (
        len(value) != 1
        or value[0].subject_segment_index != 0
        or value[0].reference_segment_index != 0
    ):
        raise ValueError("structure-first tm_align segment map is invalid")
    return sum(entry.paired_residue_count for entry in value)


def _validate_transform(value: object) -> StructureAlignmentTransform:
    if (
        type(value) is not StructureAlignmentTransform
        or value.maps_from_role != "subject"
        or value.maps_to_role != "reference"
        or type(value.row_vector_rotation) is not tuple
        or len(value.row_vector_rotation) != 3
    ):
        raise ValueError("alignment transform must map subject to reference")
    rotation = tuple(
        _finite_vector(row, name="rotation row")
        for row in value.row_vector_rotation
    )
    _finite_vector(value.translation, name="translation")
    for left in range(3):
        for right in range(3):
            dot = math.fsum(
                rotation[index][left] * rotation[index][right]
                for index in range(3)
            )
            expected = 1.0 if left == right else 0.0
            if not math.isclose(dot, expected, rel_tol=0.0, abs_tol=1e-8):
                raise ValueError("alignment rotation is not orthonormal")
    determinant = (
        rotation[0][0]
        * (
            rotation[1][1] * rotation[2][2]
            - rotation[1][2] * rotation[2][1]
        )
        - rotation[0][1]
        * (
            rotation[1][0] * rotation[2][2]
            - rotation[1][2] * rotation[2][0]
        )
        + rotation[0][2]
        * (
            rotation[1][0] * rotation[2][1]
            - rotation[1][1] * rotation[2][0]
        )
    )
    if not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-8):
        raise ValueError("alignment rotation must be a proper rotation")
    return value


def _validate_correspondence(
    value: object,
    *,
    transform: StructureAlignmentTransform,
) -> int:
    if type(value) is not tuple or not value:
        raise ValueError("alignment correspondence must be non-empty")
    subject_atoms: set[tuple[str, str]] = set()
    reference_atoms: set[tuple[str, str]] = set()
    for entry in value:
        if (
            type(entry) is not AlignmentAtomCorrespondence
            or type(entry.subject_residue_id) is not str
            or not entry.subject_residue_id
            or type(entry.reference_residue_id) is not str
            or not entry.reference_residue_id
            or entry.subject_atom_name != "CA"
            or entry.reference_atom_name != "CA"
            or isinstance(entry.residual_distance, bool)
            or not isinstance(entry.residual_distance, (int, float))
            or not math.isfinite(float(entry.residual_distance))
            or float(entry.residual_distance) < 0
        ):
            raise ValueError("alignment atom correspondence is invalid")
        subject_coordinate = _finite_vector(
            entry.subject_coordinate,
            name="subject coordinate",
        )
        reference_coordinate = _finite_vector(
            entry.reference_coordinate,
            name="reference coordinate",
        )
        transformed = _finite_vector(
            entry.transformed_subject_coordinate,
            name="transformed subject coordinate",
        )
        expected_transformed = tuple(
            math.fsum(
                subject_coordinate[index]
                * transform.row_vector_rotation[index][axis]
                for index in range(3)
            )
            + transform.translation[axis]
            for axis in range(3)
        )
        if any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-8)
            for actual, expected in zip(
                transformed,
                expected_transformed,
                strict=True,
            )
        ):
            raise ValueError(
                "transformed subject coordinate contradicts the transform"
            )
        expected_distance = math.dist(reference_coordinate, transformed)
        if not math.isclose(
            float(entry.residual_distance),
            expected_distance,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError("alignment residual contradicts its coordinates")
        subject_atom = (entry.subject_residue_id, entry.subject_atom_name)
        reference_atom = (entry.reference_residue_id, entry.reference_atom_name)
        if subject_atom in subject_atoms or reference_atom in reference_atoms:
            raise ValueError("alignment correspondence reuses an atom")
        subject_atoms.add(subject_atom)
        reference_atoms.add(reference_atom)
    return len(value)


def _validate_normalization(
    value: object,
    *,
    correspondence_count: int,
) -> StructureAlignmentNormalization:
    if (
        type(value) is not StructureAlignmentNormalization
        or type(value.subject_axis_residue_count) is not int
        or value.subject_axis_residue_count <= 0
        or type(value.reference_axis_residue_count) is not int
        or value.reference_axis_residue_count <= 0
        or type(value.subject_ca_count) is not int
        or not 0 < value.subject_ca_count <= value.subject_axis_residue_count
        or type(value.reference_ca_count) is not int
        or not 0 < value.reference_ca_count <= value.reference_axis_residue_count
        or type(value.aligned_atom_count) is not int
        or value.aligned_atom_count < 1
        or value.aligned_atom_count != correspondence_count
        or value.aligned_atom_count
        > min(value.subject_ca_count, value.reference_ca_count)
    ):
        raise ValueError("alignment normalization counts are invalid")
    return value


def validate_alignment_evidence(value: object) -> None:
    """Validate one closed v4 evidence value and its derived quantities."""
    if type(value) is not StructureAlignmentEvidence:
        raise ValueError("alignment evidence has the wrong nominal type")
    _validate_candidate_reference(value.subject, role="subject")
    _validate_candidate_reference(value.reference, role="reference")
    if (
        type(value.subject_axis_content_digest) is not str
        or _DIGEST.fullmatch(value.subject_axis_content_digest) is None
        or type(value.reference_axis_content_digest) is not str
        or _DIGEST.fullmatch(value.reference_axis_content_digest) is None
    ):
        raise ValueError("alignment axis content digests are invalid")
    policy = _validate_policy(value.policy)
    sequence_paired_count = _validate_segment_map(
        value.segment_map,
        policy=policy,
    )
    expected_method = _METHOD_BY_POLICY[policy.kind]
    if value.method != expected_method:
        raise ValueError("alignment evidence Method contradicts its policy")
    transform = _validate_transform(value.transform)
    correspondence_count = _validate_correspondence(
        value.correspondence,
        transform=transform,
    )
    normalization = _validate_normalization(
        value.normalization,
        correspondence_count=correspondence_count,
    )
    if (
        normalization.aligned_atom_count > sequence_paired_count
        or sequence_paired_count
        > min(
            normalization.subject_axis_residue_count,
            normalization.reference_axis_residue_count,
        )
        or (
            policy.kind == "structure_first_tm_align"
            and normalization.aligned_atom_count != sequence_paired_count
        )
    ):
        raise ValueError(
            "alignment sequence-paired residue count contradicts its "
            "normalization"
        )
    expected_rmsd = math.sqrt(
        math.fsum(
            float(entry.residual_distance) ** 2
            for entry in value.correspondence
        )
        / normalization.aligned_atom_count
    )
    expected_coverage = normalization.aligned_atom_count / max(
        normalization.subject_axis_residue_count,
        normalization.reference_axis_residue_count,
    )
    for name, actual, expected in (
        ("RMSD", value.rmsd, expected_rmsd),
        ("coverage", value.coverage, expected_coverage),
    ):
        if (
            isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isfinite(float(actual))
            or not math.isclose(
                float(actual),
                expected,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            raise ValueError(f"alignment {name} contradicts its evidence")


def alignment_evidence_to_wire(value: object) -> object:
    """Encode one validated evidence value to the closed v4 wire shape."""
    assert type(value) is StructureAlignmentEvidence
    return {
        "schema_version": EVIDENCE_VERSION,
        "subject": value.subject.to_public(),
        "reference": value.reference.to_public(),
        "subject_axis_content_digest": value.subject_axis_content_digest,
        "reference_axis_content_digest": value.reference_axis_content_digest,
        "segment_map": [
            {
                "subject_segment_index": entry.subject_segment_index,
                "reference_segment_index": entry.reference_segment_index,
                "subject_chain_id": entry.subject_chain_id,
                "reference_chain_id": entry.reference_chain_id,
                "sequence_score": entry.sequence_score,
                "paired_residue_count": entry.paired_residue_count,
                "cigar": entry.cigar,
            }
            for entry in value.segment_map
        ],
        "policy": {
            "kind": value.policy.kind,
            "pin_matching_chain_ids": value.policy.pin_matching_chain_ids,
        },
        "correspondence": [
            {
                "subject_residue_id": entry.subject_residue_id,
                "subject_atom_name": entry.subject_atom_name,
                "subject_coordinate": list(entry.subject_coordinate),
                "reference_residue_id": entry.reference_residue_id,
                "reference_atom_name": entry.reference_atom_name,
                "reference_coordinate": list(entry.reference_coordinate),
                "transformed_subject_coordinate": list(
                    entry.transformed_subject_coordinate
                ),
                "residual_distance": entry.residual_distance,
            }
            for entry in value.correspondence
        ],
        "transform": {
            "maps_from_role": value.transform.maps_from_role,
            "maps_to_role": value.transform.maps_to_role,
            "row_vector_rotation": [
                list(row) for row in value.transform.row_vector_rotation
            ],
            "translation": list(value.transform.translation),
        },
        "normalization": {
            "subject_axis_residue_count": (
                value.normalization.subject_axis_residue_count
            ),
            "reference_axis_residue_count": (
                value.normalization.reference_axis_residue_count
            ),
            "subject_ca_count": value.normalization.subject_ca_count,
            "reference_ca_count": value.normalization.reference_ca_count,
            "aligned_atom_count": value.normalization.aligned_atom_count,
        },
        "rmsd": value.rmsd,
        "coverage": value.coverage,
        "method": {
            "contract_kind": value.method.contract_kind,
            "contract_id": value.method.contract_id,
            "contract_version": value.method.contract_version,
            "contract_digest": value.method.contract_digest,
        },
    }


def _closed(value: object, fields: set[str], *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} wire value is not closed")
    return value


def _tuple3(value: object, *, name: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} wire value is invalid")
    return tuple(value)  # type: ignore[return-value]


def alignment_evidence_from_wire(value: object) -> StructureAlignmentEvidence:
    """Decode only the exact closed v4 evidence wire shape."""
    raw = _closed(
        value,
        {
            "schema_version",
            "subject",
            "reference",
            "subject_axis_content_digest",
            "reference_axis_content_digest",
            "segment_map",
            "policy",
            "correspondence",
            "transform",
            "normalization",
            "rmsd",
            "coverage",
            "method",
        },
        name="alignment evidence",
    )
    if raw["schema_version"] != EVIDENCE_VERSION:
        raise ValueError("alignment evidence schema version is not active")
    subject = _closed(
        raw["subject"],
        {"candidate_id", "data_type_id", "content_digest"},
        name="subject",
    )
    reference = _closed(
        raw["reference"],
        {"candidate_id", "data_type_id", "content_digest"},
        name="reference",
    )
    policy = _closed(
        raw["policy"],
        {"kind", "pin_matching_chain_ids"},
        name="policy",
    )
    transform = _closed(
        raw["transform"],
        {
            "maps_from_role",
            "maps_to_role",
            "row_vector_rotation",
            "translation",
        },
        name="transform",
    )
    normalization = _closed(
        raw["normalization"],
        {
            "subject_axis_residue_count",
            "reference_axis_residue_count",
            "subject_ca_count",
            "reference_ca_count",
            "aligned_atom_count",
        },
        name="normalization",
    )
    method = _closed(
        raw["method"],
        {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        },
        name="method",
    )
    if (
        not isinstance(raw["segment_map"], list)
        or not isinstance(raw["correspondence"], list)
        or not isinstance(transform["row_vector_rotation"], list)
        or len(transform["row_vector_rotation"]) != 3
    ):
        raise ValueError("alignment evidence wire arrays are invalid")
    segment_map = tuple(
        AlignmentSegmentMapEntry(
            **_closed(
                entry,
                {
                    "subject_segment_index",
                    "reference_segment_index",
                    "subject_chain_id",
                    "reference_chain_id",
                    "sequence_score",
                    "paired_residue_count",
                    "cigar",
                },
                name="segment map entry",
            )
        )
        for entry in raw["segment_map"]
    )
    correspondence = tuple(
        AlignmentAtomCorrespondence(
            subject_residue_id=entry["subject_residue_id"],
            subject_atom_name=entry["subject_atom_name"],
            subject_coordinate=_tuple3(
                entry["subject_coordinate"],
                name="subject coordinate",
            ),
            reference_residue_id=entry["reference_residue_id"],
            reference_atom_name=entry["reference_atom_name"],
            reference_coordinate=_tuple3(
                entry["reference_coordinate"],
                name="reference coordinate",
            ),
            transformed_subject_coordinate=_tuple3(
                entry["transformed_subject_coordinate"],
                name="transformed subject coordinate",
            ),
            residual_distance=entry["residual_distance"],
        )
        for raw_entry in raw["correspondence"]
        for entry in (
            _closed(
                raw_entry,
                {
                    "subject_residue_id",
                    "subject_atom_name",
                    "subject_coordinate",
                    "reference_residue_id",
                    "reference_atom_name",
                    "reference_coordinate",
                    "transformed_subject_coordinate",
                    "residual_distance",
                },
                name="correspondence entry",
            ),
        )
    )
    evidence = StructureAlignmentEvidence(
        subject=CandidateDataReference.from_public(subject),
        reference=CandidateDataReference.from_public(reference),
        subject_axis_content_digest=raw["subject_axis_content_digest"],
        reference_axis_content_digest=raw["reference_axis_content_digest"],
        segment_map=segment_map,
        policy=AlignmentCorrespondencePolicy(**policy),
        correspondence=correspondence,
        transform=StructureAlignmentTransform(
            maps_from_role=transform["maps_from_role"],
            maps_to_role=transform["maps_to_role"],
            row_vector_rotation=tuple(
                _tuple3(row, name="rotation row")
                for row in transform["row_vector_rotation"]
            ),
            translation=_tuple3(transform["translation"], name="translation"),
        ),
        normalization=StructureAlignmentNormalization(**normalization),
        rmsd=raw["rmsd"],
        coverage=raw["coverage"],
        method=ExactContractReference(**method),
    )
    return evidence


ALIGNMENT_EVIDENCE_PORT_TYPE = PortTypeDefinition(
    type_id="structure_comparison.alignment_evidence",
    version=EVIDENCE_VERSION,
    validator=BehaviorReference(
        "structure_comparison.alignment_evidence/validate",
        EVIDENCE_VERSION,
        {
            "nominal_type": "StructureAlignmentEvidence",
            "candidate_association": "exact-CandidateDataReference",
            "axis_provenance": "required-content-digests",
            "normalization_counts": [
                "axis_residue_count",
                "CA_count",
                "aligned_atom_count",
            ],
            "segment_paired_residue_count_minimum": 0,
            "global_aligned_atom_count_minimum": 1,
            "accepted_method_digests": [
                reference.contract_digest
                for reference in _METHOD_BY_POLICY.values()
            ],
        },
    ),
    codec=BehaviorReference(
        "structure_comparison.alignment_evidence/codec",
        EVIDENCE_VERSION,
        {
            "canonicalization": "RFC 8785",
            "schema_version": EVIDENCE_VERSION,
        },
    ),
    content_identity=BehaviorReference(
        "structure_comparison.alignment_evidence/content",
        EVIDENCE_VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_alignment_evidence,
    runtime_to_wire=alignment_evidence_to_wire,
    runtime_from_wire=alignment_evidence_from_wire,
)


THREE_WAY_CONSISTENCY_VERSION = "1.0.0"
_CONFIDENCE_ROLES = ("esmfold2", "simplefold")
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


def validate_three_way_consistency(value: object) -> None:
    """Validate the one closed 1PGA three-way scientific conclusion."""
    if type(value) is not ThreeWayConsistencyEvidence:
        raise ValueError("three-way consistency evidence has the wrong type")
    references = (
        value.input_structure,
        value.sequence_parent,
        value.esmfold2_structure,
        value.simplefold_structure,
    )
    if (
        any(type(item) is not CandidateDataReference for item in references)
        or value.input_structure.data_type_id != "protein.structure"
        or value.sequence_parent.data_type_id != "protein.sequence"
        or value.esmfold2_structure.data_type_id != "protein.structure"
        or value.simplefold_structure.data_type_id != "protein.structure"
        or type(value.classification_method) is not ExactContractReference
        or value.classification_method.contract_kind != "method"
        or (
            value.classification_method.contract_id,
            value.classification_method.contract_version,
        )
        != (
            "structure_comparison.1pga_three_way_consistency.threshold_graph",
            "1.0.0",
        )
        or value.input_b_factor_semantics
        != "uninterpreted_coordinate_temperature_factor"
        or value.plddt_threshold != 70.0
        or value.tm_score_threshold != 0.8
        or value.rmsd_threshold_angstrom != 2.5
        or tuple(item.role for item in value.confidences) != _CONFIDENCE_ROLES
        or tuple(item.edge_id for item in value.edges) != _EDGE_IDS
        or value.classification not in _CLASSIFICATIONS
    ):
        raise ValueError("three-way consistency evidence is not canonical")

    expected_confidence_subjects = (
        value.esmfold2_structure,
        value.simplefold_structure,
    )
    expected_confidence_methods = (
        ("folding.fold.esmfold2_fast_biohub_2026_05", "4.0.0"),
        ("folding.fold.simplefold_100m_c7a5570", "4.0.0"),
    )
    for item, subject, method_identity in zip(
        value.confidences,
        expected_confidence_subjects,
        expected_confidence_methods,
        strict=True,
    ):
        if (
            type(item) is not ThreeWayConfidenceEvidence
            or item.subject != subject
            or type(item.method) is not ExactContractReference
            or (item.method.contract_id, item.method.contract_version)
            != method_identity
            or not math.isfinite(item.mean_residue_plddt)
            or not 0 <= item.mean_residue_plddt <= 100
            or item.eligible != (item.mean_residue_plddt >= 70.0)
            or _DIGEST.fullmatch(item.score_content_digest) is None
        ):
            raise ValueError("three-way confidence evidence is not canonical")

    expected_edge_participants = (
        (value.esmfold2_structure, value.input_structure),
        (value.simplefold_structure, value.input_structure),
        (value.esmfold2_structure, value.simplefold_structure),
    )
    for edge, participants in zip(
        value.edges,
        expected_edge_participants,
        strict=True,
    ):
        if (
            type(edge) is not ThreeWayComparisonEdge
            or (edge.subject, edge.reference) != participants
            or edge.alignment_method
            != SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
            or edge.tm_score_method
            != TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE
            or edge.rmsd_method
            != RMSD_FROM_EVIDENCE_METHOD_REFERENCE
            or edge.normalization_length != 75
            or not 1 <= edge.aligned_atom_count <= edge.normalization_length
            or not math.isfinite(edge.tm_score)
            or not 0 <= edge.tm_score <= 1
            or not math.isfinite(edge.rmsd_angstrom)
            or edge.rmsd_angstrom < 0
            or any(
                _DIGEST.fullmatch(digest) is None
                for digest in (
                    edge.alignment_evidence_content_digest,
                    edge.tm_score_content_digest,
                    edge.rmsd_content_digest,
                )
            )
            or edge.close
            != (edge.tm_score >= 0.8 and edge.rmsd_angstrom <= 2.5)
        ):
            raise ValueError("three-way comparison edge is not canonical")
    expected_classification = classify_three_way_consistency(
        value.confidences,
        value.edges,
    )
    if (value.classification, value.subreason) != expected_classification:
        raise ValueError("three-way classification contradicts its evidence")


def _reference_to_wire(value: CandidateDataReference) -> dict[str, object]:
    return value.to_public()


def _method_to_wire(value: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def three_way_consistency_to_wire(value: object) -> object:
    assert type(value) is ThreeWayConsistencyEvidence
    return {
        "schema_version": THREE_WAY_CONSISTENCY_VERSION,
        "input_structure": _reference_to_wire(value.input_structure),
        "sequence_parent": _reference_to_wire(value.sequence_parent),
        "esmfold2_structure": _reference_to_wire(value.esmfold2_structure),
        "simplefold_structure": _reference_to_wire(value.simplefold_structure),
        "classification_method": _method_to_wire(value.classification_method),
        "input_b_factor_semantics": value.input_b_factor_semantics,
        "thresholds": {
            "mean_residue_plddt": value.plddt_threshold,
            "reference_normalized_tm_score": value.tm_score_threshold,
            "ca_rmsd_angstrom": value.rmsd_threshold_angstrom,
        },
        "confidences": [
            {
                "role": item.role,
                "subject": _reference_to_wire(item.subject),
                "method": _method_to_wire(item.method),
                "mean_residue_plddt": item.mean_residue_plddt,
                "eligible": item.eligible,
                "score_content_digest": item.score_content_digest,
            }
            for item in value.confidences
        ],
        "edges": [
            {
                "edge_id": edge.edge_id,
                "subject": _reference_to_wire(edge.subject),
                "reference": _reference_to_wire(edge.reference),
                "alignment_evidence_content_digest": (
                    edge.alignment_evidence_content_digest
                ),
                "alignment_method": _method_to_wire(edge.alignment_method),
                "normalization_length": edge.normalization_length,
                "aligned_atom_count": edge.aligned_atom_count,
                "tm_score": edge.tm_score,
                "rmsd_angstrom": edge.rmsd_angstrom,
                "tm_score_method": _method_to_wire(edge.tm_score_method),
                "rmsd_method": _method_to_wire(edge.rmsd_method),
                "tm_score_content_digest": edge.tm_score_content_digest,
                "rmsd_content_digest": edge.rmsd_content_digest,
                "close": edge.close,
            }
            for edge in value.edges
        ],
        "classification": value.classification,
        "subreason": value.subreason,
    }


def _method_from_wire(value: object) -> ExactContractReference:
    raw = _closed(
        value,
        {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        },
        name="Method reference",
    )
    return ExactContractReference(**raw)


def three_way_consistency_from_wire(value: object) -> object:
    raw = _closed(
        value,
        {
            "schema_version",
            "input_structure",
            "sequence_parent",
            "esmfold2_structure",
            "simplefold_structure",
            "classification_method",
            "input_b_factor_semantics",
            "thresholds",
            "confidences",
            "edges",
            "classification",
            "subreason",
        },
        name="three-way consistency evidence",
    )
    if raw["schema_version"] != THREE_WAY_CONSISTENCY_VERSION:
        raise ValueError("three-way consistency schema version is not active")
    thresholds = _closed(
        raw["thresholds"],
        {
            "mean_residue_plddt",
            "reference_normalized_tm_score",
            "ca_rmsd_angstrom",
        },
        name="three-way thresholds",
    )
    if not isinstance(raw["confidences"], list) or not isinstance(
        raw["edges"], list
    ):
        raise ValueError("three-way evidence collections are invalid")
    result = ThreeWayConsistencyEvidence(
        input_structure=CandidateDataReference.from_public(raw["input_structure"]),
        sequence_parent=CandidateDataReference.from_public(raw["sequence_parent"]),
        esmfold2_structure=CandidateDataReference.from_public(
            raw["esmfold2_structure"]
        ),
        simplefold_structure=CandidateDataReference.from_public(
            raw["simplefold_structure"]
        ),
        classification_method=_method_from_wire(raw["classification_method"]),
        input_b_factor_semantics=raw["input_b_factor_semantics"],
        plddt_threshold=thresholds["mean_residue_plddt"],
        tm_score_threshold=thresholds["reference_normalized_tm_score"],
        rmsd_threshold_angstrom=thresholds["ca_rmsd_angstrom"],
        confidences=tuple(
            ThreeWayConfidenceEvidence(
                role=item["role"],
                subject=CandidateDataReference.from_public(item["subject"]),
                method=_method_from_wire(item["method"]),
                mean_residue_plddt=item["mean_residue_plddt"],
                eligible=item["eligible"],
                score_content_digest=item["score_content_digest"],
            )
            for raw_item in raw["confidences"]
            for item in (
                _closed(
                    raw_item,
                    {
                        "role",
                        "subject",
                        "method",
                        "mean_residue_plddt",
                        "eligible",
                        "score_content_digest",
                    },
                    name="three-way confidence",
                ),
            )
        ),
        edges=tuple(
            ThreeWayComparisonEdge(
                edge_id=item["edge_id"],
                subject=CandidateDataReference.from_public(item["subject"]),
                reference=CandidateDataReference.from_public(item["reference"]),
                alignment_evidence_content_digest=item[
                    "alignment_evidence_content_digest"
                ],
                alignment_method=_method_from_wire(item["alignment_method"]),
                normalization_length=item["normalization_length"],
                aligned_atom_count=item["aligned_atom_count"],
                tm_score=item["tm_score"],
                rmsd_angstrom=item["rmsd_angstrom"],
                tm_score_method=_method_from_wire(item["tm_score_method"]),
                rmsd_method=_method_from_wire(item["rmsd_method"]),
                tm_score_content_digest=item["tm_score_content_digest"],
                rmsd_content_digest=item["rmsd_content_digest"],
                close=item["close"],
            )
            for raw_item in raw["edges"]
            for item in (
                _closed(
                    raw_item,
                    {
                        "edge_id",
                        "subject",
                        "reference",
                        "alignment_evidence_content_digest",
                        "alignment_method",
                        "normalization_length",
                        "aligned_atom_count",
                        "tm_score",
                        "rmsd_angstrom",
                        "tm_score_method",
                        "rmsd_method",
                        "tm_score_content_digest",
                        "rmsd_content_digest",
                        "close",
                    },
                    name="three-way edge",
                ),
            )
        ),
        classification=raw["classification"],
        subreason=raw["subreason"],
    )
    validate_three_way_consistency(result)
    return result


THREE_WAY_CONSISTENCY_PORT_TYPE = PortTypeDefinition(
    type_id="structure_comparison.1pga_three_way_consistency",
    version=THREE_WAY_CONSISTENCY_VERSION,
    validator=BehaviorReference(
        "structure_comparison.1pga_three_way_consistency/validate",
        THREE_WAY_CONSISTENCY_VERSION,
        {
            "participants": ["input", "esmfold2", "simplefold"],
            "confidence_threshold": 70.0,
            "close": {
                "reference_normalized_tm_score_minimum": 0.8,
                "ca_rmsd_angstrom_maximum": 2.5,
            },
            "input_b_factor": "uninterpreted-coordinate-field",
        },
    ),
    codec=BehaviorReference(
        "structure_comparison.1pga_three_way_consistency/codec",
        THREE_WAY_CONSISTENCY_VERSION,
        {"canonicalization": "RFC 8785"},
    ),
    content_identity=BehaviorReference(
        "structure_comparison.1pga_three_way_consistency/content",
        THREE_WAY_CONSISTENCY_VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_three_way_consistency,
    runtime_to_wire=three_way_consistency_to_wire,
    runtime_from_wire=three_way_consistency_from_wire,
)
