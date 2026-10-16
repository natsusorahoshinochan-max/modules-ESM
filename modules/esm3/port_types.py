"""Nominal ESMC representation Port owned by the ESM3 package."""

from __future__ import annotations

from core.catalog.port_contract import BehaviorReference, PortTypeDefinition

from .domain import (
    ESMC_MEAN_EMBEDDING_DIMENSION,
    ESMC_SEQUENCE_LOGITS_DIMENSION,
    ESMCSequenceRepresentation,
)




def _validate_esmc_representation(value: object) -> None:
    if type(value) is not ESMCSequenceRepresentation:
        raise ValueError("ESMC representation has the wrong runtime type")


def _to_wire(value: ESMCSequenceRepresentation) -> object:
    return {
        "sequence": value.sequence,
        "residue_ids": None if value.residue_ids is None else list(value.residue_ids),
        "mean_embedding": None if value.mean_embedding is None else list(value.mean_embedding),
        "sequence_logits": None if value.sequence_logits is None else [list(row) for row in value.sequence_logits],
    }


def _from_wire(value: object) -> object:
    if not isinstance(value, dict):
        raise ValueError("ESMC representation must be an object")
    return ESMCSequenceRepresentation(
        sequence=value["sequence"],
        residue_ids=None if value["residue_ids"] is None else tuple(value["residue_ids"]),
        mean_embedding=None if value["mean_embedding"] is None else tuple(value["mean_embedding"]),
        sequence_logits=None if value["sequence_logits"] is None else tuple(tuple(row) for row in value["sequence_logits"]),
    )


_TYPE_ID = "esm3.esmc_sequence_representation"
ESMC_SEQUENCE_REPRESENTATION_PORT_TYPE = PortTypeDefinition(
    type_id=_TYPE_ID,
    validator=BehaviorReference(
        f"{_TYPE_ID}/validate",
        {
            "accepted_value_kind": "esmc_sequence_representation",
            "optional_finite_values": True,
            "mean_embedding_dimension": ESMC_MEAN_EMBEDDING_DIMENSION,
            "sequence_logits_shape": "L_by_64",
            "sequence_logits_axis": "input_residues_without_CLS_EOS",
            "sequence_logits_class_width": ESMC_SEQUENCE_LOGITS_DIMENSION,
        },
    ),
    codec=BehaviorReference(
        f"{_TYPE_ID}/codec",
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
        },
    ),
    content_identity=BehaviorReference(
        f"{_TYPE_ID}/content",
        {"digest": "SHA-256"},
    ),
    runtime_validator=_validate_esmc_representation,
    runtime_to_wire=_to_wire,
    runtime_from_wire=_from_wire,
)
