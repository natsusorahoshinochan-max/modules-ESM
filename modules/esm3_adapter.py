"""ESM3 adapter: translates between workbench ProteinPrompt and ESM SDK ESMProtein."""

from __future__ import annotations

import uuid
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


def _track_to_str(track: ResidueTrack | None, length: int) -> str | None:
    """Convert a ResidueTrack to a string, with None sentinels mapped to '_'."""
    if track is None:
        return None
    chars = []
    for v in track.values:
        if v is None:
            chars.append("_")
        else:
            chars.append(str(v))
    result = "".join(chars)
    if len(result) > length:
        result = result[:length]
    elif len(result) < length:
        result = result + "_" * (length - len(result))
    return result


def _track_to_float_list(
    track: ResidueTrack | None, length: int
) -> list[float | None] | None:
    """Convert a ResidueTrack to a list of floats, with sentinels as None."""
    if track is None:
        return None
    result: list[float | None] = []
    for v in track.values:
        if v is None:
            result.append(None)
        else:
            result.append(float(v))
    if len(result) > length:
        result = result[:length]
    elif len(result) < length:
        result.extend([None] * (length - len(result)))
    return result


def protein_prompt_to_esm_protein(prompt: ProteinPrompt) -> Any:
    """Convert a ProteinPrompt to an ESM SDK ESMProtein."""
    from esm.sdk.api import ESMProtein as ESMProteinSDK

    n = prompt.num_residues
    if n == 0:
        raise ValueError("ProteinPrompt has no target layout (num_residues=0)")

    sequence = _track_to_str(prompt.sequence_track, n)
    if sequence is None:
        sequence = "_" * n
    secondary_structure = _track_to_str(prompt.secondary_structure_track, n)
    sasa = _track_to_float_list(prompt.sasa_track, n)

    # Coordinates: place CA at position 1 in atom37 representation
    coordinates = None
    if prompt.structure_track is not None:
        coord_values: list[tuple[float, float, float] | None] = []
        for v in prompt.structure_track.values:
            coord_values.append(v if v is not None else None)
        if len(coord_values) > n:
            coord_values = coord_values[:n]
        elif len(coord_values) < n:
            coord_values.extend([None] * (n - len(coord_values)))

        has_coords = any(c is not None for c in coord_values)
        if has_coords:
            coords_37 = torch.full((n, 37, 3), _MASKED_COORD)
            for i, c in enumerate(coord_values):
                if c is not None:
                    coords_37[i, 1, 0] = float(c[0])
                    coords_37[i, 1, 1] = float(c[1])
                    coords_37[i, 1, 2] = float(c[2])
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
