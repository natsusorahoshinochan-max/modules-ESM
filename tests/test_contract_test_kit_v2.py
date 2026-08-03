"""Executable maintainer contract for a zero-Core Module Package."""

from __future__ import annotations

from dataclasses import replace
import importlib
import json
from pathlib import Path
import shutil
import sys

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core import (
    CatalogBuildError,
    ModulePackageDiscoveryError,
    ModulePackageConformanceError,
    PortTypeDefinition,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    verify_module_package_contract,
)
from core.server import create_app
from protein_workbench_public import (
    prepare_run_event_stream_request,
    prepare_rest_request,
    validate_artifact_response,
    validate_event,
    validate_response,
)
from tests.fixtures.zero_core_packages.synthetic_echo.tests.cases import (
    ARTIFACT_PORT_CASE,
    EXECUTION_CASE,
    PORT_CASE,
    SOURCE_EXECUTION_CASE,
)
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal
from tests.fixtures.zero_core_packages.synthetic_echo.tests.invalid_registrations import (
    FALSE_READINESS_PACKAGE,
    INCOMPLETE_PROVENANCE_PACKAGE,
)


FIXTURE_ROOT = "tests.fixtures.zero_core_packages"
EXECUTION_CASES = (SOURCE_EXECUTION_CASE, EXECUTION_CASE)


def _forget_packages(root_name: str) -> None:
    for name in tuple(sys.modules):
        if name == root_name or name.startswith(f"{root_name}."):
            sys.modules.pop(name)
    importlib.invalidate_caches()


def test_contract_test_kit_executes_the_discovered_production_registration(
    tmp_path: Path,
) -> None:
    registration = discover_module_packages(FIXTURE_ROOT)[0]
    discovered = build_discovered_frozen_catalog(FIXTURE_ROOT)

    report = verify_module_package_contract(
        registration,
        execution_cases=EXECUTION_CASES,
        port_cases=(PORT_CASE, ARTIFACT_PORT_CASE),
        work_root=tmp_path,
    )

    assert report.catalog_contract_digest == discovered.contract_digest
    assert report.package_id == registration.package_id
    case_reports = {
        case_report.case_id: case_report
        for case_report in report.case_reports
    }
    source_report = case_reports[SOURCE_EXECUTION_CASE.case_id]
    scorer_report = case_reports[EXECUTION_CASE.case_id]
    assert source_report.status == "succeeded"
    assert source_report.output_ports == ("candidates", "text")
    assert source_report.artifact_ports == ("artifact",)
    assert scorer_report.status == "succeeded"
    assert scorer_report.output_ports == (
        "candidates",
        "scores",
        "text",
    )
    assert scorer_report.artifact_ports == ("artifact",)
    assert scorer_report.event_types[-1] == "run_terminal"
    assert len(scorer_report.event_sequences) == len(
        set(scorer_report.event_sequences)
    )
    assert build_frozen_catalog((registration,)).contract_digest == (
        report.catalog_contract_digest
    )
    published = json.dumps(report.to_public(), sort_keys=True)
    assert "contract-test-secret-must-not-publish" not in published
    assert "/private/contract-test-runtime" not in published


def test_contract_test_case_rejects_a_path_like_case_identity() -> None:
    with pytest.raises(
        ModulePackageConformanceError,
        match="case_id must be one safe path segment",
    ):
        replace(EXECUTION_CASE, case_id="../escaped-case")


def test_contract_test_kit_requires_cases_for_every_owned_port_type(
    tmp_path: Path,
) -> None:
    registration = discover_module_packages(FIXTURE_ROOT)[0]

    with pytest.raises(
        ModulePackageConformanceError,
        match="Port cases must cover every package-owned Port Type",
    ):
        verify_module_package_contract(
            registration,
            execution_cases=EXECUTION_CASES,
            port_cases=(),
            work_root=tmp_path,
        )


def test_cases_and_fixtures_are_not_part_of_production_registration() -> None:
    registration = discover_module_packages(FIXTURE_ROOT)[0]

    registered_resources = {
        resource.resource
        for resource in (
            *registration.node_definitions,
            *registration.metric_definitions,
        )
    }

    assert registered_resources == {
        "definitions/candidate_source.yaml",
        "definitions/echo.yaml",
        "definitions/identity_metric.yaml",
    }
    assert all(
        "test" not in Path(resource).parts
        and "tests" not in Path(resource).parts
        and "fixture" not in Path(resource).parts
        and "fixtures" not in Path(resource).parts
        for resource in registered_resources
    )
    production = build_discovered_frozen_catalog()
    assert not any(
        contract.contract_id.startswith("contract_test.synthetic")
        for contract in production.contracts
    )


