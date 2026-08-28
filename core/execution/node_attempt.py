"""One schedulable Node Execution Attempt lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast
import uuid

from core.execution._node_attempt_errors import (
    _binding_error,
    _execution_error,
    _publication_error,
)
from core.execution._node_attempt_identity import (
    _exact_reference,
    _node_output_plan,
    _resolve_effective_randomness,
    _result_identity,
)
from core.execution._node_attempt_invocation import (
    _OperationInvocationRecorder,
)
from core.execution._node_attempt_models import (
    AttemptOutcome,
    AttemptSpec,
    ExecutionTermination,
    _EffectiveRandomnessSnapshot,
    _NodeExecutionAttemptState,
    _PreparedNodeExecution,
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
from core.execution.output_admission.admission import admit_node_output
from core.execution.output_admission.port_values import combine_admitted_port
from core.execution.resources import LocalProviderMemory, RunResources
from core.execution.results.cache import ResultIndexError
from core.execution.results.store import ResultIntegrityError, ResultStore
from core.operation import (
    AdmittedPort,
    OperationCall,
    OperationContext,
    retain_secondary_cleanup_exception,
)
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.plan import ExecutionPlanNode


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
        local_provider_memory: LocalProviderMemory,
    ) -> None:
        self._projects = projects
        self._environment = environment
        self._ledger = ledger
        self._readiness_failures: dict[
            str,
            V2RunError | None,
        ] = {}
        self._result_store = result_store
        self._local_provider_memory = local_provider_memory
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
        declaration = node._runtime.readiness_declaration
        environment = self._environment.for_binding(binding_id)
        observed_at = _utc_now()
        result = declaration.check(environment)
        ledger.record(
            ReadinessAttestation(
                binding=_exact_reference(node.binding),
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
                    "binding": {
                        "contract_kind": node.binding.contract_kind,
                        "contract_id": node.binding.contract_id,
                    },
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
        prepared: _PreparedNodeExecution,
    ) -> _NodeExecutionAttemptState:
        return _NodeExecutionAttemptState(
            project_id=spec.project_id,
            run_id=spec.run_id,
            node=spec.node,
            candidate_data_port_types=spec.candidate_data_port_types,
            cancellation=spec.cancellation,
            node_attempt_id=f"node-attempt-{uuid.uuid4().hex}",
            operation_attempt_id=f"operation-{uuid.uuid4().hex}",
            inputs=prepared.inputs,
            project_inputs=prepared.project_inputs,
            resource_identities=prepared.resource_identities,
            cache_eligible=prepared.cache_eligible,
        )

    @staticmethod
    def _admitted_inputs_for(
        node: ExecutionPlanNode,
        values: Mapping[tuple[str, str], AdmittedPort],
    ) -> Mapping[str, AdmittedPort]:
        """Combine committed upstream values under the compiled Port plan."""
        admitted_inputs: dict[str, list[Any]] = {}
        for port_name, sources in node._runtime.input_sources.items():
            for source_reference in sources:
                source = values.get(
                    (
                        source_reference.node_id,
                        source_reference.output_port,
                    )
                )
                if source is None or not source.values:
                    continue
                admitted_inputs.setdefault(port_name, []).extend(source.values)

        inputs: dict[str, AdmittedPort] = {}
        for port_name, admitted in admitted_inputs.items():
            declaration = node._runtime.input_ports[port_name]
            inputs[port_name] = combine_admitted_port(
                port_type=_exact_reference(declaration.reference),
                multiplicity=declaration.multiplicity,
                values=tuple(admitted),
            )
        return inputs

    def _prepare(self, spec: AttemptSpec) -> _PreparedNodeExecution:
        inputs = self._admitted_inputs_for(
            spec.node,
            spec.committed_values,
        )
        project_inputs, resource_identities = (
            self._resolve_project_inputs(spec.project_id, spec.node)
        )
        effective_randomness = _resolve_effective_randomness(
            spec.node,
            inputs,
        )
        cache_eligible = (
            spec.node._runtime.cacheable
            and spec.node._runtime.deterministic
        )
        result_identity = (
            _result_identity(
                spec.node,
                inputs,
                resolved_resource_inputs=resource_identities,
                effective_randomness_snapshot=effective_randomness,
            )
            if cache_eligible
            else None
        )
        return _PreparedNodeExecution(
            inputs=inputs,
            project_inputs=project_inputs,
            resource_identities=resource_identities,
            effective_randomness=effective_randomness,
            cache_eligible=cache_eligible,
            result_identity=result_identity,
        )

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
        binding_key = state.node.binding.contract_id
        if binding_key not in self._readiness_failures:
            readiness_error: V2RunError | None = None
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
                default_engine_identity=state.node.method.contract_id,
            ),
            _cancellation_control=state.cancellation,
            _local_provider_memory=self._local_provider_memory,
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
        primary_cleanup_error: BaseException | None = None
        try:
            resources.cleanup_temporary_work()
        except BaseException as cleanup_error:
            primary_cleanup_error = cleanup_error
            outcome = "interrupted"
        cancellation_cleanup_error = state.cancellation.cleanup_error
        if cancellation_cleanup_error is not None:
            if primary_cleanup_error is None:
                primary_cleanup_error = cancellation_cleanup_error
            else:
                retain_secondary_cleanup_exception(
                    primary_cleanup_error,
                    cancellation_cleanup_error,
                )
            outcome = "interrupted"
        return self._publication.commit_termination(
            state,
            status=outcome,
            public_error=(
                _execution_error(primary_cleanup_error)
                if primary_cleanup_error is not None
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
        cancellation_cleanup_error = state.cancellation.cleanup_error
        if (
            cancellation_cleanup_error is not None
            and cancellation_cleanup_error is not error
        ):
            retain_secondary_cleanup_exception(
                error,
                cancellation_cleanup_error,
            )
        terminal_status = (
            "failed"
            if cancellation_cleanup_error is not None
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
                retain_secondary_cleanup_exception(
                    error,
                    cleanup_error,
                )
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
                    retain_secondary_cleanup_exception(
                        body_error,
                        cleanup_error,
                    )
                else:
                    body_error = cleanup_error
            if self._ledger.cancellation_requested:
                state.cancellation.wait_for_cleanup()
            cancellation_cleanup_error = state.cancellation.cleanup_error
            if (
                cancellation_cleanup_error is not None
                and body_error is None
            ):
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
        prepared = self._prepare(spec)
        state = self._new_state(spec, prepared)
        cancellation = self._begin_attempt(state)
        if cancellation is not None:
            return self._publication.commit_unstarted(
                node_id=state.node.node_id,
                outcome=cancellation,
            )
        try:
            effective_randomness = prepared.effective_randomness
            result_identity = prepared.result_identity
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
            committed_error = self._commit_preoperation_error(state, error)
            if isinstance(error, (ResultIndexError, ResultIntegrityError)):
                return committed_error
            raise
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

    __slots__ = (
        "_environment",
        "_local_provider_memory",
        "_projects",
        "_result_store",
    )

    def __init__(
        self,
        projects: ProjectManager,
        environment: EnvironmentConfiguration,
        result_store: ResultStore,
    ) -> None:
        self._projects = projects
        self._environment = environment
        self._result_store = result_store
        self._local_provider_memory = LocalProviderMemory()

    def create(
        self,
        *,
        ledger: Ledger,
    ) -> NodeAttemptExecutor:
        return _NodeAttempt(
            projects=self._projects,
            environment=self._environment,
            result_store=self._result_store,
            ledger=ledger,
            local_provider_memory=self._local_provider_memory,
        )

    def shutdown(self) -> None:
        self._local_provider_memory.release()


__all__ = [
    "AttemptOutcome",
    "AttemptSpec",
    "ExecutionTermination",
    "NodeAttemptExecutor",
    "NodeAttemptFactory",
]
