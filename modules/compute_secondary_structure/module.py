"""Compute Secondary Structure: runs mkdssp and produces per-residue DSSP codes."""

import subprocess
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure, ResidueTrack


def _parse_dssp_mmcif(dssp_text: str) -> tuple[list[str], list[float]]:
    """Parse mkdssp 4.x mmCIF output for secondary structure and SASA.

    Returns (ss_codes, sasa_values) parallel lists.
    ss_codes: H/B/E/G/I/T/S or '-' for coil/unspecified.
    sasa_values: float solvent accessibility, 0.0 if missing.
    """
    ss_codes: list[str] = []
    sasa_values: list[float] = []

    in_summary = False
    field_count = 0
    ss_index = -1
    acc_index = -1

    for raw_line in dssp_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line == "loop_":
            # End previous loop, start new one
            in_summary = False
            field_count = 0
            ss_index = -1
            acc_index = -1
            continue

        if line.startswith("_dssp_struct_summary."):
            in_summary = True
            field_count += 1
            if line == "_dssp_struct_summary.secondary_structure":
                ss_index = field_count - 1
            elif line == "_dssp_struct_summary.accessibility":
                acc_index = field_count - 1
            continue

        if in_summary and not line.startswith("_") and not line.startswith("#"):
            tokens = line.split()
            if ss_index >= 0 and ss_index < len(tokens):
                ss = tokens[ss_index]
                if ss == ".":
                    ss = "-"
                ss_codes.append(ss)
            if acc_index >= 0 and acc_index < len(tokens):
                try:
                    sasa_values.append(float(tokens[acc_index]))
                except ValueError:
                    sasa_values.append(0.0)

    return ss_codes, sasa_values


class ComputeSecondaryStructureModule(WorkflowModule):
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
        with context.temporary_file(
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
