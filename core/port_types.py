"""Canonical nominal Port Type contracts for the v2 FrozenCatalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import re
import types
from types import MappingProxyType
from typing import Any, Callable, Union, get_args, get_origin, get_type_hints

import rfc8785

from core.artifacts import is_valid_artifact_media_type
from core.parameter_contract import (
    ParameterContractDefinitionError,
    validate_parameter_declarations,
)
from datatypes import (
    CalibrationObservationContext,
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    ExactPortValueReference,
    FunctionAnnotations,
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueAxisReference,
    ResidueMap,
    ResidueTrack,
    ScoreCollection,
    ScoreObservation,
    validate_canonical_identifier,
)
from datatypes.i_json import FrozenList, freeze_i_json, thaw_i_json
from datatypes.protein import (
    validate_candidate_lineage_graph,
    validate_candidate_parent_ids,
    validate_protein_sequence,
    validate_protein_structure,
    validate_residue_layout,
    validate_residue_map,
)


CONTRACT_NAMESPACE = "protein-workbench-contract/v2"
CATALOG_NAMESPACE = "protein-workbench-catalog/v2"
PORT_VALUE_NAMESPACE = "protein-workbench-port-value/v2"
PORT_TYPE_VERSION = "2.1.0"
CANDIDATE_COLLECTION_PORT_TYPE_VERSION = "3.0.0"
CANDIDATE_PAIRING_PORT_TYPE_VERSION = "3.0.0"
SCORE_COLLECTION_PORT_TYPE_VERSION = "4.0.0"
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
    "function_annotations": FunctionAnnotations,
    "intrinsic_observation_context": IntrinsicObservationContext,
    "pairwise_candidate_mapping": PairwiseCandidateMapping,
    "pairwise_candidate_match": PairwiseCandidateMatch,
    "pairwise_observation_context": PairwiseObservationContext,
    "pairwise_participant": PairwiseParticipant,
    "protein_prompt": ProteinPrompt,
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
    "function_annotations": FunctionAnnotations,
    "protein_prompt": ProteinPrompt,
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


def _require_runtime_type(
    value: Any,
    expected: Any,
    *,
    path: str,
) -> None:
    if expected is Any or expected is object:
        _value_to_wire(value, path=path)
        return

    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin in (Union, types.UnionType):
        exact_dataclass_type = next(
            (
                alternative
                for alternative in arguments
                if isinstance(alternative, type)
                and is_dataclass(alternative)
                and type(value) is alternative
            ),
            None,
        )
        if exact_dataclass_type is not None:
            _require_runtime_type(
                value,
                exact_dataclass_type,
                path=path,
            )
            return
        failures: list[PortValueError] = []
        for alternative in arguments:
            try:
                _require_runtime_type(value, alternative, path=path)
            except PortValueError as error:
                failures.append(error)
            else:
                return
        raise PortValueError(
            f"{path} does not match any declared runtime value type"
        ) from failures[0]

    if expected is type(None):
        if value is not None:
            raise PortValueError(f"{path} must be null")
        return

    if origin is list or expected is list:
        if type(value) is not list:
            raise PortValueError(f"{path} must be a list")
        item_type = arguments[0] if arguments else Any
        for index, item in enumerate(value):
            _require_runtime_type(item, item_type, path=f"{path}[{index}]")
        return

    if origin in (dict, Mapping) or expected in (dict, Mapping):
        if not isinstance(value, Mapping):
            raise PortValueError(f"{path} must be an object mapping")
        key_type, item_type = arguments if arguments else (Any, Any)
        for key, item in value.items():
            _require_runtime_type(key, key_type, path=f"{path}.<key>")
            _require_runtime_type(item, item_type, path=f"{path}[{key!r}]")
        return

    if origin is tuple or expected is tuple:
        if not isinstance(value, tuple):
            raise PortValueError(f"{path} must be a tuple")
        if not arguments:
            for index, item in enumerate(value):
                _value_to_wire(item, path=f"{path}[{index}]")
            return
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            for index, item in enumerate(value):
                _require_runtime_type(
                    item,
                    arguments[0],
                    path=f"{path}[{index}]",
                )
            return
        if arguments and len(value) != len(arguments):
            raise PortValueError(
                f"{path} must be a {len(arguments)}-item tuple"
            )
        for index, (item, item_type) in enumerate(zip(value, arguments, strict=True)):
            _require_runtime_type(item, item_type, path=f"{path}[{index}]")
        return

    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PortValueError(f"{path} must be numeric")
        _value_to_wire(value, path=path)
        return

    if expected is int:
        if type(value) is not int:
            raise PortValueError(f"{path} must be an integer")
        _value_to_wire(value, path=path)
        return

    if expected in (str, bool):
        if type(value) is not expected:
            raise PortValueError(f"{path} must be {expected.__name__}")
        _value_to_wire(value, path=path)
        return

    if isinstance(expected, type) and is_dataclass(expected):
        if type(value) is not expected:
            raise PortValueError(f"{path} must be {expected.__name__}")
        _validate_dataclass_value(value, path=path)
        return

    raise PortValueError(f"{path} uses an unsupported runtime type declaration")


def _validate_dataclass_value(value: Any, *, path: str) -> None:
    annotations = get_type_hints(type(value))
    for item in fields(value):
        _require_runtime_type(
            getattr(value, item.name),
            annotations[item.name],
            path=f"{path}.{item.name}",
        )


def _validate_domain_value(value: Any, *, path: str) -> None:
    if type(value) is CandidateDataReference:
        for field_name in ("candidate_id", "data_type_id"):
            _validate_runtime_identifier(
                getattr(value, field_name),
                path=f"{path}.{field_name}",
            )
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            value.content_digest,
        ) is None:
            raise PortValueError(
                f"{path}.content_digest must be an exact SHA-256 digest"
            )
        return

    if type(value) is ExactPortValueReference:
        _validate_domain_value(value.port_type, path=f"{path}.port_type")
        if value.port_type.contract_kind != "port_type":
            raise PortValueError(
                f"{path}.port_type must be an exact Port Type reference"
            )
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", value.content_digest
        ) is None:
            raise PortValueError(
                f"{path}.content_digest must be an exact SHA-256 digest"
            )
        return

    if type(value) is ResidueAxisReference:
        if value.axis_kind not in {"resolved_structure", "prediction_input"}:
            raise PortValueError(f"{path}.axis_kind is not a closed axis kind")
        _validate_domain_value(
            value.axis_contract,
            path=f"{path}.axis_contract",
        )
        if value.axis_contract.contract_kind != "port_type":
            raise PortValueError(
                f"{path}.axis_contract must be an exact Port Type reference"
            )
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", value.axis_content_digest
        ) is None:
            raise PortValueError(
                f"{path}.axis_content_digest must be an exact SHA-256 digest"
            )
        _validate_domain_value(value.source, path=f"{path}.source")
        _validate_domain_value(value.layout, path=f"{path}.layout")
        if (
            value.axis_kind == "resolved_structure"
            and (
                type(value.source) is not CandidateDataReference
                or value.source.data_type_id != "protein.structure"
            )
        ):
            raise PortValueError(
                f"{path}.source must be an exact structure Candidate reference"
            )
        if (
            value.axis_kind == "prediction_input"
            and type(value.source)
            not in {CandidateDataReference, ExactPortValueReference}
        ):
            raise PortValueError(
                f"{path}.source must be an exact Candidate or input Port "
                "value reference"
            )
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

    if type(value) is FunctionAnnotations:
        expected_fields = {"label", "start", "end"}
        for index, annotation in enumerate(value.annotations):
            annotation_path = f"{path}.annotations[{index}]"
            if set(annotation) != expected_fields:
                raise PortValueError(
                    f"{annotation_path} must contain label, start, and end"
                )
            if type(annotation["label"]) is not str or not annotation["label"]:
                raise PortValueError(f"{annotation_path}.label must be non-empty text")
            if (
                type(annotation["start"]) is not int
                or type(annotation["end"]) is not int
                or annotation["start"] < 0
                or annotation["end"] < annotation["start"]
            ):
                raise PortValueError(
                    f"{annotation_path} range must be ordered non-negative integers"
                )
        return

    if type(value) is ProteinPrompt:
        if value.target_layout is not None:
            _validate_domain_value(
                value.target_layout,
                path=f"{path}.target_layout",
            )
            expected_length = value.target_layout.length
            for field_name in (
                "sequence_track",
                "structure_track",
                "structure_visibility_track",
                "secondary_structure_track",
                "sasa_track",
            ):
                track = getattr(value, field_name)
                if track is not None and len(track.values) != expected_length:
                    raise PortValueError(
                        f"{path}.{field_name} length must match target_layout"
                    )
            for field_name in ("sequence_track", "secondary_structure_track"):
                track = getattr(value, field_name)
                if track is None:
                    continue
                for index, item in enumerate(track.values):
                    if item is track.sentinel:
                        continue
                    if type(item) is not str or len(item) != 1:
                        raise PortValueError(
                            f"{path}.{field_name}.values[{index}] "
                            "must be one canonical code or the sentinel"
                        )
            visibility = value.structure_visibility_track
            if visibility is not None and any(
                item is not visibility.sentinel and type(item) is not bool
                for item in visibility.values
            ):
                raise PortValueError(
                    f"{path}.structure_visibility_track values must be "
                    "boolean or the sentinel"
                )
            sasa = value.sasa_track
            if sasa is not None:
                for index, item in enumerate(sasa.values):
                    if item is sasa.sentinel:
                        continue
                    if (
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or item < 0
                    ):
                        raise PortValueError(
                            f"{path}.sasa_track.values[{index}] "
                            "must be non-negative numeric or the sentinel"
                        )
        _validate_domain_value(
            value.function_annotations,
            path=f"{path}.function_annotations",
        )
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
        _validate_runtime_identifier(
            value.contract_id,
            path=f"{path}.contract_id",
        )
        if (
            type(value.contract_version) is not str
            or not 5 <= len(value.contract_version) <= 64
            or _SEMANTIC_VERSION.fullmatch(value.contract_version) is None
        ):
            raise PortValueError(
                f"{path}.contract_version must be an exact semantic version"
            )
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value.contract_digest) is None:
            raise PortValueError(
                f"{path}.contract_digest must be an exact SHA-256 digest"
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
        _validate_domain_value(value.candidate, path=f"{path}.candidate")
        return

    if type(value) is PairwiseCandidateMatch:
        _validate_domain_value(value.subject, path=f"{path}.subject")
        _validate_domain_value(value.reference, path=f"{path}.reference")
        return

    if type(value) is PairwiseCandidateMapping:
        subjects: set[CandidateDataReference] = set()
        references: set[CandidateDataReference] = set()
        candidate_references: dict[str, CandidateDataReference] = {}
        for index, entry in enumerate(value.entries):
            _validate_domain_value(
                entry,
                path=f"{path}.entries[{index}]",
            )
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
        _validate_domain_value(value.subject, path=f"{path}.subject")
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
            if type(score) is not ScoreObservation:
                raise PortValueError(
                    f"{path}.entries must contain exact Score Observations"
                )
            _validate_domain_value(score, path=f"{path}.entries[{index}]")
        _deduplicated_score_entries(value, path=path)
        return

def _validate_builtin_semantics(value_kind: str, value: Any) -> None:
    if is_dataclass(value):
        _validate_dataclass_value(value, path="$.value")
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
    if type(value) is ScoreCollection:
        value = ScoreCollection(
            collection_id=value.collection_id,
            entries=_deduplicated_score_entries(value, path=path),
        )
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


def _deduplicated_score_entries(
    collection: ScoreCollection,
    *,
    path: str,
) -> list[ScoreObservation]:
    deduplicated: list[ScoreObservation] = []
    typed_by_identity: dict[
        tuple[object, ...],
        tuple[bytes, str],
    ] = {}
    for index, score in enumerate(collection.entries):
        if type(score) is not ScoreObservation:
            raise PortValueError(
                f"{path}.entries must contain exact Score Observations"
            )
        encoded_value = canonical_json_bytes(
            _value_to_wire(
                score.value,
                path=f"{path}.entries[{index}].value",
            )
        )
        identity = score.identity
        existing = typed_by_identity.get(identity)
        if existing is not None:
            existing_value, existing_partition = existing
            if existing_value != encoded_value:
                raise PortValueError(
                    f"{path}.entries contains one Observation identity "
                    "with conflicting values"
                )
            if existing_partition != score.source_partition:
                raise PortValueError(
                    f"{path}.entries contains an Observation identity "
                    "partition collision"
                )
            continue
        typed_by_identity[identity] = (
            encoded_value,
            score.source_partition,
        )
        deduplicated.append(score)
    return deduplicated


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

    def __post_init__(self) -> None:
        _validate_identifier(self.type_id, "type_id")
        _validate_version(self.version, "version")
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
        canonical_json_bytes(self.descriptor())

    def descriptor(self) -> dict[str, Any]:
        """Return the canonical closed descriptor used for contract identity."""
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "port_type",
            "contract_id": self.type_id,
            "contract_version": self.version,
            "validator": self.validator.descriptor(),
            "codec": self.codec.descriptor(),
            "content_identity": self.content_identity.descriptor(),
        }
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
    def artifact_media_types(self) -> tuple[str, ...] | None:
        """Return the exact media contract for generic artifact publication."""
        declaration = self.validator.parameters.get("artifact_publication")
        if declaration is None:
            return None
        if (
            not isinstance(declaration, Mapping)
            or set(declaration) != {"media_types"}
            or not isinstance(declaration["media_types"], tuple)
        ):
            raise CatalogBuildError(
                f"{self.type_id}@{self.version} has an invalid artifact "
                "publication declaration"
            )
        media_types = tuple(declaration["media_types"])
        if (
            not media_types
            or tuple(sorted(set(media_types))) != media_types
            or any(
                not is_valid_artifact_media_type(media_type)
                for media_type in media_types
            )
        ):
            raise CatalogBuildError(
                f"{self.type_id}@{self.version} has invalid artifact media types"
            )
        return media_types

    @property
    def descriptor_bytes(self) -> bytes:
        """RFC 8785 canonical UTF-8 descriptor bytes."""
        return canonical_json_bytes(self.descriptor())

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

    def public_contract(self) -> dict[str, Any]:
        """Return the public protocol representation."""
        return {
            "reference": self.reference(),
            "descriptor": self.descriptor(),
        }

    def scientific_axis_references(
        self,
        value: Any,
    ) -> tuple[ResidueAxisReference, ...]:
        """Project nested scalar axes using the nominal Port owner's codec."""
        projector = self.runtime_scientific_axis_projection
        if projector is None:
            raise PortValueError(
                f"Port Type {self.type_id}@{self.version} does not own a "
                "scientific-axis projection"
            )
        references = tuple(projector(value))
        if any(type(item) is not ResidueAxisReference for item in references):
            raise PortValueError(
                "scientific-axis projection returned a non-axis reference"
            )
        if len(references) != len(set(references)):
            raise PortValueError(
                "scientific-axis projection returned duplicate exact axes"
            )
        return references

    def observation_method_references(
        self,
        value: Any,
    ) -> tuple[ExactContractReference, ...]:
        """Project exact provider Methods using the nominal Port owner."""
        projector = self.runtime_observation_method_projection
        if projector is None:
            raise PortValueError(
                f"Port Type {self.type_id}@{self.version} does not own an "
                "Observation Method projection"
            )
        references = tuple(projector(value))
        if any(
            type(item) is not ExactContractReference
            or item.contract_kind != "method"
            for item in references
        ):
            raise PortValueError(
                "Observation Method projection returned a non-Method reference"
            )
        if len(references) != len(set(references)):
            raise PortValueError(
                "Observation Method projection returned duplicate exact Methods"
            )
        return references

    @property
    def value_kind(self) -> str:
        """Return the stable runtime value kind declared by the validator."""
        value_kind = self.validator.parameters.get("accepted_value_kind")
        if not isinstance(value_kind, str) or value_kind not in _VALUE_TYPE_BY_KIND:
            raise PortValueError(
                f"{self.type_id}@{self.version} has no installed validator behavior"
            )
        return value_kind

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
            return
        try:
            self.value_kind
        except PortValueError as error:
            raise CatalogBuildError(str(error)) from error

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
        expected_type = _VALUE_TYPE_BY_KIND[self.value_kind]
        if type(value) is not expected_type:
            raise PortValueError(
                f"{self.type_id}@{self.version} requires "
                f"{expected_type.__name__}, got {type(value).__name__}"
            )
        _validate_builtin_semantics(self.value_kind, value)
        _value_to_wire(value)

    def encode(self, value: Any) -> bytes:
        """Validate and encode one value as canonical RFC 8785 UTF-8 bytes."""
        self.validate(value)
        if self.runtime_to_wire is not None:
            try:
                wire_value = self.runtime_to_wire(value)
            except PortValueError:
                raise
            except (TypeError, ValueError) as error:
                raise PortValueError(
                    f"{self.type_id}@{self.version} could not encode its value: "
                    f"{error}"
                ) from error
            try:
                canonical_json_bytes(wire_value)
            except CatalogBuildError as error:
                raise PortValueError(str(error)) from error
        else:
            wire_value = _value_to_wire(value)
        return canonical_json_bytes(
            {
                "schema_namespace": PORT_VALUE_NAMESPACE,
                "port_type_id": self.type_id,
                "port_type_version": self.version,
                "value": wire_value,
            }
        )

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
        if self.runtime_from_wire is not None:
            try:
                value = self.runtime_from_wire(payload["value"])
            except PortValueError:
                raise
            except (TypeError, ValueError) as error:
                raise PortValueError(
                    f"{self.type_id}@{self.version} could not decode its value: "
                    f"{error}"
                ) from error
        else:
            value = _wire_to_value(payload["value"])
        self.validate(value)
        return value

    def content_digest(self, value: Any) -> str:
        """Identify validated content by SHA-256 of canonical codec bytes."""
        return f"sha256:{hashlib.sha256(self.encode(value)).hexdigest()}"


