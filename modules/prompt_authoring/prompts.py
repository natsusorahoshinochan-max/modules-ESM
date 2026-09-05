"""Provider-independent ProteinPrompt assembly and track updates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

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

from .domain import (
    TrackOverrideDeclaration,
    override_values,
    validate_layout,
    validate_track_values,
)


_PROMPT_TRACK_KINDS = {
    "sequence": "sequence",
    "coordinates": "coordinates",
    "secondary_structure": "secondary_structure",
    "sasa": "sasa",
}


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
    validate_track_values(
        value.sequence,
        kind="sequence",
        subject="protein_prompt sequence",
        length=layout.length,
    )
    validate_track_values(
        value.coordinates,
        kind="coordinates",
        subject="protein_prompt coordinates",
        length=layout.length,
    )
    if value.secondary_structure is not None:
        validate_track_values(
            value.secondary_structure,
            kind="secondary_structure",
            subject="protein_prompt secondary_structure",
            length=layout.length,
        )
    if value.sasa is not None:
        validate_track_values(
            value.sasa,
            kind="sasa",
            subject="protein_prompt sasa",
            length=layout.length,
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


def override_protein_prompt_track(
    prompt: ProteinPrompt,
    *,
    track: str,
    overrides: Sequence[TrackOverrideDeclaration],
) -> ProteinPrompt:
    """Override one declared Prompt track and preserve every other track."""
    if track not in _PROMPT_TRACK_KINDS:
        raise ValueError(f"unknown prompt track {track!r}")
    layout = prompt.layout
    if track in {"sequence", "coordinates"}:
        current: tuple | None = getattr(prompt, track)
    else:
        current = getattr(prompt, track)
        if current is None:
            current = tuple([None] * layout.length)
    changed = override_values(
        current,
        layout,
        overrides,
        kind=_PROMPT_TRACK_KINDS[track],
    )
    validate_track_values(
        changed,
        kind=_PROMPT_TRACK_KINDS[track],
        subject=f"protein_prompt {track}",
        length=layout.length,
    )
    fields: dict[str, object] = {
        "sequence": prompt.sequence,
        "coordinates": prompt.coordinates,
        "secondary_structure": prompt.secondary_structure,
        "sasa": prompt.sasa,
    }
    if track in {"secondary_structure", "sasa"} and fields[track] is None:
        fields[track] = tuple([None] * layout.length)
    fields[track] = changed
    return ProteinPrompt(
        layout=layout,
        sequence=cast("tuple[str | None, ...]", fields["sequence"]),
        coordinates=cast(
            "tuple[NamedAtomCoordinates | None, ...]",
            fields["coordinates"],
        ),
        secondary_structure=cast(
            "tuple[str | None, ...] | None",
            fields["secondary_structure"],
        ),
        sasa=cast(
            "tuple[float | None, ...] | None",
            fields["sasa"],
        ),
        function_annotations=prompt.function_annotations,
    )
