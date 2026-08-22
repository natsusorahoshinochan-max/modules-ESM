"""Serial Run execution and durable domain use cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import threading
from types import MappingProxyType
from typing import Any, Literal
import uuid

from core.catalog.model import CatalogAvailabilityProjection, FrozenCatalog
from core.execution._run_runtime_derived import _DerivedRunStarter
from core.execution._run_runtime_evidence import (
    _exact_contract_reference,
    _execution_plan_contract_roots,
    plan_evidence,
)
from core.execution._run_runtime_models import _RunRecord
from core.execution._run_runtime_queries import _RunQueries
from core.execution._run_runtime_registry import _RunRegistry
from core.execution._run_runtime_selection import (
    _selection_error,
    selection_consumer_result,
)
from core.execution.ledger import (
    AvailabilityBinding,
    CancellationDecision,
    DerivedRunReference,
    Fact,
    Ledger,
    LedgerStore,
    ReplayWindow,
    RunCursor,
    RunAdmission,
    RunClosure,
    RunProjection,
    RunScopeBinding,
    RunStart,
    SelectionFailure,
    SelectionSuccess,
    UnstartedNodeConclusion,
    V2RunError,
    run_cursor,
    run_timestamp,
)
from core.execution.node_attempt import AttemptSpec, NodeAttemptFactory
from core.execution.output_admission.candidate_identity import (
    _validate_input_candidate_identities,
)
from core.execution.output_admission.port_values import combine_admitted_port
from core.execution.results import ResultStore
from core.operation import AdmittedPort
from core.project.manager import ProjectManager
from core.project.storage import StoragePathError
from core.scoring.selection import SelectionError
from core.workflow.authoring import (
    VerifiedWorkflowCommit,
    WorkflowAuthoringService,
)
from core.workflow.plan import ExecutionPlanNode


MAX_BACKGROUND_RUNS = 8
FAST_RUN_COMPLETION_GRACE_SECONDS = 0.25


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
            catalog=catalog,
            ledger_store=ledger_transaction_store,
        )
        self._queries = _RunQueries(
            registry=self._registry,
            result_store=result_store,
        )
        self._worker_condition = threading.Condition(threading.RLock())
        self._workers: set[threading.Thread] = set()
        self._reserved_projects: set[str] = set()
        self._closing_projects: set[str] = set()
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
                and project_id in self._closing_projects
            ):
                self._worker_condition.wait()
            if (
                self._closed
                or project_id in self._reserved_projects
                or (
                    worker is not None
                    and len(self._workers) >= MAX_BACKGROUND_RUNS
                )
            ):
                raise V2RunError(
                    "evidence_unavailable",
                    "Run execution admission is temporarily unavailable",
                    details={"last_durable_cursor": run_cursor(0).value},
                )
            self._reserved_projects.add(project_id)
            if worker is not None:
                self._workers.add(worker)
                try:
                    worker.start()
                except BaseException:
                    self._workers.discard(worker)
                    self._reserved_projects.discard(project_id)
                    self._closing_projects.discard(project_id)
                    self._worker_condition.notify_all()
                    raise

    def _mark_project_closing(self, project_id: str) -> None:
        with self._worker_condition:
            self._closing_projects.add(project_id)

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
            self._closing_projects.discard(project_id)
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

    @staticmethod
    def _admitted_inputs_for(
        node: ExecutionPlanNode,
        values: Mapping[tuple[str, str], AdmittedPort],
    ) -> Mapping[str, AdmittedPort]:
        """Combine already-admitted upstream values for one planned Node."""
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
            if declaration.multiplicity == "one" and len(admitted) != 1:
                raise RuntimeError(
                    "Execution Plan one-valued input Port "
                    f"{port_name!r} resolved to {len(admitted)} admitted values"
                )
            inputs[port_name] = combine_admitted_port(
                port_type=declaration.reference.canonical_projection(),
                multiplicity=declaration.multiplicity,
                values=tuple(admitted),
            )
        _validate_input_candidate_identities(inputs)
        return MappingProxyType(inputs)

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
        admitted_plan_evidence = plan_evidence(plan)
        try:
            ledger = Ledger(
                self._projects,
                project_id,
                run_id,
                admitted_plan_evidence,
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
            CatalogAvailabilityProjection,
        ] = {}
        for binding_key, node in distinct.items():
            availability = self._catalog.require_availability(
                _exact_contract_reference(node.binding)
            )
            availability_by_binding[binding_key] = availability
            ledger.record(
                AvailabilityBinding(
                    binding=availability.binding,
                    catalog_observed_at=run_timestamp(
                        availability.observed_at
                    ),
                    available=availability.result.is_available,
                )
            )
        admitted = ledger.record(
            RunAdmission(
                workflow_commit_id=workflow_commit_id,
                workflow_commit_revision=workflow_commit_revision,
            )
        )
        ledger.record(RunStart(started_at=run_timestamp()))

        committed_artifact_count = 0
        committed_artifact_bytes = 0
        record = _RunRecord(
            compiled=compiled,
            ledger=ledger,
        )
        attempts = self._node_attempt_factory.create(
            ledger=ledger,
            availability_by_binding=availability_by_binding,
        )

        self._registry.register(project_id, run_id, record)
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
                AttemptSpec(
                    project_id=project_id,
                    run_id=run_id,
                    node=node,
                    candidate_data_port_types=(
                        plan._runtime.candidate_data_port_types
                    ),
                    admitted_inputs=self._admitted_inputs_for(
                        node,
                        committed_values,
                    ),
                    cancellation=record.cancellation,
                    committed_artifact_count=committed_artifact_count,
                    committed_artifact_bytes=committed_artifact_bytes,
                    cache_bypassed=node.node_id in _cache_bypass_nodes,
                )
            )
            if committed.disposition == "succeeded":
                committed_values.update(committed.admitted_outputs)
                committed_artifact_count += (
                    committed.published_artifact_count
                )
                committed_artifact_bytes += (
                    committed.published_artifact_bytes
                )
        selection_conclusions: tuple[
            SelectionSuccess | SelectionFailure,
            ...,
        ] = ()
        if ledger.selection_consumer_ids and ledger.all_dispositions_succeeded:
            selection_consumers = {
                node.node_id: node for node in plan.nodes
            }
            try:
                selection_conclusions = tuple(
                    SelectionSuccess(
                        result=selection_consumer_result(
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
        self._mark_project_closing(project_id)
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
        self._registry.require_available_evidence(record)
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
