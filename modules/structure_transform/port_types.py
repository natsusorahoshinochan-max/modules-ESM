"""Nominal capability Port definitions owned by structure transform."""

from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from datatypes.structure import ProteinStructure

from ._candidate_association_codecs import (
    CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE,
    CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
    CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE,
)
from ._normalization_codec import (
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
)
from ._resolved_axis_codec import (
    RESOLVED_AXIS_PORT_TYPE,
)
from .projections import validate_backbone_structure




def _backbone_to_wire(value: ProteinStructure) -> object:
    return {"pdb_string" if value.format == "pdb" else "mmcif_string": value.text}


def _backbone_from_wire(value: object) -> object:
    if not isinstance(value, dict):
        raise ValueError("backbone wire value is invalid")
    if set(value) == {"pdb_string"} and type(value["pdb_string"]) is str:
        return ProteinStructure(value["pdb_string"], "pdb")
    if set(value) == {"mmcif_string"} and type(value["mmcif_string"]) is str:
        return ProteinStructure(value["mmcif_string"], "mmcif")
    raise ValueError("backbone wire value is invalid")


BACKBONE_STRUCTURE_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.backbone_structure",
    validator=BehaviorReference(
        "structure_transform.backbone_structure/validate",
        {
            "accepted_value_kind": "protein_structure",
            "embedded_structure_contract": "protein.structure",
            "record_contract": {
                "records": ["ATOM", "TER", "END"],
                "formats": ["pdb", "mmcif"],
                "atoms": ["N", "CA", "C", "O"],
                "alternate_locations": "resolved",
                "missing_atoms": "rejected",
                "chain_breaks": "TER-terminated",
            },
        },
    ),
    codec=BehaviorReference(
        "structure_transform.backbone_structure/codec",
        {
            "canonicalization": "RFC 8785",
            "line_endings": "LF",
            "format_fields": ["pdb_string", "mmcif_string"],
        },
    ),
    content_identity=BehaviorReference(
        "structure_transform.backbone_structure/content",
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_backbone_structure,
    runtime_to_wire=_backbone_to_wire,
    runtime_from_wire=_backbone_from_wire,
)


__all__ = [
    "BACKBONE_STRUCTURE_PORT_TYPE",
    "CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE",
    "CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE",
    "CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE",
    "MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE",
    "RESOLVED_AXIS_PORT_TYPE",
]
