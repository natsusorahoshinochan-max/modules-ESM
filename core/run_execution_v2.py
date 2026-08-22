"""Readiness-gated direct execution and durable public Run projections."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Any, Literal
import uuid

from core.catalog.port_contract import (
    is_valid_artifact_media_type,
)
from core.operation import (
    AdmittedPort,
    InvocationRandomness,
    ProviderResidueProjection,
    ProviderResidueProjectionEntry,
)
from core.execution.environment import EnvironmentConfiguration
from core.execution.node_attempt import AttemptSpec, NodeAttempt
from core.execution.ledger import (
    ArtifactOutputEvidence,
    AvailabilityBinding,
    CancellationDecision,
    ContextSelectorEvidence,
    DerivedRunReference,
    FilesystemLedgerStore,
    Fact,
    Ledger,
    LedgerStore,
    ObservationSelectorEvidence,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
    PublishedOutput,
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
from core.execution.output_admission.candidate_identity import (
    _validate_input_candidate_identities,
)
from core.execution.output_admission.port_values import combine_admitted_port
from core.execution.resources import CancellationControl
from core.execution.results import (
    ResultIntegrityError,
    ResultStore,
)
from core.catalog.model import (
    FrozenCatalog,
)
from core.catalog.port_contract import (
    ContractResolutionError,
    PortTypeDefinition,
)
from core.project.manager import ProjectManager
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


MAX_BACKGROUND_RUNS = 8
FAST_RUN_COMPLETION_GRACE_SECONDS = 0.25
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")


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




def _exact_reference(reference: Any) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=reference.contract_kind,
        contract_id=reference.contract_id,
        contract_version=reference.contract_version,
        contract_digest=reference.contract_digest,
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

        committed_artifact_count = 0
        committed_artifact_bytes = 0
        record = _RunRecord(
            compiled=compiled,
            ledger=ledger,
        )
        attempts = NodeAttempt(
            projects=self._projects,
            environment=self._environment,
            result_store=self._result_store,
            ledger=ledger,
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
