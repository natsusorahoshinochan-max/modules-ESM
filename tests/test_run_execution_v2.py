"""Public-seam contracts for readiness-gated v2 direct execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import stat
from typing import Any

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core import (
    BehaviorReference,
    CatalogContract,
    FrozenCatalog,
    LazyImplementationFactory,
    PortTypeDefinition,
    PortValueError,
    ReadinessResult,
    ReadinessDeclaration,
    ReusableReadinessProof,
    builtin_frozen_catalog,
)
from core.server import create_app
import core.run_execution_v2 as run_execution_v2
from protein_workbench_public import validate_response, validate_schema


def _contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict[str, Any],
) -> CatalogContract:
    return CatalogContract(
        contract_kind=contract_kind,
        contract_id=contract_id,
        contract_version="2.0.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            "contract_version": "2.0.0",
            **descriptor,
        },
    )


def _direct_catalog(
    calls: list[str],
    *,
    binding_ids: tuple[str, ...] = ("test.direct.local",),
    failing_binding_id: str | None = None,
    readiness_prerequisites: dict[str, Any] | None = None,
    readiness_checks: dict[str, Any] | None = None,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text", "2.0.0")
    method = _contract(
        "method",
        "test.direct.method",
        {
            "algorithm_identity": {"name": "deterministic-text"},
            "model_identity": {"kind": "none"},
            "checkpoint_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "source_identity": {"kind": "contract-test"},
            "scale_contract": {"kind": "identity"},
        },
    )
    node_type = _contract(
        "node_type",
        "test.direct",
        {
            "title": "Deterministic direct test Node",
            "summary": "Returns one canonical text value.",
            "category": "contract_test",
            "inputs": [],
            "outputs": [
                {
                    "name": "text",
                    "port_type": text.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Deterministic canonical text",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    bindings: list[CatalogContract] = []
    factories = {}
    readiness_declarations = {}
    for binding_id in binding_ids:
        binding_factory_behavior = BehaviorReference(
            f"{binding_id}/factory",
            "2.0.0",
            {"route": "direct"},
        )
        binding_readiness_behavior = BehaviorReference(
            f"{binding_id}/readiness",
            "2.0.0",
            {"observation": "per-run"},
        )
        binding = _contract(
            "binding",
            binding_id,
            {
                "node_type": node_type.reference(),
                "method": method.reference(),
                "binding_parameters": {},
                "execution_route": "direct",
                "route_behavior": binding_factory_behavior.descriptor(),
                "availability_declaration": {
                    "behavior": {
                        "behavior_id": f"{binding_id}/availability",
                        "behavior_version": "2.0.0",
                        "parameters": {},
                    },
                    "prerequisites": {},
                },
                "readiness_declaration": {
                    "behavior": binding_readiness_behavior.descriptor(),
                    "prerequisites": (
                        readiness_prerequisites
                        if readiness_prerequisites is not None
                        else {"credential": "required"}
                    ),
                },
                "deterministic": True,
                "cacheable": False,
                "implementation_identity": {
                    "name": binding_id,
                    "factory": binding_factory_behavior.descriptor(),
                },
                "produced_observations": [],
            },
        )
        bindings.append(binding)

        class DirectImplementation:
            def __init__(self, exact_binding_id: str) -> None:
                self._binding_id = exact_binding_id

            def execute(
                self,
                *,
                inputs: dict[str, Any],
                node_parameters: dict[str, Any],
                binding_parameters: dict[str, Any],
            ) -> dict[str, Any]:
                assert inputs == {}
                assert node_parameters == {}
                assert binding_parameters == {}
                calls.append(f"execute:{self._binding_id}")
                return {"text": "READY"}

        def make_readiness(exact_binding_id: str):
            def readiness(environment: dict[str, Any]) -> bool:
                if (
                    readiness_checks is not None
                    and exact_binding_id in readiness_checks
                ):
                    return readiness_checks[exact_binding_id](environment)
                assert environment["credential"] == "credential-value"
                calls.append(f"readiness:{exact_binding_id}")
                return exact_binding_id != failing_binding_id

            return readiness

        def make_factory(exact_binding_id: str):
            def factory(**kwargs: Any) -> DirectImplementation:
                assert kwargs["environment_configuration"]["credential"] == (
                    "credential-value"
                )
                assert kwargs["execution_plan"].workflow_id
                assert kwargs["frozen_catalog"] is not None
                assert kwargs["run_resources"].project_id
                calls.append(f"factory:{exact_binding_id}")
                return DirectImplementation(exact_binding_id)

            return factory

        factories[(binding_id, "2.0.0")] = LazyImplementationFactory(
            behavior=binding_factory_behavior,
            build=make_factory(binding_id),
        )
        readiness_declarations[(binding_id, "2.0.0")] = ReadinessDeclaration(
            behavior=binding_readiness_behavior,
            prerequisites=(
                readiness_prerequisites
                if readiness_prerequisites is not None
                else {"credential": "required"}
            ),
            check=make_readiness(binding_id),
        )

    observed_at = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    return FrozenCatalog(
        builtin.port_types,
        contracts=(method, node_type, *bindings),
        availability=tuple(
            {
                "binding": binding.reference(),
                "observed_at": observed_at.isoformat(),
                "available": True,
            }
            for binding in bindings
        ),
        availability_observed_at=observed_at,
        factories=factories,
        readiness_declarations=readiness_declarations,
    )


def _compile_one_node(client: TestClient) -> tuple[str, dict[str, Any]]:
    project = client.post("/api/projects", json={"name": "v2 direct"}).json()
    project_id = project["id"]
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "direct",
                "node_type_id": "test.direct",
                "node_type_version": "2.0.0",
                "binding_id": "test.direct.local",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "contract_lock": [],
    }
    saved = client.put(
        f"/api/v2/projects/{project_id}/workflow",
        json={"expected_workflow_revision": 0, "workflow": workflow},
    )
    assert saved.status_code == 200
    relocked = client.post(
        f"/api/v2/projects/{project_id}/workflow:relock",
        json={"workflow_revision": 1},
    )
    assert relocked.status_code == 200
    compiled = client.post(
        f"/api/v2/projects/{project_id}/workflow:compile",
        json={
            "workflow_revision": 2,
            "workflow": relocked.json()["workflow"],
        },
    )
    assert compiled.status_code == 200
    return project_id, compiled.json()


def _compile_independent_nodes(
    client: TestClient,
    binding_ids: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    project = client.post("/api/projects", json={"name": "v2 readiness"}).json()
    project_id = project["id"]
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": f"direct-{index}",
                "node_type_id": "test.direct",
                "node_type_version": "2.0.0",
                "binding_id": binding_id,
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
            for index, binding_id in enumerate(binding_ids)
        ],
        "edges": [],
        "contract_lock": [],
    }
    assert client.put(
        f"/api/v2/projects/{project_id}/workflow",
        json={"expected_workflow_revision": 0, "workflow": workflow},
    ).status_code == 200
    relocked = client.post(
        f"/api/v2/projects/{project_id}/workflow:relock",
        json={"workflow_revision": 1},
    )
    compiled = client.post(
        f"/api/v2/projects/{project_id}/workflow:compile",
        json={
            "workflow_revision": 2,
            "workflow": relocked.json()["workflow"],
        },
    )
    assert compiled.status_code == 200
    return project_id, compiled.json()


def _pipeline_catalog(
    calls: list[str],
    *,
    invalid_source_output: bool = False,
) -> FrozenCatalog:
    def validate_text(value: Any) -> None:
        calls.append(f"validate:{value!r}")
        if type(value) is not str:
            raise PortValueError("canonical text requires a string")

    canonical_text = PortTypeDefinition(
        type_id="test.canonical_text",
        version="2.0.0",
        validator=BehaviorReference(
            "test.canonical_text/validate",
            "2.0.0",
            {"accepted_value_kind": "text"},
        ),
        codec=BehaviorReference(
            "test.canonical_text/codec",
            "2.0.0",
            {"normalization": "strip-and-lowercase"},
        ),
        content_identity=BehaviorReference(
            "test.canonical_text/content",
            "2.0.0",
            {"digest": "SHA-256"},
        ),
        runtime_validator=validate_text,
        runtime_to_wire=lambda value: value.strip().lower(),
        runtime_from_wire=lambda value: value,
    )
    method = _contract(
        "method",
        "test.pipeline.method",
        {
            "algorithm_identity": {"name": "canonical-pipeline"},
            "model_identity": {"kind": "none"},
            "checkpoint_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "source_identity": {"kind": "contract-test"},
            "scale_contract": {"kind": "identity"},
        },
    )
    source = _contract(
        "node_type",
        "test.pipeline.source",
        {
            "title": "Canonical source",
            "summary": "Produces canonical text.",
            "category": "contract_test",
            "inputs": [],
            "outputs": [
                {
                    "name": "text",
                    "port_type": canonical_text.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Canonical source text",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    sink = _contract(
        "node_type",
        "test.pipeline.sink",
        {
            "title": "Canonical sink",
            "summary": "Consumes canonical text.",
            "category": "contract_test",
            "inputs": [
                {
                    "name": "text",
                    "port_type": canonical_text.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Canonical input text",
                }
            ],
            "outputs": [
                {
                    "name": "text",
                    "port_type": canonical_text.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Canonical sink text",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    contracts: list[CatalogContract] = [method, source, sink]
    factories = {}
    readiness = {}
    availability = []

    class SourceImplementation:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["inputs"] == {}
            return {"text": 17 if invalid_source_output else " READY "}

    class SinkImplementation:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(f"sink-input:{kwargs['inputs']['text']}")
            return {"text": kwargs["inputs"]["text"]}

    for binding_id, node_type, implementation in (
        ("test.pipeline.source.direct", source, SourceImplementation),
        ("test.pipeline.sink.direct", sink, SinkImplementation),
    ):
        factory_behavior = BehaviorReference(
            f"{binding_id}/factory",
            "2.0.0",
            {},
        )
        readiness_behavior = BehaviorReference(
            f"{binding_id}/readiness",
            "2.0.0",
            {},
        )
        binding = _contract(
            "binding",
            binding_id,
            {
                "node_type": node_type.reference(),
                "method": method.reference(),
                "binding_parameters": {},
                "execution_route": "direct",
                "route_behavior": factory_behavior.descriptor(),
                "availability_declaration": {
                    "behavior": {
                        "behavior_id": f"{binding_id}/availability",
                        "behavior_version": "2.0.0",
                        "parameters": {},
                    },
                    "prerequisites": {},
                },
                "readiness_declaration": {
                    "behavior": readiness_behavior.descriptor(),
                    "prerequisites": {},
                },
                "deterministic": True,
                "cacheable": False,
                "implementation_identity": {
                    "name": binding_id,
                    "factory": factory_behavior.descriptor(),
                },
                "produced_observations": [],
            },
        )
        contracts.append(binding)
        factories[(binding_id, "2.0.0")] = LazyImplementationFactory(
            behavior=factory_behavior,
            build=lambda implementation=implementation, **kwargs: (
                implementation()
            ),
        )
        readiness[(binding_id, "2.0.0")] = ReadinessDeclaration(
            behavior=readiness_behavior,
            prerequisites={},
            check=lambda environment: True,
        )
        availability.append(
            {
                "binding": binding.reference(),
                "observed_at": "2026-07-29T08:00:00+00:00",
                "available": True,
            }
        )
    return FrozenCatalog(
        (canonical_text,),
        contracts=tuple(contracts),
        availability=tuple(availability),
        availability_observed_at=datetime(
            2026,
            7,
            29,
            8,
            0,
            tzinfo=timezone.utc,
        ),
        factories=factories,
        readiness_declarations=readiness,
    )


def _artifact_catalog(calls: list[str]) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    file_path = builtin.require_port_type("file.path", "2.0.0")
    method = _contract(
        "method",
        "test.artifact.method",
        {
            "algorithm_identity": {"name": "deterministic-artifact"},
            "model_identity": {"kind": "none"},
            "checkpoint_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "source_identity": {"kind": "contract-test"},
            "scale_contract": {"kind": "identity"},
        },
    )
    node = _contract(
        "node_type",
        "test.artifact",
        {
            "title": "Deterministic artifact",
            "summary": "Publishes one deterministic PDB artifact.",
            "category": "contract_test",
            "inputs": [],
            "outputs": [
                {
                    "name": "structure",
                    "port_type": file_path.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Published PDB structure",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    factory_behavior = BehaviorReference(
        "test.artifact/factory",
        "2.0.0",
        {},
    )
    readiness_behavior = BehaviorReference(
        "test.artifact/readiness",
        "2.0.0",
        {},
    )
    binding = _contract(
        "binding",
        "test.artifact.direct",
        {
            "node_type": node.reference(),
            "method": method.reference(),
            "binding_parameters": {},
            "execution_route": "direct",
            "route_behavior": factory_behavior.descriptor(),
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "test.artifact/availability",
                    "behavior_version": "2.0.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": readiness_behavior.descriptor(),
                "prerequisites": {},
            },
            "deterministic": True,
            "cacheable": False,
            "implementation_identity": {
                "name": "test.artifact.direct",
                "factory": factory_behavior.descriptor(),
            },
            "produced_observations": [],
        },
    )

    class ArtifactImplementation:
        def __init__(self, resources) -> None:
            self._resources = resources

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["inputs"] == {}
            with self._resources.temporary_directory(
                prefix="artifact-engine"
            ) as workspace:
                calls.append(f"workspace:{workspace.name.startswith('artifact-engine-')}")
            reference = self._resources.write_artifact(
                "models/result.pdb",
                b"MODEL        1\nEND\n",
            )
            return {"structure": reference}

    def factory(**kwargs: Any) -> ArtifactImplementation:
        return ArtifactImplementation(kwargs["run_resources"])

    observed_at = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    return FrozenCatalog(
        builtin.port_types,
        contracts=(method, node, binding),
        availability=(
            {
                "binding": binding.reference(),
                "observed_at": observed_at.isoformat(),
                "available": True,
            },
        ),
        availability_observed_at=observed_at,
        factories={
            ("test.artifact.direct", "2.0.0"): LazyImplementationFactory(
                behavior=factory_behavior,
                build=factory,
            )
        },
        readiness_declarations={
            ("test.artifact.direct", "2.0.0"): ReadinessDeclaration(
                behavior=readiness_behavior,
                prerequisites={},
                check=lambda environment: True,
            )
        },
    )


def _compile_artifact_node(
    client: TestClient,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/projects",
        json={"name": "v2 artifact"},
    ).json()["id"]
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "artifact",
                "node_type_id": "test.artifact",
                "node_type_version": "2.0.0",
                "binding_id": "test.artifact.direct",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "contract_lock": [],
    }
    assert client.put(
        f"/api/v2/projects/{project_id}/workflow",
        json={"expected_workflow_revision": 0, "workflow": workflow},
    ).status_code == 200
    relocked = client.post(
        f"/api/v2/projects/{project_id}/workflow:relock",
        json={"workflow_revision": 1},
    )
    compiled = client.post(
        f"/api/v2/projects/{project_id}/workflow:compile",
        json={
            "workflow_revision": 2,
            "workflow": relocked.json()["workflow"],
        },
    )
    assert compiled.status_code == 200
    return project_id, compiled.json()


def _compile_pipeline(client: TestClient) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/projects",
        json={"name": "v2 canonical boundary"},
    ).json()["id"]
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "source",
                "node_type_id": "test.pipeline.source",
                "node_type_version": "2.0.0",
                "binding_id": "test.pipeline.source.direct",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "sink",
                "node_type_id": "test.pipeline.sink",
                "node_type_version": "2.0.0",
                "binding_id": "test.pipeline.sink.direct",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
        ],
        "edges": [
            {
                "source_node_id": "source",
                "source_port": "text",
                "target_node_id": "sink",
                "target_port": "text",
            }
        ],
        "contract_lock": [],
    }
    assert client.put(
        f"/api/v2/projects/{project_id}/workflow",
        json={"expected_workflow_revision": 0, "workflow": workflow},
    ).status_code == 200
    relocked = client.post(
        f"/api/v2/projects/{project_id}/workflow:relock",
        json={"workflow_revision": 1},
    )
    compiled = client.post(
        f"/api/v2/projects/{project_id}/workflow:compile",
        json={
            "workflow_revision": 2,
            "workflow": relocked.json()["workflow"],
        },
    )
    assert compiled.status_code == 200
    return project_id, compiled.json()


def test_public_start_run_binds_the_exact_compile_before_direct_execution(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {
                    "credential": "credential-value",
                    "runtime_path": str(tmp_path / "private-runtime"),
                },
                "safe_fingerprint": "test-direct-config-v1",
                "invalidation_token": "test-direct-assets-v1",
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "request-1",
            },
        )

        assert started.status_code == 202
        receipt = started.json()
        validate_response("start_run", 202, receipt)
        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}"
        )
        assert projection.status_code == 200
        validate_response("run_projection", 200, projection.json())
        assert projection.json() == {
            "project_id": project_id,
            "run_id": receipt["run_id"],
            "workflow_revision": 2,
            "workflow_digest": compiled["workflow_digest"],
            "compile_id": compiled["compile_id"],
            "status": "succeeded",
            "terminal_sequence": projection.json()["terminal_sequence"],
            "ledger_cursor": projection.json()["ledger_cursor"],
            "node_dispositions": [
                {
                    "node_id": "direct",
                    "outcome": "succeeded",
                    "resolution": "executed",
                    "terminal_sequence": (
                        projection.json()["node_dispositions"][0][
                            "terminal_sequence"
                        ]
                    ),
                    "blocked_by": [],
                }
            ],
            "outputs": [
                {
                    "node_id": "direct",
                    "output_port": "text",
                    "port_type": (
                        _direct_catalog([]).require_port_type(
                            "text",
                            "2.0.0",
                        ).reference()
                    ),
                    "content_digest": (
                        _direct_catalog([]).require_port_type(
                            "text",
                            "2.0.0",
                        ).content_digest("READY")
                    ),
                    "values": ["READY"],
                }
            ],
            "artifact_index": [],
        }

    assert calls == [
        "readiness:test.direct.local",
        "factory:test.direct.local",
        "execute:test.direct.local",
    ]


def test_all_distinct_bindings_are_attested_before_any_factory_and_shared(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    bindings = ("test.direct.local", "test.other.local")
    environment = {
        (binding_id, "2.0.0"): {
            "values": {"credential": "credential-value"},
            "safe_fingerprint": f"{binding_id}-config-v1",
            "invalidation_token": f"{binding_id}-assets-v1",
        }
        for binding_id in bindings
    }
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            binding_ids=bindings,
        ),
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_independent_nodes(
            client,
            (
                "test.direct.local",
                "test.direct.local",
                "test.other.local",
            ),
        )
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "distinct-binding-request",
            },
        )

    assert response.status_code == 202
    assert calls[:2] == [
        "readiness:test.direct.local",
        "readiness:test.other.local",
    ]
    assert calls.count("readiness:test.direct.local") == 1
    assert calls[2:] == [
        "factory:test.direct.local",
        "execute:test.direct.local",
        "factory:test.direct.local",
        "execute:test.direct.local",
        "factory:test.other.local",
        "execute:test.other.local",
    ]


def test_failed_readiness_rejects_before_factory_and_redacts_environment(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    bindings = ("test.direct.local", "test.other.local")
    secret = "sk-never-persist-this-value"
    private_path = str(tmp_path / "private-runtime")
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            binding_ids=bindings,
            failing_binding_id="test.other.local",
        ),
        v2_environment_configuration={
            (binding_id, "2.0.0"): {
                "values": {
                    "credential": "credential-value",
                    "api_key": secret,
                    "runtime_path": private_path,
                },
                "safe_fingerprint": f"{binding_id}-config-v1",
                "invalidation_token": f"{binding_id}-assets-v1",
            }
            for binding_id in bindings
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_independent_nodes(client, bindings)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "failed-readiness-request",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "readiness_rejected"
    assert calls == [
        "readiness:test.direct.local",
        "readiness:test.other.local",
    ]
    durable_evidence = b"".join(
        path.read_bytes()
        for path in (tmp_path / "runs").rglob("*.json")
    )
    assert secret.encode() not in durable_evidence
    assert private_path.encode() not in durable_evidence
    assert secret not in response.text
    assert private_path not in response.text


def test_volatile_readiness_is_reobserved_and_rejects_stale_green(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    credential_state = {"present": True}

    def readiness(environment) -> bool:
        calls.append("readiness")
        return environment["credential_state"]["present"]

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            readiness_checks={"test.direct.local": readiness},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {
                    "credential": "credential-value",
                    "credential_state": credential_state,
                },
                "safe_fingerprint": "volatile-config-v1",
                "invalidation_token": "volatile-assets-v1",
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        first = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "volatile-first",
            },
        )
        credential_state["present"] = False
        second = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "volatile-second",
            },
        )

    assert first.status_code == 202
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "readiness_rejected"
    assert calls.count("readiness") == 2
    assert calls.count("factory:test.direct.local") == 1


def test_invalid_public_readiness_metadata_fails_before_factory(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def readiness(environment) -> ReadinessResult:
        assert environment["credential"] == "credential-value"
        return ReadinessResult(True, proof_source="contains whitespace")

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            readiness_checks={"test.direct.local": readiness},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "invalid-readiness-metadata",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "readiness_rejected"
    assert not any(call.startswith("factory:") for call in calls)


def test_reusable_readiness_proof_requires_identity_scope_age_fingerprint_and_invalidation(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[bool] = []
    observed_at = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
    current_time = {"value": observed_at}
    configuration = {
        "fingerprint": "configuration-v1",
        "invalidation": "assets-v1",
    }
    monkeypatch.setattr(
        run_execution_v2,
        "_utc_now",
        lambda: current_time["value"],
    )

    def readiness(environment) -> ReadinessResult:
        calls.append(environment.reusable_proof is not None)
        if environment.reusable_proof is not None:
            return ReadinessResult(True, proof_source="reused-proof")
        return ReadinessResult(
            True,
            proof_source="fresh-proof",
            reusable_proof=ReusableReadinessProof(
                proof_identity="immutable-model-proof-v1",
                proof_scope="test.direct.local@2.0.0",
                observed_at=current_time["value"],
                maximum_age_seconds=60,
                configuration_fingerprint=configuration["fingerprint"],
                invalidation_token=configuration["invalidation"],
            ),
        )

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            readiness_prerequisites={
                "reusable_proof": {
                    "identity": "immutable-model-proof-v1",
                    "scope": "test.direct.local@2.0.0",
                    "maximum_age_seconds": 60,
                }
            },
            readiness_checks={"test.direct.local": readiness},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
                "safe_fingerprint": lambda: configuration["fingerprint"],
                "invalidation_token": lambda: configuration["invalidation"],
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)

        def start(request_id: str):
            return client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": 2,
                    "compile_id": compiled["compile_id"],
                    "client_request_id": request_id,
                },
            )

        assert start("proof-first").status_code == 202
        current_time["value"] += timedelta(seconds=10)
        assert start("proof-reused").status_code == 202
        configuration["fingerprint"] = "configuration-v2"
        assert start("proof-fingerprint-changed").status_code == 202
        configuration["invalidation"] = "assets-v2"
        assert start("proof-invalidated").status_code == 202
        current_time["value"] += timedelta(seconds=61)
        assert start("proof-expired").status_code == 202

    assert calls == [False, True, False, False, False]


def test_connected_ports_publish_and_consume_only_canonical_validated_values(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(frozen_catalog_override=_pipeline_catalog(calls))

    with TestClient(app) as client:
        project_id, compiled = _compile_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "canonical-port-boundary",
            },
        )
        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{started.json()['run_id']}"
        )

    assert started.status_code == 202
    assert projection.status_code == 200
    assert [output["values"] for output in projection.json()["outputs"]] == [
        ["ready"],
        ["ready"],
    ]
    assert "sink-input:ready" in calls
    assert "sink-input: READY " not in calls


def test_invalid_output_never_publishes_success_or_a_public_result(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_pipeline_catalog(
            calls,
            invalid_source_output=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "invalid-output",
            },
        )

    assert started.status_code == 500
    assert started.json()["error"]["code"] == "internal_error"
    durable_facts = [
        json.loads(path.read_text())
        for path in sorted((tmp_path / "runs").rglob("*.json"))
    ]
    assert not any(
        fact["fact_type"] == "outputs_published"
        or (
            fact["fact_type"] == "node_disposition"
            and fact["payload"]["outcome"] == "succeeded"
        )
        for fact in durable_facts
    )
    invocation_terminals = [
        fact
        for fact in durable_facts
        if fact["fact_type"] == "engine_invocation_terminal"
    ]
    assert len(invocation_terminals) == 1
    assert invocation_terminals[0]["payload"]["status"] == "succeeded"
    assert [
        fact["payload"]["status"]
        for fact in durable_facts
        if fact["fact_type"]
        in {
            "operation_attempt_terminal",
            "node_attempt_terminal",
            "run_terminal",
        }
    ] == ["failed", "failed", "failed"]


def test_success_ledger_projects_validated_events_and_opaque_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    app = create_app(frozen_catalog_override=_artifact_catalog(calls))

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "artifact-success",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        )
        assert projection.status_code == 200
        payload = projection.json()
        assert payload["status"] == "succeeded"
        assert payload["outputs"] == []
        assert len(payload["artifact_index"]) == 1
        artifact = payload["artifact_index"][0]
        assert artifact["artifact_kind"] == "standalone"
        assert artifact["node_id"] == "artifact"
        assert artifact["output_port"] == "structure"
        assert artifact["artifact_reference"] != "models/result.pdb"
        assert "/" not in artifact["artifact_reference"]
        assert artifact["content_digest"] == (
            "sha256:"
            + hashlib.sha256(b"MODEL        1\nEND\n").hexdigest()
        )

        downloaded = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
            f"{artifact['artifact_reference']}"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"MODEL        1\nEND\n"
        assert downloaded.headers["digest"] == artifact["content_digest"]
        assert downloaded.headers["content-type"] == "chemical/x-pdb"
        assert downloaded.headers["content-length"] == str(artifact["size"])

        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            messages: list[dict[str, Any]] = []
            try:
                while True:
                    messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000

        assert messages[0]["event"]["type"] == "replay_started"
        assert messages[-1]["event"]["type"] == "replay_complete"
        projected_events = messages[1:-1]
        for message in messages:
            validate_schema("#/$defs/RunEventEnvelope", message)
        event_types = [message["event"]["type"] for message in projected_events]
        assert event_types == [
            "readiness_attested",
            "run_admitted",
            "run_started",
            "node_attempt_started",
            "operation_attempt_started",
            "engine_invocation_started",
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
            "node_disposition",
            "run_terminal",
        ]
        assert [
            message["sequence"] for message in projected_events
        ] == sorted(message["sequence"] for message in projected_events)
        assert payload["terminal_sequence"] == projected_events[-1]["sequence"]
        assert payload["ledger_cursor"] == projected_events[-1]["cursor"]

    fact_paths = sorted(run_root.rglob("*.json"))
    facts = [json.loads(path.read_text()) for path in fact_paths]
    assert [fact["sequence"] for fact in facts] == list(
        range(1, len(facts) + 1)
    )
    assert {
        "availability_bound",
        "readiness_attested",
        "engine_invocation_started",
    } <= {fact["fact_type"] for fact in facts}
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in fact_paths)
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o700
        for path in {
            path.parent
            for path in fact_paths
        }
    )
    assert calls == ["workspace:True"]
    assert not any((run_root / project_id / run_id / "temp").rglob("*"))


def test_artifact_retrieval_rejects_cross_scope_tamper_and_symlink(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    app = create_app(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        other_project_id = client.post(
            "/api/projects",
            json={"name": "other scope"},
        ).json()["id"]
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "artifact-scope",
            },
        ).json()
        run_id = started["run_id"]
        artifact = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        ).json()["artifact_index"][0]
        reference = artifact["artifact_reference"]

        cross_scope = client.get(
            f"/api/v2/projects/{other_project_id}/runs/{run_id}/artifacts/"
            f"{reference}"
        )
        assert cross_scope.status_code == 404
        assert cross_scope.json()["error"]["code"] == (
            "cross_scope_access_denied"
        )

        managed = output_root / project_id / run_id / "published" / reference
        managed.write_bytes(b"TAMPERED")
        managed.chmod(0o600)
        tampered = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
            f"{reference}"
        )
        assert tampered.status_code == 409
        assert tampered.json()["error"]["code"] == (
            "artifact_integrity_mismatch"
        )

        managed.unlink()
        outside = tmp_path / "outside.pdb"
        outside.write_bytes(b"MODEL        1\nEND\n")
        managed.symlink_to(outside)
        symlinked = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
            f"{reference}"
        )
        assert symlinked.status_code == 409
        assert symlinked.json()["error"]["code"] == (
            "artifact_integrity_mismatch"
        )


def test_symlinked_run_workspace_fails_before_readiness_without_outside_write(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    run_root = tmp_path / "runs"
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
                "safe_fingerprint": "safe-config",
                "invalidation_token": "safe-assets",
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        run_root.mkdir(mode=0o700)
        (run_root / project_id).symlink_to(outside, target_is_directory=True)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "poisoned-run-workspace",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "evidence_unavailable"
    assert calls == []
    assert list(outside.iterdir()) == []
