"""Nominal observation Port Types owned by structure annotation.

Both surviving Ports carry one residue track observed for exactly one
structure Candidate. The track owns its authoritative ResidueLayout; the
subject CandidateDataReference is preserved for candidate-data projection.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, cast

from core.catalog import _port_value_codec as _value_codec
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.candidate import CandidateDataReference
from datatypes.residue import (
    CandidateResidueTrack,
    ResidueTrack,
    validate_residue_layout,
)
from modules.residue_data.port_types import (
    ABSOLUTE_SASA_QUANTITY_CONTRACT,
    CANONICAL_SS8,
)


def _sasa_observed_from_wire(value: Any) -> Any:
    """Decode one observed SASA port value, normalizing JSON ints to floats."""
    track = _value_codec._wire_to_value(value)
    if type(track) is CandidateResidueTrack and type(track.track) is ResidueTrack:
        values = tuple(
            float(item) if type(item) is int else item
            for item in track.track.values
        )
        return CandidateResidueTrack(
            track.subject,
            ResidueTrack(track.track.layout, values),
        )
    return track


def _validate_subject(subject: object) -> None:
    if type(subject) is not CandidateDataReference:
        raise ValueError(
            "observed annotation subject must be a CandidateDataReference"
        )
    if subject.data_type_id != "protein.structure":
        raise ValueError(
            "observed annotation subject must reference protein.structure"
        )


def _validate_observed_secondary(value: object) -> None:
    if type(value) is not CandidateResidueTrack:
        raise ValueError(
            "secondary-structure observed value must be a CandidateResidueTrack"
        )
    _validate_subject(value.subject)
    layout = validate_residue_layout(
        value.track.layout,
        subject="observed secondary-structure layout",
    )
    for index, item in enumerate(value.track.values):
        if item is None:
            continue
        if type(item) is not str or item not in CANONICAL_SS8:
            raise ValueError(
                "secondary-structure observed values["
                f"{index}] must be one canonical SS8 state"
            )


def _validate_observed_sasa(value: object) -> None:
    if type(value) is not CandidateResidueTrack:
        raise ValueError(
            "SASA observed value must be a CandidateResidueTrack"
        )
    _validate_subject(value.subject)
    layout = validate_residue_layout(
        value.track.layout,
        subject="observed SASA layout",
    )
    for index, item in enumerate(value.track.values):
        if item is None:
            continue
        if (
            isinstance(item, bool)
            or type(item) is not float
            or not math.isfinite(item)
            or item < 0
        ):
            raise ValueError(
                "SASA observed values["
                f"{index}] must be absolute non-negative square angstroms"
            )


def _candidate_data_references(
    value: object,
    _port_types: object,
) -> tuple[CandidateDataReference, ...]:
    return (cast(Any, value).subject,)


def _observed_port_type(
    *,
    type_id: str,
    validator: Any,
    quantity_contract: Mapping[str, str] | None = None,
    from_wire: Any = None,
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id=type_id,
        validator=BehaviorReference(
            f"{type_id}/validate",
            {
                "accepted_value_kind": "candidate_residue_track",
                "subject_reference_required": True,
                "layout_identity_required": True,
                "nullable_semantics": "JSON null means unavailable",
                **(
                    {"quantity_contract": quantity_contract}
                    if quantity_contract is not None
                    else {}
                ),
            },
        ),
        codec=BehaviorReference(
            f"{type_id}/canonical-json-codec",
            {
                "canonicalization": "RFC 8785",
                "embedded_layout_contract": "residue_layout",
                "subject_wire": (
                    "exact CandidateDataReference candidate_id, "
                    "data_type_id, content_digest"
                ),
            },
        ),
        content_identity=BehaviorReference(
            f"{type_id}/content",
            {
                "digest": "SHA-256",
                "includes_subject_reference": True,
            },
        ),
        runtime_validator=validator,
        runtime_to_wire=_value_codec._value_to_wire,
        runtime_from_wire=(
            from_wire
            if from_wire is not None
            else _value_codec._wire_to_value
        ),
        candidate_data_projection=BehaviorReference(
            f"{type_id}/candidate_data_projection",
            {"fields": ["subject"]},
        ),
        runtime_candidate_data_projection=_candidate_data_references,
    )


STRUCTURE_ANNOTATION_PORT_TYPES = (
    _observed_port_type(
        type_id="structure_annotation.secondary_structure.observed",
        validator=_validate_observed_secondary,
    ),
    _observed_port_type(
        type_id="structure_annotation.sasa.observed",
        validator=_validate_observed_sasa,
        quantity_contract=ABSOLUTE_SASA_QUANTITY_CONTRACT,
        from_wire=_sasa_observed_from_wire,
    ),
)
