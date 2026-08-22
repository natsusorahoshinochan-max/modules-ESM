"""Readiness-gated direct execution and durable public Run projections."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
import uuid

from core.catalog.port_contract import (
    is_valid_artifact_media_type,
)
from core.operation import (
    AdmittedPort,
    EngineInvocationProvenance,
    InvocationRandomness,
    OperationCall,
    OperationContext,
    ProviderResidueProjection,
    ProviderResidueProjectionEntry,
    ReadinessCheckInput,
    ReadinessResult,
)
from core.execution.environment import EnvironmentConfiguration
from core.execution.ledger import (
    ArtifactOutputEvidence,
    AvailabilityBinding,
    CancellationDecision,
    ContextSelectorEvidence,
    DerivedRunReference,
    EngineInvocationConclusion,
    EngineInvocationStart,
    FilesystemLedgerStore,
    Fact,
    Ledger,
    LedgerStore,
    ImmutableObjectReference,
    LedgerAcknowledgement,
    NodeAttemptStart,
    NodeFailurePublication,
    NodeSuccessPublication,
    NodeTerminationPublication,
    ObservationSelectorEvidence,
    OperationAttemptStart,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
    PublishedArtifact,
    PublishedOutput,
    ReadinessAttestation,
    ReplayWindow,
    RunCursor,
    RunAdmission,
    RunClosure,
    RunProjection,
    RunScopeBinding,
    RunStart,
    SelectionFailure,
    SelectionObjectiveEvidence,
    SelectionResult,
    SelectionSuccess,
    StructuredError,
    UnstartedNodeConclusion,
    V2RunError,
    run_cursor,
    run_timestamp,
)
from core.execution.output_admission import (
    AdmittedNodeOutput,
    NodeOutputPlan,
    OutputPortPlan,
    admit_node_output,
)
from core.execution.output_admission.artifacts import (
    AdmittedArtifactPublicationPlan,
    ArtifactOutputDeclaration,
)
from core.execution.output_admission.candidate_identity import (
    _validate_input_candidate_identities,
)
from core.execution.output_admission.port_values import combine_admitted_port
from core.execution.resources import CancellationControl, RunResources
from core.execution.results import (
    ResultIntegrityError,
    ResultStore,
    ResultStoreWriteError,
    StoredNodeResult,
)
from core.catalog.model import (
    FrozenCatalog,
)
from core.catalog.port_contract import (
    ContractResolutionError,
    PortTypeDefinition,
    PortValueError,
    canonical_json_bytes,
    canonical_sha256,
)
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.scoring.selection import (
    PairwiseContextSelector,
    SelectionError,
    observation_selector_provenance_from_facts,
    selection_objective_provenance_from_facts,
)
from core.project.storage import (
    StoragePathError,
    replace_file,
    validate_identifier,
    validate_relative_path,
    write_new_file_durable,
)
from core.workflow.authoring import (
    VerifiedWorkflowCommit,
    WorkflowAuthoringService,
)
from core.workflow.document import CONTRACT_LOCK_NAMESPACE, ContractLockEntry
from core.workflow.plan import (
    ExecutionPlan,
    ExecutionPlanNode,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
)
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
)
from datatypes.residue import residue_identity_chain


_LOGGER = logging.getLogger(__name__)


RESULT_IDENTITY_NAMESPACE = "protein-workbench-cache/v3"
MAX_ARTIFACTS_PER_RUN = 2_048
MAX_ARTIFACT_BYTES_PER_RUN = 256 * 1024 * 1024
MAX_BACKGROUND_RUNS = 8
FAST_RUN_COMPLETION_GRACE_SECONDS = 0.25
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")
_ATTEMPT_TERMINALS = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "outcome_unknown",
    }
)
_DISPOSITION_OUTCOMES = frozenset(
    {"succeeded", "failed", "blocked", "cancelled", "interrupted"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _execution_error(error: BaseException) -> StructuredError:
    error_type = type(error).__name__
    if (
        len(error_type) > 128
        or _PUBLIC_IDENTIFIER.fullmatch(error_type) is None
    ):
        error_type = "Exception"
    return StructuredError(
        code="node_execution_failed",
        message="Node execution failed safely",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details={"exception_type": error_type},
    )


def _binding_error(error: V2RunError) -> StructuredError:
    """Preserve one failed Binding gate without inventing an Operation."""
    return StructuredError(
        code=error.code,
        message=str(error),
        retryable={
            "binding_unavailable": False,
            "readiness_rejected": True,
        }[error.code],
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details=error.details,
    )


def _publication_error(
    *,
    node_id: str,
    stage: Literal[
        "typed_value_object",
        "artifact_object",
        "manifest",
    ],
) -> StructuredError:
    return StructuredError(
        code="node_publication_failed",
        message="Node result publication failed",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details={
            "node_id": node_id,
            "publication_stage": stage,
        },
    )


def _selection_error(error: BaseException) -> StructuredError:
    error_type = type(error).__name__
    if (
        len(error_type) > 128
        or _PUBLIC_IDENTIFIER.fullmatch(error_type) is None
    ):
        error_type = "Exception"
    details = (
        {"reason": str(error)}
        if isinstance(error, SelectionError)
        else {"exception_type": error_type}
    )
    return StructuredError(
        code="selection_failed",
        message="Workflow selection failed safely",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details=details,
    )


class ExecutionTermination(RuntimeError):
    """A bounded terminal conclusion reported by a started engine seam."""

    def __init__(self, status: str) -> None:
        if status not in {
            "failed",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        }:
            raise ValueError("Execution terminal status is invalid")
        self.status = status
        super().__init__("Execution terminated without public diagnostics")


class _ArtifactCapacityError(RuntimeError):
    """A restored result cannot fit the current Run publication bounds."""


@dataclass(frozen=True, slots=True)
class _CommittedNodeOutcome:
    """The only Node Execution Attempt outcome visible to Run scheduling."""

    disposition: Literal[
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "blocked",
    ]
    admitted_outputs: Mapping[
        tuple[str, str],
        AdmittedPort,
    ] = field(default_factory=dict)
    artifacts: tuple[Mapping[str, Any], ...] = ()


@dataclass(slots=True)
class _NodeExecutionAttemptState:
    """Closed internal state for one Node Execution Attempt lifecycle."""

    node: ExecutionPlanNode
    node_attempt_id: str
    operation_attempt_id: str
    inputs: Mapping[str, AdmittedPort]
    project_inputs: Mapping[str, tuple[ProjectInputDescriptor, bytes]]
    resource_identities: tuple[Mapping[str, Any], ...]
    effective_randomness: _EffectiveRandomnessSnapshot
    result_identity: str | None
    cache_eligible: bool = False
    resolution: Literal["executed", "cache_replayed"] = "executed"
    resources: RunResources | None = None
    operation_started: bool = False
    admitted_node_output: AdmittedNodeOutput | None = None
    stored_result: StoredNodeResult | None = None
    admitted_outputs: Mapping[
        tuple[str, str],
        AdmittedPort,
    ] = field(default_factory=dict)
    artifact_publication_plan: AdmittedArtifactPublicationPlan = field(
        default_factory=lambda: AdmittedArtifactPublicationPlan((), ())
    )


class _NodeExecutionAttemptModule:
    """Own each schedulable Node Execution Attempt behind one interface."""

    def __init__(
        self,
        *,
        projects: ProjectManager,
        environment: EnvironmentConfiguration,
        result_store: ResultStore,
        project_id: str,
        run_id: str,
        execution_plan: ExecutionPlan,
        ledger: Ledger,
        run_record: _RunRecord,
        availability_by_binding: Mapping[
            tuple[str, str],
            Mapping[str, Any],
        ],
    ) -> None:
        self._projects = projects
        self._environment = environment
        self._project_id = project_id
        self._run_id = run_id
        self._execution_plan = execution_plan
        self._ledger = ledger
        self._run_record = run_record
        self._availability_by_binding = availability_by_binding
        self._readiness_failures: dict[
            tuple[str, str],
            V2RunError | None,
        ] = {}
        self._result_store = result_store

    @staticmethod
    def _disposition_for_status(
        status: Literal[
            "failed",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        ],
    ) -> Literal["failed", "cancelled", "interrupted"]:
        return "interrupted" if status == "outcome_unknown" else status

    def _record_failure(
        self,
        state: _NodeExecutionAttemptState,
        *,
        public_error: StructuredError,
        failure_origin: Literal["binding", "operation", "publication"],
        only_if_active: bool = False,
    ) -> _CommittedNodeOutcome | None:
        transition = NodeFailurePublication(
                node_id=state.node.node_id,
                node_attempt_id=state.node_attempt_id,
                operation_attempt_id=(
                    state.operation_attempt_id
                    if state.operation_started
                    else None
                ),
                resolution=state.resolution,
                error=public_error,
                failure_origin=failure_origin,
        )
        acknowledged = (
            self._ledger.record_if_active(transition)
            if only_if_active
            else self._ledger.record(transition)
        )
        if acknowledged is None:
            return None
        return _CommittedNodeOutcome(disposition="failed")

    def _commit_failure(
        self,
        state: _NodeExecutionAttemptState,
        *,
        public_error: StructuredError,
        failure_origin: Literal["binding", "operation", "publication"],
    ) -> _CommittedNodeOutcome:
        committed = self._record_failure(
            state,
            public_error=public_error,
            failure_origin=failure_origin,
        )
        if committed is None:
            raise RuntimeError("Required Node failure was not acknowledged")
        return committed

    def _record_termination(
        self,
        state: _NodeExecutionAttemptState,
        *,
        status: Literal["cancelled", "interrupted", "outcome_unknown"],
        public_error: StructuredError | None,
        operation_status: Literal[
            "succeeded",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        ]
        | None = None,
    ) -> _CommittedNodeOutcome:
        self._ledger.record(
            NodeTerminationPublication(
                node_id=state.node.node_id,
                status=status,
                node_attempt_id=state.node_attempt_id,
                operation_attempt_id=(
                    state.operation_attempt_id
                    if state.operation_started
                    else None
                ),
                operation_status=(
                    operation_status
                    if operation_status is not None
                    else status
                    if state.operation_started
                    else None
                ),
                resolution=state.resolution,
                error=public_error,
            )
        )
        return _CommittedNodeOutcome(
            disposition=self._disposition_for_status(status)
        )

    def _commit_termination(
        self,
        state: _NodeExecutionAttemptState,
        *,
        status: Literal["cancelled", "interrupted", "outcome_unknown"],
        public_error: StructuredError | None,
    ) -> _CommittedNodeOutcome:
        return self._record_termination(
            state,
            status=status,
            public_error=public_error,
        )

    def _commit_unstarted(
        self,
        *,
        node_id: str,
        outcome: Literal["cancelled", "interrupted"],
    ) -> _CommittedNodeOutcome:
        self._ledger.record(
            UnstartedNodeConclusion(
                node_id=node_id,
                outcome=outcome,
            )
        )
        return _CommittedNodeOutcome(disposition=outcome)

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
            else self._pending_cancellation_outcome()
        )

    def _pending_cancellation_outcome(
        self,
    ) -> Literal["cancelled", "interrupted"]:
        return (
            "interrupted"
            if self._run_record.cancellation.cleanup_error is not None
            else "cancelled"
        )

    def _stage_success(
        self,
        state: _NodeExecutionAttemptState,
    ) -> StoredNodeResult:
        if state.stored_result is not None:
            return state.stored_result
        if (
            state.result_identity is None
            or state.admitted_node_output is None
        ):
            raise RuntimeError(
                "Node Execution Attempt success lacks a complete admitted result"
            )
        stored = self._result_store.store(
            project_id=self._project_id,
            materialization_run_id=self._run_id,
            admitted_output=state.admitted_node_output,
            result_contract_metadata=_result_contract_metadata(state.node),
        )
        state.stored_result = stored
        return stored

    def _record_success(
        self,
        state: _NodeExecutionAttemptState,
        *,
        stored_result: StoredNodeResult,
        only_if_active: bool = False,
    ) -> tuple[_CommittedNodeOutcome, LedgerAcknowledgement] | None:
        if state.result_identity is None:
            raise RuntimeError(
                "Node Execution Attempt success lacks a Result Identity"
            )
        published_outputs = tuple(
            PublishedOutput(
                node_id=output.node_id,
                output_port=output.output_port,
                port_type=output.port_type,
                content_digest=output.content_digest,
                result_identity=stored_result.result_identity,
                materialization={
                    "run_id": output.materialization_run_id,
                    "resolution": output.resolution,
                },
                producer_provenance={
                    "producer_run_id": output.producer_run_id,
                    "producer_result_identity": stored_result.result_identity,
                    "output_port": output.output_port,
                },
                value_count=output.value_count,
                value_manifest_reference=output.value_manifest.content_digest,
            )
            for output in stored_result.published_outputs
        )
        published_artifacts = tuple(
            PublishedArtifact(
                artifact_reference=artifact.artifact_reference,
                artifact_kind=artifact.artifact_kind,
                node_id=artifact.node_id,
                output_port=artifact.output_port,
                media_type=artifact.media_type,
                filename=artifact.filename,
                size=artifact.body.size,
                content_digest=artifact.body.content_digest,
                candidate_id=artifact.candidate_id,
            )
            for artifact in stored_result.artifacts
        )
        transition = NodeSuccessPublication(
                node_id=state.node.node_id,
                node_attempt_id=state.node_attempt_id,
                operation_attempt_id=(
                    state.operation_attempt_id
                    if state.operation_started
                    else None
                ),
                resolution=state.resolution,
                result_identity=state.result_identity,
                node_result_manifest=ImmutableObjectReference(
                    content_digest=(
                        stored_result.node_result_manifest.content_digest
                    ),
                    size=stored_result.node_result_manifest.size,
                ),
                outputs=published_outputs,
                artifacts=published_artifacts,
                nonempty_output_ports=tuple(
                    sorted(
                        output_port
                        for (node_id, output_port), admitted in (
                            state.admitted_outputs.items()
                        )
                        if node_id == state.node.node_id and admitted
                    )
                ),
        )
        acknowledged = (
            self._ledger.record_if_active(transition)
            if only_if_active
            else self._ledger.record(transition)
        )
        if acknowledged is None:
            return None
        artifacts = tuple(
            {
                "artifact_reference": artifact.artifact_reference,
                "artifact_kind": artifact.artifact_kind,
                "node_id": artifact.node_id,
                "output_port": artifact.output_port,
                "media_type": artifact.media_type,
                "filename": artifact.filename,
                "size": artifact.body.size,
                "content_digest": artifact.body.content_digest,
                **(
                    {"candidate_id": artifact.candidate_id}
                    if artifact.candidate_id is not None
                    else {}
                ),
            }
            for artifact in stored_result.artifacts
        )
        return (
            _CommittedNodeOutcome(
                disposition="succeeded",
                admitted_outputs=state.admitted_outputs,
                artifacts=artifacts,
            ),
            acknowledged,
        )

    def _record_committed_cancellation(
        self,
        state: _NodeExecutionAttemptState,
    ) -> _CommittedNodeOutcome | None:
        if not self._ledger.cancellation_requested:
            return None
        resources = state.resources
        if resources is None:
            raise RuntimeError(
                "Started Node Execution Attempt lacks owned Run resources"
            )
        cancellation = resources._cancellation_control
        if cancellation is not None:
            cancellation.wait_for_cleanup()
        if cancellation is not None and cancellation.cleanup_error is not None:
            if not state.operation_started:
                return self._record_termination(
                    state,
                    status="interrupted",
                    public_error=_execution_error(cancellation.cleanup_error),
                )
            return self._record_failure(
                state,
                public_error=_execution_error(cancellation.cleanup_error),
                failure_origin="publication",
            )
        return self._record_termination(
            state,
            status="cancelled",
            public_error=None,
            operation_status=(
                "succeeded" if state.operation_started else None
            ),
        )

    def _commit_success(
        self,
        state: _NodeExecutionAttemptState,
    ) -> _CommittedNodeOutcome:
        try:
            stored_result = self._stage_success(state)
        except ResultStoreWriteError as error:
            failed = self._record_failure(
                state,
                public_error=_publication_error(
                    node_id=state.node.node_id,
                    stage=error.stage,
                ),
                failure_origin="publication",
                only_if_active=True,
            )
            if failed is not None:
                return failed
            cancelled = self._record_committed_cancellation(state)
            if cancelled is None:
                raise RuntimeError(
                    "Node outcome lost its cancellation ordering decision"
                )
            return cancelled

        recorded = self._record_success(
            state,
            stored_result=stored_result,
            only_if_active=True,
        )
        if recorded is None:
            cancelled = self._record_committed_cancellation(state)
            if cancelled is None:
                raise RuntimeError(
                    "Node outcome lost its cancellation ordering decision"
                )
            return cancelled
        committed, acknowledgement = recorded
        if (
            committed.disposition == "succeeded"
            and state.resolution == "executed"
            and state.cache_eligible
        ):
            try:
                self._result_store.index_committed_result(
                    stored_result,
                    acknowledgement,
                )
            except OSError:
                _LOGGER.warning(
                    "Committed Result replay index publication is unavailable"
                )
        return committed

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
                binding=_exact_contract_reference(node.binding),
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

    def _inputs_for(
        self,
        node: ExecutionPlanNode,
        values: Mapping[
            tuple[str, str],
            AdmittedPort,
        ],
    ) -> Mapping[str, AdmittedPort]:
        declarations = node._runtime.input_ports
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
                admitted_inputs.setdefault(port_name, []).extend(
                    source.values
                )

        inputs: dict[str, AdmittedPort] = {}
        for port_name, admitted in admitted_inputs.items():
            declaration = declarations[port_name]
            if (
                declaration.multiplicity == "one"
                and len(admitted) != 1
            ):
                raise RuntimeError(
                    "Execution Plan one-valued input Port "
                    f"{port_name!r} resolved to {len(admitted)} "
                    "admitted values"
                )
            inputs[port_name] = combine_admitted_port(
                port_type=declaration.reference.canonical_projection(),
                multiplicity=declaration.multiplicity,
                values=tuple(admitted),
            )
        _validate_input_candidate_identities(inputs)
        return MappingProxyType(inputs)

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
        committed_artifacts: tuple[Mapping[str, Any], ...],
        replayed: bool,
    ) -> None:
        if (
            len(committed_artifacts) + len(plan.publications)
            > MAX_ARTIFACTS_PER_RUN
        ):
            if replayed:
                raise _ArtifactCapacityError
            raise PortValueError("Run artifact count exceeds the public bound")
        if (
            sum(artifact["size"] for artifact in committed_artifacts)
            + sum(len(publication.body) for publication in plan.publications)
            > MAX_ARTIFACT_BYTES_PER_RUN
        ):
            if replayed:
                raise _ArtifactCapacityError
            raise PortValueError("Run artifact bytes exceed the public bound")


    def _prepare(
        self,
        node: ExecutionPlanNode,
        *,
        committed_values: Mapping[
            tuple[str, str],
            AdmittedPort,
        ],
    ) -> _NodeExecutionAttemptState:
        inputs = self._inputs_for(node, committed_values)
        project_inputs, resource_identities = (
            self._resolve_project_inputs(self._project_id, node)
        )
        effective_randomness = _resolve_effective_randomness(node, inputs)
        return _NodeExecutionAttemptState(
            node=node,
            node_attempt_id=f"node-attempt-{uuid.uuid4().hex}",
            operation_attempt_id=f"operation-{uuid.uuid4().hex}",
            inputs=inputs,
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
        committed_artifacts: tuple[Mapping[str, Any], ...],
    ) -> _CommittedNodeOutcome | None:
        if (
            not state.cache_eligible
            or cache_bypassed
            or state.result_identity is None
        ):
            return None
        try:
            replayed = self._result_store.lookup_replay(
                project_id=self._project_id,
                materialization_run_id=self._run_id,
                node_plan=_node_output_plan(
                    self._execution_plan,
                    state.node,
                ),
                result_identity=state.result_identity,
                result_contract_metadata=_result_contract_metadata(
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
                committed_artifacts=committed_artifacts,
                replayed=True,
            )
        except _ArtifactCapacityError:
            state.resolution = "cache_replayed"
            return self._commit_failure(
                state,
                public_error=_publication_error(
                    node_id=state.node.node_id,
                    stage="artifact_object",
                ),
                failure_origin="publication",
            )
        state.resources = RunResources(
            project_id=self._project_id,
            run_id=self._run_id,
            node_id=state.node.node_id,
            _projects=self._projects,
            _cancellation_control=self._run_record.cancellation,
        )
        return self._commit_success(state)

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
            project_id=self._project_id,
            run_id=self._run_id,
            node_id=state.node.node_id,
            _projects=self._projects,
            _invocation_recorder=_OperationInvocationRecorder(
                ledger=self._ledger,
                operation_attempt_id=state.operation_attempt_id,
                default_engine_identity=state.node.method.contract_digest,
            ),
            _cancellation_control=self._run_record.cancellation,
            _project_inputs=state.project_inputs,
            _project_input_identities=state.resource_identities,
        )

    def _cleanup_before_operation_attempt(
        self,
        state: _NodeExecutionAttemptState,
        *,
        outcome: Literal["cancelled", "interrupted"],
    ) -> _CommittedNodeOutcome:
        resources = state.resources
        if resources is None:
            raise RuntimeError(
                "Node Execution Attempt cleanup lacks owned Run resources"
            )
        if self._ledger.cancellation_requested:
            self._run_record.cancellation.wait_for_cleanup()
        try:
            resources.cleanup_temporary_work()
        except BaseException as cleanup_error:
            outcome = "interrupted"
        if self._run_record.cancellation.cleanup_error is not None:
            outcome = "interrupted"
        return self._commit_termination(
            state,
            status=outcome,
            public_error=(
                _execution_error(self._run_record.cancellation.cleanup_error)
                if self._run_record.cancellation.cleanup_error is not None
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
    ] | _CommittedNodeOutcome:
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
            return self._pending_cancellation_outcome()
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
        committed_artifacts: tuple[Mapping[str, Any], ...],
    ) -> _CommittedNodeOutcome:
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
                    self._execution_plan,
                    state.node,
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
                committed_artifacts=committed_artifacts,
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
            cancellation_cleanup_error = (
                self._run_record.cancellation.cleanup_error
            )
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
                self._run_record.cancellation.wait_for_cleanup()
            if (
                isinstance(body_error, V2RunError)
                and body_error.code == "evidence_unavailable"
            ):
                self._ledger.retain_evidence_unavailable(body_error)
                raise body_error
            terminal_status = (
                "failed"
                if self._run_record.cancellation.cleanup_error is not None
                else "cancelled"
                if self._ledger.cancellation_requested
                else body_error.status
                if isinstance(body_error, ExecutionTermination)
                else "failed"
            )
            public_error = _execution_error(body_error)
            if terminal_status == "failed":
                return self._commit_failure(
                    state,
                    public_error=public_error,
                    failure_origin="operation",
                )
            return self._commit_termination(
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
        return self._commit_success(state)

    def execute(
        self,
        node: ExecutionPlanNode,
        *,
        committed_values: Mapping[
            tuple[str, str],
            AdmittedPort,
        ],
        committed_artifacts: tuple[Mapping[str, Any], ...],
        cache_bypassed: bool,
    ) -> _CommittedNodeOutcome:
        """Execute one schedulable Node Execution Attempt lifecycle."""
        state = self._prepare(node, committed_values=committed_values)
        cancellation = self._begin_attempt(state)
        if cancellation is not None:
            return self._commit_unstarted(
                node_id=state.node.node_id,
                outcome=cancellation,
            )
        self._resolve_result_identity(state)
        if self._ledger.cancellation_requested:
            return self._commit_termination(
                state,
                status=self._pending_cancellation_outcome(),
                public_error=None,
            )
        replayed = self._cache_outcome(
            state,
            cache_bypassed=cache_bypassed,
            committed_artifacts=committed_artifacts,
        )
        if replayed is not None:
            return replayed
        if self._ledger.cancellation_requested:
            return self._commit_termination(
                state,
                status=self._pending_cancellation_outcome(),
                public_error=None,
            )

        readiness_error = self._readiness_failure(state)
        if self._ledger.cancellation_requested:
            return self._commit_termination(
                state,
                status=self._pending_cancellation_outcome(),
                public_error=None,
            )
        if readiness_error is not None:
            return self._commit_failure(
                state,
                public_error=_binding_error(readiness_error),
                failure_origin="binding",
            )

        operation = self._build_operation(state)
        if isinstance(operation, _CommittedNodeOutcome):
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
            committed_artifacts=committed_artifacts,
        )


@dataclass(frozen=True, slots=True)
class _OperationInvocationRecorder:
    ledger: Ledger
    operation_attempt_id: str
    default_engine_identity: str

    @contextmanager
    def invoke(
        self,
        *,
        engine_role: str,
        parent_invocation_id: str | None,
        invocation_provenance: EngineInvocationProvenance | None,
    ):
        invocation_id = f"invocation-{uuid.uuid4().hex}"
        acknowledged = self.ledger.record_if_active(
            EngineInvocationStart(
                invocation_id=invocation_id,
                operation_attempt_id=self.operation_attempt_id,
                engine_role=engine_role,
                engine_identity=self.default_engine_identity,
                parent_invocation_id=parent_invocation_id,
                provenance=invocation_provenance,
            )
        )
        if acknowledged is None:
            raise ExecutionTermination("cancelled")
        try:
            yield invocation_id
        except BaseException as error:
            terminal_status = (
                error.status
                if isinstance(error, ExecutionTermination)
                else "failed"
            )
            self.ledger.record(
                EngineInvocationConclusion(
                    invocation_id=invocation_id,
                    status=terminal_status,
                    error=_execution_error(error),
                )
            )
            raise
        else:
            self.ledger.record(
                EngineInvocationConclusion(
                    invocation_id=invocation_id,
                    status="succeeded",
                )
            )
            if self.ledger.cancellation_requested:
                raise ExecutionTermination("cancelled")


@dataclass(slots=True)
class _RunRecord:
    compiled: VerifiedWorkflowCommit | None
    ledger: Ledger
    cancellation: CancellationControl = field(
        default_factory=CancellationControl,
    )
    finished: threading.Event = field(default_factory=threading.Event)
    execution_error: BaseException | None = None
    evidence_unavailable: V2RunError | None = None


_RESOLVED_CONTRACT_FIELDS = frozenset(
    {
        "contract_kind",
        "contract_id",
        "contract_version",
        "contract_digest",
    }
)


def _exact_contract_reference(
    entry: ContractLockEntry,
) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=entry.contract_kind,
        contract_id=entry.contract_id,
        contract_version=entry.contract_version,
        contract_digest=entry.contract_digest,
    )


def _exact_reference_from_catalog(
    reference: Mapping[str, Any],
) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=reference["contract_kind"],
        contract_id=reference["contract_id"],
        contract_version=reference["contract_version"],
        contract_digest=reference["contract_digest"],
    )


def _execution_plan_contract_roots(
    plan: ExecutionPlan,
) -> tuple[ExactContractReference, ...]:
    """Persist the exact roots needed to reconstruct one Plan's Lock."""
    root_identities = {
        reference.key
        for node in plan.nodes
        for reference in (node.node_type, node.binding)
    }
    for resolved_selector in plan._runtime.observation_selectors:
        root_identities.update(
            {
                (
                    resolved_selector.metric.contract_kind,
                    resolved_selector.metric.contract_id,
                    resolved_selector.metric.contract_version,
                ),
                (
                    resolved_selector.method.contract_kind,
                    resolved_selector.method.contract_id,
                    resolved_selector.method.contract_version,
                ),
            }
        )
    for resolved_objective in plan._runtime.selection_objectives:
        root_identities.update(
            {
                (
                    resolved_objective.metric.contract_kind,
                    resolved_objective.metric.contract_id,
                    resolved_objective.metric.contract_version,
                ),
                (
                    resolved_objective.method.contract_kind,
                    resolved_objective.method.contract_id,
                    resolved_objective.method.contract_version,
                ),
                (
                    resolved_objective.utility.reference.contract_kind,
                    resolved_objective.utility.reference.contract_id,
                    resolved_objective.utility.reference.contract_version,
                ),
            }
        )
    lock_by_identity = {
        entry.key: entry for entry in plan.resolved_contracts
    }
    return tuple(
        _exact_contract_reference(lock_by_identity[identity])
        for identity in sorted(root_identities)
    )


