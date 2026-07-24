"""Random Mask: randomly mask exactly N non-sentinel positions in a residue track."""

import random
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ResidueTrack


class RandomMaskModule(WorkflowModule):
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
        track: ResidueTrack | None = inputs.get("track")
        if track is None:
            raise ValueError("track input is required")

        count = int(parameters.get("count", 0))

        # Identify non-sentinel positions
        indices = [i for i, v in enumerate(track.values) if v is not track.sentinel]
        specified = len(indices)

        if count < 0:
            raise ValueError(f"count must be non-negative, got {count}")
        if count > specified:
            raise ValueError(
                f"count ({count}) exceeds number of non-sentinel positions ({specified})"
            )

        # Deterministic random selection using context seed
        rng = random.Random(context.seed)
        chosen = set(rng.sample(indices, count))

        new_values = [
            track.sentinel if i in chosen else v
            for i, v in enumerate(track.values)
        ]

        result = ResidueTrack(values=new_values, sentinel=track.sentinel)
        return {"track": result}
