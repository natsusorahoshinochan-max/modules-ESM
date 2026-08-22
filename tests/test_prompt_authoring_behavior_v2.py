"""Differential and public-protocol prompt-authoring acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.workflow.authoring import WorkflowAuthoringError
from protein_workbench_public.bootstrap import create_application
from core.workflow.document import WorkflowEdge
from datatypes.residue import ResidueLayout
from modules.prompt_authoring.domain import AlignedResidueTrack
from modules.prompt_authoring.package import MODULE_PACKAGE
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from protein_workbench_public import prepare_rest_request, validate_response
from tests.fixtures.prompt_authoring_v2 import (
    TARGET_LAYOUT,
    VERSION,
    WORKFLOW_SCHEMA_VERSION,
    decoded_output,
    run_operation,
    wire_value,
)
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)


def _author_output(projection: dict[str, Any]) -> dict[str, Any]:
    return next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )


@pytest.mark.parametrize(
    "edits",
    (
        [
            {
                "operation": "insert",
                "chain_id": "A",
                "residue_id": "A:outside",
            }
        ],
        [
            {
                "operation": "insert",
                "chain_id": "B",
                "residue_id": "A:new",
            },
            {
                "operation": "delete",
                "chain_id": "A",
                "residue_id": "A:2",
            },
        ],
        [
            {
                "operation": "insert",
                "chain_id": "A",
                "residue_id": "A:new",
            }
        ],
    ),
)
def test_residue_edits_reject_range_chain_and_length_drift(
    tmp_path: Path,
    edits: list[dict[str, object]],
) -> None:
    _, _, projection, _ = run_operation(
        tmp_path,
        operation="edit_residue_layout",
        node_parameters={"edits": edits},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "source_layout"),
            WorkflowEdge("source", "target_layout", "author", "target_layout"),
        ),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "author"
        for output in projection["outputs"]
    )


@pytest.mark.parametrize(
    "fixture",
    (
        "source-track-length-drift",
        "overlapping-residue-map",
        "unmapped-residue-map",
        "noncontiguous-chain-layout",
        "contradictory-residue-map",
    ),
)
def test_track_mapping_rejects_misalignment_and_malformed_maps(
    tmp_path: Path,
    fixture: str,
) -> None:
    _, _, projection, _ = run_operation(
        tmp_path,
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "source_sequence_track",
                "author",
                "sequence_track",
            ),
            WorkflowEdge("source", "residue_map", "author", "residue_map"),
        ),
        source_fixture=fixture,
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "author"
        for output in projection["outputs"]
    )


def test_nominal_tracks_cannot_connect_by_structural_similarity(
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkflowAuthoringError) as rejected:
        run_operation(
            tmp_path,
            operation="map_residue_track",
            node_parameters={},
            source_edges=(
                WorkflowEdge(
                    "source",
                    "source_sequence_track",
                    "author",
                    "secondary_structure_track",
                ),
                WorkflowEdge(
                    "source",
                    "residue_map",
                    "author",
                    "residue_map",
                ),
            ),
        )

    assert rejected.value.code == "compile_rejected"
    assert rejected.value.details["issues"][0]["code"] == (
        "port_type_mismatch"
    )


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
    outputs = {
        output["output_port"]: decoded_output(
            catalog,
            service,
            projection,
            output,
        )
        for output in projection["outputs"]
        if output["node_id"] == "author"
    }
    assert outputs["layout"] == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:2", "B:1"],
    )
    assert outputs["protein_prompt"].sequence_track.values == (
        "A",
        "G",
        "S",
    )


def test_override_rejects_unknown_residue_without_shifting_positions(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = run_operation(
        tmp_path,
        operation="override_residue_track",
        node_parameters={
            "overrides": [
                {
                    "action": "replace",
                    "residue_id": "B:outside",
                    "value": "H",
                }
            ],
        },
        source_edges=(
            WorkflowEdge("source", "target_layout", "author", "target_layout"),
            WorkflowEdge(
                "source",
                "target_secondary_structure_track",
                "author",
                "secondary_structure_track",
            ),
        ),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "author"
        for output in projection["outputs"]
    )


def test_provider_free_identity_ignores_environment_configuration(
    tmp_path: Path,
) -> None:
    identities: list[str] = []
    values: list[object] = []
    for label in ("one", "two"):
        catalog, service, projection, events = run_operation(
            tmp_path / label,
            operation="build_residue_layout",
            node_parameters={
                "chains": [
                    {"chain_id": "A", "length": 2},
                    {"chain_id": "B", "length": 1},
                ]
            },
            environment_label=label,
        )
        assert projection["status"] == "succeeded"
        output = _author_output(projection)
        identities.append(output["result_identity"])
        values.append(decoded_output(catalog, service, projection, output))
        assert "not-result-affecting" not in json.dumps(
            {"projection": projection, "events": events},
            sort_keys=True,
        )

    assert identities[0] == identities[1]
    assert values[0] == values[1]


def test_insertion_deletion_boundaries_and_chain_breaks_remain_explicit(
    tmp_path: Path,
) -> None:
    shifted_layout = ResidueLayout(
        "A,B",
        4,
        ["A:new", "A:1", "B:1", "B:new"],
    )
    catalog, edit_service, edit_projection, _ = run_operation(
        tmp_path / "edit",
        operation="edit_residue_layout",
        node_parameters={
            "edits": [
                {
                    "operation": "insert",
                    "chain_id": "A",
                    "residue_id": "A:new",
                },
                {
                    "operation": "delete",
                    "chain_id": "A",
                    "residue_id": "A:2",
                },
                {
                    "operation": "insert",
                    "chain_id": "B",
                    "residue_id": "B:new",
                },
            ]
        },
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "source_layout"),
            WorkflowEdge("source", "target_layout", "author", "target_layout"),
        ),
        source_fixture="boundary-edit",
    )
    residue_map = decoded_output(
        catalog,
        edit_service,
        edit_projection,
        _author_output(edit_projection),
    )
    assert residue_map.mappings == (
        (-1, 0, "insert"),
        (0, 1, "match"),
        (2, 2, "match"),
        (-1, 3, "insert"),
        (1, -1, "delete"),
    )

    catalog, map_service, map_projection, _ = run_operation(
        tmp_path / "map",
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "source_sequence_track",
                "author",
                "sequence_track",
            ),
            WorkflowEdge("source", "residue_map", "author", "residue_map"),
        ),
        source_fixture="boundary-edit",
    )
    assert decoded_output(
        catalog,
        map_service,
        map_projection,
        _author_output(map_projection),
    ) == AlignedResidueTrack(
        shifted_layout,
        (None, "A", "S", None),
    )


def test_visibility_track_mapping_keeps_nullable_positions_explicit(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "source_visibility_track",
                "author",
                "visibility_track",
            ),
            WorkflowEdge("source", "residue_map", "author", "residue_map"),
        ),
    )

    assert decoded_output(
        catalog,
        service,
        projection,
        _author_output(projection),
    ) == AlignedResidueTrack(
        TARGET_LAYOUT,
        (True, None, False),
    )


def test_structure_override_accepts_named_atom_coordinates(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation="override_residue_track",
        node_parameters={
            "overrides": [
                {
                    "action": "replace",
                    "residue_id": "A:1",
                    "value": {
                        "atom_coordinates": [
                            {
                                "atom_name": "N",
                                "coordinates": [0.0, 1.0, 2.0],
                            },
                            {
                                "atom_name": "CA",
                                "coordinates": [1.0, 2.0, 3.0],
                            },
                        ]
                    },
                }
            ],
        },
        source_edges=(
            WorkflowEdge("source", "target_layout", "author", "target_layout"),
            WorkflowEdge(
                "source",
                "target_structure_track",
                "author",
                "structure_track",
            ),
        ),
    )

    assert decoded_output(
        catalog,
        service,
        projection,
        _author_output(projection),
    ) == AlignedResidueTrack(
        TARGET_LAYOUT,
        (
            {
                "N": (0.0, 1.0, 2.0),
                "CA": (1.0, 2.0, 3.0),
            },
            None,
            None,
        ),
    )


def test_secondary_structure_layout_shift_regression_is_nominal_and_stable(
    tmp_path: Path,
) -> None:
    shifted_layout = ResidueLayout(
        "A,B",
        4,
        ["A:new", "A:1", "B:1", "B:new"],
    )
    catalog, mapped_service, mapped_projection, _ = run_operation(
        tmp_path / "map",
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "source_secondary_structure_track",
                "author",
                "secondary_structure_track",
            ),
            WorkflowEdge("source", "residue_map", "author", "residue_map"),
        ),
        source_fixture="boundary-edit",
    )
    assert decoded_output(
        catalog,
        mapped_service,
        mapped_projection,
        _author_output(mapped_projection),
    ) == AlignedResidueTrack(
        shifted_layout,
        (None, "H", "-", None),
    )

    catalog, overridden_service, overridden_projection, _ = run_operation(
        tmp_path / "override",
        operation="override_residue_track",
        node_parameters={
            "overrides": [
                {
                    "action": "replace",
                    "residue_id": "A:new",
                    "value": "E",
                },
                {"action": "preserve", "residue_id": "A:1"},
                {"action": "clear", "residue_id": "B:1"},
                {
                    "action": "replace",
                    "residue_id": "B:new",
                    "value": "H",
                },
            ]
        },
        source_edges=(
            WorkflowEdge("source", "target_layout", "author", "target_layout"),
            WorkflowEdge(
                "source",
                "target_secondary_structure_track",
                "author",
                "secondary_structure_track",
            ),
        ),
        source_fixture="boundary-edit",
    )
    assert decoded_output(
        catalog,
        overridden_service,
        overridden_projection,
        _author_output(overridden_projection),
    ) == AlignedResidueTrack(
        shifted_layout,
        ("E", "H", None, "H"),
    )


def test_prompt_authoring_executes_through_the_public_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))

    catalog_override = build_frozen_catalog(
        (MODULE_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )
    with TestClient(
        create_application(frozen_catalog_override=catalog_override)
    ) as client:
        def public_request(
            operation_id: str,
            request: dict[str, Any],
            expected_status: int,
        ):
            prepared = prepare_rest_request(operation_id, request)
            response = client.request(
                prepared.method,
                prepared.route,
                json=prepared.json_body,
            )
            assert response.status_code == expected_status
            validate_response(operation_id, expected_status, response.json())
            return response

        catalog = public_request("catalog_snapshot", {}, 200).json()
        assert any(
            contract["reference"]["contract_id"]
            == "prompt_authoring.build_residue_layout"
            for contract in catalog["contracts"]
        )
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "prompt authoring public journey"},
        ).json()["id"]
        workflow = {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "workflow_id": project_id,
            "nodes": [{
                "node_id": "layout",
                "node_type_id": "prompt_authoring.build_residue_layout",
                "node_type_version": VERSION,
                "binding_id": (
                    "prompt_authoring.build_residue_layout.direct"
                ),
                "binding_version": VERSION,
                "node_parameters": {
                    "chains": [
                        {"chain_id": "A", "length": 2},
                        {"chain_id": "B", "length": 1},
                    ]
                },
                "binding_parameters": {},
            }],
            "edges": [],
            "contract_lock": [],
        }
        committed = public_request(
            "commit_project_workflow",
            {
                "project_id": project_id,
                "workflow": workflow,
            },
            200,
        ).json()
        started = public_request(
            "start_run",
            {
                "project_id": project_id,
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "prompt-authoring-public",
            },
            202,
        ).json()
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started["run_id"],
        )

        assert projection["status"] == "succeeded"
        output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "layout"
        )
        values = retrieve_typed_output_values(
            client,
            project_id,
            started["run_id"],
            output,
        )

    assert values == [
        wire_value(
            "residue.layout",
            ResidueLayout(
                "A,B",
                3,
                ["A:1", "A:2", "B:1"],
            ),
        )
    ]
