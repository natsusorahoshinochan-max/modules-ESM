"""Exact Port Types for canonical annotations and ProteinPrompt."""

from __future__ import annotations

import json

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.catalog.port_contract import (
    canonical_json_bytes,
)
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    validate_canonical_function_annotations,
)
from datatypes.residue import ResidueTrack
from core.catalog.port_contract import (
    _function_annotation_to_canonical,
)

from .prompts import validate_protein_prompt
from .track_types import ABSOLUTE_SASA_QUANTITY_CONTRACT


_ANNOTATIONS_VERSION = "3.0.0"
_PROMPT_VERSION = "3.0.0"
_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_TRACK_CODEC = _BUILTINS.require_port_type("residue.track", "2.1.0")
_ANNOTATION_FIELDS = {
    "label",
    "start",
    "end",
    "chain_id",
    "start_residue_id",
    "end_residue_id",
    "overlap_policy",
}
_PROMPT_FIELDS = {
    "target_layout",
    "sequence_track",
    "structure_track",
    "structure_visibility_track",
    "secondary_structure_track",
    "sasa_track",
    "function_annotations",
}


def _wire_value(codec: PortTypeDefinition, value: object) -> object:
    return json.loads(codec.encode(value))["value"]


def _decode_value(
    codec: PortTypeDefinition,
    wire_value: object,
) -> object:
    return codec.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": codec.type_id,
                "port_type_version": codec.version,
                "value": wire_value,
            }
        )
    )


def _validate_annotations(value: object) -> None:
    validate_canonical_function_annotations(value)


def _annotations_to_wire(value: FunctionAnnotations) -> object:
    return {
        "annotations": [
            _function_annotation_to_canonical(annotation)
            for annotation in value.annotations
        ],
    }


def _annotations_from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {"annotations"}:
        raise ValueError("function annotations wire value is not closed")
    raw_annotations = value["annotations"]
    if not isinstance(raw_annotations, list):
        raise ValueError("function annotations wire collection must be a list")
    annotations: list[FunctionAnnotation] = []
    for index, raw in enumerate(raw_annotations):
        if not isinstance(raw, dict) or set(raw) != _ANNOTATION_FIELDS:
            raise ValueError(
                f"function annotation wire value {index} is not closed"
            )
        annotations.append(
            FunctionAnnotation(
                label=raw["label"],
                start=raw["start"],
                end=raw["end"],
                chain_id=raw["chain_id"],
                start_residue_id=raw["start_residue_id"],
                end_residue_id=raw["end_residue_id"],
                overlap_policy=raw["overlap_policy"],
            )
        )
    return FunctionAnnotations(annotations)


def _track_to_wire(track: ResidueTrack | None) -> object:
    return None if track is None else _wire_value(_TRACK_CODEC, track)


def _track_from_wire(value: object) -> ResidueTrack | None:
    if value is None:
        return None
    track = _decode_value(_TRACK_CODEC, value)
    if type(track) is not ResidueTrack or track.sentinel is not None:
        raise ValueError("ProteinPrompt tracks must use JSON null semantics")
    return track


def _validate_prompt(value: object) -> None:
    validate_protein_prompt(value)


def _prompt_to_wire(prompt: ProteinPrompt) -> object:
    return {
        "target_layout": _wire_value(
            _LAYOUT_CODEC,
            prompt.target_layout,
        ),
        "sequence_track": _track_to_wire(prompt.sequence_track),
        "structure_track": _track_to_wire(prompt.structure_track),
        "structure_visibility_track": _track_to_wire(
            prompt.structure_visibility_track
        ),
        "secondary_structure_track": _track_to_wire(
            prompt.secondary_structure_track
        ),
        "sasa_track": _track_to_wire(prompt.sasa_track),
        "function_annotations": _annotations_to_wire(
            prompt.function_annotations
        ),
    }


def _prompt_from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != _PROMPT_FIELDS:
        raise ValueError("ProteinPrompt wire value is not closed")
    return ProteinPrompt(
        target_layout=_decode_value(
            _LAYOUT_CODEC,
            value["target_layout"],
        ),
        sequence_track=_track_from_wire(value["sequence_track"]),
        structure_track=_track_from_wire(value["structure_track"]),
        structure_visibility_track=_track_from_wire(
            value["structure_visibility_track"]
        ),
        secondary_structure_track=_track_from_wire(
            value["secondary_structure_track"]
        ),
        sasa_track=_track_from_wire(value["sasa_track"]),
        function_annotations=_annotations_from_wire(
            value["function_annotations"]
        ),
    )


FUNCTION_ANNOTATIONS_PORT_TYPE = PortTypeDefinition(
    type_id="function.annotations",
    version=_ANNOTATIONS_VERSION,
    validator=BehaviorReference(
        "prompt_authoring.function.annotations/validate",
        _ANNOTATIONS_VERSION,
        {
            "accepted_value_kind": "canonical_function_annotations",
            "canonical_interval_contract": {
                "fields": sorted(_ANNOTATION_FIELDS),
                "indexing": "one-based-inclusive",
                "ordering": (
                    "start,end,label,chain-and-residue-provenance"
                ),
                "overlap_policy": ["allow", "reject"],
                "residue_identity_contract": "residue.layout@3.0.0",
            },
            "complete_values_only": True,
        },
    ),
    codec=BehaviorReference(
        "prompt_authoring.function.annotations/canonical-json-codec",
        _ANNOTATIONS_VERSION,
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "envelope_namespace": "protein-workbench-port-value/v2",
            "wire_shape": "closed-annotation-records",
        },
    ),
    content_identity=BehaviorReference(
        "prompt_authoring.function.annotations/content-sha256",
        _ANNOTATIONS_VERSION,
        {
            "digest_algorithm": "SHA-256",
            "digest_input": "canonical_codec_bytes",
        },
    ),
    runtime_validator=_validate_annotations,
    runtime_to_wire=_annotations_to_wire,
    runtime_from_wire=_annotations_from_wire,
)


PROTEIN_PROMPT_PORT_TYPE = PortTypeDefinition(
    type_id="protein.prompt",
    version=_PROMPT_VERSION,
    validator=BehaviorReference(
        "prompt_authoring.protein.prompt/validate",
        _PROMPT_VERSION,
        {
            "accepted_value_kind": "canonical_protein_prompt",
            "complete_values_only": True,
            "effective_layout_required": True,
            "track_layout": "exact-effective-residue-layout",
            "track_contracts": {
                "sasa_track": ABSOLUTE_SASA_QUANTITY_CONTRACT,
            },
        },
    ),
    codec=BehaviorReference(
        "prompt_authoring.protein.prompt/canonical-json-codec",
        _PROMPT_VERSION,
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "envelope_namespace": "protein-workbench-port-value/v2",
            "embedded_contracts": {
                "function_annotations": "function.annotations@3.0.0",
                "target_layout": "residue.layout@3.0.0",
                "tracks": "residue.track@2.1.0",
            },
            "nullable_semantics": "JSON null means unspecified",
        },
    ),
    content_identity=BehaviorReference(
        "prompt_authoring.protein.prompt/content-sha256",
        _PROMPT_VERSION,
        {
            "digest_algorithm": "SHA-256",
            "digest_input": "canonical_codec_bytes",
        },
    ),
    runtime_validator=_validate_prompt,
    runtime_to_wire=_prompt_to_wire,
    runtime_from_wire=_prompt_from_wire,
)


PROMPT_PORT_TYPES = (
    FUNCTION_ANNOTATIONS_PORT_TYPE,
    PROTEIN_PROMPT_PORT_TYPE,
)
