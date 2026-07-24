"""Random Fixed Positions: randomly select a fraction of positions as fixed for ProteinMPNN."""

import random
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinMPNNConstraints


class RandomFixedPositionsModule(WorkflowModule):
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
        length = int(parameters.get("length", 1))
        fraction = float(parameters.get("fraction", 0.5))

        if length < 1:
            raise ValueError(f"length must be >= 1, got {length}")
        if fraction < 0.0 or fraction > 1.0:
            raise ValueError(f"fraction must be in [0.0, 1.0], got {fraction}")

        count = int(length * fraction)

        if count == 0:
            constraints = ProteinMPNNConstraints(fixed_positions=[])
            return {"constraints": constraints}

        rng = random.Random(context.seed)
        fixed = sorted(rng.sample(range(length), count))

        constraints = ProteinMPNNConstraints(fixed_positions=fixed)
        return {"constraints": constraints}
