"""One schedulable Node Execution Attempt lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast
import uuid

from core.catalog.port_contract import canonical_sha256
from core.catalog.model import CatalogAvailabilityProjection
from core.execution._node_attempt_errors import (
    _binding_error,
    _execution_error,
    _publication_error,
)
from core.execution._node_attempt_identity import (
    _EffectiveRandomnessSnapshot,
    _exact_reference,
    _node_output_plan,
    _resolve_effective_randomness,
    _result_identity,
    result_contract_metadata,
    result_identity_descriptor,
)
from core.execution._node_attempt_invocation import (
    _OperationInvocationRecorder,
)
from core.execution._node_attempt_models import (
    AttemptOutcome,
    AttemptSpec,
    ExecutionTermination,
    _NodeExecutionAttemptState,
)
from core.execution._node_attempt_publication import _AttemptPublication
from core.execution.environment import EnvironmentConfiguration
from core.execution.ledger import (
    Ledger,
    NodeAttemptStarted,
    OperationAttemptStarted,
    ReadinessAttestation,
    V2RunError,
    run_timestamp,
)
from core.execution.output_admission import admit_node_output
from core.execution.resources import RunResources
from core.execution.results import ResultStore
from core.operation import (
    OperationCall,
    OperationContext,
    ReadinessCheckInput,
)
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.plan import ExecutionPlanNode
from datatypes.i_json import thaw_i_json


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NodeAttemptExecutor(Protocol):
    """The sole Run Runtime view of a Node Attempt lifecycle."""

    def execute(self, spec: AttemptSpec) -> AttemptOutcome:
        """Execute one schedulable Node lifecycle."""
        ...


class _NodeAttempt:
    """Own each schedulable Node Execution Attempt behind one interface."""

    def __init__(
        self,
        *,
        projects: ProjectManager,
        environment: EnvironmentConfiguration,
        result_store: ResultStore,
        ledger: Ledger,
        availability_by_binding: Mapping[
            tuple[str, str],
            CatalogAvailabilityProjection,
        ],
    ) -> None:
        self._projects = projects
        self._environment = environment
        self._ledger = ledger
        self._availability_by_binding = availability_by_binding
        self._readiness_failures: dict[
            tuple[str, str],
            V2RunError | None,
        ] = {}
        self._result_store = result_store
        self._publication = _AttemptPublication(
            ledger=ledger,
            result_store=result_store,
        )

    def _begin_attempt(
        self,
        state: _NodeExecutionAttemptState,
    ) -> Literal["cancelled", "interrupted"] | None:
        acknowledged = self._ledger.record_if_active(
            NodeAttemptStarted(
                node_id=state.node.node_id,
                node_attempt_id=state.node_attempt_id,
            )
        )
        return (
            None
            if acknowledged is not None
            else self._pending_cancellation_outcome(state)
        )

    @staticmethod
    def _pending_cancellation_outcome(
        state: _NodeExecutionAttemptState,
    ) -> Literal["cancelled", "interrupted"]:
        return (
            "interrupted"
            if state.cancellation.cleanup_error is not None
            else "cancelled"
        )

    def _attest_readiness(
        self,
        *,
        node: ExecutionPlanNode,
        ledger: Ledger,
    ) -> None:
        binding_id = node.binding.contract_id
        binding_version = node.binding.contract_version
        declaration = node._runtime.readiness_declaration
        environment = self._environment.for_binding(
            binding_id,
            binding_version,
        )
        observed_at = _utc_now()
        result = declaration.check(ReadinessCheckInput(environment.values))
        readiness_digest = canonical_sha256(
            {
                "schema_namespace": "protein-workbench-readiness/v2",
                "binding": node.binding.canonical_projection(),
                "declaration": thaw_i_json(declaration.descriptor()),
            }
        )
        ledger.record(
            ReadinessAttestation(
                binding=_exact_reference(node.binding),
                readiness_contract_digest=readiness_digest,
                observed_at=run_timestamp(observed_at),
                conclusion="passing" if result.passing else "failing",
                proof_source=result.proof_source,
            )
        )
        if not result.passing:
            raise V2RunError(
                "readiness_rejected",
                "Selected Binding is not ready for this Run",
                details={
                    "binding": node.binding.canonical_projection(),
                    "reason_code": result.reason_code,
                },
            )

    def _resolve_project_inputs(
        self,
        project_id: str,
        node: ExecutionPlanNode,
    ) -> tuple[
        dict[str, tuple[ProjectInputDescriptor, bytes]],
        tuple[Mapping[str, Any], ...],
    ]:
        """Resolve declared Project resources before Result Identity lookup."""
        resolved: dict[str, tuple[ProjectInputDescriptor, bytes]] = {}
        identities: list[Mapping[str, Any]] = []
        for parameter_name in node._runtime.project_input_parameters:
            reference = node.node_parameters[parameter_name]
            descriptor, payload = self._projects.read_input(
                project_id,
                reference,
            )
            resolved[reference] = (descriptor, payload)
            identities.append(
                {
                    "resource_kind": "project_input",
                    "parameter_name": parameter_name,
                    "content_digest": descriptor.content_digest,
                    "size": descriptor.size,
                }
            )
        return resolved, tuple(identities)

    @staticmethod
    def _new_state(
        spec: AttemptSpec,
    ) -> _NodeExecutionAttemptState:
        return _NodeExecutionAttemptState(
            project_id=spec.project_id,
            run_id=spec.run_id,
            node=spec.node,
            candidate_data_port_types=spec.candidate_data_port_types,
            cancellation=spec.cancellation,
            node_attempt_id=f"node-attempt-{uuid.uuid4().hex}",
            operation_attempt_id=f"operation-{uuid.uuid4().hex}",
            inputs=spec.admitted_inputs,
            project_inputs={},
            resource_identities=(),
        )

    def _prepare(
        self,
        state: _NodeExecutionAttemptState,
    ) -> _EffectiveRandomnessSnapshot:
        project_inputs, resource_identities = (
            self._resolve_project_inputs(state.project_id, state.node)
        )
        state.project_inputs = project_inputs
        state.resource_identities = resource_identities
        return _resolve_effective_randomness(state.node, state.inputs)

    def _resolve_result_identity(
        self,
        state: _NodeExecutionAttemptState,
        effective_randomness: _EffectiveRandomnessSnapshot,
    ) -> str | None:
        state.cache_eligible = (
            state.node._runtime.cacheable
            and state.node._runtime.deterministic
        )
        if state.cache_eligible:
            return _result_identity(
                state.node,
                state.inputs,
                resolved_resource_inputs=state.resource_identities,
                effective_randomness_snapshot=effective_randomness,
            )
        return None

    def _cache_outcome(
        self,
        state: _NodeExecutionAttemptState,
        *,
        result_identity: str | None,
        cache_bypassed: bool,
    ) -> AttemptOutcome | None:
        if cache_bypassed or result_identity is None:
            return None
        replayed = self._result_store.lookup_replay(
            project_id=state.project_id,
            materialization_run_id=state.run_id,
            node_plan=_node_output_plan(
                state.node,
                state.candidate_data_port_types,
            ),
            result_identity=result_identity,
            result_contract_metadata=result_contract_metadata(
                state.node,
            ),
        )
        if replayed is None:
            return None
        state.resolution = "cache_replayed"
        admitted_node_output = replayed.admitted_output
        return self._publication.commit_success(
            state,
            admitted_output=admitted_node_output,
            stored_result=replayed,
        )

    def _readiness_failure(
        self,
        state: _NodeExecutionAttemptState,
    ) -> V2RunError | None:
        if state.node._runtime.execution_route != "adapter":
            return None
        binding_key = (
            state.node.binding.contract_id,
            state.node.binding.contract_version,
        )
        if binding_key not in self._readiness_failures:
            availability = self._availability_by_binding[binding_key]
            readiness_error: V2RunError | None = None
            if not availability.result.is_available:
                readiness_error = V2RunError(
                    "binding_unavailable",
                    "Selected Binding is unavailable",
                    details={
                        "binding": state.node.binding.canonical_projection(),
                        "reason_code": availability.result.code,
                    },
                )
            else:
                try:
                    self._attest_readiness(
                        node=state.node,
                        ledger=self._ledger,
                    )
                except V2RunError as error:
                    if error.code != "readiness_rejected":
                        raise
                    readiness_error = error
            self._readiness_failures[binding_key] = readiness_error
        return self._readiness_failures[binding_key]

    def _owned_resources(
        self,
        state: _NodeExecutionAttemptState,
    ) -> RunResources:
        return RunResources(
            project_id=state.project_id,
            run_id=state.run_id,
            node_id=state.node.node_id,
            _projects=self._projects,
            _invocation_recorder=_OperationInvocationRecorder(
                ledger=self._ledger,
                operation_attempt_id=state.operation_attempt_id,
                default_engine_identity=state.node.method.contract_digest,
            ),
            _cancellation_control=state.cancellation,
            _project_inputs=state.project_inputs,
            _project_input_identities=state.resource_identities,
        )

    def _cleanup_before_operation_attempt(
        self,
        state: _NodeExecutionAttemptState,
        resources: RunResources,
        *,
        outcome: Literal["cancelled", "interrupted"],
    ) -> AttemptOutcome:
        if self._ledger.cancellation_requested:
            state.cancellation.wait_for_cleanup()
        try:
            resources.cleanup_temporary_work()
        except BaseException:
            outcome = "interrupted"
        if state.cancellation.cleanup_error is not None:
            outcome = "interrupted"
        return self._publication.commit_termination(
            state,
            status=outcome,
            public_error=(
                _execution_error(state.cancellation.cleanup_error)
                if state.cancellation.cleanup_error is not None
                else None
            ),
        )

    def _build_operation(
        self,
        state: _NodeExecutionAttemptState,
        effective_randomness: _EffectiveRandomnessSnapshot,
    ) -> tuple[
        Callable[[OperationCall], Mapping[str, Any]],
        OperationCall,
        RunResources,
    ]:
        resources = self._owned_resources(state)
        state.resources = resources
        operation_call = OperationCall(
            inputs=state.inputs,
            node_parameters=effective_randomness.node_parameters,
            binding_parameters=effective_randomness.binding_parameters,
            effective_randomness=effective_randomness.effective_randomness,
        )
        environment = self._environment.for_binding(
            state.node.binding.contract_id,
            state.node.binding.contract_version,
        )
        implementation = state.node._runtime.factory.build(
            OperationContext(
                method=_exact_reference(state.node.method),
                produced_observations=(
                    state.node._runtime.produced_observation_plan.observations
                ),
                selection_objectives=(
                    state.node._runtime.selection_objectives
                ),
                observation_selectors=(
                    state.node._runtime.observation_selectors
                ),
                environment=environment,
                resources=resources,
            )
        )
        return implementation.execute, operation_call, resources

    def _commit_execution_error(
        self,
        state: _NodeExecutionAttemptState,
        error: BaseException,
        *,
        failure_origin: Literal["attempt", "operation"],
    ) -> AttemptOutcome:
        if self._ledger.cancellation_requested:
            state.cancellation.wait_for_cleanup()
        if (
            isinstance(error, V2RunError)
            and error.code == "evidence_unavailable"
        ):
            self._ledger.retain_evidence_unavailable(error)
            raise error
        terminal_status = (
            "failed"
            if state.cancellation.cleanup_error is not None
            else "cancelled"
            if self._ledger.cancellation_requested
            else error.status
            if isinstance(error, ExecutionTermination)
            else "failed"
        )
        public_error = _execution_error(error)
        if terminal_status == "failed":
            return self._publication.commit_failure(
                state,
                public_error=public_error,
                failure_origin=failure_origin,
            )
        return self._publication.commit_termination(
            state,
            status=cast(
                Literal[
                    "cancelled",
                    "interrupted",
                    "outcome_unknown",
                ],
                terminal_status,
            ),
            public_error=public_error,
        )

    def _commit_preoperation_error(
        self,
        state: _NodeExecutionAttemptState,
        error: BaseException,
    ) -> AttemptOutcome:
        resources = state.resources
        if resources is not None:
            try:
                resources.cleanup_temporary_work()
            except BaseException as cleanup_error:
                error.add_note(
                    "Run workspace cleanup also failed: "
                    f"{type(cleanup_error).__name__}"
                )
        cancellation_cleanup_error = state.cancellation.cleanup_error
        if cancellation_cleanup_error is not None:
            if cancellation_cleanup_error is not error:
                cancellation_cleanup_error.add_note(
                    "Execution also terminated before cleanup: "
                    f"{type(error).__name__}"
                )
            error = cancellation_cleanup_error
        return self._commit_execution_error(
            state,
            error,
            failure_origin=(
                "operation" if state.operation_started else "attempt"
            ),
        )

    def _start_operation(
        self,
        state: _NodeExecutionAttemptState,
    ) -> Literal["cancelled", "interrupted"] | None:
        acknowledged = self._ledger.record_if_active(
            OperationAttemptStarted(
                operation_attempt_id=state.operation_attempt_id,
                node_attempt_id=state.node_attempt_id,
            )
        )
        if acknowledged is None:
            return self._pending_cancellation_outcome(state)
        else:
            state.operation_started = True
        return None

    def _run_operation(
        self,
        state: _NodeExecutionAttemptState,
        *,
        operation_execute: Callable[
            [OperationCall],
            Mapping[str, Any],
        ],
        operation_call: OperationCall,
        resources: RunResources,
        effective_randomness: _EffectiveRandomnessSnapshot,
        result_identity: str | None,
    ) -> AttemptOutcome:
        body_error: BaseException | None = None
        try:
            raw_outputs = operation_execute(operation_call)
            if self._ledger.cancellation_requested:
                raise ExecutionTermination("cancelled")
            if result_identity is None:
                result_identity = _result_identity(
                    state.node,
                    state.inputs,
                    resolved_resource_inputs=resources.result_identity_inputs,
                    effective_randomness_snapshot=effective_randomness,
                )
            admitted_node_output = admit_node_output(
                node_plan=_node_output_plan(
                    state.node,
                    state.candidate_data_port_types,
                ),
                admitted_inputs=state.inputs,
                raw_outputs=raw_outputs,
                result_identity=result_identity,
            )
            if self._ledger.cancellation_requested:
                raise ExecutionTermination("cancelled")
        except BaseException as error:
            body_error = error
        finally:
            try:
                resources.cleanup_temporary_work()
            except BaseException as cleanup_error:
                if body_error is not None:
                    body_error.add_note(
                        "Run workspace cleanup also failed: "
                        f"{type(cleanup_error).__name__}"
                    )
                else:
                    body_error = cleanup_error
            cancellation_cleanup_error = state.cancellation.cleanup_error
            if cancellation_cleanup_error is not None:
                if (
                    body_error is not None
                    and body_error is not cancellation_cleanup_error
                ):
                    cancellation_cleanup_error.add_note(
                        "Execution also terminated before cleanup: "
                        f"{type(body_error).__name__}"
                    )
                body_error = cancellation_cleanup_error
        if body_error is not None:
            return self._commit_execution_error(
                state,
                body_error,
                failure_origin="operation",
            )
        return self._publication.commit_success(
            state,
            admitted_output=admitted_node_output,
        )

    def execute(
        self,
        spec: AttemptSpec,
    ) -> AttemptOutcome:
        """Execute one schedulable Node Execution Attempt lifecycle."""
        state = self._new_state(spec)
        cancellation = self._begin_attempt(state)
        if cancellation is not None:
            return self._publication.commit_unstarted(
                node_id=state.node.node_id,
                outcome=cancellation,
            )
        try:
            effective_randomness = self._prepare(state)
            result_identity = self._resolve_result_identity(
                state,
                effective_randomness,
            )
            if self._ledger.cancellation_requested:
                return self._publication.commit_termination(
                    state,
                    status=self._pending_cancellation_outcome(state),
                    public_error=None,
                )
            replayed = self._cache_outcome(
                state,
                result_identity=result_identity,
                cache_bypassed=spec.cache_bypassed,
            )
            if replayed is not None:
                return replayed
            if self._ledger.cancellation_requested:
                return self._publication.commit_termination(
                    state,
                    status=self._pending_cancellation_outcome(state),
                    public_error=None,
                )

            readiness_error = self._readiness_failure(state)
            if self._ledger.cancellation_requested:
                return self._publication.commit_termination(
                    state,
                    status=self._pending_cancellation_outcome(state),
                    public_error=None,
                )
            if readiness_error is not None:
                return self._publication.commit_failure(
                    state,
                    public_error=_binding_error(readiness_error),
                    failure_origin="binding",
                )

            operation_execute, operation_call, resources = (
                self._build_operation(state, effective_randomness)
            )
            if self._ledger.cancellation_requested:
                return self._cleanup_before_operation_attempt(
                    state,
                    resources,
                    outcome="cancelled",
                )
            cancellation = self._start_operation(state)
            if cancellation is not None:
                return self._cleanup_before_operation_attempt(
                    state,
                    resources,
                    outcome=cancellation,
                )
        except BaseException as error:
            return self._commit_preoperation_error(state, error)
        return self._run_operation(
            state,
            operation_execute=operation_execute,
            operation_call=operation_call,
            resources=resources,
            effective_randomness=effective_randomness,
            result_identity=result_identity,
        )


class NodeAttemptFactory:
    """Construct the package-owned Node Attempt implementation per Run."""

    __slots__ = ("_environment", "_projects", "_result_store")

    def __init__(
        self,
        projects: ProjectManager,
        environment: EnvironmentConfiguration,
        result_store: ResultStore,
    ) -> None:
        self._projects = projects
        self._environment = environment
        self._result_store = result_store

    def create(
        self,
        *,
        ledger: Ledger,
        availability_by_binding: Mapping[
            tuple[str, str],
            CatalogAvailabilityProjection,
        ],
    ) -> NodeAttemptExecutor:
        return _NodeAttempt(
            projects=self._projects,
            environment=self._environment,
            result_store=self._result_store,
            ledger=ledger,
            availability_by_binding=availability_by_binding,
        )


__all__ = [
    "AttemptOutcome",
    "AttemptSpec",
    "ExecutionTermination",
    "NodeAttemptExecutor",
    "NodeAttemptFactory",
    "result_contract_metadata",
    "result_identity_descriptor",
]
