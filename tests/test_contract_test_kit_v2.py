"""Executable maintainer contract for a zero-Core Module Package."""

from __future__ import annotations

from tests.support.public_runs import PublicRunClient

from protein_workbench_public.bootstrap import module_registrations

from dataclasses import replace
import importlib
import json
from pathlib import Path
import shutil
import sys

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.execution.ledger import EngineInvocationStarted, EngineInvocationTerminal
from datatypes.candidate import CandidateCollection
from datatypes.observation import ScoreCollection
from datatypes.sequence import ProteinSequence
from core.catalog.errors import CatalogBuildError
from core.catalog.port_contract import PortTypeDefinition
from tests.support.contract_test_kit import (
    ModulePackageConformanceError,
    execute_module_package_case,
    verify_module_package_port,
    ModulePackageContractCase,
    ModulePackagePortCase,
)
from tests.support.application import create_application
from tests.support.public_request import (
    prepare_run_event_stream_request,
    prepare_rest_request,
)
from tests.support.protocol import (
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
from tests.support.inprocess_runs import wait_for_testclient_run_terminal
from tests.fixtures.zero_core_packages.synthetic_echo.tests.invalid_registrations import (
    FALSE_READINESS_PACKAGE,
    INCOMPLETE_PROVENANCE_PACKAGE,
)
from tests.fixtures.zero_core_packages.synthetic_echo.package import (
    MODULE_PACKAGE as FIXTURE_PACKAGE,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "zero_core_packages"
)


@pytest.mark.parametrize(
    "case", (SOURCE_EXECUTION_CASE, EXECUTION_CASE), ids=lambda case: case.case_id
)
@pytest.mark.parametrize("invocation_count", (0, 1, 2))
def test_contract_test_kit_returns_only_the_target_engine_calls(
    tmp_path: Path,
    case: ModulePackageContractCase,
    invocation_count: int,
) -> None:
    case = replace(
        case,
        environment_values={
            **case.environment_values,
            "invocation_count": invocation_count,
        },
    )
    result = execute_module_package_case(FIXTURE_PACKAGE, case, work_root=tmp_path)
    assert result.projection.status == "succeeded"
    calls = [
        fact.payload
        for fact in result.node_events
        if isinstance(fact.payload, EngineInvocationStarted)
    ]
    terminals = [
        fact.payload
        for fact in result.node_events
        if isinstance(fact.payload, EngineInvocationTerminal)
    ]
    assert len(calls) == invocation_count
    assert {call.invocation_id for call in calls} == {
        terminal.invocation_id for terminal in terminals
    }
    upstream_count = 1 if case.workflow_nodes else 0
    assert (
        sum(
            isinstance(fact.payload, EngineInvocationStarted)
            for fact in result.run_events
        )
        == invocation_count + upstream_count
    )
    # An owner expecting a target call must fail even when the upstream called an engine.
    if invocation_count == 0 and upstream_count:
        with pytest.raises(AssertionError):
            assert len(calls) == 1


def _forget_packages(root_name: str) -> None:
    for name in tuple(sys.modules):
        if name == root_name or name.startswith(f"{root_name}."):
            sys.modules.pop(name)
    importlib.invalidate_caches()


@pytest.mark.parametrize(
    ("case", "text", "has_scores"),
    ((SOURCE_EXECUTION_CASE, "SOURCE", False), (EXECUTION_CASE, "ECHOECHO", True)),
    ids=("source", "scorer"),
)
def test_contract_test_kit_returns_values_after_releasing_storage(
    tmp_path: Path,
    case: ModulePackageContractCase,
    text: str,
    has_scores: bool,
) -> None:
    result = execute_module_package_case(FIXTURE_PACKAGE, case, work_root=tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert result.outputs["text"] == (text,)
    (artifact,) = result.publication.artifacts
    assert artifact.output_port == "artifact"
    assert result.artifacts == {artifact.artifact_reference: text.encode()}
    (candidates,) = result.outputs["candidates"]
    assert isinstance(candidates, CandidateCollection)
    assert len(candidates.items) == 1
    assert candidates.items[0].candidate_id.startswith("candidate-")
    assert candidates.items[0].data == ProteinSequence("M")
    if has_scores:
        (scores,) = result.outputs["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 1
        assert scores.entries[0].candidate_id == candidates.items[0].candidate_id
    assert result.publication.node_id == "contract-test-node"
    assert result.publication.result_identity.startswith("sha256:")
    assert all(
        output.producer_run_id == result.projection.run_id
        for output in result.publication.outputs
    )
    assert result.projection.workflow_commit_id
    published = json.dumps(result.public_evidence, sort_keys=True)
    for fragment in (
        "contract-test-secret-must-not-publish",
        "/private/contract-test-runtime",
        str(tmp_path),
    ):
        assert fragment not in published


@pytest.mark.parametrize(
    "case", (PORT_CASE, ARTIFACT_PORT_CASE), ids=lambda case: case.type_id
)
def test_port_conformance_is_independent_of_workflow_execution(
    case: ModulePackagePortCase,
) -> None:
    verify_module_package_port(FIXTURE_PACKAGE, case)


def test_cases_and_fixtures_are_not_part_of_production_registration() -> None:
    registration = FIXTURE_PACKAGE

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
    production = build_frozen_catalog(module_registrations())
    assert not any(
        contract.contract_id.startswith("contract_test.synthetic")
        for contract in production.contracts
    )


def test_source_and_scorer_publish_distinct_exact_contracts() -> None:
    catalog = build_frozen_catalog((FIXTURE_PACKAGE,))
    source_node = catalog.require_contract(
        "node_type",
        SOURCE_EXECUTION_CASE.node_type_id)
    scorer_node = catalog.require_contract(
        "node_type",
        EXECUTION_CASE.node_type_id)
    source_binding = catalog.require_contract(
        "binding",
        SOURCE_EXECUTION_CASE.binding_id)
    scorer_binding = catalog.require_contract(
        "binding",
        EXECUTION_CASE.binding_id)

    assert source_node.descriptor["inputs"] == ()
    assert scorer_node.descriptor["inputs"] == (
        {
            "name": "candidate_input",
            "port_type": catalog.require_contract(
                "port_type",
                "candidate.collection").reference(),
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
        "contract_test.synthetic_echo.source") is None


def test_source_public_journey_compiles_executes_replays_and_retrieves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=build_frozen_catalog((FIXTURE_PACKAGE,)),
        v2_environment_configuration={
            case.binding_id: dict(case.environment_values)
            for case in (SOURCE_EXECUTION_CASE, EXECUTION_CASE)
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
        assert catalog.json()["contracts"]
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
                    "binding_id": SOURCE_EXECUTION_CASE.binding_id,
                    "node_parameters": {"message": "SOURCE"},
                    "binding_parameters": {"repeat_count": 1},
                },
                {
                    "node_id": "synthetic-echo",
                    "node_type_id": EXECUTION_CASE.node_type_id,
                    "binding_id": EXECUTION_CASE.binding_id,
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
            ]}
        committed = public_request(
            "commit_project_workflow",
            {
                "project_id": project_id,
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
        text_output = next(
            output
            for output in payload["outputs"]
            if output["node_id"] == "synthetic-echo"
            and output["output_port"] == "text"
        )
        assert PublicRunClient(client).typed_output_values(
            project_id, run_id, text_output
        ) == ["ECHOECHO"]
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
        ModulePackageConformanceError, match="execution did not succeed"
    ):
        execute_module_package_case(
            FALSE_READINESS_PACKAGE, EXECUTION_CASE, work_root=tmp_path
        )


def test_contract_test_kit_rejects_an_invalid_package_codec(
    tmp_path: Path,
) -> None:
    registration = FIXTURE_PACKAGE
    port_type = registration.port_types[0]
    invalid_port_type = PortTypeDefinition(
        type_id=port_type.type_id,
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
        verify_module_package_port(
            replace(
                registration,
                port_types=(
                    invalid_port_type,
                    registration.port_types[1],
                ),
            ),
            PORT_CASE,
        )


def test_contract_test_kit_rejects_incomplete_observation_provenance(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ModulePackageConformanceError, match="execution did not succeed"
    ):
        execute_module_package_case(
            INCOMPLETE_PROVENANCE_PACKAGE, EXECUTION_CASE, work_root=tmp_path
        )


def test_malformed_definition_fails_before_catalog_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_name = "negative_zero_core_packages"
    source = FIXTURE_ROOT
    destination = tmp_path / root_name
    shutil.copytree(source, destination)
    (
        destination
        / "synthetic_echo"
        / "definitions"
        / "echo.yaml"
    ).write_text("schema_version: [", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        registration = importlib.import_module(
            f"{root_name}.synthetic_echo.package"
        ).MODULE_PACKAGE
        with pytest.raises(CatalogBuildError, match="malformed YAML"):
            build_frozen_catalog((registration,))
    finally:
        _forget_packages(root_name)


def test_eager_optional_dependency_import_propagates_programmer_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_name = "eager_zero_core_packages"
    source = FIXTURE_ROOT
    destination = tmp_path / root_name
    shutil.copytree(source, destination)
    package_path = destination / "synthetic_echo" / "package.py"
    package_source = package_path.read_text(encoding="utf-8")
    package_path.write_text(
        package_source.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n"
            "import synthetic_optional_provider_that_is_not_installed\n",
            1,
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"{root_name}.synthetic_echo.package")
    finally:
        _forget_packages(root_name)
