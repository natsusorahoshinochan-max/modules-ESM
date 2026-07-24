"""Select Chains: keeps only specified chains from a multi-chain PDB."""

import json
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure


class SelectChainsModule(WorkflowModule):
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

        chains_raw = parameters.get("chains", "[]")
        if isinstance(chains_raw, str):
            chains = json.loads(chains_raw)
        else:
            chains = chains_raw

        if not chains:
            raise ValueError("At least one chain must be specified")

        chain_set = set(str(c) for c in chains)
        lines = structure.pdb_string.splitlines()
        kept: list[str] = []

        for line in lines:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                chain = line[21:22].strip()
                if chain in chain_set:
                    kept.append(line)
            elif line.startswith("TER"):
                # Keep TER if previous atom was kept
                if kept and (kept[-1].startswith("ATOM") or kept[-1].startswith("HETATM")):
                    kept.append(line)
            elif line.startswith("END"):
                kept.append(line)

        atom_lines = [l for l in kept if l.startswith("ATOM") or l.startswith("HETATM")]
        if not atom_lines:
            raise ValueError(f"No atoms found for chains: {chains}")

        new_pdb = "\n".join(kept) + "\n"
        return {"structure": ProteinStructure(
            pdb_string=new_pdb,
            source=structure.source,
        )}
