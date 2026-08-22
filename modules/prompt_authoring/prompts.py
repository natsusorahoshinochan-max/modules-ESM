"""Provider-independent ProteinPrompt assembly and sequence updates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from datatypes.prompt import (
    FunctionAnnotations,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
)
from datatypes.sequence import ProteinSequence

from .annotations import (
    require_function_annotation_layout,
    validate_function_annotations,
)
from .domain import (
    AlignedResidueTrack,
    TrackOverrideDeclaration,
    TrackKind,
    override_track,
    validate_layout,
    validate_track,
)


_TRACK_KINDS = {
    "sequence_track": TrackKind.SEQUENCE,
    "structure_track": TrackKind.STRUCTURE,
    "visibility_track": TrackKind.VISIBILITY,
    "secondary_structure_track": TrackKind.SECONDARY_STRUCTURE,
    "sasa_track": TrackKind.SASA,
}

_PROMPT_TRACK_ATTRIBUTES = {
    "sequence": ("sequence_track", TrackKind.SEQUENCE),
    "structure": ("structure_track", TrackKind.STRUCTURE),
    "visibility": ("structure_visibility_track", TrackKind.VISIBILITY),
    "secondary_structure": (
        "secondary_structure_track",
        TrackKind.SECONDARY_STRUCTURE,
    ),
    "sasa": ("sasa_track", TrackKind.SASA),
}


def _copy_track(track: ResidueTrack | None) -> ResidueTrack | None:
    return (
        None
        if track is None
        else ResidueTrack(list(track.values), track.sentinel)
    )


def assemble_protein_prompt(
    layout: ResidueLayout,
    tracks: Mapping[str, AlignedResidueTrack],
    function_annotations: FunctionAnnotations | None,
) -> ProteinPrompt:
    """Assemble only explicit aligned values into one validated Prompt."""
    normalized: dict[str, ResidueTrack | None] = {
        name: None for name in _TRACK_KINDS
    }
    for name, track in tracks.items():
        if track.layout != layout:
            raise ValueError(
                f"{name} residue identities do not match the prompt layout"
            )
        normalized[name] = ResidueTrack(list(track.values), None)
    annotations = (
        FunctionAnnotations()
        if function_annotations is None
        else require_function_annotation_layout(
            function_annotations,
            layout,
        )
    )
    return ProteinPrompt(
        target_layout=layout,
        sequence_track=normalized["sequence_track"],
        structure_track=normalized["structure_track"],
        structure_visibility_track=normalized["visibility_track"],
        secondary_structure_track=normalized[
            "secondary_structure_track"
        ],
        sasa_track=normalized["sasa_track"],
        function_annotations=FunctionAnnotations(
            list(annotations.annotations)
        ),
    )


def validate_protein_prompt(value: object) -> ProteinPrompt:
    """Validate one canonical Prompt independent of any provider Adapter."""
    if type(value) is not ProteinPrompt or value.target_layout is None:
        raise ValueError(
            "protein_prompt must carry one identity-complete target layout"
        )
    target = validate_layout(
        value.target_layout,
        subject="protein_prompt target layout",
    )
    prompt_tracks = {
        "sequence_track": (value.sequence_track, TrackKind.SEQUENCE),
        "structure_track": (value.structure_track, TrackKind.STRUCTURE),
        "visibility_track": (
            value.structure_visibility_track,
            TrackKind.VISIBILITY,
        ),
        "secondary_structure_track": (
            value.secondary_structure_track,
            TrackKind.SECONDARY_STRUCTURE,
        ),
        "sasa_track": (value.sasa_track, TrackKind.SASA),
    }
    for name, (track, kind) in prompt_tracks.items():
        if track is None:
            continue
        if type(track) is not ResidueTrack or track.sentinel is not None:
            raise ValueError(
                f"protein_prompt {name} must use explicit JSON null semantics"
            )
        validate_track(
            AlignedResidueTrack(target, tuple(track.values)),
            kind=kind,
            subject=f"protein_prompt {name}",
            expected_layout=target,
        )
    validate_function_annotations(value.function_annotations, target)
    return value


def update_prompt_sequence(
    prompt: ProteinPrompt,
    sequence: ProteinSequence,
) -> ProteinPrompt:
    """Replace only sequence assignments on one canonical Prompt layout."""
    source = prompt
    target = prompt.target_layout
    assert target is not None
    if len(sequence.sequence) != target.length:
        raise ValueError(
            "sequence length must equal the protein_prompt target layout"
        )
    if (
        sequence.residue_ids is not None
        and tuple(sequence.residue_ids)
        != tuple(target.residue_ids or ())
    ):
        raise ValueError(
            "sequence residue identities must equal the protein_prompt layout"
        )
    updated = ProteinPrompt(
        target_layout=target,
        sequence_track=ResidueTrack(list(sequence.sequence), None),
        structure_track=_copy_track(source.structure_track),
        structure_visibility_track=_copy_track(
            source.structure_visibility_track
        ),
        secondary_structure_track=_copy_track(
            source.secondary_structure_track
        ),
        sasa_track=_copy_track(source.sasa_track),
        function_annotations=FunctionAnnotations(
            list(source.function_annotations.annotations)
        ),
    )
    return updated


def override_protein_prompt_track(
    prompt: ProteinPrompt,
    *,
    track: str,
    overrides: Sequence[TrackOverrideDeclaration],
) -> ProteinPrompt:
    """Override one declared Prompt track and preserve every other track."""
    source = prompt
    attribute, kind = _PROMPT_TRACK_ATTRIBUTES[track]
    selected = getattr(source, attribute)
    if selected is None:
        raise ValueError(f"protein_prompt has no {track} track to override")
    layout = source.target_layout
    assert layout is not None
    changed = override_track(
        AlignedResidueTrack(layout, tuple(selected.values)),
        layout,
        overrides,
        kind=kind,
    )

    tracks = {
        "sequence_track": _copy_track(source.sequence_track),
        "structure_track": _copy_track(source.structure_track),
        "structure_visibility_track": _copy_track(
            source.structure_visibility_track
        ),
        "secondary_structure_track": _copy_track(
            source.secondary_structure_track
        ),
        "sasa_track": _copy_track(source.sasa_track),
    }
    tracks[attribute] = ResidueTrack(list(changed.values), None)
    return ProteinPrompt(
        target_layout=layout,
        sequence_track=tracks["sequence_track"],
        structure_track=tracks["structure_track"],
        structure_visibility_track=tracks["structure_visibility_track"],
        secondary_structure_track=tracks["secondary_structure_track"],
        sasa_track=tracks["sasa_track"],
        function_annotations=FunctionAnnotations(
            list(source.function_annotations.annotations)
        ),
    )
