"""Closed Port contract for inserted-loop scientific conclusions."""

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
    INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
)
from .domain import (
    AtomPairDistanceEvidence,
    InsertedLoopCandidateEvidence,
    InsertedLoopEvaluationCollection,
    InsertedLoopThresholds,
    ResidueIdentityCorrespondence,
    atom_pair_distance,
    inserted_loop_gate_results,
)


VERSION = "2.0.0"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _reference(value: object, *, role: str) -> CandidateDataReference:
    if (
        type(value) is not CandidateDataReference
        or value.data_type_id != "protein.structure"
    ):
        raise ValueError(f"inserted-loop {role} reference is invalid")
    return value


def _finite(
    value: object,
    *,
    name: str,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < minimum
        or maximum is not None
        and float(value) > maximum
    ):
        raise ValueError(f"inserted-loop {name} is invalid")
    return float(value)


def _ids(value: object, *, name: str) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not str or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"inserted-loop {name} are invalid")
    return value


def _coordinate(value: object, *, name: str) -> tuple[float, float, float]:
    if type(value) is not tuple or len(value) != 3:
        raise ValueError(f"inserted-loop {name} coordinate is invalid")
    return tuple(
        _finite(item, name=f"{name} coordinate", minimum=-1.0e9) for item in value
    )  # type: ignore[return-value]


