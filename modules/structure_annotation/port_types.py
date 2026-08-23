"""Nominal annotation Ports owned by structure annotation."""

from collections.abc import Mapping
import math
from typing import Any, cast

from core.catalog.builtins import builtin_frozen_catalog
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
    _candidate_data_reference_from_canonical,
    _candidate_data_reference_to_canonical,
)
from datatypes.candidate import CandidateDataReference
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
    validate_residue_layout,
)

from .domain import DSSPAnnotation, StructureAnnotationTrack


_VERSION = "4.0.0"
_ANNOTATION_SECONDARY_SYMBOLS = frozenset("GHITEBSPC_")
_SECONDARY_SYMBOLS = frozenset("GHITEBSC_")
_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_TRACK_CODEC = _BUILTINS.require_port_type("residue.track", "2.1.0")
_ABSOLUTE_SASA_QUANTITY_CONTRACT = {
    "quantity": "solvent_accessible_surface_area",
    "measure": "absolute",
    "unit": "angstrom_squared",
    "granularity": "per_residue",
    "normalization": "none",
}


def _validate_layout(layout: object) -> ResidueLayout:
    return validate_residue_layout(layout, subject="annotation layout")


def _validate_subject(subject: object) -> None:
    if type(subject) is not CandidateDataReference:
        raise ValueError(
            "annotation subject must be a CandidateDataReference"
        )


def _validate_secondary(
    values: object,
    *,
    length: int,
    symbols: frozenset[str] = _SECONDARY_SYMBOLS,
) -> None:
    if (
        not isinstance(values, tuple)
        or len(values) != length
        or any(
            type(value) is not str or value not in symbols
            for value in values
        )
    ):
        raise ValueError(
            "secondary-structure values use an unsupported alphabet"
        )


def _validate_sasa(values: object, *, length: int) -> None:
    if not isinstance(values, tuple) or len(values) != length:
        raise ValueError("SASA values must match the exact residue layout")
    for value in values:
        if value is None:
            continue
        if (
            type(value) is not float
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("SASA values must be nullable non-negative numbers")


def _validate_annotation(value: object) -> None:
    if type(value) is not DSSPAnnotation:
        raise ValueError("DSSP annotation has the wrong runtime type")
    _validate_subject(value.subject)
    layout = _validate_layout(value.layout)
    _validate_secondary(
        value.secondary_structure,
        length=layout.length,
        symbols=_ANNOTATION_SECONDARY_SYMBOLS,
    )
    _validate_sasa(value.sasa, length=layout.length)


def _annotation_to_wire(value: DSSPAnnotation) -> object:
    return {
        "subject": _candidate_data_reference_to_canonical(value.subject),
        "layout": _LAYOUT_CODEC.to_wire(value.layout),
        "secondary_structure": list(value.secondary_structure),
        "sasa": list(value.sasa),
    }


def _annotation_from_wire(value: object) -> object:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"subject", "layout", "secondary_structure", "sasa"}
        or not isinstance(value["secondary_structure"], list)
        or not isinstance(value["sasa"], list)
    ):
        raise ValueError("DSSP annotation wire value is not closed")
    layout = _LAYOUT_CODEC.from_wire(value["layout"])
    return DSSPAnnotation(
        subject=_candidate_data_reference_from_canonical(value["subject"]),
        layout=layout,
        secondary_structure=tuple(value["secondary_structure"]),
        sasa=tuple(
            float(item) if type(item) is int else item
            for item in value["sasa"]
        ),
    )


def _validate_secondary_track(value: object) -> None:
    if type(value) is not StructureAnnotationTrack:
        raise ValueError("secondary-structure track has the wrong runtime type")
    _validate_subject(value.subject)
    layout = _validate_layout(value.layout)
    _validate_secondary(value.values, length=layout.length)


