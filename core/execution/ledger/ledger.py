"""Run Evidence Ledger authority: causality, atomic publication, replay, restart."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import threading
from typing import Any, Literal

from core.catalog.port_contract import canonical_sha256
from core.execution.ledger.codec import (
    LedgerTransaction,
    contract_lock_digest,
    cursor_scope_digest,
    decode_cursor,
    decode_transaction,
    encode_cursor,
    encode_transaction,
    readiness_attestation_digest,
)
from core.execution.ledger.facts import (
    AvailabilityBound,
    CancellationRequested,
    DerivedRunReference,
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    FactPayload,
    NodeAttemptStarted,
    NodeAttemptTerminal,
    NodeDisposition,
    OperationAttemptStarted,
    OperationAttemptTerminal,
    OutputsPublished,
    ReadinessAttested,
    RunAdmitted,
    RunScopeBound,
    RunStarted,
    RunTerminal,
    SelectionTerminal,
    validate_fact_payload,
)
from core.execution.ledger.reducer import (
    InvocationState,
    LedgerReducerState,
    NodeAttemptState,
    OperationAttemptState,
)
from core.execution.ledger.projections import (
    CancellationDecision,
    ReplayWindow,
    RunCursor,
    RunProjection,
    event_facts,
    project_run,
)
from core.execution.ledger.store import FilesystemLedgerStore, LedgerStore
from core.execution.ledger.transitions import (
    AvailabilityBinding,
    EngineInvocationConclusion,
    EngineInvocationStart,
    LedgerAcknowledgement,
    LedgerTransition,
    NodeAttemptStart,
    NodeFailurePublication,
    NodeSuccessPublication,
    NodeTerminationPublication,
    OperationAttemptStart,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
    ReadinessAttestation,
    RunAdmission,
    RunClosure,
    RunScopeBinding,
    RunStart,
    SelectionFailure,
    SelectionSuccess,
    UnstartedNodeConclusion,
)
from core.project.manager import ProjectManager
from core.project.storage import (
    StoragePathError,
    validate_identifier,
)
from datatypes.exact_reference import ExactContractReference


READINESS_ATTESTATION_NAMESPACE = "protein-workbench-readiness-attestation/v2"
MAX_LEDGER_TRANSACTION_BYTES = 4 * 1024 * 1024


class V2RunError(RuntimeError):
    """A closed Run failure safe to expose through a transport adapter."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any]) -> None:
        self.code = code
        self.details = dict(details)
        super().__init__(message)


def _typed_reference_key(
    reference: ExactContractReference,
) -> tuple[str, str, str, str]:
    return (
        reference.contract_kind,
        reference.contract_id,
        reference.contract_version,
        reference.contract_digest,
    )


def _typed_run_terminal_status(
    dispositions: Iterable[NodeDisposition],
    selection_terminals: tuple[SelectionTerminal, ...],
) -> Literal["succeeded", "failed", "cancelled", "interrupted"]:
    outcomes = {
        disposition.outcome for disposition in dispositions
    }
    if "failed" in outcomes or any(
        terminal.status == "failed"
        for terminal in selection_terminals
    ):
        return "failed"
    if "interrupted" in outcomes:
        return "interrupted"
    if "cancelled" in outcomes:
        return "cancelled"
    return "succeeded"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_timestamp(value: datetime | None = None) -> str:
    observed = value or _utc_now()
    return observed.astimezone(timezone.utc).isoformat()


def run_cursor(
    sequence: int,
    *,
    project_id: str = "unavailable",
    run_id: str = "unavailable",
    fact: Fact | None = None,
) -> RunCursor:
    return encode_cursor(
        sequence,
        project_id=project_id,
        run_id=run_id,
        fact=fact,
    )


def _safe_cursor_detail(value: RunCursor) -> str:
    if type(value) is not RunCursor or not value.value:
        return "invalid"
    return value.value[:512]