def test_source_and_scorer_publish_distinct_exact_contracts() -> None:
    catalog = build_discovered_frozen_catalog(FIXTURE_ROOT)
    source_node = catalog.require_contract(
        "node_type",
        SOURCE_EXECUTION_CASE.node_type_id,
        SOURCE_EXECUTION_CASE.node_type_version,
    )
    scorer_node = catalog.require_contract(
        "node_type",
        EXECUTION_CASE.node_type_id,
        EXECUTION_CASE.node_type_version,
    )
    source_binding = catalog.require_contract(
        "binding",
        SOURCE_EXECUTION_CASE.binding_id,
        SOURCE_EXECUTION_CASE.binding_version,
    )
    scorer_binding = catalog.require_contract(
        "binding",
        EXECUTION_CASE.binding_id,
        EXECUTION_CASE.binding_version,
    )

    assert source_node.descriptor["inputs"] == ()
    assert scorer_node.descriptor["inputs"] == (
        {
            "name": "candidate_input",
            "port_type": catalog.require_contract(
                "port_type",
                "candidate.collection",
                "3.0.0",
            ).reference(),
            "required": True,
            "multiplicity": "one",
            "scientific_meaning": (
                "Admitted Candidate collection echoed as the scored subject."
            ),
        },
    )
    assert source_binding.descriptor["node_type"] == source_node.reference()
    assert scorer_binding.descriptor["node_type"] == scorer_node.reference()
    assert catalog.get_contract(
        "binding",
        "contract_test.synthetic_echo.source",
        "3.0.0",
    ) is None
    assert catalog.get_contract(
        "node_type",
        "contract_test.synthetic_echo",
        "3.0.0",
    ) is None


def test_source_public_journey_discovers_compiles_executes_replays_and_retrieves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    app = create_app(
        module_packages_package=FIXTURE_ROOT,
        v2_environment_configuration={
            (case.binding_id, case.binding_version): {
                "values": dict(case.environment_values),
                "safe_fingerprint": case.safe_environment_fingerprint,
                "invalidation_token": case.invalidation_token,
            }
            for case in EXECUTION_CASES
        },
    )

    with TestClient(app) as client:
        def public_request(
            operation_id: str,
            request: dict,
            *,
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

        catalog = public_request(
            "catalog_snapshot",
            {},
            expected_status=200,
        )
        assert catalog.json()["catalog_contract_digest"] == (
            build_discovered_frozen_catalog(FIXTURE_ROOT).contract_digest
        )
        project = client.post(
            "/api/v2/projects",
            json={"name": "source zero-Core extension"},
        ).json()
        project_id = project["id"]
        workflow = {
            "schema_version": "2.1.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "candidate-source",
                    "node_type_id": SOURCE_EXECUTION_CASE.node_type_id,
                    "node_type_version": SOURCE_EXECUTION_CASE.node_type_version,
                    "binding_id": SOURCE_EXECUTION_CASE.binding_id,
                    "binding_version": SOURCE_EXECUTION_CASE.binding_version,
                    "node_parameters": {"message": "SOURCE"},
                    "binding_parameters": {"repeat_count": 1},
                },
                {
                    "node_id": "synthetic-echo",
                    "node_type_id": EXECUTION_CASE.node_type_id,
                    "node_type_version": EXECUTION_CASE.node_type_version,
                    "binding_id": EXECUTION_CASE.binding_id,
                    "binding_version": EXECUTION_CASE.binding_version,
                    "node_parameters": dict(EXECUTION_CASE.node_parameters),
                    "binding_parameters": dict(
                        EXECUTION_CASE.binding_parameters
                    ),
                },
            ],
            "edges": [
                {
                    "source_node_id": "candidate-source",
                    "source_port": "candidates",
                    "target_node_id": "synthetic-echo",
                    "target_port": "candidate_input",
                }
            ],
            "contract_lock": [],
        }
        committed = public_request(
            "commit_project_workflow",
            {
                "project_id": project_id,
                "expected_draft_revision": 0,
                "workflow": workflow,
            },
            expected_status=200,
        )
        started = public_request(
            "start_run",
            {
                "project_id": project_id,
                "workflow_commit_id": committed.json()[
                    "workflow_commit_id"
                ],
                "client_request_id": "source-zero-core",
            },
            expected_status=202,
        )
        run_id = started.json()["run_id"]
        payload = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=run_id,
        )
        assert payload["status"] == "succeeded"
        assert {
            output["output_port"]: output["values"]
            for output in payload["outputs"]
            if output["node_id"] == "synthetic-echo"
            and output["output_port"] == "text"
        } == {"text": ["ECHOECHO"]}
        assert len(payload["artifact_index"]) == 2
        artifact = next(
            item
            for item in payload["artifact_index"]
            if item["node_id"] == "synthetic-echo"
        )
        artifact_request = prepare_rest_request(
            "artifact_retrieval",
            {
                "project_id": project_id,
                "run_id": run_id,
                "artifact_reference": artifact["artifact_reference"],
            },
        )
        retrieved = client.request(
            artifact_request.method,
            artifact_request.route,
        )
        assert retrieved.status_code == 200
        validate_artifact_response(
            {
                "artifact": artifact,
                "content_disposition": retrieved.headers[
                    "content-disposition"
                ],
            },
            retrieved.headers,
            retrieved.content,
        )
        assert retrieved.content == b"ECHOECHO"
        derived = public_request(
            "start_derived_run",
            {
                "project_id": project_id,
                "source_run_id": run_id,
                "policy": "force_selected",
                "node_ids": ["synthetic-echo"],
                "client_request_id": "source-zero-core-derived",
            },
            expected_status=202,
        )
        derived_projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=derived.json()["run_id"],
        )
        assert derived_projection["derived_from_run_id"] == run_id
        stream_request = prepare_run_event_stream_request(
            {"project_id": project_id, "run_id": run_id}
        )
        assert stream_request.transport == "websocket"
        with client.websocket_connect(
            stream_request.route
        ) as websocket:
            replay = []
            try:
                while True:
                    replay.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000

    for event in replay:
        validate_event(event)
    replay_types = [item["event"]["type"] for item in replay]
    assert replay_types[0] == "replay_started"
    assert "replay_complete" in replay_types
    assert replay_types[-1] == "replay_complete"
    durable_sequences = [
        item["sequence"]
        for item in replay
        if item["event"]["type"]
        not in {"replay_started", "replay_complete"}
    ]
    assert len(durable_sequences) == len(set(durable_sequences))
    published = json.dumps(
        {"projection": payload, "replay": replay},
        sort_keys=True,
    )
    assert "contract-test-secret-must-not-publish" not in published
    assert "/private/contract-test-runtime" not in published


