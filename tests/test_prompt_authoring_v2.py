"""Public v2 contracts for cohesive residue-layout and track authoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowCompileError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    build_discovered_frozen_catalog,
    builtin_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.workflow_v2 import WorkflowEdge
from core.port_types import canonical_json_bytes
from datatypes import ResidueLayout, ResidueMap, ResidueTrack
from modules.prompt_authoring.package import MODULE_PACKAGE
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


_VERSION = "2.0.0"


def test_prompt_authoring_is_one_package_with_four_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["prompt_authoring"]
    assert registration.package_module == "modules.prompt_authoring"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/build_residue_layout.yaml",
        "definitions/edit_residue_layout.yaml",
        "definitions/map_residue_track.yaml",
        "definitions/override_residue_track.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "prompt_authoring" in catalog.owners[
            (kind, contract_id, version)
        ]
    }
    assert owned_nodes == {
        ("prompt_authoring.build_residue_layout", _VERSION),
        ("prompt_authoring.edit_residue_layout", _VERSION),
        ("prompt_authoring.map_residue_track", _VERSION),
        ("prompt_authoring.override_residue_track", _VERSION),
    }


_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.prompt_authoring_values",
    node_type_version=_VERSION,
    binding_id="contract_test.prompt_authoring_values.direct",
    binding_version=_VERSION,
    node_parameters={},
    binding_parameters={},
)
_SOURCE_LAYOUT = ResidueLayout(
    chain_id="A,B",
    length=3,
    residue_ids=["A:1", "A:2", "B:1"],
)
_TARGET_LAYOUT = ResidueLayout(
    chain_id="A,B",
    length=3,
    residue_ids=["A:1", "A:new", "B:1"],
)
_RESIDUE_MAP = ResidueMap(
    source_layout=_SOURCE_LAYOUT,
    target_layout=_TARGET_LAYOUT,
    mappings=[
        (0, 0, "match"),
        (-1, 1, "insert"),
        (2, 2, "match"),
        (1, -1, "delete"),
    ],
)


def _wire_value(type_id: str, value: object) -> object:
    encoded = builtin_frozen_catalog().require_port_type(
        type_id,
        _VERSION,
    ).encode(value)
    return json.loads(encoded)["value"]


def _decoded_output(catalog: Any, output: dict[str, Any]) -> object:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": reference["contract_id"],
                "port_type_version": reference["contract_version"],
                "value": output["values"][0],
            }
        )
    )


def _run_operation(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any],
    source_edges: tuple[WorkflowEdge, ...] = (),
    source_fixture: str = "canonical",
    environment_label: str = "one",
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"prompt authoring {operation}")
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.prompt_authoring_values",
        node_type_version=_VERSION,
        binding_id="contract_test.prompt_authoring_values.direct",
        binding_version=_VERSION,
        node_parameters={"fixture": source_fixture},
        binding_parameters={},
    )
    binding_id = f"prompt_authoring.{operation}.direct"
    workflow = WorkflowDocument(
        schema_version=_VERSION,
        workflow_id=project.id,
        nodes=(
            *((source,) if source_edges else ()),
            WorkflowNodeInstance(
                node_id="author",
                node_type_id=f"prompt_authoring.{operation}",
                node_type_version=_VERSION,
                binding_id=binding_id,
                binding_version=_VERSION,
                node_parameters=node_parameters,
                binding_parameters={},
            ),
        ),
        edges=source_edges,
        contract_lock=(),
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (binding_id, _VERSION): {
                    "values": {
                        "credential": f"not-result-affecting-{environment_label}",
                    },
                    "safe_fingerprint": f"environment-{environment_label}",
                    "invalidation_token": f"environment-{environment_label}",
                }
            }
        ),
    )
    receipt = service.start_background(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id=f"prompt-authoring-{operation}-{environment_label}",
    )
    service.shutdown()
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    return catalog, projection, events


def test_all_four_nodes_execute_through_shared_contract_kit(
    tmp_path: Path,
) -> None:
    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=(
            ModulePackageContractCase(
                case_id="prompt-authoring-build-layout",
                node_type_id="prompt_authoring.build_residue_layout",
                node_type_version=_VERSION,
                binding_id="prompt_authoring.build_residue_layout.direct",
                binding_version=_VERSION,
                node_parameters={
                    "chains": [
                        {"chain_id": "A", "length": 2},
                        {"chain_id": "B", "length": 1},
                    ],
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-build-layout-v1",
                expected_scalar_outputs={
                    "layout": _wire_value(
                        "residue.layout",
                        ResidueLayout(
                            chain_id="A,B",
                            length=3,
                            residue_ids=["A:1", "A:2", "B:1"],
                        ),
                    ),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-edit-layout",
                node_type_id="prompt_authoring.edit_residue_layout",
                node_type_version=_VERSION,
                binding_id="prompt_authoring.edit_residue_layout.direct",
                binding_version=_VERSION,
                node_parameters={
                    "edits": [
                        {
                            "operation": "delete",
                            "chain_id": "A",
                            "residue_id": "A:2",
                        },
                        {
                            "operation": "insert",
                            "chain_id": "A",
                            "residue_id": "A:new",
                        },
                    ]
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-edit-layout-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "source_layout",
                        "contract-test-node",
                        "source_layout",
                    ),
                    WorkflowEdge(
                        "source",
                        "target_layout",
                        "contract-test-node",
                        "target_layout",
                    ),
                ),
                expected_scalar_outputs={
                    "residue_map": _wire_value(
                        "residue.map",
                        _RESIDUE_MAP,
                    ),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-map-track",
                node_type_id="prompt_authoring.map_residue_track",
                node_type_version=_VERSION,
                binding_id="prompt_authoring.map_residue_track.direct",
                binding_version=_VERSION,
                node_parameters={},
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-map-track-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "source_track",
                        "contract-test-node",
                        "track",
                    ),
                    WorkflowEdge(
                        "source",
                        "residue_map",
                        "contract-test-node",
                        "residue_map",
                    ),
                ),
                expected_scalar_outputs={
                    "track": _wire_value(
                        "residue.track",
                        ResidueTrack(["H", None, "-"], None),
                    ),
                },
            ),
            ModulePackageContractCase(
                case_id="prompt-authoring-override-track",
                node_type_id="prompt_authoring.override_residue_track",
                node_type_version=_VERSION,
                binding_id="prompt_authoring.override_residue_track.direct",
                binding_version=_VERSION,
                node_parameters={
                    "overrides": [
                        {
                            "action": "replace",
                            "residue_id": "A:1",
                            "value": "E",
                        },
                        {
                            "action": "clear",
                            "residue_id": "A:new",
                        },
                        {
                            "action": "preserve",
                            "residue_id": "B:1",
                        },
                    ]
                },
                binding_parameters={},
                environment_values={},
                safe_environment_fingerprint="provider-free",
                invalidation_token="prompt-authoring-override-track-v1",
                workflow_nodes=(_SOURCE,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "target_layout",
                        "contract-test-node",
                        "target_layout",
                    ),
                    WorkflowEdge(
                        "source",
                        "target_secondary_structure_track",
                        "contract-test-node",
                        "secondary_structure_track",
                    ),
                ),
                expected_scalar_outputs={
                    "secondary_structure_track": _wire_value(
                        "residue.track.secondary_structure",
                        ResidueTrack(["E", None, "-"], None),
                    ),
                },
            ),
        ),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert {
        identity
        for case in report.case_reports
        for identity in case.result_identities
    }


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
def test_residue_edits_fail_closed_for_out_of_range_chain_and_length_drift(
    tmp_path: Path,
    edits: list[dict[str, object]],
) -> None:
    _, projection, _ = _run_operation(
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
    ),
)
def test_track_mapping_rejects_misalignment_and_malformed_maps(
    tmp_path: Path,
    fixture: str,
) -> None:
    _, projection, _ = _run_operation(
        tmp_path,
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_track", "author", "track"),
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
    with pytest.raises(WorkflowCompileError) as rejected:
        _run_operation(
            tmp_path,
            operation="map_residue_track",
            node_parameters={},
            source_edges=(
                WorkflowEdge(
                    "source",
                    "source_track",
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

    assert rejected.value.code == "port_type_mismatch"


def test_override_rejects_unknown_residue_without_shifting_positions(
    tmp_path: Path,
) -> None:
    _, projection, _ = _run_operation(
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


def test_provider_free_layout_identity_ignores_environment_configuration(
    tmp_path: Path,
) -> None:
    identities: list[str] = []
    values: list[object] = []
    for label in ("one", "two"):
        _, projection, events = _run_operation(
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
        output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "author"
        )
        identities.append(output["result_identity"])
        values.append(output["values"])
        assert "not-result-affecting" not in json.dumps(
            {"projection": projection, "events": events},
            sort_keys=True,
        )

    assert identities[0] == identities[1]
    assert values[0] == values[1]


def test_insertion_deletion_boundaries_and_chain_breaks_remain_explicit(
    tmp_path: Path,
) -> None:
    edits = [
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
    catalog, edit_projection, _ = _run_operation(
        tmp_path / "edit",
        operation="edit_residue_layout",
        node_parameters={"edits": edits},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "source_layout"),
            WorkflowEdge("source", "target_layout", "author", "target_layout"),
        ),
        source_fixture="boundary-edit",
    )
    assert edit_projection["status"] == "succeeded"
    residue_map = _decoded_output(
        catalog,
        next(
            output
            for output in edit_projection["outputs"]
            if output["node_id"] == "author"
        ),
    )
    assert residue_map.mappings == [
        (-1, 0, "insert"),
        (0, 1, "match"),
        (2, 2, "match"),
        (-1, 3, "insert"),
        (1, -1, "delete"),
    ]

    catalog, map_projection, _ = _run_operation(
        tmp_path / "map",
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_track", "author", "track"),
            WorkflowEdge("source", "residue_map", "author", "residue_map"),
        ),
        source_fixture="boundary-edit",
    )
    assert map_projection["status"] == "succeeded"
    mapped = _decoded_output(
        catalog,
        next(
            output
            for output in map_projection["outputs"]
            if output["node_id"] == "author"
        ),
    )
    assert mapped == ResidueTrack([None, "H", "-", None], None)


def test_visibility_track_mapping_keeps_nullable_positions_explicit(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = _run_operation(
        tmp_path,
        operation="map_residue_track",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "source_visibility_track",
                "author",
                "track",
            ),
            WorkflowEdge("source", "residue_map", "author", "residue_map"),
        ),
    )

    assert projection["status"] == "succeeded"
    mapped = _decoded_output(
        catalog,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "author"
        ),
    )
    assert mapped == ResidueTrack([True, None, False], None)
