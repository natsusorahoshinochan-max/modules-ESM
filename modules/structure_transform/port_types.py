"""Nominal capability Port definitions owned by structure transform."""

from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from datatypes.structure import ProteinStructure

from ._candidate_association_codecs import (
    CANDIDATE_ASSOCIATION_VERSION,
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
    NORMALIZATION_FACTS_VERSION,
)
from ._normalization_codec import (
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
)
from ._resolved_axis_codec import (
    RESOLVED_AXIS_PORT_TYPE,
    RESOLVED_AXIS_VERSION,
)
from .projections import validate_backbone_structure


_BACKBONE_PORT_VERSION = "4.0.0"


def _backbone_to_wire(value: ProteinStructure) -> object:
    return {"pdb_string": value.pdb_string}


def _backbone_from_wire(value: object) -> object:
    if (
        not isinstance(value, dict)
        or set(value) != {"pdb_string"}
        or type(value["pdb_string"]) is not str
    ):
        raise ValueError("backbone wire value is invalid")
    return ProteinStructure(pdb_string=value["pdb_string"])


BACKBONE_STRUCTURE_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.backbone_structure",
    version=_BACKBONE_PORT_VERSION,
    validator=BehaviorReference(
        "structure_transform.backbone_structure/validate",
        _BACKBONE_PORT_VERSION,
        {
            "accepted_value_kind": "protein_structure",
            "embedded_structure_contract": "protein.structure@4.0.0",
            "record_contract": {
                "records": ["ATOM", "TER", "END"],
                "atoms": ["N", "CA", "C", "O"],
                "alternate_locations": "resolved",
                "missing_atoms": "rejected",
                "chain_breaks": "TER-terminated",
            },
        },
    ),
    codec=BehaviorReference(
        "structure_transform.backbone_structure/codec",
        _BACKBONE_PORT_VERSION,
        {
            "canonicalization": "RFC 8785",
            "pdb_line_endings": "LF",
        },
    ),
    content_identity=BehaviorReference(
        "structure_transform.backbone_structure/content",
        _BACKBONE_PORT_VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_backbone_structure,
    runtime_to_wire=_backbone_to_wire,
    runtime_from_wire=_backbone_from_wire,
)


__all__ = [
    "BACKBONE_STRUCTURE_PORT_TYPE",
    "CANDIDATE_ASSOCIATION_VERSION",
    "CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE",
    "CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE",
    "CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE",
    "MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE",
    "NORMALIZATION_FACTS_VERSION",
    "RESOLVED_AXIS_PORT_TYPE",
    "RESOLVED_AXIS_VERSION",
]
