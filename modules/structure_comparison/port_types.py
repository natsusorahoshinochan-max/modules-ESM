"""Closed v4 evidence codec for resolved-axis structure alignment."""

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
)


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_VERSION = "5.0.0"
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
        or value.data_type_id != "protein.structure"
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


def alignment_evidence_to_wire(value: StructureAlignmentEvidence) -> object:
    """Encode one validated evidence value to the closed v4 wire shape."""
    return {
        "schema_version": EVIDENCE_VERSION,
        "subject": _candidate_data_reference_to_canonical(value.subject),
        "reference": _candidate_data_reference_to_canonical(value.reference),
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


def _float_from_wire(value: object) -> object:
    return float(value) if type(value) is int else value


def alignment_evidence_from_wire(value: object) -> StructureAlignmentEvidence:
    """Decode only the exact closed v4 evidence wire shape."""
    if value["schema_version"] != EVIDENCE_VERSION:
        raise ValueError("alignment evidence schema version is not active")
    raw = {key: item for key, item in value.items() if key != "schema_version"}
    transform = value["transform"]
    return StructureAlignmentEvidence(
        **{
            **raw,
            "subject": _candidate_data_reference_from_canonical(value["subject"]),
            "reference": _candidate_data_reference_from_canonical(
                value["reference"]
            ),
            "segment_map": tuple(
                AlignmentSegmentMapEntry(**entry)
                for entry in value["segment_map"]
            ),
            "policy": AlignmentCorrespondencePolicy(**value["policy"]),
            "correspondence": tuple(
                AlignmentAtomCorrespondence(
                    **{
                        **entry,
                        "subject_coordinate": tuple(
                            _float_from_wire(item)
                            for item in entry["subject_coordinate"]
                        ),
                        "reference_coordinate": tuple(
                            _float_from_wire(item)
                            for item in entry["reference_coordinate"]
                        ),
                        "transformed_subject_coordinate": tuple(
                            _float_from_wire(item)
                            for item in entry[
                                "transformed_subject_coordinate"
                            ]
                        ),
                        "residual_distance": _float_from_wire(
                            entry["residual_distance"]
                        ),
                    }
                )
                for entry in value["correspondence"]
            ),
            "transform": StructureAlignmentTransform(
                **{
                    **transform,
                    "row_vector_rotation": tuple(
                        tuple(_float_from_wire(item) for item in row)
                        for row in transform["row_vector_rotation"]
                    ),
                    "translation": tuple(
                        _float_from_wire(item)
                        for item in transform["translation"]
                    ),
                }
            ),
            "normalization": StructureAlignmentNormalization(
                **value["normalization"]
            ),
            "rmsd": _float_from_wire(value["rmsd"]),
            "coverage": _float_from_wire(value["coverage"]),
            "method": ExactContractReference(**value["method"]),
        }
    )


def _candidate_data_references(
    value: object,
    _candidate_data_port_types: object,
) -> tuple[CandidateDataReference, ...]:
    admitted = cast(StructureAlignmentEvidence, value)
    return (admitted.subject, admitted.reference)


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
    candidate_data_projection=BehaviorReference(
        "structure_comparison.alignment_evidence/candidate_data_projection",
        EVIDENCE_VERSION,
        {"fields": ["subject", "reference"]},
    ),
    runtime_candidate_data_projection=_candidate_data_references,
)
