"""Private built-in Port value admission and canonical wire codec."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
import json
import math
from typing import Any, cast

from datatypes import i_json as _canonical
from core.catalog import errors as _errors
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    validate_candidate_lineage_graph,
    validate_candidate_parent_ids,
    validate_candidate_data_reference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ExactPortValueReference,
    ResidueAxisReference,
    validate_exact_contract_reference,
    validate_residue_axis_reference,
)
from datatypes.identifier import validate_canonical_identifier
from datatypes.i_json import FrozenList, validate_i_json, i_json_values_equal
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    CandidateRelation,
    CandidateRelationEntry,
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
    validate_pairwise_evidence,
)
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotationTrack,
    ProteinPrompt,
)
from datatypes.residue import (
    CandidateResidueTrack,
    ResidueLayout,
    ResidueTrack,
    validate_residue_layout,
)
from datatypes.sequence import ProteinSequence, validate_protein_sequence
from datatypes.structure import (
    NamedAtomCoordinates,
    ProteinStructure,
    validate_protein_structure,
)


def _validate_runtime_identifier(value: object, *, path: str) -> None:
    try:
        validate_canonical_identifier(value, path)
    except ValueError as error:
        raise _errors.PortValueError(
            f"{path} must be a canonical identifier"
        ) from error


_DATACLASS_BY_TAG = {
    "calibration_observation_context": CalibrationObservationContext,
    "candidate": Candidate,
    "candidate_collection": CandidateCollection,
    "candidate_data_reference": CandidateDataReference,
    "candidate_residue_track": CandidateResidueTrack,
    "exact_contract_reference": ExactContractReference,
    "exact_port_value_reference": ExactPortValueReference,
    "function_annotation": FunctionAnnotation,
    "function_annotation_track": FunctionAnnotationTrack,
    "intrinsic_observation_context": IntrinsicObservationContext,
    "candidate_relation": CandidateRelation,
    "candidate_relation_entry": CandidateRelationEntry,
    "named_atom_coordinates": NamedAtomCoordinates,
    "pairwise_observation_context": PairwiseObservationContext,
    "pairwise_participant": PairwiseParticipant,
    "protein_prompt": ProteinPrompt,
    "protein_sequence": ProteinSequence,
    "protein_structure": ProteinStructure,
    "residue_layout": ResidueLayout,
    "residue_axis_reference": ResidueAxisReference,
    "residue_track": ResidueTrack,
    "score_collection": ScoreCollection,
    "score_observation": ScoreObservation,
}
_TAG_BY_DATACLASS = {
    value_type: tag for tag, value_type in _DATACLASS_BY_TAG.items()
}
_VALUE_TYPE_BY_KIND = {
    "candidate_collection": CandidateCollection,
    "candidate_relation": CandidateRelation,
    "protein_sequence": ProteinSequence,
    "protein_structure": ProteinStructure,
    "residue_layout": ResidueLayout,
    "score_collection": ScoreCollection,
    "text": str,
}


def _validate_domain_value(value: Any, *, path: str) -> None:
    if type(value) is ResidueAxisReference:
        validate_residue_axis_reference(value)
        return

    if type(value) is ProteinSequence:
        try:
            validate_protein_sequence(value, subject=path)
        except (TypeError, ValueError) as error:
            raise _errors.PortValueError(str(error)) from error
        return

    if type(value) is ProteinStructure:
        try:
            validate_protein_structure(value, subject=path)
        except (TypeError, ValueError) as error:
            raise _errors.PortValueError(str(error)) from error
        return

    if type(value) is ResidueLayout:
        try:
            validate_residue_layout(value, subject=path)
        except (TypeError, ValueError) as error:
            raise _errors.PortValueError(str(error)) from error
        return

    if type(value) is Candidate:
        _validate_runtime_identifier(
            value.candidate_id,
            path=f"{path}.candidate_id",
        )
        if type(value.data) not in (ProteinSequence, ProteinStructure):
            raise _errors.PortValueError(
                f"{path}.data must be a registered Candidate value"
            )
        validate_i_json(value.metadata, path=f"{path}.metadata")
        try:
            validate_candidate_parent_ids(value, subject=path)
        except ValueError as error:
            raise _errors.PortValueError(str(error)) from error
        return

    if type(value) is CandidateCollection:
        _validate_runtime_identifier(
            value.collection_id,
            path=f"{path}.collection_id",
        )
        expected_candidate_types = {
            "protein.sequence": ProteinSequence,
            "protein.structure": ProteinStructure,
        }
        expected_candidate_type = expected_candidate_types.get(value.item_type)
        if expected_candidate_type is None:
            raise _errors.PortValueError(
                f"{path}.item_type must name a supported Candidate data type"
            )
        for index, candidate in enumerate(value.items):
            if type(candidate) is not Candidate:
                raise _errors.PortValueError(f"{path}.items must contain Candidates")
            _validate_domain_value(candidate, path=f"{path}.items[{index}]")
            if type(candidate.data) is not expected_candidate_type:
                raise _errors.PortValueError(
                    f"{path}.items[{index}].data mismatches "
                    f"item_type {value.item_type}"
                )
        try:
            validate_candidate_lineage_graph(
                tuple(value.items),
                subject=path,
            )
        except ValueError as error:
            raise _errors.PortValueError(str(error)) from error
        return

    if type(value) is IntrinsicObservationContext:
        if value.kind != "intrinsic":
            raise _errors.PortValueError(
                f"{path} must use the fixed intrinsic Observation Context"
            )
        return

    if type(value) is CalibrationObservationContext:
        if value.kind != "calibration":
            raise _errors.PortValueError(
                f"{path} must use the calibration Observation Context"
            )
        for name in (
            "calibration_metric",
            "calibration_unit",
            "population_id",
        ):
            _validate_runtime_identifier(
                getattr(value, name),
                path=f"{path}.{name}",
            )
        if (
            isinstance(value.calibration_value, bool)
            or not isinstance(value.calibration_value, (int, float))
            or not math.isfinite(float(value.calibration_value))
            or (
                value.calibration_value == 0
                and math.copysign(1.0, value.calibration_value) < 0
            )
        ):
            raise _errors.PortValueError(
                f"{path}.calibration_value must be a finite canonical number"
            )
        return

    if type(value) is CandidateRelation:
        subjects: set[CandidateDataReference] = set()
        candidate_references: dict[str, CandidateDataReference] = {}
        for entry in value.entries:
            if type(entry) is not CandidateRelationEntry:
                raise _errors.PortValueError(f"{path}.entries must contain CandidateRelationEntry")
            for participant in (entry.subject, entry.reference):
                validate_candidate_data_reference(participant)
                known_reference = candidate_references.get(
                    participant.candidate_id
                )
                if (
                    known_reference is not None
                    and known_reference != participant
                ):
                    raise _errors.PortValueError(
                        f"{path} reuses one Candidate identity with "
                        "conflicting exact data reference"
                    )
                candidate_references[participant.candidate_id] = participant
            if entry.subject in subjects:
                raise _errors.PortValueError(
                    f"{path} contains multiple references for one subject"
                )
            subjects.add(entry.subject)
        return

    if type(value) is PairwiseObservationContext:
        validate_pairwise_evidence(value)
        if value.evidence_method is not None:
            validate_exact_contract_reference(value.evidence_method)
        for participant in (value.subject, value.reference):
            if type(participant) is not PairwiseParticipant:
                raise _errors.PortValueError(f"{path} requires exact PairwiseParticipants")
            validate_candidate_data_reference(participant.candidate)
        if value.kind != "pairwise":
            raise _errors.PortValueError(
                f"{path} must use the pairwise Observation Context"
            )
        if value.subject.role != "subject":
            raise _errors.PortValueError(f"{path}.subject must use the subject role")
        if value.reference.role != "reference":
            raise _errors.PortValueError(
                f"{path}.reference must use the reference role"
            )
        if value.subject.candidate_id == value.reference.candidate_id:
            raise _errors.PortValueError(
                f"{path} subject and reference identities must differ"
            )
        if value.pairing_mode not in {
            "fixed_reference",
            "explicit_relation",
        }:
            raise _errors.PortValueError(
                f"{path}.pairing_mode is not a controlled pairing mode"
            )
        _validate_runtime_identifier(
            value.normalization,
            path=f"{path}.normalization",
        )
        return

    if type(value) is ScoreObservation:
        validate_candidate_data_reference(value.subject)
        validate_exact_contract_reference(value.metric)
        validate_exact_contract_reference(value.method)
        validate_i_json(value.value, path=f"{path}.value")
        if type(value.context) not in (IntrinsicObservationContext, CalibrationObservationContext, PairwiseObservationContext):
            raise _errors.PortValueError(f"{path}.context must be an Observation Context")
        if value.metric.contract_kind != "metric":
            raise _errors.PortValueError(
                f"{path}.metric must be an exact metric reference"
            )
        if value.method.contract_kind != "method":
            raise _errors.PortValueError(
                f"{path}.method must be an exact method reference"
            )
        _validate_domain_value(value.context, path=f"{path}.context")
        if value.residue_axis is not None:
            validate_residue_axis_reference(value.residue_axis)
        _validate_runtime_identifier(
            value.source_partition,
            path=f"{path}.source_partition",
        )
        if (
            type(value.context) is PairwiseObservationContext
            and value.context.subject.candidate != value.subject
        ):
            raise _errors.PortValueError(
                f"{path}.context subject identity must match exact subject"
            )
        return

    if type(value) is ScoreCollection:
        _validate_runtime_identifier(
            value.collection_id,
            path=f"{path}.collection_id",
        )
        by_identity: dict[tuple[object, ...], ScoreObservation] = {}
        for index, score in enumerate(value.entries):
            if type(score) is not ScoreObservation:
                raise _errors.PortValueError(f"{path}.entries must contain exact Score Observations")
            _validate_domain_value(score, path=f"{path}.entries[{index}]")
            existing = by_identity.get(score.identity)
            if existing is not None:
                if not i_json_values_equal(existing.value, score.value):
                    raise _errors.PortValueError("Score Collection contains one Observation identity with conflicting values")
                if existing.source_partition != score.source_partition:
                    raise _errors.PortValueError("Score Collection contains an Observation identity partition collision")
            by_identity[score.identity] = score
        return


def _validate_builtin_semantics(value_kind: str, value: Any) -> None:
    _validate_domain_value(value, path="$.value")


def _value_to_wire(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, FrozenList)):
        return [_value_to_wire(item) for item in value]
    if isinstance(value, tuple):
        return {"$tuple": [_value_to_wire(item) for item in value]}
    if isinstance(value, Mapping):
        entries = [
            [key, _value_to_wire(item)]
            for key, item in value.items()
        ]
        entries.sort(key=lambda entry: _canonical.canonical_json_bytes(entry[0]))
        return {"$map": entries}
    return {
        "$dataclass": _TAG_BY_DATACLASS[type(value)],
        "fields": {
            item.name: _value_to_wire(getattr(value, item.name))
            for item in fields(value)
        },
    }


def _wire_to_value(value: Any, *, path: str = "$.value") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [
            _wire_to_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        raise _errors.PortValueError(f"{path} is not a valid canonical value")
    if set(value) == {"$tuple"} and isinstance(value["$tuple"], list):
        return tuple(
            _wire_to_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value["$tuple"])
        )
    if set(value) == {"$map"} and isinstance(value["$map"], list):
        result: dict[str, Any] = {}
        encoded_keys: list[bytes] = []
        for index, entry in enumerate(value["$map"]):
            if not isinstance(entry, list) or len(entry) != 2:
                raise _errors.PortValueError(
                    f"{path}.$map[{index}] must be a key/value pair"
                )
            encoded_keys.append(_canonical.canonical_json_bytes(entry[0]))
            key = _wire_to_value(entry[0], path=f"{path}.$map[{index}][0]")
            item = _wire_to_value(entry[1], path=f"{path}.$map[{index}][1]")
            if type(key) is not str:
                raise _errors.PortValueError(
                    f"{path}.$map contains a non-string I-JSON object key"
                )
            result[key] = item
        if encoded_keys != sorted(encoded_keys) or len(encoded_keys) != len(
            set(encoded_keys)
        ):
            raise _errors.PortValueError(
                f"{path}.$map entries are not in unique canonical key order"
            )
        return result
    if set(value) == {"$dataclass", "fields"}:
        tag = value["$dataclass"]
        raw_fields = value["fields"]
        value_type = _DATACLASS_BY_TAG.get(tag)
        if value_type is None or not isinstance(raw_fields, dict):
            raise _errors.PortValueError(f"{path} names an unknown runtime value kind")
        expected_fields = {item.name for item in fields(value_type)}
        if set(raw_fields) != expected_fields:
            raise _errors.PortValueError(
                f"{path} fields do not match the complete {tag} contract"
            )
        decoded_fields = {
            name: _wire_to_value(item, path=f"{path}.{name}")
            for name, item in raw_fields.items()
        }
        try:
            return value_type(**decoded_fields)
        except (TypeError, ValueError) as error:
            raise _errors.PortValueError(
                f"{path} is not a valid {tag} value: {error}"
            ) from error
    raise _errors.PortValueError(f"{path} contains a malformed canonical value object")


@dataclass(frozen=True, slots=True)
class CandidateCollectionSlice:
    """A window of an existing collection, not a new scientific collection."""

    collection_id: str
    item_type: str
    total: int
    items: tuple[Candidate, ...]


def restore_candidate_collection_slice(
    encoded: bytes, *, offset: int, limit: int,
) -> CandidateCollectionSlice:
    """Restore only the requested Candidates from an already-published value.

    The caller owns the nominal type and request-range checks. JSON parsing
    still covers the whole value; Candidate restoration covers only the slice.
    """
    collection = json.loads(encoded)["value"]["fields"]
    items = collection["items"]
    return CandidateCollectionSlice(
        collection["collection_id"], collection["item_type"], len(items),
        tuple(
            cast(Candidate, _wire_to_value(item))
            for item in items[offset:offset + limit]
        ),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _errors.PortValueError("duplicate JSON object key")
    return result


def _parse_canonical_json(encoded: bytes) -> Any:
    if not isinstance(encoded, bytes):
        raise _errors.PortValueError("canonical codec input must be bytes")
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _errors.PortValueError(
            "canonical codec input is malformed UTF-8 JSON"
        ) from error
    try:
        canonical = _canonical.canonical_json_bytes(payload)
    except ValueError as error:
        raise _errors.PortValueError(str(error)) from error
    if encoded != canonical:
        raise _errors.PortValueError(
            "codec input is valid JSON but not canonical RFC 8785 bytes"
        )
    return payload
