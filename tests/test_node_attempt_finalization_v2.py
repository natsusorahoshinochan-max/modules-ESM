"""Closed Node Attempt finalization contracts."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Literal

import pytest

from core import ProjectManager, ResultReplaySource
import core.run_execution_v2 as run_execution_v2


class _ResultIdentityPlanFacts:
    def __init__(self, marker: str) -> None:
        self._marker = marker

    def cache_contract_metadata(self) -> dict[str, object]:
        return {
            "result_identity_plan_facts": {
                "schema_namespace": self._marker,
            }
        }


def _node(
    marker: str = "fixture-result-identity-plan/v1",
) -> SimpleNamespace:
    return SimpleNamespace(
        node_id="node-1",
        result_identity_plan_facts=_ResultIdentityPlanFacts(marker),
    )


def _open_attempt_ledger(
    tmp_path,
    *,
    operation_started: bool,
    selection_required: bool = False,
    run_id: str = "run-1",
    transaction_store: run_execution_v2.LedgerTransactionStore | None = None,
    provider_readiness: Literal["passing", "failing"] | None = None,
) -> run_execution_v2._RunEvidenceLedger:
    workflow_commit_id = "workflow-commit-" + "0" * 64
    plan_node = run_execution_v2._PlanNodeEvidence(
        node_id="node-1",
        dependencies=(),
        required_input_sources=(),
        result_identity_plan_facts_digest="sha256:" + "1" * 64,
        binding={
            "contract_kind": "binding",
            "contract_id": "fixture.binding",
            "contract_version": "1.0.0",
            "contract_digest": "sha256:" + "8" * 64,
        },
        execution_route=(
            "adapter" if provider_readiness is not None else "direct"
        ),
        selection_consumer=selection_required,
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        run_id,
        (plan_node,),
        transaction_store,
        expected_resolved_contracts=(plan_node.binding,),
        expected_contract_roots=(plan_node.binding,),
    )
    ledger.record(
        run_execution_v2.RunScopeBinding(
            workflow_commit_id=workflow_commit_id,
            workflow_commit_revision=1,
            workflow_digest="sha256:" + "2" * 64,
            contract_lock_digest=run_execution_v2.canonical_sha256(
                {
                    "schema_namespace": (
                        run_execution_v2.CONTRACT_LOCK_NAMESPACE
                    ),
                    "entries": [dict(plan_node.binding)],
                }
            ),
            execution_plan_digest="sha256:" + "4" * 64,
            catalog_contract_digest="sha256:" + "5" * 64,
            resolved_contracts=(plan_node.binding,),
            resolved_contract_roots=(plan_node.binding,),
        )
    )
    ledger.record(
        run_execution_v2.AvailabilityBinding(
            binding=plan_node.binding,
            catalog_observed_at="2026-08-14T00:00:00Z",
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
        run_execution_v2.RunStart(started_at="2026-08-14T00:00:00Z")
    )
    if provider_readiness is not None:
        readiness_payload = {
            "binding": plan_node.binding,
            "readiness_contract_digest": "sha256:" + "9" * 64,
            "observed_at": "2026-08-14T00:00:01Z",
            "conclusion": provider_readiness,
            "proof_source": "direct-observation",
        }
        ledger.record(
            run_execution_v2.ReadinessAttestation(
                **readiness_payload,
                attestation_digest=run_execution_v2.canonical_sha256(
                    {
                        "schema_namespace": (
                            run_execution_v2.READINESS_ATTESTATION_NAMESPACE
                        ),
                        **readiness_payload,
                    }
                ),
            )
        )
    ledger.record(
        run_execution_v2.NodeAttemptStart(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
        )
    )
    if operation_started:
        ledger.record(
            run_execution_v2.OperationAttemptStart(
                operation_attempt_id="operation-1",
                node_attempt_id="node-attempt-1",
            )
        )
    return ledger


def _finalizer(
    ledger: run_execution_v2._RunEvidenceLedger,
    *,
    result_replay_source: ResultReplaySource | None = None,
    object_store: run_execution_v2.ProjectObjectStore | None = None,
) -> run_execution_v2.NodeAttemptFinalizer:
    resolved_object_store = (
        object_store
        or run_execution_v2.ProjectObjectStore(ledger._projects)
    )
    return run_execution_v2.NodeAttemptFinalizer(
        ledger=ledger,
        result_replay_source=result_replay_source or ResultReplaySource(),
        object_store=resolved_object_store,
    )


def _ledger_transaction_paths(tmp_path):
    return sorted(
        (
            tmp_path
            / "projects"
            / "project-1"
            / "runs"
            / "run-1"
            / "ledger"
        ).glob("*.json")
    )


def _last_transaction_fact_types(tmp_path) -> list[str]:
    transaction = json.loads(
        _ledger_transaction_paths(tmp_path)[-1].read_bytes()
    )
    return [fact["fact_type"] for fact in transaction["facts"]]


def test_executed_success_is_finalized_with_outputs_and_disposition(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    finalized = _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "6" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=False,
        )
    )

    assert finalized.disposition == "succeeded"
    assert [fact["fact_type"] for fact in ledger.facts[-4:]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]
    assert ledger.projection()["node_dispositions"][0]["resolution"] == (
        "executed"
    )


def test_executed_success_publishes_one_physical_ledger_transaction(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)

    _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "6" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=False,
        )
    )

    transaction_paths = _ledger_transaction_paths(tmp_path)
    transaction = json.loads(transaction_paths[-1].read_bytes())
    assert transaction["schema_namespace"] == (
        "protein-workbench-run-ledger-transaction/v4"
    )
    assert transaction["schema_version"] == "4.0.0"
    assert transaction["transaction_sequence"] == len(transaction_paths)
    assert transaction["first_fact_sequence"] == 7
    assert transaction["last_fact_sequence"] == 10
    assert [fact["fact_type"] for fact in transaction["facts"]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]


def test_operation_failure_is_one_exact_node_conclusion_transaction(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    public_error = {
        "code": "node_execution_failed",
        "message": "Node execution failed safely",
        "retryable": False,
        "correlation_id": "incident-operation",
        "details": {"exception_type": "PortValueError"},
    }

    finalized = _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeNonSuccess(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            status="failed",
            public_error=public_error,
            failure_origin="operation",
        )
    )

    assert finalized.disposition == "failed"
    transaction = json.loads(_ledger_transaction_paths(tmp_path)[-1].read_bytes())
    assert [fact["fact_type"] for fact in transaction["facts"]] == [
        "operation_attempt_terminal",
        "node_attempt_terminal",
        "node_disposition",
    ]
    operation_terminal, node_terminal, disposition = transaction["facts"]
    assert operation_terminal["payload"] == {
        "operation_attempt_id": "operation-1",
        "status": "failed",
        "error": public_error,
    }
    assert node_terminal["payload"] == {
        "node_attempt_id": "node-attempt-1",
        "status": "failed",
        "resolution": "executed",
        "failure_origin": "operation",
        "error": public_error,
    }
    assert disposition["payload"]["outcome"] == "failed"


def test_binding_failure_closes_node_without_an_operation_attempt(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=False,
        provider_readiness="failing",
    )
    public_error = {
        "code": "readiness_rejected",
        "message": "Selected Binding is not ready for this Run",
        "retryable": True,
        "correlation_id": "incident-binding",
        "details": {
            "binding": {
                "contract_kind": "binding",
                "contract_id": "fixture.binding",
                "contract_version": "1.0.0",
                "contract_digest": "sha256:" + "8" * 64,
            },
            "reason_code": "model_unavailable",
        },
    }

    finalized = _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeNonSuccess(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
            operation_attempt_id=None,
            status="failed",
            public_error=public_error,
            failure_origin="binding",
        )
    )

    assert finalized.disposition == "failed"
    transaction = json.loads(_ledger_transaction_paths(tmp_path)[-1].read_bytes())
    assert [fact["fact_type"] for fact in transaction["facts"]] == [
        "node_attempt_terminal",
        "node_disposition",
    ]
    node_terminal, disposition = transaction["facts"]
    assert node_terminal["payload"] == {
        "node_attempt_id": "node-attempt-1",
        "status": "failed",
        "resolution": "executed",
        "failure_origin": "binding",
        "error": public_error,
    }
    assert disposition["payload"]["outcome"] == "failed"


def test_finalizer_rejects_error_code_from_another_failure_origin(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(ledger).finalize(
            run_execution_v2.ExecutedNodeNonSuccess(
                node_id="node-1",
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
                status="failed",
                public_error={
                    "code": "node_execution_failed",
                    "message": "Node execution failed safely",
                    "retryable": False,
                    "correlation_id": "incident-mismatched-origin",
                    "details": {"exception_type": "PortValueError"},
                },
                failure_origin="publication",
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_operation_failure_requires_one_executed_child_operation(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=False)
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(ledger).finalize(
            run_execution_v2.ExecutedNodeNonSuccess(
                node_id="node-1",
                node_attempt_id="node-attempt-1",
                operation_attempt_id=None,
                status="failed",
                public_error={
                    "code": "node_execution_failed",
                    "message": "Node execution failed safely",
                    "retryable": False,
                    "correlation_id": "incident-no-operation",
                    "details": {"exception_type": "PortValueError"},
                },
                failure_origin="operation",
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    assert ledger.facts == before


def test_same_result_identity_and_manifest_publish_across_runs(
    tmp_path,
) -> None:
    ledgers = {
        run_id: _open_attempt_ledger(
            tmp_path,
            operation_started=True,
            run_id=run_id,
        )
        for run_id in ("run-a", "run-b")
    }
    object_store = run_execution_v2.ProjectObjectStore(
        ledgers["run-a"]._projects
    )
    dispositions = []
    for run_id, ledger in ledgers.items():
        finalized = _finalizer(
            ledger,
            object_store=object_store,
        ).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id=run_id,
                execution_plan=SimpleNamespace(),
                node=_node(),
                resources=SimpleNamespace(
                    run_id=run_id,
                    _output_root=tmp_path / "outputs",
                    _cancellation_control=None,
                ),
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
                result_identity="sha256:" + "d" * 64,
                admitted_output_descriptors=(),
                admitted_outputs={},
                cache_eligible=False,
            )
        )
        dispositions.append(finalized.disposition)

    assert dispositions == ["succeeded", "succeeded"]


def test_artifact_object_failure_publishes_no_artifact_or_output(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    artifact_body = b"artifact-write-failure"

    class FailingArtifactObjectStore(run_execution_v2.ProjectObjectStore):
        def put_exact(self, project_id, payload):
            if payload == artifact_body:
                raise OSError("fixture artifact object failure")
            return super().put_exact(project_id, payload)

    object_store = FailingArtifactObjectStore(ledger._projects)
    finalized = _finalizer(
        ledger,
        object_store=object_store,
    ).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "5" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=False,
            artifact_publication_plan=(
                run_execution_v2.AdmittedArtifactPublicationPlan(
                    artifact_output_ports=("structure",),
                    publications=(
                        run_execution_v2.AdmittedArtifactPublication(
                            output_port="structure",
                            artifact_kind="standalone",
                            body=artifact_body,
                            media_type="chemical/x-pdb",
                            filename="structure.pdb",
                            candidate_id=None,
                        ),
                    ),
                )
            ),
        )
    )

    assert finalized.disposition == "failed"
    assert ledger.projection()["node_dispositions"][0]["outcome"] == "failed"
    assert ledger.projection()["artifact_index"] == []
    assert ledger.projection()["outputs"] == []
    operation_terminal = next(
        fact
        for fact in ledger.facts
        if fact["fact_type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        fact
        for fact in ledger.facts
        if fact["fact_type"] == "node_attempt_terminal"
    )
    assert operation_terminal["payload"]["status"] == "succeeded"
    assert node_terminal["payload"]["failure_origin"] == "publication"
    assert node_terminal["payload"]["error"]["code"] == (
        "node_publication_failed"
    )
    assert node_terminal["payload"]["error"]["details"] == {
        "node_id": "node-1",
        "publication_stage": "artifact_object",
    }


def test_manifest_object_failure_preserves_successful_operation(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)

    class FailingManifestObjectStore(run_execution_v2.ProjectObjectStore):
        def put_exact(self, project_id, payload):
            raise OSError("fixture manifest path and canonical bytes")

    finalized = _finalizer(
        ledger,
        object_store=FailingManifestObjectStore(ledger._projects),
    ).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "5" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=False,
        )
    )

    assert finalized.disposition == "failed"
    operation_terminal = next(
        fact["payload"]
        for fact in ledger.facts
        if fact["fact_type"] == "operation_attempt_terminal"
    )
    node_terminal = next(
        fact["payload"]
        for fact in ledger.facts
        if fact["fact_type"] == "node_attempt_terminal"
    )
    assert operation_terminal == {
        "operation_attempt_id": "operation-1",
        "status": "succeeded",
    }
    assert node_terminal["failure_origin"] == "publication"
    assert node_terminal["error"]["details"] == {
        "node_id": "node-1",
        "publication_stage": "manifest",
    }
    retained = json.dumps(ledger.facts).encode()
    assert b"fixture manifest path" not in retained
    assert b"canonical bytes" not in retained
    assert ledger.projection()["outputs"] == []
    assert ledger.projection()["artifact_index"] == []


def test_failed_node_transaction_exposes_no_logical_fact_subset(
    tmp_path,
) -> None:
    class FailNodeConclusion:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            transaction = json.loads(payload)
            if any(
                fact["fact_type"] == "outputs_published"
                for fact in transaction["facts"]
            ):
                raise OSError("fixture transaction failure")
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=FailNodeConclusion(),
    )
    before = ledger.facts
    object_store = run_execution_v2.ProjectObjectStore(ledger._projects)

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(
            ledger,
            object_store=object_store,
        ).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=_node(),
                resources=SimpleNamespace(
                    run_id="run-1",
                    _output_root=tmp_path / "outputs",
                    _cancellation_control=None,
                ),
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
                result_identity="sha256:" + "6" * 64,
                admitted_output_descriptors=(),
                admitted_outputs={},
                cache_eligible=False,
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    assert ledger.facts == before
    with pytest.raises(run_execution_v2.V2RunError) as unavailable:
        ledger.projection()
    assert unavailable.value.code == "evidence_unavailable"
    transaction_paths = _ledger_transaction_paths(tmp_path)
    assert len(transaction_paths) == 6


def test_artifact_object_remains_unpublished_when_transaction_fails(
    tmp_path,
) -> None:
    class FailArtifactConclusion:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            transaction = json.loads(payload)
            if any(
                fact["fact_type"] == "artifact_published"
                for fact in transaction["facts"]
            ):
                raise OSError("fixture Artifact transaction failure")
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=FailArtifactConclusion(),
    )
    object_store = run_execution_v2.ProjectObjectStore(ledger._projects)
    artifact_body = b"exact artifact bytes"
    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(
            ledger,
            object_store=object_store,
        ).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=_node(),
                resources=SimpleNamespace(
                    run_id="run-1",
                    _cancellation_control=None,
                ),
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
                result_identity="sha256:" + "6" * 64,
                admitted_output_descriptors=(),
                admitted_outputs={},
                cache_eligible=False,
                artifact_publication_plan=(
                    run_execution_v2.AdmittedArtifactPublicationPlan(
                        artifact_output_ports=("structure",),
                        publications=(
                            run_execution_v2.AdmittedArtifactPublication(
                                output_port="structure",
                                artifact_kind="standalone",
                                body=artifact_body,
                                media_type="chemical/x-pdb",
                                filename="structure.pdb",
                                candidate_id=None,
                            ),
                        ),
                    )
                ),
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    with pytest.raises(run_execution_v2.V2RunError) as unavailable:
        ledger.projection()
    assert unavailable.value.code == "evidence_unavailable"
    assert object_store.read(
        "project-1",
        "sha256:"
        "334e3a1d10a0a00a0a6c77ce4272cff103dd46564b51cf3b36becf01571685ba",
    ) == artifact_body
    assert not list(tmp_path.rglob("published/*"))


def test_node_events_appear_only_after_the_whole_transaction_is_durable(
    tmp_path,
) -> None:
    class ObserveBeforePublication:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )
            self.ledger = None
            self.observed_fact_types = None
            self.observed_events = None

        def publish(self, *, root, relative_parts, payload) -> None:
            if _transaction_contains(payload, "node_disposition"):
                assert self.ledger is not None
                self.observed_fact_types = tuple(
                    fact["fact_type"] for fact in self.ledger.facts
                )
                self.observed_events = self.ledger.public_events(
                    after_sequence=6
                )
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    def _transaction_contains(payload: bytes, fact_type: str) -> bool:
        return any(
            fact["fact_type"] == fact_type
            for fact in json.loads(payload)["facts"]
        )

    store = ObserveBeforePublication()
    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=store,
    )
    store.ledger = ledger

    _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "6" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=False,
        )
    )

    assert store.observed_fact_types is not None
    assert "operation_attempt_terminal" not in store.observed_fact_types
    assert store.observed_events == ()
    events = ledger.public_events(after_sequence=6)
    assert [(event["sequence"], event["event"]["type"]) for event in events] == [
        (7, "operation_attempt_terminal"),
        (9, "node_attempt_terminal"),
        (10, "node_disposition"),
    ]


def test_reader_rejects_a_v4_node_conclusion_split_across_transactions(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "6" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=False,
        )
    )
    ledger_dir = _ledger_transaction_paths(tmp_path)[0].parent
    conclusion_path = ledger_dir / "00000000000000000007.json"
    conclusion = json.loads(conclusion_path.read_bytes())
    tail = {**conclusion, "transaction_sequence": 8}
    tail["facts"] = conclusion["facts"][1:]
    tail["first_fact_sequence"] = tail["facts"][0]["sequence"]
    conclusion["facts"] = conclusion["facts"][:1]
    conclusion["last_fact_sequence"] = conclusion["facts"][-1]["sequence"]
    conclusion_path.write_bytes(
        run_execution_v2.canonical_json_bytes(conclusion)
    )
    tail_path = ledger_dir / "00000000000000000008.json"
    tail_path.write_bytes(
        run_execution_v2.canonical_json_bytes(tail)
    )
    tail_path.chmod(0o600)

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        run_execution_v2._read_run_evidence_ledger(
            projects,
            "project-1",
            "run-1",
        )

    assert rejected.value.code == "evidence_unavailable"


def test_reader_ignores_private_ledger_staging_file(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    ledger_dir = _ledger_transaction_paths(tmp_path)[0].parent
    staging = ledger_dir / ".00000000000000000007.json.staging"
    staging.write_bytes(b"private incomplete transaction")
    staging.chmod(0o600)

    restarted = run_execution_v2._read_run_evidence_ledger(
        projects,
        "project-1",
        "run-1",
    )

    assert restarted is not None
    assert restarted.facts == ledger.facts


def test_reader_rejects_noncontiguous_transaction_names(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    _open_attempt_ledger(tmp_path, operation_started=True)
    ledger_dir = _ledger_transaction_paths(tmp_path)[0].parent
    sixth = ledger_dir / "00000000000000000006.json"
    sixth.rename(ledger_dir / "00000000000000000007.json")

    with pytest.raises(
        RuntimeError,
        match="transaction sequence is not contiguous",
    ):
        run_execution_v2._read_run_evidence_ledger(
            projects,
            "project-1",
            "run-1",
        )


def test_executed_non_success_is_finalized_without_outputs(tmp_path) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    finalized = _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeNonSuccess(
            node_id="node-1",
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            status="failed",
            public_error=run_execution_v2._public_failure(
                RuntimeError("fixture failure")
            ),
        )
    )

    assert finalized.disposition == "failed"
    assert ledger.projection()["outputs"] == []
    assert [fact["fact_type"] for fact in ledger.facts[-3:]] == [
        "operation_attempt_terminal",
        "node_attempt_terminal",
        "node_disposition",
    ]
    assert _last_transaction_fact_types(tmp_path) == [
        "operation_attempt_terminal",
        "node_attempt_terminal",
        "node_disposition",
    ]
    assert ledger.facts[-2]["payload"]["resolution"] == "executed"


def test_cache_publish_storage_failure_keeps_committed_node_success(
    tmp_path,
) -> None:
    class UnreadableOnPublish(ResultReplaySource):
        def publish(self, **_kwargs):
            raise OSError("fixture cache publish storage failure")

    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    finalized = _finalizer(
        ledger,
        result_replay_source=UnreadableOnPublish(),
    ).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "b" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=True,
        )
    )

    assert finalized.disposition == "succeeded"
    assert ledger.projection()["node_dispositions"][0]["outcome"] == (
        "succeeded"
    )


def test_local_finalization_invariant_failure_is_not_coerced(tmp_path) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)

    class InvalidObjectStore(run_execution_v2.ProjectObjectStore):
        def put_exact(self, project_id, payload):
            raise TypeError("fixture local invariant")

    with pytest.raises(TypeError, match="fixture local invariant"):
        _finalizer(
            ledger,
            object_store=InvalidObjectStore(ledger._projects),
        ).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=_node(),
                resources=SimpleNamespace(
                    run_id="run-1",
                    _output_root=tmp_path / "outputs",
                    _cancellation_control=None,
                ),
                node_attempt_id="node-attempt-1",
                operation_attempt_id="operation-1",
                result_identity="sha256:" + "9" * 64,
                admitted_output_descriptors=(),
                admitted_outputs={},
                cache_eligible=False,
            )
        )

    assert not any(
        fact["fact_type"].endswith("_terminal")
        or fact["fact_type"] == "node_disposition"
        for fact in ledger.facts
    )


def test_cache_replay_success_has_no_operation_attempt(tmp_path) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=False)
    finalized = _finalizer(ledger).finalize(
        run_execution_v2.CacheReplayNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            result_identity="sha256:" + "7" * 64,
            producer_run_id="producer-run",
            admitted_output_descriptors=(),
            admitted_outputs={},
        )
    )

    assert finalized.disposition == "succeeded"
    assert not any(
        fact["fact_type"].startswith("operation_attempt")
        for fact in ledger.facts
    )
    assert ledger.projection()["node_dispositions"][0]["resolution"] == (
        "cache_replayed"
    )
    assert _last_transaction_fact_types(tmp_path) == [
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]


def test_cache_replay_cancellation_cleanup_failure_retains_resolution(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=False)
    decision = ledger.request_cancellation(None)
    assert decision["outcome"] == "cancellation_requested"
    cancellation = SimpleNamespace(
        wait_for_cleanup=lambda: None,
        cleanup_error=OSError("fixture cancellation cleanup failure"),
    )

    finalized = _finalizer(ledger).finalize(
        run_execution_v2.CacheReplayNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=_node(),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=cancellation,
            ),
            node_attempt_id="node-attempt-1",
            result_identity="sha256:" + "c" * 64,
            producer_run_id="producer-run",
            admitted_output_descriptors=(),
            admitted_outputs={},
        )
    )

    assert finalized.disposition == "interrupted"
    node_terminal = next(
        fact for fact in ledger.facts
        if fact["fact_type"] == "node_attempt_terminal"
    )
    assert node_terminal["payload"]["status"] == "interrupted"
    assert node_terminal["payload"]["resolution"] == "cache_replayed"
    assert "failure_origin" not in node_terminal["payload"]
    assert not any(
        fact["fact_type"].startswith("operation_attempt")
        or fact["fact_type"] == "outputs_published"
        for fact in ledger.facts
    )


def test_ledger_rejects_publication_that_omits_the_started_operation(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.record(
            run_execution_v2.NodeSuccessPublication(
                node_id="node-1",
                node_attempt_id="node-attempt-1",
                operation_attempt_id=None,
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
    with pytest.raises(run_execution_v2.V2RunError) as unavailable:
        ledger.projection()
    assert unavailable.value.code == "evidence_unavailable"


def test_cancellation_first_blocks_publication_without_deleting_shared_objects(
    tmp_path,
) -> None:
    artifact_body = b"shared immutable Artifact bytes"
    object_persisted = threading.Event()
    release_materialization = threading.Event()

    class PauseAfterArtifactPersistence(run_execution_v2.ProjectObjectStore):
        def put_exact(self, project_id, payload):
            stored = super().put_exact(project_id, payload)
            if payload == artifact_body:
                object_persisted.set()
                assert release_materialization.wait(timeout=2)
            return stored

    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    object_store = PauseAfterArtifactPersistence(ledger._projects)
    finalized: dict[str, run_execution_v2.FinalizedNode] = {}
    failures: list[BaseException] = []

    def finalize() -> None:
        try:
            finalized["node"] = _finalizer(
                ledger,
                object_store=object_store,
            ).finalize(
                run_execution_v2.ExecutedNodeSuccess(
                    project_id="project-1",
                    run_id="run-1",
                    execution_plan=SimpleNamespace(),
                    node=_node(),
                    resources=SimpleNamespace(
                        run_id="run-1",
                        _output_root=tmp_path / "outputs",
                        _cancellation_control=None,
                    ),
                    node_attempt_id="node-attempt-1",
                    operation_attempt_id="operation-1",
                    result_identity="sha256:" + "6" * 64,
                    admitted_output_descriptors=(),
                    admitted_outputs={},
                    cache_eligible=False,
                    artifact_publication_plan=(
                        run_execution_v2.AdmittedArtifactPublicationPlan(
                            artifact_output_ports=("structure",),
                            publications=(
                                run_execution_v2.AdmittedArtifactPublication(
                                    output_port="structure",
                                    artifact_kind="standalone",
                                    body=artifact_body,
                                    media_type="chemical/x-pdb",
                                    filename="structure.pdb",
                                    candidate_id=None,
                                ),
                            ),
                        )
                    ),
                )
            )
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=finalize)
    worker.start()
    assert object_persisted.wait(timeout=2)
    decision = ledger.request_cancellation(None)
    release_materialization.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert failures == []
    assert decision["outcome"] == "cancellation_requested"
    assert finalized["node"].disposition == "cancelled"
    assert ledger.projection()["outputs"] == []
    assert ledger.projection()["artifact_index"] == []
    assert not any(
        fact["fact_type"] in {"outputs_published", "artifact_published"}
        for fact in ledger.facts
    )
    operation_terminal = next(
        fact
        for fact in ledger.facts
        if fact["fact_type"] == "operation_attempt_terminal"
    )
    assert operation_terminal["payload"] == {
        "operation_attempt_id": "operation-1",
        "status": "succeeded",
    }
    node_terminal = next(
        fact
        for fact in ledger.facts
        if fact["fact_type"] == "node_attempt_terminal"
    )
    assert node_terminal["payload"]["status"] == "cancelled"
    assert list(tmp_path.rglob("objects/v1/sha256/*/*"))


def test_success_first_keeps_success_when_cancellation_waits_on_run_ordering(
    tmp_path,
) -> None:
    success_commit_entered = threading.Event()
    release_success_commit = threading.Event()

    class PauseInsideSuccessCommit:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            transaction = json.loads(payload)
            if any(
                fact["fact_type"] == "outputs_published"
                for fact in transaction["facts"]
            ):
                success_commit_entered.set()
                assert release_success_commit.wait(timeout=2)
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )

    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=PauseInsideSuccessCommit(),
    )
    finalized: dict[str, run_execution_v2.FinalizedNode] = {}
    cancellation: dict[str, dict[str, object]] = {}
    failures: list[BaseException] = []

    def finalize() -> None:
        try:
            finalized["node"] = _finalizer(ledger).finalize(
                run_execution_v2.ExecutedNodeSuccess(
                    project_id="project-1",
                    run_id="run-1",
                    execution_plan=SimpleNamespace(),
                    node=_node(),
                    resources=SimpleNamespace(
                        run_id="run-1",
                        _output_root=tmp_path / "outputs",
                        _cancellation_control=None,
                    ),
                    node_attempt_id="node-attempt-1",
                    operation_attempt_id="operation-1",
                    result_identity="sha256:" + "6" * 64,
                    admitted_output_descriptors=(),
                    admitted_outputs={},
                    cache_eligible=False,
                )
            )
        except BaseException as error:
            failures.append(error)

    def cancel() -> None:
        try:
            cancellation["decision"] = ledger.request_cancellation(None)
        except BaseException as error:
            failures.append(error)

    finalization_worker = threading.Thread(target=finalize)
    finalization_worker.start()
    assert success_commit_entered.wait(timeout=2)
    cancellation_worker = threading.Thread(target=cancel)
    cancellation_worker.start()
    release_success_commit.set()
    finalization_worker.join(timeout=2)
    cancellation_worker.join(timeout=2)

    assert not finalization_worker.is_alive()
    assert not cancellation_worker.is_alive()
    assert failures == []
    assert finalized["node"].disposition == "succeeded"
    assert cancellation["decision"]["outcome"] == "completed_before_cancel"
    assert ledger.projection()["node_dispositions"][0]["outcome"] == (
        "succeeded"
    )
    assert not any(
        fact["fact_type"] == "cancellation_requested"
        for fact in ledger.facts
    )


@pytest.mark.parametrize("publish_final_name", (False, True))
def test_unavailable_evidence_wins_before_waiting_cancellation(
    tmp_path,
    publish_final_name: bool,
) -> None:
    conclusion_entered = threading.Event()
    release_conclusion = threading.Event()

    class PauseThenLoseConclusionAcknowledgement:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            transaction = json.loads(payload)
            is_conclusion = any(
                fact["fact_type"] == "outputs_published"
                for fact in transaction["facts"]
            )
            if not is_conclusion or publish_final_name:
                self.filesystem.publish(
                    root=root,
                    relative_parts=relative_parts,
                    payload=payload,
                )
            if is_conclusion:
                conclusion_entered.set()
                assert release_conclusion.wait(timeout=2)
                raise OSError("fixture conclusion acknowledgement failure")

    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=PauseThenLoseConclusionAcknowledgement(),
    )
    finalization_errors: list[BaseException] = []
    cancellation_errors: list[BaseException] = []
    cancellation_decisions: list[dict[str, object]] = []
    cancellation_started = threading.Event()

    def finalize() -> None:
        try:
            _finalizer(ledger).finalize(
                run_execution_v2.ExecutedNodeSuccess(
                    project_id="project-1",
                    run_id="run-1",
                    execution_plan=SimpleNamespace(),
                    node=_node(),
                    resources=SimpleNamespace(
                        run_id="run-1",
                        _output_root=tmp_path / "outputs",
                        _cancellation_control=None,
                    ),
                    node_attempt_id="node-attempt-1",
                    operation_attempt_id="operation-1",
                    result_identity="sha256:" + "6" * 64,
                    admitted_output_descriptors=(),
                    admitted_outputs={},
                    cache_eligible=False,
                )
            )
        except BaseException as error:
            finalization_errors.append(error)

    def cancel() -> None:
        cancellation_started.set()
        try:
            cancellation_decisions.append(ledger.request_cancellation(None))
        except BaseException as error:
            cancellation_errors.append(error)

    finalization_worker = threading.Thread(target=finalize)
    finalization_worker.start()
    assert conclusion_entered.wait(timeout=2)
    cancellation_worker = threading.Thread(target=cancel)
    cancellation_worker.start()
    assert cancellation_started.wait(timeout=2)
    release_conclusion.set()
    finalization_worker.join(timeout=2)
    cancellation_worker.join(timeout=2)

    assert not finalization_worker.is_alive()
    assert not cancellation_worker.is_alive()
    assert len(finalization_errors) == 1
    assert isinstance(finalization_errors[0], run_execution_v2.V2RunError)
    assert finalization_errors[0].code == "evidence_unavailable"
    assert cancellation_decisions == []
    assert len(cancellation_errors) == 1
    assert isinstance(cancellation_errors[0], run_execution_v2.V2RunError)
    assert cancellation_errors[0].code == "evidence_unavailable"
    assert not any(
        fact["fact_type"] == "cancellation_requested"
        for fact in ledger.facts
    )
    with pytest.raises(run_execution_v2.V2RunError) as unavailable:
        ledger.projection()
    assert unavailable.value.code == "evidence_unavailable"


@pytest.mark.parametrize(
    ("status", "disposition"),
    (
        ("cancelled", "cancelled"),
        ("interrupted", "interrupted"),
        ("outcome_unknown", "interrupted"),
    ),
)
def test_cancellation_and_interruption_share_the_finalization_seam(
    tmp_path,
    status: str,
    disposition: str,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    finalized = _finalizer(ledger).finalize(
        run_execution_v2.CancelledOrInterruptedNode(
            node_id="node-1",
            status=status,
            public_error=run_execution_v2._public_failure(
                RuntimeError("fixture termination")
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            resolution="executed",
        )
    )

    assert finalized.disposition == disposition
    assert ledger.projection()["node_dispositions"][0]["outcome"] == (
        disposition
    )
    assert ledger.facts[-2]["payload"]["status"] == status
