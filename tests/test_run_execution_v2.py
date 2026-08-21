"""Public-seam contracts for readiness-gated v2 direct execution."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Literal, Mapping

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
    OperationCall,
    OperationContext,
    PortTypeDefinition,
    PortValueError,
    PreScheduleTermination,
    ProjectManager,
    ReadinessCheckInput,
    ReadinessResult,
    ReadinessDeclaration,
    ResultReplayHit,
    ResultReplaySource,
    RunResources,
    ScientificOperationFactory,
    builtin_frozen_catalog,
)
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from core.server import create_app
import core.run_execution_v2 as run_execution_v2
from core.value_admission import admitted_port_values
from core.workflow_authoring_v2 import WorkflowAuthoringService
from core.workflow_v2 import (
    ExecutionPlanNode,
    compile_workflow,
    parse_workflow_document,
    relock_workflow,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ProteinSequence,
)
from protein_workbench_public import (
    artifact_content_disposition,
    validate_error,
    validate_response,
    validate_schema,
)
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)
from tests.fixtures.result_replay_v2 import admitted_replay_outputs
from tests.fixtures.scientific_operation import admitted_port_fixture


def _transaction_has_fact(payload: bytes, fact_type: str) -> bool:
    transaction = json.loads(payload)
    return any(
        fact["fact_type"] == fact_type for fact in transaction["facts"]
    )


def _durable_facts(root) -> list[dict[str, Any]]:
    return [
        fact
        for path in sorted(root.rglob("ledger/*.json"))
        for fact in json.loads(path.read_text())["facts"]
    ]


def _object_path(
    output_root: Path,
    project_id: str,
    content_digest: str,
) -> Path:
    return (
        output_root
        / project_id
        / "objects"
        / Path(
            *run_execution_v2.ProjectObjectStore._relative_parts(
                content_digest
            )
        )
    )


def _contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict[str, Any],
) -> CatalogContract:
    return CatalogContract(
        contract_kind=contract_kind,
        contract_id=contract_id,
        contract_version="2.1.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            "contract_version": "2.1.0",
            **descriptor,
        },
    )


def test_operation_cannot_override_plan_owned_engine_identity(tmp_path) -> None:
    recorded: list[dict[str, Any]] = []

    class Recorder:
        @contextmanager
        def invoke(self, **kwargs: Any):
            recorded.append(kwargs)
            yield "invocation-1"

    resources = RunResources(
        project_id="project-1",
        run_id="run-1",
        node_id="node-1",
        _projects=ProjectManager(tmp_path / "projects"),
        _invocation_recorder=Recorder(),
    )

    with pytest.raises(TypeError, match="engine_identity"):
        with resources.engine_invocation(
            engine_identity="sha256:" + "1" * 64,
        ):  # type: ignore[call-arg]
            pass
    assert recorded == []


def _direct_catalog(
    calls: list[str],
    *,
    binding_ids: tuple[str, ...] = ("test.direct.local",),
    failing_binding_id: str | None = None,
    readiness_prerequisites: dict[str, Any] | None = None,
    readiness_checks: dict[str, Any] | None = None,
    cacheable: bool = False,
    unavailable_binding_ids: tuple[str, ...] = (),
    invocation_count: int = 1,
    execution_gate: tuple[threading.Event, threading.Event] | None = None,
    execution_action: Any | None = None,
    factory_action: Any | None = None,
    invalid_factory_result: bool = False,
    execution_output: Any = "READY",
    implementation_variant: str = "default",
    implementation_label: str | None = None,
    deterministic: bool = True,
    execution_route: Literal["adapter", "direct"] = "adapter",
    source_identity: Mapping[str, Any] | None = None,
    node_parameter_declarations: Mapping[str, Any] | None = None,
    node_title: str = "Deterministic direct test Node",
    effective_randomness_parameters: tuple[str, ...] = (),
    effective_randomness_resolver: EffectiveRandomnessResolver | None = None,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text", "2.1.0")
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
            "2.1.0",
            {"route": "direct"},
        )
        binding_readiness_behavior = BehaviorReference(
            f"{binding_id}/readiness",
            "2.1.0",
            {"observation": "per-run"},
        )
        binding_adapter_behavior = BehaviorReference(
            f"{binding_id}/adapter",
            "2.1.0",
            {"route": "provider"},
        )
        binding = _contract(
            "binding",
            binding_id,
            {
                "node_type": node_type.reference(),
                "method": method.reference(),
                "binding_parameters": {},
                "execution_route": execution_route,
                "route_behavior": (
                    binding_adapter_behavior.descriptor()
                    if execution_route == "adapter"
                    else binding_factory_behavior.descriptor()
                ),
                "availability_declaration": {
                    "behavior": {
                        "behavior_id": f"{binding_id}/availability",
                        "behavior_version": "2.1.0",
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
                        {"adapter": binding_adapter_behavior.descriptor()}
                        if execution_route == "adapter"
                        else {}
                    ),
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

            def execute(self, call: OperationCall) -> dict[str, Any]:
                assert call.inputs == {}
                if node_parameter_declarations is None:
                    assert call.node_parameters == {}
                else:
                    calls.append(
                        f"parameters:{dict(call.node_parameters)!r}"
                    )
                assert call.binding_parameters == {}
                if effective_randomness_parameters:
                    calls.append(
                        "randomness:"
                        f"{dict(call.effective_randomness)!r}"
                    )
                else:
                    assert call.effective_randomness == {}
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
            def readiness(
                check_input: ReadinessCheckInput,
            ) -> ReadinessResult:
                if (
                    readiness_checks is not None
                    and exact_binding_id in readiness_checks
                ):
                    return readiness_checks[exact_binding_id](check_input)
                assert (
                    check_input.values["credential"]
                    == "credential-value"
                )
                calls.append(f"readiness:{exact_binding_id}")
                return ReadinessResult(
                    exact_binding_id != failing_binding_id
                )

            return readiness

        def make_factory(exact_binding_id: str):
            def factory(context: OperationContext) -> DirectImplementation:
                assert isinstance(
                    context.environment["credential"],
                    str,
                )
                assert context.method.contract_id == "test.direct.method"
                assert context.produced_observations == ()
                assert context.selection_objectives == ()
                assert context.observation_selectors == ()
                assert not hasattr(context, "frozen_catalog")
                assert not hasattr(context, "execution_plan")
                assert not hasattr(context, "node_type")
                assert not hasattr(context, "binding")
                assert not hasattr(context, "content_digest")
                assert context.resources.project_id
                calls.append(f"factory:{exact_binding_id}")
                if factory_action is not None:
                    factory_action(context.resources)
                if invalid_factory_result:
                    return None  # type: ignore[return-value]
                return DirectImplementation(
                    exact_binding_id,
                    context.resources,
                )

            return factory

        factories[(binding_id, "2.1.0")] = ScientificOperationFactory(
            behavior=binding_factory_behavior,
            build=make_factory(binding_id),
        )
        readiness_declarations[(binding_id, "2.1.0")] = ReadinessDeclaration(
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
            (
                {
                    "binding": binding.reference(),
                    "observed_at": observed_at.isoformat(),
                    "available": False,
                    "reason": {
                        "code": "provider_unavailable",
                        "message": "Provider is unavailable",
                        "retryable": False,
                    },
                }
                if binding.contract_id in unavailable_binding_ids
                else {
                    "binding": binding.reference(),
                    "observed_at": observed_at.isoformat(),
                    "available": True,
                }
            )
            for binding in bindings
        ),
        availability_observed_at=observed_at,
        factories=factories,
        readiness_declarations=readiness_declarations,
        effective_randomness_resolvers=(
            {
                (binding_id, "2.1.0"): effective_randomness_resolver
                for binding_id in binding_ids
            }
            if effective_randomness_resolver is not None
            else {}
        ),
    )


def _commit_public_workflow(
    client: TestClient,
    project_id: str,
    workflow: Mapping[str, Any],
) -> dict[str, Any]:
    committed = client.post(
        f"/api/v2/projects/{project_id}/workflow:commit",
        json={
            "workflow": workflow,
        },
    )
    assert committed.status_code == 200
    return committed.json()


def _commit_one_node(client: TestClient) -> tuple[str, dict[str, Any]]:
    project = client.post(
        "/api/v2/projects", json={"name": "v2 direct"}
    ).json()
    project_id = project["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "direct",
                "node_type_id": "test.direct",
                "node_type_version": "2.1.0",
                "binding_id": "test.direct.local",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "contract_lock": [],
    }
    return project_id, _commit_public_workflow(client, project_id, workflow)


def _commit_independent_nodes(
    client: TestClient,
    binding_ids: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    project = client.post(
        "/api/v2/projects", json={"name": "v2 readiness"}
    ).json()
    project_id = project["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": f"direct-{index}",
                "node_type_id": "test.direct",
                "node_type_version": "2.1.0",
                "binding_id": binding_id,
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
            for index, binding_id in enumerate(binding_ids)
        ],
        "edges": [],
        "contract_lock": [],
    }
    return project_id, _commit_public_workflow(client, project_id, workflow)


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
    candidate_digest_probe: bool = False,
    candidate_conflict_probe: bool = False,
    execution_gates: (
        Mapping[str, tuple[threading.Event, threading.Event]] | None
    ) = None,
) -> FrozenCatalog:
    include_candidate_data = candidate_digest_probe or candidate_conflict_probe
    builtin = builtin_frozen_catalog()
    candidate_collection_type = builtin.require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    candidate_data_type = builtin.require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    def validate_text(value: Any) -> None:
        calls.append(f"validate:{value!r}")
        if type(value) is not str:
            raise PortValueError("canonical text requires a string")

    canonical_text = PortTypeDefinition(
        type_id="test.canonical_text",
        version="2.1.0",
        validator=BehaviorReference(
            "test.canonical_text/validate",
            "2.1.0",
            {"accepted_value_kind": "text"},
        ),
        codec=BehaviorReference(
            "test.canonical_text/codec",
            "2.1.0",
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
            "2.1.0",
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
                },
                *(
                    [
                        {
                            "name": "candidates",
                            "port_type": candidate_collection_type.reference(),
                            "required": True,
                            "multiplicity": "one",
                            "scientific_meaning": "Candidate digest probe",
                        }
                    ]
                    if include_candidate_data
                    else []
                ),
            ],
            "parameter_groups": [],
            "node_parameters": (
                {
                    "source_variant": {
                        "parameter_scope": "scientific",
                        "scientific_meaning": (
                            "Distinct source identity for Candidate conflict "
                            "fixtures"
                        ),
                        "value_contract": {"type": "string"},
                        "required": True,
                    }
                }
                if candidate_conflict_probe
                else {}
            ),
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
                },
                *(
                    [
                        {
                            "name": "candidates",
                            "port_type": candidate_collection_type.reference(),
                            "required": True,
                            "multiplicity": (
                                "many" if candidate_conflict_probe else "one"
                            ),
                            "scientific_meaning": "Candidate digest probe",
                        }
                    ]
                    if include_candidate_data
                    else []
                ),
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

        def execute(self, call: OperationCall) -> dict[str, Any]:
            assert call.inputs == {}
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
                outputs: dict[str, Any] = {
                    "text": 17 if invalid_source_output else " READY "
                }
                if include_candidate_data:
                    outputs["candidates"] = CandidateCollection(
                        collection_id="digest-probe",
                        item_type="protein.sequence",
                        items=[
                            Candidate(
                                candidate_id="digest-probe-z",
                                data=ProteinSequence(sequence="MA"),
                            ),
                            Candidate(
                                candidate_id="digest-probe-a",
                                data=ProteinSequence(sequence="MG"),
                            ),
                        ],
                    )
                return outputs

    class SinkImplementation:
        def __init__(self, resources) -> None:
            self._resources = resources

        def execute(self, call: OperationCall) -> dict[str, Any]:
            text_record = call.inputs.get("text")
            if text_record is not None:
                assert (
                    text_record.port_type["contract_id"]
                    == "test.canonical_text"
                )
                assert len(text_record.value_content_digests) == 1
            if include_candidate_data:
                candidate_record = call.inputs["candidates"]
                candidates = candidate_record.value
                candidate_values = (
                    tuple(
                        candidate
                        for collection in candidates
                        for candidate in collection.items
                    )
                    if candidate_conflict_probe
                    else tuple(candidates.items)
                )
                assert (
                    candidate_record.port_type["contract_id"]
                    == "candidate.collection"
                )
                assert len(candidate_record.value_content_digests) == (
                    2 if candidate_conflict_probe else 1
                )
                assert all(
                    type(item) is CandidateDataReference
                    for item in candidate_record.candidate_data
                )
                assert [
                    item.candidate_id for item in candidate_record.candidate_data
                ] == [candidate.candidate_id for candidate in candidate_values]
                assert [
                    item.data_type_id for item in candidate_record.candidate_data
                ] == ["protein.sequence"] * len(candidate_values)
                assert [
                    item.content_digest for item in candidate_record.candidate_data
                ] == [
                    candidate_data_type.content_digest(candidate.data)
                    for candidate in candidate_values
                ]
                calls.append("candidate-digests:verified")
            with self._resources.engine_invocation():
                text_value = (
                    text_record.value
                    if text_record is not None
                    else "OPTIONAL"
                )
                calls.append(
                    f"sink-input:{text_record.value if text_record else None}"
                )
                return {"text": text_value}

    for binding_id, node_type, implementation in (
        ("test.pipeline.source.direct", source, SourceImplementation),
        ("test.pipeline.sink.direct", sink, SinkImplementation),
    ):
        factory_behavior = BehaviorReference(
            f"{binding_id}/factory",
            "2.1.0",
            {},
        )
        readiness_behavior = BehaviorReference(
            f"{binding_id}/readiness",
            "2.1.0",
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
                        "behavior_version": "2.1.0",
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
            context: OperationContext,
            implementation=implementation,
        ) -> Any:
            if candidate_conflict_probe:
                calls.append(f"factory:{context.resources.node_id}")
            if implementation is SourceImplementation:
                node_id = context.resources.node_id
                if (
                    pre_schedule_source_nodes is not None
                    and node_id in pre_schedule_source_nodes
                ):
                    raise PreScheduleTermination(
                        pre_schedule_source_nodes[node_id]
                    )
                return implementation(node_id, context.resources)
            return implementation(context.resources)

        factories[(binding_id, "2.1.0")] = ScientificOperationFactory(
            behavior=factory_behavior,
            build=build_implementation,
        )
        readiness[(binding_id, "2.1.0")] = ReadinessDeclaration(
            behavior=readiness_behavior,
            prerequisites={},
            check=lambda check_input: ReadinessResult(True),
        )
        availability.append(
            {
                "binding": binding.reference(),
                "observed_at": "2026-07-29T08:00:00+00:00",
                "available": True,
            }
        )
    return FrozenCatalog(
        (
            canonical_text,
            *(
                (candidate_collection_type, candidate_data_type)
                if include_candidate_data
                else ()
            ),
        ),
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
    artifact_candidate_id: str | None = None,
    collection: bool = False,
    artifact_payloads: tuple[bytes, ...] = (b"MODEL        1\nEND\n",),
    cacheable: bool = False,
    include_ordinary_output: bool = False,
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    artifact_port_type = PROTEIN_IO_PACKAGE.port_types[0]
    if artifact_kind == "candidate":
        # This fixture isolates the core publication seam. Candidate identity
        # is metadata owned by that seam, not by a storage-path policy in a
        # package-specific artifact codec.
        artifact_port_type = replace(
            artifact_port_type,
            runtime_validator=lambda _value: None,
        )
    output_contracts = [
        {
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
        }
    ]
    if include_ordinary_output:
        output_contracts.insert(
            0,
            {
                "name": "summary",
                "port_type": builtin.require_port_type(
                    "text",
                    "2.1.0",
                ).reference(),
                "required": True,
                "multiplicity": "one",
                "scientific_meaning": "Deterministic artifact summary",
            },
        )
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
            "outputs": output_contracts,
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    factory_behavior = BehaviorReference(
        "test.artifact/factory",
        "2.1.0",
        {},
    )
    readiness_behavior = BehaviorReference(
        "test.artifact/readiness",
        "2.1.0",
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
                    "behavior_version": "2.1.0",
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

        def execute(self, call: OperationCall) -> dict[str, Any]:
            assert call.inputs == {}
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
                    candidate_id=artifact_candidate_id,
                )
                for index, payload in enumerate(artifact_payloads)
            ]
            outputs: dict[str, Any] = {
                "structure": (
                    payload_values if collection else payload_values[0]
                )
            }
            if include_ordinary_output:
                outputs["summary"] = "READY"
            return outputs

    def factory(context: OperationContext) -> ArtifactImplementation:
        return ArtifactImplementation(context.resources)

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
            ("test.artifact.direct", "2.1.0"): ScientificOperationFactory(
                behavior=factory_behavior,
                build=factory,
            )
        },
        readiness_declarations={
            ("test.artifact.direct", "2.1.0"): ReadinessDeclaration(
                behavior=readiness_behavior,
                prerequisites={},
                check=lambda check_input: ReadinessResult(True),
            )
        },
    )


def _commit_artifact_node(
    client: TestClient,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/v2/projects",
        json={"name": "v2 artifact"},
    ).json()["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "artifact",
                "node_type_id": "test.artifact",
                "node_type_version": "2.1.0",
                "binding_id": "test.artifact.direct",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "contract_lock": [],
    }
    return project_id, _commit_public_workflow(client, project_id, workflow)


def _commit_pipeline(
    client: TestClient,
    *,
    candidate_digest_probe: bool = False,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/v2/projects",
        json={"name": "v2 canonical boundary"},
    ).json()["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "source",
                "node_type_id": "test.pipeline.source",
                "node_type_version": "2.1.0",
                "binding_id": "test.pipeline.source.direct",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "sink",
                "node_type_id": "test.pipeline.sink",
                "node_type_version": "2.1.0",
                "binding_id": "test.pipeline.sink.direct",
                "binding_version": "2.1.0",
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
            },
            *(
                [
                    {
                        "source_node_id": "source",
                        "source_port": "candidates",
                        "target_node_id": "sink",
                        "target_port": "candidates",
                    }
                ]
                if candidate_digest_probe
                else []
            ),
        ],
        "contract_lock": [],
    }
    return project_id, _commit_public_workflow(client, project_id, workflow)


def _commit_branching_pipeline(
    client: TestClient,
) -> tuple[str, dict[str, Any]]:
    project_id = client.post(
        "/api/v2/projects",
        json={"name": "v2 branch failure"},
    ).json()["id"]
    nodes = [
        {
            "node_id": node_id,
            "node_type_id": node_type_id,
            "node_type_version": "2.1.0",
            "binding_id": binding_id,
            "binding_version": "2.1.0",
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
        "schema_version": "2.1.0",
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
    return project_id, _commit_public_workflow(client, project_id, workflow)


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
        project_id, compiled = _commit_branching_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        project_id, compiled = _commit_branching_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        project_id, compiled = _commit_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
def test_factory_termination_closes_node_attempt_without_operation(
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
        project_id, compiled = _commit_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
    event_types = [event["event"]["type"] for event in events]
    assert event_types.count("node_attempt_started") == 1
    assert event_types.count("node_attempt_terminal") == 1
    assert "operation_attempt_started" not in event_types
    assert "engine_invocation_started" not in event_types


def test_invalid_scientific_operation_factory_fails_after_attempt_start(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            invalid_factory_result=True,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "invalid-operation-factory",
            },
        )

    assert started.status_code == 500
    validate_error(started.json(), status=500)
    assert started.json()["error"]["code"] == "internal_error"
    fact_types = [
        fact["fact_type"] for fact in _durable_facts(tmp_path / "runs")
    ]
    assert fact_types.count("node_attempt_started") == 1
    assert "operation_attempt_started" not in fact_types
    assert "engine_invocation_started" not in fact_types
    assert "node_attempt_terminal" not in fact_types


def test_cache_replay_closes_only_the_scheduled_node_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    catalog = _direct_catalog(
        calls,
        cacheable=True,
        unavailable_binding_ids=("test.direct.local",),
    )

    class FixtureReplaySource(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            assert kwargs["project_id"]
            assert kwargs["node"].node_id == "direct"
            assert kwargs["inputs"] == {}
            calls.append("cache-lookup")
            outputs = {"text": "CACHED"}
            return ResultReplayHit(
                result_identity=kwargs["result_identity"],
                producer_run_id="fixture-producer",
                admitted_outputs=admitted_replay_outputs(
                    catalog=catalog,
                    node=kwargs["node"],
                    outputs=outputs,
                ),
            )

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=catalog,
        v2_result_replay_source=FixtureReplaySource(),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        replayed_values = retrieve_typed_output_values(
            client,
            project_id,
            run_id,
            projection["outputs"][0],
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
    assert replayed_values == ["CACHED"]
    assert calls == ["cache-lookup"]
    event_types = [event["event"]["type"] for event in events]
    assert event_types.count("node_attempt_started") == 1
    assert event_types.count("node_attempt_terminal") == 1
    assert "operation_attempt_started" not in event_types
    assert "engine_invocation_started" not in event_types


def test_cache_miss_fails_at_an_unavailable_binding_without_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            unavailable_binding_ids=("test.direct.local",),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "unavailable-cache-miss",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started.json()["run_id"],
        )
        events = app.state.run_execution_v2.public_events(
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "failed"
    assert calls == []
    terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert terminal["failure_origin"] == "binding"
    assert terminal["error"]["code"] == "binding_unavailable"
    assert not any(
        item["event"]["type"] in {
            "readiness_attested",
            "operation_attempt_started",
            "engine_invocation_started",
        }
        for item in events
    )


def test_direct_cache_miss_enters_its_operation_without_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            execution_route="direct",
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "direct-without-readiness",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started.json()["run_id"],
        )
        events = app.state.run_execution_v2.public_events(
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert calls == [
        "factory:test.direct.local",
        "execute:test.direct.local",
    ]
    assert not any(
        item["event"]["type"] == "readiness_attested"
        for item in events
    )


def test_adapter_preoperation_error_precedes_provider_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fail_randomness(**_kwargs: Any) -> Mapping[str, Any]:
        calls.append("randomness")
        raise RuntimeError("fixture randomness resolution failed")

    def fail_readiness(_check_input: ReadinessCheckInput) -> ReadinessResult:
        calls.append("readiness")
        return ReadinessResult(False)

    resolver = EffectiveRandomnessResolver(
        behavior=BehaviorReference(
            "test.direct/failing-randomness",
            "2.1.0",
            {},
        ),
        resolve=fail_randomness,
    )
    catalog = _direct_catalog(
        calls,
        readiness_checks={"test.direct.local": fail_readiness},
        node_parameter_declarations={
            "seed": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Exact synthetic random seed",
                "value_contract": {"type": "integer"},
                "default": 5,
            }
        },
        effective_randomness_parameters=("seed",),
        effective_randomness_resolver=resolver,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "preoperation-error",
            },
        )

    assert started.status_code == 500
    validate_error(started.json(), status=500)
    assert started.json()["error"]["code"] == "internal_error"
    assert not any(
        fact["fact_type"]
        in {
            "node_attempt_started",
            "operation_attempt_started",
            "readiness_attested",
            "engine_invocation_started",
        }
        for fact in _durable_facts(tmp_path / "runs")
    )
    assert calls == ["randomness"]


def test_readiness_programming_error_fails_after_attempt_start(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def invalid_readiness(
        _check_input: ReadinessCheckInput,
    ) -> ReadinessResult:
        calls.append("readiness")
        raise RuntimeError("fixture Readiness invariant failure")

    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_RUN_ROOT",
        str(tmp_path / "runs"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            readiness_checks={"test.direct.local": invalid_readiness},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "invalid-readiness",
            },
        )

    assert started.status_code == 500
    validate_error(started.json(), status=500)
    assert started.json()["error"]["code"] == "internal_error"
    assert calls == ["readiness"]
    fact_types = [
        fact["fact_type"] for fact in _durable_facts(tmp_path / "runs")
    ]
    assert fact_types.count("node_attempt_started") == 1
    assert "readiness_attested" not in fact_types
    assert "operation_attempt_started" not in fact_types
    assert "engine_invocation_started" not in fact_types
    assert "node_attempt_terminal" not in fact_types


def test_result_replay_hit_requires_admitted_output_snapshots() -> None:
    with pytest.raises(TypeError, match="admitted_outputs"):
        ResultReplayHit(
            result_identity="sha256:" + "0" * 64,
            producer_run_id="fixture-producer",
        )
    with pytest.raises(TypeError, match="admitted_outputs"):
        ResultReplayHit(
            result_identity="sha256:" + "0" * 64,
            producer_run_id="fixture-producer",
            admitted_outputs=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("cache_failure", ("lookup_error", "invalid_value"))
def test_cache_invariant_failure_fails_fast_without_executing_provider(
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
            outputs = {"text": 17}
            return ResultReplayHit(
                result_identity=kwargs["result_identity"],
                producer_run_id="fixture-producer",
                admitted_outputs=admitted_replay_outputs(
                    catalog=catalog,
                    node=kwargs["node"],
                    outputs=outputs,
                ),
            )

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    catalog = _direct_catalog(calls, cacheable=True)
    app = create_app(
        frozen_catalog_override=catalog,
        v2_result_replay_source=FailingReplaySource(),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": f"cache-failure-{cache_failure}",
            },
        )
        assert started.status_code == 500
        assert started.json()["error"]["code"] == "internal_error"

    assert calls == ["cache-lookup"]
    fact_types = [
        fact["fact_type"] for fact in _durable_facts(tmp_path / "runs")
    ]
    assert fact_types.count("node_attempt_started") == 1
    assert "operation_attempt_started" not in fact_types
    assert "engine_invocation_started" not in fact_types


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
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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


def test_public_start_run_binds_the_exact_commit_before_direct_execution(
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
            ("test.direct.local", "2.1.0"): {
                "values": {
                    "credential": "credential-value",
                    "runtime_path": str(tmp_path / "private-runtime"),
                },
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        output_values = retrieve_typed_output_values(
            client,
            project_id,
            receipt["run_id"],
            projection["outputs"][0],
        )
        assert projection == {
            "project_id": project_id,
            "run_id": receipt["run_id"],
            "workflow_commit_id": compiled["workflow_commit_id"],
            "workflow_commit_revision": compiled[
                "workflow_commit_revision"
            ],
            "workflow_digest": compiled["workflow_digest"],
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
                            "2.1.0",
                        ).reference()
                    ),
                    "content_digest": (
                        _direct_catalog([]).require_port_type(
                            "text",
                            "2.1.0",
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
                    "value_count": 1,
                    "value_manifest_reference": (
                        projection["outputs"][0][
                            "value_manifest_reference"
                        ]
                    ),
                }
            ],
            "artifact_index": [],
        }
        assert output_values == ["READY"]

    assert calls == [
        "readiness:test.direct.local",
        "factory:test.direct.local",
        "execute:test.direct.local",
    ]


def test_node_execution_attempt_interface_returns_only_committed_outcome(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_RUN_ROOT",
        str(tmp_path / "runs"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        service = app.state.run_execution_v2
        compiled = service._authoring.require_compiled(
            project_id,
            workflow_commit_id=committed["workflow_commit_id"],
        )
        plan = compiled.execution_plan
        node = plan.nodes[0]
        run_id = "run-attempt-interface"
        contract_roots = tuple(
            run_execution_v2._execution_plan_contract_roots(plan)
        )
        ledger = run_execution_v2._RunEvidenceLedger(
            service._projects,
            project_id,
            run_id,
            service._plan_evidence(plan),
            service._ledger_transaction_store,
            expected_resolved_contracts=tuple(
                entry.to_public() for entry in plan.resolved_contracts
            ),
            expected_contract_roots=contract_roots,
        )
        ledger.record(
            run_execution_v2.RunScopeBinding(
                workflow_commit_id=committed["workflow_commit_id"],
                workflow_commit_revision=plan.workflow_commit_revision,
                workflow_digest=plan.workflow_digest,
                contract_lock_digest=plan.contract_lock_digest,
                execution_plan_digest=plan.execution_plan_digest,
                catalog_contract_digest=plan.catalog_contract_digest,
                resolved_contracts=tuple(
                    entry.to_public() for entry in plan.resolved_contracts
                ),
                resolved_contract_roots=contract_roots,
            )
        )
        availability = service._availability(node)
        ledger.record(
            run_execution_v2.AvailabilityBinding(
                binding=node.binding.to_public(),
                catalog_observed_at=availability["observed_at"],
                available=availability["available"],
            )
        )
        ledger.record(
            run_execution_v2.RunAdmission(
                workflow_commit_id=committed["workflow_commit_id"],
                workflow_commit_revision=plan.workflow_commit_revision,
            )
        )
        ledger.record(
            run_execution_v2.RunStart(
                started_at="2026-08-21T00:00:00Z",
            )
        )
        record = run_execution_v2._RunRecord(
            compiled=compiled,
            ledger=ledger,
        )
        attempts = run_execution_v2._NodeExecutionAttemptModule(
            projects=service._projects,
            environment=service._environment,
            result_replay_source=service._result_replay_source,
            object_store=service._object_store,
            project_id=project_id,
            run_id=run_id,
            execution_plan=plan,
            ledger=ledger,
            run_record=record,
            availability_by_binding={
                (
                    node.binding.contract_id,
                    node.binding.contract_version,
                ): availability,
            },
        )

        outcome = attempts.execute(
            node,
            committed_values={},
            committed_artifacts=(),
            cache_bypassed=False,
        )

    assert outcome.disposition == "succeeded"
    assert outcome.artifacts == ()
    assert outcome.admitted_outputs[("direct", "text")].value == "READY"
    assert [fact["fact_type"] for fact in ledger.facts[-4:]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]


def test_run_executes_only_the_resolved_plan_after_compilation(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    randomness_calls: list[dict[str, Any]] = []

    def resolve_randomness(**kwargs: Any) -> Mapping[str, Any]:
        randomness_calls.append(
            {
                **kwargs,
                "node_parameters": dict(kwargs["node_parameters"]),
            }
        )
        return {"seed": 17}

    resolver = EffectiveRandomnessResolver(
        behavior=BehaviorReference(
            "test.direct/randomness",
            "2.1.0",
            {"resolution": "exact-seed"},
        ),
        resolve=resolve_randomness,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    catalog = _direct_catalog(
        calls,
        node_parameter_declarations={
            "seed": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Exact synthetic random seed",
                "value_contract": {"type": "integer"},
                "default": 5,
            }
        },
        effective_randomness_parameters=("seed",),
        effective_randomness_resolver=resolver,
    )
    app = create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)

        def forbid_execution_lookup(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(
                "Run execution must use only commit-time resolved facts"
            )

        for method_name in (
            "get_contract",
            "get_effective_randomness_resolver",
            "require_contract",
            "require_factory",
            "require_port_type",
            "require_readiness_declaration",
            "require_utility_transform",
        ):
            monkeypatch.setattr(
                FrozenCatalog,
                method_name,
                forbid_execution_lookup,
            )

        receipt = app.state.run_execution_v2.start(
            project_id,
            workflow_commit_id=compiled["workflow_commit_id"],
            client_request_id="resolved-plan-only",
        )
        projection = app.state.run_execution_v2.projection(
            project_id,
            receipt["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert len(randomness_calls) == 1
    assert randomness_calls[0]["node_parameters"] == {"seed": 5}
    assert calls == [
        "readiness:test.direct.local",
        "factory:test.direct.local",
        "parameters:{'seed': 17}",
        "randomness:{'seed': 17}",
        "execute:test.direct.local",
    ]


def test_run_rejects_a_resolved_plan_from_another_catalog_generation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    compiled_catalog = _direct_catalog([])
    app = create_app(frozen_catalog_override=compiled_catalog)

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        active_catalog = _direct_catalog(
            [],
            node_title="Scientifically distinct active generation",
        )
        service = run_execution_v2.V2RunService(
            app.state.project_manager,
            active_catalog,
            app.state.workflow_authoring_v2,
            run_execution_v2.EnvironmentConfiguration({}),
        )
        try:
            with pytest.raises(run_execution_v2.V2RunError) as captured:
                service.start(
                    project_id,
                    workflow_commit_id=compiled["workflow_commit_id"],
                    client_request_id="inactive-plan",
                )
        finally:
            service.shutdown()

    assert captured.value.code == "contract_digest_mismatch"


def test_simplefold_bindings_receive_independent_run_scoped_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    import modules.folding.simplefold_adapter as folding_adapter
    import modules.folding.simplefold_confidence_adapter as confidence_adapter
    from modules.folding.simplefold_asset_closure import (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        SimpleFoldProviderAssetClosure,
    )

    calls: list[str] = []
    admissions: list[SimpleFoldProviderAssetClosure] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    bindings = (
        "folding.fold.simplefold_local",
        "folding.simplefold_confidence.simplefold_local",
    )
    environment = {
        (binding_id, "2.1.0"): {
                "values": {
                    "credential": "credential-value",
                    "device": "cpu",
                },
        }
        for binding_id in bindings
    }

    def record_admission(
        closure: SimpleFoldProviderAssetClosure,
        _environment: Mapping[str, Any],
    ) -> None:
        admissions.append(closure)

    monkeypatch.setattr(
        folding_adapter,
        "admit_simplefold_provider_asset_closure",
        record_admission,
    )
    monkeypatch.setattr(
        confidence_adapter,
        "admit_simplefold_provider_asset_closure",
        record_admission,
    )

    production_readiness = {
        bindings[0]: folding_adapter.simplefold_readiness,
        bindings[1]: confidence_adapter.simplefold_confidence_readiness,
    }

    def readiness_for(binding_id: str):
        def readiness(check_input: ReadinessCheckInput) -> ReadinessResult:
            calls.append(f"readiness:{binding_id}")
            return production_readiness[binding_id](check_input.values)

        return readiness

    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            binding_ids=bindings,
            readiness_checks={
                binding_id: readiness_for(binding_id)
                for binding_id in bindings
            },
        ),
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_independent_nodes(
            client,
            (
                "folding.fold.simplefold_local",
                "folding.fold.simplefold_local",
                "folding.simplefold_confidence.simplefold_local",
            ),
        )
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "distinct-binding-request",
            },
        )

    assert response.status_code == 202
    assert admissions == [
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
    ]
    assert calls == [
        "readiness:folding.fold.simplefold_local",
        "factory:folding.fold.simplefold_local",
        "execute:folding.fold.simplefold_local",
        "factory:folding.fold.simplefold_local",
        "execute:folding.fold.simplefold_local",
        "readiness:folding.simplefold_confidence.simplefold_local",
        "factory:folding.simplefold_confidence.simplefold_local",
        "execute:folding.simplefold_confidence.simplefold_local",
    ]


def test_failed_readiness_closes_only_the_provider_bound_node(
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
            (binding_id, "2.1.0"): {
                "values": {
                    "credential": "credential-value",
                    "api_key": secret,
                    "runtime_path": private_path,
                },
                }
            for binding_id in bindings
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_independent_nodes(client, bindings)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "failed-readiness-request",
            },
        )
        assert response.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=response.json()["run_id"],
        )
        events = app.state.run_execution_v2.public_events(
            project_id,
            response.json()["run_id"],
        )

    assert projection["status"] == "failed"
    assert {
        item["node_id"]: item["outcome"]
        for item in projection["node_dispositions"]
    } == {
        "direct-0": "succeeded",
        "direct-1": "failed",
    }
    assert calls == [
        "readiness:test.direct.local",
        "factory:test.direct.local",
        "execute:test.direct.local",
        "readiness:test.other.local",
    ]
    failed_attempt_id = next(
        message["event"]["node_attempt_id"]
        for message in events
        if message["event"]["type"] == "node_attempt_started"
        and message["event"]["node_id"] == "direct-1"
    )
    assert not any(
        message["event"]["type"] == "operation_attempt_started"
        and message["event"]["node_attempt_id"] == failed_attempt_id
        for message in events
    )
    failed_terminal = next(
        message["event"]
        for message in events
        if message["event"]["type"] == "node_attempt_terminal"
        and message["event"]["node_attempt_id"] == failed_attempt_id
    )
    assert failed_terminal["failure_origin"] == "binding"
    assert failed_terminal["error"]["code"] == "readiness_rejected"
    assert failed_terminal["error"]["retryable"] is True
    durable_evidence = b"".join(
        path.read_bytes()
        for path in (tmp_path / "runs").rglob("*.json")
    )
    assert secret.encode() not in durable_evidence
    assert private_path.encode() not in durable_evidence
    assert secret not in str(projection)
    assert private_path not in str(projection)


def test_public_run_exposes_no_node_subset_when_transaction_commit_fails(
    tmp_path,
    monkeypatch,
) -> None:
    class FailNodeConclusionTransaction:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            if _transaction_has_fact(payload, "node_disposition"):
                raise OSError("fixture evidence store failure")
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    calls: list[str] = []
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    app = create_app(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
        _v2_ledger_transaction_store=FailNodeConclusionTransaction(),
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "disposition-commit-failure",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "evidence_unavailable"
    facts = _durable_facts(tmp_path / "runs")
    assert not any(
        fact["fact_type"]
        in {
            "operation_attempt_terminal",
            "outputs_published",
            "node_attempt_terminal",
            "node_disposition",
            "run_terminal",
        }
        for fact in facts
    )
    assert not list(cache_root.rglob("*.json"))
    assert calls.count("execute:test.direct.local") == 1


def test_run_without_selection_closes_after_its_node_disposition(
    tmp_path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "no-selection-run-closure",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )

    transactions = [
        json.loads(path.read_text())
        for path in sorted(
            (run_root / project_id / run_id / "ledger").glob("*.json")
        )
    ]
    closure_index, closure = next(
        (index, transaction)
        for index, transaction in enumerate(transactions)
        if any(
            fact["fact_type"] == "run_terminal"
            for fact in transaction["facts"]
        )
    )
    disposition_index = next(
        index
        for index, transaction in enumerate(transactions)
        if any(
            fact["fact_type"] == "node_disposition"
            for fact in transaction["facts"]
        )
    )

    assert projection["status"] == "succeeded"
    assert closure_index > disposition_index
    assert [fact["fact_type"] for fact in closure["facts"]] == [
        "run_terminal"
    ]
    assert closure["facts"][0]["payload"] == {"status": "succeeded"}


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
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        project_id, compiled = _commit_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "canonical-port-boundary",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        published_values = [
            retrieve_typed_output_values(
                client,
                project_id,
                started.json()["run_id"],
                output,
            )
            for output in projection["outputs"]
        ]

    assert started.status_code == 202
    assert published_values == [
        ["ready"],
        ["ready"],
    ]
    assert "sink-input:ready" in calls
    assert "sink-input: READY " not in calls
    assert [item for item in calls if item.startswith("validate:")] == [
        "validate:' READY '",
        "validate:'ready'",
        "validate:'ready'",
        "validate:'ready'",
    ]


def test_operation_call_reuses_admitted_scientific_values_without_copy() -> None:
    candidate = Candidate(
        candidate_id="candidate-admitted",
        data=ProteinSequence("MA"),
        metadata={"source": "canonical"},
    )

    call = OperationCall(
        inputs={
            "candidate": admitted_port_fixture(
                candidate,
                port_type_id="candidate",
                value_content_digests=("sha256:" + ("a" * 64),),
            )
        },
        node_parameters={},
        binding_parameters={},
        effective_randomness={},
    )

    assert call.inputs["candidate"].value is candidate
    with pytest.raises(TypeError):
        call.inputs["other"] = candidate


def test_operation_call_exposes_ordered_candidate_data_content_digests(
    tmp_path,
) -> None:
    calls: list[str] = []
    catalog = _pipeline_catalog(
        calls,
        candidate_digest_probe=True,
    )
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("Candidate data reference runtime")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=parse_workflow_document(
            {
                "schema_version": "2.1.0",
                "workflow_id": project.id,
                "nodes": [
                    {
                        "node_id": "source",
                        "node_type_id": "test.pipeline.source",
                        "node_type_version": "2.1.0",
                        "binding_id": "test.pipeline.source.direct",
                        "binding_version": "2.1.0",
                        "node_parameters": {},
                        "binding_parameters": {},
                    },
                    {
                        "node_id": "sink",
                        "node_type_id": "test.pipeline.sink",
                        "node_type_version": "2.1.0",
                        "binding_id": "test.pipeline.sink.direct",
                        "binding_version": "2.1.0",
                        "node_parameters": {},
                        "binding_parameters": {},
                    },
                ],
                "edges": [
                    {
                        "source_node_id": "source",
                        "source_port": output_port,
                        "target_node_id": "sink",
                        "target_port": output_port,
                    }
                    for output_port in ("text", "candidates")
                ],
                "contract_lock": [],
            }
        ),
    )
    service = run_execution_v2.V2RunService(
        projects,
        catalog,
        authoring,
        run_execution_v2.EnvironmentConfiguration({}),
    )

    try:
        receipt = service.start(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="candidate-content-digest-interface",
        )
        projection = service.projection(
            project.id,
            receipt["run_id"],
        )
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded"
    assert calls.count("candidate-digests:verified") == 1


@pytest.mark.parametrize(
    "candidate_case",
    ("data", "parent", "metadata", "metadata_json_type", "identical"),
)
def test_cross_input_candidate_identity_closes_runtime_before_sink_side_effects(
    tmp_path,
    candidate_case: str,
) -> None:
    calls: list[str] = []
    cache_lookups: list[str] = []
    catalog = _pipeline_catalog(
        calls,
        cacheable=True,
        candidate_conflict_probe=True,
    )

    class ConflictingCandidateReplay(ResultReplaySource):
        def lookup(self, **kwargs: Any) -> ResultReplayHit | None:
            node = kwargs["node"]
            cache_lookups.append(node.node_id)
            if node.node_id == "sink":
                if candidate_case == "identical":
                    return None
                raise AssertionError(
                    "Candidate conflict must fail before sink cache lookup"
                )
            candidate_facts = {
                "data": {
                    "source-left": ("AA", (), {"partition": "shared"}),
                    "source-right": ("CC", (), {"partition": "shared"}),
                },
                "parent": {
                    "source-left": (
                        "AA",
                        ("candidate-parent-left",),
                        {"partition": "shared"},
                    ),
                    "source-right": (
                        "AA",
                        ("candidate-parent-right",),
                        {"partition": "shared"},
                    ),
                },
                "metadata": {
                    "source-left": ("AA", (), {"partition": "left"}),
                    "source-right": ("AA", (), {"partition": "right"}),
                },
                "metadata_json_type": {
                    "source-left": ("AA", (), {"flag": True}),
                    "source-right": ("AA", (), {"flag": 1}),
                },
                "identical": {
                    "source-left": (
                        "AA",
                        ("candidate-parent",),
                        {"partition": "shared"},
                    ),
                    "source-right": (
                        "AA",
                        ("candidate-parent",),
                        {"partition": "shared"},
                    ),
                },
            }
            sequence, parent_ids, metadata = candidate_facts[
                candidate_case
            ][node.node_id]
            return ResultReplayHit(
                result_identity=kwargs["result_identity"],
                producer_run_id="fixture-producer",
                admitted_outputs=admitted_replay_outputs(
                    catalog=catalog,
                    node=node,
                    outputs={
                        "text": node.node_id,
                        "candidates": CandidateCollection(
                            collection_id=f"collection-{node.node_id}",
                            item_type="protein.sequence",
                            items=(
                                Candidate(
                                    candidate_id="candidate-shared",
                                    data=ProteinSequence(sequence),
                                    parent_ids=parent_ids,
                                    metadata=metadata,
                                ),
                            ),
                        ),
                    },
                ),
            )

    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("cross-input Candidate conflict")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = parse_workflow_document(
        {
            "schema_version": "2.1.0",
            "workflow_id": project.id,
            "nodes": [
                {
                    "node_id": node_id,
                    "node_type_id": node_type_id,
                    "node_type_version": "2.1.0",
                    "binding_id": binding_id,
                    "binding_version": "2.1.0",
                    "node_parameters": (
                        {"source_variant": node_id}
                        if node_type_id == "test.pipeline.source"
                        else {}
                    ),
                    "binding_parameters": {},
                }
                for node_id, node_type_id, binding_id in (
                    (
                        "source-left",
                        "test.pipeline.source",
                        "test.pipeline.source.direct",
                    ),
                    (
                        "source-right",
                        "test.pipeline.source",
                        "test.pipeline.source.direct",
                    ),
                    (
                        "sink",
                        "test.pipeline.sink",
                        "test.pipeline.sink.direct",
                    ),
                )
            ],
            "edges": [
                {
                    "source_node_id": "source-left",
                    "source_port": "text",
                    "target_node_id": "sink",
                    "target_port": "text",
                },
                *(
                    {
                        "source_node_id": source_node_id,
                        "source_port": "candidates",
                        "target_node_id": "sink",
                        "target_port": "candidates",
                    }
                    for source_node_id in (
                        "source-left",
                        "source-right",
                    )
                ),
            ],
            "contract_lock": [],
        }
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    service = run_execution_v2.V2RunService(
        projects,
        catalog,
        authoring,
        run_execution_v2.EnvironmentConfiguration({}),
        ConflictingCandidateReplay(),
    )

    try:
        if candidate_case == "identical":
            receipt = service.start(
                project.id,
                workflow_commit_id=committed.workflow_commit_id,
                client_request_id="candidate-conflict",
            )
            projection = service.projection(project.id, receipt["run_id"])
            events = service.public_events(project.id, receipt["run_id"])
        else:
            with pytest.raises(
                PortValueError,
                match="Candidate identity resolves to conflicting canonical facts",
            ):
                service.start(
                    project.id,
                    workflow_commit_id=committed.workflow_commit_id,
                    client_request_id="candidate-conflict",
                )
    finally:
        service.shutdown()

    assert cache_lookups == [
        "source-left",
        "source-right",
        *(("sink",) if candidate_case == "identical" else ()),
    ]
    assert [call for call in calls if call.startswith("factory:")] == (
        ["factory:sink"] if candidate_case == "identical" else []
    )
    assert not any(call.startswith("execute:") for call in calls)
    assert [call for call in calls if call.startswith("sink-input:")] == (
        ["sink-input:source-left"]
        if candidate_case == "identical"
        else []
    )
    if candidate_case != "identical":
        assert not any(
            fact["fact_type"] == "node_attempt_started"
            and fact["payload"]["node_id"] == "sink"
            for fact in _durable_facts(tmp_path)
        )
        assert not any(
            fact["fact_type"] == "operation_attempt_started"
            for fact in _durable_facts(tmp_path)
        )
        return

    sink_started = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_started"
        and item["event"]["node_id"] == "sink"
    )
    sink_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
        and item["event"]["node_attempt_id"]
        == sink_started["node_attempt_id"]
    )
    sink_disposition = next(
        item["event"]["disposition"]
        for item in events
        if item["event"]["type"] == "node_disposition"
        and item["event"]["disposition"]["node_id"] == "sink"
    )
    run_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "run_terminal"
    )
    assert projection["status"] == "succeeded"
    assert sink_terminal["status"] == "succeeded"
    assert sink_disposition["outcome"] == "succeeded"
    assert run_terminal["status"] == "succeeded"
    assert sum(
        item["event"]["type"] == "operation_attempt_started"
        for item in events
    ) == 1


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
        project_id, compiled = _commit_pipeline(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
    durable_facts = _durable_facts(tmp_path / "runs")
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
        frozen_catalog_override=_artifact_catalog(
            [],
            artifact_kind=None,
            collection=True,
            artifact_payloads=(),
        )
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_artifact_node(client)
        response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "artifact-without-opt-in",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            response.json()["run_id"],
        )
        events = client.app.state.run_execution_v2.public_events(
            project_id,
            response.json()["run_id"],
        )

    assert response.status_code == 202
    assert projection["status"] == "failed"
    assert projection["artifact_index"] == []
    operation_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert operation_terminal["status"] == "failed"
    assert node_terminal["failure_origin"] == "operation"


def test_artifact_object_write_failure_publishes_no_node_values(
    tmp_path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "outputs"
    original_put = run_execution_v2.ProjectObjectStore.put_exact

    def fail_artifact_put(store, project_id, payload):
        if payload == b"MODEL        1\nEND\n":
            raise OSError("fixture Artifact object write failure")
        return original_put(store, project_id, payload)

    monkeypatch.setattr(
        run_execution_v2.ProjectObjectStore,
        "put_exact",
        fail_artifact_put,
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    app = create_app(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, committed = _commit_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "artifact-object-write-failure",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        events = client.app.state.run_execution_v2.public_events(
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "failed"
    assert projection["artifact_index"] == []
    assert projection["outputs"] == []
    operation_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert operation_terminal["status"] == "succeeded"
    assert node_terminal["failure_origin"] == "publication"
    publication_error = dict(node_terminal["error"])
    assert publication_error.pop("correlation_id").startswith("incident-")
    assert publication_error == {
        "code": "node_publication_failed",
        "message": "Node result publication failed",
        "retryable": False,
        "details": {
            "node_id": "artifact",
            "publication_stage": "artifact_object",
        },
    }
    assert not any(
        fact["fact_type"] in {"artifact_published", "outputs_published"}
        for fact in _durable_facts(tmp_path / "runs")
    )
    assert not list(output_root.rglob("objects/v1/sha256/*/*"))
    assert not list(output_root.rglob("published/*"))


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
        project_id, compiled = _commit_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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


@pytest.mark.parametrize("candidate_id", ("a/b", "a:b", "a+b"))
def test_candidate_artifact_identifier_is_metadata_not_a_storage_path(
    tmp_path,
    monkeypatch,
    candidate_id: str,
) -> None:
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    app = create_app(
        frozen_catalog_override=_artifact_catalog(
            [],
            artifact_kind="candidate",
            artifact_candidate_id=candidate_id,
        )
    )

    with TestClient(app) as client:
        project_id, committed = _commit_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "candidate-artifact-identifier",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert len(projection["artifact_index"]) == 1
    descriptor = projection["artifact_index"][0]
    assert descriptor["candidate_id"] == candidate_id
    assert descriptor["artifact_reference"].startswith("artifact-")
    assert candidate_id not in descriptor["artifact_reference"]
    stored = _object_path(
        output_root,
        project_id,
        descriptor["content_digest"],
    )
    assert stored.read_bytes() == b"MODEL        1\nEND\n"
    assert not list(output_root.rglob("published/*"))


@pytest.mark.parametrize("candidate_id", ("候选", "a" * 129))
def test_invalid_candidate_artifact_identifier_leaves_no_stored_payload(
    tmp_path,
    monkeypatch,
    candidate_id: str,
) -> None:
    output_root = tmp_path / "outputs"
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    app = create_app(
        frozen_catalog_override=_artifact_catalog(
            [],
            artifact_kind="candidate",
            artifact_candidate_id=candidate_id,
        )
    )

    with TestClient(app) as client:
        project_id, committed = _commit_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed["workflow_commit_id"],
                "client_request_id": "invalid-candidate-artifact-identifier",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "failed"
    assert projection["artifact_index"] == []
    assert list(output_root.rglob("objects/v1/sha256/*/*")) == []
    assert not any(
        fact["fact_type"] == "artifact_published"
        for fact in _durable_facts(run_root)
    )


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
        project_id, compiled = _commit_artifact_node(client)
        count_response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        fact["fact_type"] == "artifact_published"
        for fact in _durable_facts(tmp_path / "runs")
    )
    assert next(
        fact for fact in _durable_facts(tmp_path / "runs")
        if fact["fact_type"] == "operation_attempt_terminal"
    )["payload"]["status"] == "failed"

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
        project_id, compiled = _commit_artifact_node(client)
        aggregate_response = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        fact["fact_type"] == "artifact_published"
        for fact in _durable_facts(aggregate_root)
    ) == 0
    unreferenced_objects = list(
        (tmp_path / "outputs").rglob("objects/v1/sha256/*/*")
    )
    assert unreferenced_objects == []
    assert next(
        fact for fact in _durable_facts(aggregate_root)
        if fact["fact_type"] == "operation_attempt_terminal"
    )["payload"]["status"] == "failed"
    assert not list((tmp_path / "outputs").rglob("published/*"))


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
        project_id, compiled = _commit_artifact_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
        assert artifact["filename"] == "result-0.pdb"
        assert artifact["content_digest"] == (
            "sha256:"
            + hashlib.sha256(b"MODEL        1\nEND\n").hexdigest()
        )
        assert client.app.state.run_execution_v2._object_store.read(
            project_id,
            artifact["content_digest"],
        ) == b"MODEL        1\nEND\n"
        assert not (output_root / project_id / run_id / "published").exists()

        downloaded = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}/artifacts/"
            f"{artifact['artifact_reference']}"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"MODEL        1\nEND\n"
        assert downloaded.headers["digest"] == artifact["content_digest"]
        assert downloaded.headers["content-type"] == "chemical/x-pdb"
        assert downloaded.headers["content-length"] == str(artifact["size"])
        assert downloaded.headers["content-disposition"] == (
            artifact_content_disposition(artifact["filename"])
        )

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
    transactions = [json.loads(path.read_text()) for path in fact_paths]
    facts = _durable_facts(run_root)
    assert [
        transaction["transaction_sequence"] for transaction in transactions
    ] == list(range(1, len(transactions) + 1))
    assert all(
        transaction["schema_namespace"]
        == "protein-workbench-run-ledger-transaction/v4"
        and transaction["schema_version"] == "4.0.0"
        for transaction in transactions
    )
    assert [fact["sequence"] for fact in facts] == list(
        range(1, len(facts) + 1)
    )
    assert {
        "availability_bound",
        "engine_invocation_started",
    } <= {fact["fact_type"] for fact in facts}
    node_transaction = next(
        transaction
        for transaction in transactions
        if any(
            fact["fact_type"] == "node_disposition"
            for fact in transaction["facts"]
        )
    )
    assert [
        fact["fact_type"] for fact in node_transaction["facts"]
    ] == [
        "operation_attempt_terminal",
        "outputs_published",
        "artifact_published",
        "node_attempt_terminal",
        "node_disposition",
    ]
    assert calls == ["workspace:True"]
    assert not any((run_root / project_id / run_id / "temp").rglob("*"))


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
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }

    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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


def test_restart_rejects_an_inactive_catalog_generation_without_rewriting_ledger(
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
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    original_catalog = _direct_catalog(
        [],
        execution_gate=(entered, release),
        node_title="Original Catalog generation",
    )
    active_catalog = _direct_catalog(
        [],
        node_title="Active Catalog generation",
    )
    assert original_catalog.contract_digest != active_catalog.contract_digest

    try:
        with TestClient(
            create_app(
                frozen_catalog_override=original_catalog,
                v2_environment_configuration=environment,
                _v2_wait_for_workers_on_shutdown=False,
            )
        ) as first:
            project_id, compiled = _commit_one_node(first)
            started = first.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_commit_id": compiled["workflow_commit_id"],
                    "client_request_id": "inactive-generation-restart",
                },
            )
            assert started.status_code == 202
            assert entered.wait(timeout=1)
            run_id = started.json()["run_id"]

        ledger_dir = run_root / project_id / run_id / "ledger"
        before = {
            path.name: path.read_bytes()
            for path in sorted(ledger_dir.glob("*.json"))
        }

        with TestClient(
            create_app(
                frozen_catalog_override=active_catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted:
            rejected = restarted.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            )

        after = {
            path.name: path.read_bytes()
            for path in sorted(ledger_dir.glob("*.json"))
        }
    finally:
        release.set()

    assert rejected.status_code == 409
    validate_error(rejected.json(), status=409)
    assert rejected.json()["error"]["code"] == "inactive_generation"
    assert rejected.json()["error"]["details"] == {
        "artifact_kind": "run_evidence",
        "expected_catalog_contract_digest": active_catalog.contract_digest,
        "received_catalog_contract_digest": original_catalog.contract_digest,
    }
    assert before == after


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
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started_at = time.monotonic()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_a, compiled_a = _commit_one_node(client)
        project_b, compiled_b = _commit_one_node(client)
        project_c, compiled_c = _commit_one_node(client)

        def start(project_id: str, workflow_commit_id: str, request_id: str):
            return client.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_commit_id": workflow_commit_id,
                    "client_request_id": request_id,
                },
            )

        first = start(project_a, compiled_a["workflow_commit_id"], "serial-a")
        assert first.status_code == 202
        assert entered.wait(timeout=1)
        second = start(project_b, compiled_b["workflow_commit_id"], "serial-b")
        assert second.status_code == 202
        assert calls.count("execute:test.direct.local") == 1

        same_project = start(
            project_a,
            compiled_a["workflow_commit_id"],
            "serial-a-conflict",
        )
        at_capacity = start(
            project_c,
            compiled_c["workflow_commit_id"],
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
            compiled_c["workflow_commit_id"],
            "serial-closed",
        )
        assert after_shutdown.status_code == 503
        validate_error(after_shutdown.json(), status=503)


def test_restart_marks_unfinished_run_interrupted_without_guessing_attempts(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    catalog = _direct_catalog(
        [],
        execution_gate=(entered, release),
    )
    environment = {
        ("test.direct.local", "2.1.0"): {
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
            project_id, compiled = _commit_one_node(first)
            started = first.post(
                f"/api/v2/projects/{project_id}/runs",
                json={
                    "workflow_commit_id": compiled["workflow_commit_id"],
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

    assert projection["status"] == "interrupted"
    assert projection["node_dispositions"] == []
    assert projection["outputs"] == []
    assert projection["artifact_index"] == []
    assert reconciled_events[:-1] == before_events
    assert reconciled_events[-1]["event"] == {
        "type": "run_terminal",
        "status": "interrupted",
    }
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
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_a, compiled_a = _commit_one_node(client)
        started_a = client.post(
            f"/api/v2/projects/{project_a}/runs",
            json={
                "workflow_commit_id": compiled_a["workflow_commit_id"],
                "client_request_id": "cursor-a",
            },
        ).json()
        project_b, compiled_b = _commit_one_node(client)
        started_b = client.post(
            f"/api/v2/projects/{project_b}/runs",
            json={
                "workflow_commit_id": compiled_b["workflow_commit_id"],
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
    original_replace = run_execution_v2.replace_file
    fail_terminal_lifecycle = {"pending": True}

    def replace_projection(root, relative_parts, payload):
        if (
            relative_parts[-1] == "lifecycle.jsonl"
            and fail_terminal_lifecycle["pending"]
            and b'"type":"run_terminal"' in payload
        ):
            fail_terminal_lifecycle["pending"] = False
            raise OSError("fixture projection failure")
        return original_replace(
            root,
            relative_parts,
            payload,
        )

    monkeypatch.setattr(
        run_execution_v2,
        "replace_file",
        replace_projection,
    )
    catalog = _direct_catalog([])
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    with TestClient(
        create_app(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
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
