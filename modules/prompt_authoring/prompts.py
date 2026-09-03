"""Provider-independent ProteinPrompt assembly and track updates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from datatypes.prompt import (
    FunctionAnnotation,
    ProteinPrompt,
    validate_canonical_function_annotations,
)
from datatypes.residue import (
    ResidueLayout,
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


def assemble_protein_prompt(
    layout: ResidueLayout,
    tracks: Mapping[str, ResidueTrack | None],
    function_annotations: Sequence[FunctionAnnotation] | None,
) -> ProteinPrompt:
    """Assemble only explicit layout-bound values into one Prompt.

    ``tracks`` keys are ``sequence``, ``coordinates``,
    ``secondary_structure``, and ``sasa``. Sequence and coordinates are
    always present in the aggregate (all-null allowed); secondary
    structure and SASA may be whole-track absent (``None``). Every
    present track must address exactly the given layout.
    """
    validate_layout(layout, subject="protein_prompt layout")
    normalized: dict[str, tuple | None] = {
        "sequence": tuple([None] * layout.length),
        "coordinates": tuple([None] * layout.length),
        "secondary_structure": None,
        "sasa": None,
    }
    for name, track in tracks.items():
        if name not in _PROMPT_TRACK_KINDS:
            raise ValueError(f"unknown prompt track {name!r}")
        if track is None:
            if name in {"sequence", "coordinates"}:
                raise ValueError(
                    f"{name} conditioning is always present on a Prompt"
                )
            normalized[name] = None
            continue
        if type(track) is not ResidueTrack:
            raise ValueError(f"{name} must be a ResidueTrack")
        if track.layout != layout:
            raise ValueError(
                f"{name} residue identities do not match the prompt layout"
            )
        validate_track_values(
            track.values,
            kind=_PROMPT_TRACK_KINDS[name],
            subject=f"protein_prompt {name}",
            length=layout.length,
        )
        normalized[name] = tuple(track.values)
    annotations = (
        ()
        if function_annotations is None
        else validate_canonical_function_annotations(
            tuple(function_annotations)
        )
    )
    addressed = {
        residue_id
        for annotation in annotations
        for residue_id in (
            annotation.start_residue_id,
            annotation.end_residue_id,
        )
    }
    unknown = addressed - set(layout.residue_ids)
    if unknown:
        raise ValueError(
            "function annotations address residue identities outside the "
            "prompt layout"
        )
    return ProteinPrompt(
        layout=layout,
        sequence=cast("tuple[str | None, ...]", normalized["sequence"]),
        coordinates=cast(
            "tuple[NamedAtomCoordinates | None, ...]",
            normalized["coordinates"],
        ),
        secondary_structure=cast(
            "tuple[str | None, ...] | None",
            normalized["secondary_structure"],
        ),
        sasa=cast("tuple[float | None, ...] | None", normalized["sasa"]),
        function_annotations=tuple(annotations),
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
    validate_canonical_function_annotations(value.function_annotations)
    addressed = {
        residue_id
        for annotation in value.function_annotations
        for residue_id in (
            annotation.start_residue_id,
            annotation.end_residue_id,
        )
    }
    unknown = addressed - set(layout.residue_ids)
    if unknown:
        raise ValueError(
            "function annotations address residue identities outside the "
            "prompt layout"
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