class Ledger:
    """Causally closed typed evidence authority for one Run."""

    def __init__(
        self,
        projects: ProjectManager,
        project_id: str,
        run_id: str,
        plan_nodes: tuple[PlanNodeEvidence, ...],
        transaction_store: LedgerStore | None = None,
        *,
        expected_resolved_contracts: tuple[ExactContractReference, ...],
        expected_contract_roots: tuple[ExactContractReference, ...],
    ) -> None:
        run_dir = projects.run_storage_directory(project_id, run_id)
        self._root = run_dir.parent
        self._project_id = project_id
        self._run_id = run_id
        self._plan_node_order = tuple(node.node_id for node in plan_nodes)
        self._plan_nodes = frozenset(self._plan_node_order)
        self._dependencies = {
            node.node_id: frozenset(node.dependencies)
            for node in plan_nodes
        }
        self._required_input_sources = {
            node.node_id: node.required_input_sources
            for node in plan_nodes
        }
        self._plan_evidence = plan_nodes
        self._bindings_by_node = {
            node.node_id: node.binding for node in plan_nodes
        }
        self._execution_routes = {
            node.node_id: node.execution_route for node in plan_nodes
        }
        self._expected_binding_keys = frozenset(
            _typed_reference_key(node.binding)
            for node in plan_nodes
        )
        self._provider_binding_keys = frozenset(
            _typed_reference_key(node.binding)
            for node in plan_nodes
            if node.execution_route == "adapter"
        )
        minimum_roots = tuple(
            reference
            for node in plan_nodes
            for reference in (
                node.binding,
                *((node.node_type,) if node.node_type is not None else ()),
            )
        )
        minimum_contracts = (
            *minimum_roots,
            *(
                output.port_type
                for node in plan_nodes
                for output in node.artifact_outputs
            ),
        )
        self._minimum_contract_root_keys = frozenset(
            _typed_reference_key(reference) for reference in minimum_roots
        )
        self._minimum_resolved_contract_keys = frozenset(
            _typed_reference_key(reference)
            for reference in minimum_contracts
        )
        self._expected_contract_roots = expected_contract_roots
        self._expected_resolved_contracts = expected_resolved_contracts
        self._result_identity_plan_facts_digests = {
            node.node_id: node.result_identity_plan_facts_digest
            for node in plan_nodes
        }
        self._node_types = {
            node.node_id: (
                node.node_type if node.node_type is not None else None
            )
            for node in plan_nodes
        }
        self._artifact_outputs = {
            node.node_id: node.artifact_outputs
            for node in plan_nodes
        }
        self._selection_consumer_ids = tuple(
            node.node_id for node in plan_nodes if node.selection_consumer
        )
        self._state = LedgerReducerState.empty()
        self._transaction_count = 0
        self._committed_fact_count = 0
        self._transaction_store = (
            FilesystemLedgerStore()
            if transaction_store is None
            else transaction_store
        )
        self._condition = threading.Condition(threading.RLock())
        self._evidence_unavailable: V2RunError | None = None

    @classmethod
    def load(
        cls,
        projects: ProjectManager,
        project_id: str,
        run_id: str,
        store: LedgerStore | None = None,
    ) -> Ledger | None:
        """Decode, admit, and causally replay one persisted Run Ledger."""
        run_dir = projects.run_storage_directory(project_id, run_id)
        transaction_store = FilesystemLedgerStore() if store is None else store
        transactions = transaction_store.read_transactions(
            root=run_dir.parent,
            relative_parts=(run_id, "ledger"),
        )
        if not transactions:
            return None
        encoded_transactions: list[bytes] = []
        for expected_sequence, (name, encoded) in enumerate(
            transactions,
            start=1,
        ):
            if name != f"{expected_sequence:020d}.json":
                raise RuntimeError(
                    "Run Ledger transaction sequence is not contiguous"
                )
            if len(encoded) > MAX_LEDGER_TRANSACTION_BYTES:
                raise RuntimeError("Run Ledger transaction exceeds its bound")
            encoded_transactions.append(encoded)
        try:
            first = decode_transaction(
                encoded_transactions[0],
                expected_project_id=project_id,
                expected_run_id=run_id,
                expected_transaction_sequence=1,
                expected_first_fact_sequence=1,
            )
            scope = first.facts[0].payload
            if not isinstance(scope, RunScopeBound):
                raise ValueError("Run Ledger begins without a bound scope")
            ledger = cls(
                projects,
                project_id,
                run_id,
                scope.plan_nodes,
                transaction_store,
                expected_resolved_contracts=scope.resolved_contracts,
                expected_contract_roots=scope.resolved_contract_roots,
            )
            ledger._install_loaded_transaction(first)
            for encoded in encoded_transactions[1:]:
                ledger._load_transaction(encoded)
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Run Ledger transaction is invalid") from error
        return ledger

    def _mark_evidence_unavailable(self, error: V2RunError) -> None:
        if self._evidence_unavailable is None:
            self._evidence_unavailable = error
        self._condition.notify_all()

    def retain_evidence_unavailable(self, error: V2RunError) -> None:
        """Order one unavailable-evidence decision against Run writers."""
        with self._condition:
            self._mark_evidence_unavailable(error)

    def _require_available_evidence(self) -> None:
        unavailable = self._evidence_unavailable
        if unavailable is not None:
            raise V2RunError(
                unavailable.code,
                str(unavailable),
                details=unavailable.details,
            ) from unavailable

    def _install_reducer_state(self, state: LedgerReducerState) -> None:
        self._state = state

    @property
    def facts(self) -> tuple[Fact, ...]:
        with self._condition:
            return tuple(self._state.facts)

    @property
    def cursor(self) -> RunCursor:
        with self._condition:
            return self._cursor_at(self._committed_fact_count)

    @property
    def terminal(self) -> bool:
        with self._condition:
            return self._state.run_terminal

    @property
    def admitted(self) -> bool:
        with self._condition:
            return self._state.run_admitted

    @property
    def run_scope(self) -> RunScopeBinding | None:
        """Project the admitted immutable Run scope as its typed value."""
        with self._condition:
            if not self._state.facts:
                return None
            payload = self._state.facts[0].payload
            if not isinstance(payload, RunScopeBound):
                raise self._causal_error()
            return RunScopeBinding(
                workflow_commit_id=payload.workflow_commit_id,
                workflow_commit_revision=payload.workflow_commit_revision,
                workflow_digest=payload.workflow_digest,
                contract_lock_digest=payload.contract_lock_digest,
                execution_plan_digest=payload.execution_plan_digest,
                catalog_contract_digest=payload.catalog_contract_digest,
                resolved_contracts=payload.resolved_contracts,
                resolved_contract_roots=payload.resolved_contract_roots,
                derived_from=payload.derived_from,
            )

    @property
    def cancellation_requested(self) -> bool:
        with self._condition:
            return self._state.cancellation_sequence is not None

    @property
    def all_dispositions_succeeded(self) -> bool:
        """Return whether the durable Plan disposition set is all-success."""
        with self._condition:
            return (
                set(self._state.dispositions) == set(self._plan_nodes)
                and all(
                    disposition.outcome == "succeeded"
                    for disposition in self._state.dispositions.values()
                )
            )

    @property
    def selection_consumer_ids(self) -> tuple[str, ...]:
        """Return the Selection consumers fixed by durable Run scope."""
        return self._selection_consumer_ids

    @property
    def plan_nodes(self) -> tuple[PlanNodeEvidence, ...]:
        return self._plan_evidence

    def _cursor_at(self, sequence: int) -> RunCursor:
        fact = self._state.facts[sequence - 1] if sequence else None
        return run_cursor(
            sequence,
            project_id=self._project_id,
            run_id=self._run_id,
            fact=fact,
        )

    def sequence_for_cursor(self, cursor: RunCursor | None) -> int:
        if cursor is None:
            return 0
        try:
            payload = decode_cursor(cursor)
        except ValueError as error:
            raise V2RunError(
                "invalid_cursor",
                "Run Event Stream cursor is invalid",
                details={"after_sequence": _safe_cursor_detail(cursor)},
            ) from error
        sequence = payload.sequence
        with self._condition:
            expected = (
                self._cursor_at(sequence)
                if sequence <= len(self._state.facts)
                else None
            )
        if (
            payload.scope_digest
            != cursor_scope_digest(self._project_id, self._run_id)
            or expected != cursor
        ):
            raise V2RunError(
                "invalid_cursor",
                "Run Event Stream cursor is stale or belongs to another scope",
                details={"after_sequence": _safe_cursor_detail(cursor)},
            )
        return sequence

    def cursor_at(self, sequence: int) -> RunCursor:
        with self._condition:
            if sequence < 0 or sequence > len(self._state.facts):
                raise ValueError("Ledger cursor sequence is outside the Run")
            return self._cursor_at(sequence)

    def record(
        self,
        transition: LedgerTransition,
    ) -> LedgerAcknowledgement:
        """Validate and durably acknowledge one complete legal transition."""
        if isinstance(transition, RunScopeBinding):
            return self._record_run_scope(transition)
        if isinstance(transition, AvailabilityBinding):
            return self._record_availability(transition)
        if isinstance(transition, RunAdmission):
            return self._record_run_admission(transition)
        if isinstance(transition, RunStart):
            return self._record_run_start(transition)
        if isinstance(transition, ReadinessAttestation):
            return self._record_readiness(transition)
        if isinstance(transition, NodeAttemptStart):
            return self._record_node_attempt_start(transition)
        if isinstance(transition, OperationAttemptStart):
            return self._record_operation_attempt_start(transition)
        if isinstance(transition, EngineInvocationStart):
            return self._record_engine_invocation_start(transition)
        if isinstance(transition, EngineInvocationConclusion):
            return self._record_engine_invocation_conclusion(transition)
        if isinstance(transition, NodeSuccessPublication):
            return self._record_node_success(transition)
        if isinstance(transition, NodeFailurePublication):
            return self._record_node_failure(transition)
        if isinstance(transition, NodeTerminationPublication):
            return self._record_node_termination(transition)
        if isinstance(transition, UnstartedNodeConclusion):
            return self._record_unstarted_node(transition)
        if isinstance(transition, RunClosure):
            return self._record_run_closure(transition)
        raise TypeError("Run Evidence Ledger transition is not current")

    def record_if_active(
        self,
        transition: LedgerTransition,
    ) -> LedgerAcknowledgement | None:
        """Atomically reject a transition when cancellation already won."""
        with self._condition:
            if self._state.cancellation_sequence is not None:
                return None
            return self.record(transition)

    def _record_run_scope(
        self,
        scope: RunScopeBinding,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                RunScopeBound(
                    project_id=self._project_id,
                    run_id=self._run_id,
                    workflow_commit_id=scope.workflow_commit_id,
                    workflow_commit_revision=scope.workflow_commit_revision,
                    workflow_digest=scope.workflow_digest,
                    contract_lock_digest=scope.contract_lock_digest,
                    execution_plan_digest=scope.execution_plan_digest,
                    catalog_contract_digest=scope.catalog_contract_digest,
                    resolved_contracts=scope.resolved_contracts,
                    resolved_contract_roots=scope.resolved_contract_roots,
                    plan_nodes=self.plan_nodes,
                    selection_required=bool(self._selection_consumer_ids),
                    selection_terminal_keys=self._selection_consumer_ids,
                    derived_from=scope.derived_from,
                ),
            )
        )

    def _record_availability(
        self,
        availability: AvailabilityBinding,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                AvailabilityBound(
                    binding=availability.binding,
                    catalog_observed_at=availability.catalog_observed_at,
                    available=availability.available,
                ),
            )
        )

    def _record_run_admission(
        self,
        admission: RunAdmission,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                RunAdmitted(
                    admission.workflow_commit_id,
                    admission.workflow_commit_revision,
                ),
            )
        )

    def _record_run_start(
        self,
        transition: RunStart,
    ) -> LedgerAcknowledgement:
        return self._commit((RunStarted(transition.started_at),))

    def _record_readiness(
        self,
        attestation: ReadinessAttestation,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                ReadinessAttested(
                    binding=attestation.binding,
                    readiness_contract_digest=(
                        attestation.readiness_contract_digest
                    ),
                    observed_at=attestation.observed_at,
                    conclusion=attestation.conclusion,
                    proof_source=attestation.proof_source,
                    attestation_digest=readiness_attestation_digest(
                        binding=attestation.binding,
                        readiness_contract_digest=(
                            attestation.readiness_contract_digest
                        ),
                        observed_at=attestation.observed_at,
                        conclusion=attestation.conclusion,
                        proof_source=attestation.proof_source,
                    ),
                ),
            )
        )

    def _record_node_attempt_start(
        self,
        transition: NodeAttemptStart,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                NodeAttemptStarted(
                    transition.node_id,
                    transition.node_attempt_id,
                ),
            )
        )

    def _record_operation_attempt_start(
        self,
        transition: OperationAttemptStart,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                OperationAttemptStarted(
                    transition.operation_attempt_id,
                    transition.node_attempt_id,
                ),
            )
        )

    def _record_engine_invocation_start(
        self,
        transition: EngineInvocationStart,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                EngineInvocationStarted(
                    invocation_id=transition.invocation_id,
                    operation_attempt_id=transition.operation_attempt_id,
                    engine_role=transition.engine_role,
                    engine_identity=transition.engine_identity,
                    parent_invocation_id=transition.parent_invocation_id,
                    provenance=transition.provenance,
                ),
            )
        )

    def _record_engine_invocation_conclusion(
        self,
        conclusion: EngineInvocationConclusion,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                EngineInvocationTerminal(
                    invocation_id=conclusion.invocation_id,
                    status=conclusion.status,
                    error=conclusion.error,
                ),
            )
        )

    def _record_node_success(
        self,
        publication: NodeSuccessPublication,
    ) -> LedgerAcknowledgement:
        outputs = publication.outputs
        artifacts = publication.artifacts
        facts: list[FactPayload] = []
        if publication.operation_attempt_id is not None:
            facts.append(
                OperationAttemptTerminal(
                    publication.operation_attempt_id,
                    "succeeded",
                )
            )
        facts.append(
            OutputsPublished(
                node_id=publication.node_id,
                result_identity=publication.result_identity,
                node_result_manifest=publication.node_result_manifest,
                outputs=outputs,
                artifacts=artifacts,
            )
        )
        facts.extend(
            (
                NodeAttemptTerminal(
                    node_attempt_id=publication.node_attempt_id,
                    status="succeeded",
                    resolution=publication.resolution,
                ),
                NodeDisposition(
                    node_id=publication.node_id,
                    outcome="succeeded",
                    resolution=publication.resolution,
                    blocked_by=(),
                ),
            )
        )
        return self._commit(tuple(facts))

    def _record_node_failure(
        self,
        publication: NodeFailurePublication,
    ) -> LedgerAcknowledgement:
        error = publication.error
        facts: list[FactPayload] = []
        if publication.operation_attempt_id is not None:
            operation_status = (
                "failed"
                if publication.failure_origin == "operation"
                else "succeeded"
            )
            facts.append(
                OperationAttemptTerminal(
                    operation_attempt_id=publication.operation_attempt_id,
                    status=operation_status,
                    error=error if operation_status == "failed" else None,
                )
            )
        facts.extend(
            (
                NodeAttemptTerminal(
                    node_attempt_id=publication.node_attempt_id,
                    status="failed",
                    resolution=publication.resolution,
                    error=error,
                    failure_origin=publication.failure_origin,
                ),
                NodeDisposition(
                    publication.node_id,
                    "failed",
                    (),
                ),
            )
        )
        return self._commit(tuple(facts))

    def _record_node_termination(
        self,
        publication: NodeTerminationPublication,
    ) -> LedgerAcknowledgement:
        disposition = (
            "interrupted"
            if publication.status == "outcome_unknown"
            else publication.status
        )
        error = publication.error
        facts: list[FactPayload] = []
        if publication.operation_attempt_id is not None:
            facts.append(
                OperationAttemptTerminal(
                    operation_attempt_id=publication.operation_attempt_id,
                    status=publication.operation_status,
                    error=(
                        error
                        if publication.operation_status != "succeeded"
                        else None
                    ),
                )
            )
        facts.extend(
            (
                NodeAttemptTerminal(
                    node_attempt_id=publication.node_attempt_id,
                    status=publication.status,
                    resolution=publication.resolution,
                    error=error,
                ),
                NodeDisposition(
                    publication.node_id,
                    disposition,
                    (),
                ),
            )
        )
        return self._commit(tuple(facts))

    def _record_unstarted_node(
        self,
        conclusion: UnstartedNodeConclusion,
    ) -> LedgerAcknowledgement:
        return self._commit(
            (
                NodeDisposition(
                    conclusion.node_id,
                    conclusion.outcome,
                    conclusion.blocked_by,
                ),
            )
        )

    def _record_run_closure(
        self,
        closure: RunClosure,
    ) -> LedgerAcknowledgement:
        selections = tuple(
            (
                SelectionTerminal(
                    status="succeeded",
                    result=selection.result,
                )
                if isinstance(selection, SelectionSuccess)
                else SelectionTerminal(
                    status="failed",
                    error=selection.error,
                )
            )
            for selection in closure.selections
        )
        run_status = _typed_run_terminal_status(
            self._state.dispositions.values(),
            selections,
        )
        return self._commit(
            (
                *selections,
                RunTerminal(run_status),
            )
        )

    def _causal_error(self) -> V2RunError:
        return V2RunError(
            "evidence_unavailable",
            "Required Run evidence failed causal validation",
            details={"last_durable_cursor": self.cursor.value},
        )

    def _required_input_blocker_set(self, node_id: str) -> frozenset[str]:
        blockers: set[str] = set()
        for required_input in self._required_input_sources[node_id]:
            if any(
                source.output_port
                in self._state.nonempty_output_ports.get(source.node_id, set())
                for source in required_input.sources
            ):
                continue
            blockers.update(source.node_id for source in required_input.sources)
        return frozenset(blockers)

    def _validate_causality(self, payload: FactPayload) -> None:
        if self._state.run_terminal:
            raise self._causal_error()
        if isinstance(payload, RunScopeBound):
            try:
                workflow_commit_id = validate_identifier(
                    payload.workflow_commit_id,
                    "workflow_commit_id",
                )
            except StoragePathError as error:
                raise self._causal_error() from error
            if (
                self._state.facts
                or payload.project_id != self._project_id
                or payload.run_id != self._run_id
                or workflow_commit_id != payload.workflow_commit_id
                or payload.workflow_commit_revision < 1
                or payload.plan_nodes != self.plan_nodes
                or tuple(
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                )
                != tuple(
                    sorted(
                        {
                            _typed_reference_key(reference)
                            for reference in payload.resolved_contracts
                        }
                    )
                )
                or tuple(
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                )
                != tuple(
                    sorted(
                        {
                            _typed_reference_key(reference)
                            for reference in payload.resolved_contract_roots
                        }
                    )
                )
                or tuple(
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                )
                != tuple(
                    _typed_reference_key(reference)
                    for reference in self._expected_resolved_contracts
                )
                or tuple(
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                )
                != tuple(
                    _typed_reference_key(reference)
                    for reference in self._expected_contract_roots
                )
                or not self._minimum_contract_root_keys
                <= {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                }
                or not self._minimum_resolved_contract_keys
                <= {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                }
                or not {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                }
                <= {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                }
                or payload.contract_lock_digest
                != contract_lock_digest(payload.resolved_contracts)
                or payload.selection_required
                != bool(self._selection_consumer_ids)
                or payload.selection_terminal_keys
                != self._selection_consumer_ids
            ):
                raise self._causal_error()
            return
        if (
            not self._state.facts
            or not isinstance(self._state.facts[0].payload, RunScopeBound)
        ):
            raise self._causal_error()
        scope = self._state.facts[0].payload
        if isinstance(payload, AvailabilityBound):
            binding_key = _typed_reference_key(payload.binding)
            if (
                self._state.run_admitted
                or binding_key not in self._expected_binding_keys
                or binding_key in self._state.availability_by_binding
            ):
                raise self._causal_error()
            return
        if isinstance(payload, RunAdmitted):
            if (
                self._state.run_admitted
                or self._state.run_started
                or payload.workflow_commit_id != scope.workflow_commit_id
                or payload.workflow_commit_revision
                != scope.workflow_commit_revision
                or set(self._state.availability_by_binding)
                != set(self._expected_binding_keys)
            ):
                raise self._causal_error()
            return
        if isinstance(payload, RunStarted):
            if not self._state.run_admitted or self._state.run_started:
                raise self._causal_error()
            return
        if isinstance(payload, ReadinessAttested):
            binding_key = _typed_reference_key(payload.binding)
            availability = self._state.availability_by_binding.get(binding_key)
            if (
                not self._state.run_started
                or binding_key not in self._provider_binding_keys
                or availability is None
                or availability.available is not True
                or binding_key in self._state.readiness_by_binding
                or payload.attestation_digest
                != readiness_attestation_digest(
                    binding=payload.binding,
                    readiness_contract_digest=(
                        payload.readiness_contract_digest
                    ),
                    observed_at=payload.observed_at,
                    conclusion=payload.conclusion,
                    proof_source=payload.proof_source,
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, CancellationRequested):
            if (
                not self._state.run_started
                or self._state.cancellation_sequence is not None
            ):
                raise self._causal_error()
            return
        if isinstance(payload, NodeAttemptStarted):
            node_id = payload.node_id
            attempt_id = payload.node_attempt_id
            if (
                not self._state.run_started
                or self._state.cancellation_sequence is not None
                or node_id not in self._plan_nodes
                or node_id in self._state.node_attempt_by_node
                or node_id in self._state.dispositions
                or attempt_id in self._state.node_attempts
                or any(
                    upstream not in self._state.dispositions
                    for upstream in self._dependencies[node_id]
                )
                or self._required_input_blocker_set(node_id)
            ):
                raise self._causal_error()
            return
        if isinstance(payload, OperationAttemptStarted):
            attempt_id = payload.node_attempt_id
            operation_id = payload.operation_attempt_id
            attempt = self._state.node_attempts.get(attempt_id)
            if attempt is None:
                raise self._causal_error()
            node_id = attempt.node_id
            binding_key = _typed_reference_key(
                self._bindings_by_node[node_id]
            )
            readiness = self._state.readiness_by_binding.get(binding_key)
            if (
                self._state.cancellation_sequence is not None
                or attempt.terminal is not None
                or operation_id in self._state.operations
                or any(
                    operation.node_attempt_id == attempt_id
                    for operation in self._state.operations.values()
                )
                or (
                    self._execution_routes[node_id] == "adapter"
                    and (
                        readiness is None
                        or readiness.conclusion != "passing"
                    )
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, EngineInvocationStarted):
            operation_id = payload.operation_attempt_id
            invocation_id = payload.invocation_id
            parent_invocation_id = payload.parent_invocation_id
            operation = self._state.operations.get(operation_id)
            parent = (
                self._state.invocations.get(parent_invocation_id)
                if parent_invocation_id is not None
                else None
            )
            if (
                self._state.cancellation_sequence is not None
                or operation is None
                or operation.terminal is not None
                or invocation_id in self._state.invocations
                or (
                    parent_invocation_id is not None
                    and (
                        parent is None
                        or parent.operation_attempt_id != operation_id
                        or parent.terminal != "succeeded"
                    )
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, EngineInvocationTerminal):
            invocation = self._state.invocations.get(payload.invocation_id)
            if (
                invocation is None
                or invocation.terminal is not None
                or (
                    payload.status == "cancelled"
                    and self._state.cancellation_sequence is None
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, OperationAttemptTerminal):
            operation_id = payload.operation_attempt_id
            operation = self._state.operations.get(operation_id)
            if (
                operation is None
                or operation.terminal is not None
                or (
                    payload.status == "cancelled"
                    and self._state.cancellation_sequence is None
                )
                or any(
                    invocation.operation_attempt_id == operation_id
                    and invocation.terminal is None
                    for invocation in self._state.invocations.values()
                )
                or (
                    payload.status == "succeeded"
                    and any(
                        invocation.operation_attempt_id == operation_id
                        and invocation.terminal != "succeeded"
                        for invocation in self._state.invocations.values()
                    )
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, OutputsPublished):
            node_id = payload.node_id
            attempt_id = self._state.node_attempt_by_node.get(node_id)
            attempt = (
                self._state.node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if (
                self._state.cancellation_sequence is not None
                or attempt is None
                or attempt.terminal is not None
                or node_id in self._state.dispositions
                or node_id in self._state.outputs_published
            ):
                raise self._causal_error()
            child_operations = [
                operation_id
                for operation_id, operation in self._state.operations.items()
                if operation.node_attempt_id == attempt_id
            ]
            if child_operations and any(
                self._state.operations[operation_id].terminal != "succeeded"
                for operation_id in child_operations
            ):
                raise self._causal_error()
            return
        if isinstance(payload, NodeAttemptTerminal):
            attempt_id = payload.node_attempt_id
            attempt = self._state.node_attempts.get(attempt_id)
            child_operations = [
                operation
                for operation in self._state.operations.values()
                if operation.node_attempt_id == attempt_id
            ]
            if (
                attempt is None
                or attempt.terminal is not None
                or (
                    payload.status == "cancelled"
                    and self._state.cancellation_sequence is None
                )
                or any(operation.terminal is None for operation in child_operations)
                or (
                    payload.resolution == "cache_replayed"
                    and (
                        child_operations
                        or (
                            payload.status == "succeeded"
                            and attempt.node_id
                            not in self._state.outputs_published
                        )
                        or (
                            payload.status == "failed"
                            and attempt.node_id
                            in self._state.outputs_published
                        )
                    )
                )
                or (
                    payload.resolution == "executed"
                    and payload.status == "succeeded"
                    and len(child_operations) != 1
                )
                or (
                    payload.resolution == "executed"
                    and child_operations
                    and child_operations[-1].terminal != payload.status
                    and not (
                        payload.status == "failed"
                        and payload.failure_origin == "publication"
                        and child_operations[-1].terminal == "succeeded"
                    )
                    and not (
                        self._state.cancellation_sequence is not None
                        and payload.status
                        in {"cancelled", "interrupted", "outcome_unknown"}
                        and child_operations[-1].terminal
                        in {
                            "succeeded",
                            "cancelled",
                            "interrupted",
                            "outcome_unknown",
                        }
                    )
                )
            ):
                raise self._causal_error()
            failure_origin = payload.failure_origin
            if failure_origin == "operation" and (
                payload.resolution != "executed"
                or len(child_operations) != 1
                or child_operations[0].terminal != "failed"
            ):
                raise self._causal_error()
            if failure_origin == "attempt" and (
                payload.resolution != "executed" or child_operations
            ):
                raise self._causal_error()
            if failure_origin == "binding" and (
                payload.resolution != "executed" or child_operations
            ):
                raise self._causal_error()
            if failure_origin == "binding":
                node_id = attempt.node_id
                binding_key = _typed_reference_key(
                    self._bindings_by_node[node_id]
                )
                availability = self._state.availability_by_binding.get(
                    binding_key
                )
                readiness = self._state.readiness_by_binding.get(binding_key)
                error = payload.error
                if (
                    error is None
                    or self._execution_routes[node_id] != "adapter"
                    or (
                        error.code == "binding_unavailable"
                        and (
                            availability is None
                            or availability.available is not False
                        )
                    )
                    or (
                        error.code == "readiness_rejected"
                        and (
                            readiness is None
                            or readiness.conclusion != "failing"
                        )
                    )
                    or error.code
                    not in {"binding_unavailable", "readiness_rejected"}
                ):
                    raise self._causal_error()
            if failure_origin == "publication" and (
                (
                    payload.resolution == "executed"
                    and (
                        len(child_operations) != 1
                        or child_operations[0].terminal != "succeeded"
                    )
                )
                or (
                    payload.resolution == "cache_replayed"
                    and child_operations
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, NodeDisposition):
            node_id = payload.node_id
            outcome = payload.outcome
            if (
                node_id not in self._plan_nodes
                or node_id in self._state.dispositions
            ):
                raise self._causal_error()
            attempt_id = self._state.node_attempt_by_node.get(node_id)
            attempt = (
                self._state.node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if outcome == "blocked":
                blocked_by = frozenset(payload.blocked_by)
                if (
                    self._state.cancellation_sequence is not None
                    or attempt is not None
                    or not blocked_by
                    or any(
                        upstream not in self._state.dispositions
                        for upstream in self._dependencies[node_id]
                    )
                    or blocked_by != self._required_input_blocker_set(node_id)
                ):
                    raise self._causal_error()
                return
            if (
                outcome == "succeeded"
                and self._state.cancellation_sequence is not None
            ):
                raise self._causal_error()
            if (
                outcome == "cancelled"
                and self._state.cancellation_sequence is None
            ):
                raise self._causal_error()
            if outcome == "cancelled" and attempt is None:
                return
            if outcome == "interrupted" and attempt is None:
                return
            if attempt is None or attempt.terminal is None:
                raise self._causal_error()
            expected_outcome = {
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled",
                "interrupted": "interrupted",
                "outcome_unknown": "interrupted",
            }[attempt.terminal]
            if (
                expected_outcome != outcome
                or (
                    outcome == "succeeded"
                    and payload.resolution != attempt.resolution
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, SelectionTerminal):
            selection_key = (
                payload.result.selection_node_id
                if payload.result is not None
                else "__failed__"
            )
            if (
                not self._state.run_started
                or not self._state.selection_required
                or set(self._state.dispositions) != set(self._plan_nodes)
                or any(
                    disposition.outcome != "succeeded"
                    for disposition in self._state.dispositions.values()
                )
                or (
                    payload.status == "succeeded"
                    and (
                        selection_key
                        not in self._state.expected_selection_terminal_keys
                        or selection_key in self._state.selection_terminal_keys
                    )
                )
                or (
                    payload.status == "failed"
                    and self._state.selection_terminals
                )
                or (
                    payload.status == "succeeded"
                    and any(
                        terminal.status == "failed"
                        for terminal in self._state.selection_terminals
                    )
                )
            ):
                raise self._causal_error()
            return
        if isinstance(payload, RunTerminal):
            if (
                payload.status == "interrupted"
                and self._state.run_admitted
                and not self._state.run_terminal
            ):
                return
            expected_status = _typed_run_terminal_status(
                self._state.dispositions.values(),
                tuple(self._state.selection_terminals),
            )
            outcomes = {
                disposition.outcome
                for disposition in self._state.dispositions.values()
            }
            if (
                not self._state.run_started
                or set(self._state.dispositions) != set(self._plan_nodes)
                or any(
                    attempt.terminal is None
                    for attempt in self._state.node_attempts.values()
                )
                or any(
                    operation.terminal is None
                    for operation in self._state.operations.values()
                )
                or any(
                    invocation.terminal is None
                    for invocation in self._state.invocations.values()
                )
                or (
                    self._state.selection_required
                    and not outcomes.intersection(
                        {"failed", "interrupted", "cancelled"}
                    )
                    and payload.status == "succeeded"
                    and self._state.selection_terminal_keys
                    != set(self._state.expected_selection_terminal_keys)
                )
                or payload.status != expected_status
            ):
                raise self._causal_error()
            return
        raise self._causal_error()

    def _apply(self, payload: FactPayload) -> None:
        if isinstance(payload, RunScopeBound):
            self._state.selection_required = payload.selection_required
            self._state.expected_selection_terminal_keys = (
                payload.selection_terminal_keys
            )
        elif isinstance(payload, AvailabilityBound):
            self._state.availability_by_binding[
                _typed_reference_key(payload.binding)
            ] = payload
        elif isinstance(payload, ReadinessAttested):
            self._state.readiness_by_binding[
                _typed_reference_key(payload.binding)
            ] = payload
        elif isinstance(payload, RunAdmitted):
            self._state.run_admitted = True
        elif isinstance(payload, RunStarted):
            self._state.run_started = True
        elif isinstance(payload, CancellationRequested):
            self._state.cancellation_sequence = len(self._state.facts)
        elif isinstance(payload, NodeAttemptStarted):
            self._state.node_attempts[payload.node_attempt_id] = (
                NodeAttemptState(node_id=payload.node_id)
            )
            self._state.node_attempt_by_node[payload.node_id] = (
                payload.node_attempt_id
            )
        elif isinstance(payload, OperationAttemptStarted):
            self._state.operations[payload.operation_attempt_id] = (
                OperationAttemptState(node_attempt_id=payload.node_attempt_id)
            )
        elif isinstance(payload, EngineInvocationStarted):
            self._state.invocations[payload.invocation_id] = InvocationState(
                operation_attempt_id=payload.operation_attempt_id,
                parent_invocation_id=payload.parent_invocation_id,
            )
        elif isinstance(payload, EngineInvocationTerminal):
            invocation = self._state.invocations[payload.invocation_id]
            invocation.terminal = payload.status
            invocation.error = payload.error
        elif isinstance(payload, OperationAttemptTerminal):
            operation = self._state.operations[payload.operation_attempt_id]
            operation.terminal = payload.status
            operation.error = payload.error
        elif isinstance(payload, NodeAttemptTerminal):
            attempt = self._state.node_attempts[payload.node_attempt_id]
            attempt.terminal = payload.status
            attempt.resolution = payload.resolution
        elif isinstance(payload, OutputsPublished):
            self._state.outputs_published.add(payload.node_id)
            self._state.nonempty_output_ports[payload.node_id] = {
                output.output_port
                for output in payload.outputs
                if output.value_count > 0
            } | {artifact.output_port for artifact in payload.artifacts}
        elif isinstance(payload, NodeDisposition):
            self._state.dispositions[payload.node_id] = payload
        elif isinstance(payload, SelectionTerminal):
            self._state.selection_terminals.append(payload)
            if payload.result is not None:
                self._state.selection_terminal_keys.add(
                    payload.result.selection_node_id
                )
        elif isinstance(payload, RunTerminal):
            self._state.run_terminal = True

    def _stage_facts(
        self,
        facts: tuple[Fact, ...],
    ) -> LedgerReducerState:
        self._validate_transaction_boundary(facts)
        prior_state = self._state
        staged_state = prior_state.clone()
        self._install_reducer_state(staged_state)
        try:
            for fact in facts:
                payload = fact.payload
                self._validate_causality(payload)
                self._state.facts.append(fact)
                self._apply(payload)
            return staged_state
        finally:
            self._install_reducer_state(prior_state)

    def _validate_transaction_boundary(
        self,
        facts: tuple[Fact, ...],
    ) -> None:
        closure_facts = [
            fact
            for fact in facts
            if isinstance(fact.payload, (SelectionTerminal, RunTerminal))
        ]
        if closure_facts:
            if (
                closure_facts != list(facts)
                or not isinstance(facts[-1].payload, RunTerminal)
                or any(
                    not isinstance(fact.payload, SelectionTerminal)
                    for fact in facts[:-1]
                )
            ):
                raise self._causal_error()
            return
        operation_terminals = [
            fact
            for fact in facts
            if isinstance(fact.payload, OperationAttemptTerminal)
        ]
        node_terminals = [
            fact
            for fact in facts
            if isinstance(fact.payload, NodeAttemptTerminal)
        ]
        output_publications = [
            fact
            for fact in facts
            if isinstance(fact.payload, OutputsPublished)
        ]
        dispositions = [
            fact
            for fact in facts
            if isinstance(fact.payload, NodeDisposition)
        ]
        if not (operation_terminals or node_terminals or output_publications):
            return
        if (
            len(operation_terminals) > 1
            or len(node_terminals) != 1
            or len(dispositions) != 1
        ):
            raise self._causal_error()
        node_terminal = node_terminals[0].payload
        assert isinstance(node_terminal, NodeAttemptTerminal)
        attempt = self._state.node_attempts.get(
            node_terminal.node_attempt_id
        )
        disposition = dispositions[0].payload
        assert isinstance(disposition, NodeDisposition)
        if (
            attempt is None
            or disposition.node_id != attempt.node_id
        ):
            raise self._causal_error()
        terminal_succeeded = node_terminal.status == "succeeded"
        publication_node_ids = {
            fact.payload.node_id for fact in output_publications
        }
        if (
            terminal_succeeded != (len(output_publications) == 1)
            or (not terminal_succeeded and output_publications)
            or publication_node_ids - {attempt.node_id}
        ):
            raise self._causal_error()
        open_operations = [
            operation_id
            for operation_id, operation in self._state.operations.items()
            if (
                operation.node_attempt_id == node_terminal.node_attempt_id
                and operation.terminal is None
            )
        ]
        if (
            bool(open_operations) != bool(operation_terminals)
            or (
                operation_terminals
                and isinstance(
                    operation_terminals[0].payload,
                    OperationAttemptTerminal,
                )
                and operation_terminals[0].payload.operation_attempt_id
                not in open_operations
            )
        ):
            raise self._causal_error()
        expected_payload_types = [
            *(
                (OperationAttemptTerminal,)
                if operation_terminals
                else ()
            ),
            *((OutputsPublished,) if terminal_succeeded else ()),
            NodeAttemptTerminal,
            NodeDisposition,
        ]
        if [type(fact.payload) for fact in facts] != expected_payload_types:
            raise self._causal_error()

    def _commit(
        self,
        payloads: tuple[FactPayload, ...],
    ) -> LedgerAcknowledgement:
        """Validate and durably publish one atomic logical transition."""
        if not payloads:
            raise ValueError("Run Ledger transaction must contain facts")
        with self._condition:
            self._require_available_evidence()
            first_sequence = len(self._state.facts) + 1
            facts = tuple(
                Fact(
                    sequence=first_sequence + offset,
                    recorded_at=run_timestamp(),
                    payload=payload,
                )
                for offset, payload in enumerate(payloads)
            )
            try:
                for fact in facts:
                    validate_fact_payload(fact.payload)
                staged_state = self._stage_facts(facts)
            except (TypeError, ValueError) as error:
                raise self._causal_error() from error
            except V2RunError as error:
                if error.code == "evidence_unavailable":
                    self._mark_evidence_unavailable(error)
                raise
            transaction_sequence = self._transaction_count + 1
            transaction = LedgerTransaction(
                project_id=self._project_id,
                run_id=self._run_id,
                transaction_sequence=transaction_sequence,
                first_fact_sequence=first_sequence,
                last_fact_sequence=facts[-1].sequence,
                committed_at=run_timestamp(),
                facts=facts,
            )
            encoded = encode_transaction(transaction)
            if len(encoded) > MAX_LEDGER_TRANSACTION_BYTES:
                error = V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence exceeds the durable transaction bound",
                    details={"last_durable_cursor": self.cursor.value},
                )
                self._mark_evidence_unavailable(error)
                raise error
            try:
                self._transaction_store.publish(
                    root=self._root,
                    relative_parts=(
                        self._run_id,
                        "ledger",
                        f"{transaction_sequence:020d}.json",
                    ),
                    payload=encoded,
                )
            except (OSError, StoragePathError) as error:
                unavailable = V2RunError(
                    "evidence_unavailable",
                    "Required Run evidence transaction could not be acknowledged",
                    details={"last_durable_cursor": self.cursor.value},
                )
                self._mark_evidence_unavailable(unavailable)
                raise unavailable from error
            self._install_reducer_state(staged_state)
            self._transaction_count = transaction_sequence
            self._committed_fact_count = facts[-1].sequence
            self._condition.notify_all()
            return LedgerAcknowledgement(
                first_sequence=first_sequence,
                last_sequence=facts[-1].sequence,
                cursor=self._cursor_at(facts[-1].sequence),
            )

    def _install_loaded_transaction(
        self,
        transaction: LedgerTransaction,
    ) -> None:
        staged_state = self._stage_facts(transaction.facts)
        self._install_reducer_state(staged_state)
        self._transaction_count = transaction.transaction_sequence
        self._committed_fact_count = transaction.last_fact_sequence

    def _load_transaction(self, encoded: bytes) -> None:
        with self._condition:
            try:
                transaction = decode_transaction(
                    encoded,
                    expected_project_id=self._project_id,
                    expected_run_id=self._run_id,
                    expected_transaction_sequence=self._transaction_count + 1,
                    expected_first_fact_sequence=len(self._state.facts) + 1,
                )
            except (KeyError, TypeError, ValueError) as error:
                raise self._causal_error() from error
            self._install_loaded_transaction(transaction)

    def projection(self) -> RunProjection:
        """Return the current typed domain projection of admitted facts."""
        with self._condition:
            self._require_available_evidence()
            return project_run(
                project_id=self._project_id,
                run_id=self._run_id,
                plan_node_order=self._plan_node_order,
                facts=self._state.facts,
                cursor=self._cursor_at(self._committed_fact_count),
            )

    def request_cancellation(
        self,
        after_cursor: RunCursor | None,
    ) -> CancellationDecision:
        """Persist one cancellation decision under the Ledger ordering lock."""
        with self._condition:
            self._require_available_evidence()
            observed_sequence = self.sequence_for_cursor(after_cursor)
            if self._state.cancellation_sequence is not None:
                decision_sequence = self._state.cancellation_sequence
                return CancellationDecision(
                    outcome="already_requested",
                    decision_sequence=decision_sequence,
                    cursor=self._cursor_at(decision_sequence),
                )
            if self._state.run_terminal:
                terminal_sequence = len(self._state.facts)
                return CancellationDecision(
                    outcome=(
                        "completed_before_cancel"
                        if (
                            after_cursor is not None
                            and observed_sequence < terminal_sequence
                        )
                        else "already_terminal"
                    ),
                    decision_sequence=terminal_sequence,
                    cursor=self._cursor_at(terminal_sequence),
                )
            if set(self._state.dispositions) == set(self._plan_nodes):
                decision_sequence = len(self._state.facts)
                return CancellationDecision(
                    outcome="completed_before_cancel",
                    decision_sequence=decision_sequence,
                    cursor=self._cursor_at(decision_sequence),
                )
            committed = self._commit((CancellationRequested(run_timestamp()),))
            decision_sequence = committed.last_sequence
            return CancellationDecision(
                outcome="cancellation_requested",
                decision_sequence=decision_sequence,
                cursor=self._cursor_at(decision_sequence),
            )

    def events(
        self,
        *,
        after_sequence: int = 0,
        through_sequence: int | None = None,
    ) -> tuple[Fact, ...]:
        with self._condition:
            self._require_available_evidence()
            return event_facts(
                self._state.facts,
                after_sequence=after_sequence,
                through_sequence=through_sequence,
            )

    def replay(self, cursor: RunCursor | None) -> ReplayWindow:
        with self._condition:
            self._require_available_evidence()
            after_sequence = self.sequence_for_cursor(cursor)
            through_sequence = len(self._state.facts)
            return ReplayWindow(
                after_sequence=after_sequence,
                after_cursor=self._cursor_at(after_sequence),
                through_sequence=through_sequence,
                through_cursor=self._cursor_at(through_sequence),
                events=self.events(
                    after_sequence=after_sequence,
                    through_sequence=through_sequence,
                ),
                terminal=self._state.run_terminal,
            )

    def wait_for_events(
        self,
        after_sequence: int,
        *,
        timeout_seconds: float,
    ) -> tuple[tuple[Fact, ...], int, bool]:
        with self._condition:
            self._require_available_evidence()
            if (
                len(self._state.facts) <= after_sequence
                and not self._state.run_terminal
            ):
                self._condition.wait(timeout_seconds)
            self._require_available_evidence()
            return (
                self.events(after_sequence=after_sequence),
                len(self._state.facts),
                self._state.run_terminal,
            )

    def notify_waiters(self) -> None:
        """Wake event consumers after an active Run state transition."""
        with self._condition:
            self._condition.notify_all()

    def reconcile_restart(self) -> None:
        """Mark a previously admitted process as interrupted."""
        with self._condition:
            if not self._state.run_admitted or self._state.run_terminal:
                return
            self._commit((RunTerminal("interrupted"),))