def _validate_sasa_track(value: object) -> None:
    if type(value) is not StructureAnnotationTrack:
        raise ValueError("SASA track has the wrong runtime type")
    _validate_subject(value.subject)
    layout = _validate_layout(value.layout)
    _validate_sasa(value.values, length=layout.length)


def _track_to_wire(value: StructureAnnotationTrack) -> object:
    return {
        "subject": _candidate_data_reference_to_canonical(value.subject),
        "layout": _LAYOUT_CODEC.to_wire(value.layout),
        "track": _TRACK_CODEC.to_wire(
            ResidueTrack(list(value.values), None),
        ),
    }


def _track_from_wire(value: object, *, sasa: bool = False) -> object:
    if (
        not isinstance(value, dict)
        or set(value) != {"subject", "layout", "track"}
    ):
        raise ValueError("annotation track wire value is not closed")
    track = _TRACK_CODEC.from_wire(value["track"])
    values = tuple(track.values)
    if sasa:
        values = tuple(
            float(item) if type(item) is int else item for item in values
        )
    return StructureAnnotationTrack(
        subject=_candidate_data_reference_from_canonical(value["subject"]),
        layout=_LAYOUT_CODEC.from_wire(value["layout"]),
        values=values,
    )


def _sasa_track_from_wire(value: object) -> object:
    return _track_from_wire(value, sasa=True)


def _port_type(
    *,
    type_id: str,
    kind: str,
    validator: Any,
    to_wire: Any,
    from_wire: Any,
    quantity_contract: Mapping[str, str] | None = None,
) -> PortTypeDefinition:
    def candidate_data_references(
        value: object,
        _candidate_data_port_types: object,
    ) -> tuple[CandidateDataReference, ...]:
        return (cast(Any, value).subject,)

    return PortTypeDefinition(
        type_id=type_id,
        version=_VERSION,
        validator=BehaviorReference(
            f"{type_id}/validate",
            _VERSION,
            {
                "accepted_value_kind": kind,
                "subject_reference_required": True,
                "layout_identity_required": True,
                "nullable_semantics": (
                    "underscore_absent"
                    if kind == "secondary_structure_track"
                    else "JSON null means unavailable"
                ),
                **(
                    {"quantity_contract": quantity_contract}
                    if quantity_contract is not None
                    else {}
                ),
            },
        ),
        codec=BehaviorReference(
            f"{type_id}/codec",
            _VERSION,
            {
                "canonicalization": "RFC 8785",
                "embedded_layout_contract": "residue.layout@3.0.0",
                "subject_wire": (
                    "exact CandidateDataReference candidate_id, "
                    "data_type_id, content_digest"
                ),
            },
        ),
        content_identity=BehaviorReference(
            f"{type_id}/content",
            _VERSION,
            {
                "digest": "SHA-256",
                "includes_subject_reference": True,
            },
        ),
        runtime_validator=validator,
        runtime_to_wire=to_wire,
        runtime_from_wire=from_wire,
        candidate_data_projection=BehaviorReference(
            f"{type_id}/candidate_data_projection",
            _VERSION,
            {"fields": ["subject"]},
        ),
        runtime_candidate_data_projection=candidate_data_references,
    )


STRUCTURE_ANNOTATION_PORT_TYPES = (
    _port_type(
        type_id="structure_annotation.dssp_annotations",
        kind="dssp_annotation",
        validator=_validate_annotation,
        to_wire=_annotation_to_wire,
        from_wire=_annotation_from_wire,
    ),
    _port_type(
        type_id="structure_annotation.secondary_structure_track",
        kind="secondary_structure_track",
        validator=_validate_secondary_track,
        to_wire=_track_to_wire,
        from_wire=_track_from_wire,
    ),
    _port_type(
        type_id="structure_annotation.sasa_track",
        kind="sasa_track",
        validator=_validate_sasa_track,
        to_wire=_track_to_wire,
        from_wire=_sasa_track_from_wire,
        quantity_contract=_ABSOLUTE_SASA_QUANTITY_CONTRACT,
    ),
)
