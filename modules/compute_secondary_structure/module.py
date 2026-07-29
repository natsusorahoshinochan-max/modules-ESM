"""Legacy secondary-structure module backed by the cohesive annotation package."""

import subprocess
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from modules.structure_annotation.legacy import (
    parse_dssp_mmcif_legacy,
    run_dssp_sync_legacy,
)


_parse_dssp_mmcif = parse_dssp_mmcif_legacy


class ComputeSecondaryStructureModule(WorkflowModule):
    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml(
            Path(__file__).parent / "definition.yaml"
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        return run_dssp_sync_legacy(
            inputs,
            parameters,
            context,
            operation="secondary_structure",
            output_port="secondary_structure_track",
            select_values=lambda parsed: parsed[0],
            run_process=subprocess.run,
        )
