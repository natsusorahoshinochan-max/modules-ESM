"""Legacy async DSSP module backed by the cohesive annotation package."""

import asyncio
from pathlib import Path
import signal
from typing import Any

from core.module_definition import ModuleDefinition
from core.process_control import signal_process_group
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from modules.structure_annotation.legacy import run_dssp_async_legacy


class ComputeDSSPModule(WorkflowModule):
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
        return asyncio.run(self.run_async(inputs, parameters, context))

    async def run_async(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        return await run_dssp_async_legacy(
            inputs,
            parameters,
            context,
            signal_process_group_fn=signal_process_group,
        )
