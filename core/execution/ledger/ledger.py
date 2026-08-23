"""Run Evidence Ledger authority: causality, atomic publication, replay, restart."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import threading
from typing import Any, TypeAlias, cast

from core.catalog.canonical import canonical_sha256
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
)
from core.execution.ledger.reducer import (
    LedgerReducer,
    LedgerReducerState,
    run_terminal_status,
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
    LedgerAcknowledgement,
    NodeFailurePublication,
    NodeSuccessPublication,
    NodeTerminationPublication,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
    ReadinessAttestation,
    RunClosure,
    RunScopeBinding,
)
from core.project.manager import ProjectManager
from core.project.storage import (
    StoragePathError,
)
_LedgerTransition: TypeAlias = (
    RunScopeBinding
    | ReadinessAttestation
    | AvailabilityBound
    | RunAdmitted
    | RunStarted
    | NodeAttemptStarted
    | OperationAttemptStarted
    | EngineInvocationStarted
    | EngineInvocationTerminal
    | NodeDisposition
    | NodeSuccessPublication
    | NodeFailurePublication
    | NodeTerminationPublication
    | RunClosure
)


class V2RunError(RuntimeError):
    """A closed Run failure safe to expose through a transport adapter."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any]) -> None:
        self.code = code
        self.details = dict(details)
        super().__init__(message)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_timestamp(value: datetime | None = None) -> str:
    observed = value or _utc_now()
    return observed.astimezone(timezone.utc).isoformat()


def run_cursor(
    sequence: int,
    *,
    project_id: str,
    run_id: str,
    fact: Fact | None = None,
) -> RunCursor:
    return encode_cursor(
        sequence,
        project_id=project_id,
        run_id=run_id,
        fact=fact,
    )

class Ledger:
    """Causally closed typed evidence authority for one Run."""

    def __init__(
        self,
        projects: ProjectManager,
        project_id: str,
        run_id: str,
        plan_nodes: tuple[PlanNodeEvidence, ...],
        transaction_store: LedgerStore | None = None,
    ) -> None:
        run_dir = projects.run_storage_directory(project_id, run_id)
        self._root = run_dir.parent
        self._project_id = project_id
        self._run_id = run_id
        self._plan_node_order = tuple(node.node_id for node in plan_nodes)
        self._reducer = LedgerReducer(
            project_id=project_id,
            run_id=run_id,
            plan_evidence=plan_nodes,
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

    def _require_available_evidence(self) -> None:
        unavailable = self._evidence_unavailable
        if unavailable is not None:
            raise V2RunError(
                unavailable.code,
                str(unavailable),
                details=unavailable.details,
            ) from unavailable

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
            payload = cast(RunScopeBound, self._state.facts[0].payload)
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
                set(self._state.dispositions) == set(self._plan_node_order)
                and all(
                    disposition.outcome == "succeeded"
                    for disposition in self._state.dispositions.values()
                )
            )

    @property
    def selection_consumer_ids(self) -> tuple[str, ...]:
        """Return the Selection consumers fixed by durable Run scope."""
        return self._reducer.selection_consumer_ids

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
                details={"after_sequence": cursor.value},
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
                details={"after_sequence": cursor.value},
            )
        return sequence

    def record(
        self,
        transition: _LedgerTransition,
    ) -> LedgerAcknowledgement:
        """Validate and durably acknowledge one complete legal transition."""
        if isinstance(transition, RunScopeBinding):
            return self._record_run_scope(transition)
        if isinstance(transition, ReadinessAttestation):
            return self._record_readiness(transition)
        if isinstance(
            transition,
            (
                AvailabilityBound,
                RunAdmitted,
                RunStarted,
                NodeAttemptStarted,
                OperationAttemptStarted,
                EngineInvocationStarted,
                EngineInvocationTerminal,
                NodeDisposition,
            ),
        ):
            return self._commit((transition,))
        if isinstance(transition, NodeSuccessPublication):
            return self._record_node_success(transition)
        if isinstance(transition, NodeFailurePublication):
            return self._record_node_failure(transition)
        if isinstance(transition, NodeTerminationPublication):
            return self._record_node_termination(transition)
        if isinstance(transition, RunClosure):
            return self._record_run_closure(transition)
        raise TypeError("Run Evidence Ledger transition is not current")

    def record_if_active(
        self,
        transition: _LedgerTransition,
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
                    plan_nodes=self._reducer.plan_evidence,
                    selection_terminal_keys=self._reducer.selection_consumer_ids,
                    derived_from=scope.derived_from,
                ),
            )
        )

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

    def _record_run_closure(
        self,
        closure: RunClosure,
    ) -> LedgerAcknowledgement:
        selections = closure.selections
        run_status = run_terminal_status(
            self._state.dispositions.values(),
            selections,
        )
        return self._commit(
            (
                *selections,
                RunTerminal(run_status),
            )
        )

    def _commit(
        self,
        payloads: tuple[FactPayload, ...],
    ) -> LedgerAcknowledgement:
        """Durably publish one trusted typed logical transition."""
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
            staged_state = self._reducer.apply_facts(self._state, facts)
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
            self._state = staged_state
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
        staged_state = self._reducer.replay_facts(
            self._state,
            transaction.facts,
        )
        self._state = staged_state
        self._transaction_count = transaction.transaction_sequence
        self._committed_fact_count = transaction.last_fact_sequence

    def _load_transaction(self, encoded: bytes) -> None:
        with self._condition:
            transaction = decode_transaction(
                encoded,
                expected_project_id=self._project_id,
                expected_run_id=self._run_id,
                expected_transaction_sequence=self._transaction_count + 1,
                expected_first_fact_sequence=len(self._state.facts) + 1,
            )
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
            if set(self._state.dispositions) == set(self._plan_node_order):
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

    def reconcile_restart(self) -> None:
        """Mark a previously admitted process as interrupted."""
        with self._condition:
            if not self._state.run_admitted or self._state.run_terminal:
                return
            self._commit((RunTerminal("interrupted"),))
