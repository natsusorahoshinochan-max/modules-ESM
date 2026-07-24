"""Batch TM-score: aligns each candidate structure to reference, computes TM-score."""

import uuid
from pathlib import Path
from typing import Any

import numpy as np

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, ProteinStructure, Score, ScoreCollection

_AA_3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def _parse_pdb_ca(pdb_string: str) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[str, str]],
]:
    """Extract CA coordinates and residue IDs from a PDB string."""
    coords: list[tuple[float, float, float]] = []
    res_ids: list[tuple[str, str]] = []
    for line in pdb_string.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()
        if atom_name != "CA":
            continue
        chain = line[21:22].strip()
        res_seq = line[22:26].strip()
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            continue
        coords.append((x, y, z))
        res_ids.append((chain, res_seq))
    return coords, res_ids


def _compute_tm_score(
    ref_coords: np.ndarray, mob_coords: np.ndarray, n_ref: int
) -> float:
    """Compute TM-score from SVD-superimposed coordinates (same logic as structure.tm_score)."""
    from Bio.SVDSuperimposer import SVDSuperimposer

    sup = SVDSuperimposer()
    sup.set(ref_coords, mob_coords)
    sup.run()

    rmsd = sup.get_rms()
    n_aligned = ref_coords.shape[0]

    if n_aligned > 15:
        d0 = 1.24 * (n_aligned - 15) ** (1.0 / 3.0) - 1.8
    else:
        d0 = 0.5
    d0 = max(d0, 0.5)

    tm = 1.0 / (1.0 + (rmsd / d0) ** 2)
    return float(round(tm, 4))


class BatchTMScoreModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        ref_struct: ProteinStructure | None = inputs.get("reference")
        candidates: CandidateCollection | None = inputs.get("candidates")

        if ref_struct is None:
            raise ValueError("reference input is required")
        if candidates is None:
            raise ValueError("candidates input is required")
        if len(candidates) == 0:
            raise ValueError("candidates collection is empty")

        if candidates.item_type != "protein.structure":
            raise ValueError(
                f"candidates item_type must be protein.structure, got {candidates.item_type}"
            )

        # Parse reference CA coordinates
        ref_coords_raw, ref_ids = _parse_pdb_ca(ref_struct.pdb_string)
        if not ref_coords_raw:
            raise ValueError("No CA atoms found in reference structure")
        ref_index: dict[tuple[str, str], int] = {
            rid: i for i, rid in enumerate(ref_ids)
        }
        n_ref = len(ref_coords_raw)

        entries: list[Score] = []

        for cand in candidates.items:
            struct = cand.data
            if not isinstance(struct, ProteinStructure):
                raise ValueError(
                    f"Candidate {cand.candidate_id} data is not a ProteinStructure"
                )

            mob_coords_raw, mob_ids = _parse_pdb_ca(struct.pdb_string)
            if not mob_coords_raw:
                raise ValueError(
                    f"No CA atoms found in candidate {cand.candidate_id}"
                )

            mob_index: dict[tuple[str, str], int] = {
                rid: i for i, rid in enumerate(mob_ids)
            }

            # Find common residues
            common = sorted(set(ref_index.keys()) & set(mob_index.keys()))
            if not common:
                # No overlap → TM-score is effectively 0
                entries.append(Score(
                    score_id="tm_score",
                    value=0.0,
                    subjects=[cand.candidate_id],
                    details={"aligned_residues": 0},
                ))
                continue

            ref_aligned = np.array(
                [ref_coords_raw[ref_index[k]] for k in common],
                dtype=np.float64,
            )
            mob_aligned = np.array(
                [mob_coords_raw[mob_index[k]] for k in common],
                dtype=np.float64,
            )

            tm = _compute_tm_score(ref_aligned, mob_aligned, n_ref)
            entries.append(Score(
                score_id="tm_score",
                value=tm,
                subjects=[cand.candidate_id],
                details={"aligned_residues": len(common)},
            ))

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
