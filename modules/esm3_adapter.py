"""ESM3 adapter: translates between workbench ProteinPrompt and ESM SDK ESMProtein."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import torch

from datatypes import (
    Candidate,
    CandidateCollection,
    FunctionAnnotations,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
    ResidueTrack,
    Score,
    ScoreCollection,
)

_MASKED_COORD = float("nan")
_ATOM37_INDEX = {
    atom_name: index
    for index, atom_name in enumerate(
        (
            "N", "CA", "C", "CB", "O", "CG", "CG1", "CG2", "OG", "OG1",
            "SG", "CD", "CD1", "CD2", "ND1", "ND2", "OD1", "OD2", "SD",
            "CE", "CE1", "CE2", "CE3", "NE", "NE1", "NE2", "OE1", "OE2",
            "CH2", "NH1", "NH2", "OH", "CZ", "CZ2", "CZ3", "NZ", "OXT",
        )
    )
}

# ESM3 SS8 vocabulary. DSSP "-" is not accepted as an ESM3 SS8 symbol;
# callers must explicitly represent coil as "C".
_ESM3_SS8 = frozenset("GHITEBSC")
_ESM3_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYXBZUO")


def _sequence_track_to_str(track: ResidueTrack | None) -> str | None:
    """Convert a sequence track without applying another track's vocabulary."""
    if track is None:
        return None
    chars = []
    for position, value in enumerate(track.values):
        if value is track.sentinel:
            chars.append("_")
            continue
        symbol = str(value)
        if symbol not in _ESM3_SEQUENCE_ALPHABET:
            raise ValueError(
                "sequence_track has unsupported amino-acid symbol "
                f"{symbol!r} at position {position}"
            )
        chars.append(symbol)
    return "".join(chars)


def _secondary_structure_track_to_str(
    track: ResidueTrack | None,
) -> str | None:
    """Convert an SS8 track, with unspecified positions represented as masks."""
    if track is None:
        return None
    chars = []
    for position, value in enumerate(track.values):
        if value is track.sentinel:
            chars.append("_")
        else:
            symbol = str(value)
            if symbol not in _ESM3_SS8:
                raise ValueError(
                    "secondary_structure_track has unsupported SS8 symbol "
                    f"{symbol!r} at position {position}"
                )
            chars.append(symbol)
    return "".join(chars)


def _track_to_float_list(
    track: ResidueTrack | None,
) -> list[float | None] | None:
    """Convert a ResidueTrack to a list of floats, with sentinels as None."""
    if track is None:
        return None
    result: list[float | None] = []
    for v in track.values:
        if v is track.sentinel:
            result.append(None)
        else:
            result.append(float(v))
    return result


def protein_prompt_to_esm_protein(prompt: ProteinPrompt) -> Any:
    """Convert a ProteinPrompt to an ESM SDK ESMProtein."""
    from esm.sdk.api import ESMProtein as ESMProteinSDK

    n = prompt.num_residues
    if n == 0:
        raise ValueError("ProteinPrompt has no target layout (num_residues=0)")

    tracks = (
        ("sequence_track", prompt.sequence_track),
        ("structure_track", prompt.structure_track),
        ("structure_visibility_track", prompt.structure_visibility_track),
        ("secondary_structure_track", prompt.secondary_structure_track),
        ("sasa_track", prompt.sasa_track),
    )
    for track_name, track in tracks:
        if track is not None and len(track) != n:
            raise ValueError(
                f"{track_name} length {len(track)} "
                f"!= target layout length {n}"
            )

    sequence = _sequence_track_to_str(prompt.sequence_track)
    if sequence is None:
        sequence = "_" * n
    secondary_structure = _secondary_structure_track_to_str(
        prompt.secondary_structure_track
    )
    sasa = _track_to_float_list(prompt.sasa_track)

    # Coordinates: preserve named template atoms in ESM3's atom37 layout.
    coordinates = None
    structure_track = prompt.structure_track
    if structure_track is not None:
        coord_values: list[Any | None] = [
            None if value is structure_track.sentinel else value
            for value in structure_track.values
        ]

        visible_values = [True] * n
        visibility_track = prompt.structure_visibility_track
        if visibility_track is not None:
            visible_values = [
                value is not visibility_track.sentinel and bool(value)
                for value in visibility_track.values
            ]

        has_coords = any(
            coord is not None and visible
            for coord, visible in zip(coord_values, visible_values, strict=True)
        )
        if has_coords:
            coords_37 = torch.full((n, 37, 3), _MASKED_COORD)
            for i, (c, visible) in enumerate(
                zip(coord_values, visible_values, strict=True)
            ):
                if c is None or not visible:
                    continue
                if isinstance(c, Mapping):
                    for atom_name, atom_coordinates in c.items():
                        atom_index = _ATOM37_INDEX.get(str(atom_name))
                        if atom_index is None:
                            continue
                        coords_37[i, atom_index] = torch.tensor(
                            atom_coordinates, dtype=coords_37.dtype
                        )
                else:
                    coords_37[i, _ATOM37_INDEX["CA"]] = torch.tensor(
                        c, dtype=coords_37.dtype
                    )
            coordinates = coords_37

    # Function annotations
    fa_list = None
    if prompt.function_annotations is not None and len(prompt.function_annotations) > 0:
        from esm.utils.types import FunctionAnnotation as ESMFA
        fa_list = [
            ESMFA(label=a["label"], start=a["start"], end=a["end"])
            for a in prompt.function_annotations.annotations
        ]

    return ESMProteinSDK(
        sequence=sequence,
        secondary_structure=secondary_structure,
        sasa=sasa,
        function_annotations=fa_list,
        coordinates=coordinates,
    )


