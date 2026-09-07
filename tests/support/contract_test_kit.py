"""Focused Module Package conformance through real Catalog and Run interfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any

from core.catalog.builder import build_frozen_catalog
from core.catalog.declarations import ModulePackageRegistration
from core.catalog.errors import PortValueError
from core.catalog.model import FrozenCatalog
from core.execution.environment import admit_environment_configuration
from core.execution.ledger import (
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    NodeAttemptStarted,
    NodeAttemptTerminal,
    NodeDisposition,
    OperationAttemptStarted,
    OperationAttemptTerminal,
    OutputsPublished,
    RunProjection,
)
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.scoring.selection import ObservationSelector, SelectionObjective
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import WorkflowDocument, WorkflowEdge, WorkflowNodeInstance
from protein_workbench_public.ledger_codec import encode_event, encode_run_projection
from tests.support.result_store import result_store


class ModulePackageConformanceError(AssertionError):
    """A representative case failed its shared conformance contract."""


@dataclass(frozen=True, slots=True)
class ModulePackagePortCase:
    """Owner-supplied representative values for one nominal Port Type."""

    type_id: str
    valid_value: Any = field(compare=False)
    invalid_values: tuple[Any, ...] = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class ModulePackageContractCase:
    """Execution inputs for one target Node and its supporting Workflow."""

    case_id: str
    node_type_id: str
    binding_id: str
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    environment_values: Mapping[str, Any]
    workflow_nodes: tuple[WorkflowNodeInstance, ...] = ()
    workflow_edges: tuple[WorkflowEdge, ...] = ()
    observation_selectors: tuple[ObservationSelector, ...] = ()
    selection_objectives: tuple[SelectionObjective, ...] = ()
    project_inputs: Mapping[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModulePackageExecutionResult:
    """Actual values and admitted evidence, independent of the cleaned Run storage."""

    case_id: str
    outputs: Mapping[str, tuple[Any, ...]]
    artifacts: Mapping[str, bytes]  # Exact artifact_reference -> retained bytes.
    publication: OutputsPublished
    projection: RunProjection
    node_events: tuple[Fact, ...]
    run_events: tuple[Fact, ...]

    @property
    def public_evidence(self) -> dict[str, Any]:
        """The actual public Run projection and events, not a Kit summary."""
        return {
            "projection": encode_run_projection(self.projection),
            "events": [
                encode_event(
                    project_id=self.projection.project_id,
                    run_id=self.projection.run_id,
                    fact=fact,
                )
                for fact in self.run_events
            ],
        }


def verify_module_package_port(
    registration: ModulePackageRegistration,
    case: ModulePackagePortCase,
    *,
    supporting_registrations: Sequence[ModulePackageRegistration] = (),
) -> None:
    """Check one owned Port's codec without creating or executing a Workflow."""
    catalog = build_frozen_catalog((registration, *supporting_registrations))
    if case.type_id not in {port.type_id for port in registration.port_types}:
        raise ModulePackageConformanceError(
            f"Port case references a type not owned by {registration.package_id}"
        )
    port_type = catalog.require_port_type(case.type_id)
    try:
        encoded = port_type.encode(case.valid_value)
        decoded = port_type.decode(encoded)
        if decoded != case.valid_value or port_type.encode(decoded) != encoded:
            raise ModulePackageConformanceError(
                f"{case.type_id} codec is not canonical and round-trippable"
            )
    except PortValueError as error:
        raise ModulePackageConformanceError(
            f"{case.type_id} codec conformance failed"
        ) from error
    for invalid in case.invalid_values:
        try:
            port_type.encode(invalid)
        except PortValueError:
            continue
        raise ModulePackageConformanceError(f"{case.type_id} accepted an invalid value")


