"""Nominal Port contracts, canonical codecs, and artifact media grammar."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Callable, cast

import rfc8785

from core.operation import EncodedOutputIdentities, ResolvedOutputIdentity
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    validate_candidate_lineage_graph,
    validate_candidate_parent_ids,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ExactPortValueReference,
    ResidueAxisReference,
    validate_canonical_identifier,
)
from datatypes.i_json import FrozenList, freeze_i_json, thaw_i_json
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
    validate_residue_layout,
    validate_residue_map,
)
from datatypes.sequence import ProteinSequence, validate_protein_sequence
from datatypes.structure import ProteinStructure, validate_protein_structure


_MEDIA_TYPE = re.compile(r"^[^\s/]+/[^\s/]+$")


def is_valid_artifact_media_type(value: object) -> bool:
    """Return whether a value uses the public type/subtype media grammar."""
    return (
        isinstance(value, str)
        and len(value) <= 256
        and _MEDIA_TYPE.fullmatch(value) is not None
    )


def _candidate_data_reference_to_canonical(
    value: CandidateDataReference,
) -> dict[str, str]:
    return {
        "candidate_id": value.candidate_id,
        "data_type_id": value.data_type_id,
        "content_digest": value.content_digest,
    }


def _candidate_data_reference_from_canonical(
    value: object,
) -> CandidateDataReference:
    exact_fields = {
        "candidate_id",
        "data_type_id",
        "content_digest",
    }
    if not isinstance(value, Mapping) or set(value) != exact_fields:
        raise ValueError(
            "CandidateDataReference canonical value must contain exact fields"
        )
    return CandidateDataReference(
        candidate_id=cast(str, value["candidate_id"]),
        data_type_id=cast(str, value["data_type_id"]),
        content_digest=cast(str, value["content_digest"]),
    )


def _exact_contract_reference_to_canonical(
    value: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def _exact_port_value_reference_to_canonical(
    value: ExactPortValueReference,
) -> dict[str, object]:
    return {
        "port_type": _exact_contract_reference_to_canonical(value.port_type),
        "content_digest": value.content_digest,
    }


def _residue_axis_reference_to_canonical(
    value: ResidueAxisReference,
) -> dict[str, object]:
    if type(value.source) is CandidateDataReference:
        source_kind = "candidate_data"
        source = _candidate_data_reference_to_canonical(value.source)
    else:
        source_kind = "port_value"
        source = _exact_port_value_reference_to_canonical(value.source)
    return {
        "axis_kind": value.axis_kind,
        "axis_contract": _exact_contract_reference_to_canonical(
            value.axis_contract
        ),
        "axis_content_digest": value.axis_content_digest,
        "source": {
            "kind": source_kind,
            "reference": source,
        },
        "layout": {
            "chain_id": value.layout.chain_id,
            "length": value.layout.length,
            "residue_ids": value.layout.residue_ids,
        },
    }


def _pairwise_participant_to_canonical(
    value: PairwiseParticipant,
) -> dict[str, object]:
    return {
        "role": value.role,
        "candidate": _candidate_data_reference_to_canonical(value.candidate),
    }


def observation_context_canonical(
    value: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    ),
) -> dict[str, object]:
    if type(value) is IntrinsicObservationContext:
        return {"kind": value.kind}
    if type(value) is CalibrationObservationContext:
        return {
            "kind": value.kind,
            "calibration_metric": value.calibration_metric,
            "calibration_value": value.calibration_value,
            "calibration_unit": value.calibration_unit,
            "population_id": value.population_id,
        }
    result: dict[str, object] = {
        "kind": value.kind,
        "subject": _pairwise_participant_to_canonical(value.subject),
        "reference": _pairwise_participant_to_canonical(value.reference),
        "pairing_mode": value.pairing_mode,
        "normalization": value.normalization,
    }
    if value.evidence_content_digest is not None:
        result["evidence_content_digest"] = value.evidence_content_digest
    if value.evidence_method is not None:
        result["evidence_method"] = _exact_contract_reference_to_canonical(
            value.evidence_method
        )
    if value.subject_axis_content_digest is not None:
        result["subject_axis_content_digest"] = (
            value.subject_axis_content_digest
        )
    if value.reference_axis_content_digest is not None:
        result["reference_axis_content_digest"] = (
            value.reference_axis_content_digest
        )
    if value.normalization_length is not None:
        result["normalization_length"] = value.normalization_length
    if value.aligned_atom_count is not None:
        result["aligned_atom_count"] = value.aligned_atom_count
    return result


CONTRACT_NAMESPACE = "protein-workbench-contract/v2"
CATALOG_NAMESPACE = "protein-workbench-catalog/v2"
PORT_VALUE_NAMESPACE = "protein-workbench-port-value/v2"
PORT_TYPE_VERSION = "2.1.0"
CANDIDATE_COLLECTION_PORT_TYPE_VERSION = "4.0.0"
CANDIDATE_PAIRING_PORT_TYPE_VERSION = "4.0.0"
SCORE_COLLECTION_PORT_TYPE_VERSION = "5.0.0"
PROTEIN_SEQUENCE_PORT_TYPE_VERSION = "3.0.0"
PROTEIN_STRUCTURE_PORT_TYPE_VERSION = "4.0.0"
RESIDUE_LAYOUT_PORT_TYPE_VERSION = "3.0.0"
RESIDUE_MAP_PORT_TYPE_VERSION = "3.0.0"
_BUILTIN_PORT_TYPE_VERSIONS = {
    "candidate.collection": CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    "candidate.pairing": CANDIDATE_PAIRING_PORT_TYPE_VERSION,
    "protein.sequence": PROTEIN_SEQUENCE_PORT_TYPE_VERSION,
    "protein.structure": PROTEIN_STRUCTURE_PORT_TYPE_VERSION,
    "residue.layout": RESIDUE_LAYOUT_PORT_TYPE_VERSION,
    "residue.map": RESIDUE_MAP_PORT_TYPE_VERSION,
    "score.collection": SCORE_COLLECTION_PORT_TYPE_VERSION,
}
_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)


class CatalogBuildError(ValueError):
    """A malformed stable contract prevented atomic Catalog publication."""


class UnknownPortTypeError(LookupError):
    """An exact Port Type identity is not present in the FrozenCatalog."""


class ContractResolutionError(LookupError):
    """An exact Contract identity cannot resolve in the active Catalog."""


class UnknownContractError(ContractResolutionError):
    """No active Catalog contract has the requested logical identity."""

    def __init__(
        self,
        contract_kind: str,
        contract_id: str,
        requested_version: str,
    ) -> None:
        self.contract_kind = contract_kind
        self.contract_id = contract_id
        self.requested_version = requested_version
        super().__init__(
            f"Unknown contract {contract_kind}:"
            f"{contract_id}@{requested_version}"
        )


class InactiveContractGenerationError(ContractResolutionError):
    """A logical contract exists, but its requested version is not active."""

    def __init__(
        self,
        contract_kind: str,
        contract_id: str,
        requested_version: str,
        active_version: str,
    ) -> None:
        self.contract_kind = contract_kind
        self.contract_id = contract_id
        self.requested_version = requested_version
        self.active_version = active_version
        super().__init__(
            f"Requested contract version {contract_kind}:"
            f"{contract_id}@{requested_version} is not active; active version is "
            f"{active_version}"
        )


class PortValueError(ValueError):
    """A runtime Port value violates its nominal validation or codec contract."""


def _require_single_active_contract_version(
    identities: Iterable[tuple[str, str, str]],
) -> None:
    active_versions: dict[tuple[str, str], str] = {}
    for contract_kind, contract_id, contract_version in identities:
        logical_identity = (contract_kind, contract_id)
        active_version = active_versions.get(logical_identity)
        if active_version is not None and active_version != contract_version:
            raise CatalogBuildError(
                "multiple active versions for contract "
                f"{contract_kind}:{contract_id}: "
                f"{active_version} and {contract_version}"
            )
        active_versions[logical_identity] = contract_version


def _validate_identifier(value: str, field_name: str) -> None:
    try:
        validate_canonical_identifier(value, field_name)
    except ValueError as error:
        raise CatalogBuildError(
            f"{field_name} must be a versioned identifier"
        ) from error


def _validate_runtime_identifier(value: object, *, path: str) -> None:
    try:
        validate_canonical_identifier(value, path)
    except ValueError as error:
        raise PortValueError(f"{path} must be a canonical identifier") from error


def _validate_version(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not 5 <= len(value) <= 64
        or _SEMANTIC_VERSION.fullmatch(value) is None
    ):
        raise CatalogBuildError(f"{field_name} must be an exact semantic version")


def _validate_i_json(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise CatalogBuildError(
                    f"{path} contains a non-Unicode scalar value"
                ) from error
        return
    if isinstance(value, int):
        if not -_I_JSON_INTEGER_LIMIT <= value <= _I_JSON_INTEGER_LIMIT:
            raise CatalogBuildError(f"{path} is outside the I-JSON integer domain")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CatalogBuildError(f"{path} must not contain NaN or Infinity")
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise CatalogBuildError(f"{path} must not contain negative zero")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_i_json(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogBuildError(f"{path} has a non-string object key")
            _validate_i_json(key, path=f"{path}.<key>")
            _validate_i_json(item, path=f"{path}.{key}")
        return
    raise CatalogBuildError(
        f"{path} contains a value that cannot be represented in I-JSON"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785 canonical UTF-8 after enforcing Workbench I-JSON."""
    projected = thaw_i_json(value)
    _validate_i_json(projected)
    try:
        return rfc8785.dumps(projected)
    except (rfc8785.CanonicalizationError, UnicodeError) as error:
        raise CatalogBuildError("value cannot be canonicalized with RFC 8785") from error


