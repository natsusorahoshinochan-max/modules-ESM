"""Closed Node Attempt finalization contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core import ProjectManager, ResultReplaySource
import core.run_execution_v2 as run_execution_v2
from core.value_admission import AdmittedPortValues, AdmittedValue


def _open_attempt_ledger(
    tmp_path,
    *,
    operation_started: bool,
    transaction_store: run_execution_v2.LedgerTransactionStore | None = None,
) -> run_execution_v2._RunEvidenceLedger:
    workflow_commit_id = "workflow-commit-" + "0" * 64
    plan_node = run_execution_v2._PlanNodeEvidence(
        node_id="node-1",
        dependencies=(),
        required_dependencies=(),
        result_identity_plan_facts_digest="sha256:" + "1" * 64,
    )
    ledger = run_execution_v2._RunEvidenceLedger(
        ProjectManager(tmp_path / "projects"),
        "project-1",
        "run-1",
        (plan_node,),
        transaction_store,
    )
    ledger.append(
        "run_scope_bound",
        {
            "project_id": "project-1",
            "run_id": "run-1",
            "workflow_commit_id": workflow_commit_id,
            "workflow_commit_revision": 1,
            "workflow_digest": "sha256:" + "2" * 64,
            "contract_lock_digest": "sha256:" + "3" * 64,
            "execution_plan_digest": "sha256:" + "4" * 64,
            "catalog_contract_digest": "sha256:" + "5" * 64,
            "resolved_contracts": [],
            "selection_required": False,
            "selection_terminal_keys": [],
            "plan_nodes": [plan_node.to_dict()],
        },
    )
    ledger.append(
        "run_admitted",
        {
            "workflow_commit_id": workflow_commit_id,
            "workflow_commit_revision": 1,
        },
    )
    ledger.append("run_started", {"started_at": "2026-08-14T00:00:00Z"})
    ledger.append(
        "node_attempt_started",
        {"node_id": "node-1", "node_attempt_id": "node-attempt-1"},
    )
    if operation_started:
        ledger.append(
            "operation_attempt_started",
            {
                "operation_attempt_id": "operation-1",
                "node_attempt_id": "node-attempt-1",
            },
        )
    return ledger


def _finalizer(
    ledger: run_execution_v2._RunEvidenceLedger,
    *,
    result_replay_source: ResultReplaySource | None = None,
    materialize_artifacts: run_execution_v2._ArtifactMaterializer | None = None,
    object_store: run_execution_v2.ProjectObjectStore | None = None,
) -> run_execution_v2.NodeAttemptFinalizer:
    if materialize_artifacts is None:
        def default_materializer(**kwargs):
            return list(kwargs["admitted_output_descriptors"]), [], {}

        materialize_artifacts = default_materializer

    return run_execution_v2.NodeAttemptFinalizer(
        ledger=ledger,
        result_replay_source=result_replay_source or ResultReplaySource(),
        materialize_artifacts=materialize_artifacts,
        object_store=(
            object_store
            or run_execution_v2.ProjectObjectStore(ledger._projects)
        ),
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
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
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
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    transaction_paths = _ledger_transaction_paths(tmp_path)
    transaction = json.loads(transaction_paths[-1].read_bytes())
    assert transaction["schema_namespace"] == (
        "protein-workbench-run-ledger-transaction/v4"
    )
    assert transaction["schema_version"] == "4.0.0"
    assert transaction["transaction_sequence"] == len(transaction_paths)
    assert transaction["first_fact_sequence"] == 6
    assert transaction["last_fact_sequence"] == 9
    assert [fact["fact_type"] for fact in transaction["facts"]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]


@pytest.mark.parametrize(
    "cleanup_error",
    (None, RuntimeError("fixture cancellation cleanup failure")),
    ids=("ordinary", "cancel-cleanup-failure"),
)
def test_typed_object_failure_cleans_already_materialized_artifact(
    tmp_path,
    cleanup_error: RuntimeError | None,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    cancellation_control = None
    if cleanup_error is not None:
        ledger.request_cancellation(None)
        cancellation_control = SimpleNamespace(
            wait_for_cleanup=lambda: None,
            cleanup_error=cleanup_error,
        )
    artifact_path = tmp_path / "outputs" / "run-1" / "published" / "artifact"

    def materialize(**kwargs):
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_bytes(b"artifact")
        artifact_path.chmod(0o600)
        artifact = {
            "artifact_reference": "artifact",
            "artifact_kind": "standalone",
            "node_id": "node-1",
            "output_port": "artifact",
            "media_type": "text/plain",
            "size": 8,
            "content_digest": "sha256:" + "9" * 64,
        }
        return (
            list(kwargs["admitted_output_descriptors"]),
            [artifact],
            {"artifact": (artifact, ("published", "artifact"))},
        )

    class FailingObjectStore:
        def put_exact(self, project_id: str, payload: bytes) -> object:
            del project_id, payload
            raise run_execution_v2.ObjectIntegrityError(
                "sha256:" + "8" * 64
            )

    reference = {
        "contract_kind": "port_type",
        "contract_id": "contract_test.text",
        "contract_version": "1.0.0",
        "contract_digest": "sha256:" + "7" * 64,
    }
    admitted = AdmittedPortValues(
        port_type=reference,
        multiplicity="one",
        values=(
            AdmittedValue(
                canonical_bytes=b'{"value":"exact"}',
                content_digest="sha256:" + "6" * 64,
                runtime_value="exact",
            ),
        ),
        content_digest="sha256:" + "6" * 64,
    )
    finalized = _finalizer(
        ledger,
        materialize_artifacts=materialize,
        object_store=FailingObjectStore(),
    ).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=SimpleNamespace(node_id="node-1"),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=cancellation_control,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "5" * 64,
            admitted_output_descriptors=(
                {
                    "node_id": "node-1",
                    "output_port": "text",
                    "port_type": reference,
                    "content_digest": admitted.content_digest,
                },
            ),
            admitted_outputs={("node-1", "text"): admitted},
            cache_eligible=False,
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    assert finalized.disposition == "failed"
    assert ledger.projection()["node_dispositions"][0]["outcome"] == "failed"
    assert not artifact_path.exists()


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

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(ledger).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=SimpleNamespace(node_id="node-1"),
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
                current_artifact_count=0,
                current_artifact_bytes=0,
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    assert ledger.facts == before
    assert ledger.projection()["outputs"] == []
    assert ledger.projection()["node_dispositions"] == []
    transaction_paths = _ledger_transaction_paths(tmp_path)
    assert len(transaction_paths) == 5


def test_unacknowledged_commit_is_hidden_until_restart_reads_durable_file(
    tmp_path,
) -> None:
    class PublishThenLoseAcknowledgement:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )
            transaction = json.loads(payload)
            if any(
                fact["fact_type"] == "outputs_published"
                for fact in transaction["facts"]
            ):
                raise OSError("fixture acknowledgement failure")

    projects = ProjectManager(tmp_path / "projects")
    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=PublishThenLoseAcknowledgement(),
    )
    before = ledger.facts

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(ledger).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=SimpleNamespace(node_id="node-1"),
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
                current_artifact_count=0,
                current_artifact_bytes=0,
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    assert ledger.facts == before
    restarted = run_execution_v2._read_run_evidence_ledger(
        projects,
        "project-1",
        "run-1",
    )
    assert restarted is not None
    assert [fact["fact_type"] for fact in restarted.facts[-4:]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]
    assert restarted.projection()["node_dispositions"][0]["outcome"] == (
        "succeeded"
    )


def test_acknowledged_commit_reloads_after_reducer_advance_failure(
    tmp_path,
    monkeypatch,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    install_state = ledger._install_reducer_state
    failed = False

    def fail_first_conclusion_advance(state) -> None:
        nonlocal failed
        if not failed and any(
            fact["fact_type"] == "node_disposition"
            for fact in state.facts
        ):
            failed = True
            raise RuntimeError("fixture reducer advance failure")
        install_state(state)

    monkeypatch.setattr(
        ledger,
        "_install_reducer_state",
        fail_first_conclusion_advance,
    )

    finalized = _finalizer(ledger).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    assert finalized.disposition == "succeeded"
    assert [fact["fact_type"] for fact in ledger.facts[-4:]] == [
        "operation_attempt_terminal",
        "outputs_published",
        "node_attempt_terminal",
        "node_disposition",
    ]
    assert ledger.projection()["node_dispositions"][0]["outcome"] == (
        "succeeded"
    )
    assert len(_ledger_transaction_paths(tmp_path)) == 6


def test_reducer_advance_and_reload_failure_reports_evidence_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    class PublishUnreadableConclusion:
        def __init__(self) -> None:
            self.filesystem = (
                run_execution_v2.FilesystemLedgerTransactionStore()
            )

        def publish(self, *, root, relative_parts, payload) -> None:
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )
            if any(
                fact["fact_type"] == "node_disposition"
                for fact in json.loads(payload)["facts"]
            ):
                root.joinpath(*relative_parts).chmod(0o000)

    ledger = _open_attempt_ledger(
        tmp_path,
        operation_started=True,
        transaction_store=PublishUnreadableConclusion(),
    )
    install_state = ledger._install_reducer_state
    failed = False

    def fail_first_conclusion_advance(state) -> None:
        nonlocal failed
        if not failed and any(
            fact["fact_type"] == "node_disposition"
            for fact in state.facts
        ):
            failed = True
            raise RuntimeError("fixture reducer advance failure")
        install_state(state)

    monkeypatch.setattr(
        ledger,
        "_install_reducer_state",
        fail_first_conclusion_advance,
    )

    with pytest.raises(run_execution_v2.V2RunError) as rejected:
        _finalizer(ledger).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=SimpleNamespace(node_id="node-1"),
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
                current_artifact_count=0,
                current_artifact_bytes=0,
            )
        )

    assert rejected.value.code == "evidence_unavailable"
    assert ledger.projection()["node_dispositions"] == []


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
                    after_sequence=5
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
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    assert store.observed_fact_types is not None
    assert "operation_attempt_terminal" not in store.observed_fact_types
    assert store.observed_events == ()
    events = ledger.public_events(after_sequence=5)
    assert [(event["sequence"], event["event"]["type"]) for event in events] == [
        (6, "operation_attempt_terminal"),
        (8, "node_attempt_terminal"),
        (9, "node_disposition"),
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
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )
    ledger_dir = _ledger_transaction_paths(tmp_path)[0].parent
    conclusion_path = ledger_dir / "00000000000000000006.json"
    conclusion = json.loads(conclusion_path.read_bytes())
    tail = {**conclusion, "transaction_sequence": 7}
    tail["facts"] = conclusion["facts"][1:]
    tail["first_fact_sequence"] = tail["facts"][0]["sequence"]
    conclusion["facts"] = conclusion["facts"][:1]
    conclusion["last_fact_sequence"] = conclusion["facts"][-1]["sequence"]
    conclusion_path.write_bytes(
        run_execution_v2.canonical_json_bytes(conclusion)
    )
    tail_path = ledger_dir / "00000000000000000007.json"
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


def test_cache_validation_storage_failure_closes_the_executed_node(
    tmp_path,
) -> None:
    class UnreadableCache(ResultReplaySource):
        def validate_publish(self, **_kwargs) -> None:
            raise OSError("fixture cache storage failure")

    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    finalized = _finalizer(
        ledger,
        result_replay_source=UnreadableCache(),
    ).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=SimpleNamespace(node_id="node-1"),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "8" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=True,
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    assert finalized.disposition == "failed"
    assert ledger.projection()["node_dispositions"][0]["outcome"] == "failed"
    assert ledger.projection()["outputs"] == []


def test_committed_cancellation_wins_over_cache_validation_conflict(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)

    class CancelThenConflict(ResultReplaySource):
        def validate_publish(self, **_kwargs) -> None:
            decision = ledger.request_cancellation(None)
            assert decision["outcome"] == "cancellation_requested"
            raise run_execution_v2.V2RunError(
                "cache_identity_conflict",
                "Fixture conflict after committed cancellation",
                details={"result_identity": "sha256:" + "a" * 64},
            )

    finalized = _finalizer(
        ledger,
        result_replay_source=CancelThenConflict(),
    ).finalize(
        run_execution_v2.ExecutedNodeSuccess(
            project_id="project-1",
            run_id="run-1",
            execution_plan=SimpleNamespace(),
            node=SimpleNamespace(node_id="node-1"),
            resources=SimpleNamespace(
                run_id="run-1",
                _output_root=tmp_path / "outputs",
                _cancellation_control=None,
            ),
            node_attempt_id="node-attempt-1",
            operation_attempt_id="operation-1",
            result_identity="sha256:" + "a" * 64,
            admitted_output_descriptors=(),
            admitted_outputs={},
            cache_eligible=True,
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    assert finalized.disposition == "cancelled"
    assert ledger.projection()["node_dispositions"] == [
        {
            "node_id": "node-1",
            "outcome": "cancelled",
            "blocked_by": [],
            "terminal_sequence": ledger.projection()["node_dispositions"][0][
                "terminal_sequence"
            ],
        }
    ]
    assert ledger.projection()["outputs"] == []
    assert [fact["payload"]["status"] for fact in ledger.facts[-3:-1]] == [
        "cancelled",
        "cancelled",
    ]


def test_cache_publish_storage_failure_remains_fail_fast(tmp_path) -> None:
    class UnreadableOnPublish(ResultReplaySource):
        def publish(self, **_kwargs):
            raise OSError("fixture cache publish storage failure")

    ledger = _open_attempt_ledger(tmp_path, operation_started=True)
    with pytest.raises(OSError, match="cache publish storage failure"):
        _finalizer(
            ledger,
            result_replay_source=UnreadableOnPublish(),
        ).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=SimpleNamespace(node_id="node-1"),
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
                current_artifact_count=0,
                current_artifact_bytes=0,
            )
        )

    assert not any(
        fact["fact_type"].endswith("_terminal")
        or fact["fact_type"] == "node_disposition"
        for fact in ledger.facts
    )


def test_local_finalization_invariant_failure_is_not_coerced(tmp_path) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=True)

    def invalid_materializer(**_kwargs):
        raise TypeError("fixture local invariant")

    with pytest.raises(TypeError, match="fixture local invariant"):
        _finalizer(
            ledger,
            materialize_artifacts=invalid_materializer,
        ).finalize(
            run_execution_v2.ExecutedNodeSuccess(
                project_id="project-1",
                run_id="run-1",
                execution_plan=SimpleNamespace(),
                node=SimpleNamespace(node_id="node-1"),
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
                current_artifact_count=0,
                current_artifact_bytes=0,
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
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
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
            node=SimpleNamespace(node_id="node-1"),
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
            current_artifact_count=0,
            current_artifact_bytes=0,
        )
    )

    assert finalized.disposition == "failed"
    node_terminal = next(
        fact for fact in ledger.facts
        if fact["fact_type"] == "node_attempt_terminal"
    )
    assert node_terminal["payload"]["status"] == "failed"
    assert node_terminal["payload"]["resolution"] == "cache_replayed"
    assert not any(
        fact["fact_type"].startswith("operation_attempt")
        or fact["fact_type"] == "outputs_published"
        for fact in ledger.facts
    )


def test_ledger_rejects_publication_outside_a_node_conclusion_transaction(
    tmp_path,
) -> None:
    ledger = _open_attempt_ledger(tmp_path, operation_started=False)
    with pytest.raises(run_execution_v2.V2RunError) as captured:
        ledger.append(
            "outputs_published",
            {"node_id": "node-1", "outputs": [], "artifacts": []},
        )

    assert captured.value.code == "evidence_unavailable"
    assert ledger.projection()["outputs"] == []


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
