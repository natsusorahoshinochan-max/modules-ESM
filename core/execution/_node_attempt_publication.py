"""Ledger-owned terminal publication for Node Execution Attempt."""

from __future__ import annotations

import logging
from typing import Literal, cast

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
    NodeFailurePublication,
    NodeDisposition,
    NodeSuccessPublication,
    NodeTerminationPublication,
    StructuredError,
)
from core.execution.output_admission.admission import AdmittedNodeOutput
from core.execution.results.store import (
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
        failure_origin: Literal[
            "attempt",
            "binding",
            "operation",
            "publication",
        ],
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
        failure_origin: Literal[
            "attempt",
            "binding",
            "operation",
            "publication",
        ],
    ) -> AttemptOutcome:
        return cast(
            AttemptOutcome,
            self._record_failure(
                state,
                public_error=public_error,
                failure_origin=failure_origin,
            ),
        )

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
            NodeDisposition(
                node_id=node_id,
                outcome=outcome,
                blocked_by=(),
            )
        )
        return AttemptOutcome(disposition=outcome)

    def _record_success(
        self,
        state: _NodeExecutionAttemptState,
        *,
        admitted_output: AdmittedNodeOutput,
        stored_result: StoredNodeResult,
    ) -> AttemptOutcome | None:
        transition = NodeSuccessPublication(
            node_id=state.node.node_id,
            node_attempt_id=state.node_attempt_id,
            operation_attempt_id=(
                state.operation_attempt_id
                if state.operation_started
                else None
            ),
            resolution=state.resolution,
            result_identity=admitted_output.result_identity,
            node_result_manifest=ImmutableObjectReference(
                content_digest=(
                    stored_result.node_result_manifest.content_digest
                ),
                size=stored_result.node_result_manifest.size,
            ),
            outputs=stored_result.outputs,
            artifacts=stored_result.artifacts,
        )
        acknowledged = self._ledger.record_if_active(transition)
        if acknowledged is None:
            return None
        return AttemptOutcome(
            disposition="succeeded",
            admitted_outputs=admitted_output.runtime_ports,
        )

    def _record_committed_cancellation(
        self,
        state: _NodeExecutionAttemptState,
    ) -> AttemptOutcome:
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
            return self.commit_failure(
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
        *,
        admitted_output: AdmittedNodeOutput,
        stored_result: StoredNodeResult | None = None,
    ) -> AttemptOutcome:
        try:
            if stored_result is None:
                stored_result = self._result_store.store(
                    project_id=state.project_id,
                    materialization_run_id=state.run_id,
                    admitted_output=admitted_output,
                    result_contract_metadata=result_contract_metadata(
                        state.node
                    ),
                )
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
            return self._record_committed_cancellation(state)

        recorded = self._record_success(
            state,
            admitted_output=admitted_output,
            stored_result=stored_result,
        )
        if recorded is None:
            return self._record_committed_cancellation(state)
        if state.resolution == "executed" and state.cache_eligible:
            try:
                self._result_store.index_committed_result(stored_result)
            except OSError:
                _LOGGER.warning(
                    "Committed Result replay index publication is unavailable"
                )
        return recorded
