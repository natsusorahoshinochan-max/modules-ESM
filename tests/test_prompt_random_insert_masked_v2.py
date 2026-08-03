"""Behavior contracts for the v2 masked-insertion prompt Node."""

from __future__ import annotations

from pathlib import Path

from core.workflow_v2 import WorkflowEdge
from datatypes import ResidueLayout, ResidueTrack
from tests.fixtures.prompt_authoring_v2 import (
    VERSION,
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


def test_masked_insertion_handles_repeated_chain_boundary_choices(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 1,
            "count": 3,
            "eligible_chain_ids": [],
        },
        source_edges=_SOURCE_EDGE,
    )

    assert projection["status"] == "succeeded"
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    }
    inserted = decoded_output(catalog, outputs["protein_prompt"])
    assert inserted.target_layout == ResidueLayout(
        "A,B",
        6,
        [
            "A:masked.1.2",
            "A:1",
            "A:2",
            "B:masked.1.1",
            "B:masked.1.3",
            "B:1",
        ],
    )
    assert inserted.sequence_track == ResidueTrack(
        [None, "A", "G", None, None, "S"],
        None,
    )
    assert inserted.secondary_structure_track == ResidueTrack(
        [None, "H", "E", None, None, "-"],
        None,
    )
    assert inserted.structure_visibility_track == ResidueTrack(
        [None, True, True, None, None, False],
        None,
    )
    assert [
        (
            annotation.start,
            annotation.end,
            annotation.start_residue_id,
            annotation.end_residue_id,
        )
        for annotation in inserted.function_annotations.annotations
    ] == [(2, 3, "A:1", "A:2")]
    residue_map = decoded_output(catalog, outputs["residue_map"])
    assert residue_map.mappings == (
        (-1, 0, "insert"),
        (0, 1, "match"),
        (1, 2, "match"),
        (-1, 3, "insert"),
        (-1, 4, "insert"),
        (2, 5, "match"),
    )


def test_zero_insertion_and_chain_restriction_are_explicit(
    tmp_path: Path,
) -> None:
    catalog, zero_projection, _ = run_operation(
        tmp_path / "zero",
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 73,
            "count": 0,
            "eligible_chain_ids": [],
        },
        source_edges=_SOURCE_EDGE,
    )
    zero_outputs = {
        output["output_port"]: output
        for output in zero_projection["outputs"]
        if output["node_id"] == "author"
    }
    zero_prompt = decoded_output(catalog, zero_outputs["protein_prompt"])
    zero_map = decoded_output(catalog, zero_outputs["residue_map"])
    assert zero_prompt.target_layout == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:2", "B:1"],
    )
    assert zero_map.mappings == (
        (0, 0, "match"),
        (1, 1, "match"),
        (2, 2, "match"),
    )

    catalog, chain_projection, _ = run_operation(
        tmp_path / "chain-b",
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 73,
            "count": 2,
            "eligible_chain_ids": ["B"],
        },
        source_edges=_SOURCE_EDGE,
    )
    chain_prompt = decoded_output(
        catalog,
        next(
            output
            for output in chain_projection["outputs"]
            if output["node_id"] == "author"
            and output["output_port"] == "protein_prompt"
        ),
    )
    inserted_ids = (
        set(chain_prompt.target_layout.residue_ids or ())
        - {"A:1", "A:2", "B:1"}
    )
    assert inserted_ids == {"B:masked.73.1", "B:masked.73.2"}
    assert chain_prompt.target_layout.residue_ids[:2] == ("A:1", "A:2")


def test_masked_insertion_rejects_unknown_chain_constraints(
    tmp_path: Path,
) -> None:
    _, projection, _ = run_operation(
        tmp_path,
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 73,
            "count": 1,
            "eligible_chain_ids": ["C"],
        },
        source_edges=_SOURCE_EDGE,
    )

    assert projection["status"] == "failed"


def test_masked_insertion_rejects_generated_residue_identity_collision(
    tmp_path: Path,
) -> None:
    _, projection, _ = run_operation(
        tmp_path,
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 1,
            "count": 1,
            "eligible_chain_ids": ["A"],
        },
        source_edges=_SOURCE_EDGE,
        source_fixture="insertion-identity-collision",
    )

    assert projection["status"] == "failed"


def test_canonical_3gb1_insertion_intent_is_an_ordinary_regression(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 1603,
            "count": 15,
            "eligible_chain_ids": ["A"],
        },
        source_edges=_SOURCE_EDGE,
        source_fixture="3gb1-intent",
    )
    inserted = decoded_output(
        catalog,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "author"
            and output["output_port"] == "protein_prompt"
        ),
    )

    assert inserted.target_layout.length == 71
    assert catalog.require_port_type(
        "protein.prompt",
        VERSION,
    ).content_digest(inserted) == (
        "sha256:4eab8a2f2da724eebd19ba5430de9c73afec264f59a07575b53aa0934eb73e19"
    )
    method = catalog.require_contract(
        "method",
        "prompt_authoring.random_insert_masked.method",
        "2.1.0",
    )
    assert method.descriptor["algorithm_identity"]["sampling"] == (
        "sha256-boundary-set-digest-counter-modulo-v1"
    )
