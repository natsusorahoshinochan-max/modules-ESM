"""Closed Node Attempt finalization contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import ProjectManager, ResultReplaySource
import core.run_execution_v2 as run_execution_v2


def _open_attempt_ledger(
    tmp_path,
    *,
    operation_started: bool,
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
) -> run_execution_v2.NodeAttemptFinalizer:
    if materialize_artifacts is None:
        def default_materializer(**kwargs):
            return list(kwargs["admitted_output_descriptors"]), [], {}

        materialize_artifacts = default_materializer

    return run_execution_v2.NodeAttemptFinalizer(
        ledger=ledger,
        result_replay_source=result_replay_source or ResultReplaySource(),
        materialize_artifacts=materialize_artifacts,
    )


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
        for fact in ledger.facts
    )


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