def esm_protein_to_sequence(esm_protein: Any) -> ProteinSequence:
    """Extract a ProteinSequence from a generated ESMProtein."""
    seq = getattr(esm_protein, "sequence", None)
    if seq is None:
        raise ValueError("Generated ESMProtein has no sequence")
    return ProteinSequence(sequence=str(seq))


def esm_protein_to_structure(esm_protein: Any) -> ProteinStructure:
    """Extract a ProteinStructure (PDB string) from a generated ESMProtein."""
    pdb_str = esm_protein.to_pdb_string()
    return ProteinStructure(pdb_string=pdb_str)


def esm_protein_to_scores(
    esm_protein: Any, candidate_id: str
) -> ScoreCollection:
    """Extract pTM and pLDDT scores, normalizing pTM (1,)→scalar."""
    entries: list[Score] = []

    ptm = getattr(esm_protein, "ptm", None)
    if ptm is not None:
        if isinstance(ptm, torch.Tensor):
            ptm_val = float(ptm.detach().cpu().flatten()[0])
        else:
            ptm_val = float(ptm)
        entries.append(Score(score_id="ptm", value=ptm_val, subjects=[candidate_id]))

    plddt = getattr(esm_protein, "plddt", None)
    if plddt is not None:
        if isinstance(plddt, torch.Tensor):
            plddt_vals = plddt.detach().cpu().flatten().tolist()
            mean_plddt = sum(plddt_vals) / len(plddt_vals) if plddt_vals else 0.0
        else:
            mean_plddt = float(plddt)
        entries.append(Score(
            score_id="plddt",
            value=mean_plddt,
            subjects=[candidate_id],
            details={"per_residue": plddt_vals if isinstance(plddt, torch.Tensor) else None},
        ))

    return ScoreCollection(
        collection_id=str(uuid.uuid4()),
        entries=entries,
    )


def read_biohub_token(project_dir: str | None = None) -> str:
    """Read Biohub API token from keys/esmkey.txt."""
    candidates = [Path("keys/esmkey.txt")]
    if project_dir:
        candidates.append(Path(project_dir) / ".." / ".." / "keys" / "esmkey.txt")
    for p in candidates:
        if p.exists():
            return p.read_text().strip()
    raise FileNotFoundError(
        "Biohub API key not found. Place your token in keys/esmkey.txt"
    )


def create_esm3_client(
    model_name: str, project_dir: str | None = None
) -> Any:
    """Create an ESM3 inference client.

    Routes to Biohub Forge for Biohub models; local open-weight
    models require the huggingface token from keys/huggingfacekey.txt.
    """
    from esm.sdk import client as esm_client

    local_models = {"esm3_sm_open_v1"}
    if model_name in local_models:
        hf_path = Path("keys/huggingfacekey.txt")
        if project_dir:
            alt = Path(project_dir) / ".." / ".." / "keys" / "huggingfacekey.txt"
            if alt.exists():
                hf_path = alt
        if not hf_path.exists():
            raise FileNotFoundError(
                f"HuggingFace token not found for local model {model_name}. "
                "Place your token in keys/huggingfacekey.txt"
            )
        token = hf_path.read_text().strip()
        return esm_client(model=model_name, token=token)

    token = read_biohub_token(project_dir)
    return esm_client(model=model_name, token=token)
