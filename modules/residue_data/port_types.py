"""Nominal residue conditioning Port Types owned by residue data."""

from __future__ import annotations

from typing import Any

from core.catalog import _port_value_codec as _value_codec
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.prompt import FunctionAnnotationTrack
from datatypes.residue import (
    CandidateResidueTrack,
    ResidueTrack,
    validate_residue_layout,
)

from .elements import (
    ABSOLUTE_SASA_QUANTITY_CONTRACT,
    validate_coordinate_elements,
    validate_sasa_elements,
    validate_secondary_structure_elements,
    validate_sequence_elements,
)


def _generic_wire(value: Any) -> Any:
    return _value_codec._value_to_wire(value)


def _generic_unwire(value: Any) -> Any:
    return _value_codec._wire_to_value(value)


def _sasa_conditioning_from_wire(value: Any) -> Any:
    """Decode one SASA conditioning value, normalizing JSON ints to floats."""
    track = _value_codec._wire_to_value(value)
    if type(track) is ResidueTrack:
        values = tuple(
            float(item) if type(item) is int else item
            for item in track.values
        )
        return ResidueTrack(track.layout, values)
    return track


def _validate_track(value: object, *, subject: str) -> ResidueTrack[Any]:
    if type(value) is not ResidueTrack:
        raise ValueError(f"{subject} must be a ResidueTrack")
    validate_residue_layout(value.layout, subject=f"{subject} layout")
    return value


def _validate_sequence(value: object) -> None:
    track = _validate_track(value, subject="sequence conditioning")
    validate_sequence_elements(track.values, subject="sequence conditioning values")


def _validate_coordinates(value: object) -> None:
    track = _validate_track(value, subject="coordinates conditioning")
    validate_coordinate_elements(
        track.values, subject="coordinates conditioning values",
    )


def _validate_secondary_structure(value: object) -> None:
    track = _validate_track(
        value,
        subject="secondary-structure conditioning",
    )
    validate_secondary_structure_elements(
        track.values, subject="secondary-structure conditioning values",
    )


def _validate_sasa(value: object) -> None:
    track = _validate_track(value, subject="SASA conditioning")
    validate_sasa_elements(track.values, subject="SASA conditioning values")


def _validate_function_annotations(value: object) -> None:
    if type(value) is not FunctionAnnotationTrack:
        raise ValueError(
            "function annotation conditioning must be a "
            "FunctionAnnotationTrack"
        )
    validate_residue_layout(
        value.layout,
        subject="function annotation conditioning layout",
    )


def _conditioning_port_type(
    *,
    type_id: str,
    kind: str,
    validator: Any,
    scientific_meaning: str,
    element_contract: dict[str, Any],
    from_wire: Any = None,
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id=type_id,
        validator=BehaviorReference(
            f"{type_id}/validate",
            {
                "accepted_value_kind": kind,
                "complete_values_only": True,
                "layout_contract": "identity-complete ResidueLayout owned "
                "by the ResidueTrack",
                "element_contract": element_contract,
                "scientific_meaning": scientific_meaning,
            },
        ),
        codec=BehaviorReference(
            f"{type_id}/canonical-json-codec",
            {
                "canonicalization": "RFC 8785",
                "character_encoding": "UTF-8",
                "envelope_namespace": "protein-workbench-port-value/v2",
                "wire_shape": "closed-residue-track-carrier",
            },
        ),
        content_identity=BehaviorReference(
            f"{type_id}/content-sha256",
            {
                "digest_algorithm": "SHA-256",
                "digest_input": "canonical_codec_bytes",
            },
        ),
        runtime_validator=validator,
        runtime_to_wire=_generic_wire,
        runtime_from_wire=(
            from_wire if from_wire is not None else _generic_unwire
        ),
    )


RESIDUE_CONDITION_PORT_TYPES = (
    _conditioning_port_type(
        type_id="residue.condition.sequence",
        kind="residue_condition_sequence",
        validator=_validate_sequence,
        scientific_meaning=(
            "Nullable amino-acid conditioning aligned to one exact "
            "residue layout"
        ),
        element_contract={
            "alphabet": "ACDEFGHIKLMNPQRSTVWYBXZJUO",
            "missing": "per-residue JSON null",
        },
    ),
    _conditioning_port_type(
        type_id="residue.condition.coordinates",
        kind="residue_condition_coordinates",
        validator=_validate_coordinates,
        scientific_meaning=(
            "Nullable named-atom coordinate conditioning in angstroms "
            "aligned to one exact residue layout"
        ),
        element_contract={
            "carrier": "NamedAtomCoordinates",
            "unit": "angstrom",
            "missing": "per-residue JSON null",
        },
    ),
    _conditioning_port_type(
        type_id="residue.condition.secondary_structure",
        kind="residue_condition_secondary_structure",
        validator=_validate_secondary_structure,
        scientific_meaning=(
            "Nullable canonical SS8 conditioning aligned to one exact "
            "residue layout"
        ),
        element_contract={
            "alphabet": "HBEGITSC",
            "missing": "per-residue JSON null",
        },
    ),
    _conditioning_port_type(
        type_id="residue.condition.sasa",
        kind="residue_condition_sasa",
        validator=_validate_sasa,
        scientific_meaning=(
            "Nullable absolute per-residue solvent-accessible surface "
            "area conditioning without normalization"
        ),
        element_contract={
            **ABSOLUTE_SASA_QUANTITY_CONTRACT,
            "missing": "per-residue JSON null",
        },
        from_wire=_sasa_conditioning_from_wire,
    ),
    _conditioning_port_type(
        type_id="residue.condition.function_annotations",
        kind="residue_condition_function_annotations",
        validator=_validate_function_annotations,
        scientific_meaning=(
            "Identity-addressed function intervals bound to one exact "
            "residue layout"
        ),
        element_contract={
            "carrier": "FunctionAnnotationTrack",
            "ordering": "start_residue_id,end_residue_id,label",
            "interval_contract": "same-chain inclusive residue identities",
        },
    ),
)