def _reachable_contract_evidence(
    catalog: FrozenCatalog,
    roots: tuple[ExactContractReference, ...],
) -> tuple[ExactContractReference, ...]:
    """Rebuild the exact active Catalog closure from durable Plan roots."""
    pending = list(roots)
    reachable: dict[
        tuple[str, str, str],
        ExactContractReference,
    ] = {}
    while pending:
        reference = pending.pop()
        identity = (
            reference.contract_kind,
            reference.contract_id,
            reference.contract_version,
        )
        contract = catalog.require_contract(*identity)
        current_reference = _exact_reference_from_catalog(
            contract.reference()
        )
        if reference != current_reference:
            raise RuntimeError("Run scope Contract root is not active")
        if identity in reachable:
            continue
        reachable[identity] = current_reference
        descriptor = (
            contract.descriptor()
            if type(contract) is PortTypeDefinition
            else contract.descriptor
        )
        nested_values: list[Any] = [descriptor]
        while nested_values:
            value = nested_values.pop()
            if (
                isinstance(value, Mapping)
                and set(value) == _RESOLVED_CONTRACT_FIELDS
            ):
                pending.append(_exact_reference_from_catalog(value))
            elif isinstance(value, Mapping):
                nested_values.extend(value.values())
            elif isinstance(value, (list, tuple)):
                nested_values.extend(value)
    return tuple(reachable[identity] for identity in sorted(reachable))


