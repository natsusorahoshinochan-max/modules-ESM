"""Override Residue Track: hand-edit individual positions in a residue track."""

import json
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ResidueTrack


class OverrideResidueTrackModule(WorkflowModule):
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
        track: ResidueTrack | None = inputs.get("track_input")
        if track is None:
            raise ValueError("track_input is required")

        overrides_raw = str(parameters.get("overrides", "[]"))
        overrides = json.loads(overrides_raw)

        clear_unmentioned = parameters.get("clear_unmentioned", False)
        if not isinstance(clear_unmentioned, bool):
            raise ValueError("clear_unmentioned must be a boolean")
        new_values = (
            [track.sentinel] * len(track)
            if clear_unmentioned
            else list(track.values)
        )
        for ov in overrides:
            pos = int(ov["position"])
            val = ov["value"]
            if pos < 0 or pos >= len(new_values):
                raise ValueError(f"Override position {pos} out of range [0, {len(new_values)})")
            new_values[pos] = val

        result = ResidueTrack(values=new_values, sentinel=track.sentinel)
        return {"track_output": result}