def _freeze_validated_i_json(value: Any) -> Any:
    """Copy already-admitted I-JSON into immutable containers."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _freeze_validated_i_json(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return FrozenList(_freeze_validated_i_json(item) for item in value)
    return value


def canonical_sha256(value: Any) -> str:
    """Return the public digest of canonical I-JSON bytes."""
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


_DATACLASS_BY_TAG = {
    "calibration_observation_context": CalibrationObservationContext,
    "candidate": Candidate,
    "candidate_collection": CandidateCollection,
    "candidate_data_reference": CandidateDataReference,
    "exact_contract_reference": ExactContractReference,
    "exact_port_value_reference": ExactPortValueReference,
    "intrinsic_observation_context": IntrinsicObservationContext,
    "pairwise_candidate_mapping": PairwiseCandidateMapping,
    "pairwise_candidate_match": PairwiseCandidateMatch,
    "pairwise_observation_context": PairwiseObservationContext,
    "pairwise_participant": PairwiseParticipant,
    "protein_sequence": ProteinSequence,
    "protein_structure": ProteinStructure,
    "residue_layout": ResidueLayout,
    "residue_axis_reference": ResidueAxisReference,
    "residue_map": ResidueMap,
    "residue_track": ResidueTrack,
    "score_collection": ScoreCollection,
    "score_observation": ScoreObservation,
}
_TAG_BY_DATACLASS = {
    value_type: tag for tag, value_type in _DATACLASS_BY_TAG.items()
}
_VALUE_TYPE_BY_KIND = {
    "candidate_collection": CandidateCollection,
    "pairwise_candidate_mapping": PairwiseCandidateMapping,
    "protein_sequence": ProteinSequence,
    "protein_structure": ProteinStructure,
    "residue_layout": ResidueLayout,
    "residue_map": ResidueMap,
    "residue_track": ResidueTrack,
    "sasa_residue_track": ResidueTrack,
    "secondary_structure_residue_track": ResidueTrack,
    "score_collection": ScoreCollection,
    "text": str,
}


def _validate_domain_value(value: Any, *, path: str) -> None:
    if type(value) is ResidueAxisReference:
        _validate_domain_value(value.layout, path=f"{path}.layout")
        return

    if type(value) is ProteinSequence:
        try:
            validate_protein_sequence(value, subject=path)
        except (TypeError, ValueError) as error:
            raise PortValueError(str(error)) from error
        return

    if type(value) is ProteinStructure:
        try:
            validate_protein_structure(value, subject=path)
        except (TypeError, ValueError) as error:
            raise PortValueError(str(error)) from error
        return

    if type(value) is ResidueLayout:
        try:
            validate_residue_layout(value, subject=path)
        except (TypeError, ValueError) as error:
            raise PortValueError(str(error)) from error
        return

    if type(value) is ResidueMap:
        try:
            validate_residue_map(value, subject=path)
        except (TypeError, ValueError) as error:
            raise PortValueError(str(error)) from error
        return

    if type(value) is Candidate:
        _validate_runtime_identifier(
            value.candidate_id,
            path=f"{path}.candidate_id",
        )
        if type(value.data) not in (ProteinSequence, ProteinStructure):
            raise PortValueError(f"{path}.data must be a registered Candidate value")
        _validate_domain_value(value.data, path=f"{path}.data")
        try:
            validate_candidate_parent_ids(value, subject=path)
        except ValueError as error:
            raise PortValueError(str(error)) from error
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
            raise PortValueError(
                f"{path}.item_type must name a supported Candidate data type"
            )
        for index, candidate in enumerate(value.items):
            _validate_domain_value(candidate, path=f"{path}.items[{index}]")
            if type(candidate.data) is not expected_candidate_type:
                raise PortValueError(
                    f"{path}.items[{index}].data mismatches "
                    f"item_type {value.item_type}"
                )
        try:
            validate_candidate_lineage_graph(
                tuple(value.items),
                subject=path,
            )
        except ValueError as error:
            raise PortValueError(str(error)) from error
        return

    if type(value) is ExactContractReference:
        if value.contract_kind not in {
            "metric",
            "method",
            "port_type",
            "utility_transform",
        }:
            raise PortValueError(
                f"{path}.contract_kind is not a scientific value contract"
            )
        return

    if type(value) is IntrinsicObservationContext:
        if value.kind != "intrinsic":
            raise PortValueError(
                f"{path} must use the fixed intrinsic Observation Context"
            )
        return

    if type(value) is CalibrationObservationContext:
        if value.kind != "calibration":
            raise PortValueError(
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
            raise PortValueError(
                f"{path}.calibration_value must be a finite canonical number"
            )
        return

    if type(value) is PairwiseParticipant:
        if value.role not in {"subject", "reference"}:
            raise PortValueError(
                f"{path}.role must be subject or reference"
            )
        return

    if type(value) is PairwiseCandidateMapping:
        subjects: set[CandidateDataReference] = set()
        references: set[CandidateDataReference] = set()
        candidate_references: dict[str, CandidateDataReference] = {}
        for entry in value.entries:
            for participant in (entry.subject, entry.reference):
                known_reference = candidate_references.get(
                    participant.candidate_id
                )
                if (
                    known_reference is not None
                    and known_reference != participant
                ):
                    raise PortValueError(
                        f"{path} reuses one Candidate identity with "
                        "conflicting exact data reference"
                    )
                candidate_references[participant.candidate_id] = participant
            if entry.subject in subjects:
                raise PortValueError(
                    f"{path} contains multiple counterparts for one subject"
                )
            subjects.add(entry.subject)
            if entry.reference in references:
                raise PortValueError(
                    f"{path} reuses one counterpart for multiple subjects"
                )
            references.add(entry.reference)
        return

    if type(value) is PairwiseObservationContext:
        if value.kind != "pairwise":
            raise PortValueError(
                f"{path} must use the pairwise Observation Context"
            )
        _validate_domain_value(value.subject, path=f"{path}.subject")
        _validate_domain_value(value.reference, path=f"{path}.reference")
        if value.subject.role != "subject":
            raise PortValueError(f"{path}.subject must use the subject role")
        if value.reference.role != "reference":
            raise PortValueError(
                f"{path}.reference must use the reference role"
            )
        if value.subject.candidate_id == value.reference.candidate_id:
            raise PortValueError(
                f"{path} subject and reference identities must differ"
            )
        if value.pairing_mode not in {
            "fixed_reference",
            "per_subject_counterpart",
        }:
            raise PortValueError(
                f"{path}.pairing_mode is not a controlled pairing mode"
            )
        _validate_runtime_identifier(
            value.normalization,
            path=f"{path}.normalization",
        )
        if value.evidence_method is not None:
            _validate_domain_value(
                value.evidence_method,
                path=f"{path}.evidence_method",
            )
        return

    if type(value) is ScoreObservation:
        if value.metric.contract_kind != "metric":
            raise PortValueError(
                f"{path}.metric must be an exact metric reference"
            )
        if value.method.contract_kind != "method":
            raise PortValueError(
                f"{path}.method must be an exact method reference"
            )
        _validate_domain_value(value.metric, path=f"{path}.metric")
        _validate_domain_value(value.method, path=f"{path}.method")
        _validate_domain_value(value.context, path=f"{path}.context")
        if value.residue_axis is not None:
            _validate_domain_value(
                value.residue_axis,
                path=f"{path}.residue_axis",
            )
        _validate_runtime_identifier(
            value.source_partition,
            path=f"{path}.source_partition",
        )
        if (
            type(value.context) is PairwiseObservationContext
            and value.context.subject.candidate != value.subject
        ):
            raise PortValueError(
                f"{path}.context subject identity must match exact subject"
            )
        return

    if type(value) is ScoreCollection:
        _validate_runtime_identifier(
            value.collection_id,
            path=f"{path}.collection_id",
        )
        for index, score in enumerate(value.entries):
            _validate_domain_value(score, path=f"{path}.entries[{index}]")
        return

def _validate_builtin_semantics(value_kind: str, value: Any) -> None:
    if is_dataclass(value):
        _validate_domain_value(value, path="$.value")

    if value_kind == "sasa_residue_track":
        for index, item in enumerate(value.values):
            if item is value.sentinel:
                continue
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise PortValueError(
                    f"$.value.values[{index}] must be numeric or the sentinel"
                )
            if item < 0:
                raise PortValueError(
                    f"$.value.values[{index}] must be non-negative"
                )

    if value_kind == "secondary_structure_residue_track":
        for index, item in enumerate(value.values):
            if item is value.sentinel:
                continue
            if type(item) is not str:
                raise PortValueError(
                    f"$.value.values[{index}] must be text or the sentinel"
                )
            if len(item) != 1:
                raise PortValueError(
                    f"$.value.values[{index}] must be one canonical code"
                )


def _value_to_wire(value: Any, *, path: str = "$.value") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        try:
            _validate_i_json(value, path=path)
        except CatalogBuildError as error:
            raise PortValueError(str(error)) from error
        return value
    if isinstance(value, (list, FrozenList)):
        return [
            _value_to_wire(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return {
            "$tuple": [
                _value_to_wire(item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
        }
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise PortValueError(
                f"{path} contains a non-string I-JSON object key"
            )
        entries = [
            [
                _value_to_wire(key, path=f"{path}.<key>"),
                _value_to_wire(item, path=f"{path}[{key!r}]"),
            ]
            for key, item in value.items()
        ]
        entries.sort(key=lambda entry: canonical_json_bytes(entry[0]))
        return {"$map": entries}
    if is_dataclass(value) and not isinstance(value, type):
        value_type = type(value)
        tag = _TAG_BY_DATACLASS.get(value_type)
        if tag is None:
            raise PortValueError(
                f"{path} uses an unregistered runtime value class "
                f"{value_type.__name__}"
            )
        return {
            "$dataclass": tag,
            "fields": {
                item.name: _value_to_wire(
                    getattr(value, item.name),
                    path=f"{path}.{item.name}",
                )
                for item in fields(value)
            },
        }
    raise PortValueError(
        f"{path} contains an unsupported runtime value "
        f"{type(value).__name__}"
    )


def _wire_to_value(value: Any, *, path: str = "$.value") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [
            _wire_to_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        raise PortValueError(f"{path} is not a valid canonical value")
    if set(value) == {"$tuple"} and isinstance(value["$tuple"], list):
        return tuple(
            _wire_to_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value["$tuple"])
        )
    if set(value) == {"$map"} and isinstance(value["$map"], list):
        result: dict[Any, Any] = {}
        encoded_keys: list[bytes] = []
        for index, entry in enumerate(value["$map"]):
            if not isinstance(entry, list) or len(entry) != 2:
                raise PortValueError(f"{path}.$map[{index}] must be a key/value pair")
            encoded_keys.append(canonical_json_bytes(entry[0]))
        if encoded_keys != sorted(encoded_keys) or len(encoded_keys) != len(
            set(encoded_keys)
        ):
            raise PortValueError(
                f"{path}.$map entries are not in unique canonical key order"
            )
        for index, entry in enumerate(value["$map"]):
            key = _wire_to_value(entry[0], path=f"{path}.$map[{index}][0]")
            item = _wire_to_value(entry[1], path=f"{path}.$map[{index}][1]")
            if type(key) is not str:
                raise PortValueError(
                    f"{path}.$map contains a non-string I-JSON object key"
                )
            try:
                if key in result:
                    raise PortValueError(
                        f"{path}.$map contains a duplicate decoded key"
                    )
                result[key] = item
            except TypeError as error:
                raise PortValueError(
                    f"{path}.$map contains an unhashable key"
                ) from error
        return result
    if set(value) == {"$dataclass", "fields"}:
        tag = value["$dataclass"]
        raw_fields = value["fields"]
        value_type = _DATACLASS_BY_TAG.get(tag)
        if value_type is None or not isinstance(raw_fields, dict):
            raise PortValueError(f"{path} names an unknown runtime value kind")
        expected_fields = {item.name for item in fields(value_type)}
        if set(raw_fields) != expected_fields:
            raise PortValueError(
                f"{path} fields do not match the complete {tag} contract"
            )
        decoded_fields = {
            name: _wire_to_value(item, path=f"{path}.{name}")
            for name, item in raw_fields.items()
        }
        try:
            return value_type(**decoded_fields)
        except (TypeError, ValueError) as error:
            raise PortValueError(
                f"{path} is not a valid {tag} value: {error}"
            ) from error
    raise PortValueError(f"{path} contains a malformed canonical value object")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PortValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _parse_canonical_json(encoded: bytes) -> Any:
    if not isinstance(encoded, bytes):
        raise PortValueError("canonical codec input must be bytes")
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PortValueError(f"non-I-JSON numeric value {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PortValueError("canonical codec input is malformed UTF-8 JSON") from error
    try:
        canonical = canonical_json_bytes(payload)
    except CatalogBuildError as error:
        raise PortValueError(str(error)) from error
    if encoded != canonical:
        raise PortValueError("codec input is valid JSON but not canonical RFC 8785 bytes")
    return payload


@dataclass(frozen=True, slots=True)
class BehaviorReference:
    """Stable public identity for one private runtime behavior."""

    behavior_id: str
    behavior_version: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier(self.behavior_id, "behavior_id")
        _validate_version(self.behavior_version, "behavior_version")
        parameters = dict(self.parameters)
        canonical_json_bytes(parameters)
        object.__setattr__(self, "parameters", freeze_i_json(parameters))

    def descriptor(self) -> dict[str, Any]:
        """Return the closed public declaration without a Python callable."""
        return {
            "behavior_id": self.behavior_id,
            "behavior_version": self.behavior_version,
            "parameters": thaw_i_json(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class PortTypeDefinition:
    """One exact nominal Port Type and its stable behavior declarations."""

    type_id: str
    version: str
    validator: BehaviorReference
    codec: BehaviorReference
    content_identity: BehaviorReference
    runtime_validator: Callable[[Any], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    runtime_to_wire: Callable[[Any], Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    runtime_from_wire: Callable[[Any], Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    output_identity_materialization: BehaviorReference | None = None
    runtime_output_identity_materializer: Callable[
        [object, EncodedOutputIdentities],
        ResolvedOutputIdentity,
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    output_identity_source_port_types: Mapping[
        str,
        "PortTypeDefinition",
    ] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    candidate_data_projection: BehaviorReference | None = None
    runtime_candidate_data_projection: Callable[
        [Any, Mapping[str, "PortTypeDefinition"]],
        tuple[CandidateDataReference, ...],
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    scientific_axis_projection: BehaviorReference | None = None
    runtime_scientific_axis_projection: Callable[
        [Any], tuple[ResidueAxisReference, ...]
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    observation_method_projection: BehaviorReference | None = None
    runtime_observation_method_projection: Callable[
        [Any], tuple[ExactContractReference, ...]
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _canonical_descriptor: Mapping[str, Any] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_identifier(self.type_id, "type_id")
        _validate_version(self.version, "version")
        source_port_types = dict(self.output_identity_source_port_types)
        for source_role, source_port_type in source_port_types.items():
            _validate_identifier(source_role, "output identity source role")
            if type(source_port_type) is not PortTypeDefinition:
                raise CatalogBuildError(
                    "output identity source roles require exact Port Types"
                )
        object.__setattr__(
            self,
            "output_identity_source_port_types",
            MappingProxyType(source_port_types),
        )
        if (self.output_identity_materialization is None) != (
            self.runtime_output_identity_materializer is None
        ):
            raise CatalogBuildError(
                "output identity materialization declaration and runtime must "
                "be provided together"
            )
        if (self.output_identity_materialization is None) != (
            not source_port_types
        ):
            raise CatalogBuildError(
                "output identity materialization requires exact source Port "
                "roles"
            )
        if (
            self.output_identity_materialization is not None
            and self.validator.parameters.get(
                "output_identity_materialization"
            )
            != self.output_identity_materialization.descriptor()
        ):
            raise CatalogBuildError(
                "output identity materialization must be declared by the "
                "Port validator behavior"
            )
        if (
            self.output_identity_materialization is not None
            and self.output_identity_materialization.parameters.get(
                "source_roles"
            )
            != {
                source_role: source_port_type.reference()
                for source_role, source_port_type in source_port_types.items()
            }
        ):
            raise CatalogBuildError(
                "output identity source roles must declare exact Port references"
            )
        if (self.candidate_data_projection is None) != (
            self.runtime_candidate_data_projection is None
        ):
            raise CatalogBuildError(
                "candidate_data_projection declaration and runtime must be "
                "provided together"
            )
        if (self.scientific_axis_projection is None) != (
            self.runtime_scientific_axis_projection is None
        ):
            raise CatalogBuildError(
                "scientific_axis_projection declaration and runtime must be "
                "provided together"
            )
        if (self.observation_method_projection is None) != (
            self.runtime_observation_method_projection is None
        ):
            raise CatalogBuildError(
                "observation_method_projection declaration and runtime must "
                "be provided together"
            )
        descriptor = self._build_descriptor()
        canonical_json_bytes(descriptor)
        object.__setattr__(
            self,
            "_canonical_descriptor",
            _freeze_validated_i_json(descriptor),
        )

    def _build_descriptor(self) -> dict[str, Any]:
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "port_type",
            "contract_id": self.type_id,
            "contract_version": self.version,
            "validator": self.validator.descriptor(),
            "codec": self.codec.descriptor(),
            "content_identity": self.content_identity.descriptor(),
        }
        if self.candidate_data_projection is not None:
            descriptor["candidate_data_projection"] = (
                self.candidate_data_projection.descriptor()
            )
        if self.scientific_axis_projection is not None:
            descriptor["scientific_axis_projection"] = (
                self.scientific_axis_projection.descriptor()
            )
        if self.observation_method_projection is not None:
            descriptor["observation_method_projection"] = (
                self.observation_method_projection.descriptor()
            )
        return descriptor

    @property
    def canonical_descriptor(self) -> Mapping[str, Any]:
        """Return the immutable scientific descriptor owned by Catalog."""
        return self._canonical_descriptor

    def descriptor(self) -> dict[str, Any]:
        """Copy the canonical scientific descriptor into JSON containers."""
        return cast(dict[str, Any], thaw_i_json(self._canonical_descriptor))

    @property
    def artifact_media_types(self) -> tuple[str, ...] | None:
        """Return the exact media contract for generic artifact publication."""
        declaration = self.validator.parameters.get("artifact_publication")
        if declaration is None:
            return None
        return cast(tuple[str, ...], declaration["media_types"])

    @property
    def descriptor_bytes(self) -> bytes:
        """RFC 8785 canonical UTF-8 descriptor bytes."""
        return canonical_json_bytes(self._canonical_descriptor)

    @property
    def contract_digest(self) -> str:
        """SHA-256 identity of this exact canonical descriptor."""
        return f"sha256:{hashlib.sha256(self.descriptor_bytes).hexdigest()}"

    def reference(self) -> dict[str, Any]:
        """Return the exact reference shape shared by every Catalog contract."""
        return {
            "contract_kind": "port_type",
            "contract_id": self.type_id,
            "contract_version": self.version,
            "contract_digest": self.contract_digest,
        }

    def scientific_axis_references(
        self,
        value: Any,
    ) -> tuple[ResidueAxisReference, ...]:
        """Project nested scalar axes using the nominal Port owner's codec."""
        projector = cast(
            Callable[[Any], tuple[ResidueAxisReference, ...]],
            self.runtime_scientific_axis_projection,
        )
        return tuple(projector(value))

    def candidate_data_references(
        self,
        value: Any,
        candidate_data_port_types: Mapping[str, "PortTypeDefinition"],
    ) -> tuple[CandidateDataReference, ...]:
        """Project exact Candidate data identities using the nominal owner."""
        projector = cast(
            Callable[
                [Any, Mapping[str, "PortTypeDefinition"]],
                tuple[CandidateDataReference, ...],
            ],
            self.runtime_candidate_data_projection,
        )
        return tuple(projector(value, candidate_data_port_types))

    def observation_method_references(
        self,
        value: Any,
    ) -> tuple[ExactContractReference, ...]:
        """Project exact provider Methods using the nominal Port owner."""
        projector = cast(
            Callable[[Any], tuple[ExactContractReference, ...]],
            self.runtime_observation_method_projection,
        )
        return tuple(projector(value))

    def materialize_output_identity(
        self,
        relation: object,
        identities: EncodedOutputIdentities,
    ) -> ResolvedOutputIdentity:
        """Resolve one data-only fresh identity relation for this Port."""
        materializer = self.runtime_output_identity_materializer
        if materializer is None:
            raise PortValueError(
                f"Port Type {self.type_id}@{self.version} does not own output "
                "identity materialization"
            )
        return materializer(relation, identities)

    @property
    def value_kind(self) -> str:
        """Return the stable runtime value kind declared by the validator."""
        return cast(str, self.validator.parameters["accepted_value_kind"])

    def validate_runtime_contract(self) -> None:
        """Require a complete installed runtime behind stable behavior IDs."""
        custom_behaviors = (
            self.runtime_validator,
            self.runtime_to_wire,
            self.runtime_from_wire,
        )
        if any(behavior is not None for behavior in custom_behaviors):
            if not all(behavior is not None for behavior in custom_behaviors):
                raise CatalogBuildError(
                    f"{self.type_id}@{self.version} has an incomplete runtime "
                    "validator/codec declaration"
                )
        else:
            value_kind = self.validator.parameters.get(
                "accepted_value_kind"
            )
            if (
                not isinstance(value_kind, str)
                or value_kind not in _VALUE_TYPE_BY_KIND
            ):
                raise CatalogBuildError(
                    f"{self.type_id}@{self.version} has no installed "
                    "validator behavior"
                )

    def _validate_builtin(self, value: Any) -> None:
        value_kind = self.value_kind
        expected_type = _VALUE_TYPE_BY_KIND[value_kind]
        if type(value) is not expected_type:
            raise PortValueError(
                f"{self.type_id}@{self.version} requires {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
        _validate_builtin_semantics(value_kind, value)

    def validate(self, value: Any) -> None:
        """Validate one complete runtime value through this nominal contract."""
        if self.runtime_validator is not None:
            try:
                self.runtime_validator(value)
            except PortValueError:
                raise
            except (TypeError, ValueError) as error:
                raise PortValueError(
                    f"{self.type_id}@{self.version} rejected its runtime value: "
                    f"{error}"
                ) from error
            return
        self._validate_builtin(value)

    def to_wire(self, value: Any) -> Any:
        """Project one already-admitted value into its nested wire form."""
        if self.runtime_to_wire is not None:
            return self.runtime_to_wire(value)
        return _value_to_wire(value)

    def encode(self, value: Any) -> bytes:
        """Validate and encode one value as canonical RFC 8785 UTF-8 bytes."""
        self.validate(value)
        wire_value = self.to_wire(value)
        try:
            return canonical_json_bytes(
                {
                    "schema_namespace": PORT_VALUE_NAMESPACE,
                    "port_type_id": self.type_id,
                    "port_type_version": self.version,
                    "value": wire_value,
                }
            )
        except CatalogBuildError as error:
            raise PortValueError(str(error)) from error

    def from_wire(self, wire_value: Any) -> Any:
        """Admit one nested wire value through its nominal decoder."""
        if self.runtime_from_wire is not None:
            try:
                value = self.runtime_from_wire(wire_value)
            except PortValueError:
                raise
            except (KeyError, TypeError, ValueError) as error:
                raise PortValueError(
                    f"{self.type_id}@{self.version} could not decode its value: "
                    f"{error}"
                ) from error
        else:
            value = _wire_to_value(wire_value)
        self.validate(value)
        return value

    def decode(self, encoded: bytes) -> Any:
        """Decode canonical bytes, rejecting malformed or non-canonical input."""
        payload = _parse_canonical_json(encoded)
        if not isinstance(payload, dict) or set(payload) != {
            "schema_namespace",
            "port_type_id",
            "port_type_version",
            "value",
        }:
            raise PortValueError("canonical Port value envelope is not closed")
        if payload["schema_namespace"] != PORT_VALUE_NAMESPACE:
            raise PortValueError("canonical Port value namespace does not match")
        if (
            payload["port_type_id"],
            payload["port_type_version"],
        ) != (self.type_id, self.version):
            raise PortValueError("canonical Port value nominal identity does not match")
        return self.from_wire(payload["value"])

    def content_digest(self, value: Any) -> str:
        """Identify validated content by SHA-256 of canonical codec bytes."""
        return f"sha256:{hashlib.sha256(self.encode(value)).hexdigest()}"
