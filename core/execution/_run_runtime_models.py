"""Mutable in-process records owned by Run Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading

from core.execution.ledger import Ledger, V2RunError
from core.execution.resources import CancellationControl
from core.workflow.authoring import VerifiedWorkflowCommit


@dataclass(frozen=True, slots=True)
class _RunRecordState:
    worker_finished: bool
    execution_error: BaseException | None


@dataclass(slots=True)
class _RunRecord:
    compiled: VerifiedWorkflowCommit | None
    ledger: Ledger
    cancellation: CancellationControl = field(
        default_factory=CancellationControl,
    )
    execution_error: BaseException | None = None
    _worker_finished: bool = False
    _condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock()),
        repr=False,
    )

    def mark_worker_completed(
        self,
        error: BaseException | None = None,
    ) -> None:
        with self._condition:
            self.execution_error = error
            self._worker_finished = True
            self._condition.notify_all()
        self.ledger.wake_waiters()

    def state_snapshot(self) -> _RunRecordState:
        with self._condition:
            return _RunRecordState(
                worker_finished=self._worker_finished,
                execution_error=self.execution_error,
            )

    def require_lifecycle_evidence(self) -> None:
        """Gate a lifecycle use case on one current worker-state snapshot."""
        self.ledger.ensure_evidence_available()
        state = self.state_snapshot()
        if state.worker_finished and state.execution_error is not None:
            raise V2RunError(
                "evidence_unavailable",
                "Run worker exited before durable Run closure",
                details={
                    "last_durable_cursor": self.ledger.cursor.value,
                },
            ) from state.execution_error
