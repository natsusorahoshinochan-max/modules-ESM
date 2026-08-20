"""Typed transition contracts for the Run Evidence Ledger."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import stat
import threading
from typing import Any, Literal, Mapping

import pytest

from core import ProjectManager
import core.run_execution_v2 as run_execution_v2
import core.storage as storage


def _binding_reference(
    *,
    contract_id: str = "fixture.binding",
    digest_marker: str = "8",
) -> dict[str, str]:
    return {
        "contract_kind": "binding",
        "contract_id": contract_id,
        "contract_version": "1.0.0",
        "contract_digest": "sha256:" + digest_marker * 64,
    }


def _contract_lock_digest(
    entries: tuple[dict[str, Any], ...],
) -> str:
    return run_execution_v2.canonical_sha256(
        {
            "schema_namespace": run_execution_v2.CONTRACT_LOCK_NAMESPACE,
            "entries": list(entries),
        }
    )


def _canonical_contract_references(
    values: tuple[dict[str, Any] | Mapping[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    by_key = {
        (
            value["contract_kind"],
            value["contract_id"],
            value["contract_version"],
            value["contract_digest"],
        ): dict(value)
        for value in values
    }
    return tuple(by_key[key] for key in sorted(by_key))


def _typed_output(node_id: str, output_port: str) -> dict[str, Any]:
    result_identity = "sha256:" + "6" * 64
    return {
        "node_id": node_id,
        "output_port": output_port,
        "port_type": {
            "contract_kind": "port_type",
            "contract_id": "fixture.value",
            "contract_version": "1.0.0",
            "contract_digest": "sha256:" + "9" * 64,
        },
        "content_digest": "sha256:" + "a" * 64,
        "result_identity": result_identity,
        "materialization": {
            "run_id": "run-1",
            "resolution": "cache_replayed",
        },
        "producer_provenance": {
            "producer_run_id": "run-1",
            "producer_result_identity": result_identity,
            "output_port": output_port,
        },
        "value_count": 1,
        "value_manifest_reference": "sha256:" + "b" * 64,
    }


def _readiness_attestation(
    binding: dict[str, str],
    *,
    conclusion: Literal["passing", "failing"] = "passing",
) -> run_execution_v2.ReadinessAttestation:
    payload = {
        "binding": binding,
        "readiness_contract_digest": "sha256:" + "c" * 64,
        "observed_at": "2026-08-21T00:00:02+00:00",
        "conclusion": conclusion,
        "proof_source": "direct-observation",
    }
    return run_execution_v2.ReadinessAttestation(
        **payload,
        attestation_digest=run_execution_v2.canonical_sha256(
            {
                "schema_namespace": (
                    run_execution_v2.READINESS_ATTESTATION_NAMESPACE
                ),
                **payload,
            }
        ),
    )


def _plan_node(
    *,
    node_id: str = "node-1",
    dependencies: tuple[str, ...] = (),
    required_input_sources: tuple[
        tuple[str, tuple[tuple[str, str], ...]],
        ...,
    ] = (),
    binding: dict[str, str] | None = None,
    execution_route: Literal["direct", "adapter"] = "direct",
    selection_required: bool = False,
) -> run_execution_v2._PlanNodeEvidence:
    return run_execution_v2._PlanNodeEvidence(
        node_id=node_id,
        dependencies=dependencies,
        required_input_sources=tuple(
            run_execution_v2._PlanRequiredInputEvidence(
                input_port=input_port,
                sources=tuple(
                    run_execution_v2._PlanValueSourceEvidence(
                        source_node_id,
                        output_port,
                    )
                    for source_node_id, output_port in sources
                ),
            )
            for input_port, sources in required_input_sources
        ),
        result_identity_plan_facts_digest="sha256:" + "1" * 64,
        binding=binding or _binding_reference(),
        execution_route=execution_route,
        selection_consumer=selection_required,
    )


def _plan_contract_scope(
    plan_nodes: tuple[run_execution_v2._PlanNodeEvidence, ...],
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], str]:
    root_values = tuple(
        reference
        for node in plan_nodes
        for reference in (
            node.binding,
            *((node.node_type,) if node.node_type is not None else ()),
        )
    )
    roots = tuple(
        dict(reference)
        for reference in _canonical_contract_references(root_values)
    )
    contracts = tuple(
        dict(reference)
        for reference in _canonical_contract_references(
            (
                *root_values,
                *(
                    output["port_type"]
                    for node in plan_nodes
                    for output in node.artifact_outputs
                ),
            )
        )
    )
    return contracts, roots, _contract_lock_digest(contracts)


def _admitted_ledger(
    tmp_path,
    *,
    selection_required: bool = False,
    plan_nodes: tuple[run_execution_v2._PlanNodeEvidence, ...] | None = None,
    transaction_store: run_execution_v2.LedgerTransactionStore | None = None,
) -> run_execution_v2._RunEvidenceLedger:
    retained_plan_nodes = plan_nodes or (
        _plan_node(selection_required=selection_required),
    )
    ledger, workflow_commit_id = _scoped_ledger(
        tmp_path,
        retained_plan_nodes,
        transaction_store=transaction_store,
    )
    availability_by_binding = {
        tuple(node.binding.values()): node.binding for node in retained_plan_nodes
    }
    for binding in availability_by_binding.values():
        ledger.record(
            run_execution_v2.AvailabilityBinding(
                binding=binding,
                catalog_observed_at="2026-08-21T00:00:00+00:00",
                available=True,
            )
        )
    ledger.record(
        run_execution_v2.RunAdmission(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
        )
    )
    ledger.record(
        run_execution_v2.RunStart(
            started_at="2026-08-21T00:00:01+00:00"
        )
    )
    return ledger


def _scoped_ledger(
    tmp_path,
    plan_nodes: tuple[run_execution_v2._PlanNodeEvidence, ...],
    *,
    transaction_store: run_execution_v2.LedgerTransactionStore | None = None,
) -> tuple[run_execution_v2._RunEvidenceLedger, str]:
    resolved_contracts, resolved_contract_roots, contract_lock_digest = (
        _plan_contract_scope(plan_nodes)
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        plan_nodes,
        transaction_store,
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=resolved_contract_roots,
    )
    workflow_commit_id = "workflow-commit-" + "0" * 64
    ledger.record(
        run_execution_v2.RunScopeBinding(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
            workflow_digest="sha256:" + "2" * 64,
            contract_lock_digest=contract_lock_digest,
            execution_plan_digest="sha256:" + "4" * 64,
            catalog_contract_digest="sha256:" + "5" * 64,
            resolved_contracts=resolved_contracts,
            resolved_contract_roots=resolved_contract_roots,
        )
    )
    return ledger, workflow_commit_id


def _operation_failure(
    ledger: run_execution_v2._RunEvidenceLedger,
    *,
    node_id: str,
) -> None:
    attempt_id = f"node-attempt-{node_id}"
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id=node_id,
            node_attempt_id=attempt_id,
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id=attempt_id,
            operation_attempt_id=f"operation-{node_id}",
        )
    )
    ledger.record(
        run_execution_v2.NodeFailurePublication(
            node_id=node_id,
            node_attempt_id=attempt_id,
            operation_attempt_id=f"operation-{node_id}",
            resolution="executed",
            error=run_execution_v2._public_failure(
                RuntimeError("fixture operation failed")
            ),
            failure_origin="operation",
        )
    )


def test_unstarted_termination_rejects_started_attempt_fields(tmp_path) -> None:
    ledger = _admitted_ledger(tmp_path)
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.NodeTerminationPublication(
                node_id="node-1",
                status="interrupted",
                node_attempt_id=None,  # type: ignore[arg-type]
                operation_attempt_id="operation-other",
                resolution="cache_replayed",
                error=run_execution_v2._public_failure(
                    RuntimeError("fixture interruption")
                ),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_cancellation_is_a_barrier_to_later_attempt_starts(tmp_path) -> None:
    node_ledger = _admitted_ledger(tmp_path / "node")
    node_ledger.request_cancellation(None)
    with pytest.raises(run_execution_v2.V2RunError):
        node_ledger.record(
            run_execution_v2.NodeAttemptStart(
                node_id="node-1",
                node_attempt_id="node-attempt-1",
            )
        )

    operation_ledger = _admitted_ledger(tmp_path / "operation")
    operation_ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    operation_ledger.request_cancellation(None)
    with pytest.raises(run_execution_v2.V2RunError):
        operation_ledger.record(
            run_execution_v2.OperationAttemptStart(
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
            )
        )

    invocation_ledger = _admitted_ledger(tmp_path / "invocation")
    invocation_ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    invocation_ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    invocation_ledger.request_cancellation(None)
    with pytest.raises(run_execution_v2.V2RunError):
        invocation_ledger.record(
            run_execution_v2.EngineInvocationStart(
                invocation_id="invocation-1",
                operation_attempt_id="operation-1",
                engine_role="primary",
                engine_identity="sha256:" + "6" * 64,
            )
        )


def test_cancellation_is_a_barrier_to_success_publication(tmp_path) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    ledger.request_cancellation(None)
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.NodeSuccessPublication(
                node_id="node-1",
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
                resolution="executed",
                result_identity="sha256:" + "6" * 64,
                node_result_manifest={
                    "content_digest": "sha256:" + "7" * 64,
                    "size": 128,
                },
                outputs=(),
                artifacts=(),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_cancellation_commit_orders_before_a_racing_node_start(tmp_path) -> None:
    cancellation_entered = threading.Event()
    release_cancellation = threading.Event()

    class PauseCancellationAcknowledgement:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            transaction = json.loads(payload)
            if any(
                fact["fact_type"] == "cancellation_requested"
                for fact in transaction["facts"]
            ):
                cancellation_entered.set()
                assert release_cancellation.wait(timeout=2)
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    ledger = _admitted_ledger(
        tmp_path,
        transaction_store=PauseCancellationAcknowledgement(),
    )
    cancellation: dict[str, Any] = {}
    start_errors: list[run_execution_v2.V2RunError] = []

    cancellation_worker = threading.Thread(
        target=lambda: cancellation.update(ledger.request_cancellation(None))
    )

    def start_node() -> None:
        try:
            ledger.record(
                run_execution_v2.NodeAttemptStart(
                    node_id="node-1",
                    node_attempt_id="node-attempt-1",
                )
            )
        except run_execution_v2.V2RunError as error:
            start_errors.append(error)

    cancellation_worker.start()
    assert cancellation_entered.wait(timeout=2)
    start_worker = threading.Thread(target=start_node)
    start_worker.start()
    release_cancellation.set()
    cancellation_worker.join(timeout=2)
    start_worker.join(timeout=2)

    assert not cancellation_worker.is_alive()
    assert not start_worker.is_alive()
    assert cancellation["outcome"] == "cancellation_requested"
    assert [error.code for error in start_errors] == ["evidence_unavailable"]
    assert not any(
        fact["fact_type"] == "node_attempt_started"
        for fact in ledger.facts
    )


def test_ledger_admits_run_through_typed_transitions(tmp_path) -> None:
    plan_node = _plan_node()
    resolved_contracts, resolved_contract_roots, contract_lock_digest = (
        _plan_contract_scope((plan_node,))
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=resolved_contract_roots,
    )
    workflow_commit_id = "workflow-commit-" + "0" * 64

    ledger.record(
        run_execution_v2.RunScopeBinding(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
            workflow_digest="sha256:" + "2" * 64,
            contract_lock_digest=contract_lock_digest,
            execution_plan_digest="sha256:" + "4" * 64,
            catalog_contract_digest="sha256:" + "5" * 64,
            resolved_contracts=resolved_contracts,
            resolved_contract_roots=resolved_contract_roots,
        )
    )
    ledger.record(
        run_execution_v2.AvailabilityBinding(
            binding=_binding_reference(),
            catalog_observed_at="2026-08-21T00:00:00+00:00",
            available=True,
        )
    )
    admitted = ledger.record(
        run_execution_v2.RunAdmission(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
        )
    )
    ledger.record(
        run_execution_v2.RunStart(
            started_at="2026-08-21T00:00:01+00:00"
        )
    )

    assert admitted.last_sequence == 3
    assert [fact["fact_type"] for fact in ledger.facts] == [
        "run_scope_bound",
        "availability_bound",
        "run_admitted",
        "run_started",
    ]
    assert not hasattr(ledger, "append")
    assert not hasattr(ledger, "commit")


def test_run_admission_requires_one_availability_per_exact_plan_binding(
    tmp_path,
) -> None:
    first_binding = _binding_reference(
        contract_id="fixture.first",
        digest_marker="8",
    )
    second_binding = _binding_reference(
        contract_id="fixture.second",
        digest_marker="9",
    )
    plan_nodes = (
        _plan_node(node_id="first", binding=first_binding),
        _plan_node(node_id="second", binding=second_binding),
    )
    ledger, workflow_commit_id = _scoped_ledger(tmp_path, plan_nodes)
    ledger.record(
        run_execution_v2.AvailabilityBinding(
            binding=first_binding,
            catalog_observed_at="2026-08-21T00:00:00+00:00",
            available=True,
        )
    )
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.RunAdmission(
                workflow_commit_id=workflow_commit_id,
                workflow_commit_revision=1,
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_availability_binding_is_exact_and_unique(tmp_path) -> None:
    plan_node = _plan_node()
    ledger, _ = _scoped_ledger(tmp_path, (plan_node,))
    transition = run_execution_v2.AvailabilityBinding(
        binding=plan_node.binding,
        catalog_observed_at="2026-08-21T00:00:00+00:00",
        available=True,
    )
    ledger.record(transition)
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(transition)

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_provider_operation_requires_one_passing_readiness_attestation(
    tmp_path,
) -> None:
    provider = _plan_node(execution_route="adapter")
    missing = _admitted_ledger(tmp_path / "missing", plan_nodes=(provider,))
    missing.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        missing.record(
            run_execution_v2.OperationAttemptStart(
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
            )
        )

    assert captured.value.code == "evidence_unavailable"

    passing = _admitted_ledger(tmp_path / "passing", plan_nodes=(provider,))
    passing.record(_readiness_attestation(_binding_reference()))
    passing.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    acknowledgement = passing.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )

    assert passing.facts[acknowledgement.last_sequence - 1]["fact_type"] == (
        "operation_attempt_started"
    )


def test_readiness_attestation_is_exact_and_unique(tmp_path) -> None:
    provider = _plan_node(execution_route="adapter")
    ledger = _admitted_ledger(tmp_path, plan_nodes=(provider,))
    ledger.record(_readiness_attestation(_binding_reference()))
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            _readiness_attestation(
                _binding_reference(),
                conclusion="failing",
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


@pytest.mark.parametrize(
    "scope_change",
    (
        {"workflow_digest": "not-a-digest"},
        {"execution_plan_digest": "not-a-digest"},
        {"catalog_contract_digest": "not-a-digest"},
        {"contract_lock_digest": "not-a-digest"},
        {"contract_lock_digest": "sha256:" + "d" * 64},
    ),
    ids=(
        "workflow",
        "execution-plan",
        "catalog",
        "contract-lock-shape",
        "contract-lock-content",
    ),
)
def test_run_scope_rejects_malformed_private_digests(
    tmp_path,
    scope_change,
) -> None:
    plan_node = _plan_node()
    resolved_contracts, resolved_contract_roots, contract_lock_digest = (
        _plan_contract_scope((plan_node,))
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=resolved_contract_roots,
    )
    scope = {
        "workflow_commit_id": "workflow-commit-" + "0" * 64,
        "workflow_commit_revision": 1,
        "workflow_digest": "sha256:" + "2" * 64,
        "contract_lock_digest": contract_lock_digest,
        "execution_plan_digest": "sha256:" + "4" * 64,
        "catalog_contract_digest": "sha256:" + "5" * 64,
        "resolved_contracts": resolved_contracts,
        "resolved_contract_roots": resolved_contract_roots,
        **scope_change,
    }

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(run_execution_v2.RunScopeBinding(**scope))

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == ()


def test_run_scope_requires_exact_plan_contract_roots(tmp_path) -> None:
    plan_node = _plan_node()
    resolved_contracts, _, contract_lock_digest = _plan_contract_scope(
        (plan_node,)
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=(dict(plan_node.binding),),
    )

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.RunScopeBinding(
                workflow_commit_id="workflow-commit-" + "0" * 64,
                workflow_commit_revision=1,
                workflow_digest="sha256:" + "2" * 64,
                contract_lock_digest=contract_lock_digest,
                execution_plan_digest="sha256:" + "4" * 64,
                catalog_contract_digest="sha256:" + "5" * 64,
                resolved_contracts=resolved_contracts,
                resolved_contract_roots=(),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == ()


def test_run_scope_requires_the_expected_resolved_contract_closure(
    tmp_path,
) -> None:
    plan_node = _plan_node()
    extra_contract = {
        "contract_kind": "port_type",
        "contract_id": "fixture.value",
        "contract_version": "1.0.0",
        "contract_digest": "sha256:" + "9" * 64,
    }
    expected_contracts = tuple(
        dict(reference)
        for reference in _canonical_contract_references(
            (plan_node.binding, extra_contract)
        )
    )
    expected_roots = (dict(plan_node.binding),)
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        expected_resolved_contracts=expected_contracts,
        expected_contract_roots=expected_roots,
    )
    incomplete_contracts = (dict(plan_node.binding),)

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.RunScopeBinding(
                workflow_commit_id="workflow-commit-" + "0" * 64,
                workflow_commit_revision=1,
                workflow_digest="sha256:" + "2" * 64,
                contract_lock_digest=_contract_lock_digest(
                    incomplete_contracts
                ),
                execution_plan_digest="sha256:" + "4" * 64,
                catalog_contract_digest="sha256:" + "5" * 64,
                resolved_contracts=incomplete_contracts,
                resolved_contract_roots=expected_roots,
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == ()


def test_availability_rejects_a_malformed_binding_timestamp(tmp_path) -> None:
    plan_node = _plan_node()
    ledger, _ = _scoped_ledger(tmp_path, (plan_node,))

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.AvailabilityBinding(
                binding=plan_node.binding,
                catalog_observed_at="not-a-timestamp",
                available=True,
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert [fact["fact_type"] for fact in ledger.facts] == ["run_scope_bound"]


def test_typed_invocation_provenance_is_transported_then_admitted_by_ledger(
    tmp_path,
) -> None:
    recorded: list[dict[str, Any]] = []

    class Recorder:
        @contextmanager
        def invoke(self, **transition: Any):
            recorded.append(transition)
            yield "invocation-1"

    provenance = run_execution_v2.EngineInvocationProvenance(
        effective_randomness=run_execution_v2.InvocationRandomness(
            control="exact_seed",
            effective_seed=17,
        ),
        provider_residue_projection=(
            run_execution_v2.ProviderResidueProjection(
                workbench_chain_order=("X", "Y"),
                provider_structure_chain_order=("A", "B"),
                provider_chain_order=("B", "A"),
                entries=(
                    run_execution_v2.ProviderResidueProjectionEntry(
                        residue_id="X:6",
                        segment_index=0,
                        provider_chain_id="A",
                        provider_position=1,
                    ),
                    run_execution_v2.ProviderResidueProjectionEntry(
                        residue_id="Y:20",
                        segment_index=1,
                        provider_chain_id="B",
                        provider_position=1,
                    ),
                ),
            )
        ),
    )
    resources = run_execution_v2.RunResources(
        project_id="project-1",
        run_id="run-1",
        node_id="node-1",
        _projects=ProjectManager(tmp_path / "resource-projects"),
        _invocation_recorder=Recorder(),
    )

    with resources.engine_invocation(invocation_provenance=provenance):
        pass

    assert recorded[0]["invocation_provenance"] is provenance

    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    ledger.record(
        run_execution_v2.EngineInvocationStart(
            invocation_id="invocation-1",
            operation_attempt_id="operation-1",
            engine_role="primary",
            engine_identity="sha256:" + "6" * 64,
            provenance=provenance,
        )
    )

    started = ledger.facts[-1]
    assert started["fact_type"] == "engine_invocation_started"
    assert started["payload"]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": 17,
        },
        "provider_residue_projection": {
            "position_semantics": "one_based_chain_local",
            "workbench_chain_order": ["X", "Y"],
            "provider_structure_chain_order": ["A", "B"],
            "provider_chain_order": ["B", "A"],
            "entries": [
                {
                    "residue_id": "X:6",
                    "segment_index": 0,
                    "provider_chain_id": "A",
                    "provider_position": 1,
                },
                {
                    "residue_id": "Y:20",
                    "segment_index": 1,
                    "provider_chain_id": "B",
                    "provider_position": 1,
                },
            ],
        },
    }


def test_invalid_invocation_provenance_fails_only_at_ledger_durable_write(
    tmp_path,
) -> None:
    recorded: list[dict[str, Any]] = []

    class Recorder:
        @contextmanager
        def invoke(self, **transition: Any):
            recorded.append(transition)
            yield "invocation-1"

    invalid = run_execution_v2.EngineInvocationProvenance(
        provider_residue_projection=(
            run_execution_v2.ProviderResidueProjection(
                workbench_chain_order=("X",),
                provider_structure_chain_order=("A",),
                provider_chain_order=("B",),
                entries=(
                    run_execution_v2.ProviderResidueProjectionEntry(
                        residue_id="X:1",
                        segment_index=0,
                        provider_chain_id="A",
                        provider_position=1,
                    ),
                ),
            )
        )
    )
    resources = run_execution_v2.RunResources(
        project_id="project-1",
        run_id="run-1",
        node_id="node-1",
        _projects=ProjectManager(tmp_path / "resource-projects"),
        _invocation_recorder=Recorder(),
    )

    with resources.engine_invocation(invocation_provenance=invalid):
        pass
    assert recorded[0]["invocation_provenance"] is invalid

    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.EngineInvocationStart(
                invocation_id="invocation-1",
                operation_attempt_id="operation-1",
                engine_role="primary",
                engine_identity="sha256:" + "6" * 64,
                provenance=invalid,
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


@pytest.mark.parametrize(
    "provenance",
    (
        run_execution_v2.EngineInvocationProvenance(),
        run_execution_v2.EngineInvocationProvenance(
            effective_randomness=run_execution_v2.InvocationRandomness(
                control="exact_seed"
            )
        ),
        run_execution_v2.EngineInvocationProvenance(
            effective_randomness=run_execution_v2.InvocationRandomness(
                control="provider_uncontrolled",
                effective_seed=17,
            )
        ),
        run_execution_v2.EngineInvocationProvenance(
            provider_residue_projection=(
                run_execution_v2.ProviderResidueProjection(
                    workbench_chain_order=("A",),
                    provider_structure_chain_order=("A", "B"),
                    provider_chain_order=("B", "A"),
                    entries=(
                        run_execution_v2.ProviderResidueProjectionEntry(
                            residue_id="A:1",
                            segment_index=0,
                            provider_chain_id="A",
                            provider_position=1,
                        ),
                        run_execution_v2.ProviderResidueProjectionEntry(
                            residue_id="A:8",
                            segment_index=1,
                            provider_chain_id="B",
                            provider_position=2,
                        ),
                    ),
                )
            )
        ),
    ),
    ids=(
        "empty",
        "exact-seed-missing",
        "uncontrolled-with-seed",
        "segment-position-discontinuous",
    ),
)
def test_ledger_owns_every_invocation_provenance_invariant(
    tmp_path,
    provenance,
) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.EngineInvocationStart(
                invocation_id="invocation-1",
                operation_attempt_id="operation-1",
                engine_role="primary",
                engine_identity="sha256:" + "6" * 64,
                provenance=provenance,
            )
        )

    assert captured.value.code == "evidence_unavailable"


def test_ledger_admits_one_workbench_chain_split_across_provider_segments(
    tmp_path,
) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    projection = run_execution_v2.ProviderResidueProjection(
        workbench_chain_order=("A",),
        provider_structure_chain_order=("A", "B"),
        provider_chain_order=("B", "A"),
        entries=(
            run_execution_v2.ProviderResidueProjectionEntry(
                residue_id="A:1",
                segment_index=0,
                provider_chain_id="A",
                provider_position=1,
            ),
            run_execution_v2.ProviderResidueProjectionEntry(
                residue_id="A:2",
                segment_index=0,
                provider_chain_id="A",
                provider_position=2,
            ),
            run_execution_v2.ProviderResidueProjectionEntry(
                residue_id="A:8",
                segment_index=1,
                provider_chain_id="B",
                provider_position=1,
            ),
        ),
    )

    ledger.record(
        run_execution_v2.EngineInvocationStart(
            invocation_id="invocation-1",
            operation_attempt_id="operation-1",
            engine_role="primary",
            engine_identity="sha256:" + "6" * 64,
            provenance=run_execution_v2.EngineInvocationProvenance(
                provider_residue_projection=projection
            ),
        )
    )

    retained = ledger.facts[-1]["payload"]["invocation_provenance"]
    assert retained["provider_residue_projection"]["entries"][-1] == {
        "residue_id": "A:8",
        "segment_index": 1,
        "provider_chain_id": "B",
        "provider_position": 1,
    }


def test_child_invocation_requires_a_succeeded_parent(tmp_path) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    ledger.record(
        run_execution_v2.EngineInvocationStart(
            invocation_id="parent",
            operation_attempt_id="operation-1",
            engine_role="parent",
            engine_identity="sha256:" + "6" * 64,
        )
    )
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.EngineInvocationStart(
                invocation_id="child",
                operation_attempt_id="operation-1",
                engine_role="child",
                engine_identity="sha256:" + "7" * 64,
                parent_invocation_id="parent",
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_required_dependency_failure_blocks_node_attempt_start(tmp_path) -> None:
    source = _plan_node(node_id="source")
    sink = _plan_node(
        node_id="sink",
        dependencies=("source",),
        required_input_sources=(
            ("input", (("source", "value"),)),
        ),
    )
    ledger = _admitted_ledger(tmp_path, plan_nodes=(source, sink))
    _operation_failure(ledger, node_id="source")
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.NodeAttemptStart(
                node_id="sink",
                node_attempt_id="node-attempt-sink",
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_optional_dependency_failure_does_not_block_node_attempt_start(
    tmp_path,
) -> None:
    source = _plan_node(node_id="source")
    sink = _plan_node(
        node_id="sink",
        dependencies=("source",),
    )
    ledger = _admitted_ledger(tmp_path, plan_nodes=(source, sink))
    _operation_failure(ledger, node_id="source")

    acknowledgement = ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="sink",
            node_attempt_id="node-attempt-sink",
        )
    )

    assert ledger.facts[acknowledgement.last_sequence - 1]["payload"] == {
        "node_id": "sink",
        "node_attempt_id": "node-attempt-sink",
    }


def test_any_published_source_satisfies_one_required_many_valued_input(
    tmp_path,
) -> None:
    successful = _plan_node(node_id="successful")
    failed = _plan_node(node_id="failed")
    sink = _plan_node(
        node_id="sink",
        dependencies=("failed", "successful"),
        required_input_sources=(
            (
                "input",
                (("failed", "value"), ("successful", "value")),
            ),
        ),
    )
    ledger = _admitted_ledger(
        tmp_path,
        plan_nodes=(successful, failed, sink),
    )
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="successful",
            node_attempt_id="node-attempt-successful",
        )
    )
    ledger.record(
        run_execution_v2.NodeSuccessPublication(
            node_id="successful",
            node_attempt_id="node-attempt-successful",
            operation_attempt_id=None,
            resolution="cache_replayed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest={
                "content_digest": "sha256:" + "7" * 64,
                "size": 128,
            },
            outputs=(_typed_output("successful", "value"),),
            artifacts=(),
            nonempty_output_ports=("value",),
        )
    )
    _operation_failure(ledger, node_id="failed")

    acknowledgement = ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="sink",
            node_attempt_id="node-attempt-sink",
        )
    )

    assert ledger.facts[acknowledgement.last_sequence - 1]["payload"] == {
        "node_id": "sink",
        "node_attempt_id": "node-attempt-sink",
    }


def test_blocked_disposition_cannot_cite_an_optional_dependency(tmp_path) -> None:
    source = _plan_node(node_id="source")
    sink = _plan_node(
        node_id="sink",
        dependencies=("source",),
    )
    ledger = _admitted_ledger(tmp_path, plan_nodes=(source, sink))
    _operation_failure(ledger, node_id="source")
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.UnstartedNodeConclusion(
                node_id="sink",
                outcome="blocked",
                blocked_by=("source",),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_succeeded_source_without_a_required_value_is_a_real_blocker(
    tmp_path,
) -> None:
    source = _plan_node(node_id="source")
    sink = _plan_node(
        node_id="sink",
        dependencies=("source",),
        required_input_sources=(
            ("input", (("source", "value"),)),
        ),
    )
    ledger = _admitted_ledger(tmp_path, plan_nodes=(source, sink))
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="source",
            node_attempt_id="node-attempt-source",
        )
    )
    ledger.record(
        run_execution_v2.NodeSuccessPublication(
            node_id="source",
            node_attempt_id="node-attempt-source",
            operation_attempt_id=None,
            resolution="cache_replayed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest={
                "content_digest": "sha256:" + "7" * 64,
                "size": 128,
            },
            outputs=(),
            artifacts=(),
        )
    )

    acknowledgement = ledger.record(
        run_execution_v2.UnstartedNodeConclusion(
            node_id="sink",
            outcome="blocked",
            blocked_by=("source",),
        )
    )

    assert ledger.facts[acknowledgement.last_sequence - 1]["payload"] == {
        "node_id": "sink",
        "outcome": "blocked",
        "blocked_by": ["source"],
    }


def test_cancellation_is_a_barrier_to_a_later_blocked_conclusion(
    tmp_path,
) -> None:
    source = _plan_node(node_id="source")
    sink = _plan_node(
        node_id="sink",
        dependencies=("source",),
        required_input_sources=(("input", (("source", "value"),)),),
    )
    ledger = _admitted_ledger(tmp_path, plan_nodes=(source, sink))
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="source",
            node_attempt_id="node-attempt-source",
        )
    )
    ledger.record(
        run_execution_v2.NodeSuccessPublication(
            node_id="source",
            node_attempt_id="node-attempt-source",
            operation_attempt_id=None,
            resolution="cache_replayed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest={
                "content_digest": "sha256:" + "7" * 64,
                "size": 128,
            },
            outputs=(),
            artifacts=(),
        )
    )
    ledger.request_cancellation(None)
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.UnstartedNodeConclusion(
                node_id="sink",
                outcome="blocked",
                blocked_by=("source",),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_blocked_disposition_requires_every_dependency_to_be_concluded(
    tmp_path,
) -> None:
    failed = _plan_node(node_id="failed")
    pending = _plan_node(node_id="pending")
    sink = _plan_node(
        node_id="sink",
        dependencies=("failed", "pending"),
        required_input_sources=(
            (
                "input",
                (("failed", "value"), ("pending", "value")),
            ),
        ),
    )
    ledger = _admitted_ledger(tmp_path, plan_nodes=(failed, pending, sink))
    _operation_failure(ledger, node_id="failed")
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.UnstartedNodeConclusion(
                node_id="sink",
                outcome="blocked",
                blocked_by=("failed",),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_outer_cancellation_does_not_rewrite_successful_engine_terminal(
    tmp_path,
) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    recorder = run_execution_v2._OperationInvocationRecorder(
        ledger=ledger,
        operation_attempt_id="operation-1",
        default_engine_identity="sha256:" + "6" * 64,
    )

    with pytest.raises(run_execution_v2.ExecutionTermination):
        with recorder.invoke(
            engine_role="primary",
            parent_invocation_id=None,
            invocation_provenance=None,
        ):
            ledger.request_cancellation(None)

    terminal = next(
        fact
        for fact in ledger.facts
        if fact["fact_type"] == "engine_invocation_terminal"
    )
    assert terminal["payload"]["status"] == "succeeded"


def test_outer_cancellation_does_not_rewrite_failed_engine_terminal(
    tmp_path,
) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    recorder = run_execution_v2._OperationInvocationRecorder(
        ledger=ledger,
        operation_attempt_id="operation-1",
        default_engine_identity="sha256:" + "6" * 64,
    )

    with pytest.raises(RuntimeError, match="engine failed"):
        with recorder.invoke(
            engine_role="primary",
            parent_invocation_id=None,
            invocation_provenance=None,
        ):
            ledger.request_cancellation(None)
            raise RuntimeError("engine failed")

    terminal = next(
        fact
        for fact in ledger.facts
        if fact["fact_type"] == "engine_invocation_terminal"
    )
    assert terminal["payload"]["status"] == "failed"


def test_node_success_is_one_ledger_assembled_publication_transaction(
    tmp_path,
) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )

    acknowledgement = ledger.record(
        run_execution_v2.NodeSuccessPublication(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            resolution="executed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest={
                "content_digest": "sha256:" + "7" * 64,
                "size": 128,
            },
            outputs=(),
            artifacts=(),
        )
    )

    transaction_path = sorted(
        (
            tmp_path
            / "projects"
            / "project-1"
            / "runs"
            / "run-1"
            / "ledger"
        ).glob("*.json")
    )[-1]
    transaction = json.loads(transaction_path.read_bytes())
    assert acknowledgement.first_sequence == 7
    assert acknowledgement.last_sequence == 10
    assert [fact["fact_type"] for fact in transaction["facts"]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]


def test_selection_and_run_closure_are_one_ledger_assembled_transaction(
    tmp_path,
) -> None:
    ledger = _admitted_ledger(tmp_path, selection_required=True)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.NodeSuccessPublication(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
            operation_attempt_id=None,
            resolution="cache_replayed",
            result_identity="sha256:" + "6" * 64,
            node_result_manifest={
                "content_digest": "sha256:" + "7" * 64,
                "size": 128,
            },
            outputs=(),
            artifacts=(),
        )
    )

    acknowledgement = ledger.record(
        run_execution_v2.RunClosure(
            (
            run_execution_v2.SelectionSuccess(
                result={
                    "status": "succeeded",
                    "selection_node_id": "node-1",
                    "candidate_input": {
                        "node_id": "source",
                        "output_port": "candidates",
                    },
                    "selected_collection_id": "selected-1",
                    "selected_candidate_ids": [],
                }
            ),
            )
        )
    )

    transaction_path = sorted(
        (
            tmp_path
            / "projects"
            / "project-1"
            / "runs"
            / "run-1"
            / "ledger"
        ).glob("*.json")
    )[-1]
    transaction = json.loads(transaction_path.read_bytes())
    assert acknowledgement.last_sequence - acknowledgement.first_sequence == 1
    assert [fact["fact_type"] for fact in transaction["facts"]] == [
        "selection_terminal",
        "run_terminal",
    ]
    assert transaction["facts"][-1]["payload"] == {"status": "succeeded"}


def test_acknowledgement_failure_does_not_install_node_publication(
    tmp_path,
) -> None:
    class ControlledStore:
        def __init__(self) -> None:
            self.fail = False
            self.filesystem = run_execution_v2.FilesystemLedgerTransactionStore()

        def publish(self, **kwargs: Any) -> None:
            if self.fail:
                raise OSError("controlled acknowledgement failure")
            self.filesystem.publish(**kwargs)

    store = ControlledStore()
    plan_node = _plan_node()
    resolved_contracts, resolved_contract_roots, contract_lock_digest = (
        _plan_contract_scope((plan_node,))
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        store,
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=resolved_contract_roots,
    )
    workflow_commit_id = "workflow-commit-" + "0" * 64
    ledger.record(
        run_execution_v2.RunScopeBinding(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
            workflow_digest="sha256:" + "2" * 64,
            contract_lock_digest=contract_lock_digest,
            execution_plan_digest="sha256:" + "4" * 64,
            catalog_contract_digest="sha256:" + "5" * 64,
            resolved_contracts=resolved_contracts,
            resolved_contract_roots=resolved_contract_roots,
        )
    )
    ledger.record(
        run_execution_v2.AvailabilityBinding(
            binding=_binding_reference(),
            catalog_observed_at="2026-08-21T00:00:00+00:00",
            available=True,
        )
    )
    ledger.record(
        run_execution_v2.RunAdmission(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
        )
    )
    ledger.record(
        run_execution_v2.RunStart(
            started_at="2026-08-21T00:00:01+00:00"
        )
    )
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    before = ledger.facts
    store.fail = True

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.NodeSuccessPublication(
                node_id="node-1",
                node_attempt_id="node-attempt-1",
                operation_attempt_id=None,
                resolution="cache_replayed",
                result_identity="sha256:" + "6" * 64,
                node_result_manifest={
                    "content_digest": "sha256:" + "7" * 64,
                    "size": 128,
                },
                outputs=(),
                artifacts=(),
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == before
    assert not any(
        fact["fact_type"] in {"outputs_published", "node_disposition"}
        for fact in ledger.facts
    )


def test_filesystem_acknowledgement_syncs_transaction_and_directory(
    tmp_path,
    monkeypatch,
) -> None:
    synchronized_modes: list[int] = []
    real_fsync = os.fsync

    def capture_fsync(file_descriptor: int) -> None:
        synchronized_modes.append(os.fstat(file_descriptor).st_mode)
        real_fsync(file_descriptor)

    monkeypatch.setattr(storage.os, "fsync", capture_fsync)

    _admitted_ledger(tmp_path)

    assert any(stat.S_ISREG(mode) for mode in synchronized_modes)
    assert any(stat.S_ISDIR(mode) for mode in synchronized_modes)


def test_ledger_redacts_failure_text_before_durable_publication(tmp_path) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    secret = "sk-never-persist-this-token"

    ledger.record(
        run_execution_v2.NodeFailurePublication(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            resolution="executed",
            failure_origin="operation",
            error={
                "code": "node_execution_failed",
                "message": f"Provider returned bearer {secret}",
                "retryable": False,
                "correlation_id": "incident-redaction",
                "details": {"exception_type": "RuntimeError"},
            },
        )
    )

    retained = json.dumps(ledger.facts)
    assert secret not in retained
    assert "[REDACTED]" in retained


def test_cursor_replay_is_scope_bound_and_exclusive(tmp_path) -> None:
    ledger = _admitted_ledger(tmp_path)
    cursor = ledger.cursor_at(3)

    (
        after_sequence,
        resumed_cursor,
        through_sequence,
        through_cursor,
        events,
        terminal,
    ) = ledger.replay_window(cursor)

    assert after_sequence == 3
    assert resumed_cursor == cursor
    assert through_sequence == 4
    assert through_cursor == ledger.cursor
    assert [event["sequence"] for event in events] == [4]
    assert events[0]["event"]["type"] == "run_started"
    assert terminal is False


def test_restart_rebuilds_projection_and_only_interrupts_the_run(tmp_path) -> None:
    ledger = _admitted_ledger(tmp_path)
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    ledger.record(
        run_execution_v2.OperationAttemptStart(
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
        )
    )
    ledger.record(
        run_execution_v2.EngineInvocationStart(
            invocation_id="invocation-1",
            operation_attempt_id="operation-1",
            engine_role="primary",
            engine_identity="sha256:" + "6" * 64,
        )
    )
    manifest_path = (
        tmp_path
        / "projects"
        / "project-1"
        / "runs"
        / "run-1"
        / "manifest.json"
    )
    manifest_path.write_text("not a projection")

    reloaded = run_execution_v2._read_run_evidence_ledger(
        ledger._projects,
        "project-1",
        "run-1",
    )
    assert reloaded is not None
    reloaded.reconcile_restart()
    reloaded.rebuild_projections()

    terminal_facts = [
        fact
        for fact in reloaded.facts
        if fact["fact_type"].endswith("_terminal")
    ]
    assert [fact["fact_type"] for fact in terminal_facts] == ["run_terminal"]
    assert terminal_facts[0]["payload"] == {"status": "interrupted"}
    assert json.loads(manifest_path.read_bytes())["status"] == "interrupted"


def test_restart_interrupts_an_admitted_run_that_never_started(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    plan_node = _plan_node()
    resolved_contracts, resolved_contract_roots, contract_lock_digest = (
        _plan_contract_scope((plan_node,))
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        projects,
        "project-1",
        "run-1",
        (plan_node,),
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=resolved_contract_roots,
    )
    workflow_commit_id = "workflow-commit-" + "0" * 64
    ledger.record(
        run_execution_v2.RunScopeBinding(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
            workflow_digest="sha256:" + "2" * 64,
            contract_lock_digest=contract_lock_digest,
            execution_plan_digest="sha256:" + "4" * 64,
            catalog_contract_digest="sha256:" + "5" * 64,
            resolved_contracts=resolved_contracts,
            resolved_contract_roots=resolved_contract_roots,
        )
    )
    ledger.record(
        run_execution_v2.AvailabilityBinding(
            binding=_binding_reference(),
            catalog_observed_at="2026-08-21T00:00:00+00:00",
            available=True,
        )
    )
    ledger.record(
        run_execution_v2.RunAdmission(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
        )
    )

    reloaded = run_execution_v2._read_run_evidence_ledger(
        projects,
        "project-1",
        "run-1",
    )
    assert reloaded is not None
    reloaded.reconcile_restart()

    assert [fact["fact_type"] for fact in reloaded.facts] == [
        "run_scope_bound",
        "availability_bound",
        "run_admitted",
        "run_terminal",
    ]
    assert reloaded.facts[-1]["payload"] == {"status": "interrupted"}
    assert reloaded.projection()["status"] == "interrupted"


def test_ledger_rejects_a_transition_beyond_its_durable_size_bound(
    tmp_path,
    monkeypatch,
) -> None:
    plan_node = _plan_node()
    resolved_contracts, resolved_contract_roots, contract_lock_digest = (
        _plan_contract_scope((plan_node,))
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        expected_resolved_contracts=resolved_contracts,
        expected_contract_roots=resolved_contract_roots,
    )
    monkeypatch.setattr(run_execution_v2, "MAX_LEDGER_TRANSACTION_BYTES", 128)

    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.RunScopeBinding(
                workflow_commit_id="workflow-commit-" + "0" * 64,
                workflow_commit_revision=1,
                workflow_digest="sha256:" + "2" * 64,
                contract_lock_digest=contract_lock_digest,
                execution_plan_digest="sha256:" + "4" * 64,
                catalog_contract_digest="sha256:" + "5" * 64,
                resolved_contracts=resolved_contracts,
                resolved_contract_roots=resolved_contract_roots,
            )
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.facts == ()
    assert not list((tmp_path / "projects").rglob("ledger/*.json"))