def test_contract_test_kit_rejects_a_false_readiness_attestation(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ModulePackageConformanceError,
        match="failed shared conformance",
    ):
        verify_module_package_contract(
            FALSE_READINESS_PACKAGE,
            execution_cases=EXECUTION_CASES,
            port_cases=(PORT_CASE, ARTIFACT_PORT_CASE),
            work_root=tmp_path,
        )


def test_contract_test_kit_rejects_an_invalid_package_codec(
    tmp_path: Path,
) -> None:
    registration = discover_module_packages(FIXTURE_ROOT)[0]
    port_type = registration.port_types[0]
    invalid_port_type = PortTypeDefinition(
        type_id=port_type.type_id,
        version=port_type.version,
        validator=port_type.validator,
        codec=port_type.codec,
        content_identity=port_type.content_identity,
        runtime_validator=port_type.runtime_validator,
        runtime_to_wire=port_type.runtime_to_wire,
        runtime_from_wire=lambda value: 7,
    )

    with pytest.raises(
        ModulePackageConformanceError,
        match="codec conformance failed",
    ):
        verify_module_package_contract(
            replace(
                registration,
                port_types=(
                    invalid_port_type,
                    registration.port_types[1],
                ),
            ),
            execution_cases=EXECUTION_CASES,
            port_cases=(PORT_CASE, ARTIFACT_PORT_CASE),
            work_root=tmp_path,
        )


def test_contract_test_kit_rejects_incomplete_observation_provenance(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ModulePackageConformanceError,
        match="execution did not succeed",
    ):
        verify_module_package_contract(
            INCOMPLETE_PROVENANCE_PACKAGE,
            execution_cases=EXECUTION_CASES,
            port_cases=(PORT_CASE, ARTIFACT_PORT_CASE),
            work_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            'schema_version: "2.1.0"\nunknown_field: true\n',
            "unknown fields",
        ),
        ("schema_version: [", "malformed YAML"),
    ],
)
def test_malformed_or_unknown_definition_fails_before_catalog_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
    message: str,
) -> None:
    root_name = "negative_zero_core_packages"
    source = Path("tests/fixtures/zero_core_packages")
    destination = tmp_path / root_name
    shutil.copytree(source, destination)
    (
        destination
        / "synthetic_echo"
        / "definitions"
        / "echo.yaml"
    ).write_text(replacement, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        with pytest.raises(CatalogBuildError, match=message):
            build_discovered_frozen_catalog(root_name)
    finally:
        _forget_packages(root_name)


def test_eager_optional_dependency_import_fails_discovery_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_name = "eager_zero_core_packages"
    source = Path("tests/fixtures/zero_core_packages")
    destination = tmp_path / root_name
    shutil.copytree(source, destination)
    package_path = destination / "synthetic_echo" / "package.py"
    package_path.write_text(
        "import synthetic_optional_provider_that_is_not_installed\n"
        + package_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        with pytest.raises(
            ModulePackageDiscoveryError,
            match="Failed to import explicit Module Package registration",
        ):
            discover_module_packages(root_name)
    finally:
        _forget_packages(root_name)
