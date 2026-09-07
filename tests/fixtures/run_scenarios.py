"""Shared execution scenarios with explicit runtime injection seams."""

from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
import threading
from typing import Any, Literal, Mapping
from fastapi.testclient import TestClient
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
)
from core.execution.node_attempt import ExecutionTermination
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.support.catalog import (
    binding_availability,
    catalog_contract,
    install_runtime,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.sequence import ProteinSequence

from tests.support.public_runs import PublicRunClient


def contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict[str, Any],
    *,
    environment_fields: tuple[EnvironmentFieldDeclaration, ...] | None = None,
) -> CatalogContract:
    return catalog_contract(
        contract_kind,
        contract_id,
        {
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
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


def direct_catalog(
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
    method = contract(
        "method",
        "test.direct.method",
        {
            "algorithm_identity": {"name": "deterministic-text"},
            "model_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "scale_contract": {"kind": "identity"},
        },
    )
    text = builtin.require_port_type("text")
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
            validator=BehaviorReference(
                "test.method_observation/validate",
                {},
            ),
            codec=BehaviorReference(
                "test.method_observation/codec",
                {},
            ),
            content_identity=BehaviorReference(
                "test.method_observation/content",
                {},
            ),
            runtime_validator=lambda value: None,
            runtime_to_wire=lambda value: value,
            runtime_from_wire=lambda value: value,
            observation_method_projection=BehaviorReference(
                "test.method_observation/method_projection",
                {},
            ),
            runtime_observation_method_projection=lambda _: (projected_method,),
        )
        catalog_port_types = (*builtin.port_types, text)
    node_type = contract(
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
            {"route": "direct"},
        )
        binding_readiness_behavior = BehaviorReference(
            f"{binding_id}/readiness",
            {"observation": "per-run"},
        )
        binding_adapter_behavior = BehaviorReference(
            f"{binding_id}/adapter",
            {"route": "provider"},
        )
        binding = contract(
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
                    calls.append(f"parameters:{dict(call.node_parameters)!r}")
                assert call.binding_parameters == {}
                if effective_randomness_parameters:
                    calls.append("randomness:" f"{dict(call.effective_randomness)!r}")
                else:
                    assert call.effective_randomness == {}
                if invocation_count == 0:
                    calls.append(f"execute:{self._binding_id}")
                else:
                    for index in range(invocation_count):
                        with self._resources.engine_invocation(
                            engine_role=("primary" if index == 0 else "secondary")
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
                assert check_input.values["credential"] == "credential-value"
                calls.append(f"readiness:{exact_binding_id}")
                passing = exact_binding_id != failing_binding_id
                return ReadinessResult(
                    passing,
                    reason_code=(None if passing else "fixture_readiness_rejected"),
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

        factories[binding_id] = ScientificOperationFactory(
            behavior=binding_factory_behavior,
            build=make_factory(binding_id),
        )
        readiness_declarations[binding_id] = ReadinessDeclaration(
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
                    binding_id: effective_randomness_resolver
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


def commit_one_node(client: TestClient) -> tuple[str, dict[str, Any]]:
    project = client.post("/api/v2/projects", json={"name": "v2 direct"}).json()
    project_id = project["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "direct",
                "node_type_id": "test.direct",
                "binding_id": "test.direct.local",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
    }
    return project_id, PublicRunClient(client).commit_workflow(project_id, workflow)


def commit_independent_nodes(
    client: TestClient,
    binding_ids: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    project = client.post("/api/v2/projects", json={"name": "v2 readiness"}).json()
    project_id = project["id"]
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": f"direct-{index}",
                "node_type_id": "test.direct",
                "binding_id": binding_id,
                "node_parameters": {},
                "binding_parameters": {},
            }
            for index, binding_id in enumerate(binding_ids)
        ],
        "edges": [],
    }
    return project_id, PublicRunClient(client).commit_workflow(project_id, workflow)


def pipeline_catalog(
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
    )
    candidate_data_type = builtin.require_port_type(
        "protein.sequence",
    )

    def validate_text(value: Any) -> None:
        calls.append(f"validate:{value!r}")
        if type(value) is not str or value != value.strip().lower():
            raise PortValueError("canonical text requires a string")

    canonical_text = PortTypeDefinition(
        type_id="test.canonical_text",
        validator=BehaviorReference(
            "test.canonical_text/validate",
            {"accepted_value_kind": "text"},
        ),
        codec=BehaviorReference(
            "test.canonical_text/codec",
            {"normalization": "strip-and-lowercase"},
        ),
        content_identity=BehaviorReference(
            "test.canonical_text/content",
            {"digest": "SHA-256"},
        ),
        runtime_validator=validate_text,
        runtime_to_wire=lambda value: value.strip().lower(),
        runtime_from_wire=lambda value: value,
    )
    method = contract(
        "method",
        "test.pipeline.method",
        {
            "algorithm_identity": {"name": "canonical-pipeline"},
            "model_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "scale_contract": {"kind": "identity"},
        },
    )
    source = contract(
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
    sink = contract(
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
                if execution_gates is not None and self._node_id in execution_gates:
                    entered, release = execution_gates[self._node_id]
                    entered.set()
                    if not release.wait(timeout=5):
                        raise TimeoutError("fixture execution gate timed out")
                if self._node_id == failing_source_node_id:
                    raise RuntimeError("sk-secret-branch-provider-failure")
                if (
                    terminating_source_nodes is not None
                    and self._node_id in terminating_source_nodes
                ):
                    raise ExecutionTermination(terminating_source_nodes[self._node_id])
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
                assert text_record.port_type.contract_id == "test.canonical_text"
                assert len(text_record.value_content_digests) == 1
            if include_candidate_data:
                candidate_record = call.inputs["candidates"]
                candidates = candidate_record.value
                candidate_values = tuple(candidates.items)
                assert candidate_record.port_type.contract_id == "candidate.collection"
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
                    text_record.value if text_record is not None else "optional"
                )
                calls.append(f"sink-input:{text_record.value if text_record else None}")
                return {"text": text_value}

    for binding_id, node_type, implementation in (
        ("test.pipeline.source.direct", source, SourceImplementation),
        ("test.pipeline.sink.direct", sink, SinkImplementation),
    ):
        factory_behavior = BehaviorReference(
            f"{binding_id}/factory",
            {},
        )
        readiness_behavior = BehaviorReference(
            f"{binding_id}/readiness",
            {},
        )
        binding = contract(
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

        factories[binding_id] = ScientificOperationFactory(
            behavior=factory_behavior,
            build=build_implementation,
        )
        readiness[binding_id] = ReadinessDeclaration(
            behavior=readiness_behavior,
            prerequisites={},
            check=lambda check_input: ReadinessResult(True),
        )
        availability.append(binding_availability(binding, observed_at))
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


def artifact_catalog(
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
                ).reference(),
                "required": True,
                "multiplicity": "one",
                "scientific_meaning": "Deterministic artifact summary",
            },
        )
    method = contract(
        "method",
        "test.artifact.method",
        {
            "algorithm_identity": {"name": "deterministic-artifact"},
            "model_identity": {"kind": "none"},
            "featurization_identity": {"kind": "none"},
            "scale_contract": {"kind": "identity"},
        },
    )
    node = contract(
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
        {},
    )
    readiness_behavior = BehaviorReference(
        "test.artifact/readiness",
        {},
    )
    binding = contract(
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
                calls.append(
                    f"workspace:{workspace.name.startswith('artifact-engine-')}"
                )
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
                "structure": (payload_values if collection else payload_values[0])
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
                "test.artifact.direct": ScientificOperationFactory(
                    behavior=factory_behavior,
                    build=factory,
                )
            },
            readiness={
                "test.artifact.direct": ReadinessDeclaration(
                    behavior=readiness_behavior,
                    prerequisites={},
                    check=lambda check_input: ReadinessResult(True),
                )
            },
        ),
        availability=(binding_availability(binding, observed_at),),
        availability_observed_at=observed_at,
    )


def commit_artifact_node(
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
                "binding_id": "test.artifact.direct",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
    }
    return project_id, PublicRunClient(client).commit_workflow(project_id, workflow)


def commit_pipeline(
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
                "binding_id": "test.pipeline.source.direct",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "sink",
                "node_type_id": "test.pipeline.sink",
                "binding_id": "test.pipeline.sink.direct",
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
    }
    return project_id, PublicRunClient(client).commit_workflow(project_id, workflow)
