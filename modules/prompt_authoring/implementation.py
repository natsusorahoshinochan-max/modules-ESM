"""Provider-free prompt-authoring implementations."""

from __future__ import annotations

from typing import Any

from core.operation import (
    OperationResources,
    OperationCall,
)
from datatypes.prompt import (
    FunctionAnnotations,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
)
from datatypes.structure import ResolvedStructureResidueAxis

from .annotations import replace_function_annotations
from .domain import build_layout
from .deterministic import (
    edit_protein_prompt_layout,
    edit_protein_prompt_layout_from_declarations,
    merge_protein_prompt_source,
)
from .prompts import (
    assemble_protein_prompt,
    override_protein_prompt_track,
    update_prompt_sequence,
)
from .stochastic import random_insert_masked, random_mask_prompt


_TRACK_PORTS = (
    "sequence_track",
    "structure_track",
    "secondary_structure_track",
    "sasa_track",
)


class _Implementation:
    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def _invocation(self):
        return self._run_resources.engine_invocation()


class BuildResidueLayoutImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        with self._invocation():
            layout = build_layout(call.node_parameters["chains"])
        return {"layout": layout}


def _prompt_from_structure(
    residue_axis: ResolvedStructureResidueAxis,
) -> tuple[ResidueLayout, ProteinPrompt]:
    coordinates = [
        (
            {
                atom.atom_name: atom.coordinate
                for atom in residue.atom_coordinates
            }
            or None
        )
        for residue in residue_axis.residue_coordinates
    ]
    prompt = ProteinPrompt(
        target_layout=residue_axis.layout,
        sequence_track=ResidueTrack(
            list(residue_axis.sequence),
            None,
        ),
        structure_track=ResidueTrack(
            coordinates,
            None,
        ),
        secondary_structure_track=ResidueTrack(
            [None for _ in coordinates],
            None,
        ),
        sasa_track=None,
        function_annotations=FunctionAnnotations(),
    )
    return residue_axis.layout, prompt


class PromptFromStructureImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        with self._invocation():
            layout, prompt = _prompt_from_structure(
                inputs["residue_axis"].value
            )
        return {"layout": layout, "protein_prompt": prompt}


class OverrideProteinPromptTrackImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        with self._invocation():
            prompt = override_protein_prompt_track(
                inputs["protein_prompt"].value,
                track=node_parameters["track"],
                overrides=node_parameters["overrides"],
            )
        return {"protein_prompt": prompt}


class AssembleProteinPromptImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        tracks = {
            name: inputs[name].value
            for name in _TRACK_PORTS
            if name in inputs
        }
        with self._invocation():
            prompt = assemble_protein_prompt(
                inputs["layout"].value,
                tracks,
                (
                    inputs["function_annotations"].value
                    if "function_annotations" in inputs
                    else None
                ),
            )
        return {"protein_prompt": prompt}


class ReplaceProteinPromptAnnotationsImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        source = inputs["protein_prompt"].value
        with self._invocation():
            annotations = replace_function_annotations(
                source.target_layout,
                node_parameters["annotations"],
                overlap_policy=node_parameters["overlap_policy"],
            )
            prompt = ProteinPrompt(
                target_layout=source.target_layout,
                sequence_track=source.sequence_track,
                structure_track=source.structure_track,
                secondary_structure_track=source.secondary_structure_track,
                sasa_track=source.sasa_track,
                function_annotations=annotations,
            )
        return {"protein_prompt": prompt}


class UpdatePromptSequenceImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        with self._invocation():
            prompt = update_prompt_sequence(
                inputs["protein_prompt"].value,
                inputs["sequence"].value,
            )
        return {"protein_prompt": prompt}


class RandomMaskImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        randomness = call.effective_randomness
        with self._invocation():
            prompt = random_mask_prompt(
                inputs["protein_prompt"].value,
                effective_seed=randomness["effective_seed"],
                count=randomness["count"],
                track=randomness["track"],
                eligible_residue_ids=randomness["eligible_residue_ids"],
            )
        return {"protein_prompt": prompt}


class RandomInsertMaskedImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        randomness = call.effective_randomness
        with self._invocation():
            prompt, residue_map = random_insert_masked(
                inputs["protein_prompt"].value,
                effective_seed=randomness["effective_seed"],
                count=randomness["count"],
                eligible_chain_ids=randomness["eligible_chain_ids"],
            )
        return {
            "protein_prompt": prompt,
            "residue_map": residue_map,
        }


class EditProteinPromptLayoutImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        with self._invocation():
            prompt, residue_map = edit_protein_prompt_layout_from_declarations(
                inputs["protein_prompt"].value,
                node_parameters["insertions"],
                node_parameters["deleted_residue_ids"],
            )
        return {
            "protein_prompt": prompt,
            "residue_map": residue_map,
        }


class MergeProteinPromptSourceImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        with self._invocation():
            prompt = merge_protein_prompt_source(
                call.inputs["target_prompt"].value,
                call.inputs["source_prompt"].value,
                call.node_parameters["correspondence"],
                call.node_parameters["track_decisions"],
            )
        return {"protein_prompt": prompt}