def _run_catalog_digest(
    ledger: Ledger,
    catalog: FrozenCatalog,
) -> str:
    """Classify one admitted Ledger against the active Catalog generation."""
    scope = ledger.run_scope
    if scope is None:
        raise RuntimeError("Run Ledger has no admitted scope")
    persisted_catalog_digest = scope.catalog_contract_digest
    if persisted_catalog_digest != catalog.contract_digest:
        return persisted_catalog_digest
    expected_contracts = _reachable_contract_evidence(
        catalog,
        scope.resolved_contract_roots,
    )
    if scope.resolved_contracts != expected_contracts:
        raise RuntimeError("Run scope resolved Contracts are invalid")
    return persisted_catalog_digest


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, list):
        return [_plain_json(item) for item in value]
    return value


def _freeze_runtime_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze_runtime_json(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_runtime_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class _EffectiveRandomnessSnapshot:
    effective_randomness: Mapping[str, Any]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]


def _resolve_effective_randomness(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
) -> _EffectiveRandomnessSnapshot:
    node_parameters = _plain_json(node.node_parameters)
    binding_parameters = _plain_json(node.binding_parameters)
    declared_randomness = node._runtime.effective_randomness_parameters
    if declared_randomness:
        resolver = node._runtime.effective_randomness_resolver
        if resolver is None:
            resolved_randomness: Mapping[str, Any] = {
                parameter_name: (
                    node_parameters[parameter_name]
                    if parameter_name in node_parameters
                    and parameter_name not in binding_parameters
                    else (
                        binding_parameters[parameter_name]
                        if parameter_name in binding_parameters
                        and parameter_name not in node_parameters
                        else {"resolution": "unresolved"}
                    )
                )
                for parameter_name in declared_randomness
            }
        else:
            resolved_randomness = resolver.resolve(
                inputs=inputs,
                node_parameters=node_parameters,
                binding_parameters=binding_parameters,
            )
            if (
                not isinstance(resolved_randomness, Mapping)
                or set(resolved_randomness) != set(declared_randomness)
            ):
                raise ValueError(
                    "effective randomness resolver must return every "
                    "declared parameter exactly once"
                )
        effective_randomness = {}
        for parameter_name in declared_randomness:
            resolved_value = _plain_json(
                resolved_randomness[parameter_name]
            )
            effective_randomness[parameter_name] = (
                {"resolution": "unresolved"}
                if resolved_value is None
                else resolved_value
            )
            if (
                parameter_name in node_parameters
                and parameter_name not in binding_parameters
            ):
                node_parameters[parameter_name] = resolved_value
            elif (
                parameter_name in binding_parameters
                and parameter_name not in node_parameters
            ):
                binding_parameters[parameter_name] = resolved_value
    else:
        effective_randomness = {}
    canonical_json_bytes(
        {
            "effective_randomness": effective_randomness,
            "node_parameters": node_parameters,
            "binding_parameters": binding_parameters,
        }
    )
    return _EffectiveRandomnessSnapshot(
        effective_randomness=_freeze_runtime_json(effective_randomness),
        node_parameters=_freeze_runtime_json(node_parameters),
        binding_parameters=_freeze_runtime_json(binding_parameters),
    )


