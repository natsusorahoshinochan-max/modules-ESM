"""Structure Alignment: superimposes two protein structures using SVD."""

from pathlib import Path
from typing import Any

import numpy as np

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure, StructureAlignment

_AA_3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def _parse_pdb_ca(pdb_string: str) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[str, str]],  # (chain, res_seq) keys
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


def _residue_label(chain: str, res_seq: str) -> str:
    return f"{chain}:{res_seq}"


class StructureAlignModule(WorkflowModule):
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
        mob_struct: ProteinStructure | None = inputs.get("mobile")

        if ref_struct is None:
            raise ValueError("reference input is required")
        if mob_struct is None:
            raise ValueError("mobile input is required")

        ref_coords, ref_ids = _parse_pdb_ca(ref_struct.pdb_string)
        mob_coords, mob_ids = _parse_pdb_ca(mob_struct.pdb_string)

        if not ref_coords:
            raise ValueError("No CA atoms found in reference structure")
        if not mob_coords:
            raise ValueError("No CA atoms found in mobile structure")

        # Build lookup of ref residues by (chain, res_seq)
        ref_index: dict[tuple[str, str], int] = {
            rid: i for i, rid in enumerate(ref_ids)
        }
        mob_index: dict[tuple[str, str], int] = {
            rid: i for i, rid in enumerate(mob_ids)
        }

        # Find common residues
        common_keys = set(ref_index.keys()) & set(mob_index.keys())
        if not common_keys:
            raise ValueError(
                "No common residues found between reference and mobile structures"
            )

        # Build aligned coordinate arrays
        ref_aligned = np.array([
            ref_coords[ref_index[k]] for k in sorted(common_keys)
        ], dtype=np.float64)
        mob_aligned = np.array([
            mob_coords[mob_index[k]] for k in sorted(common_keys)
        ], dtype=np.float64)

        # SVD superposition
        from Bio.SVDSuperimposer import SVDSuperimposer

        sup = SVDSuperimposer()
        sup.set(ref_aligned, mob_aligned)
        sup.run()

        rotation = sup.get_rotran()[0].tolist()
        translation = sup.get_rotran()[1].tolist()
        rmsd = sup.get_rms()
        n_aligned = ref_aligned.shape[0]
        coverage = n_aligned / max(len(ref_coords), len(mob_coords))

        # Build residue map
        residue_map: list[tuple[str, str]] = [
            (_residue_label(k[0], k[1]), _residue_label(k[0], k[1]))
            for k in sorted(common_keys)
        ]

        # Chain map
        ref_chains = {k[0] for k in common_keys}
        mob_chains = {k[0] for k in common_keys}
        chain_map: dict[str, str] = {}
        for ch in sorted(ref_chains & mob_chains):
            chain_map[ch] = ch

        alignment = StructureAlignment(
            residue_map=residue_map,
            chain_map=chain_map,
            rotation=rotation,
            translation=translation,
            rmsd=float(rmsd),
            coverage=float(coverage),
        )

        return {"alignment": alignment}
