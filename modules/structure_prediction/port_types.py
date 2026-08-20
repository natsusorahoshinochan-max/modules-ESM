"""Exact nominal Port Types for structure-prediction confidence facts."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from core import (
    BehaviorReference,
    PortTypeDefinition,
    builtin_frozen_catalog,
    canonical_json_bytes,
)
from datatypes import (
    CandidateDataReference,
    ExactContractReference,
    ExactPortValueReference,
    ProteinSequence,
    ResidueLayout,
    ResidueAxisReference,
    validate_canonical_identifier,
)

from .domain import (
    ConfidenceFact,
    ConfidenceFactCollection,
    PredictionResidueAxis,
)


VERSION = "1.0.0"
_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_SEQUENCE_CODEC = _BUILTINS.require_port_type("protein.sequence", "3.0.0")
_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)
_DecodedValue = TypeVar("_DecodedValue")


def _wire_value(codec: PortTypeDefinition, value: object) -> object:
    return json.loads(codec.encode(value))["value"]


def _decode_value(
    codec: PortTypeDefinition,
    value: object,
    expected_type: type[_DecodedValue],
) -> _DecodedValue:
    decoded = codec.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": codec.type_id,
                "port_type_version": codec.version,
                "value": value,
            }
        )
    )
    if type(decoded) is not expected_type:
        raise ValueError(
            f"{codec.type_id} codec returned the wrong canonical value type"
        )
    return decoded


def _closed_dict(
    value: object,
    fields: set[str],
    *,
    subject: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{subject} must be a closed object")
    return value


def _reference_to_wire(reference: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


def _reference_from_wire(
    value: object,
    *,
    expected_kind: str,
) -> ExactContractReference:
    decoded = _closed_dict(
        value,
        {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        },
        subject="exact contract reference",
    )
    if any(type(item) is not str for item in decoded.values()):
        raise ValueError("exact contract reference fields must be text")
    reference = ExactContractReference(**decoded)
    if reference.contract_kind != expected_kind:
        raise ValueError(
            f"exact contract reference must identify one {expected_kind}"
        )
    validate_canonical_identifier(
        reference.contract_id,
        "exact contract reference id",
    )
    if _SEMANTIC_VERSION.fullmatch(reference.contract_version) is None:
        raise ValueError("exact contract reference version must be semantic")
    if _CONTENT_DIGEST.fullmatch(reference.contract_digest) is None:
        raise ValueError("exact contract reference digest is invalid")
    return reference


def _source_to_wire(
    source: CandidateDataReference | ExactPortValueReference,
) -> dict[str, object]:
    if type(source) is CandidateDataReference:
        return {
            "kind": "candidate_data_reference",
            "value": source.to_public(),
        }
    assert type(source) is ExactPortValueReference
    return {
        "kind": "exact_port_value_reference",
        "value": source.to_public(),
    }


def _source_from_wire(
    value: object,
) -> CandidateDataReference | ExactPortValueReference:
    decoded = _closed_dict(
        value,
        {"kind", "value"},
        subject="prediction residue axis source",
    )
    kind = decoded["kind"]
    if kind == "candidate_data_reference":
        return CandidateDataReference.from_public(decoded["value"])
    if kind != "exact_port_value_reference":
        raise ValueError("prediction residue axis source kind is invalid")
    port_value = _closed_dict(
        decoded["value"],
        {"port_type", "content_digest"},
        subject="exact Port value reference",
    )
    if type(port_value["content_digest"]) is not str:
        raise ValueError("exact Port value content digest must be text")
    return ExactPortValueReference(
        port_type=_reference_from_wire(
            port_value["port_type"],
            expected_kind="port_type",
        ),
        content_digest=port_value["content_digest"],
    )


def _validate_prediction_residue_axis(value: object) -> None:
    if type(value) is not PredictionResidueAxis:
        raise ValueError(
            "prediction residue axis must be a PredictionResidueAxis"
        )
    normalized = PredictionResidueAxis(
        source=value.source,
        layout=value.layout,
        sequence=value.sequence,
    )
    if normalized != value:
        raise ValueError("prediction residue axis is not in canonical form")


def _prediction_axis_to_wire(value: object) -> object:
    assert type(value) is PredictionResidueAxis
    return {
        "source": _source_to_wire(value.source),
        "layout": _wire_value(_LAYOUT_CODEC, value.layout),
        "sequence": _wire_value(_SEQUENCE_CODEC, value.sequence),
    }


def _prediction_axis_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {"source", "layout", "sequence"},
        subject="prediction residue axis",
    )
    result = PredictionResidueAxis(
        source=_source_from_wire(decoded["source"]),
        layout=_decode_value(
            _LAYOUT_CODEC,
            decoded["layout"],
            ResidueLayout,
        ),
        sequence=_decode_value(
            _SEQUENCE_CODEC,
            decoded["sequence"],
            ProteinSequence,
        ),
    )
    _validate_prediction_residue_axis(result)
    return result


def _prediction_axis_candidate_data_references(
    value: object,
    _candidate_data_port_types: object,
) -> tuple[CandidateDataReference, ...]:
    _validate_prediction_residue_axis(value)
    assert type(value) is PredictionResidueAxis
    return (
        (value.source,)
        if type(value.source) is CandidateDataReference
        else ()
    )


PREDICTION_RESIDUE_AXIS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_prediction.prediction_residue_axis",
    version=VERSION,
    validator=BehaviorReference(
        "structure_prediction.prediction_residue_axis/validate",
        VERSION,
        {
            "accepted_value_kind": "prediction_residue_axis",
            "source": (
                "exact-protein-sequence-Candidate-or-exact-protein-sequence-"
                "or-protein-prompt-Port-value"
            ),
            "layout": "identity-complete",
            "sequence_layout_identity": "exact-residue-id-equality",
        },
    ),
    codec=BehaviorReference(
        "structure_prediction.prediction_residue_axis/codec",
        VERSION,
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "embedded_layout_contract": "residue.layout@3.0.0",
            "embedded_sequence_contract": "protein.sequence@3.0.0",
        },
    ),
    content_identity=BehaviorReference(
        "structure_prediction.prediction_residue_axis/content",
        VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=_validate_prediction_residue_axis,
    runtime_to_wire=_prediction_axis_to_wire,
    runtime_from_wire=_prediction_axis_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_prediction.prediction_residue_axis/"
        "candidate_data_projection",
        VERSION,
        {"fields": ["source-if-CandidateDataReference"]},
    ),
    runtime_candidate_data_projection=(
        _prediction_axis_candidate_data_references
    ),
)


def _validate_confidence_fact(value: object) -> ConfidenceFact:
    if type(value) is not ConfidenceFact:
        raise ValueError("confidence fact must be a ConfidenceFact")
    normalized = ConfidenceFact(
        prediction_key=value.prediction_key,
        structure_content_digest=value.structure_content_digest,
        prediction_axis=value.prediction_axis,
        plddt_per_residue=value.plddt_per_residue,
        ptm=value.ptm,
        pae=value.pae,
    )
    if normalized != value:
        raise ValueError("confidence fact is not in canonical form")
    return value


def _validate_confidence_facts(value: object) -> None:
    if type(value) is not ConfidenceFactCollection:
        raise ValueError(
            "confidence facts must be a ConfidenceFactCollection"
        )
    for entry in value.entries:
        _validate_confidence_fact(entry)
    normalized = ConfidenceFactCollection(
        observation_method=value.observation_method,
        entries=value.entries,
    )
    if normalized != value:
        raise ValueError("confidence facts are not in canonical key order")


def _confidence_fact_to_wire(value: ConfidenceFact) -> dict[str, object]:
    return {
        "prediction_key": value.prediction_key,
        "structure_content_digest": value.structure_content_digest,
        "prediction_axis": _wire_value(
            PREDICTION_RESIDUE_AXIS_PORT_TYPE,
            value.prediction_axis,
        ),
        "plddt_per_residue": list(value.plddt_per_residue),
        "ptm": value.ptm,
        "pae": (
            None
            if value.pae is None
            else [list(row) for row in value.pae]
        ),
    }


def _confidence_fact_from_wire(value: object) -> ConfidenceFact:
    decoded = _closed_dict(
        value,
        {
            "prediction_key",
            "structure_content_digest",
            "prediction_axis",
            "plddt_per_residue",
            "ptm",
            "pae",
        },
        subject="confidence fact",
    )
    if (
        type(decoded["prediction_key"]) is not str
        or type(decoded["structure_content_digest"]) is not str
        or not isinstance(decoded["plddt_per_residue"], list)
        or decoded["pae"] is not None
        and not isinstance(decoded["pae"], list)
    ):
        raise ValueError("confidence fact wire fields are invalid")
    pae = decoded["pae"]
    if pae is not None and any(not isinstance(row, list) for row in pae):
        raise ValueError("confidence fact PAE wire value is invalid")
    result = ConfidenceFact(
        prediction_key=decoded["prediction_key"],
        structure_content_digest=decoded["structure_content_digest"],
        prediction_axis=_decode_value(
            PREDICTION_RESIDUE_AXIS_PORT_TYPE,
            decoded["prediction_axis"],
            PredictionResidueAxis,
        ),
        plddt_per_residue=tuple(decoded["plddt_per_residue"]),
        ptm=decoded["ptm"],
        pae=(
            None
            if pae is None
            else tuple(tuple(row) for row in pae)
        ),
    )
    return _validate_confidence_fact(result)


def _confidence_facts_to_wire(value: object) -> object:
    assert type(value) is ConfidenceFactCollection
    return {
        "observation_method": _reference_to_wire(value.observation_method),
        "entries": [
            _confidence_fact_to_wire(entry) for entry in value.entries
        ],
    }


def _confidence_facts_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {"observation_method", "entries"},
        subject="confidence facts",
    )
    if not isinstance(decoded["entries"], list) or not decoded["entries"]:
        raise ValueError("confidence fact entries must be a nonempty list")
    entries = tuple(
        _confidence_fact_from_wire(item) for item in decoded["entries"]
    )
    keys = tuple(entry.prediction_key for entry in entries)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError(
            "confidence fact entries must use unique canonical key order"
        )
    result = ConfidenceFactCollection(
        observation_method=_reference_from_wire(
            decoded["observation_method"],
            expected_kind="method",
        ),
        entries=entries,
    )
    _validate_confidence_facts(result)
    return result


def prediction_axis_reference(
    axis: PredictionResidueAxis,
) -> ResidueAxisReference:
    """Project one scalar prediction axis into its exact Score reference."""
    _validate_prediction_residue_axis(axis)
    return ResidueAxisReference(
        axis_kind="prediction_input",
        axis_contract=ExactContractReference(
            **PREDICTION_RESIDUE_AXIS_PORT_TYPE.reference()
        ),
        axis_content_digest=(
            PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(axis)
        ),
        source=axis.source,
        layout=axis.layout,
    )


def _confidence_axis_references(
    value: object,
) -> tuple[ResidueAxisReference, ...]:
    _validate_confidence_facts(value)
    assert type(value) is ConfidenceFactCollection
    references: list[ResidueAxisReference] = []
    for entry in value.entries:
        reference = prediction_axis_reference(entry.prediction_axis)
        if reference not in references:
            references.append(reference)
    return tuple(references)


def _confidence_method_references(
    value: object,
) -> tuple[ExactContractReference, ...]:
    _validate_confidence_facts(value)
    assert type(value) is ConfidenceFactCollection
    return (value.observation_method,)


CONFIDENCE_FACTS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_prediction.confidence_facts",
    version=VERSION,
    validator=BehaviorReference(
        "structure_prediction.confidence_facts/validate",
        VERSION,
        {
            "accepted_value_kind": "confidence_fact_collection",
            "entry_key": "prediction_key",
            "entry_order": "canonical-prediction-key",
            "observation_method": "one-exact-shared-Method",
            "axis_contract": (
                "structure_prediction.prediction_residue_axis@1.0.0"
            ),
        },
    ),
    codec=BehaviorReference(
        "structure_prediction.confidence_facts/codec",
        VERSION,
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "collection_order": "prediction_key",
            "nested_axis_codec": (
                "structure_prediction.prediction_residue_axis@1.0.0"
            ),
        },
    ),
    content_identity=BehaviorReference(
        "structure_prediction.confidence_facts/content",
        VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=_validate_confidence_facts,
    runtime_to_wire=_confidence_facts_to_wire,
    runtime_from_wire=_confidence_facts_from_wire,
    scientific_axis_projection=BehaviorReference(
        "structure_prediction.confidence_facts/scientific_axis_projection",
        VERSION,
        {
            "axis_kind": "prediction_input",
            "nested_axis_identity": "independent-scalar-codec-digest",
            "shared_axes": "stable-deduplication",
        },
    ),
    runtime_scientific_axis_projection=_confidence_axis_references,
    observation_method_projection=BehaviorReference(
        "structure_prediction.confidence_facts/observation_method_projection",
        VERSION,
        {
            "source": "collection-level-observation_method",
            "cardinality": "exactly-one",
        },
    ),
    runtime_observation_method_projection=_confidence_method_references,
)


__all__ = [
    "CONFIDENCE_FACTS_PORT_TYPE",
    "PREDICTION_RESIDUE_AXIS_PORT_TYPE",
    "prediction_axis_reference",
]
