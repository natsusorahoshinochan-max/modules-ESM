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
        "residue_ids": (
            None if value.residue_ids is None else list(value.residue_ids)
        ),
        "mean_embedding": list(value.mean_embedding),
        "sequence_logits_shape": list(value.sequence_logits_shape),
    }


def _from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {
        "sequence",
        "residue_ids",
        "mean_embedding",
        "sequence_logits_shape",
    }:
        raise ValueError("ESMC representation wire value is not closed")
    residue_ids = value["residue_ids"]
    mean_embedding = value["mean_embedding"]
    logits_shape = value["sequence_logits_shape"]
    if (
        (residue_ids is not None and not isinstance(residue_ids, list))
        or not isinstance(mean_embedding, list)
        or not isinstance(logits_shape, list)
    ):
        raise ValueError("ESMC representation wire value has invalid fields")
    if any(type(item) not in {int, float} for item in mean_embedding):
        raise ValueError("ESMC representation embedding is not numeric")
    return ESMCSequenceRepresentation(
        sequence=value["sequence"],
        residue_ids=None if residue_ids is None else tuple(residue_ids),
        mean_embedding=tuple(float(item) for item in mean_embedding),
        sequence_logits_shape=tuple(logits_shape),
    )


_TYPE_ID = "esm3.esmc_sequence_representation"
ESMC_SEQUENCE_REPRESENTATION_PORT_TYPE = PortTypeDefinition(
    type_id=_TYPE_ID,
    validator=BehaviorReference(
        f"{_TYPE_ID}/validate",
        {
            "accepted_value_kind": "esmc_sequence_representation",
            "finite_binary32_embedding": True,
            "mean_embedding_dimension": ESMC_MEAN_EMBEDDING_DIMENSION,
            "sequence_logits_shape": "L_plus_2_by_64",
            "sequence_logits_axis": "CLS_residue_tokens_EOS",
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
