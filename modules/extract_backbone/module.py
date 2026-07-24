"""Extract Backbone: keeps only N, CA, C, O atoms from a PDB structure."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure

_BACKBONE_ATOMS = {"N", "CA", "C", "O"}


class ExtractBackboneModule(WorkflowModule):
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

        lines = structure.pdb_string.splitlines()
        kept: list[str] = []

        for line in lines:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                atom_name = line[12:16].strip()
                if atom_name in _BACKBONE_ATOMS:
                    kept.append(line)
            elif line.startswith("TER"):
                kept.append(line)
            elif line.startswith("END"):
                kept.append(line)
            # Keep non-ATOM lines (HEADER, etc.) if before first ATOM
            elif not kept or kept[0].startswith("ATOM") or kept[0].startswith("HETATM"):
                if not line.startswith("ATOM") and not line.startswith("HETATM"):
                    # Only keep header lines before first atom
                    if not any(l.startswith("ATOM") or l.startswith("HETATM") for l in kept):
                        kept.append(line)

        atom_lines = [l for l in kept if l.startswith("ATOM") or l.startswith("HETATM")]
        if not atom_lines:
            raise ValueError("No backbone atoms found in PDB")

        new_pdb = "\n".join(kept) + "\n"
        return {"structure": ProteinStructure(
            pdb_string=new_pdb,
            source=structure.source,
        )}
