"""Update Prompt Sequence: replaces sequence track, preserves all other tracks."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinPrompt, ProteinSequence, ResidueTrack


class UpdatePromptSequenceModule(WorkflowModule):
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
        prompt: ProteinPrompt | None = inputs.get("protein_prompt")
        sequence: ProteinSequence | None = inputs.get("sequence")

        if prompt is None:
            raise ValueError("protein_prompt input is required")
        if sequence is None:
            raise ValueError("sequence input is required")

        # Build new sequence track
        seq_chars = [c for c in sequence.sequence]
        if prompt.target_layout is not None and len(seq_chars) != prompt.target_layout.length:
            raise ValueError(
                f"Sequence length {len(seq_chars)} != prompt layout length "
                f"{prompt.target_layout.length}"
            )

        new_seq_track = ResidueTrack(values=seq_chars, sentinel=None)

        updated = ProteinPrompt(
            target_layout=prompt.target_layout,
            sequence_track=new_seq_track,
            structure_track=prompt.structure_track,
            structure_visibility_track=prompt.structure_visibility_track,
            secondary_structure_track=prompt.secondary_structure_track,
            sasa_track=prompt.sasa_track,
            function_annotations=prompt.function_annotations,
        )

        return {"protein_prompt": updated}
