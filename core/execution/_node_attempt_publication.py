"""Ledger-owned terminal publication for Node Execution Attempt."""

from __future__ import annotations

import logging
from typing import Literal

from core.execution._node_attempt_errors import (
    _execution_error,
    _publication_error,
)
from core.execution._node_attempt_identity import result_contract_metadata
from core.execution._node_attempt_models import (
    AttemptOutcome,
    _NodeExecutionAttemptState,
)
from core.execution.ledger import (
    ImmutableObjectReference,
    Ledger,
    LedgerAcknowledgement,
    NodeFailurePublication,
    NodeSuccessPublication,
    NodeTerminationPublication,
    PublishedArtifact,
    PublishedOutput,
    StructuredError,
    UnstartedNodeConclusion,
)
from core.execution.results import (
    ResultStore,
    ResultStoreWriteError,
    StoredNodeResult,
)


_LOGGER = logging.getLogger(__name__)


class _AttemptPublication:
    """Publish one closed Attempt outcome without owning scheduling."""

    def __init__(self, *, ledger: Ledger, result_store: ResultStore) -> None:
        self._ledger = ledger
        self._result_store = result_store

    @staticmethod
    def _disposition_for_status(
        status: Literal[
            "failed",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        ],
    ) -> Literal["failed", "cancelled", "interrupted"]:
        return "interrupted" if status == "outcome_unknown" else status

    def _record_failure(
        self,
        state: _NodeExecutionAttemptState,
        *,
        public_error: StructuredError,
        failure_origin: Literal["binding", "operation", "publication"],
        only_if_active: bool = False,
    ) -> AttemptOutcome | None:
        transition = NodeFailurePublication(
            node_id=state.node.node_id,
            node_attempt_id=state.node_attempt_id,
            operation_attempt_id=(
                state.operation_attempt_id
                if state.operation_started
                else None
            ),
            resolution=state.resolution,
            error=public_error,
            failure_origin=failure_origin,
        )
        acknowledged = (
            self._ledger.record_if_active(transition)
            if only_if_active
            else self._ledger.record(transition)
        )
        if acknowledged is None:
            return None
        return AttemptOutcome(disposition="failed")

    def commit_failure(
        self,
        state: _NodeExecutionAttemptState,
        *,
        public_error: StructuredError,
        failure_origin: Literal["binding", "operation", "publication"],
    ) -> AttemptOutcome:
        committed = self._record_failure(
            state,
            public_error=public_error,
            failure_origin=failure_origin,
        )
        if committed is None:
            raise RuntimeError("Required Node failure was not acknowledged")
        return committed

    def _record_termination(
        self,
        state: _NodeExecutionAttemptState,
        *,
        status: Literal["cancelled", "interrupted", "outcome_unknown"],
        public_error: StructuredError | None,
        operation_status: Literal[
            "succeeded",
            "cancelled",
            "interrupted",
            "outcome_unknown",
        ]
        | None = None,
    ) -> AttemptOutcome:
        self._ledger.record(
            NodeTerminationPublication(
                node_id=state.node.node_id,
                status=status,
                node_attempt_id=state.node_attempt_id,
                operation_attempt_id=(
                    state.operation_attempt_id
                    if state.operation_started
                    else None
                ),
                operation_status=(
                    operation_status
                    if operation_status is not None
                    else status
                    if state.operation_started
                    else None
                ),
                resolution=state.resolution,
                error=public_error,
            )
        )
        return AttemptOutcome(
            disposition=self._disposition_for_status(status)
        )

    def commit_termination(
        self,
        state: _NodeExecutionAttemptState,
        *,
        status: Literal["cancelled", "interrupted", "outcome_unknown"],
        public_error: StructuredError | None,
    ) -> AttemptOutcome:
        return self._record_termination(
            state,
            status=status,
            public_error=public_error,
        )

    def commit_unstarted(
        self,
        *,
        node_id: str,
        outcome: Literal["cancelled", "interrupted"],
    ) -> AttemptOutcome:
        self._ledger.record(
            UnstartedNodeConclusion(
                node_id=node_id,
                outcome=outcome,
            )
        )
        return AttemptOutcome(disposition=outcome)

    def _stage_success(
        self,
        state: _NodeExecutionAttemptState,
    ) -> StoredNodeResult:
        if state.stored_result is not None:
            return state.stored_result
        if (
            state.result_identity is None
            or state.admitted_node_output is None
        ):
            raise RuntimeError(
                "Node Execution Attempt success lacks a complete admitted result"
            )
        stored = self._result_store.store(
            project_id=state.project_id,
            materialization_run_id=state.run_id,
            admitted_output=state.admitted_node_output,
            result_contract_metadata=result_contract_metadata(state.node),
        )
        state.stored_result = stored
        return stored

    def _record_success(
        self,
        state: _NodeExecutionAttemptState,
        *,
        stored_result: StoredNodeResult,
        only_if_active: bool = False,
    ) -> tuple[AttemptOutcome, LedgerAcknowledgement] | None:
        if state.result_identity is None:
            raise RuntimeError(
                "Node Execution Attempt success lacks a Result Identity"
            )
        published_outputs = tuple(
            PublishedOutput(
                node_id=output.node_id,
                output_port=output.output_port,
                port_type=output.port_type,
                content_digest=output.content_digest,
                result_identity=stored_result.result_identity,
                materialization={
                    "run_id": output.materialization_run_id,
                    "resolution": output.resolution,
                },
                producer_provenance={
                    "producer_run_id": output.producer_run_id,
                    "producer_result_identity": stored_result.result_identity,
                    "output_port": output.output_port,
                },
                value_count=output.value_count,
                value_manifest_reference=(
                    output.value_manifest.content_digest
                ),
            )
            for output in stored_result.published_outputs
        )
        published_artifacts = tuple(
            PublishedArtifact(
                artifact_reference=artifact.artifact_reference,
                artifact_kind=artifact.artifact_kind,
                node_id=artifact.node_id,
                output_port=artifact.output_port,
                media_type=artifact.media_type,
                filename=artifact.filename,
                size=artifact.body.size,
                content_digest=artifact.body.content_digest,
                candidate_id=artifact.candidate_id,
            )
            for artifact in stored_result.artifacts
        )
        transition = NodeSuccessPublication(
            node_id=state.node.node_id,
            node_attempt_id=state.node_attempt_id,
            operation_attempt_id=(
                state.operation_attempt_id
                if state.operation_started
                else None
            ),
            resolution=state.resolution,
            result_identity=state.result_identity,
            node_result_manifest=ImmutableObjectReference(
                content_digest=(
                    stored_result.node_result_manifest.content_digest
                ),
                size=stored_result.node_result_manifest.size,
            ),
            outputs=published_outputs,
            artifacts=published_artifacts,
            nonempty_output_ports=tuple(
                sorted(
                    output_port
                    for (node_id, output_port), admitted in (
                        state.admitted_outputs.items()
                    )
                    if node_id == state.node.node_id and admitted
                )
            ),
        )
        acknowledged = (
            self._ledger.record_if_active(transition)
            if only_if_active
            else self._ledger.record(transition)
        )
        if acknowledged is None:
            return None
        return (
            AttemptOutcome(
                disposition="succeeded",
                admitted_outputs=state.admitted_outputs,
                published_artifact_count=len(stored_result.artifacts),
                published_artifact_bytes=sum(
                    artifact.body.size for artifact in stored_result.artifacts
                ),
            ),
            acknowledged,
        )

    def _record_committed_cancellation(
        self,
        state: _NodeExecutionAttemptState,
    ) -> AttemptOutcome | None:
        if not self._ledger.cancellation_requested:
            return None
        if state.resources is None:
            raise RuntimeError(
                "Started Node Execution Attempt lacks owned Run resources"
            )
        state.cancellation.wait_for_cleanup()
        if state.cancellation.cleanup_error is not None:
            if not state.operation_started:
                return self._record_termination(
                    state,
                    status="interrupted",
                    public_error=_execution_error(
                        state.cancellation.cleanup_error
                    ),
                )
            return self._record_failure(
                state,
                public_error=_execution_error(
                    state.cancellation.cleanup_error
                ),
                failure_origin="publication",
            )
        return self._record_termination(
            state,
            status="cancelled",
            public_error=None,
            operation_status=(
                "succeeded" if state.operation_started else None
            ),
        )

    def commit_success(
        self,
        state: _NodeExecutionAttemptState,
    ) -> AttemptOutcome:
        try:
            stored_result = self._stage_success(state)
        except ResultStoreWriteError as error:
            failed = self._record_failure(
                state,
                public_error=_publication_error(
                    node_id=state.node.node_id,
                    stage=error.stage,
                ),
                failure_origin="publication",
                only_if_active=True,
            )
            if failed is not None:
                return failed
            cancelled = self._record_committed_cancellation(state)
            if cancelled is None:
                raise RuntimeError(
                    "Node outcome lost its cancellation ordering decision"
                )
            return cancelled

        recorded = self._record_success(
            state,
            stored_result=stored_result,
            only_if_active=True,
        )
        if recorded is None:
            cancelled = self._record_committed_cancellation(state)
            if cancelled is None:
                raise RuntimeError(
                    "Node outcome lost its cancellation ordering decision"
                )
            return cancelled
        committed, acknowledgement = recorded
        if (
            committed.disposition == "succeeded"
            and state.resolution == "executed"
            and state.cache_eligible
        ):
            try:
                self._result_store.index_committed_result(
                    stored_result,
                    acknowledgement,
                )
            except OSError:
                _LOGGER.warning(
                    "Committed Result replay index publication is unavailable"
                )
        return committed
