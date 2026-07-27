"""ESM3 adapter: translates between workbench ProteinPrompt and ESM SDK ESMProtein."""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from numbers import Real
from pathlib import Path
from typing import Any

import torch

from datatypes import (
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

# ESM3 SS8 vocabulary. DSSP "-" is not accepted as an ESM3 SS8 symbol;
# callers must explicitly represent coil as "C".
_ESM3_SS8 = frozenset("GHITEBSC")
_ESM3_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYXBZUO")


class ESM3ProviderResponseError(ValueError):
    """Structured failure for invalid or incomplete ESM3 provider output."""

    def __init__(
        self,
        *,
        field: str,
        message: str,
        expected: str,
        received: object,
    ) -> None:
        self.code = "esm3_provider_response_invalid"
        self.diagnostic = {
            "code": self.code,
            "field": field,
            "message": message,
            "expected": expected,
            "received": received,
        }
        super().__init__(f"{self.code}: {field}: {message}")


class ESM3ProviderOperationError(RuntimeError):
    """Structured failure returned by the ESM SDK instead of a protein."""

    def __init__(
        self,
        *,
        operation: str,
        provider_error_code: int,
        message: str,
    ) -> None:
        self.code = "esm3_provider_operation_failed"
        self.diagnostic = {
            "code": self.code,
            "operation": operation,
            "provider_error_code": provider_error_code,
            "message": message,
        }
        super().__init__(f"{self.code}: {operation}: {message}")


def require_esm3_provider_result(result: Any, operation: str) -> Any:
    """Reject an SDK error object before output extraction begins."""
    from esm.sdk.api import ESMProteinError

    if isinstance(result, ESMProteinError):
        raise ESM3ProviderOperationError(
            operation=operation,
            provider_error_code=result.error_code,
            message=result.error_msg,
        )
    return result


def call_esm3_provider(
    client: Any,
    protein: Any,
    config: Any,
    operation: str,
    *,
    context: "RunContext | None" = None,
    model_name: str | None = None,
) -> Any:
    """Execute one ESM3 operation and normalize SDK error signaling."""
    from esm.sdk.api import ESMProteinError

    try:
        if context is not None:
            context.record_provider_call(
                "local_open"
                if model_name == "esm3_sm_open_v1"
                else "biohub",
                operation,
                model=model_name,
            )
        result = client.generate(protein, config)
    except ESMProteinError as error:
        raise ESM3ProviderOperationError(
            operation=operation,
            provider_error_code=error.error_code,
            message=error.error_msg,
        ) from error
    return require_esm3_provider_result(result, operation)


def esm3_candidate_metadata(
    *,
    model_name: str,
    operation: str,
    sample_index: int,
    classification: str,
) -> dict[str, object]:
    """Build the shared provider provenance carried by every ESM3 Candidate."""
    provider = "local_open" if model_name == "esm3_sm_open_v1" else "biohub"
    return {
        "provider": provider,
        "model": model_name,
        "operation": operation,
        "sample_index": sample_index,
        "classification": classification,
    }


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
                f"{track_name} length {len(track)} != target layout length {n}"
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


def esm_protein_to_sequence(
    esm_protein: Any,
    expected_length: int | None = None,
) -> ProteinSequence:
    """Extract a ProteinSequence from a generated ESMProtein."""
    seq = getattr(esm_protein, "sequence", None)
    if seq is None:
        raise ESM3ProviderResponseError(
            field="sequence",
            message="sequence operation returned no sequence",
            expected="non-empty amino-acid sequence",
            received={"value": None},
        )
    if not isinstance(seq, str) or not seq:
        raise ESM3ProviderResponseError(
            field="sequence",
            message="provider sequence is not non-empty text",
            expected="non-empty amino-acid sequence",
            received={"type": type(seq).__name__},
        )
    if expected_length is not None and len(seq) != expected_length:
        raise ESM3ProviderResponseError(
            field="sequence",
            message="provider sequence is not aligned to the target residue axis",
            expected=f"length {expected_length}",
            received={"length": len(seq)},
        )
    return ProteinSequence(sequence=seq)


def structure_sampling_input(
    sequence_result: Any,
    original_prompt: Any,
) -> Any:
    """Build a structure-track prompt without carrying template coordinates."""
    from esm.sdk.api import ESMProtein as ESMProteinSDK

    sequence = esm_protein_to_sequence(sequence_result).sequence
    return ESMProteinSDK(
        sequence=sequence,
        secondary_structure=getattr(original_prompt, "secondary_structure", None),
        sasa=getattr(original_prompt, "sasa", None),
        function_annotations=getattr(original_prompt, "function_annotations", None),
        coordinates=None,
    )


def validate_esm3_structure_response(
    esm_protein: Any,
    *,
    expected_sequence: str | None = None,
    expected_length: int | None = None,
) -> None:
    """Validate the sequence, residue, atom, and coordinate axes of a structure."""
    sequence = getattr(esm_protein, "sequence", None)
    if not isinstance(sequence, str) or not sequence:
        raise ESM3ProviderResponseError(
            field="sequence",
            message="structure operation returned no sequence residue axis",
            expected="non-empty amino-acid sequence",
            received={"type": type(sequence).__name__},
        )
    if expected_sequence is not None and sequence != expected_sequence:
        raise ESM3ProviderResponseError(
            field="sequence",
            message="structure response is not paired to its sampled sequence",
            expected=expected_sequence,
            received={"value": sequence},
        )
    if expected_length is not None and len(sequence) != expected_length:
        raise ESM3ProviderResponseError(
            field="sequence",
            message="structure response is not aligned to the target residue axis",
            expected=f"length {expected_length}",
            received={"length": len(sequence)},
        )
    coordinates = getattr(esm_protein, "coordinates", None)
    if coordinates is None:
        raise ESM3ProviderResponseError(
            field="coordinates",
            message="structure operation returned no coordinates",
            expected="coordinates with shape (L,37,3)",
            received={"value": None},
        )
    if not isinstance(coordinates, torch.Tensor):
        raise ESM3ProviderResponseError(
            field="coordinates",
            message="coordinates are not a tensor",
            expected="coordinates with shape (L,37,3)",
            received={"type": type(coordinates).__name__},
        )
    coordinate_shape = (len(sequence), 37, 3)
    if tuple(coordinates.shape) != coordinate_shape:
        raise ESM3ProviderResponseError(
            field="coordinates",
            message="unexpected coordinate residue or atom axes",
            expected=f"({len(sequence)},37,3)",
            received={"shape": list(coordinates.shape)},
        )


def esm_protein_to_structure(
    esm_protein: Any,
    expected_sequence: str | None = None,
    expected_length: int | None = None,
) -> ProteinStructure:
    """Extract a validated ProteinStructure (PDB string)."""
    validate_esm3_structure_response(
        esm_protein,
        expected_sequence=expected_sequence,
        expected_length=expected_length,
    )
    pdb_str = esm_protein.to_pdb_string()
    if not isinstance(pdb_str, str) or not pdb_str.strip():
        raise ESM3ProviderResponseError(
            field="pdb_string",
            message="structure serialization returned no PDB text",
            expected="non-empty canonical PDB string",
            received={"type": type(pdb_str).__name__},
        )
    return ProteinStructure(pdb_string=pdb_str, source="esm3")


def esm_protein_to_scores(
    esm_protein: Any,
    candidate_id: str,
    *,
    require_structure_metrics: bool = False,
) -> ScoreCollection:
    """Extract documented ESM3 metrics without generic shape coercion."""
    entries: list[Score] = []
    sequence = getattr(esm_protein, "sequence", None)
    sequence_length = len(sequence) if sequence is not None else None

    ptm = getattr(esm_protein, "ptm", None)
    if require_structure_metrics and ptm is None:
        raise ESM3ProviderResponseError(
            field="ptm",
            message="structure operation returned no pTM",
            expected="dimensionless scalar or tensor with shape (1,)",
            received={"value": None},
        )
    if ptm is not None:
        if isinstance(ptm, torch.Tensor):
            if tuple(ptm.shape) == ():
                ptm_val = float(ptm.detach().cpu().item())
            elif tuple(ptm.shape) == (1,):
                ptm_val = float(ptm.detach().cpu()[0].item())
            else:
                raise ESM3ProviderResponseError(
                    field="ptm",
                    message="unexpected pTM shape",
                    expected="scalar or (1,)",
                    received={"shape": list(ptm.shape)},
                )
        elif isinstance(ptm, Real) and not isinstance(ptm, bool):
            ptm_val = float(ptm)
        else:
            raise ESM3ProviderResponseError(
                field="ptm",
                message="pTM is not numeric",
                expected="dimensionless scalar or tensor with shape (1,)",
                received={"type": type(ptm).__name__},
            )
        if not math.isfinite(ptm_val) or not 0.0 <= ptm_val <= 1.0:
            raise ESM3ProviderResponseError(
                field="ptm",
                message="pTM must be finite and within [0, 1]",
                expected="dimensionless value in [0, 1]",
                received={"value": ptm_val},
            )
        entries.append(
            Score(
                score_id="ptm",
                value=ptm_val,
                subjects=[candidate_id],
                details={"units": "dimensionless", "residue_axes": []},
            )
        )

    plddt = getattr(esm_protein, "plddt", None)
    if require_structure_metrics and plddt is None:
        raise ESM3ProviderResponseError(
            field="plddt",
            message="structure operation returned no pLDDT",
            expected=f"per-residue tensor with shape ({sequence_length},)",
            received={"value": None},
        )
    if plddt is not None:
        if isinstance(plddt, torch.Tensor):
            if require_structure_metrics and tuple(plddt.shape) != (sequence_length,):
                raise ESM3ProviderResponseError(
                    field="plddt",
                    message="unexpected pLDDT residue axis",
                    expected=f"({sequence_length},)",
                    received={"shape": list(plddt.shape)},
                )
            plddt_vals = plddt.detach().cpu().flatten().tolist()
            if (
                not torch.isfinite(plddt.detach()).all()
                or bool((plddt.detach() < 0).any())
                or bool((plddt.detach() > 1).any())
            ):
                raise ESM3ProviderResponseError(
                    field="plddt",
                    message="pLDDT must contain finite values within [0, 1]",
                    expected="dimensionless confidence values in [0, 1]",
                    received={"shape": list(plddt.shape)},
                )
            mean_plddt = sum(plddt_vals) / len(plddt_vals) if plddt_vals else 0.0
        elif require_structure_metrics:
            raise ESM3ProviderResponseError(
                field="plddt",
                message="pLDDT is not a per-residue tensor",
                expected=f"per-residue tensor with shape ({sequence_length},)",
                received={"type": type(plddt).__name__},
            )
        else:
            mean_plddt = float(plddt)
            plddt_vals = None
        if not math.isfinite(mean_plddt) or not 0.0 <= mean_plddt <= 1.0:
            raise ESM3ProviderResponseError(
                field="plddt",
                message="pLDDT must be finite and within [0, 1]",
                expected="dimensionless confidence values in [0, 1]",
                received={"mean": mean_plddt},
            )
        entries.append(
            Score(
                score_id="plddt",
                value=mean_plddt,
                subjects=[candidate_id],
                details={
                    "per_residue": (
                        plddt_vals if isinstance(plddt, torch.Tensor) else None
                    ),
                    "units": "dimensionless",
                    "residue_axes": ["sequence_residue"],
                },
            )
        )

    pae = getattr(esm_protein, "pae", None)
    if pae is not None:
        if sequence_length is None:
            raise ESM3ProviderResponseError(
                field="pae",
                message="PAE residue axes cannot be validated without a sequence",
                expected="response sequence defining L residues",
                received={"sequence": None},
            )
        if not isinstance(pae, torch.Tensor):
            raise ESM3ProviderResponseError(
                field="pae",
                message="PAE is not a tensor",
                expected=f"(L,L) or (1,L+2,L+2) tensor for L={sequence_length}",
                received={"type": type(pae).__name__},
            )
        pae_tensor = pae.detach().cpu()
        shape = tuple(pae_tensor.shape)
        if shape == (sequence_length, sequence_length):
            normalized_pae = pae_tensor
        elif shape == (
            1,
            sequence_length + 2,
            sequence_length + 2,
        ):
            normalized_pae = pae_tensor[0, 1:-1, 1:-1]
        else:
            raise ESM3ProviderResponseError(
                field="pae",
                message="unexpected PAE shape or residue axes",
                expected=(
                    f"({sequence_length},{sequence_length}) or "
                    f"(1,{sequence_length + 2},{sequence_length + 2})"
                ),
                received={"shape": list(shape)},
            )
        if not torch.isfinite(normalized_pae).all() or bool((normalized_pae < 0).any()):
            raise ESM3ProviderResponseError(
                field="pae",
                message="PAE must contain finite non-negative distances",
                expected="angstrom distances >= 0",
                received={"shape": list(normalized_pae.shape)},
            )
        matrix = normalized_pae.tolist()
        entries.append(
            Score(
                score_id="pae",
                value=float(normalized_pae.to(dtype=torch.float64).mean().item()),
                subjects=[candidate_id],
                details={
                    "matrix": matrix,
                    "units": "angstrom",
                    "residue_axes": [
                        "sequence_residue",
                        "sequence_residue",
                    ],
                    "summary": "mean",
                },
            )
        )

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


def create_esm3_client(model_name: str, project_dir: str | None = None) -> Any:
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
