"""Direct contracts for the typed Run Evidence Ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from typing import Literal, cast

import pytest

from core.execution.ledger import (
    ArtifactOutputEvidence,
    AvailabilityBound,
    ContextSelectorEvidence,
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    FilesystemLedgerStore,
    ImmutableObjectReference,
    InMemoryLedgerStore,
    Ledger,
    LedgerStore,
    NodeAttemptStarted,
    NodeDisposition,
    NodeFailurePublication,
    NodeSuccessPublication,
    NodeTerminationPublication,
    ObservationSelectorEvidence,
    OperationAttemptStarted,
    OutputsPublished,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
    PublishedArtifact,
    PublishedOutput,
    ReadinessAttestation,
    ReadinessAttested,
    RunAdmitted,
    RunClosure,
    RunCursor,
    RunScopeBinding,
    RunScopeBound,
    RunStarted,
    SelectionObjectiveEvidence,
    SelectionResult,
    SelectionTerminal,
    StructuredError,
    V2RunError,
)
from core.execution.ledger.codec import (
    decode_transaction,
    payload_from_canonical,
    payload_to_canonical,
)
from core.operation import (
    EngineInvocationProvenance,
    InvocationRandomness,
    ProviderResidueProjection,
    ProviderResidueProjectionEntry,
)
from core.project.manager import ProjectManager
from core.scoring.selection import SelectionInput
from datatypes.exact_reference import ExactContractReference


_OBSERVED_AT = "2026-08-21T00:00:00+00:00"
_STARTED_AT = "2026-08-21T00:00:01+00:00"


def _reference(
    contract_kind: str = "binding",
    contract_id: str = "fixture.binding",
) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=contract_kind,
        contract_id=contract_id,
    )


def _reference_key(
    reference: ExactContractReference,
) -> tuple[str, str]:
    return (
        reference.contract_kind,
        reference.contract_id,
    )


def _plan_node(
    *,
    node_id: str = "node-1",
    execution_route: str = "direct",
    binding: ExactContractReference | None = None,
    dependencies: tuple[str, ...] = (),
    selection_consumer: bool = False,
) -> PlanNodeEvidence:
    return PlanNodeEvidence(
        node_id=node_id,
        dependencies=dependencies,
        required_input_sources=(),
        node_type=_reference("node_type", "fixture.node"),
        binding=binding or _reference(),
        method=_reference("method", "fixture.method"),
        execution_route=execution_route,
        selection_consumer=selection_consumer,
    )


def _scope_bound(node: PlanNodeEvidence) -> RunScopeBound:
    return RunScopeBound(
        project_id="project-1",
        run_id="run-1",
        workflow_commit_id="workflow-commit-" + "0" * 64,
        plan_nodes=(node,),
        selection_terminal_keys=(),
    )


def test_run_scope_codec_accepts_semantic_node_identifiers() -> None:
    node = _plan_node(node_id="source:node/1+")
    scope = _scope_bound(node)

    assert payload_from_canonical(
        "run_scope_bound",
        payload_to_canonical(scope),
    ) == scope


def test_output_publication_persists_shared_context_once() -> None:
    result_identity = "sha256:" + "6" * 64
    publication = OutputsPublished(
        node_id="node-1",
        result_identity=result_identity,
        node_result_manifest=ImmutableObjectReference(
            "sha256:" + "7" * 64,
            32,
        ),
        outputs=(
            PublishedOutput(
                output_port="scores",
                port_type=_reference("port_type", "score.collection"),
                content_digest="sha256:" + "8" * 64,
                materialization={"run_id": "run-1", "resolution": "executed"},
                producer_run_id="run-1",
                value_count=1,
                value_manifest_reference="sha256:" + "9" * 64,
            ),
        ),
        artifacts=(
            PublishedArtifact(
                artifact_reference="artifact-1",
                artifact_kind="standalone",
                output_port="report",
                media_type="text/plain",
                filename="report.txt",
                size=4,
                content_digest="sha256:" + "a" * 64,
            ),
        ),
    )

    encoded = payload_to_canonical(publication)

    assert "node_id" not in encoded["outputs"][0]
    assert "result_identity" not in encoded["outputs"][0]
    assert "node_id" not in encoded["artifacts"][0]
    assert encoded["outputs"][0]["producer_run_id"] == "run-1"
    assert payload_from_canonical("outputs_published", encoded) == publication


def test_artifact_media_grammar_has_one_typed_fact_owner() -> None:
    invalid_media_type = "not a media type"
    node = replace(
        _plan_node(),
        artifact_outputs=(
            ArtifactOutputEvidence(
                output_port="artifact",
                artifact_kind="standalone",
                artifact_media_type=invalid_media_type,
                port_type=_reference(
                    "port_type",
                    "fixture.artifact",
                ),
                accepted_media_types=(invalid_media_type,),
            ),
        ),
    )
    scope = _scope_bound(node)

    with pytest.raises(ValueError):
        payload_from_canonical(
            "run_scope_bound",
            payload_to_canonical(scope),
        )


def _scope_references(
    plan_nodes: tuple[PlanNodeEvidence, ...],
) -> tuple[ExactContractReference, ...]:
    return tuple(
        sorted(
            {node.binding for node in plan_nodes},
            key=_reference_key,
        )
    )


def _scoped_ledger(
    tmp_path: Path,
    *,
    store: LedgerStore,
    run_id: str = "run-1",
    plan_nodes: tuple[PlanNodeEvidence, ...] | None = None,
) -> tuple[Ledger, ProjectManager]:
    retained_nodes = plan_nodes or (_plan_node(),)
    projects = ProjectManager(tmp_path / "projects")
    ledger = Ledger(
        projects,
        "project-1",
        run_id,
        retained_nodes,
        store,
    )
    ledger.record(
        RunScopeBinding(
            workflow_commit_id="workflow-commit-" + "0" * 64,
        )
    )
    return ledger, projects


def _admitted_ledger(
    tmp_path: Path,
    *,
    store: LedgerStore | None = None,
    run_id: str = "run-1",
    plan_nodes: tuple[PlanNodeEvidence, ...] | None = None,
) -> tuple[Ledger, ProjectManager, LedgerStore]:
    retained_store = store or InMemoryLedgerStore()
    retained_nodes = plan_nodes or (_plan_node(),)
    ledger, projects = _scoped_ledger(
        tmp_path,
        store=retained_store,
        run_id=run_id,
        plan_nodes=retained_nodes,
    )
    for binding in _scope_references(retained_nodes):
        ledger.record(
            AvailabilityBound(
                binding=binding,
                catalog_observed_at=_OBSERVED_AT,
                available=True,
            )
        )
    ledger.record(
        RunAdmitted(
            workflow_commit_id="workflow-commit-" + "0" * 64,
        )
    )
    ledger.record(RunStarted(started_at=_STARTED_AT))
    return ledger, projects, retained_store


def _durable_facts(
    store: LedgerStore,
    projects: ProjectManager,
    *,
    run_id: str = "run-1",
) -> tuple[Fact, ...]:
    transactions = store.read_transactions(
        root=projects.run_storage_directory("project-1", run_id).parent,
        relative_parts=(run_id, "ledger"),
    )
    facts: list[Fact] = []
    expected_first_fact_sequence = 1
    for transaction_sequence, (_, encoded) in enumerate(
        transactions,
        start=1,
    ):
        transaction = decode_transaction(
            encoded,
            expected_project_id="project-1",
            expected_run_id=run_id,
            expected_transaction_sequence=transaction_sequence,
            expected_first_fact_sequence=expected_first_fact_sequence,
        )
        facts.extend(transaction.facts)
        expected_first_fact_sequence = transaction.last_fact_sequence + 1
    return tuple(facts)


def _publish_success(ledger: Ledger, *, node_id: str = "node-1") -> None:
    node_attempt_id = f"attempt-{node_id}"
    operation_attempt_id = f"operation-{node_id}"
    ledger.record(NodeAttemptStarted(node_id, node_attempt_id))
    ledger.record(
        OperationAttemptStarted(operation_attempt_id, node_attempt_id)
    )
    ledger.record(
        NodeSuccessPublication(
            node_id=node_id,
            node_attempt_id=node_attempt_id,
            operation_attempt_id=operation_attempt_id,
            resolution="executed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest=ImmutableObjectReference(
                content_digest="sha256:" + "7" * 64,
                size=32,
            ),
            outputs=(),
            artifacts=(),
        )
    )


def _selection_result(
    *,
    observation_selector: bool = False,
) -> SelectionResult:
    candidate_input = SelectionInput("source-node", "candidates")
    score_input = SelectionInput("score-node", "scores")
    context = ContextSelectorEvidence(kind="intrinsic")
    objective = SelectionObjectiveEvidence(
        objective_id="objective-1",
        candidate_input=candidate_input,
        score_collection_input=score_input,
        source_partition="scores.default",
        metric=_reference("metric", "fixture.metric"),
        method=_reference("method", "fixture.score-method"),
        context_selector=context,
        utility_transform=_reference(
            "utility_transform",
            "fixture.utility",
        ),
        utility_parameters={},
        declared_weight=1.0,
        effective_weight=1.0,
        match_cardinality="exactly_one",
        missing_policy="error",
    )
    selector = ObservationSelectorEvidence(
        selector_id="selector-1",
        candidate_input=candidate_input,
        score_collection_input=score_input,
        source_partition="scores.default",
        metric=_reference("metric", "fixture.metric"),
        method=_reference("method", "fixture.score-method"),
        context_selector=context,
        match_cardinality="exactly_one",
        missing_policy="error",
    )
    return SelectionResult(
        selection_node_id="node-1",
        selection_method=_reference(
            "method",
            "fixture.selection-method",
        ),
        candidate_input=candidate_input,
        selected_collection_id="selected.collection",
        selected_candidate_ids=("candidate-1",),
        objectives=() if observation_selector else (objective,),
        observation_selectors=(selector,) if observation_selector else (),
    )


def test_ledger_retains_typed_facts_and_projection(tmp_path: Path) -> None:
    ledger, projects, store = _admitted_ledger(tmp_path)
    facts = _durable_facts(store, projects)

    assert all(type(fact) is Fact for fact in facts)
    assert isinstance(facts[0].payload, RunScopeBound)
    assert facts[0].payload.plan_nodes == (_plan_node(),)
    assert isinstance(ledger.cursor, RunCursor)
    assert ledger.projection().ledger_cursor == ledger.cursor
    assert ledger.projection().status == "running"


def test_success_publication_is_one_atomic_typed_transition(tmp_path: Path) -> None:
    ledger, projects, store = _admitted_ledger(tmp_path)
    assert isinstance(store, InMemoryLedgerStore)
    transaction_count = len(
        store.read_transactions(
            root=projects.run_storage_directory("project-1", "run-1").parent,
            relative_parts=("run-1", "ledger"),
        )
    )

    node_attempt_id = "attempt-node-1"
    operation_attempt_id = "operation-node-1"
    ledger.record(NodeAttemptStarted("node-1", node_attempt_id))
    ledger.record(
        OperationAttemptStarted(operation_attempt_id, node_attempt_id)
    )
    acknowledgement = ledger.record(
        NodeSuccessPublication(
            node_id="node-1",
            node_attempt_id=node_attempt_id,
            operation_attempt_id=operation_attempt_id,
            resolution="executed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest=ImmutableObjectReference(
                content_digest="sha256:" + "7" * 64,
                size=32,
            ),
            outputs=(),
            artifacts=(),
        )
    )

    assert acknowledgement.last_sequence - acknowledgement.first_sequence == 3
    assert len(
        store.read_transactions(
            root=projects.run_storage_directory("project-1", "run-1").parent,
            relative_parts=("run-1", "ledger"),
        )
    ) == transaction_count + 3
    ledger.record(RunClosure())
    projection = ledger.projection()
    assert projection.status == "succeeded"
    assert projection.node_dispositions[0].outcome == "succeeded"


def test_attempt_failure_closes_without_fictitious_operation(
    tmp_path: Path,
) -> None:
    ledger, _, _ = _admitted_ledger(tmp_path)
    ledger.record(NodeAttemptStarted("node-1", "attempt-1"))
    error = StructuredError(
        code="node_execution_failed",
        message="Node execution failed safely",
        retryable=False,
        correlation_id="incident-attempt",
        details={"exception_type": "PortValueError"},
    )

    ledger.record(
        NodeFailurePublication(
            node_id="node-1",
            node_attempt_id="attempt-1",
            operation_attempt_id=None,
            resolution="executed",
            error=error,
            failure_origin="attempt",
        )
    )

    terminal = ledger.events()[-2].payload
    assert terminal.failure_origin == "attempt"
    assert terminal.error is error
    assert ledger.projection().node_dispositions[0].outcome == "failed"


@pytest.mark.parametrize("store_kind", ("memory", "filesystem"))
def test_restart_rebuilds_typed_state_from_each_store(
    tmp_path: Path,
    store_kind: str,
) -> None:
    store: LedgerStore = (
        InMemoryLedgerStore()
        if store_kind == "memory"
        else FilesystemLedgerStore()
    )
    ledger, projects, _ = _admitted_ledger(tmp_path, store=store)
    durable_cursor = ledger.cursor

    reloaded = Ledger.load(projects, "project-1", "run-1", store)
    assert reloaded is not None
    assert reloaded.cursor == durable_cursor
    assert reloaded.projection().status == "running"

    reloaded.reconcile_restart()
    assert reloaded.projection().status == "interrupted"
    assert reloaded.terminal is True


def test_cursor_replay_is_typed_and_run_scoped(tmp_path: Path) -> None:
    ledger, _, _ = _admitted_ledger(tmp_path / "first")
    other, _, _ = _admitted_ledger(
        tmp_path / "second",
        run_id="run-2",
    )
    cursor = ledger.record(NodeAttemptStarted("node-1", "attempt-1")).cursor
    ledger.record(OperationAttemptStarted("operation-1", "attempt-1"))

    replay = ledger.replay(cursor)
    assert replay.after_cursor == cursor
    assert replay.through_cursor == ledger.cursor
    assert len(replay.events) == 1
    assert type(replay.events[0]) is Fact
    assert isinstance(replay.events[0].payload, OperationAttemptStarted)

    with pytest.raises(V2RunError, match="stale or belongs") as captured:
        other.replay(cursor)
    assert captured.value.code == "invalid_cursor"


def test_cancellation_decision_is_idempotent_and_orders_writers(
    tmp_path: Path,
) -> None:
    ledger, _, _ = _admitted_ledger(tmp_path)

    requested = ledger.request_cancellation(None)
    repeated = ledger.request_cancellation(requested.cursor)

    assert requested.outcome == "cancellation_requested"
    assert repeated.outcome == "already_requested"
    assert repeated.cursor == requested.cursor
    assert (
        ledger.record_if_active(NodeAttemptStarted("node-1", "attempt-1"))
        is None
    )


def test_unstarted_termination_records_durable_outcome(
    tmp_path: Path,
) -> None:
    interrupted, _, _ = _admitted_ledger(tmp_path / "interrupted")
    interrupted.record(
        NodeDisposition(
            node_id="node-1",
            outcome="interrupted",
            blocked_by=(),
        )
    )
    assert (
        interrupted.projection().node_dispositions[0].outcome
        == "interrupted"
    )

    cancelled, _, _ = _admitted_ledger(tmp_path / "cancelled")
    cancelled.request_cancellation(None)
    cancelled.record(
        NodeDisposition(
            node_id="node-1",
            outcome="cancelled",
            blocked_by=(),
        )
    )
    assert cancelled.projection().node_dispositions[0].outcome == "cancelled"


def test_active_cancellation_precedes_termination(
    tmp_path: Path,
) -> None:
    cancelled, _, _ = _admitted_ledger(tmp_path / "cancelled")
    cancelled.record(NodeAttemptStarted("node-1", "attempt-1"))
    cancelled.record(OperationAttemptStarted("operation-1", "attempt-1"))
    cancellation = cancelled.request_cancellation(None)
    acknowledgement = cancelled.record(
        NodeTerminationPublication(
            node_id="node-1",
            status="cancelled",
            node_attempt_id="attempt-1",
            operation_attempt_id="operation-1",
            operation_status="cancelled",
        )
    )

    assert cancellation.decision_sequence < acknowledgement.first_sequence
    assert cancelled.projection().node_dispositions[0].outcome == "cancelled"


def test_engine_invocation_cancellation_is_durable(
    tmp_path: Path,
) -> None:
    cancelled, _, _ = _admitted_ledger(tmp_path / "cancelled")
    cancelled.record(NodeAttemptStarted("node-1", "attempt-1"))
    cancelled.record(OperationAttemptStarted("operation-1", "attempt-1"))
    cancelled.record(
        EngineInvocationStarted(
            invocation_id="invocation-1",
            operation_attempt_id="operation-1",
            engine_role="predictor",
            engine_identity="fixture.method",
        )
    )
    cancellation = cancelled.request_cancellation(None)
    acknowledgement = cancelled.record(
        EngineInvocationTerminal(
            invocation_id="invocation-1",
            status="cancelled",
        )
    )

    assert cancellation.decision_sequence < acknowledgement.first_sequence
    assert cancelled.events()[-1].payload.status == "cancelled"


@pytest.mark.parametrize("status", ("interrupted", "outcome_unknown"))
def test_active_non_cancel_termination_does_not_require_cancellation(
    tmp_path: Path,
    status: Literal["interrupted", "outcome_unknown"],
) -> None:
    ledger, _, _ = _admitted_ledger(tmp_path / status)
    ledger.record(NodeAttemptStarted("node-1", "attempt-1"))
    ledger.record(OperationAttemptStarted("operation-1", "attempt-1"))

    ledger.record(
        NodeTerminationPublication(
            node_id="node-1",
            status=status,
            node_attempt_id="attempt-1",
            operation_attempt_id="operation-1",
            operation_status=status,
        )
    )

    assert ledger.cancellation_requested is False
    assert ledger.projection().node_dispositions[0].outcome == "interrupted"


def test_provider_readiness_is_recorded(
    tmp_path: Path,
) -> None:
    provider_node = _plan_node(execution_route="adapter")
    passing, _, _ = _admitted_ledger(
        tmp_path / "passing",
        plan_nodes=(provider_node,),
    )
    passing.record(
        ReadinessAttestation(
            binding=provider_node.binding,
            observed_at="2026-08-21T00:00:02+00:00",
            conclusion="passing",
            proof_source="direct-observation",
        )
    )
    passing.record(NodeAttemptStarted("node-1", "attempt-1"))
    passing.record(OperationAttemptStarted("operation-1", "attempt-1"))

    readiness = next(
        fact.payload
        for fact in passing.events()
        if isinstance(fact.payload, ReadinessAttested)
    )
    assert readiness.binding is provider_node.binding
    assert readiness.conclusion == "passing"
    assert readiness.proof_source == "direct-observation"


def test_engine_invocation_keeps_typed_scientific_provenance(
    tmp_path: Path,
) -> None:
    ledger, _, _ = _admitted_ledger(tmp_path)
    ledger.record(NodeAttemptStarted("node-1", "attempt-1"))
    ledger.record(OperationAttemptStarted("operation-1", "attempt-1"))
    workbench_chain_order = ["A"]
    provider_structure_chain_order = ["X"]
    provider_chain_order = ["X"]
    entries = [
        ProviderResidueProjectionEntry(
            residue_id="A:1",
            segment_index=0,
            provider_chain_id="X",
            provider_position=1,
        )
    ]
    provenance = EngineInvocationProvenance(
        effective_randomness=InvocationRandomness(
            control="exact_seed",
            effective_seed=17,
        ),
        provider_residue_projection=ProviderResidueProjection(
            workbench_chain_order=cast(
                tuple[str, ...],
                workbench_chain_order,
            ),
            provider_structure_chain_order=cast(
                tuple[str, ...],
                provider_structure_chain_order,
            ),
            provider_chain_order=cast(
                tuple[str, ...],
                provider_chain_order,
            ),
            entries=cast(
                tuple[ProviderResidueProjectionEntry, ...],
                entries,
            ),
        ),
    )

    acknowledgement = ledger.record(
        EngineInvocationStarted(
            invocation_id="invocation-1",
            operation_attempt_id="operation-1",
            engine_role="predictor",
            engine_identity="fixture.method",
            provenance=provenance,
        )
    )
    workbench_chain_order.append("B")
    provider_structure_chain_order.append("Y")
    provider_chain_order.append("Y")
    entries.clear()

    assert ledger.events()[-1].payload.provenance is provenance
    retained_projection = provenance.provider_residue_projection
    assert retained_projection is not None
    assert retained_projection.workbench_chain_order == ("A",)
    assert retained_projection.provider_structure_chain_order == ("X",)
    assert retained_projection.provider_chain_order == ("X",)
    assert len(retained_projection.entries) == 1
    assert ledger.cursor == acknowledgement.cursor


def test_required_input_evidence_produces_exact_blocker(tmp_path: Path) -> None:
    upstream = _plan_node(node_id="upstream")
    downstream = PlanNodeEvidence(
        node_id="downstream",
        dependencies=("upstream",),
        required_input_sources=(
            PlanRequiredInputEvidence(
                input_port="input",
                sources=(
                    PlanValueSourceEvidence("upstream", "value"),
                ),
            ),
        ),
        node_type=_reference("node_type", "fixture.downstream"),
        binding=_reference(contract_id="fixture.downstream"),
        method=_reference("method", "fixture.downstream-method"),
        execution_route="direct",
    )
    ledger, _, _ = _admitted_ledger(
        tmp_path,
        plan_nodes=(upstream, downstream),
    )
    _publish_success(ledger, node_id="upstream")

    ledger.record(
        NodeDisposition(
            node_id="downstream",
            outcome="blocked",
            blocked_by=("upstream",),
        )
    )

    assert ledger.projection().node_dispositions[-1].blocked_by == ("upstream",)


def test_failed_durable_ack_does_not_install_staged_facts(tmp_path: Path) -> None:
    class ControlledStore:
        def __init__(self) -> None:
            self.delegate = InMemoryLedgerStore()
            self.fail = False

        def read_transactions(self, **arguments: object):
            return self.delegate.read_transactions(**arguments)  # type: ignore[arg-type]

        def publish(self, **arguments: object) -> None:
            if self.fail:
                raise OSError("fixture acknowledgement failure")
            self.delegate.publish(**arguments)  # type: ignore[arg-type]

    store = ControlledStore()
    ledger, projects, _ = _admitted_ledger(tmp_path, store=store)
    ledger.record(NodeAttemptStarted("node-1", "attempt-1"))
    ledger.record(OperationAttemptStarted("operation-1", "attempt-1"))
    durable_facts = _durable_facts(store, projects)
    store.fail = True

    with pytest.raises(V2RunError) as captured:
        ledger.record(
            NodeSuccessPublication(
                node_id="node-1",
                node_attempt_id="attempt-1",
                operation_attempt_id="operation-1",
                resolution="executed",
                result_identity="sha256:" + "6" * 64,
                node_result_manifest=ImmutableObjectReference(
                    content_digest="sha256:" + "7" * 64,
                    size=32,
                ),
                outputs=(),
                artifacts=(),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert _durable_facts(store, projects) == durable_facts


@pytest.mark.parametrize(
    ("mode", "invalid_field"),
    (
        ("objective", "result_input"),
        ("objective", "selection_method"),
        ("objective", "selected_candidate_id"),
        ("objective", "objective_id"),
        ("objective", "objective_input"),
        ("objective", "source_partition"),
        ("objective", "metric_kind"),
        ("objective", "method_kind"),
        ("objective", "utility_kind"),
        ("objective", "declared_weight"),
        ("objective", "effective_weight"),
        ("objective", "match_cardinality"),
        ("objective", "missing_policy"),
        ("objective", "context"),
        ("objective", "context_normalization"),
        ("selector", "selector_id"),
        ("selector", "selector_partition"),
        ("selector", "selector_metric_kind"),
        ("selector", "selector_cardinality"),
        ("selector", "selector_context"),
        ("selector", "selector_context_unit"),
    ),
)
def test_selection_decode_rejects_invalid_scientific_evidence(
    mode: str,
    invalid_field: str,
) -> None:
    terminal = SelectionTerminal(
        status="succeeded",
        result=_selection_result(observation_selector=mode == "selector"),
    )
    canonical = payload_to_canonical(terminal)
    assert isinstance(
        payload_from_canonical("selection_terminal", canonical),
        SelectionTerminal,
    )
    result = canonical["result"]

    if invalid_field == "result_input":
        result["candidate_input"]["node_id"] = "not a canonical id"
    elif invalid_field == "selection_method":
        result["selection_method"]["contract_kind"] = "metric"
    elif invalid_field == "selected_candidate_id":
        result["selected_candidate_ids"] = ["not a canonical id"]
    elif invalid_field in {
        "objective_id",
        "objective_input",
        "source_partition",
        "metric_kind",
        "method_kind",
        "utility_kind",
        "declared_weight",
        "effective_weight",
        "match_cardinality",
        "missing_policy",
        "context",
        "context_normalization",
    }:
        objective = result["objectives"][0]
        if invalid_field == "objective_id":
            objective["objective_id"] = ""
        elif invalid_field == "objective_input":
            objective["candidate_input"]["output_port"] = ""
        elif invalid_field == "source_partition":
            objective["source_partition"] = "not a canonical partition"
        elif invalid_field == "metric_kind":
            objective["metric"]["contract_kind"] = "method"
        elif invalid_field == "method_kind":
            objective["method"]["contract_kind"] = "metric"
        elif invalid_field == "utility_kind":
            objective["utility_transform"]["contract_kind"] = "metric"
        elif invalid_field == "declared_weight":
            objective["declared_weight"] = 0
        elif invalid_field == "effective_weight":
            objective["effective_weight"] = 0.5
        elif invalid_field == "match_cardinality":
            objective["match_cardinality"] = "many"
        elif invalid_field == "missing_policy":
            objective["missing_policy"] = "skip"
        elif invalid_field == "context":
            objective["context_selector"] = {
                "kind": "pairwise",
                "subject_role": "reference",
                "reference_role": "subject",
                "pairing_mode": "fixed_reference",
                "normalization": "reference-length",
            }
        else:
            objective["context_selector"] = {
                "kind": "pairwise",
                "subject_role": "subject",
                "reference_role": "reference",
                "pairing_mode": "fixed_reference",
                "normalization": "not canonical",
            }
    else:
        selector = result["observation_selectors"][0]
        if invalid_field == "selector_id":
            selector["selector_id"] = ""
        elif invalid_field == "selector_partition":
            selector["source_partition"] = "not a canonical partition"
        elif invalid_field == "selector_metric_kind":
            selector["metric"]["contract_kind"] = "method"
        elif invalid_field == "selector_cardinality":
            selector["match_cardinality"] = "many"
        elif invalid_field == "selector_context":
            selector["context_selector"] = {
                "kind": "calibration",
                "calibration_metric": "metric",
                "calibration_value": "not-a-number",
                "calibration_unit": "dimensionless",
                "population_id": "population",
            }
        else:
            selector["context_selector"] = {
                "kind": "calibration",
                "calibration_metric": "metric",
                "calibration_value": 0.5,
                "calibration_unit": "not canonical",
                "population_id": "population",
            }

    with pytest.raises(ValueError):
        payload_from_canonical("selection_terminal", canonical)


def test_restart_rejects_invalid_persisted_selection_grammar(
    tmp_path: Path,
) -> None:
    store = InMemoryLedgerStore()
    ledger, projects, _ = _admitted_ledger(
        tmp_path,
        store=store,
        plan_nodes=(_plan_node(selection_consumer=True),),
    )
    _publish_success(ledger)
    ledger.record(
        RunClosure(
            selections=(
                SelectionTerminal(
                    status="succeeded",
                    result=_selection_result(),
                ),
            ),
        )
    )

    class InvalidSelectionStore:
        def read_transactions(
            self,
            *,
            root: Path,
            relative_parts: tuple[str, ...],
        ) -> tuple[tuple[str, bytes], ...]:
            retained = list(
                store.read_transactions(
                    root=root,
                    relative_parts=relative_parts,
                )
            )
            name, encoded = retained[-1]
            raw = json.loads(encoded)
            selection = next(
                fact
                for fact in raw["facts"]
                if fact["fact_type"] == "selection_terminal"
            )
            selection["payload"]["result"]["objectives"][0][
                "missing_policy"
            ] = "skip"
            retained[-1] = (name, json.dumps(raw).encode("utf-8"))
            return tuple(retained)

        def publish(
            self,
            *,
            root: Path,
            relative_parts: tuple[str, ...],
            payload: bytes,
        ) -> None:
            store.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    with pytest.raises(RuntimeError, match="transaction is invalid"):
        Ledger.load(
            projects,
            "project-1",
            "run-1",
            InvalidSelectionStore(),
        )


def test_structured_error_is_frozen_before_it_reaches_a_fact() -> None:
    source = {"node_ids": ["node-1"]}
    error = StructuredError(
        code="operation_failed",
        message="fixture failed",
        retryable=False,
        correlation_id="correlation-1",
        details=source,
    )
    source["node_ids"].append("node-2")

    assert isinstance(error.details, Mapping)
    assert error.details["node_ids"] == ("node-1",)
    with pytest.raises((FrozenInstanceError, TypeError)):
        error.code = "changed"  # type: ignore[misc]
