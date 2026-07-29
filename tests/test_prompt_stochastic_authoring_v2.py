"""Public v2 acceptance for reproducible stochastic prompt authoring."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core import (
    CatalogBuildError,
    WorkflowAuthoringError,
    build_frozen_catalog,
    build_discovered_frozen_catalog,
    discover_module_packages,
)
from core.server import create_app
from core.workflow_v2 import WorkflowEdge
from datatypes import ResidueLayout, ResidueTrack
from fastapi.testclient import TestClient
from protein_workbench_public import validate_response
from modules.prompt_authoring.package import MODULE_PACKAGE
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)

from tests.fixtures.prompt_authoring_v2 import (
    VERSION,
    decoded_output,
    prepare_operation,
    run_operation,
)


def test_stochastic_prompt_authoring_registers_two_exact_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["prompt_authoring"]
    assert {
        resource.resource for resource in registration.node_definitions
    } >= {
        "definitions/random_mask.yaml",
        "definitions/random_insert_masked.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    for operation in ("random_mask", "random_insert_masked"):
        node = catalog.require_contract(
            "node_type",
            f"prompt_authoring.{operation}",
            VERSION,
        )
        binding = catalog.require_contract(
            "binding",
            f"prompt_authoring.{operation}.direct",
            VERSION,
        )
        assert node.descriptor["category"] == "prompt_authoring"
        assert binding.descriptor["deterministic"] is True
        assert binding.descriptor["cacheable"] is True
        assert tuple(
            binding.descriptor["effective_randomness_parameters"]
        )


def test_randomness_declaration_cannot_name_an_undeclared_parameter() -> None:
    broken_bindings = tuple(
        (
            replace(
                binding,
                effective_randomness_parameters=("missing_randomness",),
            )
            if binding.binding_id == "prompt_authoring.random_mask.direct"
            else binding
        )
        for binding in MODULE_PACKAGE.bindings
    )

    with pytest.raises(CatalogBuildError, match="undeclared parameters"):
        build_frozen_catalog(
            (replace(MODULE_PACKAGE, bindings=broken_bindings),)
        )


def test_random_mask_clears_only_seeded_assigned_sequence_positions(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="random_mask",
        node_parameters={
            "effective_seed": 11,
            "count": 2,
            "track": "sequence",
            "eligible_residue_ids": [],
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
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    masked = decoded_output(catalog, output)
    assert masked.sequence_track == ResidueTrack(["A", None, None], None)
    assert masked.target_layout.residue_ids == ["A:1", "A:2", "B:1"]
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
            "A:1",
            "A:masked.1.2",
            "A:masked.1.3",
            "A:2",
            "A:masked.1.1",
            "B:1",
        ],
    )
    assert inserted.sequence_track == ResidueTrack(
        ["A", None, None, "G", None, "S"],
        None,
    )
    assert inserted.secondary_structure_track == ResidueTrack(
        ["H", None, None, "E", None, "-"],
        None,
    )
    assert inserted.structure_visibility_track == ResidueTrack(
        [True, None, None, True, None, False],
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
    ] == [(1, 4, "A:1", "A:2")]
    residue_map = decoded_output(catalog, outputs["residue_map"])
    assert residue_map.mappings == [
        (0, 0, "match"),
        (-1, 1, "insert"),
        (-1, 2, "insert"),
        (1, 3, "match"),
        (-1, 4, "insert"),
        (2, 5, "match"),
    ]


def test_exact_effective_randomness_replays_byte_equivalent_cached_prompt(
    tmp_path: Path,
) -> None:
    prepared = prepare_operation(
        tmp_path,
        operation="random_mask",
        node_parameters={
            "effective_seed": 73,
            "count": 2,
            "track": "sequence",
            "eligible_residue_ids": [],
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
    try:
        first, _ = prepared.start("stochastic-first")
        second, second_events = prepared.start("stochastic-second")
    finally:
        prepared.service.shutdown()

    first_output = next(
        output
        for output in first["outputs"]
        if output["node_id"] == "author"
    )
    second_output = next(
        output
        for output in second["outputs"]
        if output["node_id"] == "author"
    )
    assert second_output["values"] == first_output["values"]
    assert second_output["result_identity"] == first_output["result_identity"]
    assert (
        second_output["producer_provenance"]["producer_run_id"]
        == first["run_id"]
    )
    assert any(
        event["event"]["type"] == "node_attempt_terminal"
        and event["event"].get("resolution") == "cache_replayed"
        for event in second_events
    )


def test_every_stochastic_parameter_participates_in_result_identity(
    tmp_path: Path,
) -> None:
    variants = (
        {
            "effective_seed": 73,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 74,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 73,
            "count": 2,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 73,
            "count": 1,
            "track": "secondary_structure",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 73,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": ["A:1", "A:2"],
        },
    )
    identities: list[str] = []
    values: list[object] = []
    for index, parameters in enumerate((*variants, variants[0])):
        _, projection, _ = run_operation(
            tmp_path / str(index),
            operation="random_mask",
            node_parameters=parameters,
            source_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "author",
                    "protein_prompt",
                ),
            ),
        )
        output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "author"
        )
        identities.append(output["result_identity"])
        values.append(output["values"])

    assert len(set(identities[:5])) == 5
    assert identities[-1] == identities[0]
    assert values[-1] == values[0]


def test_zero_and_full_masks_preserve_nullable_track_semantics(
    tmp_path: Path,
) -> None:
    outputs = []
    for label, count in (("zero", 0), ("full", 3)):
        catalog, projection, _ = run_operation(
            tmp_path / label,
            operation="random_mask",
            node_parameters={
                "effective_seed": 1603,
                "count": count,
                "track": "sequence",
                "eligible_residue_ids": [],
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
        outputs.append(
            decoded_output(
                catalog,
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

    catalog, structure_projection, _ = run_operation(
        tmp_path / "structure",
        operation="random_mask",
        node_parameters={
            "effective_seed": 1603,
            "count": 2,
            "track": "structure",
            "eligible_residue_ids": [],
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
    structure_masked = decoded_output(
        catalog,
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
    _, projection, _ = run_operation(
        tmp_path,
        operation="random_mask",
        node_parameters=parameters,
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
        ),
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
            source_edges=(
                WorkflowEdge(
                    "source",
                    "protein_prompt",
                    "author",
                    "protein_prompt",
                ),
            ),
        )

    assert rejected.value.code == "compile_rejected"


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
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
        ),
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
    assert zero_map.mappings == [
        (0, 0, "match"),
        (1, 1, "match"),
        (2, 2, "match"),
    ]

    catalog, chain_projection, _ = run_operation(
        tmp_path / "chain-b",
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 73,
            "count": 2,
            "eligible_chain_ids": ["B"],
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
    assert chain_prompt.target_layout.residue_ids[:2] == ["A:1", "A:2"]


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
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
        ),
    )

    assert projection["status"] == "failed"


def test_canonical_3gb1_mask_and_insert_intent_is_an_ordinary_regression(
    tmp_path: Path,
) -> None:
    source_edge = (
        WorkflowEdge(
            "source",
            "protein_prompt",
            "author",
            "protein_prompt",
        ),
    )
    catalog, mask_projection, _ = run_operation(
        tmp_path / "mask",
        operation="random_mask",
        node_parameters={
            "effective_seed": 1603,
            "count": 20,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        source_edges=source_edge,
        source_fixture="3gb1-intent",
    )
    masked = decoded_output(
        catalog,
        next(
            output
            for output in mask_projection["outputs"]
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

    catalog, insert_projection, _ = run_operation(
        tmp_path / "insert",
        operation="random_insert_masked",
        node_parameters={
            "effective_seed": 1603,
            "count": 15,
            "eligible_chain_ids": ["A"],
        },
        source_edges=source_edge,
        source_fixture="3gb1-intent",
    )
    inserted = decoded_output(
        catalog,
        next(
            output
            for output in insert_projection["outputs"]
            if output["node_id"] == "author"
            and output["output_port"] == "protein_prompt"
        ),
    )
    assert inserted.target_layout.length == 71
    assert catalog.require_port_type(
        "protein.prompt",
        "2.1.0",
    ).content_digest(inserted) == (
        "sha256:6b15097b6d529e25fe70f3e7f369a96801db0453a7d9293e571c64248f83a8b4"
    )
    method = catalog.require_contract(
        "method",
        "prompt_authoring.random_insert_masked.method",
        VERSION,
    )
    assert method.descriptor["algorithm_identity"]["sampling"] == (
        "sha256-counter-modulo-v1"
    )


def test_stochastic_prompt_authoring_executes_through_public_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))

    with TestClient(create_app(frozen_catalog_override=catalog)) as client:
        project_id = client.post(
            "/api/projects",
            json={"name": "stochastic prompt public journey"},
        ).json()["id"]
        workflow = {
            "schema_version": VERSION,
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "source",
                    "node_type_id": "contract_test.prompt_authoring_values",
                    "node_type_version": VERSION,
                    "binding_id": (
                        "contract_test.prompt_authoring_values.direct"
                    ),
                    "binding_version": VERSION,
                    "node_parameters": {"fixture": "canonical"},
                    "binding_parameters": {},
                },
                {
                    "node_id": "mask",
                    "node_type_id": "prompt_authoring.random_mask",
                    "node_type_version": VERSION,
                    "binding_id": "prompt_authoring.random_mask.direct",
                    "binding_version": VERSION,
                    "node_parameters": {
                        "effective_seed": 73,
                        "count": 1,
                        "track": "sequence",
                        "eligible_residue_ids": [],
                    },
                    "binding_parameters": {},
                },
            ],
            "edges": [
                {
                    "source_node_id": "source",
                    "source_port": "protein_prompt",
                    "target_node_id": "mask",
                    "target_port": "protein_prompt",
                },
            ],
            "contract_lock": [],
        }
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": saved.json()["workflow_revision"]},
        )
        assert relocked.status_code == 200
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked.json()["workflow_revision"],
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": relocked.json()["workflow_revision"],
                "compile_id": compiled.json()["compile_id"],
                "client_request_id": "stochastic-public-run",
            },
        )
        assert started.status_code == 202
        validate_response("start_run", 202, started.json())
        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{started.json()['run_id']}"
        )
        assert projection.status_code == 200
        validate_response("run_projection", 200, projection.json())

    assert projection.json()["status"] == "succeeded"
    assert any(
        output["node_id"] == "mask"
        and output["output_port"] == "protein_prompt"
        for output in projection.json()["outputs"]
    )