def _atom_pair(value: object, *, role: str) -> AtomPairDistanceEvidence:
    if type(value) is not AtomPairDistanceEvidence:
        raise ValueError(f"inserted-loop {role} atom pair is invalid")
    for name in (
        "left_prediction_residue_id",
        "left_structure_residue_id",
        "left_atom_name",
        "right_prediction_residue_id",
        "right_structure_residue_id",
        "right_atom_name",
    ):
        item = getattr(value, name)
        if type(item) is not str or not item:
            raise ValueError(f"inserted-loop {role} atom identity is invalid")
    _coordinate(value.left_coordinate, name=f"{role} left")
    _coordinate(value.right_coordinate, name=f"{role} right")
    distance = _finite(value.distance_angstrom, name=f"{role} distance")
    if not math.isclose(
        distance,
        atom_pair_distance(value),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise ValueError(f"inserted-loop {role} distance contradicts coordinates")
    return value


def _is_hydrogen(atom_name: str) -> bool:
    element = atom_name.lstrip("0123456789")
    return bool(element) and element.startswith("H")


def _thresholds(value: object) -> InsertedLoopThresholds:
    if type(value) is not InsertedLoopThresholds:
        raise ValueError("inserted-loop thresholds have the wrong type")
    fields = (
        "resolved_core_tm_score_minimum",
        "resolved_core_rmsd_angstrom_maximum",
        "counterpart_tm_score_minimum",
        "counterpart_rmsd_angstrom_maximum",
        "resolved_core_mean_plddt_minimum",
        "junction_cn_distance_angstrom_minimum",
        "junction_cn_distance_angstrom_maximum",
        "loop_core_nonbonded_distance_angstrom_minimum",
    )
    for name in fields:
        _finite(getattr(value, name), name=name)
    if (
        value.resolved_core_tm_score_minimum > 1
        or value.counterpart_tm_score_minimum > 1
        or value.resolved_core_mean_plddt_minimum > 100
        or value.junction_cn_distance_angstrom_minimum
        > value.junction_cn_distance_angstrom_maximum
    ):
        raise ValueError("inserted-loop thresholds are inconsistent")
    return value


def _validate_entry(value: object) -> InsertedLoopCandidateEvidence:
    if type(value) is not InsertedLoopCandidateEvidence:
        raise ValueError("inserted-loop evidence entry has the wrong type")
    _reference(value.subject, role="subject")
    _reference(value.reference, role="reference")
    _reference(value.counterpart, role="counterpart")
    if len({value.subject, value.reference, value.counterpart}) != 3:
        raise ValueError("inserted-loop participants must be distinct")
    for name in (
        "prediction_axis_content_digest",
        "structure_axis_content_digest",
        "resolved_core_alignment_content_digest",
        "counterpart_alignment_content_digest",
        "confidence_collection_content_digest",
    ):
        if _DIGEST.fullmatch(getattr(value, name)) is None:
            raise ValueError(f"inserted-loop {name} is invalid")
    if value.method != INSERTED_LOOP_EVALUATION_METHOD_REFERENCE:
        raise ValueError("inserted-loop evaluation Method is not current")
    if value.confidence_method != REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE:
        raise ValueError("inserted-loop confidence Method is not ESMFold2")

    core_ids = _ids(value.resolved_core_residue_ids, name="core residue IDs")
    loop_ids = _ids(value.loop_residue_ids, name="loop residue IDs")
    if set(core_ids) & set(loop_ids):
        raise ValueError("inserted-loop core and loop scopes overlap")
    correspondence = value.prediction_to_structure_correspondence
    if (
        type(correspondence) is not tuple
        or len(correspondence) != len(core_ids) + len(loop_ids)
        or any(
            type(item) is not ResidueIdentityCorrespondence
            or not item.prediction_residue_id
            or not item.structure_residue_id
            for item in correspondence
        )
        or len({item.prediction_residue_id for item in correspondence})
        != len(correspondence)
        or len({item.structure_residue_id for item in correspondence})
        != len(correspondence)
        or {item.prediction_residue_id for item in correspondence}
        != set(core_ids) | set(loop_ids)
    ):
        raise ValueError("inserted-loop residue correspondence is incomplete")
    prediction_order = tuple(item.prediction_residue_id for item in correspondence)
    structure_by_prediction = {
        item.prediction_residue_id: item.structure_residue_id for item in correspondence
    }

    _finite(value.resolved_core_tm_score, name="resolved-core TM-score", maximum=1)
    _finite(value.resolved_core_rmsd_angstrom, name="resolved-core RMSD")
    _finite(value.counterpart_tm_score, name="counterpart TM-score", maximum=1)
    _finite(value.counterpart_rmsd_angstrom, name="counterpart RMSD")
    _finite(
        value.resolved_core_mean_plddt,
        name="resolved-core mean pLDDT",
        maximum=100,
    )
    _finite(value.loop_mean_plddt, name="loop mean pLDDT", maximum=100)
    left = _atom_pair(value.left_junction, role="left junction")
    right = _atom_pair(value.right_junction, role="right junction")
    clash = _atom_pair(
        value.minimum_loop_core_nonbonded_distance,
        role="minimum loop/core distance",
    )
    if (
        left.left_prediction_residue_id not in core_ids
        or left.right_prediction_residue_id != loop_ids[0]
        or left.left_atom_name != "C"
        or left.right_atom_name != "N"
        or right.left_prediction_residue_id != loop_ids[-1]
        or right.right_prediction_residue_id not in core_ids
        or right.left_atom_name != "C"
        or right.right_atom_name != "N"
        or clash.left_prediction_residue_id not in loop_ids
        or clash.right_prediction_residue_id not in core_ids
        or left.left_structure_residue_id
        != structure_by_prediction[left.left_prediction_residue_id]
        or left.right_structure_residue_id
        != structure_by_prediction[left.right_prediction_residue_id]
        or right.left_structure_residue_id
        != structure_by_prediction[right.left_prediction_residue_id]
        or right.right_structure_residue_id
        != structure_by_prediction[right.right_prediction_residue_id]
        or clash.left_structure_residue_id
        != structure_by_prediction[clash.left_prediction_residue_id]
        or clash.right_structure_residue_id
        != structure_by_prediction[clash.right_prediction_residue_id]
        or _is_hydrogen(clash.left_atom_name)
        or _is_hydrogen(clash.right_atom_name)
    ):
        raise ValueError("inserted-loop geometry roles are inconsistent")
    left_index = prediction_order.index(left.left_prediction_residue_id)
    right_index = prediction_order.index(right.right_prediction_residue_id)
    if prediction_order[left_index + 1 : right_index] != loop_ids:
        raise ValueError("inserted-loop junction flanks are not immediate")
    _thresholds(value.thresholds)
    actual = (
        value.resolved_core_passed,
        value.counterpart_passed,
        value.confidence_passed,
        value.junctions_passed,
        value.clash_passed,
        value.accepted,
    )
    if any(type(item) is not bool for item in actual):
        raise ValueError("inserted-loop gate conclusions must be boolean")
    if actual != inserted_loop_gate_results(value):
        raise ValueError("inserted-loop conclusion contradicts its evidence")
    return value


def validate_inserted_loop_evaluation(value: object) -> None:
    if type(value) is not InsertedLoopEvaluationCollection or not value.entries:
        raise ValueError("inserted-loop evidence must be a nonempty collection")
    subjects = []
    for entry in value.entries:
        subjects.append(_validate_entry(entry).subject)
    if len(set(subjects)) != len(subjects):
        raise ValueError("inserted-loop evidence repeats one exact subject")


def _reference_to_wire(value: CandidateDataReference) -> dict[str, object]:
    return _candidate_data_reference_to_canonical(value)


def _method_to_wire(value: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def _atom_to_wire(value: AtomPairDistanceEvidence) -> dict[str, object]:
    return {
        "left_prediction_residue_id": value.left_prediction_residue_id,
        "left_structure_residue_id": value.left_structure_residue_id,
        "left_atom_name": value.left_atom_name,
        "left_coordinate": list(value.left_coordinate),
        "right_prediction_residue_id": value.right_prediction_residue_id,
        "right_structure_residue_id": value.right_structure_residue_id,
        "right_atom_name": value.right_atom_name,
        "right_coordinate": list(value.right_coordinate),
        "distance_angstrom": value.distance_angstrom,
    }


def _thresholds_to_wire(value: InsertedLoopThresholds) -> dict[str, float]:
    return {
        "resolved_core_tm_score_minimum": value.resolved_core_tm_score_minimum,
        "resolved_core_rmsd_angstrom_maximum": (
            value.resolved_core_rmsd_angstrom_maximum
        ),
        "counterpart_tm_score_minimum": value.counterpart_tm_score_minimum,
        "counterpart_rmsd_angstrom_maximum": (value.counterpart_rmsd_angstrom_maximum),
        "resolved_core_mean_plddt_minimum": (value.resolved_core_mean_plddt_minimum),
        "junction_cn_distance_angstrom_minimum": (
            value.junction_cn_distance_angstrom_minimum
        ),
        "junction_cn_distance_angstrom_maximum": (
            value.junction_cn_distance_angstrom_maximum
        ),
        "loop_core_nonbonded_distance_angstrom_minimum": (
            value.loop_core_nonbonded_distance_angstrom_minimum
        ),
    }


def inserted_loop_evaluation_to_wire(
    value: InsertedLoopEvaluationCollection,
) -> object:
    return {
        "schema_version": VERSION,
        "entries": [
            {
                "subject": _reference_to_wire(entry.subject),
                "reference": _reference_to_wire(entry.reference),
                "counterpart": _reference_to_wire(entry.counterpart),
                "prediction_axis_content_digest": (
                    entry.prediction_axis_content_digest
                ),
                "structure_axis_content_digest": entry.structure_axis_content_digest,
                "prediction_to_structure_correspondence": [
                    {
                        "prediction_residue_id": item.prediction_residue_id,
                        "structure_residue_id": item.structure_residue_id,
                    }
                    for item in entry.prediction_to_structure_correspondence
                ],
                "resolved_core_residue_ids": list(entry.resolved_core_residue_ids),
                "loop_residue_ids": list(entry.loop_residue_ids),
                "resolved_core_alignment_content_digest": (
                    entry.resolved_core_alignment_content_digest
                ),
                "counterpart_alignment_content_digest": (
                    entry.counterpart_alignment_content_digest
                ),
                "resolved_core_tm_score": entry.resolved_core_tm_score,
                "resolved_core_rmsd_angstrom": entry.resolved_core_rmsd_angstrom,
                "counterpart_tm_score": entry.counterpart_tm_score,
                "counterpart_rmsd_angstrom": entry.counterpart_rmsd_angstrom,
                "confidence_collection_content_digest": (
                    entry.confidence_collection_content_digest
                ),
                "confidence_method": _method_to_wire(entry.confidence_method),
                "resolved_core_mean_plddt": entry.resolved_core_mean_plddt,
                "loop_mean_plddt": entry.loop_mean_plddt,
                "left_junction": _atom_to_wire(entry.left_junction),
                "right_junction": _atom_to_wire(entry.right_junction),
                "minimum_loop_core_nonbonded_distance": _atom_to_wire(
                    entry.minimum_loop_core_nonbonded_distance
                ),
                "thresholds": _thresholds_to_wire(entry.thresholds),
                "resolved_core_passed": entry.resolved_core_passed,
                "counterpart_passed": entry.counterpart_passed,
                "confidence_passed": entry.confidence_passed,
                "junctions_passed": entry.junctions_passed,
                "clash_passed": entry.clash_passed,
                "accepted": entry.accepted,
                "method": _method_to_wire(entry.method),
            }
            for entry in value.entries
        ],
    }


def _method_from_wire(value: object) -> ExactContractReference:
    return ExactContractReference(**value)


def _float_from_wire(value: object) -> object:
    return float(value) if type(value) is int else value


def _atom_from_wire(value: object) -> AtomPairDistanceEvidence:
    return AtomPairDistanceEvidence(
        **{
            **value,
            "left_coordinate": tuple(
                _float_from_wire(item) for item in value["left_coordinate"]
            ),
            "right_coordinate": tuple(
                _float_from_wire(item) for item in value["right_coordinate"]
            ),
            "distance_angstrom": _float_from_wire(
                value["distance_angstrom"]
            ),
        }
    )


def _entry_from_wire(value: object) -> InsertedLoopCandidateEvidence:
    return InsertedLoopCandidateEvidence(
        **{
            **value,
            "subject": _candidate_data_reference_from_canonical(value["subject"]),
            "reference": _candidate_data_reference_from_canonical(
                value["reference"]
            ),
            "counterpart": _candidate_data_reference_from_canonical(
                value["counterpart"]
            ),
            "prediction_to_structure_correspondence": tuple(
                ResidueIdentityCorrespondence(**item)
                for item in value["prediction_to_structure_correspondence"]
            ),
            "resolved_core_residue_ids": tuple(
                value["resolved_core_residue_ids"]
            ),
            "loop_residue_ids": tuple(value["loop_residue_ids"]),
            "confidence_method": _method_from_wire(value["confidence_method"]),
            "left_junction": _atom_from_wire(value["left_junction"]),
            "right_junction": _atom_from_wire(value["right_junction"]),
            "minimum_loop_core_nonbonded_distance": _atom_from_wire(
                value["minimum_loop_core_nonbonded_distance"]
            ),
            "thresholds": InsertedLoopThresholds(
                **{
                    key: _float_from_wire(item)
                    for key, item in value["thresholds"].items()
                }
            ),
            "resolved_core_tm_score": _float_from_wire(
                value["resolved_core_tm_score"]
            ),
            "resolved_core_rmsd_angstrom": _float_from_wire(
                value["resolved_core_rmsd_angstrom"]
            ),
            "counterpart_tm_score": _float_from_wire(
                value["counterpart_tm_score"]
            ),
            "counterpart_rmsd_angstrom": _float_from_wire(
                value["counterpart_rmsd_angstrom"]
            ),
            "resolved_core_mean_plddt": _float_from_wire(
                value["resolved_core_mean_plddt"]
            ),
            "loop_mean_plddt": _float_from_wire(
                value["loop_mean_plddt"]
            ),
            "method": _method_from_wire(value["method"]),
        }
    )


def inserted_loop_evaluation_from_wire(
    value: object,
) -> InsertedLoopEvaluationCollection:
    if value["schema_version"] != VERSION:
        raise ValueError("inserted-loop evidence schema is not current")
    return InsertedLoopEvaluationCollection(
        **{
            **{
                key: item
                for key, item in value.items()
                if key != "schema_version"
            },
            "entries": tuple(
                _entry_from_wire(item) for item in value["entries"]
            ),
        }
    )


def _candidate_data_references(
    value: object,
    _candidate_data_port_types: object,
) -> tuple[CandidateDataReference, ...]:
    admitted = cast(InsertedLoopEvaluationCollection, value)
    return tuple(
        reference
        for entry in admitted.entries
        for reference in (entry.subject, entry.reference, entry.counterpart)
    )


INSERTED_LOOP_EVALUATION_PORT_TYPE = PortTypeDefinition(
    type_id="structure_comparison.inserted_loop_evaluation",
    version=VERSION,
    validator=BehaviorReference(
        "structure_comparison.inserted_loop_evaluation/validate",
        VERSION,
        {
            "participants": ["subject", "fixed_reference", "counterpart"],
            "prediction_to_structure_correspondence": "exact-residue-order",
            "junction_atoms": ["left-C-N", "right-C-N"],
            "clash_atom_population": "non-hydrogen",
            "excluded_nonbonded_pairs": "direct-junction-C-N-bonds",
            "method_digest": INSERTED_LOOP_EVALUATION_METHOD_REFERENCE.contract_digest,
            "confidence_method": (
                _method_to_wire(REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE)
            ),
        },
    ),
    codec=BehaviorReference(
        "structure_comparison.inserted_loop_evaluation/codec",
        VERSION,
        {"canonicalization": "RFC 8785", "schema_version": VERSION},
    ),
    content_identity=BehaviorReference(
        "structure_comparison.inserted_loop_evaluation/content",
        VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_inserted_loop_evaluation,
    runtime_to_wire=inserted_loop_evaluation_to_wire,
    runtime_from_wire=inserted_loop_evaluation_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_comparison.inserted_loop_evaluation/"
        "candidate_data_projection",
        VERSION,
        {
            "fields": [
                "entries[].subject",
                "entries[].reference",
                "entries[].counterpart",
            ]
        },
    ),
    runtime_candidate_data_projection=_candidate_data_references,
)


__all__ = [
    "INSERTED_LOOP_EVALUATION_PORT_TYPE",
    "inserted_loop_evaluation_from_wire",
    "inserted_loop_evaluation_to_wire",
    "validate_inserted_loop_evaluation",
]
