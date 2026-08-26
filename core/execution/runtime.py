"""Serial Run execution and durable domain use cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import threading
from typing import Any, Literal, cast
import uuid

from core.catalog.model import FrozenCatalog
from core.execution._run_runtime_derived import _DerivedRunStarter
from core.execution._run_runtime_evidence import plan_evidence
from core.execution._run_runtime_models import _RunRecord
from core.execution._run_runtime_queries import _RunQueries
from core.execution._run_runtime_registry import _RunRegistry
from core.execution._run_runtime_selection import (
    _selection_error,
    selection_consumer_result,
)
from core.execution.ledger import (
    AvailabilityBound,
    CancellationDecision,
    DerivedRunReference,
    Fact,
    Ledger,
    LedgerStore,
    NodeDisposition,
    ReplayWindow,
    RunCursor,
    RunAdmitted,
    RunClosure,
    RunProjection,
    RunScopeBinding,
    RunStarted,
    SelectionTerminal,
    V2RunError,
    run_cursor,
    run_timestamp,
)
from core.execution.node_attempt import AttemptSpec, NodeAttemptFactory
from core.execution.results.store import ResultStore
from core.operation import AdmittedPort
from core.project.manager import ProjectManager
from core.project.storage import StoragePathError
from core.scoring.selection import SelectionError
from core.workflow.authoring import (
    VerifiedWorkflowCommit,
    WorkflowAuthoringService,
)
from core.workflow.plan import ExecutionPlanNode

class V2RunService:
    """Execute compiled direct Nodes behind readiness and durable evidence."""

    def __init__(
        self,
        projects: ProjectManager,
        catalog: FrozenCatalog,
        authoring: WorkflowAuthoringService,
        node_attempt_factory: NodeAttemptFactory,
        result_store: ResultStore,
        ledger_transaction_store: LedgerStore | None = None,
    ) -> None:
        self._projects = projects
        self._catalog = catalog
        self._authoring = authoring
        self._node_attempt_factory = node_attempt_factory
        self._result_store = result_store
        self._ledger_transaction_store = ledger_transaction_store
        self._registry = _RunRegistry(
            projects=projects,
            ledger_store=ledger_transaction_store,
        )
        self._queries = _RunQueries(
            registry=self._registry,
            result_store=result_store,
        )
        self._worker_condition = threading.Condition(threading.RLock())
        self._workers: set[threading.Thread] = set()
        self._reserved_projects: set[str] = set()
        self._execution_lock = threading.Lock()
        self._closed = False
        self._derived = _DerivedRunStarter(
            registry=self._registry,
            start_background=self.start_background,
        )

    def _reserve_project(
        self,
        project_id: str,
        *,
        worker: threading.Thread | None = None,
    ) -> None:
        with self._worker_condition:
            while (
                not self._closed
                and project_id in self._reserved_projects
            ):
                self._worker_condition.wait()
            if self._closed:
                raise RuntimeError("Run Runtime is closed")
            self._reserved_projects.add(project_id)
            if worker is not None:
                self._workers.add(worker)
                try:
                    worker.start()
                except BaseException:
                    self._workers.discard(worker)
                    self._reserved_projects.discard(project_id)
                    self._worker_condition.notify_all()
                    raise

    def _release_project(
        self,
        project_id: str,
        *,
        worker: threading.Thread | None = None,
    ) -> None:
        with self._worker_condition:
            if worker is not None:
                self._workers.discard(worker)
            self._reserved_projects.discard(project_id)
            self._worker_condition.notify_all()

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
    ) -> dict[str, Any]:
        """Execute one Run while holding the Project admission lease."""
        self._reserve_project(project_id)
        try:
            with self._execution_lock:
                return self._execute_run(
                    project_id,
                    workflow_commit_id=workflow_commit_id,
                    client_request_id=client_request_id,
                )
        finally:
            self._release_project(project_id)

    def _execute_run(
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
        _derived_from: DerivedRunReference | None = None,
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
        run_id = f"run-{uuid.uuid4().hex}"
        admitted_plan_evidence = plan_evidence(plan)
        try:
            ledger = Ledger(
                self._projects,
                project_id,
                run_id,
                admitted_plan_evidence,
                self._ledger_transaction_store,
            )
        except (OSError, StoragePathError) as error:
            raise V2RunError(
                "evidence_unavailable",
                "Required Run evidence workspace is unavailable",
                details={
                    "last_durable_cursor": run_cursor(
                        0,
                        project_id=project_id,
                        run_id=run_id,
                    ).value
                },
            ) from error
        ledger.record(
            RunScopeBinding(
                workflow_commit_id=workflow_commit_id,
                derived_from=_derived_from,
            )
        )
        distinct: dict[str, ExecutionPlanNode] = {}
        for node in plan.nodes:
            distinct.setdefault(node.binding.contract_id, node)
        for node in distinct.values():
            availability = self._catalog.require_availability(
                node.binding
            )
            ledger.record(
                AvailabilityBound(
                    binding=availability.binding,
                    catalog_observed_at=run_timestamp(
                        availability.observed_at
                    ),
                    available=availability.result.is_available,
                )
            )
        admitted = ledger.record(
            RunAdmitted(workflow_commit_id=workflow_commit_id)
        )
        ledger.record(RunStarted(started_at=run_timestamp()))

        record = _RunRecord(
            compiled=compiled,
            ledger=ledger,
        )
        attempts = self._node_attempt_factory.create(
            ledger=ledger,
        )

        self._registry.register(project_id, run_id, record)
        receipt = {
            "project_id": project_id,
            "run_id": run_id,
            "workflow_commit_id": workflow_commit_id,
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
                    NodeDisposition(
                        node_id=node.node_id,
                        outcome="blocked",
                        blocked_by=blocked_by,
                    )
                )
                if acknowledged is None:
                    ledger.record(
                        NodeDisposition(
                            node_id=node.node_id,
                            outcome=cancellation_outcome,
                            blocked_by=(),
                        )
                    )
                concluded_before_scheduling = True
            elif ledger.cancellation_requested:
                ledger.record(
                    NodeDisposition(
                        node_id=node.node_id,
                        outcome=cancellation_outcome,
                        blocked_by=(),
                    )
                )
                concluded_before_scheduling = True
            if concluded_before_scheduling:
                continue
            committed = attempts.execute(
                AttemptSpec(
                    project_id=project_id,
                    run_id=run_id,
                    node=node,
                    candidate_data_port_types=(
                        plan._runtime.candidate_data_port_types
                    ),
                    committed_values=committed_values,
                    cancellation=record.cancellation,
                    cache_bypassed=node.node_id in _cache_bypass_nodes,
                )
            )
            if committed.disposition == "succeeded":
                committed_values.update(committed.admitted_outputs)
        selection_conclusions: tuple[SelectionTerminal, ...] = ()
        if ledger.selection_consumer_ids and ledger.all_dispositions_succeeded:
            selection_consumers = {
                node.node_id: node for node in plan.nodes
            }
            try:
                selection_conclusions = tuple(
                    SelectionTerminal(
                        status="succeeded",
                        result=selection_consumer_result(
                            selection_consumers[node_id],
                            committed_values,
                        ),
                    )
                    for node_id in ledger.selection_consumer_ids
                )
            except SelectionError as error:
                selection_conclusions = (
                    SelectionTerminal(
                        status="failed",
                        error=_selection_error(error),
                    ),
                )
        ledger.record(RunClosure(selection_conclusions))
        record.mark_worker_completed()
        return receipt

    def start_background(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
        client_request_id: str,
        _derived_from: DerivedRunReference | None = None,
        _cache_bypass_nodes: frozenset[str] = frozenset(),
        _retained_compiled: VerifiedWorkflowCommit | None = None,
    ) -> dict[str, Any]:
        """Admit synchronously, then execute without blocking event delivery."""
        admitted = threading.Event()
        receipt: dict[str, Any] | None = None
        record: _RunRecord | None = None
        error: BaseException | None = None
        execution_slot_acquired = False

        def on_admitted(
            admitted_receipt: dict[str, Any],
            admitted_record: _RunRecord,
        ) -> None:
            nonlocal receipt, record
            receipt = admitted_receipt
            record = admitted_record
            admitted.set()

        def execute() -> None:
            nonlocal error, execution_slot_acquired
            try:
                def acquire_execution_slot() -> None:
                    nonlocal execution_slot_acquired
                    self._execution_lock.acquire()
                    execution_slot_acquired = True

                self._execute_run(
                    project_id,
                    workflow_commit_id=workflow_commit_id,
                    client_request_id=client_request_id,
                    _on_admitted=on_admitted,
                    _before_execute=acquire_execution_slot,
                    _derived_from=_derived_from,
                    _cache_bypass_nodes=_cache_bypass_nodes,
                    _retained_compiled=_retained_compiled,
                )
            except BaseException as caught:
                error = caught
                if record is not None:
                    record.mark_worker_completed(caught)
            finally:
                if execution_slot_acquired:
                    self._execution_lock.release()
                self._release_project(
                    project_id,
                    worker=threading.current_thread(),
                )
                admitted.set()

        worker = threading.Thread(
            target=execute,
            name=f"v2-run-admission-{project_id}",
            daemon=False,
        )
        self._reserve_project(project_id, worker=worker)
        admitted.wait()
        if receipt is None:
            raise cast(BaseException, error)
        return receipt

    def start_derived_background(
        self,
        project_id: str,
        *,
        source_run_id: str,
        policy: str,
        node_ids: list[str],
        client_request_id: str,
    ) -> dict[str, Any]:
        return self._derived.start(
            project_id,
            source_run_id=source_run_id,
            policy=policy,
            node_ids=node_ids,
            client_request_id=client_request_id,
        )

    def cancel(
        self,
        project_id: str,
        run_id: str,
        *,
        after_cursor: RunCursor | None,
    ) -> CancellationDecision:
        """Persist cancellation before signalling active work."""
        record = self._registry.require_record(project_id, run_id)
        record.require_lifecycle_evidence()
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
        with self._worker_condition:
            while self._reserved_projects:
                self._worker_condition.wait()
        self._node_attempt_factory.shutdown()

    def projection(self, project_id: str, run_id: str) -> RunProjection:
        return self._queries.projection(project_id, run_id)

    def typed_value(
        self,
        project_id: str,
        run_id: str,
        node_id: str,
        output_port: str,
        value_index: int,
    ) -> tuple[dict[str, Any], bytes]:
        return self._queries.typed_value(
            project_id,
            run_id,
            node_id,
            output_port,
            value_index,
        )

    def artifact(
        self,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        return self._queries.artifact(
            project_id,
            run_id,
            artifact_reference,
        )

    def events(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[Fact, ...]:
        return self._queries.events(project_id, run_id)

    def ledger_cursor(self, project_id: str, run_id: str) -> RunCursor:
        return self._queries.ledger_cursor(project_id, run_id)

    def replay(
        self,
        project_id: str,
        run_id: str,
        cursor: RunCursor | None,
    ) -> ReplayWindow:
        return self._queries.replay(project_id, run_id, cursor)

    def wait_for_events(
        self,
        project_id: str,
        run_id: str,
        after_sequence: int,
        *,
        timeout_seconds: float = 1.0,
    ) -> tuple[tuple[Fact, ...], int, bool]:
        return self._queries.wait_for_events(
            project_id,
            run_id,
            after_sequence,
            timeout_seconds=timeout_seconds,
        )


__all__ = ["V2RunService"]