def _result_identity_descriptor(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> dict[str, Any]:
    """Build the closed scientific identity of one resolved Node result."""
    plan_facts = node.result_identity_plan_facts
    canonical_plan_facts = plan_facts.canonical_projection()
    static_facts = canonical_plan_facts["identity_facts"]
    declared_inputs = {
        port["input_port"]: port
        for port in static_facts["input_contracts"]
    }
    input_identities: list[dict[str, Any]] = []
    for port_name in sorted(inputs):
        declaration = declared_inputs[port_name]
        admitted = inputs[port_name]
        input_identities.append(
            {
                "input_port": port_name,
                "port_type": declaration["port_type"],
                "multiplicity": declaration["multiplicity"],
                "value_content_digests": list(
                    admitted.value_content_digests
                ),
            }
        )
    randomness_snapshot = (
        effective_randomness_snapshot
        if effective_randomness_snapshot is not None
        else _resolve_effective_randomness(node, inputs)
    )
    resolved_node_parameters = _plain_json(
        randomness_snapshot.node_parameters
    )
    resolved_binding_parameters = _plain_json(
        randomness_snapshot.binding_parameters
    )
    for parameter_name in plan_facts.node_parameter_indirections:
        resolved_node_parameters.pop(parameter_name, None)
    for parameter_name in node._runtime.project_input_parameters:
        resolved_node_parameters.pop(parameter_name, None)
    declared_randomness = node._runtime.effective_randomness_parameters
    if declared_randomness:
        effective_randomness = _plain_json(
            randomness_snapshot.effective_randomness
        )
        for parameter_name in declared_randomness:
            resolved_node_parameters.pop(parameter_name, None)
            resolved_binding_parameters.pop(parameter_name, None)
    else:
        effective_randomness = _plain_json(
            randomness_snapshot.effective_randomness
        )
    descriptor = {
        "schema_namespace": RESULT_IDENTITY_NAMESPACE,
        "result_identity_plan_facts": canonical_plan_facts,
        "inputs": input_identities,
        "node_parameters": resolved_node_parameters,
        "binding_parameters": resolved_binding_parameters,
        "determinism": {
            "deterministic": node._runtime.deterministic,
            "effective_randomness": effective_randomness,
        },
    }
    if resolved_resource_inputs:
        descriptor["resolved_resource_inputs"] = [
            _plain_json(identity)
            for identity in resolved_resource_inputs
        ]
    return descriptor


def _exact_reference(reference: Any) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=reference.contract_kind,
        contract_id=reference.contract_id,
        contract_version=reference.contract_version,
        contract_digest=reference.contract_digest,
    )


