"""Exact Workbench-to-Biohub ESM-3 translation and response validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datatypes import FunctionAnnotation, ProteinPrompt, ProteinSequence
from modules.prompt_authoring.prompts import validate_protein_prompt


_ATOM37_INDEX = {
    atom_name: index
    for index, atom_name in enumerate(
        (
            "N",
            "CA",
            "C",
            "CB",
            "O",
            "CG",
            "CG1",
            "CG2",
            "OG",
            "OG1",
            "SG",
            "CD",
            "CD1",
            "CD2",
            "ND1",
            "ND2",
            "OD1",
            "OD2",
            "SD",
            "CE",
            "CE1",
            "CE2",
            "CE3",
            "NE",
            "NE1",
            "NE2",
            "OE1",
            "OE2",
            "CH2",
            "NH1",
            "NH2",
            "OH",
            "CZ",
            "CZ2",
            "CZ3",
            "NZ",
            "OXT",
        )
    )
}
_PROVIDER_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYXBZUO")
_PROVIDER_SS8 = frozenset("GHITEBSC")


def _sequence_track(prompt: ProteinPrompt) -> str:
    values = (
        [None] * prompt.num_residues
        if prompt.sequence_track is None
        else prompt.sequence_track.values
    )
    symbols: list[str] = []
    for position, value in enumerate(values):
        if value is None:
            symbols.append("_")
            continue
        if (
            type(value) is not str
            or value not in _PROVIDER_SEQUENCE_ALPHABET
        ):
            raise ValueError(
                f"ESM-3 cannot represent sequence symbol {value!r} "
                f"at residue {position}"
            )
        symbols.append(value)
    return "".join(symbols)


def _secondary_structure_track(
    prompt: ProteinPrompt,
) -> str | None:
    if prompt.secondary_structure_track is None:
        return None
    symbols: list[str] = []
    for position, value in enumerate(
        prompt.secondary_structure_track.values
    ):
        if value is None:
            symbols.append("_")
            continue
        if value == "-":
            symbols.append("C")
            continue
        if type(value) is not str or value not in _PROVIDER_SS8:
            raise ValueError(
                "ESM-3 cannot represent secondary-structure symbol "
                f"{value!r} at residue {position}"
            )
        symbols.append(value)
    return "".join(symbols)


def _sasa_track(prompt: ProteinPrompt) -> list[float | None] | None:
    if prompt.sasa_track is None:
        return None
    return [
        None if value is None else float(value)
        for value in prompt.sasa_track.values
    ]


def _coordinates(prompt: ProteinPrompt) -> Any | None:
    if prompt.structure_track is None:
        return None
    import torch

    visibility = (
        [True] * prompt.num_residues
        if prompt.structure_visibility_track is None
        else [
            value is True
            for value in prompt.structure_visibility_track.values
        ]
    )
    coordinates = torch.full(
        (prompt.num_residues, 37, 3),
        float("nan"),
        dtype=torch.float32,
    )
    any_visible_atom = False
    for position, (residue, is_visible) in enumerate(
        zip(
            prompt.structure_track.values,
            visibility,
            strict=True,
        )
    ):
        if residue is None or not is_visible:
            continue
        if not isinstance(residue, Mapping):
            raise ValueError(
                f"ESM-3 structure residue {position} is not a named-atom map"
            )
        for atom_name, raw_coordinate in residue.items():
            atom_index = _ATOM37_INDEX.get(atom_name)
            if atom_index is None:
                raise ValueError(
                    f"ESM-3 atom37 cannot represent atom {atom_name!r} "
                    f"at residue {position}"
                )
            coordinates[position, atom_index] = torch.tensor(
                raw_coordinate,
                dtype=torch.float32,
            )
            any_visible_atom = True
    return coordinates if any_visible_atom else None


def _function_annotations(prompt: ProteinPrompt) -> list[Any] | None:
    if not prompt.function_annotations.annotations:
        return None
    from esm.utils.types import FunctionAnnotation as ProviderFunctionAnnotation

    result: list[Any] = []
    for annotation in prompt.function_annotations.annotations:
        if type(annotation) is not FunctionAnnotation:
            raise ValueError(
                "ESM-3 function annotations must be canonical values"
            )
        result.append(
            ProviderFunctionAnnotation(
                label=annotation.label,
                start=annotation.start,
                end=annotation.end,
            )
        )
    return result


def protein_prompt_to_provider(prompt: object) -> Any:
    """Translate one exact ProteinPrompt without silently mutating tracks."""
    source = validate_protein_prompt(prompt)
    if "," in source.target_layout.chain_id:
        raise ValueError(
            "The locked ESM SDK cannot preserve multi-chain aligned tracks"
        )
    from esm.sdk.api import ESMProtein

    return ESMProtein(
        sequence=_sequence_track(source),
        secondary_structure=_secondary_structure_track(source),
        sasa=_sasa_track(source),
        function_annotations=_function_annotations(source),
        coordinates=_coordinates(source),
    )


def generation_config(
    track: str,
    parameters: Mapping[str, Any],
) -> Any:
    """Build only the exact provider operation declared by the Node Type."""
    if track not in {"sequence", "structure"}:
        raise ValueError("ESM-3 generation track is not declared")
    from esm.sdk.api import GenerationConfig

    return GenerationConfig(
        track=track,
        num_steps=parameters["num_steps"],
        temperature=parameters["temperature"],
        top_p=parameters["top_p"],
        schedule=parameters["schedule"],
        strategy=parameters["strategy"],
        temperature_annealing=parameters["temperature_annealing"],
        condition_on_coordinates_only=True,
    )


def require_provider_protein(result: Any, operation: str) -> Any:
    """Reject provider error values before post-processing."""
    from esm.sdk.api import ESMProteinError

    if isinstance(result, ESMProteinError):
        raise RuntimeError(
            f"ESM-3 provider operation {operation} failed with a provider error"
        )
    return result


def complete_sequence(
    result: Any,
    prompt: ProteinPrompt,
) -> ProteinSequence:
    """Validate one complete provider sequence on the exact Prompt axis."""
    sequence = getattr(result, "sequence", None)
    if not isinstance(sequence, str) or not sequence:
        raise ValueError("ESM-3 provider response has no complete sequence")
    if (
        len(sequence) != prompt.num_residues
        or any(
            symbol not in _PROVIDER_SEQUENCE_ALPHABET
            for symbol in sequence
        )
    ):
        raise ValueError(
            "ESM-3 provider sequence is incomplete or misaligned"
        )
    layout = prompt.target_layout
    assert layout is not None and layout.residue_ids is not None
    return ProteinSequence(
        sequence=sequence,
        residue_ids=list(layout.residue_ids),
    )


def response_has_structure(result: Any) -> bool:
    return getattr(result, "coordinates", None) is not None


def reject_silent_sequence_fields(result: Any) -> None:
    """Do not discard confidence without a corresponding structure output."""
    if response_has_structure(result):
        return
    unexpected = [
        name
        for name in ("ptm", "plddt", "pae")
        if getattr(result, name, None) is not None
    ]
    if unexpected:
        raise ValueError(
            "ESM-3 sequence response contains confidence without structure"
        )
