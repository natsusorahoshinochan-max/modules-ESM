"""Provider-free prompt-authoring implementations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core import AdmittedPort, OperationCall, RunResources
from datatypes import (
    FunctionAnnotations,
    ProteinPrompt,
    ResolvedStructureResidueAxis,
    ResidueLayout,
    ResidueTrack,
)

from .annotations import add_function_annotation
from .domain import (
    build_layout,
    build_residue_map,
    map_track,
    override_track,
    TrackKind,
)
from .deterministic import insert_masked_residues
from .prompts import (
    assemble_protein_prompt,
    override_protein_prompt_track,
    update_prompt_sequence,
)
from .stochastic import random_insert_masked, random_mask_prompt


_TRACK_PORTS = {
    "sequence_track": TrackKind.SEQUENCE,
    "structure_track": TrackKind.STRUCTURE,
    "visibility_track": TrackKind.VISIBILITY,
    "secondary_structure_track": TrackKind.SECONDARY_STRUCTURE,
    "sasa_track": TrackKind.SASA,
}


class _Implementation:
    def __init__(self, run_resources: RunResources) -> None:
        self._run_resources = run_resources

    def _invocation(self):
        return self._run_resources.engine_invocation()


class BuildResidueLayoutImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or binding_parameters or set(node_parameters) != {"chains"}:
            raise ValueError("layout construction requires only chains")
        with self._invocation():
            layout = build_layout(node_parameters["chains"])
        return {"layout": layout}


class EditResidueLayoutImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"source_layout", "target_layout"}
            or set(node_parameters) != {"edits"}
            or binding_parameters
        ):
            raise ValueError(
                "residue editing requires source_layout, target_layout, and edits"
            )
        with self._invocation():
            residue_map = build_residue_map(
                inputs["source_layout"].value,
                inputs["target_layout"].value,
                node_parameters["edits"],
            )
        return {"residue_map": residue_map}


def _selected_track(
    inputs: Mapping[str, AdmittedPort],
) -> tuple[str, TrackKind, object]:
    selected = [
        (port, kind, inputs[port].value)
        for port, kind in _TRACK_PORTS.items()
        if port in inputs
    ]
    if len(selected) != 1:
        raise ValueError("exactly one nominal per-residue track is required")
    return selected[0]


class MapResidueTrackImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        port, kind, track = _selected_track(inputs)
        if (
            set(inputs) != {"residue_map", port}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "track mapping requires one track and one residue_map"
            )
        with self._invocation():
            converted = map_track(
                track,
                inputs["residue_map"].value,
                kind=kind,
            )
        return {port: converted}


class OverrideResidueTrackImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        port, kind, track = _selected_track(inputs)
        if (
            set(inputs) != {"target_layout", port}
            or set(node_parameters) != {"overrides"}
            or binding_parameters
        ):
            raise ValueError(
                "track override requires target_layout, one track, and overrides"
            )
        with self._invocation():
            result = override_track(
                track,
                inputs["target_layout"].value,
                node_parameters["overrides"],
                kind=kind,
            )
        return {port: result}


def _prompt_from_structure(
    residue_axis: object,
) -> tuple[ResidueLayout, ProteinPrompt]:
    if type(residue_axis) is not ResolvedStructureResidueAxis:
        raise ValueError(
            "prompt construction requires one ResolvedStructureResidueAxis"
        )
    coordinates = [
        {
            atom.atom_name: atom.coordinate
            for atom in residue.atom_coordinates
        }
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
        structure_visibility_track=ResidueTrack(
            [bool(value) for value in coordinates],
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
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"residue_axis"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "prompt construction requires one resolved axis and no parameters"
            )
        with self._invocation():
            layout, prompt = _prompt_from_structure(
                inputs["residue_axis"].value
            )
        return {"layout": layout, "protein_prompt": prompt}


class OverrideProteinPromptTrackImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters) != {"track", "overrides"}
            or binding_parameters
        ):
            raise ValueError(
                "prompt track override requires one Prompt and exact overrides"
            )
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
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        allowed_inputs = {"layout", "function_annotations", *_TRACK_PORTS}
        if (
            "layout" not in inputs
            or not set(inputs) <= allowed_inputs
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "prompt assembly accepts only layout and declared optional tracks"
            )
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


class AddFunctionAnnotationImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) not in (
                {"layout"},
                {"layout", "existing_annotations"},
            )
            or set(node_parameters) != {"annotation", "overlap_policy"}
            or binding_parameters
        ):
            raise ValueError(
                "function annotation requires layout, annotation, overlap_policy, "
                "and optional existing_annotations"
            )
        with self._invocation():
            annotations = add_function_annotation(
                inputs["layout"].value,
                (
                    inputs["existing_annotations"].value
                    if "existing_annotations" in inputs
                    else None
                ),
                node_parameters["annotation"],
                overlap_policy=node_parameters["overlap_policy"],
            )
        return {"function_annotations": annotations}


class UpdatePromptSequenceImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"protein_prompt", "sequence"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "sequence update requires only protein_prompt and sequence"
            )
        with self._invocation():
            prompt = update_prompt_sequence(
                inputs["protein_prompt"].value,
                inputs["sequence"].value,
            )
        return {"protein_prompt": prompt}


class RandomMaskImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters)
            != {
                "effective_seed",
                "count",
                "track",
                "eligible_residue_ids",
            }
            or binding_parameters
        ):
            raise ValueError(
                "random masking requires one ProteinPrompt and resolved randomness"
            )
        with self._invocation():
            prompt = random_mask_prompt(
                inputs["protein_prompt"].value,
                effective_seed=node_parameters["effective_seed"],
                count=node_parameters["count"],
                track=node_parameters["track"],
                eligible_residue_ids=node_parameters["eligible_residue_ids"],
            )
        return {"protein_prompt": prompt}


class RandomInsertMaskedImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters)
            != {
                "effective_seed",
                "count",
                "eligible_chain_ids",
            }
            or binding_parameters
        ):
            raise ValueError(
                "masked insertion requires one ProteinPrompt and resolved randomness"
            )
        with self._invocation():
            prompt, residue_map = random_insert_masked(
                inputs["protein_prompt"].value,
                effective_seed=node_parameters["effective_seed"],
                count=node_parameters["count"],
                eligible_chain_ids=node_parameters["eligible_chain_ids"],
            )
        return {
            "protein_prompt": prompt,
            "residue_map": residue_map,
        }


class InsertMaskedResiduesImplementation(_Implementation):
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"protein_prompt"}
            or set(node_parameters) != {"insertions"}
            or binding_parameters
        ):
            raise ValueError(
                "deterministic insertion requires one Prompt and insertions"
            )
        with self._invocation():
            prompt, residue_map = insert_masked_residues(
                inputs["protein_prompt"].value,
                node_parameters["insertions"],
            )
        return {
            "protein_prompt": prompt,
            "residue_map": residue_map,
        }
