"""Pairwise Structure Alignment: index-matched SVD alignment of two CandidateCollections."""

import uuid
from pathlib import Path
from typing import Any

import numpy as np

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import Candidate, CandidateCollection, ProteinStructure, StructureAlignment


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


def _residue_label(chain: str, res_seq: str) -> str:
    return f"{chain}:{res_seq}"


def _align_pair(
    ref_struct: ProteinStructure,
    mob_struct: ProteinStructure,
) -> StructureAlignment:
    """Perform SVD superposition of mobile onto reference, return StructureAlignment."""
    ref_coords, ref_ids = _parse_pdb_ca(ref_struct.pdb_string)
    mob_coords, mob_ids = _parse_pdb_ca(mob_struct.pdb_string)

    if not ref_coords:
        raise ValueError("No CA atoms found in reference structure")
    if not mob_coords:
        raise ValueError("No CA atoms found in mobile structure")

    ref_index: dict[tuple[str, str], int] = {rid: i for i, rid in enumerate(ref_ids)}
    mob_index: dict[tuple[str, str], int] = {rid: i for i, rid in enumerate(mob_ids)}

    common_keys = sorted(set(ref_index.keys()) & set(mob_index.keys()))

    if not common_keys:
        # No common residues → return zero alignment
        return StructureAlignment(
            residue_map=[],
            chain_map={},
            rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            translation=[0, 0, 0],
            rmsd=0.0,
            coverage=0.0,
        )

    ref_aligned = np.array(
        [ref_coords[ref_index[k]] for k in common_keys], dtype=np.float64
    )
    mob_aligned = np.array(
        [mob_coords[mob_index[k]] for k in common_keys], dtype=np.float64
    )

    from Bio.SVDSuperimposer import SVDSuperimposer

    sup = SVDSuperimposer()
    sup.set(ref_aligned, mob_aligned)
    sup.run()

    rotation = sup.get_rotran()[0].tolist()
    translation = sup.get_rotran()[1].tolist()
    rmsd = sup.get_rms()
    n_aligned = ref_aligned.shape[0]
    coverage = n_aligned / max(len(ref_coords), len(mob_coords))

    residue_map: list[tuple[str, str]] = [
        (_residue_label(k[0], k[1]), _residue_label(k[0], k[1]))
        for k in common_keys
    ]

    ref_chains = {k[0] for k in common_keys}
    mob_chains = {k[0] for k in common_keys}
    chain_map: dict[str, str] = {}
    for ch in sorted(ref_chains & mob_chains):
        chain_map[ch] = ch

    return StructureAlignment(
        residue_map=residue_map,
        chain_map=chain_map,
        rotation=rotation,
        translation=translation,
        rmsd=float(rmsd),
        coverage=float(coverage),
    )


class PairwiseAlignModule(WorkflowModule):
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
        ref_coll: CandidateCollection | None = inputs.get("reference_candidates")
        mob_coll: CandidateCollection | None = inputs.get("mobile_candidates")

        if ref_coll is None:
            raise ValueError("reference_candidates input is required")
        if mob_coll is None:
            raise ValueError("mobile_candidates input is required")

        if len(ref_coll) == 0:
            raise ValueError("reference_candidates collection is empty")
        if len(mob_coll) == 0:
            raise ValueError("mobile_candidates collection is empty")

        if len(ref_coll) != len(mob_coll):
            raise ValueError(
                f"Collections must have equal length: "
                f"reference has {len(ref_coll)}, mobile has {len(mob_coll)}"
            )

        if ref_coll.item_type != "protein.structure":
            raise ValueError(
                f"reference_candidates item_type must be protein.structure, "
                f"got {ref_coll.item_type}"
            )
        if mob_coll.item_type != "protein.structure":
            raise ValueError(
                f"mobile_candidates item_type must be protein.structure, "
                f"got {mob_coll.item_type}"
            )

        alignment_candidates: list[Candidate] = []

        for ref_item, mob_item in zip(ref_coll.items, mob_coll.items):
            ref_struct = ref_item.data
            mob_struct = mob_item.data

            if not isinstance(ref_struct, ProteinStructure):
                raise ValueError(
                    f"Reference candidate {ref_item.candidate_id} data "
                    f"is not a ProteinStructure"
                )
            if not isinstance(mob_struct, ProteinStructure):
                raise ValueError(
                    f"Mobile candidate {mob_item.candidate_id} data "
                    f"is not a ProteinStructure"
                )

            alignment = _align_pair(ref_struct, mob_struct)

            alignment_candidates.append(
                Candidate(
                    candidate_id=ref_item.candidate_id,
                    data=alignment,
                )
            )

        return {
            "alignments": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="structure.alignment",
                items=alignment_candidates,
            ),
        }
