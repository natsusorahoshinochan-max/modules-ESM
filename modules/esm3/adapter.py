"""Exact Workbench-to-Biohub ESM-3 translation and response validation."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
from typing import Any

from datatypes import (
    FunctionAnnotation,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
)
from modules.prompt_authoring.prompts import validate_protein_prompt


ESM_SDK_REVISION = "917af90b624535eed1e072d343c717e3ec11fef4"
BIOHUB_ESM3_MEDIUM_MODEL = "esm3-medium-2024-08"
BIOHUB_ESM3_OPEN_MODEL = "esm3-open-2024-03"
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
_PDB_TO_SEQUENCE = {
    "ALA": "A",
    "ARG": "R",
    "ASX": "B",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "GLX": "Z",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "PYL": "O",
    "SEC": "U",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "UNK": "X",
}


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


def require_sequence_mask(provider_prompt: Any) -> None:
    """Fail before a remote sequence call that the provider cannot sample."""
    sequence = getattr(provider_prompt, "sequence", None)
    if not isinstance(sequence, str) or "_" not in sequence:
        raise ValueError(
            "ESM-3 sequence generation requires at least one masked residue"
        )


def require_provider_protein(result: Any, operation: str) -> Any:
    """Reject provider error values before post-processing."""
    from esm.sdk.api import ESMProteinError

    if isinstance(result, ESMProteinError):
        raise RuntimeError(
            f"ESM-3 provider operation {operation} failed with a provider error"
        )
    return result


def call_remote_provider(
    client: Any,
    protein: Any,
    config: Any,
    operation: str,
) -> Any:
    """Cross only the remote engine boundary and classify its return."""
    from esm.sdk.api import ESMProteinError

    try:
        result = client.generate(protein, config)
    except ESMProteinError as error:
        raise RuntimeError(
            f"ESM-3 provider operation {operation} failed"
        ) from error
    return require_provider_protein(result, operation)


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


def complete_structure(
    result: Any,
    prompt: ProteinPrompt,
    *,
    expected_sequence: str,
) -> ProteinStructure:
    """Validate provider coordinates and serialized residues before publication."""
    sequence = complete_sequence(result, prompt).sequence
    if sequence != expected_sequence:
        raise ValueError(
            "ESM-3 structure response is not the exact requested sequence"
        )
    coordinates = getattr(result, "coordinates", None)
    try:
        shape = tuple(coordinates.shape)
    except (AttributeError, TypeError) as error:
        raise ValueError(
            "ESM-3 structure response has no coordinate tensor"
        ) from error
    if shape != (prompt.num_residues, 37, 3):
        raise ValueError(
            "ESM-3 coordinates do not match the exact atom37 residue axis"
        )
    try:
        import torch

        backbone = coordinates[:, (0, 1, 2), :]
        complete_backbone = bool(torch.isfinite(backbone).all())
    except (AttributeError, IndexError, TypeError) as error:
        raise ValueError("ESM-3 coordinates are not a valid tensor") from error
    if not complete_backbone:
        raise ValueError(
            "ESM-3 structure response lacks complete N, CA, and C coordinates"
        )
    try:
        pdb_string = result.to_pdb_string()
    except Exception as error:
        raise ValueError(
            "ESM-3 structure response could not be serialized"
        ) from error
    if not isinstance(pdb_string, str) or not pdb_string.strip():
        raise ValueError("ESM-3 structure response has no PDB text")
    residues: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in pdb_string.splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27:
            continue
        identity = (line[21], line[22:26], line[26])
        if identity in seen:
            continue
        seen.add(identity)
        residue_name = line[17:20].strip()
        symbol = _PDB_TO_SEQUENCE.get(residue_name)
        if symbol is None:
            raise ValueError(
                "ESM-3 PDB contains an unsupported protein residue"
            )
        residues.append((*identity, symbol))
    if (
        len(residues) != prompt.num_residues
        or "".join(residue[3] for residue in residues) != sequence
    ):
        raise ValueError(
            "ESM-3 PDB residue identities contradict the response sequence"
        )
    return ProteinStructure(pdb_string=pdb_string, source="esm3")


def normalized_confidence(
    result: Any,
    *,
    residue_count: int,
) -> tuple[float, list[float], float, list[list[float]] | None]:
    """Normalize only exact documented ESM-3 confidence shapes."""
    import torch

    raw_ptm = getattr(result, "ptm", None)
    if isinstance(raw_ptm, torch.Tensor):
        if tuple(raw_ptm.shape) == ():
            ptm = float(raw_ptm.detach().cpu().item())
        elif tuple(raw_ptm.shape) == (1,):
            ptm = float(raw_ptm.detach().cpu()[0].item())
        else:
            raise ValueError("ESM-3 pTM has an undocumented shape")
    elif (
        isinstance(raw_ptm, (int, float))
        and not isinstance(raw_ptm, bool)
    ):
        ptm = float(raw_ptm)
    else:
        raise ValueError("ESM-3 structure response has no scalar pTM")
    if not math.isfinite(ptm) or not 0 <= ptm <= 1:
        raise ValueError("ESM-3 pTM is outside its native [0, 1] scale")

    raw_plddt = getattr(result, "plddt", None)
    if (
        not isinstance(raw_plddt, torch.Tensor)
        or tuple(raw_plddt.shape) != (residue_count,)
        or not bool(torch.isfinite(raw_plddt).all())
        or bool((raw_plddt < 0).any())
        or bool((raw_plddt > 1).any())
    ):
        raise ValueError(
            "ESM-3 pLDDT must be one native [0, 1] value per residue"
        )
    per_residue = [
        float(value) * 100.0
        for value in raw_plddt.detach().cpu().tolist()
    ]
    mean_residue = math.fsum(per_residue) / residue_count

    raw_pae = getattr(result, "pae", None)
    pae: list[list[float]] | None = None
    if raw_pae is not None:
        if not isinstance(raw_pae, torch.Tensor):
            raise ValueError("ESM-3 PAE is not a tensor")
        shape = tuple(raw_pae.shape)
        if shape == (residue_count, residue_count):
            normalized = raw_pae.detach().cpu()
        elif shape == (1, residue_count + 2, residue_count + 2):
            normalized = raw_pae.detach().cpu()[0, 1:-1, 1:-1]
        else:
            raise ValueError("ESM-3 PAE has an undocumented shape")
        if (
            not bool(torch.isfinite(normalized).all())
            or bool((normalized < 0).any())
            or bool((normalized > 31.75).any())
        ):
            raise ValueError(
                "ESM-3 PAE is outside the locked angstrom scale"
            )
        pae = [
            [float(value) for value in row]
            for row in normalized.tolist()
        ]
    return ptm, per_residue, mean_residue, pae


def structure_prompt_for_sequence(
    provider_prompt: Any,
    sequence: str,
) -> Any:
    """Preserve every non-structure condition for one paired structure call."""
    from esm.sdk.api import ESMProtein

    return ESMProtein(
        sequence=sequence,
        secondary_structure=getattr(
            provider_prompt,
            "secondary_structure",
            None,
        ),
        sasa=getattr(provider_prompt, "sasa", None),
        function_annotations=getattr(
            provider_prompt,
            "function_annotations",
            None,
        ),
        coordinates=getattr(provider_prompt, "coordinates", None),
    )


def derived_call_seed(
    effective_seed: int,
    sample_index: int,
    track: str,
) -> int:
    """Derive one stable per-slot identity even though Biohub cannot apply it."""
    digest = hashlib.sha256(
        (
            "protein-workbench-esm3-call-seed/v2:"
            f"{effective_seed}:{sample_index}:{track}"
        ).encode("ascii")
    ).digest()
    return int.from_bytes(digest[:6], "big")