def _node_output_plan(
    execution_plan: ExecutionPlan,
    node: ExecutionPlanNode,
) -> NodeOutputPlan:
    """Project compiler-owned typed facts into the Output Admission seam."""
    return NodeOutputPlan(
        node_id=node.node_id,
        producing_method=_exact_reference(node.method),
        output_ports={
            output_port: OutputPortPlan(
                required=declaration.required,
                multiplicity=declaration.multiplicity,
                port_type=declaration.port_type,
            )
            for output_port, declaration in node._runtime.output_ports.items()
        },
        candidate_data_port_types=(
            execution_plan._runtime.candidate_data_port_types
        ),
        produced_observations=node._runtime.produced_observation_plan,
        artifact_outputs=tuple(
            ArtifactOutputDeclaration(
                output_port=declaration.output_port,
                artifact_kind=declaration.artifact_kind,
                artifact_media_type=declaration.artifact_media_type,
                accepted_media_types=declaration.accepted_media_types,
            )
            for declaration in node._runtime.artifact_outputs
        ),
    )


def _result_identity(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> str:
    return canonical_sha256(
        _result_identity_descriptor(
            node,
            inputs,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    )


def _context_selector_evidence(value: object) -> ContextSelectorEvidence:
    if isinstance(value, IntrinsicObservationContext):
        return ContextSelectorEvidence(kind="intrinsic")
    if isinstance(value, CalibrationObservationContext):
        return ContextSelectorEvidence(
            kind="calibration",
            calibration_metric=value.calibration_metric,
            calibration_value=value.calibration_value,
            calibration_unit=value.calibration_unit,
            population_id=value.population_id,
        )
    if isinstance(value, PairwiseContextSelector):
        return ContextSelectorEvidence(
            kind="pairwise",
            subject_role=value.subject_role,
            reference_role=value.reference_role,
            pairing_mode=value.pairing_mode,
            normalization=value.normalization,
        )
    raise TypeError("Selection Context selector is not current")


def _selection_consumer_result(
    node: ExecutionPlanNode,
    values: Mapping[tuple[str, str], AdmittedPort],
) -> SelectionResult:
    """Project one declared selection Node's actual typed output."""
    resolved_objectives = node._runtime.selection_objectives
    resolved_selectors = node._runtime.observation_selectors
    if resolved_selectors:
        candidate_references = {
            selector.candidate_input for selector in resolved_selectors
        }
    else:
        candidate_references = {
            objective.candidate_input for objective in resolved_objectives
        }
    if len(candidate_references) != 1:
        raise SelectionError(
            "Selection consumer objectives do not share one Candidate input"
        )
    output_port = node._runtime.selection_candidate_output_port
    resolved = (
        values.get((node.node_id, output_port))
        if isinstance(output_port, str)
        else None
    )
    if (
        resolved is None
        or resolved.multiplicity != "one"
        or type(resolved.value) is not CandidateCollection
    ):
        raise SelectionError(
            "Selection consumer output did not resolve to one exact "
            "CandidateCollection"
        )
    selected = resolved.value
    candidate_reference = next(iter(candidate_references))
    if resolved_selectors:
        observation_selectors = tuple(
            ObservationSelectorEvidence(
                selector_id=selector.selector_id,
                candidate_input=selector.candidate_input,
                score_collection_input=selector.score_collection_input,
                source_partition=selector.source_partition,
                metric=selector.metric,
                method=selector.method,
                context_selector=_context_selector_evidence(
                    selector.context_selector
                ),
                match_cardinality=selector.match_cardinality,
                missing_policy=selector.missing_policy,
            )
            for selector in observation_selector_provenance_from_facts(
                resolved_selectors
            )
        )
        objectives: tuple[SelectionObjectiveEvidence, ...] = ()
    else:
        provenance = selection_objective_provenance_from_facts(
            resolved_objectives
        )
        objectives = tuple(
            SelectionObjectiveEvidence(
                objective_id=objective.objective_id,
                candidate_input=objective.candidate_input,
                score_collection_input=objective.score_collection_input,
                source_partition=objective.source_partition,
                metric=objective.metric,
                method=objective.method,
                context_selector=_context_selector_evidence(
                    objective.context_selector
                ),
                utility_transform=objective.utility_transform,
                utility_parameters=dict(objective.utility_parameters),
                declared_weight=objective.declared_weight,
                effective_weight=objective.effective_weight,
                match_cardinality=objective.match_cardinality,
                missing_policy=objective.missing_policy,
            )
            for objective in provenance.objectives
        )
        observation_selectors = ()
    return SelectionResult(
        selection_node_id=node.node_id,
        selection_method=_exact_reference(node.method),
        candidate_input=candidate_reference,
        selected_collection_id=selected.collection_id,
        selected_candidate_ids=tuple(
            candidate.candidate_id for candidate in selected.items
        ),
        objectives=objectives,
        observation_selectors=observation_selectors,
    )


def _contains_unresolved_identity(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("identity_complete") is False:
            return True
        return any(
            _contains_unresolved_identity(item)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unresolved_identity(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return any(
            _contains_unresolved_identity(getattr(value, item.name))
            for item in fields(value)
        )
    return (
        isinstance(value, str)
        and value.strip().lower()
        in {"unknown", "unresolved", "latest", "unspecified"}
    )


def _candidate_values(value: Any) -> tuple[Candidate, ...]:
    if type(value) is Candidate:
        return (value,)
    if type(value) is CandidateCollection:
        return value.items
    if isinstance(value, (list, tuple)):
        return tuple(
            candidate
            for item in value
            for candidate in _candidate_values(item)
        )
    return ()


def _result_identity_is_cache_safe(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> bool:
    if _contains_unresolved_identity(
        node.result_identity_plan_facts.canonical_projection()
    ):
        return False
    if any(
        _contains_unresolved_identity(admitted.value)
        for admitted in inputs.values()
    ):
        return False
    if _contains_unresolved_identity(
        _result_identity_descriptor(
            node,
            inputs,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    ):
        return False
    return all(
        not _contains_unresolved_identity(candidate.candidate_id)
        for admitted in inputs.values()
        for candidate in _candidate_values(admitted.value)
    )


def _result_contract_metadata(
    node: ExecutionPlanNode,
) -> dict[str, Any]:
    return (
        node.result_identity_plan_facts.cache_contract_metadata()
    )


class V2RunService:
    """Execute compiled direct Nodes behind readiness and durable evidence."""

    def __init__(
        self,
        projects: ProjectManager,
        catalog: FrozenCatalog,
        authoring: WorkflowAuthoringService,
        environment: EnvironmentConfiguration,
        result_store: ResultStore,
        ledger_transaction_store: LedgerStore | None = None,
    ) -> None:
        self._projects = projects
        self._catalog = catalog
        self._authoring = authoring
        self._environment = environment
        self._result_store = result_store
        self._ledger_transaction_store = ledger_transaction_store
        self._runs: dict[tuple[str, str], _RunRecord] = {}
        self._damaged_runs: dict[tuple[str, str], RunCursor] = {}
        self._inactive_runs: dict[tuple[str, str], str] = {}
        self._run_owners: dict[str, str] = {}
        self._worker_condition = threading.Condition(threading.RLock())
        self._workers: set[threading.Thread] = set()
        self._reserved_projects: set[str] = set()
        self._execution_lock = threading.Lock()
        self._closed = False
        self._validated_ledgers: dict[
            tuple[str, str],
            Ledger,
        ] = {}
        self._load_persisted_runs()

    def _plan_evidence(
        self,
        plan: ExecutionPlan,
    ) -> tuple[PlanNodeEvidence, ...]:
        return tuple(
            PlanNodeEvidence(
                node_id=node.node_id,
                dependencies=node._runtime.dependencies,
                required_input_sources=tuple(
                    PlanRequiredInputEvidence(
                        input_port=input_port,
                        sources=tuple(
                            sorted(
                                (
                                    PlanValueSourceEvidence(
                                        source.node_id,
                                        source.output_port,
                                    )
                                    for source in sources
                                ),
                                key=lambda source: (
                                    source.node_id,
                                    source.output_port,
                                ),
                            )
                        ),
                    )
                    for input_port, sources in sorted(
                        node._runtime.required_input_sources.items()
                    )
                ),
                result_identity_plan_facts_digest=(
                    node.result_identity_plan_facts.digest
                ),
                binding=_exact_contract_reference(node.binding),
                execution_route=node._runtime.execution_route,
                node_type=_exact_contract_reference(node.node_type),
                artifact_outputs=tuple(
                    ArtifactOutputEvidence(
                        output_port=output.output_port,
                        artifact_kind=output.artifact_kind,
                        artifact_media_type=output.artifact_media_type,
                        port_type=_exact_contract_reference(output.port_type),
                        accepted_media_types=output.accepted_media_types,
                    )
                    for output in node._runtime.artifact_outputs
                ),
                selection_consumer=bool(
                    node._runtime.selection_objectives
                    or node._runtime.observation_selectors
                ),
            )
            for node in plan.nodes
        )

    def _run_directories(self):
        for project_id in self._projects.stored_project_ids():
            run_parent = self._projects.run_storage_root(project_id)
            if (
                not run_parent.is_dir()
            ):
                continue
            for run_dir in sorted(run_parent.iterdir()):
                if (
                    not run_dir.is_dir()
                ):
                    continue
                ledger = run_dir / "ledger"
                manifest = run_dir / "manifest.json"
                if (
                    not (
                        ledger.is_dir()
                    )
                    and not (
                        manifest.is_file()
                    )
                ):
                    continue
                try:
                    run_id = validate_identifier(run_dir.name, "run_id")
                except StoragePathError:
                    continue
                yield project_id, run_id, run_parent

    def _load_persisted_runs(self) -> None:
        for project_id, run_id, _ in self._run_directories():
            try:
                ledger = self._load_persisted_run(
                    project_id,
                    run_id,
                )
                if ledger is not None:
                    self._validated_ledgers[(project_id, run_id)] = ledger
            except (
                ContractResolutionError,
                KeyError,
                OSError,
                RuntimeError,
                StoragePathError,
                TypeError,
                V2RunError,
                ValueError,
            ):
                self._damaged_runs[(project_id, run_id)] = run_cursor(
                    0,
                    project_id=project_id,
                    run_id=run_id,
                )
                self._run_owners.setdefault(run_id, project_id)

    def _load_persisted_run(
        self,
        project_id: str,
        run_id: str,
    ) -> Ledger | None:
        ledger = Ledger.load(
            self._projects,
            project_id,
            run_id,
            self._ledger_transaction_store,
        )
        if ledger is None:
            return None
        if not ledger.admitted:
            return None
        if (
            run_id in self._run_owners
            and self._run_owners[run_id] != project_id
        ):
            raise RuntimeError("Run identity appears in multiple Projects")
        persisted_catalog_digest = _run_catalog_digest(
            ledger,
            self._catalog,
        )
        if persisted_catalog_digest != self._catalog.contract_digest:
            self._inactive_runs[(project_id, run_id)] = (
                persisted_catalog_digest
            )
            self._run_owners[run_id] = project_id
            return ledger
        ledger.reconcile_restart()
        record = _RunRecord(
            compiled=None,
            ledger=ledger,
        )
        if ledger.terminal:
            record.finished.set()
        self._runs[(project_id, run_id)] = record
        self._run_owners[run_id] = project_id
        return ledger

    def _require_record(
        self,
        project_id: str,
        run_id: str,
    ) -> _RunRecord:
        owner = self._run_owners.get(run_id)
        if owner is not None and owner != project_id:
            raise V2RunError(
                "cross_scope_access_denied",
                "Run does not belong to the requested Project",
                details={
                    "requested_project_id": project_id,
                    "requested_run_id": run_id,
                },
            )
        try:
            return self._runs[(project_id, run_id)]
        except KeyError as error:
            inactive_catalog_digest = self._inactive_runs.get(
                (project_id, run_id)
            )
            if inactive_catalog_digest is not None:
                raise V2RunError(
                    "inactive_generation",
                    "Run evidence belongs to an inactive Catalog generation",
                    details={
                        "artifact_kind": "run_evidence",
                        "expected_catalog_contract_digest": (
                            self._catalog.contract_digest
                        ),
                        "received_catalog_contract_digest": (
                            inactive_catalog_digest
                        ),
                    },
                ) from error
            damaged_cursor = self._damaged_runs.get((project_id, run_id))
            if damaged_cursor is not None:
                raise V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence is damaged and unavailable",
                    details={"last_durable_cursor": damaged_cursor.value},
                ) from error
            raise V2RunError(
                "run_not_found",
                "Run was not found",
                details={"resource_kind": "run", "resource_id": run_id},
            ) from error

    @staticmethod
    def _require_available_evidence(record: _RunRecord) -> None:
        unavailable = record.evidence_unavailable
        if unavailable is not None:
            raise V2RunError(
                unavailable.code,
                str(unavailable),
                details=unavailable.details,
            ) from unavailable

    def _availability(
        self,
        node: ExecutionPlanNode,
    ) -> Mapping[str, Any]:
        binding_id = node.binding.contract_id
        version = node.binding.contract_version
        for snapshot in self._catalog.availability:
            reference = snapshot["binding"]
            if (
                reference["contract_id"],
                reference["contract_version"],
            ) == (binding_id, version):
                return snapshot
        raise V2RunError(
            "binding_unavailable",
            "Selected Binding has no Availability snapshot",
            details={
                "binding": node.binding.canonical_projection(),
                "reason_code": "availability_missing",
            },
        )

    @staticmethod
    def _required_input_blockers(
        node: ExecutionPlanNode,
        values: Mapping[tuple[str, str], AdmittedPort],
    ) -> tuple[str, ...]:
        """Choose the Plan-level required-input blocking conclusion."""
        blockers: set[str] = set()
        for sources in node._runtime.required_input_sources.values():
            if any(
                (source := values.get(
                    (reference.node_id, reference.output_port)
                ))
                is not None
                and bool(source.values)
                for reference in sources
            ):
                continue
            blockers.update(reference.node_id for reference in sources)
        return tuple(sorted(blockers))

    def start(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
        client_request_id: str,
        _on_admitted: Callable[
            [dict[str, Any], _RunRecord],
            None,
        ]
        | None = None,
        _before_execute: Callable[[], None] | None = None,
        _derived_from: Mapping[str, Any] | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
        _retained_compiled: VerifiedWorkflowCommit | None = None,
    ) -> dict[str, Any]:
        del client_request_id
        if _retained_compiled is None:
            compiled = self._authoring.require_verified_commit(
                project_id,
                workflow_commit_id=workflow_commit_id,
            )
        else:
            compiled = _retained_compiled
        plan = compiled.execution_plan
        workflow_commit_revision = plan.workflow_commit_revision
        if plan.catalog_contract_digest != self._catalog.contract_digest:
            raise V2RunError(
                "contract_digest_mismatch",
                "Compiled FrozenCatalog identity is no longer current",
                details={
                    "issues": [
                        {
                            "code": "catalog_contract_digest_mismatch",
                            "severity": "error",
                            "message": (
                                "Start Run requires the FrozenCatalog used "
                                "during compilation"
                            ),
                            "field_path": ["workflow_commit_id"],
                        }
                    ]
                },
            )
        run_id = f"run-{uuid.uuid4().hex}"
        plan_evidence = self._plan_evidence(plan)
        try:
            ledger = Ledger(
                self._projects,
                project_id,
                run_id,
                plan_evidence,
                self._ledger_transaction_store,
                expected_resolved_contracts=tuple(
                    _exact_contract_reference(entry)
                    for entry in plan.resolved_contracts
                ),
                expected_contract_roots=tuple(
                    _execution_plan_contract_roots(plan)
                ),
            )
        except (OSError, StoragePathError) as error:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence workspace is unavailable",
                details={"last_durable_cursor": run_cursor(0).value},
            ) from error
        ledger.record(
            RunScopeBinding(
                workflow_commit_id=workflow_commit_id,
                workflow_commit_revision=workflow_commit_revision,
                workflow_digest=plan.workflow_digest,
                contract_lock_digest=plan.contract_lock_digest,
                execution_plan_digest=plan.execution_plan_digest,
                catalog_contract_digest=plan.catalog_contract_digest,
                resolved_contract_roots=tuple(
                    _execution_plan_contract_roots(plan)
                ),
                resolved_contracts=tuple(
                    _exact_contract_reference(entry)
                    for entry in plan.resolved_contracts
                ),
                derived_from=(
                    DerivedRunReference(
                        source_run_id=_derived_from["source_run_id"],
                        policy=_derived_from["policy"],
                        selected_node_ids=tuple(
                            _derived_from["selected_node_ids"]
                        ),
                        forced_node_ids=tuple(
                            _derived_from["forced_node_ids"]
                        ),
                    )
                    if _derived_from is not None
                    else None
                ),
            )
        )
        distinct: dict[tuple[str, str], ExecutionPlanNode] = {}
        for node in plan.nodes:
            distinct.setdefault(
                (
                    node.binding.contract_id,
                    node.binding.contract_version,
                ),
                node,
            )
        availability_by_binding: dict[
            tuple[str, str],
            Mapping[str, Any],
        ] = {}
        for binding_key, node in distinct.items():
            availability = self._availability(node)
            availability_by_binding[binding_key] = availability
            ledger.record(
                AvailabilityBinding(
                    binding=_exact_contract_reference(node.binding),
                    catalog_observed_at=availability["observed_at"],
                    available=availability["available"],
                )
            )
        admitted = ledger.record(
            RunAdmission(
                workflow_commit_id=workflow_commit_id,
                workflow_commit_revision=workflow_commit_revision,
            )
        )
        ledger.record(RunStart(started_at=run_timestamp()))

        all_artifacts: list[dict[str, Any]] = []
        record = _RunRecord(
            compiled=compiled,
            ledger=ledger,
        )
        attempts = _NodeExecutionAttemptModule(
            projects=self._projects,
            environment=self._environment,
            result_store=self._result_store,
            project_id=project_id,
            run_id=run_id,
            execution_plan=plan,
            ledger=ledger,
            run_record=record,
            availability_by_binding=availability_by_binding,
        )

        self._runs[(project_id, run_id)] = record
        self._run_owners[run_id] = project_id
        receipt = {
            "project_id": project_id,
            "run_id": run_id,
            "workflow_commit_id": workflow_commit_id,
            "workflow_commit_revision": workflow_commit_revision,
            "admitted_sequence": admitted.last_sequence,
            "event_cursor": admitted.cursor.value,
        }
        if _on_admitted is not None:
            _on_admitted(receipt, record)
        if _before_execute is not None:
            _before_execute()
        committed_values: dict[tuple[str, str], AdmittedPort] = {}
        for node in plan.nodes:
            blocked_by = self._required_input_blockers(
                node,
                committed_values,
            )
            concluded_before_scheduling = False
            cancellation_outcome: Literal["cancelled", "interrupted"] = (
                "interrupted"
                if record.cancellation.cleanup_error is not None
                else "cancelled"
            )
            if blocked_by:
                acknowledged = ledger.record_if_active(
                    UnstartedNodeConclusion(
                        node_id=node.node_id,
                        outcome="blocked",
                        blocked_by=tuple(blocked_by),
                    )
                )
                if acknowledged is None:
                    ledger.record(
                        UnstartedNodeConclusion(
                            node_id=node.node_id,
                            outcome=cancellation_outcome,
                        )
                    )
                concluded_before_scheduling = True
            elif ledger.cancellation_requested:
                ledger.record(
                    UnstartedNodeConclusion(
                        node_id=node.node_id,
                        outcome=cancellation_outcome,
                    )
                )
                concluded_before_scheduling = True
            if concluded_before_scheduling:
                continue
            committed = attempts.execute(
                node,
                committed_values=committed_values,
                committed_artifacts=tuple(all_artifacts),
                cache_bypassed=node.node_id in _cache_bypass_nodes,
            )
            if committed.disposition == "succeeded":
                committed_values.update(committed.admitted_outputs)
                all_artifacts.extend(committed.artifacts)
        selection_conclusions: tuple[SelectionConclusion, ...] = ()
        if ledger.selection_consumer_ids and ledger.all_dispositions_succeeded:
            selection_consumers = {
                node.node_id: node for node in plan.nodes
            }
            try:
                selection_conclusions = tuple(
                    SelectionSuccess(
                        result=_selection_consumer_result(
                            selection_consumers[node_id],
                            committed_values,
                        )
                    )
                    for node_id in ledger.selection_consumer_ids
                )
            except SelectionError as error:
                selection_conclusions = (
                    SelectionFailure(
                        error=_selection_error(error),
                    ),
                )
        ledger.record(RunClosure(selection_conclusions))
        record.finished.set()
        return receipt

    def start_background(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
        client_request_id: str,
        _derived_from: Mapping[str, Any] | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
        _retained_compiled: VerifiedWorkflowCommit | None = None,
    ) -> dict[str, Any]:
        """Admit synchronously, then execute without blocking event delivery."""
        admitted = threading.Event()
        state: dict[str, Any] = {}

        def on_admitted(
            receipt: dict[str, Any],
            record: _RunRecord,
        ) -> None:
            state["receipt"] = json.loads(json.dumps(receipt))
            state["record"] = record
            admitted.set()

        def execute() -> None:
            try:
                def acquire_execution_slot() -> None:
                    self._execution_lock.acquire()
                    state["execution_slot_acquired"] = True

                self.start(
                    project_id,
                    workflow_commit_id=workflow_commit_id,
                    client_request_id=client_request_id,
                    _on_admitted=on_admitted,
                    _before_execute=acquire_execution_slot,
                    _derived_from=_derived_from,
                    _cache_bypass_nodes=_cache_bypass_nodes,
                    _retained_compiled=_retained_compiled,
                )
            except BaseException as error:
                state["error"] = error
                record = state.get("record")
                if isinstance(record, _RunRecord):
                    record.execution_error = error
                    if (
                        isinstance(error, V2RunError)
                        and error.code == "evidence_unavailable"
                    ):
                        record.evidence_unavailable = error
                    record.finished.set()
                    record.ledger.notify_waiters()
            finally:
                if state.get("execution_slot_acquired") is True:
                    self._execution_lock.release()
                with self._worker_condition:
                    self._workers.discard(threading.current_thread())
                    self._reserved_projects.discard(project_id)
                    self._worker_condition.notify_all()
                admitted.set()

        worker = threading.Thread(
            target=execute,
            name=f"v2-run-admission-{project_id}",
            daemon=False,
        )
        with self._worker_condition:
            if (
                self._closed
                or len(self._workers) >= MAX_BACKGROUND_RUNS
                or project_id in self._reserved_projects
            ):
                raise V2RunError(
                    "evidence_unavailable",
                    "Run execution admission is temporarily unavailable",
                    details={"last_durable_cursor": run_cursor(0).value},
                )
            self._workers.add(worker)
            self._reserved_projects.add(project_id)
        try:
            worker.start()
        except BaseException:
            with self._worker_condition:
                self._workers.discard(worker)
                self._reserved_projects.discard(project_id)
                self._worker_condition.notify_all()
            raise
        admitted.wait()
        error = state.get("error")
        if "receipt" not in state:
            if isinstance(error, BaseException):
                raise error
            raise RuntimeError(
                "Background Run admission ended without a receipt or error"
            )
        record = state.get("record")
        if not isinstance(record, _RunRecord):
            raise RuntimeError(
                "Background Run admission did not retain its Run record"
            )
        record.finished.wait(FAST_RUN_COMPLETION_GRACE_SECONDS)
        if record.finished.is_set() and record.execution_error is not None:
            raise record.execution_error
        return state["receipt"]

    @staticmethod
    def _forced_node_closure(
        plan: ExecutionPlan,
        selected_node_ids: frozenset[str],
    ) -> frozenset[str]:
        forced = set(selected_node_ids)
        changed = True
        while changed:
            changed = False
            for node in plan.nodes:
                if (
                    node.node_id not in forced
                    and any(
                        dependency in forced
                        for dependency in node._runtime.dependencies
                    )
                ):
                    forced.add(node.node_id)
                    changed = True
        return frozenset(forced)

    def start_derived_background(
        self,
        project_id: str,
        *,
        source_run_id: str,
        policy: str,
        node_ids: list[str],
        client_request_id: str,
    ) -> dict[str, Any]:
        """Start a new Run from one immutable terminal source reference."""
        source = self._require_record(project_id, source_run_id)
        source_projection = source.ledger.projection()
        terminal_sequence = source_projection.terminal_sequence
        if terminal_sequence is None:
            raise V2RunError(
                "malformed_request",
                "Start Derived Run requires a terminal source Run",
                details={"field_path": ["source_run_id"]},
            )
        compiled = source.compiled
        if compiled is None:
            raise V2RunError(
                "compile_rejected",
                "Derived Run source Execution Plan is unavailable",
                details={
                    "issues": [
                        {
                            "code": "source_execution_plan_unavailable",
                            "severity": "error",
                            "message": (
                                "Derived Run requires the exact in-memory "
                                "Execution Plan retained by its source Run"
                            ),
                            "field_path": ["source_run_id"],
                        }
                    ]
                },
            )
        plan = compiled.execution_plan
        source_scope = source.ledger.run_scope
        if source_scope is None:
            raise RuntimeError("Source Run Ledger has no admitted scope")
        if (
            plan.workflow_commit_revision
            != source_projection.workflow_commit_revision
            or plan.workflow_digest
            != source_projection.workflow_digest
            or source_scope.workflow_commit_id
            != source_projection.workflow_commit_id
            or plan.contract_lock_digest
            != source_scope.contract_lock_digest
            or plan.execution_plan_digest
            != source_scope.execution_plan_digest
            or plan.catalog_contract_digest
            != source_scope.catalog_contract_digest
        ):
            raise V2RunError(
                "contract_digest_mismatch",
                "Retained Execution Plan no longer matches the source Run",
                details={
                    "issues": [
                        {
                            "code": "source_execution_plan_identity_mismatch",
                            "severity": "error",
                            "message": (
                                "Derived Run requires the exact immutable "
                                "source Execution Plan identity"
                            ),
                            "field_path": ["source_run_id"],
                        }
                    ]
                },
            )
        plan_node_ids = tuple(node.node_id for node in plan.nodes)
        selected = frozenset(node_ids)
        if (
            not node_ids
            or len(selected) != len(node_ids)
            or not selected <= frozenset(plan_node_ids)
        ):
            raise V2RunError(
                "compile_rejected",
                "Derived Run selection is not a closed Plan selection",
                details={
                    "issues": [
                        {
                            "code": "invalid_derived_node_selection",
                            "severity": "error",
                            "message": (
                                "node_ids must be unique Node Instances in "
                                "the immutable source Execution Plan"
                            ),
                            "field_path": ["node_ids"],
                        }
                    ]
                },
            )
        source_outcomes = {
            disposition.node_id: disposition.outcome
            for disposition in source_projection.node_dispositions
        }
        if policy == "retry_failed" and any(
            source_outcomes.get(node_id) != "failed"
            for node_id in selected
        ):
            raise V2RunError(
                "compile_rejected",
                "retry_failed may select only failed source Nodes",
                details={
                    "issues": [
                        {
                            "code": "retry_requires_failed_source_node",
                            "severity": "error",
                            "message": (
                                "retry_failed node_ids must identify failed "
                                "source Run Node Dispositions"
                            ),
                            "field_path": ["node_ids"],
                        }
                    ]
                },
            )
        forced = (
            selected
            if policy == "retry_failed"
            else self._forced_node_closure(plan, selected)
        )
        selected_in_plan_order = [
            node_id for node_id in plan_node_ids if node_id in selected
        ]
        forced_in_plan_order = [
            node_id for node_id in plan_node_ids if node_id in forced
        ]
        return self.start_background(
            project_id,
            workflow_commit_id=source_projection.workflow_commit_id,
            client_request_id=client_request_id,
            _derived_from={
                "source_run_id": source_run_id,
                "policy": policy,
                "selected_node_ids": selected_in_plan_order,
                "forced_node_ids": forced_in_plan_order,
            },
            _cache_bypass_nodes=forced,
            _retained_compiled=compiled,
        )

    def cancel(
        self,
        project_id: str,
        run_id: str,
        *,
        after_cursor: RunCursor | None,
    ) -> CancellationDecision:
        """Persist cancellation before signalling active work."""
        record = self._require_record(project_id, run_id)
        self._require_available_evidence(record)
        decision = record.ledger.request_cancellation(after_cursor)
        if decision.outcome in {
            "cancellation_requested",
            "already_requested",
        }:
            record.cancellation.request()
        return decision

    def shutdown(self) -> None:
        """Stop admission and wait until every tracked Run writer is closed."""
        with self._worker_condition:
            self._closed = True
            workers = tuple(self._workers)
        for worker in workers:
            worker.join()

    def projection(self, project_id: str, run_id: str) -> RunProjection:
        record = self._require_record(project_id, run_id)
        self._require_available_evidence(record)
        return record.ledger.projection()

    @staticmethod
    def _typed_value_integrity_error(
        descriptor: PublishedOutput,
        value_index: int,
        *,
        expected_digest: str,
        expected_size: int | None = None,
    ) -> V2RunError:
        details: dict[str, Any] = {
            "node_id": descriptor.node_id,
            "output_port": descriptor.output_port,
            "value_index": value_index,
            "expected_digest": expected_digest,
        }
        if expected_size is not None:
            details["expected_size"] = expected_size
        return V2RunError(
            "typed_value_integrity_mismatch",
            "Typed Output value failed integrity verification",
            details=details,
        )

    def typed_value(
        self,
        project_id: str,
        run_id: str,
        node_id: str,
        output_port: str,
        value_index: int,
    ) -> tuple[dict[str, Any], bytes]:
        """Resolve one exact canonical value through committed Run evidence."""
        record = self._require_record(project_id, run_id)
        descriptor = next(
            (
                output
                for output in record.ledger.projection().outputs
                if output.node_id == node_id
                and output.output_port == output_port
            ),
            None,
        )
        if (
            descriptor is None
            or type(value_index) is not int
            or value_index < 0
            or value_index >= descriptor.value_count
        ):
            raise V2RunError(
                "typed_output_not_found",
                "Typed Output value was not found",
                details={
                    "node_id": node_id,
                    "output_port": output_port,
                    "value_index": value_index,
                },
            )
        try:
            value = self._result_store.read_typed_value(
                project_id,
                descriptor,
                value_index,
            )
        except ResultIntegrityError as error:
            raise self._typed_value_integrity_error(
                descriptor,
                value_index,
                expected_digest=error.content_digest,
                expected_size=error.expected_size,
            ) from error
        metadata = {
            "typed_value": {
                "node_id": node_id,
                "output_port": output_port,
                "port_type": {
                    "contract_kind": descriptor.port_type.contract_kind,
                    "contract_id": descriptor.port_type.contract_id,
                    "contract_version": descriptor.port_type.contract_version,
                    "contract_digest": descriptor.port_type.contract_digest,
                },
                "port_content_digest": descriptor.content_digest,
                "value_manifest_reference": descriptor.value_manifest_reference,
                "value_index": value_index,
                "value_count": descriptor.value_count,
                "value_content_digest": value.content_digest,
                "size": value.size,
            }
        }
        return json.loads(json.dumps(metadata)), value.canonical_bytes

    def artifact(
        self,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        record = self._require_record(project_id, run_id)
        descriptor = next(
            (
                artifact
                for artifact in record.ledger.projection().artifacts
                if artifact.artifact_reference == artifact_reference
            ),
            None,
        )
        if descriptor is None:
            raise V2RunError(
                "artifact_not_found",
                "Artifact was not found",
                details={
                    "resource_kind": "artifact",
                    "resource_id": artifact_reference,
                },
            )
        try:
            payload = self._result_store.read_artifact(
                project_id,
                descriptor,
            )
        except ResultIntegrityError as error:
            raise V2RunError(
                "artifact_integrity_mismatch",
                "Artifact integrity validation failed",
                details={"artifact_reference": artifact_reference},
            ) from error
        public_descriptor = {
            "artifact_reference": descriptor.artifact_reference,
            "artifact_kind": descriptor.artifact_kind,
            "node_id": descriptor.node_id,
            "output_port": descriptor.output_port,
            "media_type": descriptor.media_type,
            "filename": descriptor.filename,
            "size": descriptor.size,
            "content_digest": descriptor.content_digest,
        }
        if descriptor.candidate_id is not None:
            public_descriptor["candidate_id"] = descriptor.candidate_id
        return public_descriptor, payload

    def events(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[Fact, ...]:
        record = self._require_record(project_id, run_id)
        self._require_available_evidence(record)
        return record.ledger.events()

    def ledger_cursor(self, project_id: str, run_id: str) -> RunCursor:
        return self._require_record(project_id, run_id).ledger.cursor

    def replay(
        self,
        project_id: str,
        run_id: str,
        cursor: RunCursor | None,
    ) -> ReplayWindow:
        record = self._require_record(
            project_id,
            run_id,
        )
        self._require_available_evidence(record)
        return record.ledger.replay(cursor)

    def wait_for_events(
        self,
        project_id: str,
        run_id: str,
        after_sequence: int,
        *,
        timeout_seconds: float = 1.0,
    ) -> tuple[tuple[Fact, ...], int, bool]:
        record = self._require_record(
            project_id,
            run_id,
        )
        self._require_available_evidence(record)
        observed = record.ledger.wait_for_events(
            after_sequence,
            timeout_seconds=timeout_seconds,
        )
        self._require_available_evidence(record)
        return observed
