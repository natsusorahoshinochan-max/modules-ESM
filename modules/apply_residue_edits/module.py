"""Apply Residue Edits: maps template structure to target layout with edit operations."""

import json
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    ProteinStructure,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)

# Standard 3-letter → 1-letter amino acid codes
AA3TO1: dict[str, str] = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F",
    "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K", "LEU": "L",
    "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R",
    "SER": "S", "THR": "T", "VAL": "V", "TRP": "W", "TYR": "Y",
    "MSE": "M", "SEC": "U", "PYL": "O",
}


def _parse_pdb_residues(
    pdb_string: str, target_chain: str = "A"
) -> list[dict[str, Any]]:
    """Parse ATOM records from PDB string into per-residue data.

    Returns list of dicts with keys: chain, aa1, resnum, coords (or None).
    Only CA atoms contribute coordinates; non-CA residues get None.
    """
    residues: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for line in pdb_string.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()
        if atom_name != "CA":
            continue
        chain = line[21:22].strip() if len(line) > 21 else " "
        if chain and chain != target_chain:
            continue
        resname = line[17:20].strip()
        resnum_str = line[22:26].strip()
        try:
            resnum = int(resnum_str)
        except ValueError:
            continue
        key = (chain, resnum)
        if key in seen:
            continue
        seen.add(key)

        aa1 = AA3TO1.get(resname.upper(), "X")
        if len(line) >= 54:
            try:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                coords = (x, y, z)
            except ValueError:
                coords = None
        else:
            coords = None
        residues.append({
            "chain": chain or " ",
            "aa1": aa1,
            "resnum": resnum,
            "coords": coords,
        })
    return residues


class ApplyResidueEditsModule(WorkflowModule):
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
        template: ProteinStructure | None = inputs.get("template_structure")
        target_layout: ResidueLayout | None = inputs.get("target_layout")
        if template is None:
            raise ValueError("template_structure input is required")
        if target_layout is None:
            raise ValueError("target_layout input is required")

        edits_raw = str(parameters.get("edits", "[]"))
        edits: list[dict[str, Any]] = json.loads(edits_raw)

        chain = target_layout.chain_id
        target_len = target_layout.length

        # Parse template residues for target chain
        template_residues = _parse_pdb_residues(template.pdb_string, chain)

        # Build initial 1:1 mapping for matching range
        # Each position in target gets: aa (or None for mask), coords (or None), visible
        seq_values: list[str | None] = [None] * target_len
        coord_values: list[tuple[float, float, float] | None] = [None] * target_len
        vis_values: list[bool] = [False] * target_len
        mappings: list[tuple[int, int, str]] = []

        # Match template residues to target positions (1:1 where they overlap)
        for i, tres in enumerate(template_residues):
            if i < target_len:
                seq_values[i] = tres["aa1"]
                coord_values[i] = tres["coords"]
                vis_values[i] = tres["coords"] is not None
                mappings.append((i, i, "match"))

        # Remaining target positions are "insert" (no template source)
        for i in range(len(template_residues), target_len):
            mappings.append((-1, i, "insert"))

        # Template residues beyond target_len are "delete"
        for i in range(target_len, len(template_residues)):
            mappings.append((i, -1, "delete"))

        # Apply user edits
        for edit in edits:
            op = edit.get("op", "")
            pos = edit.get("position")
            if pos is None or not isinstance(pos, int):
                continue
            if pos < 0 or pos >= target_len:
                raise ValueError(f"Edit position {pos} out of range [0, {target_len})")

            if op == "set":
                seq_values[pos] = str(edit.get("value", "A"))
            elif op == "mask":
                seq_values[pos] = None
            elif op == "insert":
                # Insert: shift everything from pos onward right, add new pos
                seq_values.insert(pos, str(edit.get("value", "")) or None)
                coord_values.insert(pos, None)
                vis_values.insert(pos, False)
                target_len += 1
                # Adjust mappings
                new_mappings: list[tuple[int, int, str]] = []
                for src, tgt, mop in mappings:
                    if tgt >= pos:
                        new_mappings.append((src, tgt + 1, mop))
                    else:
                        new_mappings.append((src, tgt, mop))
                new_mappings.append((-1, pos, "insert"))
                mappings = new_mappings
            elif op == "delete":
                if target_len <= 1:
                    raise ValueError("Cannot delete the last residue")
                seq_values.pop(pos)
                coord_values.pop(pos)
                vis_values.pop(pos)
                target_len -= 1
                # Adjust mappings
                new_mappings = []
                for src, tgt, mop in mappings:
                    if tgt == pos:
                        if mop == "match" and src >= 0:
                            new_mappings.append((src, -1, "delete"))
                        # else: insert → just remove, nothing to map
                    elif tgt > pos:
                        new_mappings.append((src, tgt - 1, mop))
                    else:
                        new_mappings.append((src, tgt, mop))
                mappings = new_mappings

        # Build updated layout
        updated_layout = ResidueLayout(chain_id=chain, length=target_len)

        seq_track = ResidueTrack(values=seq_values, sentinel=None)
        struct_track = ResidueTrack(values=coord_values, sentinel=None)
        vis_track = ResidueTrack(values=vis_values, sentinel=None)

        residue_map = ResidueMap(
            source_layout=ResidueLayout(
                chain_id=chain, length=len(template_residues)
            ),
            target_layout=updated_layout,
            mappings=mappings,
        )

        return {
            "sequence_track": seq_track,
            "structure_track": struct_track,
            "visibility_track": vis_track,
            "residue_map": residue_map,
        }