@dataclass(frozen=True, slots=True)
class FrozenCatalog:
    """Immutable, atomically validated v2 Catalog and runtime declarations."""

    port_types: tuple[PortTypeDefinition, ...]
    contracts: tuple[Any, ...] = ()
    availability: tuple[Mapping[str, Any], ...] = ()
    availability_observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    factories: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    readiness_declarations: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    effective_randomness_resolvers: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    utility_transforms: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    owners: Mapping[tuple[str, str, str], frozenset[str]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _by_identity: Mapping[tuple[str, str], PortTypeDefinition] = field(
        init=False,
        repr=False,
    )
    _contracts_by_identity: Mapping[tuple[str, str, str], Any] = field(
        init=False,
        repr=False,
    )
    _active_contract_versions: Mapping[tuple[str, str], str] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        resolved: dict[tuple[str, str], PortTypeDefinition] = {}
        for definition in self.port_types:
            definition.validate_runtime_contract()
            identity = (definition.type_id, definition.version)
            if identity in resolved:
                raise CatalogBuildError(
                    "duplicate Port Type identity "
                    f"{definition.type_id}@{definition.version}"
                )
            resolved[identity] = definition
        ordered = tuple(
            sorted(
                resolved.values(),
                key=lambda item: (item.type_id, item.version),
            )
        )
        object.__setattr__(self, "port_types", ordered)
        object.__setattr__(self, "_by_identity", MappingProxyType(resolved))
        contracts_by_identity: dict[tuple[str, str, str], Any] = {}
        ordered_contracts = tuple(
            sorted(
                tuple(self.contracts),
                key=lambda item: (
                    item.contract_kind,
                    item.contract_id,
                    item.contract_version,
                ),
            )
        )
        for contract in ordered_contracts:
            identity = (
                contract.contract_kind,
                contract.contract_id,
                contract.contract_version,
            )
            if identity[0] == "port_type":
                raise CatalogBuildError(
                    "Port Type contracts must use the Port Type definition view"
                )
            if identity in contracts_by_identity:
                raise CatalogBuildError(
                    "duplicate contract identity "
                    f"{identity[0]}:{identity[1]}@{identity[2]}"
                )
            contracts_by_identity[identity] = contract
        _require_single_active_contract_version(
            (
                "port_type",
                definition.type_id,
                definition.version,
            )
            for definition in ordered
        )
        _require_single_active_contract_version(contracts_by_identity)
        for contract in ordered_contracts:
            identity = (
                contract.contract_kind,
                contract.contract_id,
                contract.contract_version,
            )
            canonical_json_bytes(contract.public_contract())
            if identity[0] in {"node_type", "binding"}:
                declaration_field = (
                    "node_parameters"
                    if identity[0] == "node_type"
                    else "binding_parameters"
                )
                declarations = contract.descriptor.get(
                    declaration_field,
                    {},
                )
                if not isinstance(declarations, Mapping):
                    raise CatalogBuildError(
                        f"{declaration_field} must be an object"
                    )
                try:
                    validate_parameter_declarations(
                        declarations,
                        path=(
                            f"{identity[0]}:{identity[1]}"
                            f"@{identity[2]}.{declaration_field}"
                        ),
                    )
                except ParameterContractDefinitionError as error:
                    raise CatalogBuildError(str(error)) from error
        observation_time = self.availability_observed_at
        if (
            not isinstance(observation_time, datetime)
            or observation_time.tzinfo is None
            or observation_time.utcoffset() is None
        ):
            raise CatalogBuildError(
                "Catalog Availability observation time must be timezone-aware"
            )
        frozen_availability = tuple(
            freeze_i_json(thaw_i_json(snapshot))
            for snapshot in self.availability
        )
        canonical_json_bytes(
            [thaw_i_json(snapshot) for snapshot in frozen_availability]
        )
        object.__setattr__(self, "contracts", ordered_contracts)
        object.__setattr__(
            self,
            "_contracts_by_identity",
            MappingProxyType(contracts_by_identity),
        )
        active_contract_versions = {
            ("port_type", definition.type_id): definition.version
            for definition in ordered
        }
        active_contract_versions.update(
            {
                (contract_kind, contract_id): contract_version
                for contract_kind, contract_id, contract_version in (
                    contracts_by_identity
                )
            }
        )
        object.__setattr__(
            self,
            "_active_contract_versions",
            MappingProxyType(active_contract_versions),
        )
        object.__setattr__(self, "availability", frozen_availability)
        object.__setattr__(
            self,
            "availability_observed_at",
            observation_time.astimezone(timezone.utc),
        )
        object.__setattr__(
            self,
            "factories",
            MappingProxyType(dict(self.factories)),
        )
        object.__setattr__(
            self,
            "readiness_declarations",
            MappingProxyType(dict(self.readiness_declarations)),
        )
        object.__setattr__(
            self,
            "effective_randomness_resolvers",
            MappingProxyType(dict(self.effective_randomness_resolvers)),
        )
        object.__setattr__(
            self,
            "utility_transforms",
            MappingProxyType(dict(self.utility_transforms)),
        )
        object.__setattr__(
            self,
            "owners",
            MappingProxyType(dict(self.owners)),
        )
        canonical_json_bytes(self.catalog_descriptor())

    def catalog_descriptor(self) -> dict[str, Any]:
        """Return the stable Catalog identity, excluding observed availability."""
        return {
            "schema_namespace": CATALOG_NAMESPACE,
            "contracts": sorted(
                [
                    definition.public_contract()
                    for definition in self.port_types
                ]
                + [
                    contract.public_contract()
                    for contract in self.contracts
                ],
                key=lambda item: (
                    item["reference"]["contract_kind"],
                    item["reference"]["contract_id"],
                    item["reference"]["contract_version"],
                ),
            ),
        }

    @property
    def catalog_descriptor_bytes(self) -> bytes:
        """RFC 8785 canonical stable Catalog descriptor bytes."""
        return canonical_json_bytes(self.catalog_descriptor())

    @property
    def contract_digest(self) -> str:
        """SHA-256 identity of all stable contracts in this Catalog."""
        return (
            "sha256:"
            f"{hashlib.sha256(self.catalog_descriptor_bytes).hexdigest()}"
        )

    def get_port_type(
        self,
        type_id: str,
        version: str,
    ) -> PortTypeDefinition | None:
        """Return one exact Port Type identity, or None when unknown."""
        return self._by_identity.get((type_id, version))

    def require_port_type(
        self,
        type_id: str,
        version: str,
    ) -> PortTypeDefinition:
        """Resolve one exact identity and fail closed when it is unknown."""
        definition = self.get_port_type(type_id, version)
        if definition is None:
            raise UnknownPortTypeError(f"Unknown Port Type {type_id}@{version}")
        return definition

    def directly_compatible(
        self,
        source_type_id: str,
        source_version: str,
        target_type_id: str,
        target_version: str,
    ) -> bool:
        """Accept a direct connection only between known exact identities."""
        source = self.require_port_type(source_type_id, source_version)
        target = self.require_port_type(target_type_id, target_version)
        return (source.type_id, source.version) == (
            target.type_id,
            target.version,
        )

    def get_contract(
        self,
        contract_kind: str,
        contract_id: str,
        contract_version: str,
    ) -> Any | None:
        """Return one exact stable contract without consulting runtime state."""
        if contract_kind == "port_type":
            return self.get_port_type(contract_id, contract_version)
        return self._contracts_by_identity.get(
            (contract_kind, contract_id, contract_version)
        )

    def require_contract(
        self,
        contract_kind: str,
        contract_id: str,
        contract_version: str,
    ) -> Any:
        """Resolve one exact Catalog contract or fail closed."""
        contract = self.get_contract(
            contract_kind,
            contract_id,
            contract_version,
        )
        if contract is None:
            active_version = self._active_contract_versions.get(
                (contract_kind, contract_id)
            )
            if active_version is None:
                raise UnknownContractError(
                    contract_kind,
                    contract_id,
                    contract_version,
                )
            raise InactiveContractGenerationError(
                contract_kind,
                contract_id,
                contract_version,
                active_version,
            )
        return contract

    def require_factory(
        self,
        binding_id: str,
        binding_version: str,
    ) -> Any:
        """Return the lazy factory owned by one exact Binding."""
        try:
            return self.factories[(binding_id, binding_version)]
        except KeyError as error:
            raise CatalogBuildError(
                f"Unknown Binding factory {binding_id}@{binding_version}"
            ) from error

    def require_readiness_declaration(
        self,
        binding_id: str,
        binding_version: str,
    ) -> Any:
        """Return the run-scoped Readiness declaration for one Binding."""
        try:
            return self.readiness_declarations[
                (binding_id, binding_version)
            ]
        except KeyError as error:
            raise CatalogBuildError(
                f"Unknown Binding readiness {binding_id}@{binding_version}"
            ) from error

    def get_effective_randomness_resolver(
        self,
        binding_id: str,
        binding_version: str,
    ) -> Any | None:
        """Return a Binding's optional pre-Cache randomness resolver."""
        return self.effective_randomness_resolvers.get(
            (binding_id, binding_version)
        )

    def require_utility_transform(
        self,
        transform_id: str,
        transform_version: str,
    ) -> Any:
        """Return one private Utility Transform runtime."""
        try:
            return self.utility_transforms[
                (transform_id, transform_version)
            ]
        except KeyError as error:
            raise CatalogBuildError(
                f"Unknown Utility Transform "
                f"{transform_id}@{transform_version}"
            ) from error

    def public_snapshot(
        self,
        *,
        protocol_digest: str,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Return stable contracts plus the startup Binding observations."""
        timestamp = observed_at or self.availability_observed_at
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise CatalogBuildError(
                "Catalog Snapshot observation time must be timezone-aware"
            )
        timestamp = timestamp.astimezone(timezone.utc)
        timestamp_text = timestamp.isoformat().replace("+00:00", "Z")
        availability = [
            thaw_i_json(snapshot)
            for snapshot in self.availability
        ]
        if observed_at is not None:
            availability = [
                {**snapshot, "observed_at": timestamp_text}
                for snapshot in availability
            ]
        return {
            "schema_namespace": "protein-workbench-public/v2",
            "protocol_digest": protocol_digest,
            "catalog_contract_digest": self.contract_digest,
            "contracts": self.catalog_descriptor()["contracts"],
            "availability_observed_at": timestamp_text,
            "availability": availability,
        }


_BUILTIN_VALUE_KINDS = (
    ("candidate.collection", "candidate_collection"),
    ("candidate.pairing", "pairwise_candidate_mapping"),
    ("protein.sequence", "protein_sequence"),
    ("protein.structure", "protein_structure"),
    ("residue.layout", "residue_layout"),
    ("residue.map", "residue_map"),
    ("residue.track", "residue_track"),
    ("residue.track.sasa", "sasa_residue_track"),
    (
        "residue.track.secondary_structure",
        "secondary_structure_residue_track",
    ),
    ("score.collection", "score_collection"),
    ("text", "text"),
)


def _builtin_port_type(
    type_id: str,
    value_kind: str,
    *,
    version: str = PORT_TYPE_VERSION,
) -> PortTypeDefinition:
    behavior_prefix = f"protein-workbench.port-type/{type_id}"
    validator_parameters: dict[str, Any] = {
        "accepted_value_kind": value_kind,
        "complete_values_only": True,
    }
    codec_parameters: dict[str, Any] = {
        "canonicalization": "RFC 8785",
        "character_encoding": "UTF-8",
        "envelope_namespace": PORT_VALUE_NAMESPACE,
        "value_kind": value_kind,
    }
    if type_id == "protein.sequence":
        validator_parameters["sequence_invariants"] = {
            "alphabet": "ACDEFGHIKLMNPQRSTVWYBXZJUO",
            "nonempty": True,
            "residue_ids": {
                "cardinality": "absent-or-sequence-length",
                "chain_boundary_constraint": "none",
                "item_contract": "canonical-residue-identity",
                "unique": True,
            },
        }
    if type_id == "candidate.collection":
        validator_parameters["candidate_invariants"] = {
            "candidate_id": "canonical-identifier",
            "parent_ids": {
                "item_contract": "canonical-identifier",
                "ordered": True,
                "unique": True,
            },
            "internal_lineage": {
                "acyclic": True,
                "external_parents": "allowed",
                "self_parent": "rejected",
            },
        }
    if type_id == "candidate.pairing":
        participant_fields = [
            "candidate_id",
            "data_type_id",
            "content_digest",
        ]
        validator_parameters["association_contract"] = {
            "entry_fields": ["subject", "reference"],
            "participant": "CandidateDataReference",
            "participant_fields": participant_fields,
            "cardinality": "one-to-one",
        }
        codec_parameters["entry_wire_shape"] = {
            "subject": participant_fields,
            "reference": participant_fields,
        }
    return PortTypeDefinition(
        type_id=type_id,
        version=version,
        validator=BehaviorReference(
            behavior_id=f"{behavior_prefix}/validate",
            behavior_version=version,
            parameters=validator_parameters,
        ),
        codec=BehaviorReference(
            behavior_id=f"{behavior_prefix}/canonical-json-codec",
            behavior_version=version,
            parameters=codec_parameters,
        ),
        content_identity=BehaviorReference(
            behavior_id=f"{behavior_prefix}/content-sha256",
            behavior_version=version,
            parameters={
                "digest_algorithm": "SHA-256",
                "digest_input": "canonical_codec_bytes",
                "digest_representation": (
                    "sha256:<64 lowercase hexadecimal digits>"
                ),
            },
        ),
    )


@lru_cache(maxsize=1)
def builtin_frozen_catalog() -> FrozenCatalog:
    """Build and cache the repository-owned built-in Port Type Catalog."""
    return FrozenCatalog(
        tuple(
            _builtin_port_type(
                type_id,
                value_kind,
                version=_BUILTIN_PORT_TYPE_VERSIONS.get(
                    type_id,
                    PORT_TYPE_VERSION,
                ),
            )
            for type_id, value_kind in _BUILTIN_VALUE_KINDS
        )
    )
