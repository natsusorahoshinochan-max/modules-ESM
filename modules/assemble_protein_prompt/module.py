"""Assemble ProteinPrompt: collects all tracks into a complete ProteinPrompt."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueTrack,
)


class AssembleProteinPromptModule(WorkflowModule):
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
        layout = inputs.get("layout")
        if layout is None:
            raise ValueError("layout input is required")

        target_len = layout.length

        def _validate_track(track: ResidueTrack | None, name: str) -> None:
            if track is not None and len(track) != target_len:
                raise ValueError(
                    f"{name} length {len(track)} != layout length {target_len}"
                )

        seq_track = inputs.get("sequence_track")
        struct_track = inputs.get("structure_track")
        vis_track = inputs.get("visibility_track")
        ss_track = inputs.get("secondary_structure_track")
        sasa_track = inputs.get("sasa_track")
        func_ann = inputs.get("function_annotations")

        for name, track in [
            ("sequence_track", seq_track),
            ("structure_track", struct_track),
            ("visibility_track", vis_track),
            ("secondary_structure_track", ss_track),
            ("sasa_track", sasa_track),
        ]:
            _validate_track(track, name)

        prompt = ProteinPrompt(
            target_layout=layout,
            sequence_track=seq_track,
            structure_track=struct_track,
            structure_visibility_track=vis_track,
            secondary_structure_track=ss_track,
            sasa_track=sasa_track,
            function_annotations=func_ann if func_ann is not None else FunctionAnnotations(),
        )
        return {"protein_prompt": prompt}
