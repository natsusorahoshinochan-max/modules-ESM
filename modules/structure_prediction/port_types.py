"""Exact nominal Port Types for structure-prediction confidence facts."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar, cast

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
    canonical_json_bytes,
)
from core.operation import (
    CandidateMetadataIdentity,
    EncodedOutputIdentities,
    OutputIdentityIntent,
    OutputIdentitySource,
    ResolvedOutputIdentity,
)
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ExactPortValueReference,
    ResidueAxisReference,
    validate_canonical_identifier,
)
from datatypes.residue import ResidueLayout
from datatypes.sequence import ProteinSequence
from core.catalog.port_contract import (
    _candidate_data_reference_from_canonical,
    _candidate_data_reference_to_canonical,
    _exact_port_value_reference_to_canonical,
)
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE

from datatypes.prediction import (
    ConfidenceFact,
    ConfidenceFactCollection,
    PendingConfidenceFact,
    PendingConfidenceFactCollection,
    PredictionResidueAxis,
    materialize_confidence_fact,
    prediction_axis_reference,
)


VERSION = "2.0.0"
_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_SEQUENCE_CODEC = _BUILTINS.require_port_type("protein.sequence", "3.0.0")
_STRUCTURE_IDENTITY_PORT_TYPE = _BUILTINS.require_port_type(
    "protein.structure",
    "4.0.0",
)
_ALLOWED_SCALAR_SOURCES = {
    ExactContractReference(**_SEQUENCE_CODEC.reference()),
    ExactContractReference(**PROTEIN_PROMPT_PORT_TYPE.reference()),
}
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
            "value": _candidate_data_reference_to_canonical(source),
        }
    assert type(source) is ExactPortValueReference
    return {
        "kind": "exact_port_value_reference",
        "value": _exact_port_value_reference_to_canonical(source),
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
        return _candidate_data_reference_from_canonical(decoded["value"])
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
    if (
        type(value.source) is ExactPortValueReference
        and value.source.port_type not in _ALLOWED_SCALAR_SOURCES
    ):
        raise ValueError(
            "prediction residue axis source must identify an exact "
            "protein.sequence or protein.prompt Port value"
        )


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
    admitted = cast(PredictionResidueAxis, value)
    return (
        (admitted.source,)
        if type(admitted.source) is CandidateDataReference
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
        "prediction_axis": _prediction_axis_to_wire(value.prediction_axis),
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


def _confidence_axis_references(
    value: object,
) -> tuple[ResidueAxisReference, ...]:
    admitted = cast(ConfidenceFactCollection, value)
    references: list[ResidueAxisReference] = []
    for entry in admitted.entries:
        reference = prediction_axis_reference(
            entry.prediction_axis,
            axis_contract=ExactContractReference(
                **PREDICTION_RESIDUE_AXIS_PORT_TYPE.reference()
            ),
            axis_content_digest=PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(
                entry.prediction_axis
            ),
        )
        if reference not in references:
            references.append(reference)
    return tuple(references)


def _confidence_method_references(
    value: object,
) -> tuple[ExactContractReference, ...]:
    admitted = cast(ConfidenceFactCollection, value)
    return (admitted.observation_method,)


def confidence_output_identity_intent(
    *,
    observation_method: ExactContractReference,
    pending_facts: tuple[PendingConfidenceFact, ...],
) -> OutputIdentityIntent:
    """Declare confidence identities without carrying executable callbacks."""
    relation = PendingConfidenceFactCollection(
        observation_method=observation_method,
        entries=pending_facts,
    )
    return OutputIdentityIntent(
        identity_sources=tuple(
            source
            for index, pending in enumerate(relation.entries)
            for source in (
                OutputIdentitySource(
                    identity_id=f"structure:{index}",
                    source_role="structure",
                    value=pending.structure,
                ),
                OutputIdentitySource(
                    identity_id=f"prediction-axis:{index}",
                    source_role="prediction-axis",
                    value=pending.prediction_axis,
                ),
            )
        ),
        relation=relation,
    )


def _materialize_confidence_output_identity(
    relation: object,
    identities: EncodedOutputIdentities,
) -> ResolvedOutputIdentity:
    if type(relation) is not PendingConfidenceFactCollection:
        raise TypeError(
            "confidence output identity requires pending confidence facts"
        )
    materialized = tuple(
        materialize_confidence_fact(
            pending,
            structure_content_digest=identities.require(
                f"structure:{index}"
            ).content_digest,
            prediction_axis_contract=identities.require(
                f"prediction-axis:{index}"
            ).port_type,
            prediction_axis_content_digest=identities.require(
                f"prediction-axis:{index}"
            ).content_digest,
        )
        for index, pending in enumerate(relation.entries)
    )
    collection = ConfidenceFactCollection(
        observation_method=relation.observation_method,
        entries=tuple(item.fact for item in materialized),
    )
    axes_by_key = {
        item.prediction_key: item.scientific_axis for item in materialized
    }
    return ResolvedOutputIdentity(
        value=collection,
        candidate_metadata=tuple(
            CandidateMetadataIdentity(
                candidate_id=item.candidate_id,
                field_name="prediction_key",
                value=item.prediction_key,
            )
            for item in materialized
        ),
        scientific_axes=tuple(
            dict.fromkeys(
                axes_by_key[fact.prediction_key]
                for fact in collection.entries
            )
        ),
    )


_CONFIDENCE_OUTPUT_IDENTITY_MATERIALIZATION = BehaviorReference(
    "structure_prediction.confidence_facts/output_identity_materialization",
    VERSION,
    {
        "relation": "pending-confidence-facts",
        "source_roles": {
            "structure": _STRUCTURE_IDENTITY_PORT_TYPE.reference(),
            "prediction-axis": PREDICTION_RESIDUE_AXIS_PORT_TYPE.reference(),
        },
    },
)


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
                "structure_prediction.prediction_residue_axis@2.0.0"
            ),
            "output_identity_materialization": (
                _CONFIDENCE_OUTPUT_IDENTITY_MATERIALIZATION.descriptor()
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
                "structure_prediction.prediction_residue_axis@2.0.0"
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
    output_identity_materialization=(
        _CONFIDENCE_OUTPUT_IDENTITY_MATERIALIZATION
    ),
    runtime_output_identity_materializer=(
        _materialize_confidence_output_identity
    ),
    output_identity_source_port_types={
        "structure": _STRUCTURE_IDENTITY_PORT_TYPE,
        "prediction-axis": PREDICTION_RESIDUE_AXIS_PORT_TYPE,
    },
)


__all__ = [
    "CONFIDENCE_FACTS_PORT_TYPE",
    "PREDICTION_RESIDUE_AXIS_PORT_TYPE",
]
