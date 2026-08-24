"""Public-seam contracts for readiness-gated v2 direct execution."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
import time
from typing import Any, Literal, Mapping

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.execution.resources import CancellationControl, RunResources
from core.execution.results.store import ResultIntegrityError, ResultStore
import core.execution.node_attempt as node_attempt
from core.execution._run_runtime_evidence import (
    _exact_contract_reference,
    _execution_plan_contract_roots,
    plan_evidence,
)
from core.execution.ledger import (
    AvailabilityBound,
    FilesystemLedgerStore,
    Ledger,
    NodeAttemptTerminal,
    NodeDisposition,
    OperationAttemptTerminal,
    RunAdmitted,
    RunScopeBinding,
    RunStarted,
    V2RunError,
    run_timestamp,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.declarations import (
    AvailabilityResult,
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.model import (
    CatalogContract,
    FrozenCatalog,
)
from core.catalog.errors import PortValueError
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.operation import (
    ArtifactPayload,
    OperationCall,
    OperationContext,
    BindingEnvironment,
    ReadinessResult,
    ResolvedOutputIdentity,
)
from core.parameters.contract import admit_declarations
from core.execution.node_attempt import ExecutionTermination
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.support.application import create_application
import core.execution.runtime as run_runtime
from core.execution.environment import admit_environment_configuration
from tests.support.output_admission import admit_fixture_port
from tests.support.result_store import result_store
from tests.support.catalog import (
    binding_availability,
    catalog_contract,
    install_runtime,
)
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from core.workflow.plan import ExecutionPlanNode
from protein_workbench_public.ledger_codec import encode_event
from protein_workbench_public.workflow_codec import decode_workflow_document
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.sequence import ProteinSequence
from protein_workbench_public.protocol import (
    artifact_content_disposition,
)
from tests.support.protocol import (
    validate_error,
    validate_response,
)
from protein_workbench_public.protocol import validate_schema
from tests.fixtures.public_v2 import (
    retrieve_typed_output_values,
    wait_for_testclient_run_terminal,
)
from tests.fixtures.scientific_operation import admitted_port_fixture


def _transaction_has_fact(payload: bytes, fact_type: str) -> bool:
    transaction = json.loads(payload)
    return any(
        fact["fact_type"] == fact_type for fact in transaction["facts"]
    )


def _public_events(runtime, project_id: str, run_id: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        encode_event(
            project_id=project_id,
            run_id=run_id,
            fact=fact,
        )
        for fact in runtime.events(project_id, run_id)
    )


def _durable_facts(root) -> list[dict[str, Any]]:
    return [
        fact
        for path in sorted(root.rglob("ledger/*.json"))
        for fact in json.loads(path.read_text())["facts"]
    ]


def _contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict[str, Any],
    *,
    environment_fields: tuple[EnvironmentFieldDeclaration, ...] | None = None,
) -> CatalogContract:
    return catalog_contract(
        contract_kind,
        contract_id,
        "2.1.0",
        {
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            "contract_version": "2.1.0",
            **descriptor,
        },
        environment_fields=(
            environment_fields
            if environment_fields is not None
            else (
                (EnvironmentFieldDeclaration("credential", "credential_handle"),)
                if contract_kind == "binding"
                else ()
            )
        ),
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
        _cancellation_control=CancellationControl(),
    )

    with pytest.raises(TypeError, match="engine_identity"):
        with resources.engine_invocation(
            engine_identity="sha256:" + "1" * 64,
        ):  # type: ignore[call-arg]
            pass
    assert recorded == []


def test_local_provider_memory_retains_only_the_active_provider_state() -> None:
    from core.execution.resources import LocalProviderMemory

    memory = LocalProviderMemory()
    with memory.use("first") as first:
        first["model"] = object()
    with memory.use("first") as retained:
        assert retained is first
        assert retained["model"] is first["model"]
    with memory.use("second") as second:
        assert first == {}
        assert second == {}
        second["model"] = object()

    memory.release()
    assert second == {}


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
    execution_output: Any = "READY",
    implementation_variant: str = "default",
    implementation_label: str | None = None,
    deterministic: bool = True,
    execution_route: Literal["adapter", "direct"] = "adapter",
    node_parameter_declarations: Mapping[str, Any] | None = None,
    node_title: str = "Deterministic direct test Node",
    effective_randomness_parameters: tuple[str, ...] = (),
    effective_randomness_resolver: EffectiveRandomnessResolver | None = None,
    output_method_projection: Literal["binding", "other"] | None = None,
    binding_environment_fields: tuple[
        EnvironmentFieldDeclaration,
        ...,
    ] = (),
) -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
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
    text = builtin.require_port_type("text", "2.1.0")
    catalog_port_types = builtin.port_types
    if output_method_projection is not None:
        producing_method = ExactContractReference(**method.reference())
        projected_method = (
            producing_method
            if output_method_projection == "binding"
            else replace(
                producing_method,
                contract_id="test.other.method",
            )
        )
        text = PortTypeDefinition(
            type_id="test.method_observation",
            version="2.1.0",
            validator=BehaviorReference(
                "test.method_observation/validate",
                "2.1.0",
                {},
            ),
            codec=BehaviorReference(
                "test.method_observation/codec",
                "2.1.0",
                {},
            ),
            content_identity=BehaviorReference(
                "test.method_observation/content",
                "2.1.0",
                {},
            ),
            runtime_validator=lambda value: None,
            runtime_to_wire=lambda value: value,
            runtime_from_wire=lambda value: value,
            observation_method_projection=BehaviorReference(
                "test.method_observation/method_projection",
                "2.1.0",
                {},
            ),
            runtime_observation_method_projection=lambda _: (
                projected_method,
            ),
        )
        catalog_port_types = (*builtin.port_types, text)
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
            environment_fields=(
                EnvironmentFieldDeclaration(
                    "credential",
                    "credential_handle",
                ),
                *binding_environment_fields,
            ),
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
                check_input: BindingEnvironment,
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
                passing = exact_binding_id != failing_binding_id
                return ReadinessResult(
                    passing,
                    reason_code=(
                        None if passing else "fixture_readiness_rejected"
                    ),
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
        catalog_port_types,
        contracts=install_runtime(
            (method, node_type, *bindings),
            factories=factories,
            readiness=readiness_declarations,
            randomness=(
                {
                    (binding_id, "2.1.0"): effective_randomness_resolver
                    for binding_id in binding_ids
                }
                if effective_randomness_resolver is not None
                else {}
            ),
        ),
        availability=tuple(
            (
                binding_availability(
                    binding,
                    observed_at,
                    result=AvailabilityResult.unavailable(
                        code="provider_unavailable",
                        message="Provider is unavailable",
                        retryable=False,
                    ),
                )
                if binding.contract_id in unavailable_binding_ids
                else binding_availability(binding, observed_at)
            )
            for binding in bindings
        ),
        availability_observed_at=observed_at,
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
    optional_sink_input: bool = False,
    cacheable: bool = False,
    candidate_digest_probe: bool = False,
    execution_gates: (
        Mapping[str, tuple[threading.Event, threading.Event]] | None
    ) = None,
) -> FrozenCatalog:
    include_candidate_data = candidate_digest_probe
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
        if type(value) is not str or value != value.strip().lower():
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
            {"normalization": "strip-and-lowercase"},
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
    observed_at = datetime(2026, 7, 29, 8, tzinfo=timezone.utc)

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
                    "text": 17 if invalid_source_output else "ready"
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
                    text_record.port_type.contract_id
                    == "test.canonical_text"
                )
                assert len(text_record.value_content_digests) == 1
            if include_candidate_data:
                candidate_record = call.inputs["candidates"]
                candidates = candidate_record.value
                candidate_values = tuple(candidates.items)
                assert (
                    candidate_record.port_type.contract_id
                    == "candidate.collection"
                )
                assert len(candidate_record.value_content_digests) == 1
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
                    else "optional"
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
            if implementation is SourceImplementation:
                node_id = context.resources.node_id
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
            binding_availability(binding, observed_at)
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
        contracts=install_runtime(
            tuple(contracts),
            factories=factories,
            readiness=readiness,
        ),
        availability=tuple(availability),
        availability_observed_at=observed_at,
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
        contracts=install_runtime(
            (method, node, binding),
            factories={
                ("test.artifact.direct", "2.1.0"): ScientificOperationFactory(
                    behavior=factory_behavior,
                    build=factory,
                )
            },
            readiness={
                ("test.artifact.direct", "2.1.0"): ReadinessDeclaration(
                    behavior=readiness_behavior,
                    prerequisites={},
                    check=lambda check_input: ReadinessResult(True),
                )
            },
        ),
        availability=(binding_availability(binding, observed_at),),
        availability_observed_at=observed_at,
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
    app = create_application(
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
    app = create_application(
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
    app = create_application(
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
        events = _public_events(
            app.state.run_runtime,
            project_id,
            run_id,
        )

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


def test_cache_miss_fails_at_an_unavailable_binding_without_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
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
        events = _public_events(
            app.state.run_runtime,
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
    app = create_application(
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
        events = _public_events(
            app.state.run_runtime,
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


def test_preparation_error_emits_no_attempt_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fail_randomness(**_kwargs: Any) -> Mapping[str, Any]:
        calls.append("randomness")
        raise RuntimeError("fixture randomness resolution failed")

    def fail_readiness(_check_input: BindingEnvironment) -> ReadinessResult:
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
    app = create_application(
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
        assert started.status_code == 202
        with pytest.raises(V2RunError) as unavailable:
            wait_for_testclient_run_terminal(
                client,
                project_id,
                started.json()["run_id"],
            )
        events = _public_events(
            app.state.run_runtime,
            project_id,
            started.json()["run_id"],
        )

    assert unavailable.value.code == "evidence_unavailable"
    assert not any(
        fact["fact_type"]
        in {
            "node_attempt_started",
            "operation_attempt_started",
            "readiness_attested",
            "engine_invocation_started",
            "node_attempt_terminal",
            "node_disposition",
        }
        for fact in _durable_facts(tmp_path / "runs")
    )
    assert not any(
        item["event"]["type"].startswith("node_")
        for item in events
    )
    assert calls == ["randomness"]


def test_readiness_programming_error_fails_after_attempt_start(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def invalid_readiness(
        _check_input: BindingEnvironment,
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
    app = create_application(
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
        assert started.status_code == 202
        with pytest.raises(V2RunError) as unavailable:
            wait_for_testclient_run_terminal(
                client,
                project_id,
                started.json()["run_id"],
            )
        events = _public_events(
            app.state.run_runtime,
            project_id,
            started.json()["run_id"],
        )

    assert unavailable.value.code == "evidence_unavailable"
    terminal = next(
        item["event"]
        for item in events
        if item["event"]["type"] == "node_attempt_terminal"
    )
    assert terminal["failure_origin"] == "attempt"
    assert terminal["error"]["code"] == "node_execution_failed"
    assert terminal["error"]["details"]["exception_type"] == "RuntimeError"
    assert calls == ["readiness"]
    fact_types = [
        fact["fact_type"] for fact in _durable_facts(tmp_path / "runs")
    ]
    assert fact_types.count("node_attempt_started") == 1
    assert "readiness_attested" not in fact_types
    assert "operation_attempt_started" not in fact_types
    assert "engine_invocation_started" not in fact_types
    assert fact_types.count("node_attempt_terminal") == 1
    assert "node_disposition" in fact_types
    assert "run_terminal" not in fact_types


def test_result_store_preoperation_failure_retains_typed_run_closure(
    tmp_path,
    monkeypatch,
) -> None:
    def fail_replay(
        _store: ResultStore,
        **_kwargs: Any,
    ) -> None:
        raise ResultIntegrityError("sha256:" + "7" * 64)

    monkeypatch.setattr(ResultStore, "lookup_replay", fail_replay)
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
    app = create_application(
        frozen_catalog_override=_direct_catalog([], cacheable=True),
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
                "client_request_id": "result-store-preoperation-failure",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        events = _public_events(
            app.state.run_runtime,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "failed"
    assert projection["node_dispositions"][0]["outcome"] == "failed"
    node_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
    )
    assert node_terminal["failure_origin"] == "attempt"
    assert node_terminal["error"]["details"] == {
        "exception_type": "ResultIntegrityError",
    }
    assert not any(
        event["event"]["type"] == "operation_attempt_started"
        for event in events
    )


def test_late_worker_failure_gates_every_lifecycle_use_case_and_restart(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fail_after_receipt(
        _check_input: BindingEnvironment,
    ) -> ReadinessResult:
        calls.append("readiness")
        entered.set()
        assert release.wait(timeout=3)
        raise RuntimeError("private delayed worker failure")

    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    catalog = _direct_catalog(
        calls,
        readiness_checks={"test.direct.local": fail_after_receipt},
    )
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "late-worker-failure",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        assert entered.wait(timeout=2)
        assert app.state.run_runtime.projection(project_id, run_id).status == (
            "running"
        )

        release.set()
        app.state.run_runtime.shutdown()

        lifecycle_calls = (
            lambda: app.state.run_runtime.projection(project_id, run_id),
            lambda: app.state.run_runtime.replay(project_id, run_id, None),
            lambda: app.state.run_runtime.wait_for_events(
                project_id,
                run_id,
                0,
                timeout_seconds=0.1,
            ),
            lambda: app.state.run_runtime.cancel(
                project_id,
                run_id,
                after_cursor=None,
            ),
            lambda: app.state.run_runtime.start_derived_background(
                project_id,
                source_run_id=run_id,
                policy="retry_failed",
                node_ids=["direct"],
                client_request_id="derived-after-worker-failure",
            ),
        )
        for use_case in lifecycle_calls:
            with pytest.raises(V2RunError) as unavailable:
                use_case()
            assert unavailable.value.code == "evidence_unavailable"

        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            unavailable_message = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()

    assert unavailable_message["error"]["code"] == "evidence_unavailable"
    assert closed.value.code == 1008
    facts_before_restart = _durable_facts(run_root)
    assert not any(
        fact["fact_type"] == "run_terminal"
        for fact in facts_before_restart
    )
    assert calls == ["readiness"]

    for _ in range(2):
        restarted = create_application(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
        with TestClient(restarted) as client:
            projection = client.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            )
            assert projection.status_code == 200
            assert projection.json()["status"] == "interrupted"

    assert sum(
        fact["fact_type"] == "run_terminal"
        and fact["payload"] == {"status": "interrupted"}
        for fact in _durable_facts(run_root)
    ) == 1


def test_public_terminal_wait_helper_never_returns_a_running_projection(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    projections: list[dict[str, Any]] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
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
    app = create_application(
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
        events = _public_events(
            app.state.run_runtime,
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
    app = create_application(
        frozen_catalog_override=_direct_catalog(calls),
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
    catalog = _direct_catalog(calls)
    environment_configuration = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
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
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration=environment_configuration,
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        projects = app.state.project_manager
        compiled = app.state.workflow_authoring.require_verified_commit(
            project_id,
            workflow_commit_id=committed["workflow_commit_id"],
        )
        plan = compiled.execution_plan
        node = plan.nodes[0]
        run_id = "run-attempt-interface"
        contract_roots = tuple(
            _execution_plan_contract_roots(plan)
        )
        resolved_contracts = tuple(
            _exact_contract_reference(entry)
            for entry in plan.resolved_contracts
        )
        ledger = Ledger(
            projects,
            project_id,
            run_id,
            plan_evidence(plan),
            None,
        )
        ledger.record(
            RunScopeBinding(
                workflow_commit_id=committed["workflow_commit_id"],
                workflow_commit_revision=plan.workflow_commit_revision,
                workflow_digest=plan.workflow_digest,
                contract_lock_digest=plan.contract_lock_digest,
                execution_plan_digest=plan.execution_plan_digest,
                catalog_contract_digest=plan.catalog_contract_digest,
                resolved_contracts=resolved_contracts,
                resolved_contract_roots=contract_roots,
            )
        )
        availability = catalog.require_availability(
            _exact_contract_reference(node.binding)
        )
        ledger.record(
            AvailabilityBound(
                binding=_exact_contract_reference(
                    node.binding
                ),
                catalog_observed_at=run_timestamp(availability.observed_at),
                available=availability.result.is_available,
            )
        )
        ledger.record(
            RunAdmitted(
                workflow_commit_id=committed["workflow_commit_id"],
                workflow_commit_revision=plan.workflow_commit_revision,
            )
        )
        ledger.record(
            RunStarted(
                started_at="2026-08-21T00:00:00Z",
            )
        )
        attempt_results = result_store(projects)
        attempts = node_attempt.NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                environment_configuration,
            ),
            attempt_results,
        ).create(
            ledger=ledger,
            availability_by_binding={
                (
                    node.binding.contract_id,
                    node.binding.contract_version,
                ): availability,
            },
        )

        outcome = attempts.execute(
            node_attempt.AttemptSpec(
                project_id=project_id,
                run_id=run_id,
                node=node,
                candidate_data_port_types=(
                    plan._runtime.candidate_data_port_types
                ),
                committed_values={},
                cancellation=CancellationControl(),
                cache_bypassed=False,
            )
        )

    assert outcome.disposition == "succeeded"
    assert outcome.admitted_outputs[("direct", "text")].value == "READY"
    assert [type(event.payload) for event in ledger.events()[-3:]] == [
        OperationAttemptTerminal,
        NodeAttemptTerminal,
        NodeDisposition,
    ]


def test_run_accepts_output_method_projected_by_its_binding(
    tmp_path,
    monkeypatch,
) -> None:
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
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            output_method_projection="binding",
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
                "client_request_id": "matching-output-method",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert projection["node_dispositions"][0]["outcome"] == "succeeded"


def test_run_rejects_output_method_not_owned_by_its_binding(
    tmp_path,
    monkeypatch,
) -> None:
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
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            output_method_projection="other",
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
                "client_request_id": "mismatched-output-method",
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=run_id,
        )
        events = _public_events(
            app.state.run_runtime,
            project_id,
            run_id,
        )

    assert projection["status"] == "failed"
    assert projection["node_dispositions"][0]["outcome"] == "failed"
    operation_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
    )
    assert operation_terminal["status"] == "failed"
    assert node_terminal["failure_origin"] == "operation"


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
    app = create_application(
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
            "get_port_type",
            "require_contract",
            "require_port_type",
            "require_reference",
            "resolve_contract_closure",
        ):
            monkeypatch.setattr(
                FrozenCatalog,
                method_name,
                forbid_execution_lookup,
            )

        receipt = app.state.run_runtime.start(
            project_id,
            workflow_commit_id=compiled["workflow_commit_id"],
            client_request_id="resolved-plan-only",
        )
        projection = app.state.run_runtime.projection(
            project_id,
            receipt["run_id"],
        )

    assert projection.status == "succeeded"
    assert len(randomness_calls) == 1
    assert randomness_calls[0]["node_parameters"] == {"seed": 5}
    assert calls == [
        "readiness:test.direct.local",
        "factory:test.direct.local",
        "parameters:{'seed': 17}",
        "randomness:{'seed': 17}",
        "execute:test.direct.local",
    ]


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
        def readiness(check_input: BindingEnvironment) -> ReadinessResult:
            calls.append(f"readiness:{binding_id}")
            return production_readiness[binding_id](check_input.values)

        return readiness

    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            binding_ids=bindings,
            binding_environment_fields=(
                EnvironmentFieldDeclaration("device", "json_value"),
            ),
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
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            binding_ids=bindings,
            failing_binding_id="test.other.local",
            binding_environment_fields=(
                EnvironmentFieldDeclaration(
                    "api_key",
                    "credential_handle",
                ),
                EnvironmentFieldDeclaration(
                    "runtime_path",
                    "filesystem_path",
                ),
            ),
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
        events = _public_events(
            app.state.run_runtime,
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
            self.filesystem = FilesystemLedgerStore()

        def read_transactions(self, *, root, relative_parts):
            return self.filesystem.read_transactions(
                root=root,
                relative_parts=relative_parts,
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
    app = create_application(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
        ledger_transaction_store=FailNodeConclusionTransaction(),
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "disposition-commit-failure",
            },
        )
        assert started.status_code == 202
        app.state.run_runtime.shutdown()
        response = client.get(
            f"/api/v2/projects/{project_id}/runs/{started.json()['run_id']}"
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
    app = create_application(
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
        RunResources,
        "cleanup_temporary_work",
        fail_cleanup,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
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
        events = _public_events(
            app.state.run_runtime,
            project_id,
            run_id,
        )

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
    for event in events:
        if event["event"]["type"] in {
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }:
            assert event["event"]["error"]["details"] == {
                "exception_type": "PermissionError",
            }
    retained = b"".join(
        path.read_bytes()
        for path in (tmp_path / "runs").rglob("*.json")
    )
    assert secret.encode() not in retained
    assert secret not in json.dumps(events)


def test_operation_failure_retains_ordered_workspace_cleanup_causality(
    tmp_path,
    monkeypatch,
) -> None:
    primary_secret = "private-operation-primary"
    cleanup_secret = "private-workspace-cleanup"

    def fail_operation(_resources) -> None:
        raise RuntimeError(primary_secret)

    def fail_cleanup(_resources) -> None:
        raise PermissionError(cleanup_secret)

    monkeypatch.setattr(
        RunResources,
        "cleanup_temporary_work",
        fail_cleanup,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=fail_operation,
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
                "client_request_id": "dual-operation-cleanup-failure",
            },
        )
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        events = _public_events(
            app.state.run_runtime,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "failed"
    terminals = {
        event["event"]["type"]: event["event"]
        for event in events
        if event["event"]["type"] in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    }
    assert terminals["engine_invocation_terminal"]["status"] == "failed"
    assert terminals["engine_invocation_terminal"]["error"]["details"] == {
        "exception_type": "RuntimeError",
    }
    for event_type in (
        "operation_attempt_terminal",
        "node_attempt_terminal",
    ):
        assert terminals[event_type]["status"] == "failed"
        assert terminals[event_type]["error"]["details"] == {
            "exception_type": "RuntimeError",
            "cleanup_exception_types": ["PermissionError"],
        }
    retained = b"".join(
        path.read_bytes() for path in (tmp_path / "runs").rglob("*.json")
    )
    public = json.dumps(events)
    assert primary_secret.encode() not in retained
    assert cleanup_secret.encode() not in retained
    assert primary_secret not in public
    assert cleanup_secret not in public


def test_connected_ports_publish_and_consume_only_canonical_validated_values(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(frozen_catalog_override=_pipeline_catalog(calls))

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
        workflow=decode_workflow_document(
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
    service = run_runtime.V2RunService(
        projects,
        catalog,
        authoring,
        node_attempt.NodeAttemptFactory(
            projects,
            admit_environment_configuration(catalog, {}),
            result_store(projects),
        ),
        result_store(projects),
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

    assert projection.status == "succeeded"
    assert calls.count("candidate-digests:verified") == 1


def test_invalid_output_never_publishes_success_or_a_public_result(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
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


def test_artifact_port_without_publication_intent_remains_an_ordinary_output(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
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
        events = _public_events(
            client.app.state.run_runtime,
            project_id,
            response.json()["run_id"],
        )

    assert response.status_code == 202
    assert projection["status"] == "succeeded"
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
    assert operation_terminal["status"] == "succeeded"
    assert node_terminal["status"] == "succeeded"


def test_artifact_object_write_failure_publishes_no_node_values(
    tmp_path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "outputs"
    original_store = ProjectObjectStore.store

    def fail_artifact_put(store, project_id, payload):
        if payload == b"MODEL        1\nEND\n":
            raise OSError("fixture Artifact object write failure")
        return original_store(store, project_id, payload)

    monkeypatch.setattr(
        ProjectObjectStore,
        "store",
        fail_artifact_put,
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    app = create_application(frozen_catalog_override=_artifact_catalog([]))

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
        events = _public_events(
            client.app.state.run_runtime,
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
        fact["fact_type"] == "outputs_published"
        for fact in _durable_facts(tmp_path / "runs")
    )
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
    app = create_application(
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
    app = create_application(
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
        artifact_reference = projection["artifact_index"][0][
            "artifact_reference"
        ]
        downloaded = client.get(
            f"/api/v2/projects/{project_id}/runs/{started.json()['run_id']}"
            f"/artifacts/{artifact_reference}"
        )

    assert projection["status"] == "succeeded"
    assert len(projection["artifact_index"]) == 1
    descriptor = projection["artifact_index"][0]
    assert descriptor["candidate_id"] == candidate_id
    assert descriptor["artifact_reference"].startswith("artifact-")
    assert candidate_id not in descriptor["artifact_reference"]
    assert downloaded.status_code == 200
    assert downloaded.content == b"MODEL        1\nEND\n"
    assert not list(output_root.rglob("published/*"))


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
    app = create_application(frozen_catalog_override=_artifact_catalog(calls))

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
        == "protein-workbench-run-ledger-transaction/v5"
        and transaction["schema_version"] == "5.0.0"
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
        create_application(
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
        before_events = _public_events(
            client.app.state.run_runtime,
            project_id,
            run_id,
        )
        resume_cursor = before_events[3]["cursor"]

    with TestClient(
        create_application(
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


def test_catalog_resolves_output_identity_source_contract_closure() -> None:
    source_port = builtin_frozen_catalog().require_port_type("text", "2.1.0")
    materializer = BehaviorReference(
        "test.restart-identity/materialize",
        "1.0.0",
        {"source_roles": {"source": source_port.reference()}},
    )
    identity_port = PortTypeDefinition(
        type_id="test.restart-identity",
        version="1.0.0",
        validator=BehaviorReference(
            "test.restart-identity/validate",
            "1.0.0",
            {
                "output_identity_materialization": (
                    materializer.descriptor()
                )
            },
        ),
        codec=BehaviorReference(
            "test.restart-identity/codec",
            "1.0.0",
            {},
        ),
        content_identity=BehaviorReference(
            "test.restart-identity/content",
            "1.0.0",
            {},
        ),
        runtime_validator=lambda value: None,
        runtime_to_wire=lambda value: value,
        runtime_from_wire=lambda value: value,
        output_identity_materialization=materializer,
        runtime_output_identity_materializer=(
            lambda value, _: ResolvedOutputIdentity(value)
        ),
        output_identity_source_port_types={"source": source_port},
    )
    catalog = FrozenCatalog(
        (source_port, identity_port),
        contracts=(),
        availability=(),
        availability_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    roots = (
        ExactContractReference(**identity_port.reference()),
    )
    expected_contracts = tuple(
        sorted(
            (
                ExactContractReference(**source_port.reference()),
                roots[0],
            ),
            key=lambda reference: (
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            ),
        )
    )

    assert catalog.resolve_contract_closure(roots) == expected_contracts


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

    first = TestClient(
        create_application(
            frozen_catalog_override=original_catalog,
            v2_environment_configuration=environment,
        )
    )
    try:
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
        first.close()

        ledger_dir = run_root / project_id / run_id / "ledger"
        before = {
            path.name: path.read_bytes()
            for path in sorted(ledger_dir.glob("*.json"))
        }

        with TestClient(
            create_application(
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
        first.close()
        release.set()
        first.app.state.run_runtime.shutdown()

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
    app = create_application(
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
        projected = _public_events(
            app.state.run_runtime,
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


def test_background_runs_keep_project_reserved_serial_and_joined(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()
    calls: list[str] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
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

        def shutdown() -> None:
            app.state.run_runtime.shutdown()
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


def test_run_runtime_switches_and_releases_local_provider_state(
    tmp_path,
    monkeypatch,
) -> None:
    states: list[dict[object, object]] = []

    def use_local_provider(resources: Any) -> None:
        provider_id = {
            "direct-0": "proteinmpnn",
            "direct-1": "simplefold-folding",
        }[resources.node_id]
        with resources.local_provider(provider_id) as state:
            if states:
                assert states[-1] == {}
            state["model"] = object()
            states.append(state)

    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    binding_ids = ("test.first.local", "test.second.local")
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            binding_ids=binding_ids,
            execution_action=use_local_provider,
        ),
        v2_environment_configuration={
            (binding_id, "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
            for binding_id in binding_ids
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_independent_nodes(
            client,
            binding_ids,
        )
        receipt = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": compiled["workflow_commit_id"],
                "client_request_id": "provider-transition",
            },
        )
        assert receipt.status_code == 202
        assert wait_for_testclient_run_terminal(
            client,
            project_id,
            receipt.json()["run_id"],
        )["status"] == "succeeded"
        assert len(states) == 2
        assert states[0] == {}
        assert states[1] != {}

    assert states[1] == {}


def test_sync_runs_share_the_application_execution_slot(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
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
        runtime = app.state.run_runtime
        errors: list[BaseException] = []
        second_started = threading.Event()

        def execute(
            project_id: str,
            workflow_commit_id: str,
            started: threading.Event | None = None,
        ) -> None:
            if started is not None:
                started.set()
            try:
                runtime.start(
                    project_id,
                    workflow_commit_id=workflow_commit_id,
                    client_request_id=f"sync-{project_id}",
                )
            except BaseException as error:
                errors.append(error)

        first = threading.Thread(
            target=execute,
            args=(project_a, compiled_a["workflow_commit_id"]),
        )
        second = threading.Thread(
            target=execute,
            args=(
                project_b,
                compiled_b["workflow_commit_id"],
                second_started,
            ),
        )
        first.start()
        assert entered.wait(timeout=1)
        second.start()
        try:
            assert second_started.wait(timeout=1)
            time.sleep(0.05)
            assert calls.count("execute:test.direct.local") == 1
        finally:
            release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        assert calls.count("execute:test.direct.local") == 2


def test_terminal_project_lease_waits_for_background_release(
    tmp_path,
    monkeypatch,
) -> None:
    release_entered = threading.Event()
    allow_release = threading.Event()
    second_finished = threading.Event()
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        runtime = app.state.run_runtime
        original_release = runtime._release_project

        def delayed_first_release(
            retained_project_id: str,
            *,
            worker: threading.Thread | None = None,
        ) -> None:
            if worker is not None and not release_entered.is_set():
                release_entered.set()
                assert allow_release.wait(timeout=2)
            original_release(retained_project_id, worker=worker)

        monkeypatch.setattr(
            runtime,
            "_release_project",
            delayed_first_release,
        )
        first = runtime.start_background(
            project_id,
            workflow_commit_id=compiled["workflow_commit_id"],
            client_request_id="terminal-before-release-first",
        )
        assert release_entered.wait(timeout=1)
        assert runtime.projection(
            project_id,
            first["run_id"],
        ).status == "succeeded"

        second_state: dict[str, object] = {}

        def start_second() -> None:
            try:
                second_state["receipt"] = runtime.start_background(
                    project_id,
                    workflow_commit_id=compiled["workflow_commit_id"],
                    client_request_id="terminal-before-release-second",
                )
            except BaseException as error:
                second_state["error"] = error
            finally:
                second_finished.set()

        second_worker = threading.Thread(target=start_second)
        second_worker.start()
        assert not second_finished.wait(timeout=0.05)
        allow_release.set()
        assert second_finished.wait(timeout=2)
        second_worker.join(timeout=1)
        assert "error" not in second_state
        second = second_state["receipt"]
        assert isinstance(second, dict)
        assert wait_for_testclient_run_terminal(
            client,
            project_id,
            second["run_id"],
        )["status"] == "succeeded"


def test_sync_starts_queue_on_the_project_lease(
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
    app = create_application(
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
        runtime = app.state.run_runtime
        with pytest.raises(WorkflowAuthoringError) as missing:
            runtime.start(
                project_id,
                workflow_commit_id="workflow-commit-missing",
                client_request_id="sync-missing",
            )
        assert missing.value.code == "workflow_commit_not_found"

        state: dict[str, object] = {}

        def execute_sync() -> None:
            try:
                state["receipt"] = runtime.start(
                    project_id,
                    workflow_commit_id=compiled["workflow_commit_id"],
                    client_request_id="sync-active",
                )
            except BaseException as error:
                state["error"] = error

        sync_worker = threading.Thread(target=execute_sync)
        sync_worker.start()
        assert entered.wait(timeout=1)

        queued: dict[str, object] = {}
        queued_done = threading.Event()

        def execute_queued() -> None:
            try:
                queued["receipt"] = runtime.start(
                    project_id,
                    workflow_commit_id=compiled["workflow_commit_id"],
                    client_request_id="sync-queued",
                )
            except BaseException as error:
                queued["error"] = error
            finally:
                queued_done.set()

        queued_worker = threading.Thread(target=execute_queued)
        queued_worker.start()
        assert not queued_done.wait(timeout=0.05)

        release.set()
        sync_worker.join(timeout=2)
        queued_worker.join(timeout=2)
        assert not sync_worker.is_alive()
        assert not queued_worker.is_alive()
        assert "error" not in state
        assert "error" not in queued
        receipt = state["receipt"]
        queued_receipt = queued["receipt"]
        assert isinstance(receipt, dict)
        assert isinstance(queued_receipt, dict)
        assert runtime.projection(
            project_id,
            receipt["run_id"],
        ).status == "succeeded"
        assert runtime.projection(
            project_id,
            queued_receipt["run_id"],
        ).status == "succeeded"


def test_background_thread_start_is_atomic_with_shutdown(
    tmp_path,
    monkeypatch,
) -> None:
    start_entered = threading.Event()
    allow_start = threading.Event()
    shutdown_done = threading.Event()
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _commit_one_node(client)
        runtime = app.state.run_runtime
        original_start = threading.Thread.start

        def controlled_start(worker: threading.Thread) -> None:
            if worker.name.startswith("v2-run-admission-"):
                start_entered.set()
                assert allow_start.wait(timeout=2)
            original_start(worker)

        monkeypatch.setattr(threading.Thread, "start", controlled_start)
        state: dict[str, object] = {}

        def start_background() -> None:
            try:
                state["receipt"] = runtime.start_background(
                    project_id,
                    workflow_commit_id=compiled["workflow_commit_id"],
                    client_request_id="atomic-start",
                )
            except BaseException as error:
                state["start_error"] = error

        def shutdown() -> None:
            try:
                runtime.shutdown()
            except BaseException as error:
                state["shutdown_error"] = error
            finally:
                shutdown_done.set()

        starter = threading.Thread(target=start_background)
        starter.start()
        assert start_entered.wait(timeout=1)
        shutdown_worker = threading.Thread(target=shutdown)
        shutdown_worker.start()
        assert not shutdown_done.wait(timeout=0.05)

        allow_start.set()
        starter.join(timeout=2)
        shutdown_worker.join(timeout=2)
        assert not starter.is_alive()
        assert not shutdown_worker.is_alive()
        assert shutdown_done.is_set()
        assert "start_error" not in state
        assert "shutdown_error" not in state
        receipt = state["receipt"]
        assert isinstance(receipt, dict)
        assert runtime.projection(
            project_id,
            receipt["run_id"],
        ).status == "succeeded"


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

    first = TestClient(
        create_application(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    )
    try:
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
        before_events = _public_events(
            first.app.state.run_runtime,
            project_id,
            run_id,
        )
        first.close()

        with TestClient(
            create_application(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted:
            projection = restarted.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
            reconciled_events = _public_events(
                restarted.app.state.run_runtime,
                project_id,
                run_id,
            )

        with TestClient(
            create_application(
                frozen_catalog_override=catalog,
                v2_environment_configuration=environment,
            )
        ) as restarted_again:
            repeated_projection = restarted_again.get(
                f"/api/v2/projects/{project_id}/runs/{run_id}"
            ).json()
            repeated_events = _public_events(
                restarted_again.app.state.run_runtime,
                project_id,
                run_id,
            )
    finally:
        first.close()
        release.set()
        first.app.state.run_runtime.shutdown()

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
    app = create_application(
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
        cursor_a = app.state.run_runtime.ledger_cursor(
            project_a,
            started_a["run_id"],
        ).value
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