def _node_events(events: tuple[Fact, ...], node_id: str) -> tuple[Fact, ...]:
    """Select admitted facts by their existing causal IDs; Ledger owns validity."""
    attempts = {
        fact.payload.node_attempt_id
        for fact in events
        if isinstance(fact.payload, NodeAttemptStarted)
        and fact.payload.node_id == node_id
    }
    operations = {
        fact.payload.operation_attempt_id
        for fact in events
        if isinstance(fact.payload, OperationAttemptStarted)
        and fact.payload.node_attempt_id in attempts
    }
    invocations = {
        fact.payload.invocation_id
        for fact in events
        if isinstance(fact.payload, EngineInvocationStarted)
        and fact.payload.operation_attempt_id in operations
    }
    selected = []
    for fact in events:
        payload = fact.payload
        if (
            isinstance(payload, (NodeAttemptStarted, NodeDisposition))
            and payload.node_id == node_id
            or isinstance(payload, NodeAttemptTerminal)
            and payload.node_attempt_id in attempts
            or isinstance(payload, (OperationAttemptStarted, OperationAttemptTerminal))
            and payload.operation_attempt_id in operations
            or isinstance(payload, (EngineInvocationStarted, EngineInvocationTerminal))
            and payload.invocation_id in invocations
        ):
            selected.append(fact)
    return tuple(selected)


def execute_module_package_case(
    registration: ModulePackageRegistration,
    case: ModulePackageContractCase,
    *,
    supporting_registrations: Sequence[ModulePackageRegistration] = (),
    work_root: str | Path | None = None,
) -> ModulePackageExecutionResult:
    """Execute one fresh case and retrieve its values before releasing storage."""
    catalog = build_frozen_catalog((registration, *supporting_registrations))
    if case.binding_id not in {binding.binding_id for binding in registration.bindings}:
        raise ModulePackageConformanceError(
            f"Execution case references a Binding not owned by {registration.package_id}"
        )
    parent = Path(work_root) if work_root is not None else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="protein-workbench-ctk-", dir=parent) as temporary:
        return _execute_case(catalog, case, Path(temporary))


def _execute_case(
    catalog: FrozenCatalog,
    case: ModulePackageContractCase,
    root: Path,
) -> ModulePackageExecutionResult:
    project_manager = ProjectManager(
        root / "projects",
        cache_root=root / "cache",
        output_root=root / "outputs",
        run_root=root / "runs",
    )
    project = project_manager.create(f"Contract Test Kit: {case.case_id}")
    for reference, payload in case.project_inputs.items():
        project_manager.publish_input(
            project.id,
            reference,
            payload,
            filename=reference,
        )
    authoring = WorkflowAuthoringService(project_manager, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            *case.workflow_nodes,
            WorkflowNodeInstance(
                node_id="contract-test-node",
                node_type_id=case.node_type_id,
                binding_id=case.binding_id,
                node_parameters=case.node_parameters,
                binding_parameters=case.binding_parameters,
            ),
        ),
        edges=case.workflow_edges,
        observation_selectors=case.observation_selectors,
        selection_objectives=case.selection_objectives,
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    service = V2RunService(
        project_manager,
        catalog,
        authoring,
        NodeAttemptFactory(
            project_manager,
            admit_environment_configuration(
                catalog,
                {
                    case.binding_id: dict(case.environment_values),
                },
            ),
            result_store(project_manager),
        ),
        result_store(project_manager),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"ctk-{case.case_id}",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        replay = service.replay(project.id, receipt["run_id"], None)
        if not replay.terminal:
            raise ModulePackageConformanceError(
                f"{case.case_id} replay did not reach the durable terminal fact"
            )
        if projection.status != "succeeded":
            raise ModulePackageConformanceError(
                f"{case.case_id} execution did not succeed"
            )
        publication = next(
            item
            for item in projection.publications
            if item.node_id == "contract-test-node"
        )
        outputs = {
            output.output_port: tuple(
                catalog.require_port_type(output.port_type.contract_id).decode(
                    service.typed_value(
                        project.id,
                        receipt["run_id"],
                        publication.node_id,
                        output.output_port,
                        index,
                    )[1]
                )
                for index in range(output.value_count)
            )
            for output in publication.outputs
        }
        artifacts = {
            artifact.artifact_reference: service.artifact(
                project.id,
                receipt["run_id"],
                artifact.artifact_reference,
            )[1]
            for artifact in publication.artifacts
        }
        return ModulePackageExecutionResult(
            case_id=case.case_id,
            outputs=MappingProxyType(outputs),
            artifacts=MappingProxyType(artifacts),
            publication=publication,
            projection=projection,
            node_events=_node_events(replay.events, publication.node_id),
            run_events=replay.events,
        )
    finally:
        service.shutdown()
