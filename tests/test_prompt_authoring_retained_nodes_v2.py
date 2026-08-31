"""Focused behavior tests for retained deterministic Prompt authoring Nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from core.execution.runtime import V2RunService
from core.workflow.document import WorkflowEdge
from datatypes.prompt import ProteinPrompt
from datatypes.residue import ResidueLayout, ResidueTrack
from tests.fixtures.prompt_authoring_v2 import decoded_output, run_operation


def _author_outputs(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
) -> dict[str, object]:
    return {
        output["output_port"]: decoded_output(
            catalog,
            service,
            projection,
            output,
        )
        for output in projection["outputs"]
        if output["node_id"] == "author"
    }


def test_build_residue_layout_preserves_declared_chain_order(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="build_residue_layout",
        node_parameters={
            "chains": [
                {"chain_id": "B", "length": 2},
                {"chain_id": "A", "length": 1},
            ]
        },
    )

    assert projection["status"] == "succeeded"
    assert _author_outputs(catalog, service, projection)["layout"] == (
        ResidueLayout("B,A", 3, ["B:1", "B:2", "A:1"])
    )


def test_assemble_protein_prompt_preserves_every_declared_track(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="assemble_protein_prompt",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "source_sequence_track",
                "author",
                "sequence_track",
            ),
            WorkflowEdge(
                "source",
                "source_structure_track",
                "author",
                "structure_track",
            ),
            WorkflowEdge(
                "source",
                "source_secondary_structure_track",
                "author",
                "secondary_structure_track",
            ),
            WorkflowEdge(
                "source",
                "source_sasa_track",
                "author",
                "sasa_track",
            ),
            WorkflowEdge(
                "source",
                "function_annotations",
                "author",
                "function_annotations",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    prompt = cast(
        ProteinPrompt,
        _author_outputs(catalog, service, projection)["protein_prompt"],
    )
    assert prompt.target_layout == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:2", "B:1"],
    )
    assert prompt.sequence_track == ResidueTrack(["A", "G", "S"], None)
    assert prompt.structure_track == ResidueTrack(
        [
            {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
            None,
            None,
        ],
        None,
    )
    assert prompt.secondary_structure_track == ResidueTrack(
        ["H", "E", "-"],
        None,
    )
    assert prompt.sasa_track == ResidueTrack([12.5, None, 30.0], None)
    assert [
        (
            annotation.label,
            annotation.start_residue_id,
            annotation.end_residue_id,
        )
        for annotation in prompt.function_annotations.annotations
    ] == [("binding_site", "A:1", "A:2")]


def test_prompt_from_structure_uses_the_resolver_owned_axis(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="prompt_from_structure",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "resolved_residue_axis",
                "author",
                "residue_axis",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    outputs = _author_outputs(catalog, service, projection)
    assert outputs["layout"] == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:2", "B:1"],
    )
    prompt = cast(ProteinPrompt, outputs["protein_prompt"])
    assert prompt.sequence_track == ResidueTrack(
        ["A", "G", "S"],
        None,
    )


def test_update_prompt_sequence_preserves_every_unaffected_track(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="update_prompt_sequence",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
            WorkflowEdge(
                "source",
                "protein_sequence",
                "author",
                "sequence",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    updated = cast(
        ProteinPrompt,
        _author_outputs(catalog, service, projection)["protein_prompt"],
    )
    assert updated.sequence_track == ResidueTrack(["W", "F", "C"], None)
    assert updated.target_layout == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:2", "B:1"],
    )
    assert updated.structure_track == ResidueTrack(
        [
            {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
            None,
            None,
        ],
        None,
    )
    assert updated.secondary_structure_track == ResidueTrack(
        ["H", "E", "-"],
        None,
    )
    assert updated.sasa_track == ResidueTrack([12.5, None, 30.0], None)


def test_override_protein_prompt_track_changes_only_the_selected_track(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="override_protein_prompt_track",
        node_parameters={
            "track": "secondary_structure",
            "overrides": [
                {
                    "action": "replace",
                    "residue_id": "A:2",
                    "value": "T",
                }
            ],
        },
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    updated = cast(
        ProteinPrompt,
        _author_outputs(catalog, service, projection)["protein_prompt"],
    )
    assert updated.secondary_structure_track == ResidueTrack(
        ["H", "T", "-"],
        None,
    )
    assert updated.sequence_track == ResidueTrack(["A", "G", "S"], None)
    assert updated.structure_track == ResidueTrack(
        [
            {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
            None,
            None,
        ],
        None,
    )


def test_edit_protein_prompt_layout_executes_as_one_whole_prompt_node(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="edit_protein_prompt_layout",
        node_parameters={
            "insertions": [
                {
                    "after_residue_id": "A:1",
                    "before_residue_id": "A:2",
                    "inserted_residue_ids": ["A:inserted.test"],
                }
            ],
            "deleted_residue_ids": ["A:2"],
        },
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    outputs = _author_outputs(catalog, service, projection)
    prompt = cast(ProteinPrompt, outputs["protein_prompt"])
    assert prompt.target_layout == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:inserted.test", "B:1"],
    )
    assert prompt.sequence_track == ResidueTrack(["A", None, "S"], None)
    assert outputs["layout"] == prompt.target_layout
    residue_map = outputs["residue_map"]
    assert tuple(item[2] for item in residue_map.mappings) == (
        "match",
        "insert",
        "match",
        "delete",
    )


def test_replace_protein_prompt_annotations_executes_complete_collection(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="replace_protein_prompt_annotations",
        node_parameters={
            "annotations": [
                {
                    "label": "active_site",
                    "chain_id": "B",
                    "start_residue_id": "B:1",
                    "end_residue_id": "B:1",
                }
            ],
            "overlap_policy": "reject",
        },
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    prompt = cast(
        ProteinPrompt,
        _author_outputs(catalog, service, projection)["protein_prompt"],
    )
    annotation = prompt.function_annotations.annotations[0]
    assert (
        annotation.label,
        annotation.start_residue_id,
        annotation.end_residue_id,
    ) == ("active_site", "B:1", "B:1")


def test_merge_protein_prompt_source_executes_confirmed_correspondence(
    tmp_path: Path,
) -> None:
    correspondence = [
        {
            "disposition": "match",
            "source_residue_id": residue_id,
            "target_residue_id": residue_id,
        }
        for residue_id in ("A:1", "A:2", "B:1")
    ]
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="merge_protein_prompt_source",
        node_parameters={
            "correspondence": correspondence,
            "track_decisions": {
                "sequence": "adopt",
                "structure": "preserve",
                "secondary_structure": "preserve",
                "sasa": "preserve",
                "function_annotations": "adopt",
            },
        },
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "target_prompt",
            ),
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "source_prompt",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    prompt = cast(
        ProteinPrompt,
        _author_outputs(catalog, service, projection)["protein_prompt"],
    )
    assert prompt.sequence_track == ResidueTrack(["A", "G", "S"], None)
    assert prompt.function_annotations.annotations[0].label == "binding_site"
