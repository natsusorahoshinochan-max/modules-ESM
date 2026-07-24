"""Extract Sequence from Structure: extracts amino acid sequence from PDB."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinSequence, ProteinStructure

_AA_3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def _extract_sequence(pdb_string: str) -> str:
    seen: set[str] = set()
    residues: list[str] = []
    for line in pdb_string.splitlines():
        if line.startswith("ATOM") or line.startswith("HETATM"):
            atom_name = line[12:16].strip()
            if atom_name != "CA":
                continue
            res_name = line[17:20].strip()
            chain = line[21:22].strip()
            res_seq = line[22:26].strip()
            key = f"{chain}_{res_seq}"
            if key not in seen:
                seen.add(key)
                residues.append(_AA_3TO1.get(res_name, "X"))
    return "".join(residues)


class ExtractSequenceFromStructureModule(WorkflowModule):
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
        structure: ProteinStructure | None = inputs.get("structure")
        if structure is None:
            raise ValueError("structure input is required")

        seq = _extract_sequence(structure.pdb_string)
        if not seq:
            raise ValueError("No amino acid residues found in PDB")

        return {"sequence": ProteinSequence(sequence=seq)}
