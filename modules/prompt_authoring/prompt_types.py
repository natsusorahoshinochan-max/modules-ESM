"""Exact Port Types for canonical annotations and ProteinPrompt."""

from __future__ import annotations

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    validate_canonical_function_annotations,
)
from datatypes.residue import ResidueTrack

from .prompts import validate_protein_prompt
from .track_types import ABSOLUTE_SASA_QUANTITY_CONTRACT


_BUILTINS = builtin_frozen_catalog()
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout")
_TRACK_CODEC = _BUILTINS.require_port_type("residue.track")
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


def _function_annotation_to_canonical(
    value: FunctionAnnotation,
) -> dict[str, object]:
    return {
        "label": value.label,
        "start": value.start,
        "end": value.end,
        "chain_id": value.chain_id,
        "start_residue_id": value.start_residue_id,
        "end_residue_id": value.end_residue_id,
        "overlap_policy": value.overlap_policy,
    }


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
    return None if track is None else _TRACK_CODEC.to_wire(track)


def _track_from_wire(value: object) -> ResidueTrack | None:
    if value is None:
        return None
    return _TRACK_CODEC.from_wire(value)


def _validate_prompt(value: object) -> None:
    validate_protein_prompt(value)


def _prompt_to_wire(prompt: ProteinPrompt) -> object:
    return {
        "target_layout": _LAYOUT_CODEC.to_wire(
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
        target_layout=_LAYOUT_CODEC.from_wire(
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
    validator=BehaviorReference(
        "prompt_authoring.function.annotations/validate",
        {
            "accepted_value_kind": "canonical_function_annotations",
            "canonical_interval_contract": {
                "fields": sorted(_ANNOTATION_FIELDS),
                "indexing": "one-based-inclusive",
                "ordering": (
                    "start,end,label,chain-and-residue-provenance"
                ),
                "overlap_policy": ["allow", "reject"],
                "residue_identity_contract": "residue.layout",
            },
            "complete_values_only": True,
        },
    ),
    codec=BehaviorReference(
        "prompt_authoring.function.annotations/canonical-json-codec",
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "envelope_namespace": "protein-workbench-port-value/v2",
            "wire_shape": "closed-annotation-records",
        },
    ),
    content_identity=BehaviorReference(
        "prompt_authoring.function.annotations/content-sha256",
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
    validator=BehaviorReference(
        "prompt_authoring.protein.prompt/validate",
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
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "envelope_namespace": "protein-workbench-port-value/v2",
            "embedded_contracts": {
                "function_annotations": "function.annotations",
                "target_layout": "residue.layout",
                "tracks": "residue.track",
            },
            "nullable_semantics": "JSON null means unspecified",
        },
    ),
    content_identity=BehaviorReference(
        "prompt_authoring.protein.prompt/content-sha256",
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
