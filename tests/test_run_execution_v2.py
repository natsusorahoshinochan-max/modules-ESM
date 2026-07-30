"""Public-seam contracts for readiness-gated v2 direct execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import stat
import threading
import time
from typing import Any, Mapping

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core import (
    ArtifactPayload,
    BehaviorReference,
    CatalogContract,
    EffectiveRandomnessResolver,
    ExecutionTermination,
    FrozenCatalog,
    LazyImplementationFactory,
    PortTypeDefinition,
    PortValueError,
    PreScheduleTermination,
    ReadinessResult,
    ReadinessDeclaration,
    ResultReplayHit,
    ResultReplaySource,
    ReusableReadinessProof,
    builtin_frozen_catalog,
)
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from core.server import create_app
import core.run_execution_v2 as run_execution_v2
from protein_workbench_public import (
    validate_error,
    validate_response,
    validate_schema,
)
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal


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
    cacheable: bool = False,
    invocation_count: int = 1,
    execution_gate: tuple[threading.Event, threading.Event] | None = None,
    execution_action: Any | None = None,
    factory_action: Any | None = None,
    execution_output: Any = "READY",
    implementation_variant: str = "default",
    implementation_label: str | None = None,
    deterministic: bool = True,
    source_identity: Mapping[str, Any] | None = None,
    node_parameter_declarations: Mapping[str, Any] | None = None,
    node_title: str = "Deterministic direct test Node",
    effective_randomness_parameters: tuple[str, ...] = (),
    effective_randomness_resolver: EffectiveRandomnessResolver | None = None,
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
            "source_identity": (
                dict(source_identity)
                if source_identity is not None
                else {"kind": "contract-test"}
            ),
            "scale_contract": {"kind": "identity"},
        },
    )
    node_type = _contract(
        "node_type",
        "test.direct",
        {
            "title": node_title,
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
            "node_parameters": dict(node_parameter_declarations or {}),
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
                "deterministic": deterministic,
                "cacheable": cacheable,
                "implementation_identity": {
                    "name": binding_id,
                    "variant": implementation_variant,
                    **(
                        {"label": implementation_label}
                        if implementation_label is not None
                        else {}
                    ),
                    "factory": binding_factory_behavior.descriptor(),
                    **(
                        {
                            "effective_randomness_resolver": (
                                effective_randomness_resolver.behavior.descriptor()
                            )
                        }
                        if effective_randomness_resolver is not None
                        else {}
                    ),
                },
                "produced_observations": [],
                **(
                    {
                        "effective_randomness_parameters": list(
                            effective_randomness_parameters
                        ),
                    }
                    if effective_randomness_parameters
                    else {}
                ),
            },
        )
        bindings.append(binding)

        class DirectImplementation:
            def __init__(self, exact_binding_id: str, resources) -> None:
                self._binding_id = exact_binding_id
                self._resources = resources

            def execute(
                self,
                *,
                inputs: dict[str, Any],
                node_parameters: dict[str, Any],
                binding_parameters: dict[str, Any],
            ) -> dict[str, Any]:
                assert inputs == {}
                if node_parameter_declarations is None:
                    assert node_parameters == {}
                else:
                    calls.append(f"parameters:{dict(node_parameters)!r}")
                assert binding_parameters == {}
                if invocation_count == 0:
                    calls.append(f"execute:{self._binding_id}")
                else:
                    for index in range(invocation_count):
                        with self._resources.engine_invocation(
                            engine_role=(
                                "primary" if index == 0 else "secondary"
                            )
                        ):
                            if index == 0:
                                calls.append(f"execute:{self._binding_id}")
                                if execution_action is not None:
                                    execution_action(self._resources)
                                if execution_gate is not None:
                                    entered, release = execution_gate
                                    entered.set()
                                    if not release.wait(timeout=2):
                                        raise TimeoutError(
                                            "fixture execution gate timed out"
                                        )
                value = (
                    execution_output()
                    if callable(execution_output)
                    else execution_output
                )
                return {"text": value}

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
                assert isinstance(
                    kwargs["environment_configuration"]["credential"],
                    str,
                )
                assert kwargs["execution_plan"].workflow_id
                assert kwargs["frozen_catalog"] is not None
                assert kwargs["run_resources"].project_id
                calls.append(f"factory:{exact_binding_id}")
                if factory_action is not None:
                    factory_action(kwargs["run_resources"])
                return DirectImplementation(
                    exact_binding_id,
                    kwargs["run_resources"],
                )

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
        effective_randomness_resolvers=(
            {
                (binding_id, "2.0.0"): effective_randomness_resolver
                for binding_id in binding_ids
            }
            if effective_randomness_resolver is not None
            else {}
        ),
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
    failing_source_node_id: str | None = None,
    terminating_source_nodes: Mapping[str, str] | None = None,
    pre_schedule_source_nodes: Mapping[str, str] | None = None,
    optional_sink_input: bool = False,
    cacheable: bool = False,
    unresolved_port_identity: bool = False,
    execution_gates: (
        Mapping[str, tuple[threading.Event, threading.Event]] | None
    ) = None,
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
            {
                "normalization": "strip-and-lowercase",
                **(
                    {"identity_complete": False}
                    if unresolved_port_identity
                    else {}
                ),
            },
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
                    "required": not optional_sink_input,
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
        def __init__(self, node_id: str, resources) -> None:
            self._node_id = node_id
            self._resources = resources

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["inputs"] == {}
            with self._resources.engine_invocation():
                calls.append(f"execute:{self._node_id}")
                if (
                    execution_gates is not None
                    and self._node_id in execution_gates
                ):
                    entered, release = execution_gates[self._node_id]
                    entered.set()
                    if not release.wait(timeout=5):
                        raise TimeoutError(
                            "fixture execution gate timed out"
                        )
                if self._node_id == failing_source_node_id:
                    raise RuntimeError("sk-secret-branch-provider-failure")
                if (
                    terminating_source_nodes is not None
                    and self._node_id in terminating_source_nodes
                ):
                    raise ExecutionTermination(
                        terminating_source_nodes[self._node_id]
                    )
                return {"text": 17 if invalid_source_output else " READY "}

    class SinkImplementation:
        def __init__(self, resources) -> None:
            self._resources = resources

        def execute(self, **kwargs: Any) -> dict[str, Any]:
            with self._resources.engine_invocation():
                calls.append(f"sink-input:{kwargs['inputs'].get('text')}")
                return {"text": kwargs["inputs"].get("text", "OPTIONAL")}

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
                "cacheable": cacheable,
                "implementation_identity": {
                    "name": binding_id,
                    "factory": factory_behavior.descriptor(),
                },
                "produced_observations": [],
            },
        )
        contracts.append(binding)
        def build_implementation(
            *,
            implementation=implementation,
            **kwargs: Any,
        ) -> Any:
            if implementation is SourceImplementation:
                node_id = kwargs["run_resources"].node_id
                if (
                    pre_schedule_source_nodes is not None
                    and node_id in pre_schedule_source_nodes
                ):
                    raise PreScheduleTermination(
                        pre_schedule_source_nodes[node_id]
                    )
                return implementation(node_id, kwargs["run_resources"])
            return implementation(kwargs["run_resources"])

        factories[(binding_id, "2.0.0")] = LazyImplementationFactory(
            behavior=factory_behavior,
            build=build_implementation,
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


def _artifact_catalog(
    calls: list[str],
    *,
    artifact_kind: str | None = "standalone",
    collection: bool = False,
    artifact_payloads: tuple[bytes, ...] = (b"MODEL        1\nEND\n",),
    cacheable: bool = False,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    artifact_port_type = PROTEIN_IO_PACKAGE.port_types[0]
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
            "outputs": [{
                    "name": "structure",
                    "port_type": artifact_port_type.reference(),
                    "required": True,
                    "multiplicity": "many" if collection else "one",
                    "scientific_meaning": "Published PDB structure",
                    **(
                        {
                            "artifact_kind": artifact_kind,
                            "artifact_media_type": "chemical/x-pdb",
                        }
                        if artifact_kind is not None
                        else {}
                    ),
                }],
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
            "cacheable": cacheable,
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
            with self._resources.engine_invocation():
                pass
            with self._resources.temporary_directory(
                prefix="artifact-engine"
            ) as workspace:
                calls.append(f"workspace:{workspace.name.startswith('artifact-engine-')}")
            payload_values = [
                ArtifactPayload(
                    body=payload,
                    media_type="chemical/x-pdb",
                    filename=f"result-{index}.pdb",
                )
                for index, payload in enumerate(artifact_payloads)
            ]
            return {
                "structure": (
                    payload_values if collection else payload_values[0]
                )
            }

    def factory(**kwargs: Any) -> ArtifactImplementation:
        return ArtifactImplementation(kwargs["run_resources"])

    observed_at = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    return FrozenCatalog(
        (*builtin.port_types, artifact_port_type),
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


def _compile_branching_pipeline(
    client: TestClient,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/projects",
        json={"name": "v2 branch failure"},
    ).json()["id"]
    nodes = [
        {
            "node_id": node_id,
            "node_type_id": node_type_id,
            "node_type_version": "2.0.0",
            "binding_id": binding_id,
            "binding_version": "2.0.0",
            "node_parameters": {},
            "binding_parameters": {},
        }
        for node_id, node_type_id, binding_id in (
            (
                "failing",
                "test.pipeline.source",
                "test.pipeline.source.direct",
            ),
            (
                "independent",
                "test.pipeline.source",
                "test.pipeline.source.direct",
            ),
            (
                "blocked",
                "test.pipeline.sink",
                "test.pipeline.sink.direct",
            ),
            (
                "successful",
                "test.pipeline.sink",
                "test.pipeline.sink.direct",
            ),
        )
    ]
    workflow = {
        "schema_version": "2.0.0",
        "workflow_id": project_id,
        "nodes": nodes,
        "edges": [
            {
                "source_node_id": source,
                "source_port": "text",
                "target_node_id": target,
                "target_port": "text",
            }
            for source, target in (
                ("failing", "blocked"),
                ("independent", "successful"),
            )
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


@pytest.mark.deterministic_acceptance
def test_branch_failure_closes_every_disposition_and_unrelated_work_continues(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    run_root = tmp_path / "runs"
    secret = "sk-secret-branch-provider-failure"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_pipeline_catalog(
            calls,
            failing_source_node_id="failing",
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_branching_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "branch-failure",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        payload = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=run_id,
        )
        assert payload["status"] == "failed"
        assert [
            (
                item["node_id"],
                item["outcome"],
                item.get("resolution"),
                item["blocked_by"],
            )
            for item in payload["node_dispositions"]
        ] == [
            ("failing", "failed", None, []),
            ("independent", "succeeded", "executed", []),
            ("blocked", "blocked", None, ["failing"]),
            ("successful", "succeeded", "executed", []),
        ]
        assert [
            output["node_id"]
            for output in payload["outputs"]
        ] == ["independent", "successful"]

        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            messages: list[dict[str, Any]] = []
            try:
                while True:
                    messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000

    events = [
        message["event"]
        for message in messages
        if message["event"]["type"] not in {
            "replay_started",
            "replay_complete",
        }
    ]
    assert sum(event["type"] == "node_disposition" for event in events) == 4
    assert sum(event["type"] == "node_attempt_started" for event in events) == 3
    assert sum(
        event["type"] == "operation_attempt_started"
        for event in events
    ) == 3
    assert sum(
        event["type"] == "engine_invocation_started"
        for event in events
    ) == 3
    assert events[-1] == {"type": "run_terminal", "status": "failed"}
    failing_terminals = [
        event
        for event in events
        if event["type"] in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
        and event["status"] == "failed"
    ]
    assert len(failing_terminals) == 3
    assert all(
        event["error"]["message"] == "Node execution failed safely"
        and len(event["error"]["message"]) <= 2048
        for event in failing_terminals
    )
    retained = b"".join(path.read_bytes() for path in run_root.rglob("*.json"))
    assert secret.encode() not in retained
    assert secret not in json.dumps(messages)
    assert calls.count("execute:failing") == 1
    assert calls.count("execute:independent") == 1
    assert calls.count("sink-input:ready") == 1


def test_failed_optional_input_does_not_block_a_node(
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
            failing_source_node_id="failing",
            optional_sink_input=True,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_branching_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "optional-input-failure",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started.json()["run_id"],
        )

    assert [
        (item["node_id"], item["outcome"])
        for item in projection["node_dispositions"]
    ] == [
        ("failing", "failed"),
        ("independent", "succeeded"),
        ("blocked", "succeeded"),
        ("successful", "succeeded"),
    ]
    assert "sink-input:None" in calls
    assert projection["status"] == "failed"


@pytest.mark.parametrize(
    ("attempt_status", "disposition", "run_status"),
    (
        ("failed", "failed", "failed"),
        ("cancelled", "cancelled", "cancelled"),
        ("interrupted", "interrupted", "interrupted"),
        ("outcome_unknown", "interrupted", "interrupted"),
    ),
)
def test_started_engine_terminal_statuses_are_causally_closed(
    tmp_path,
    monkeypatch,
    attempt_status: str,
    disposition: str,
    run_status: str,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_pipeline_catalog(
            [],
            terminating_source_nodes={"source": attempt_status},
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": f"terminal-{attempt_status}",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=run_id,
        )
        events = app.state.run_execution_v2.public_events(project_id, run_id)

    assert projection["status"] == run_status
    assert [
        (item["node_id"], item["outcome"], item["blocked_by"])
        for item in projection["node_dispositions"]
    ] == [
        ("source", disposition, []),
        ("sink", "blocked", ["source"]),
    ]
    terminal_events = [
        event["event"]
        for event in events
        if event["event"]["type"] in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    ]
    assert [event["status"] for event in terminal_events] == [
        attempt_status,
        attempt_status,
        attempt_status,
    ]
    assert len(
        {
            (
                event.get("invocation_id")
                or event.get("operation_attempt_id")
                or event.get("node_attempt_id")
            )
            for event in terminal_events
        }
    ) == 3


@pytest.mark.parametrize("outcome", ("cancelled", "interrupted"))
def test_pre_schedule_termination_has_disposition_without_false_attempt(
    tmp_path,
    monkeypatch,
    outcome: str,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_pipeline_catalog(
            [],
            pre_schedule_source_nodes={"source": outcome},
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": f"pre-schedule-{outcome}",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=run_id,
        )
        events = app.state.run_execution_v2.public_events(project_id, run_id)

    assert projection["status"] == outcome
    assert [
        (item["node_id"], item["outcome"], item["blocked_by"])
        for item in projection["node_dispositions"]
    ] == [
        ("source", outcome, []),
        ("sink", "blocked", ["source"]),
    ]
    assert not any(
        event["event"]["type"]
        in {
            "node_attempt_started",
            "operation_attempt_started",
            "engine_invocation_started",
        }
        for event in events
    )


def test_cache_replay_closes_only_the_scheduled_node_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FixtureReplaySource(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            assert kwargs["project_id"]
            assert kwargs["node"].node_id == "direct"
            assert kwargs["inputs"] == {}
            calls.append("cache-lookup")
            return ResultReplayHit(
                {"text": "CACHED"},
                kwargs["result_identity"],
                "fixture-producer",
            )

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_result_replay_source=FixtureReplaySource(),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
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
                "client_request_id": "cache-replayed",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=run_id,
        )
        events = app.state.run_execution_v2.public_events(project_id, run_id)

    assert projection["node_dispositions"] == [
        {
            "node_id": "direct",
            "outcome": "succeeded",
            "resolution": "cache_replayed",
            "terminal_sequence": (
                projection["node_dispositions"][0]["terminal_sequence"]
            ),
            "blocked_by": [],
        }
    ]
    assert projection["outputs"][0]["values"] == ["CACHED"]
    assert calls == ["readiness:test.direct.local", "cache-lookup"]
    event_types = [event["event"]["type"] for event in events]
    assert event_types.count("node_attempt_started") == 1
    assert event_types.count("node_attempt_terminal") == 1
    assert "operation_attempt_started" not in event_types
    assert "engine_invocation_started" not in event_types


def test_restart_does_not_publish_unclosed_cache_replay_output(
    tmp_path,
    monkeypatch,
) -> None:
    class FixtureReplaySource(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            return ResultReplayHit(
                {"text": "UNCOMMITTED_CACHE_REPLAY"},
                kwargs["result_identity"],
                "fixture-producer",
            )

    entered = threading.Event()
    paused = threading.Event()
    release = threading.Event()
    original_write = run_execution_v2.write_private_new_file

    def pause_before_attempt_terminal(root, relative_parts, payload, *, field):
        if (
            field == "run_ledger"
            and json.loads(payload)["fact_type"] == "node_attempt_terminal"
            and not paused.is_set()
        ):
            paused.set()
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("fixture cache replay gate timed out")
        return original_write(
            root,
            relative_parts,
            payload,
            field=field,
        )

    monkeypatch.setattr(
        run_execution_v2,
        "write_private_new_file",
        pause_before_attempt_terminal,
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    catalog = _direct_catalog([], cacheable=True)
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }

    try:
        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_result_replay_source=FixtureReplaySource(),
                v2_environment_configuration=environment,
                _v2_wait_for_workers_on_shutdown=False,
            )
        ) as first:
            project_id, compiled = _compile_one_node(first)
            started = first.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": 2,
                    "compile_id": compiled["compile_id"],
                    "client_request_id": "cache-replay-restart",
                },
            )
            assert started.status_code == 202
            assert entered.wait(timeout=1)
            run_id = started.json()["run_id"]

        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted:
            projection = restarted.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
            events = restarted.app.state.run_execution_v2.public_events(
                project_id,
                run_id,
            )
    finally:
        release.set()

    node_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
    )
    assert node_terminal["status"] == "interrupted"
    assert node_terminal["resolution"] == "cache_replayed"
    assert projection["status"] == "interrupted"
    assert projection["outputs"] == []
    assert projection["artifact_index"] == []
    assert projection["node_dispositions"][0]["outcome"] == "interrupted"


@pytest.mark.parametrize("cache_failure", ("lookup_error", "invalid_value"))
def test_cache_boundary_failure_falls_back_to_causally_closed_execution(
    tmp_path,
    monkeypatch,
    cache_failure: str,
) -> None:
    calls: list[str] = []

    class FailingReplaySource(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            calls.append("cache-lookup")
            if cache_failure == "lookup_error":
                raise OSError("fixture cache failure")
            return ResultReplayHit(
                {"text": 17},
                kwargs["result_identity"],
                "fixture-producer",
            )

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_result_replay_source=FailingReplaySource(),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
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
                "client_request_id": f"cache-failure-{cache_failure}",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert projection["node_dispositions"][0]["resolution"] == "executed"
    assert calls == [
        "readiness:test.direct.local",
        "cache-lookup",
        "factory:test.direct.local",
        "execute:test.direct.local",
    ]


def test_public_terminal_wait_helper_never_returns_a_running_projection(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    projections: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_execution_v2,
        "FAST_RUN_COMPLETION_GRACE_SECONDS",
        0.0,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_gate=(entered, release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
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
                "client_request_id": "terminal-wait-regression",
            },
        )
        assert started.status_code == 202
        assert entered.wait(timeout=2)

        def wait_for_terminal() -> None:
            projections.append(
                wait_for_testclient_run_terminal(
                    client,
                    project_id=project_id,
                    run_id=started.json()["run_id"],
                )
            )
            returned.set()

        waiter = threading.Thread(target=wait_for_terminal)
        waiter.start()
        try:
            assert not returned.wait(timeout=0.2)
        finally:
            release.set()
            waiter.join(timeout=5)

    assert not waiter.is_alive()
    assert len(projections) == 1
    assert projections[0]["status"] == "succeeded"


@pytest.mark.parametrize("invocation_count", (0, 2))
def test_one_operation_can_record_zero_or_multiple_engine_invocations(
    tmp_path,
    monkeypatch,
    invocation_count: int,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            invocation_count=invocation_count,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
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
                "client_request_id": f"invocations-{invocation_count}",
            },
        )
        assert started.status_code == 202
        wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        events = app.state.run_execution_v2.public_events(
            project_id,
            started.json()["run_id"],
        )

    event_types = [event["event"]["type"] for event in events]
    assert event_types.count("operation_attempt_started") == 1
    assert event_types.count("operation_attempt_terminal") == 1
    assert event_types.count("engine_invocation_started") == invocation_count
    assert event_types.count("engine_invocation_terminal") == invocation_count
    assert [
        event["event"]["engine_role"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
    ] == (
        [] if invocation_count == 0 else ["primary", "secondary"]
    )


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
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            receipt["run_id"],
        )
        assert projection == {
            "project_id": project_id,
            "run_id": receipt["run_id"],
            "workflow_revision": 2,
            "workflow_digest": compiled["workflow_digest"],
            "compile_id": compiled["compile_id"],
            "status": "succeeded",
            "terminal_sequence": projection["terminal_sequence"],
            "ledger_cursor": projection["ledger_cursor"],
            "node_dispositions": [
                {
                    "node_id": "direct",
                    "outcome": "succeeded",
                    "resolution": "executed",
                    "terminal_sequence": (
                        projection["node_dispositions"][0][
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
                    "result_identity": (
                        projection["outputs"][0]["result_identity"]
                    ),
                    "materialization": {
                        "run_id": receipt["run_id"],
                        "resolution": "executed",
                    },
                    "producer_provenance": {
                        "producer_run_id": receipt["run_id"],
                        "producer_result_identity": (
                            projection["outputs"][0][
                                "result_identity"
                            ]
                        ),
                        "output_port": "text",
                    },
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


def test_changed_credential_is_reobserved_and_rejects_stale_green(
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


def test_reusable_proof_rejects_implicit_environment_identities(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    now = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)

    def readiness(environment) -> ReadinessResult:
        calls.append("checker")
        return ReadinessResult(
            True,
            reusable_proof=ReusableReadinessProof(
                proof_identity="immutable-model-proof-v1",
                proof_scope="test.direct.local@2.0.0",
                observed_at=now,
                maximum_age_seconds=60,
                configuration_fingerprint=(
                    "binding-test.direct.local-2.0.0"
                ),
                invalidation_token="binding-test.direct.local-2.0.0",
            ),
        )

    monkeypatch.setattr(run_execution_v2, "_utc_now", lambda: now)
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
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
                "client_request_id": "implicit-proof-identities",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "readiness_rejected"
    assert calls == []


@pytest.mark.parametrize("observed_offset_seconds", [-61, 1])
def test_new_reusable_proof_rejects_stale_or_future_observation(
    tmp_path,
    monkeypatch,
    observed_offset_seconds: int,
) -> None:
    calls: list[str] = []
    now = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)

    def readiness(environment) -> ReadinessResult:
        calls.append("checker")
        return ReadinessResult(
            True,
            reusable_proof=ReusableReadinessProof(
                proof_identity="immutable-model-proof-v1",
                proof_scope="test.direct.local@2.0.0",
                observed_at=now + timedelta(seconds=observed_offset_seconds),
                maximum_age_seconds=60,
                configuration_fingerprint="configuration-v1",
                invalidation_token="assets-v1",
            ),
        )

    monkeypatch.setattr(run_execution_v2, "_utc_now", lambda: now)
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
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
                "safe_fingerprint": "configuration-v1",
                "invalidation_token": "assets-v1",
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
                "client_request_id": "invalid-proof-age",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "readiness_rejected"
    assert not any(call.startswith("factory:") for call in calls)


def test_reusable_proof_is_cached_only_after_durable_attestation(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[bool] = []
    now = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)

    def readiness(environment) -> ReadinessResult:
        calls.append(environment.reusable_proof is not None)
        if environment.reusable_proof is not None:
            return ReadinessResult(
                True,
                proof_source="refreshed-proof",
                reusable_proof=ReusableReadinessProof(
                    proof_identity="immutable-model-proof-v1",
                    proof_scope="test.direct.local@2.0.0",
                    observed_at=now,
                    maximum_age_seconds=60,
                    configuration_fingerprint="configuration-v1",
                    invalidation_token="assets-v1",
                ),
            )
        return ReadinessResult(
            True,
            proof_source="fresh-proof",
            reusable_proof=ReusableReadinessProof(
                proof_identity="immutable-model-proof-v1",
                proof_scope="test.direct.local@2.0.0",
                observed_at=now,
                maximum_age_seconds=60,
                configuration_fingerprint="configuration-v1",
                invalidation_token="assets-v1",
            ),
        )

    original_append = run_execution_v2._RunEvidenceLedger.append
    failure = {"pending": True}

    def fail_first_attestation(ledger, fact_type, payload):
        if fact_type == "readiness_attested" and failure["pending"]:
            failure["pending"] = False
            raise run_execution_v2.V2RunError(
                "evidence_unavailable",
                "Required Run evidence could not be persisted safely",
                details={"last_durable_cursor": ledger.cursor},
            )
        return original_append(ledger, fact_type, payload)

    monkeypatch.setattr(run_execution_v2, "_utc_now", lambda: now)
    monkeypatch.setattr(
        run_execution_v2._RunEvidenceLedger,
        "append",
        fail_first_attestation,
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
                "safe_fingerprint": "configuration-v1",
                "invalidation_token": "assets-v1",
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

        assert start("proof-ledger-failure").status_code == 503
        assert start("proof-ledger-retry").status_code == 202
        assert start("proof-ledger-reuse").status_code == 202

    assert calls == [False, False, True]
    readiness_facts = [
        json.loads(path.read_text())
        for path in (tmp_path / "runs").rglob("ledger/*.json")
        if json.loads(path.read_text())["fact_type"] == "readiness_attested"
    ]
    assert {
        fact["payload"]["proof_reference"]["reuse_kind"]
        for fact in readiness_facts
    } == {"newly-observed", "reused"}
    refreshed = [
        fact["payload"]
        for fact in readiness_facts
        if fact["payload"]["proof_reference"]["reuse_kind"] == "reused"
    ]
    assert refreshed[0]["refreshed_proof_reference"]["reuse_kind"] == (
        "newly-observed"
    )


def test_node_success_is_not_published_when_disposition_commit_fails(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    cache_root = tmp_path / "cache"
    original_write = run_execution_v2.write_private_new_file

    def fail_disposition(root, relative_parts, payload, *, field):
        if (
            field == "run_ledger"
            and json.loads(payload)["fact_type"] == "node_disposition"
        ):
            raise OSError("fixture evidence store failure")
        return original_write(
            root,
            relative_parts,
            payload,
            field=field,
        )

    monkeypatch.setattr(
        run_execution_v2,
        "write_private_new_file",
        fail_disposition,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
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
                "client_request_id": "disposition-commit-failure",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "evidence_unavailable"
    facts = [
        json.loads(path.read_text())
        for path in (tmp_path / "runs").rglob("ledger/*.json")
    ]
    assert not any(
        fact["fact_type"] in {"node_disposition", "run_terminal"}
        for fact in facts
    )
    assert not list(cache_root.rglob("*.json"))
    assert calls.count("execute:test.direct.local") == 1


def test_cleanup_failure_is_bounded_and_does_not_rewrite_engine_success(
    tmp_path,
    monkeypatch,
) -> None:
    secret = "sk-private-cleanup-failure-token"

    def fail_cleanup(resources) -> None:
        del resources
        raise PermissionError(secret)

    monkeypatch.setattr(
        run_execution_v2.RunResources,
        "cleanup_temporary_work",
        fail_cleanup,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog([]),
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
                "client_request_id": "cleanup-failure",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        projection = wait_for_testclient_run_terminal(client, project_id, run_id)
        events = app.state.run_execution_v2.public_events(project_id, run_id)

    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert projection["artifact_index"] == []
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"]
        in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    ] == ["succeeded", "failed", "failed"]
    retained = b"".join(
        path.read_bytes()
        for path in (tmp_path / "runs").rglob("*.json")
    )
    assert secret.encode() not in retained
    assert secret not in json.dumps(events)


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
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert started.status_code == 202
    assert [output["values"] for output in projection["outputs"]] == [
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
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert projection["node_dispositions"] == [
        {
            "node_id": "source",
            "outcome": "failed",
            "terminal_sequence": (
                projection["node_dispositions"][0][
                    "terminal_sequence"
                ]
            ),
            "blocked_by": [],
        },
        {
            "node_id": "sink",
            "outcome": "blocked",
            "terminal_sequence": (
                projection["node_dispositions"][1][
                    "terminal_sequence"
                ]
            ),
            "blocked_by": ["source"],
        },
    ]
    durable_facts = [
        json.loads(path.read_text())
        for path in sorted((tmp_path / "runs").rglob("ledger/*.json"))
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


def test_artifact_publication_requires_explicit_node_port_opt_in(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_artifact_catalog([], artifact_kind=None)
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "artifact-without-opt-in",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            response.json()["run_id"],
        )

    assert response.status_code == 202
    assert projection["status"] == "failed"
    assert projection["artifact_index"] == []


def test_standalone_file_collection_projects_each_opaque_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    payloads = (
        b"MODEL        1\nEND\n",
        b"MODEL        2\nEND\n",
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_artifact_catalog(
            [],
            collection=True,
            artifact_payloads=payloads,
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "artifact-collection",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(client, project_id, run_id)
        assert projection["outputs"] == []
        assert len(projection["artifact_index"]) == 2
        downloaded = [
            client.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
                f"{artifact['artifact_reference']}"
            ).content
            for artifact in projection["artifact_index"]
        ]

    assert downloaded == list(payloads)


def test_run_artifact_count_and_aggregate_size_are_bounded(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(run_execution_v2, "MAX_ARTIFACTS_PER_RUN", 1)
    monkeypatch.setattr(run_execution_v2, "MAX_ARTIFACT_BYTES_PER_RUN", 8)
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    count_limited = create_app(
        frozen_catalog_override=_artifact_catalog(
            [],
            collection=True,
            artifact_payloads=(b"1234", b"5678"),
        )
    )

    with TestClient(count_limited) as client:
        project_id, compiled = _compile_artifact_node(client)
        count_response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "artifact-count-bound",
            },
        )
        count_projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            count_response.json()["run_id"],
        )

    assert count_response.status_code == 202
    assert count_projection["status"] == "failed"
    assert count_projection["artifact_index"] == []
    assert not any(
        json.loads(path.read_text())["fact_type"] == "artifact_published"
        for path in (tmp_path / "runs").rglob("ledger/*.json")
    )

    monkeypatch.setattr(run_execution_v2, "MAX_ARTIFACTS_PER_RUN", 2)
    aggregate_root = tmp_path / "aggregate-runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(aggregate_root))
    aggregate_limited = create_app(
        frozen_catalog_override=_artifact_catalog(
            [],
            collection=True,
            artifact_payloads=(b"12345", b"67890"),
        )
    )

    with TestClient(aggregate_limited) as client:
        project_id, compiled = _compile_artifact_node(client)
        aggregate_response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "artifact-aggregate-bound",
            },
        )
        aggregate_projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            aggregate_response.json()["run_id"],
        )

    assert aggregate_response.status_code == 202
    assert aggregate_projection["status"] == "failed"
    assert aggregate_projection["artifact_index"] == []
    assert sum(
        json.loads(path.read_text())["fact_type"] == "artifact_published"
        for path in aggregate_root.rglob("ledger/*.json")
    ) == 0
    published_files = list(
        (tmp_path / "outputs").rglob("published/*")
    )
    assert published_files == []


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
        catalog = client.get("/api/v2/catalog")
        assert catalog.status_code == 200
        validate_response("catalog_snapshot", 200, catalog.json())
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
        payload = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )
        assert payload["status"] == "succeeded"
        assert payload["outputs"] == []
        assert len(payload["artifact_index"]) == 1
        artifact = payload["artifact_index"][0]
        assert artifact["artifact_kind"] == "standalone"
        assert artifact["node_id"] == "artifact"
        assert artifact["output_port"] == "structure"
        assert artifact["artifact_reference"] != "models/result-0.pdb"
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

    fact_paths = sorted(run_root.rglob("ledger/*.json"))
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
        artifact = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )["artifact_index"][0]
        reference = artifact["artifact_reference"]

        cross_scope = client.get(
            f"/api/v2/projects/{other_project_id}/runs/{run_id}/artifacts/"
            f"{reference}"
        )
        assert cross_scope.status_code == 404
        assert cross_scope.json()["error"]["code"] == (
            "cross_scope_access_denied"
        )
        cross_projection = client.get(
            f"/api/v2/projects/{other_project_id}/runs/{run_id}"
        )
        assert cross_projection.status_code == 404
        assert cross_projection.json()["error"]["code"] == (
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


def test_terminal_run_projection_and_events_rebuild_after_backend_restart(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    catalog = _direct_catalog([])
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }

    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as client:
        project_id, compiled = _compile_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "restart-terminal",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        before = wait_for_testclient_run_terminal(client, project_id, run_id)
        before_events = client.app.state.run_execution_v2.public_events(
            project_id,
            run_id,
        )
        resume_cursor = before_events[3]["cursor"]

    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as restarted:
        after_response = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        )
        assert after_response.status_code == 200
        after = after_response.json()
        with restarted.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
            f"?after_sequence={resume_cursor}"
        ) as websocket:
            resumed: list[dict[str, Any]] = []
            try:
                while True:
                    resumed.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000

    assert after == before
    resumed_facts = [
        message
        for message in resumed
        if message["event"]["type"] not in {
            "replay_started",
            "replay_complete",
        }
    ]
    expected_sequences = {
        event["sequence"]
        for event in before_events
        if event["sequence"] > before_events[3]["sequence"]
    }
    assert {event["sequence"] for event in resumed_facts} == expected_sequences
    assert len(resumed_facts) == len(expected_sequences)


def test_restart_isolates_one_damaged_ledger_without_hiding_healthy_runs(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    catalog = _direct_catalog([])
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }

    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as first:
        healthy_project, healthy_compiled = _compile_one_node(first)
        damaged_project, damaged_compiled = _compile_one_node(first)
        healthy = first.post(
            f"/api/v2/projects/{healthy_project}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": healthy_compiled["compile_id"],
                "client_request_id": "healthy-ledger",
            },
        ).json()
        damaged = first.post(
            f"/api/v2/projects/{damaged_project}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": damaged_compiled["compile_id"],
                "client_request_id": "damaged-ledger",
            },
        ).json()
        healthy_projection = wait_for_testclient_run_terminal(
            first,
            healthy_project,
            healthy["run_id"],
        )
        wait_for_testclient_run_terminal(
            first,
            damaged_project,
            damaged["run_id"],
        )

    damaged_facts = sorted(
        (
            run_root
            / damaged_project
            / damaged["run_id"]
            / "ledger"
        ).glob("*.json")
    )
    damaged_facts[-1].write_bytes(b"{")

    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as restarted:
        recovered = restarted.get(
            f"/api/v2/projects/{healthy_project}/runs/{healthy['run_id']}"
        )
        isolated = restarted.get(
            f"/api/v2/projects/{damaged_project}/runs/{damaged['run_id']}"
        )

    assert recovered.status_code == 200
    assert recovered.json() == healthy_projection
    assert isolated.status_code == 503
    validate_error(isolated.json(), status=503)
    assert isolated.json()["error"]["code"] == "evidence_unavailable"


def test_running_event_reconnect_switches_from_replay_to_live_without_loss(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_gate=(entered, release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        started_at = time.monotonic()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "replay-live",
            },
        )
        elapsed = time.monotonic() - started_at
        assert started.status_code == 202
        assert elapsed < 1
        assert entered.wait(timeout=1)
        run_id = started.json()["run_id"]
        assert client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        ).json()["status"] == "running"

        first_delivery: list[dict[str, Any]] = []
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            while True:
                message = websocket.receive_json()
                first_delivery.append(message)
                if message["event"]["type"] == "replay_complete":
                    break
        durable_first = [
            message
            for message in first_delivery
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        ]
        cursor = first_delivery[-1]["cursor"]
        release.set()

        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
            f"?after_sequence={cursor}"
        ) as websocket:
            resumed: list[dict[str, Any]] = []
            try:
                while True:
                    resumed.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000
        durable_resumed = [
            message
            for message in resumed
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        ]
        projected = app.state.run_execution_v2.public_events(
            project_id,
            run_id,
        )
        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        ).json()

    delivered_sequences = [
        event["sequence"]
        for event in (*durable_first, *durable_resumed)
    ]
    assert delivered_sequences == [
        event["sequence"]
        for event in projected
    ]
    assert len(delivered_sequences) == len(set(delivered_sequences))
    assert projection["status"] == "succeeded"


def test_background_runs_are_bounded_project_reserved_serial_and_joined(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()
    calls: list[str] = []
    monkeypatch.setattr(run_execution_v2, "MAX_BACKGROUND_RUNS", 2)
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            execution_gate=(entered, release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_a, compiled_a = _compile_one_node(client)
        project_b, compiled_b = _compile_one_node(client)
        project_c, compiled_c = _compile_one_node(client)

        def start(project_id: str, compile_id: str, request_id: str):
            return client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": 2,
                    "compile_id": compile_id,
                    "client_request_id": request_id,
                },
            )

        first = start(project_a, compiled_a["compile_id"], "serial-a")
        assert first.status_code == 202
        assert entered.wait(timeout=1)
        second = start(project_b, compiled_b["compile_id"], "serial-b")
        assert second.status_code == 202
        assert calls.count("execute:test.direct.local") == 1

        same_project = start(
            project_a,
            compiled_a["compile_id"],
            "serial-a-conflict",
        )
        at_capacity = start(
            project_c,
            compiled_c["compile_id"],
            "serial-capacity",
        )
        assert same_project.status_code == 503
        assert at_capacity.status_code == 503
        validate_error(same_project.json(), status=503)
        validate_error(at_capacity.json(), status=503)

        def shutdown() -> None:
            app.state.run_execution_v2.shutdown()
            shutdown_done.set()

        shutdown_thread = threading.Thread(target=shutdown)
        shutdown_thread.start()
        assert not shutdown_done.wait(timeout=0.05)
        release.set()
        assert shutdown_done.wait(timeout=2)
        shutdown_thread.join(timeout=1)

        first_projection = client.get(
            f"/api/v2/projects/{project_a}/runs/{first.json()['run_id']}"
        ).json()
        second_projection = client.get(
            f"/api/v2/projects/{project_b}/runs/{second.json()['run_id']}"
        ).json()
        assert first_projection["status"] == "succeeded"
        assert second_projection["status"] == "succeeded"
        assert calls.count("execute:test.direct.local") == 2
        after_shutdown = start(
            project_c,
            compiled_c["compile_id"],
            "serial-closed",
        )
        assert after_shutdown.status_code == 503
        validate_error(after_shutdown.json(), status=503)


def test_restart_reconciliation_closes_started_work_without_guessing_success(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    catalog = _direct_catalog(
        [],
        execution_gate=(entered, release),
    )
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }

    try:
        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
                _v2_wait_for_workers_on_shutdown=False,
            )
        ) as first:
            project_id, compiled = _compile_one_node(first)
            started = first.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": 2,
                    "compile_id": compiled["compile_id"],
                    "client_request_id": "restart-incomplete",
                },
            )
            assert started.status_code == 202
            assert entered.wait(timeout=1)
            run_id = started.json()["run_id"]
            before_events = first.app.state.run_execution_v2.public_events(
                project_id,
                run_id,
            )
            invocation_started = next(
                event
                for event in before_events
                if event["event"]["type"] == "engine_invocation_started"
            )

        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted:
            projection = restarted.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
            reconciled_events = (
                restarted.app.state.run_execution_v2.public_events(
                    project_id,
                    run_id,
                )
            )

        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted_again:
            repeated_projection = restarted_again.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
            repeated_events = (
                restarted_again.app.state.run_execution_v2.public_events(
                    project_id,
                    run_id,
                )
            )
    finally:
        release.set()

    invocation_terminal = next(
        event
        for event in reconciled_events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        == invocation_started["event"]["invocation_id"]
    )
    operation_started = next(
        event
        for event in reconciled_events
        if event["event"]["type"] == "operation_attempt_started"
    )
    operation_terminal = next(
        event
        for event in reconciled_events
        if event["event"]["type"] == "operation_attempt_terminal"
        and event["event"]["operation_attempt_id"]
        == operation_started["event"]["operation_attempt_id"]
    )
    node_started = next(
        event
        for event in reconciled_events
        if event["event"]["type"] == "node_attempt_started"
    )
    node_terminal = next(
        event
        for event in reconciled_events
        if event["event"]["type"] == "node_attempt_terminal"
        and event["event"]["node_attempt_id"]
        == node_started["event"]["node_attempt_id"]
    )
    assert invocation_terminal["event"]["status"] == "outcome_unknown"
    assert operation_terminal["event"]["status"] == "outcome_unknown"
    assert node_terminal["event"]["status"] == "outcome_unknown"
    assert projection["status"] == "interrupted"
    assert projection["node_dispositions"] == [
        {
            "node_id": "direct",
            "outcome": "interrupted",
            "blocked_by": [],
            "terminal_sequence": projection["node_dispositions"][0][
                "terminal_sequence"
            ],
        }
    ]
    assert projection["outputs"] == []
    assert projection["artifact_index"] == []
    assert not any(cache_root.rglob("*"))
    assert repeated_projection == projection
    assert repeated_events == reconciled_events

    run_dir = run_root / project_id / run_id
    assert json.loads((run_dir / "manifest.json").read_text()) == projection
    persisted_events = [
        json.loads(line)
        for line in (run_dir / "lifecycle.jsonl").read_text().splitlines()
    ]
    assert persisted_events == list(reconciled_events)


def test_run_event_stream_rejects_malformed_stale_and_cross_scope_cursors(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_a, compiled_a = _compile_one_node(client)
        started_a = client.post(
            f"/api/v2/projects/{project_a}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled_a["compile_id"],
                "client_request_id": "cursor-a",
            },
        ).json()
        project_b, compiled_b = _compile_one_node(client)
        started_b = client.post(
            f"/api/v2/projects/{project_b}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled_b["compile_id"],
                "client_request_id": "cursor-b",
            },
        ).json()
        cursor_a = app.state.run_execution_v2.ledger_cursor(
            project_a,
            started_a["run_id"],
        )
        stale_cursor = cursor_a[:-1] + (
            "A" if cursor_a[-1] != "A" else "B"
        )

        cases = (
            (
                project_a,
                started_a["run_id"],
                "not-an-opaque-cursor",
            ),
            (
                project_a,
                started_a["run_id"],
                stale_cursor,
            ),
            (
                project_b,
                started_b["run_id"],
                cursor_a,
            ),
        )
        for project_id, run_id, cursor in cases:
            with client.websocket_connect(
                f"/api/v2/projects/{project_id}/runs/{run_id}/events"
                f"?after_sequence={cursor}"
            ) as websocket:
                error = websocket.receive_json()
                validate_error(error)
                assert error["error"]["code"] == "invalid_cursor"
                with pytest.raises(WebSocketDisconnect) as closed:
                    websocket.receive_json()
                assert closed.value.code == 1008


def test_projection_failure_leaves_facts_intact_and_restart_rebuilds_outputs(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    original_replace = run_execution_v2.replace_private_regular_file
    fail_terminal_lifecycle = {"pending": True}

    def replace_projection(root, relative_parts, payload, *, field):
        if (
            field == "run_lifecycle_projection"
            and fail_terminal_lifecycle["pending"]
            and b'"type":"run_terminal"' in payload
        ):
            fail_terminal_lifecycle["pending"] = False
            raise OSError("fixture projection failure")
        return original_replace(
            root,
            relative_parts,
            payload,
            field=field,
        )

    monkeypatch.setattr(
        run_execution_v2,
        "replace_private_regular_file",
        replace_projection,
    )
    catalog = _direct_catalog([])
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as client:
        project_id, compiled = _compile_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "projection-failure",
            },
        ).json()
        run_id = started["run_id"]
        projection = wait_for_testclient_run_terminal(client, project_id, run_id)
        assert projection["status"] == "succeeded"
        repaired_events = client.app.state.run_execution_v2.public_events(
            project_id,
            run_id,
        )
    ledger_paths = sorted(
        (run_root / project_id / run_id / "ledger").glob("*.json")
    )
    before_restart = [path.read_bytes() for path in ledger_paths]
    assert fail_terminal_lifecycle["pending"] is False
    run_dir = run_root / project_id / run_id
    assert json.loads((run_dir / "manifest.json").read_text()) == projection
    assert [
        json.loads(line)
        for line in (run_dir / "lifecycle.jsonl").read_text().splitlines()
    ] == list(repaired_events)

    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as restarted:
        rebuilt = restarted.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        ).json()
        events = restarted.app.state.run_execution_v2.public_events(
            project_id,
            run_id,
        )

    assert rebuilt == projection
    assert events[-1]["event"] == {
        "type": "run_terminal",
        "status": "succeeded",
    }
    assert [path.read_bytes() for path in ledger_paths] == before_restart
    assert json.loads((run_dir / "manifest.json").read_text()) == rebuilt
    assert [
        json.loads(line)
        for line in (run_dir / "lifecycle.jsonl").read_text().splitlines()
    ] == list(events)


@pytest.mark.parametrize(
    (
        "blocked_fact_type",
        "started_type",
        "terminal_type",
        "expected_terminal",
        "expected_outcome",
        "expected_output_count",
    ),
    (
        (
            "operation_attempt_started",
            "node_attempt_started",
            "node_attempt_terminal",
            "interrupted",
            "interrupted",
            0,
        ),
        (
            "engine_invocation_started",
            "operation_attempt_started",
            "operation_attempt_terminal",
            "interrupted",
            "interrupted",
            0,
        ),
        (
            "node_attempt_terminal",
            "node_attempt_started",
            "node_attempt_terminal",
            "interrupted",
            "interrupted",
            0,
        ),
        (
            "node_disposition",
            "node_attempt_started",
            "node_attempt_terminal",
            "succeeded",
            "succeeded",
            1,
        ),
    ),
)
def test_restart_reconciliation_closes_each_started_outer_attempt(
    tmp_path,
    monkeypatch,
    blocked_fact_type: str,
    started_type: str,
    terminal_type: str,
    expected_terminal: str,
    expected_outcome: str,
    expected_output_count: int,
) -> None:
    entered = threading.Event()
    paused = threading.Event()
    release = threading.Event()
    original_write = run_execution_v2.write_private_new_file

    def pause_before_next_attempt(root, relative_parts, payload, *, field):
        if (
            field == "run_ledger"
            and json.loads(payload)["fact_type"] == blocked_fact_type
            and not paused.is_set()
            and not release.is_set()
        ):
            paused.set()
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("fixture restart gate timed out")
        return original_write(
            root,
            relative_parts,
            payload,
            field=field,
        )

    monkeypatch.setattr(
        run_execution_v2,
        "write_private_new_file",
        pause_before_next_attempt,
    )
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    catalog = _direct_catalog([])
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }

    try:
        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
                _v2_wait_for_workers_on_shutdown=False,
            )
        ) as first:
            project_id, compiled = _compile_one_node(first)
            started = first.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": 2,
                    "compile_id": compiled["compile_id"],
                    "client_request_id": blocked_fact_type,
                },
            )
            assert started.status_code == 202
            assert entered.wait(timeout=1)
            run_id = started.json()["run_id"]

        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted:
            projection = restarted.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
            events = restarted.app.state.run_execution_v2.public_events(
                project_id,
                run_id,
            )
    finally:
        release.set()

    started_event = next(
        event["event"]
        for event in events
        if event["event"]["type"] == started_type
    )
    identity_field = {
        "node_attempt_started": "node_attempt_id",
        "operation_attempt_started": "operation_attempt_id",
    }[started_type]
    terminal_event = next(
        event["event"]
        for event in events
        if event["event"]["type"] == terminal_type
        and event["event"][identity_field] == started_event[identity_field]
    )
    assert terminal_event["status"] == expected_terminal
    assert projection["status"] == "interrupted"
    assert projection["node_dispositions"][0]["outcome"] == expected_outcome
    assert len(projection["outputs"]) == expected_output_count


def test_restart_reconciliation_disposes_every_plan_node_by_direct_cause(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    catalog = _pipeline_catalog(
        [],
        execution_gates={"failing": (entered, release)},
    )

    try:
        with TestClient(
            create_app(
                frozen_catalog_override=catalog,
                _v2_wait_for_workers_on_shutdown=False,
            )
        ) as first:
            project_id, compiled = _compile_branching_pipeline(first)
            started = first.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_revision": 2,
                    "compile_id": compiled["compile_id"],
                    "client_request_id": "restart-branching",
                },
            )
            assert started.status_code == 202
            assert entered.wait(timeout=1)
            run_id = started.json()["run_id"]

        with TestClient(
            create_app(frozen_catalog_override=catalog)
        ) as restarted:
            projection = restarted.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
    finally:
        release.set()

    dispositions = {
        item["node_id"]: item
        for item in projection["node_dispositions"]
    }
    assert set(dispositions) == {
        "failing",
        "independent",
        "blocked",
        "successful",
    }
    assert dispositions["failing"]["outcome"] == "interrupted"
    assert dispositions["independent"]["outcome"] == "interrupted"
    assert dispositions["blocked"]["blocked_by"] == ["failing"]
    assert dispositions["successful"]["blocked_by"] == ["independent"]
    assert projection["status"] == "interrupted"
