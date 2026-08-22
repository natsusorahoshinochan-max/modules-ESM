"""One schedulable Node Execution Attempt lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal, cast
import uuid

from core.catalog.port_contract import (
    PortValueError,
    canonical_sha256,
)
from core.execution._node_attempt_errors import (
    _binding_error,
    _execution_error,
    _publication_error,
)
from core.execution._node_attempt_identity import (
    _exact_reference,
    _node_output_plan,
    _plain_json,
    _resolve_effective_randomness,
    _result_identity,
    _result_identity_is_cache_safe,
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
    _ArtifactCapacityError,
    _NodeExecutionAttemptState,
)
from core.execution._node_attempt_publication import _AttemptPublication
from core.execution.environment import EnvironmentConfiguration
from core.execution.ledger import (
    Ledger,
    NodeAttemptStart,
    OperationAttemptStart,
    ReadinessAttestation,
    V2RunError,
    run_timestamp,
)
from core.execution.output_admission import admit_node_output
from core.execution.output_admission.artifacts import (
    AdmittedArtifactPublicationPlan,
)
from core.execution.resources import RunResources
from core.execution.results import ResultStore
from core.operation import (
    OperationCall,
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
)
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.plan import ExecutionPlanNode


MAX_ARTIFACTS_PER_RUN = 2_048
MAX_ARTIFACT_BYTES_PER_RUN = 256 * 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NodeAttempt:
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
            Mapping[str, Any],
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
            NodeAttemptStart(
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
        if not isinstance(result, ReadinessResult):
            raise TypeError("Readiness checker must return ReadinessResult")
        readiness_digest = canonical_sha256(
            {
                "schema_namespace": "protein-workbench-readiness/v2",
                "binding": node.binding.canonical_projection(),
                "declaration": _plain_json(declaration.descriptor()),
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
            reference = node.node_parameters.get(parameter_name)
            if not isinstance(reference, str):
                raise PortValueError(
                    f"Project input parameter {parameter_name!r} is invalid"
                )
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

    def _require_artifact_capacity(
        self,
        *,
        plan: AdmittedArtifactPublicationPlan,
        committed_artifact_count: int,
        committed_artifact_bytes: int,
        replayed: bool,
    ) -> None:
        if (
            committed_artifact_count + len(plan.publications)
            > MAX_ARTIFACTS_PER_RUN
        ):
            if replayed:
                raise _ArtifactCapacityError
            raise PortValueError("Run artifact count exceeds the public bound")
        if (
            committed_artifact_bytes
            + sum(len(publication.body) for publication in plan.publications)
            > MAX_ARTIFACT_BYTES_PER_RUN
        ):
            if replayed:
                raise _ArtifactCapacityError
            raise PortValueError("Run artifact bytes exceed the public bound")

    def _prepare(
        self,
        spec: AttemptSpec,
    ) -> _NodeExecutionAttemptState:
        project_inputs, resource_identities = (
            self._resolve_project_inputs(spec.project_id, spec.node)
        )
        effective_randomness = _resolve_effective_randomness(
            spec.node,
            spec.admitted_inputs,
        )
        return _NodeExecutionAttemptState(
            project_id=spec.project_id,
            run_id=spec.run_id,
            node=spec.node,
            candidate_data_port_types=spec.candidate_data_port_types,
            cancellation=spec.cancellation,
            node_attempt_id=f"node-attempt-{uuid.uuid4().hex}",
            operation_attempt_id=f"operation-{uuid.uuid4().hex}",
            inputs=spec.admitted_inputs,
            project_inputs=project_inputs,
            resource_identities=resource_identities,
            effective_randomness=effective_randomness,
            result_identity=None,
        )

    def _resolve_result_identity(
        self,
        state: _NodeExecutionAttemptState,
    ) -> None:
        state.cache_eligible = (
            state.node._runtime.cacheable
            and state.node._runtime.deterministic
            and _result_identity_is_cache_safe(
                state.node,
                state.inputs,
                resolved_resource_inputs=state.resource_identities,
                effective_randomness_snapshot=state.effective_randomness,
            )
        )
        if state.cache_eligible:
            state.result_identity = _result_identity(
                state.node,
                state.inputs,
                resolved_resource_inputs=state.resource_identities,
                effective_randomness_snapshot=state.effective_randomness,
            )

    def _cache_outcome(
        self,
        state: _NodeExecutionAttemptState,
        *,
        cache_bypassed: bool,
        committed_artifact_count: int,
        committed_artifact_bytes: int,
    ) -> AttemptOutcome | None:
        if (
            not state.cache_eligible
            or cache_bypassed
            or state.result_identity is None
        ):
            return None
        try:
            replayed = self._result_store.lookup_replay(
                project_id=state.project_id,
                materialization_run_id=state.run_id,
                node_plan=_node_output_plan(
                    state.node,
                    state.candidate_data_port_types,
                ),
                result_identity=state.result_identity,
                result_contract_metadata=result_contract_metadata(
                    state.node,
                ),
            )
            if replayed is None:
                return None
            state.resolution = "cache_replayed"
            state.stored_result = replayed
            admitted_node_output = replayed.admitted_output
            state.admitted_node_output = admitted_node_output
            state.admitted_outputs = dict(
                admitted_node_output.runtime_ports
            )
            state.artifact_publication_plan = (
                admitted_node_output.artifact_publication_plan
            )
            self._require_artifact_capacity(
                plan=state.artifact_publication_plan,
                committed_artifact_count=committed_artifact_count,
                committed_artifact_bytes=committed_artifact_bytes,
                replayed=True,
            )
        except _ArtifactCapacityError:
            state.resolution = "cache_replayed"
            return self._publication.commit_failure(
                state,
                public_error=_publication_error(
                    node_id=state.node.node_id,
                    stage="artifact_object",
                ),
                failure_origin="publication",
            )
        state.resources = RunResources(
            project_id=state.project_id,
            run_id=state.run_id,
            node_id=state.node.node_id,
            _projects=self._projects,
            _cancellation_control=state.cancellation,
        )
        return self._publication.commit_success(state)

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
            if availability["available"] is not True:
                readiness_error = V2RunError(
                    "binding_unavailable",
                    "Selected Binding is unavailable",
                    details={
                        "binding": state.node.binding.canonical_projection(),
                        "reason_code": availability["reason"]["code"],
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
        *,
        outcome: Literal["cancelled", "interrupted"],
    ) -> AttemptOutcome:
        resources = state.resources
        if resources is None:
            raise RuntimeError(
                "Node Execution Attempt cleanup lacks owned Run resources"
            )
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
    ) -> tuple[
        Any,
        Callable[[OperationCall], Mapping[str, Any]],
        OperationCall,
    ] | AttemptOutcome:
        resources = self._owned_resources(state)
        state.resources = resources
        operation_call = OperationCall(
            inputs=state.inputs,
            node_parameters=state.effective_randomness.node_parameters,
            binding_parameters=state.effective_randomness.binding_parameters,
            effective_randomness=(
                state.effective_randomness.effective_randomness
            ),
        )
        try:
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
            execute_candidate = getattr(implementation, "execute", None)
            if not callable(execute_candidate):
                raise TypeError(
                    "Scientific Operation factory must return an "
                    "object with callable execute(OperationCall)"
                )
        except BaseException as error:
            try:
                resources.cleanup_temporary_work()
            except BaseException as cleanup_error:
                error.add_note(
                    "Run workspace cleanup also failed: "
                    f"{type(cleanup_error).__name__}"
                )
            raise
        if self._ledger.cancellation_requested:
            return self._cleanup_before_operation_attempt(
                state,
                outcome="cancelled",
            )
        return implementation, execute_candidate, operation_call

    def _start_operation(
        self,
        state: _NodeExecutionAttemptState,
    ) -> Literal["cancelled", "interrupted"] | None:
        acknowledged = self._ledger.record_if_active(
            OperationAttemptStart(
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
        committed_artifact_count: int,
        committed_artifact_bytes: int,
    ) -> AttemptOutcome:
        resources = state.resources
        if resources is None:
            raise RuntimeError(
                "Started Operation Attempt lacks owned Run resources"
            )
        body_error: BaseException | None = None
        try:
            raw_outputs = operation_execute(operation_call)
            if self._ledger.cancellation_requested:
                raise ExecutionTermination("cancelled")
            if state.result_identity is None:
                state.result_identity = _result_identity(
                    state.node,
                    state.inputs,
                    resolved_resource_inputs=resources.result_identity_inputs,
                    effective_randomness_snapshot=state.effective_randomness,
                )
            admitted_node_output = admit_node_output(
                node_plan=_node_output_plan(
                    state.node,
                    state.candidate_data_port_types,
                ),
                admitted_inputs=state.inputs,
                raw_outputs=raw_outputs,
                result_identity=state.result_identity,
            )
            state.admitted_node_output = admitted_node_output
            state.admitted_outputs = dict(
                admitted_node_output.runtime_ports
            )
            state.artifact_publication_plan = (
                admitted_node_output.artifact_publication_plan
            )
            self._require_artifact_capacity(
                plan=state.artifact_publication_plan,
                committed_artifact_count=committed_artifact_count,
                committed_artifact_bytes=committed_artifact_bytes,
                replayed=False,
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
            if self._ledger.cancellation_requested:
                state.cancellation.wait_for_cleanup()
            if (
                isinstance(body_error, V2RunError)
                and body_error.code == "evidence_unavailable"
            ):
                self._ledger.retain_evidence_unavailable(body_error)
                raise body_error
            terminal_status = (
                "failed"
                if state.cancellation.cleanup_error is not None
                else "cancelled"
                if self._ledger.cancellation_requested
                else body_error.status
                if isinstance(body_error, ExecutionTermination)
                else "failed"
            )
            public_error = _execution_error(body_error)
            if terminal_status == "failed":
                return self._publication.commit_failure(
                    state,
                    public_error=public_error,
                    failure_origin="operation",
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
        return self._publication.commit_success(state)

    def execute(
        self,
        spec: AttemptSpec,
    ) -> AttemptOutcome:
        """Execute one schedulable Node Execution Attempt lifecycle."""
        state = self._prepare(spec)
        cancellation = self._begin_attempt(state)
        if cancellation is not None:
            return self._publication.commit_unstarted(
                node_id=state.node.node_id,
                outcome=cancellation,
            )
        self._resolve_result_identity(state)
        if self._ledger.cancellation_requested:
            return self._publication.commit_termination(
                state,
                status=self._pending_cancellation_outcome(state),
                public_error=None,
            )
        replayed = self._cache_outcome(
            state,
            cache_bypassed=spec.cache_bypassed,
            committed_artifact_count=spec.committed_artifact_count,
            committed_artifact_bytes=spec.committed_artifact_bytes,
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

        operation = self._build_operation(state)
        if isinstance(operation, AttemptOutcome):
            return operation
        _, operation_execute, operation_call = operation
        cancellation = self._start_operation(state)
        if cancellation is not None:
            return self._cleanup_before_operation_attempt(
                state,
                outcome=cancellation,
            )
        return self._run_operation(
            state,
            operation_execute=operation_execute,
            operation_call=operation_call,
            committed_artifact_count=spec.committed_artifact_count,
            committed_artifact_bytes=spec.committed_artifact_bytes,
        )


__all__ = [
    "AttemptOutcome",
    "AttemptSpec",
    "ExecutionTermination",
    "NodeAttempt",
    "result_contract_metadata",
    "result_identity_descriptor",
]
