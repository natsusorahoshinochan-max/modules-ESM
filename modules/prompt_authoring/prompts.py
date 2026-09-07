"""Provider-independent ProteinPrompt assembly and track updates."""

from __future__ import annotations

from datatypes.prompt import (
    FunctionAnnotationTrack,
    ProteinPrompt,
    validate_canonical_function_annotations,
)
from datatypes.residue import (
    ResidueTrack,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import NamedAtomCoordinates

from modules.residue_data.elements import (
    validate_coordinate_elements,
    validate_sasa_elements,
    validate_secondary_structure_elements,
    validate_sequence_elements,
)

from .domain import validate_layout


def decompose_protein_prompt(
    prompt: ProteinPrompt,
) -> dict[str, ResidueTrack | FunctionAnnotationTrack]:
    """Publish present conditioning tracks; absent optional tracks have no key."""
    outputs: dict[str, ResidueTrack | FunctionAnnotationTrack] = {
        "sequence": ResidueTrack(prompt.layout, prompt.sequence),
        "coordinates": ResidueTrack(prompt.layout, prompt.coordinates),
        "function_annotations": FunctionAnnotationTrack(prompt.layout, prompt.function_annotations),
    }
    for name in ("secondary_structure", "sasa"):
        values = getattr(prompt, name)
        if values is not None:
            outputs[name] = ResidueTrack(prompt.layout, values)
    return outputs


def assemble_protein_prompt(
    sequence_track: ResidueTrack[str],
    coordinates_track: ResidueTrack[NamedAtomCoordinates],
    annotation_track: FunctionAnnotationTrack,
    *,
    secondary_structure_track: ResidueTrack[str] | None = None,
    sasa_track: ResidueTrack[float] | None = None,
) -> ProteinPrompt:
    """Join admitted conditioning carriers only when their layouts are equal."""
    layout = sequence_track.layout
    for track in (coordinates_track, annotation_track, secondary_structure_track, sasa_track):
        if track is not None and track.layout != layout:
            raise ValueError("assemble inputs must share one ResidueLayout")
    return ProteinPrompt(
        layout=layout,
        sequence=tuple(sequence_track.values),
        coordinates=tuple(coordinates_track.values),
        secondary_structure=None if secondary_structure_track is None else tuple(secondary_structure_track.values),
        sasa=None if sasa_track is None else tuple(sasa_track.values),
        function_annotations=tuple(annotation_track.annotations),
    )


def validate_protein_prompt(value: object) -> ProteinPrompt:
    """Validate one canonical Prompt independent of any provider Adapter."""
    if type(value) is not ProteinPrompt:
        raise ValueError("protein_prompt must be a ProteinPrompt")
    layout = validate_layout(value.layout, subject="protein_prompt layout")
    validate_sequence_elements(
        value.sequence,
        subject="protein_prompt sequence",
    )
    validate_coordinate_elements(
        value.coordinates,
        subject="protein_prompt coordinates",
    )
    if value.secondary_structure is not None:
        validate_secondary_structure_elements(
            value.secondary_structure,
            subject="protein_prompt secondary_structure",
        )
    if value.sasa is not None:
        validate_sasa_elements(
            value.sasa,
            subject="protein_prompt sasa",
        )
    validate_canonical_function_annotations(
        layout,
        value.function_annotations,
    )
    return value


def update_prompt_sequence(
    prompt: ProteinPrompt,
    sequence: ProteinSequence,
) -> ProteinPrompt:
    """Replace only sequence assignments on one canonical Prompt layout."""
    layout = prompt.layout
    if len(sequence.sequence) != layout.length:
        raise ValueError(
            "sequence length must equal the protein_prompt layout"
        )
    if (
        sequence.residue_ids is not None
        and tuple(sequence.residue_ids) != tuple(layout.residue_ids)
    ):
        raise ValueError(
            "sequence residue identities must equal the protein_prompt layout"
        )
    return ProteinPrompt(
        layout=layout,
        sequence=tuple(sequence.sequence),
        coordinates=prompt.coordinates,
        secondary_structure=prompt.secondary_structure,
        sasa=prompt.sasa,
        function_annotations=prompt.function_annotations,
    )
