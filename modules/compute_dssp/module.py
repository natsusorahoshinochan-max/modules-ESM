"""Compute DSSP: runs mkdssp and produces per-residue DSSP secondary structure codes."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure, ResidueTrack

# Reuse the mmCIF parser from the prompt DSSP module
from modules.compute_secondary_structure.module import _parse_dssp_mmcif


class ComputeDSSPModule(WorkflowModule):
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

        dssp_bin = str(parameters.get("dssp_binary", "/opt/homebrew/bin/mkdssp"))

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pdb", delete=False
        ) as tmp:
            tmp.write(structure.pdb_string)
            pdb_path = tmp.name

        try:
            result = subprocess.run(
                [dssp_bin, pdb_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"mkdssp failed: {result.stderr.strip()}"
                )

            ss_codes, _ = _parse_dssp_mmcif(result.stdout)
            track = ResidueTrack(values=ss_codes, sentinel=None)
            return {"secondary_structure_track": track}
        finally:
            Path(pdb_path).unlink(missing_ok=True)
