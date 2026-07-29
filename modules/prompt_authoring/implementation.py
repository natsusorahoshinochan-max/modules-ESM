"""Provider-free prompt-authoring implementations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .annotations import add_function_annotation
from .domain import (
    build_layout,
    build_residue_map,
    map_track,
    override_track,
    TrackKind,
)
from .prompts import assemble_protein_prompt, update_prompt_sequence


_TRACK_PORTS = {
    "sequence_track": TrackKind.SEQUENCE,
    "structure_track": TrackKind.STRUCTURE,
    "visibility_track": TrackKind.VISIBILITY,
    "secondary_structure_track": TrackKind.SECONDARY_STRUCTURE,
    "sasa_track": TrackKind.SASA,
}


class _Implementation:
    def __init__(self, run_resources: Any, operation: str) -> None:
        self._run_resources = run_resources
        self._operation = operation

    def _invocation(self):
        return self._run_resources.engine_invocation(
            engine_identity=(
                f"prompt_authoring.{self._operation}.method/2.0.0"
            ),
        )


class BuildResidueLayoutImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or binding_parameters or set(node_parameters) != {"chains"}:
            raise ValueError("layout construction requires only chains")
        with self._invocation():
            layout = build_layout(node_parameters["chains"])
        return {"layout": layout}


class EditResidueLayoutImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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
                inputs["source_layout"],
                inputs["target_layout"],
                node_parameters["edits"],
            )
        return {"residue_map": residue_map}


def _selected_track(
    inputs: Mapping[str, Any],
) -> tuple[str, TrackKind, object]:
    selected = [
        (port, kind, inputs[port])
        for port, kind in _TRACK_PORTS.items()
        if port in inputs
    ]
    if len(selected) != 1:
        raise ValueError("exactly one nominal per-residue track is required")
    return selected[0]


class MapResidueTrackImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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
                inputs["residue_map"],
                kind=kind,
            )
        return {port: converted}


class OverrideResidueTrackImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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
                inputs["target_layout"],
                node_parameters["overrides"],
                kind=kind,
            )
        return {port: result}


class AssembleProteinPromptImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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
            name: inputs[name]
            for name in _TRACK_PORTS
            if name in inputs
        }
        with self._invocation():
            prompt = assemble_protein_prompt(
                inputs["layout"],
                tracks,
                inputs.get("function_annotations"),
            )
        return {"protein_prompt": prompt}


class AddFunctionAnnotationImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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
                inputs["layout"],
                inputs.get("existing_annotations"),
                node_parameters["annotation"],
                overlap_policy=node_parameters["overlap_policy"],
            )
        return {"function_annotations": annotations}


class UpdatePromptSequenceImplementation(_Implementation):
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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
                inputs["protein_prompt"],
                inputs["sequence"],
            )
        return {"protein_prompt": prompt}
