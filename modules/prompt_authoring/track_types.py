"""Exact nominal Port Types for identity-aligned residue tracks."""

from __future__ import annotations

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.residue import ResidueTrack

from .domain import AlignedResidueTrack, TrackKind, validate_track


_VERSION = "3.0.0"
_TYPE_ID_BY_KIND = {
    TrackKind.SEQUENCE: "prompt_authoring.track.sequence",
    TrackKind.STRUCTURE: "prompt_authoring.track.structure",
    TrackKind.VISIBILITY: "prompt_authoring.track.visibility",
    TrackKind.SECONDARY_STRUCTURE: (
        "prompt_authoring.track.secondary_structure"
    ),
    TrackKind.SASA: "prompt_authoring.track.sasa",
}
_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", _VERSION)
_TRACK_CODEC = _BUILTINS.require_port_type("residue.track", "2.1.0")
ABSOLUTE_SASA_QUANTITY_CONTRACT = {
    "quantity": "solvent_accessible_surface_area",
    "measure": "absolute",
    "unit": "angstrom_squared",
    "granularity": "per_residue",
    "normalization": "none",
}


def _validator(kind: TrackKind):
    def validate(value: object) -> None:
        validate_track(
            value,
            kind=kind,
            subject=f"{kind.value} track",
        )

    return validate


def _to_wire(aligned: AlignedResidueTrack) -> object:
    return {
        "layout": _LAYOUT_CODEC.to_wire(aligned.layout),
        "track": _TRACK_CODEC.to_wire(
            ResidueTrack(list(aligned.values), None),
        ),
    }


def _from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {"layout", "track"}:
        raise ValueError("aligned residue track wire value is not closed")
    layout = _LAYOUT_CODEC.from_wire(value["layout"])
    track = _TRACK_CODEC.from_wire(value["track"])
    return AlignedResidueTrack(layout=layout, values=tuple(track.values))


def aligned_track_port_type(kind: TrackKind) -> PortTypeDefinition:
    """Construct one immutable exact nominal aligned-track contract."""
    type_id = _TYPE_ID_BY_KIND[kind]
    behavior_prefix = f"{type_id}/v3"
    return PortTypeDefinition(
        type_id=type_id,
        version=_VERSION,
        validator=BehaviorReference(
            f"{behavior_prefix}/validate",
            _VERSION,
            {
                "accepted_value_kind": "identity_aligned_residue_track",
                "scientific_value_domain": kind.value,
                "layout_identity_required": True,
                "nullable_semantics": "JSON null means unspecified",
                **(
                    {
                        "quantity_contract": (
                            ABSOLUTE_SASA_QUANTITY_CONTRACT
                        ),
                    }
                    if kind is TrackKind.SASA
                    else {}
                ),
            },
        ),
        codec=BehaviorReference(
            f"{behavior_prefix}/codec",
            _VERSION,
            {
                "canonicalization": "RFC 8785",
                "embedded_layout_contract": "residue.layout@3.0.0",
                "embedded_values_contract": "residue.track@2.1.0",
            },
        ),
        content_identity=BehaviorReference(
            f"{behavior_prefix}/content",
            _VERSION,
            {
                "digest": "SHA-256",
                "digest_input": "canonical_codec_bytes",
            },
        ),
        runtime_validator=_validator(kind),
        runtime_to_wire=_to_wire,
        runtime_from_wire=_from_wire,
    )


ALIGNED_TRACK_PORT_TYPES = tuple(
    aligned_track_port_type(kind)
    for kind in TrackKind
)
