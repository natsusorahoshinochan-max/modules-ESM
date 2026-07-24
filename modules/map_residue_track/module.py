"""Map Residue Track: remaps a ResidueTrack using a ResidueMap."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ResidueMap, ResidueTrack


class MapResidueTrackModule(WorkflowModule):
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
        rmap: ResidueMap | None = inputs.get("residue_map")

        if track is None:
            raise ValueError("track input is required")
        if rmap is None:
            raise ValueError("residue_map input is required")

        target_len = rmap.target_layout.length
        mapped_values: list = [track.sentinel] * target_len

        # Build source index lookup: source_idx -> value
        source_values = track.values if track.values else []

        for mapping in rmap.mappings:
            src_idx, tgt_idx, op = mapping
            if op == "match":
                if 0 <= src_idx < len(source_values) and 0 <= tgt_idx < target_len:
                    mapped_values[tgt_idx] = source_values[src_idx]
            elif op == "insert":
                # Insertion: target position has no source counterpart
                if 0 <= tgt_idx < target_len:
                    mapped_values[tgt_idx] = track.sentinel
            elif op == "delete":
                # Deletion: source position not carried to target
                pass

        return {
            "track": ResidueTrack(values=mapped_values, sentinel=track.sentinel),
        }
