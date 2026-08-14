"""Behavior contracts for the v2 random-mask prompt Node."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import WorkflowAuthoringError
from core.workflow_v2 import WorkflowEdge
from datatypes import ResidueTrack
from tests.fixtures.prompt_authoring_v2 import (
    decoded_output,
    run_operation,
)


_SOURCE_EDGE = (
    WorkflowEdge(
        "source",
        "protein_prompt",
        "author",
        "protein_prompt",
    ),
)


def test_random_mask_clears_only_seeded_assigned_sequence_positions(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="random_mask",
        node_parameters={
            "effective_seed": 11,
            "count": 2,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        source_edges=_SOURCE_EDGE,
    )

    assert projection["status"] == "succeeded"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    masked = decoded_output(catalog, service, projection, output)
    assert masked.sequence_track == ResidueTrack(["A", None, None], None)
    assert masked.target_layout.residue_ids == ("A:1", "A:2", "B:1")
    assert masked.structure_track == ResidueTrack(
        [
            {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
            None,
            {"CA": (2.0, 0.0, 0.0)},
        ],
        None,
    )
    assert masked.secondary_structure_track == ResidueTrack(
        ["H", "E", "-"],
        None,
    )


def test_zero_and_full_masks_preserve_nullable_track_semantics(
    tmp_path: Path,
) -> None:
    outputs = []
    for label, count in (("zero", 0), ("full", 3)):
        catalog, service, projection, _ = run_operation(
            tmp_path / label,
            operation="random_mask",
            node_parameters={
                "effective_seed": 1603,
                "count": count,
                "track": "sequence",
                "eligible_residue_ids": [],
            },
            source_edges=_SOURCE_EDGE,
        )
        outputs.append(
            decoded_output(
                catalog,
                service,
                projection,
                next(
                    output
                    for output in projection["outputs"]
                    if output["node_id"] == "author"
                ),
            )
        )

    assert outputs[0].sequence_track == ResidueTrack(["A", "G", "S"], None)
    assert outputs[1].sequence_track == ResidueTrack([None, None, None], None)
    assert outputs[0].sasa_track == outputs[1].sasa_track == ResidueTrack(
        [12.5, None, 30.0],
        None,
    )

    catalog, structure_service, structure_projection, _ = run_operation(
        tmp_path / "structure",
        operation="random_mask",
        node_parameters={
            "effective_seed": 1603,
            "count": 2,
            "track": "structure",
            "eligible_residue_ids": [],
        },
        source_edges=_SOURCE_EDGE,
    )
    structure_masked = decoded_output(
        catalog,
        structure_service,
        structure_projection,
        next(
            output
            for output in structure_projection["outputs"]
            if output["node_id"] == "author"
        ),
    )
    assert structure_masked.structure_track == ResidueTrack(
        [None, None, None],
        None,
    )


@pytest.mark.parametrize(
    "parameters",
    (
        {
            "effective_seed": 1,
            "count": 4,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 1,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": ["A:outside"],
        },
    ),
)
def test_random_mask_rejects_impossible_counts_and_positions(
    tmp_path: Path,
    parameters: dict[str, object],
) -> None:
    _, _, projection, _ = run_operation(
        tmp_path,
        operation="random_mask",
        node_parameters=parameters,
        source_edges=_SOURCE_EDGE,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "author"
        for output in projection["outputs"]
    )


def test_duplicate_mask_positions_fail_during_authoring(
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkflowAuthoringError) as rejected:
        run_operation(
            tmp_path,
            operation="random_mask",
            node_parameters={
                "effective_seed": 1,
                "count": 1,
                "track": "sequence",
                "eligible_residue_ids": ["A:1", "A:1"],
            },
            source_edges=_SOURCE_EDGE,
        )

    assert rejected.value.code == "compile_rejected"


def test_canonical_3gb1_mask_intent_is_an_ordinary_regression(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="random_mask",
        node_parameters={
            "effective_seed": 1603,
            "count": 20,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        source_edges=_SOURCE_EDGE,
        source_fixture="3gb1-intent",
    )
    masked = decoded_output(
        catalog,
        service,
        projection,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "author"
        ),
    )

    assert [
        residue_id
        for residue_id, value in zip(
            masked.target_layout.residue_ids or (),
            masked.sequence_track.values,
            strict=True,
        )
        if value is None
    ] == [
        "A:1",
        "A:2",
        "A:6",
        "A:7",
        "A:12",
        "A:13",
        "A:15",
        "A:18",
        "A:19",
        "A:24",
        "A:26",
        "A:30",
        "A:35",
        "A:42",
        "A:44",
        "A:47",
        "A:48",
        "A:49",
        "A:50",
        "A:53",
    ]
