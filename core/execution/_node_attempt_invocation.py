"""Nested engine invocation evidence for one Operation Attempt."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import uuid

from core.execution._node_attempt_errors import _execution_error
from core.execution._node_attempt_models import ExecutionTermination
from core.execution.ledger import (
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Ledger,
)
from core.operation import EngineInvocationProvenance


@dataclass(frozen=True, slots=True)
class _OperationInvocationRecorder:
    ledger: Ledger
    operation_attempt_id: str
    default_engine_identity: str

    @contextmanager
    def invoke(
        self,
        *,
        engine_role: str,
        parent_invocation_id: str | None,
        invocation_provenance: EngineInvocationProvenance | None,
    ):
        invocation_id = f"invocation-{uuid.uuid4().hex}"
        acknowledged = self.ledger.record_if_active(
            EngineInvocationStarted(
                invocation_id=invocation_id,
                operation_attempt_id=self.operation_attempt_id,
                engine_role=engine_role,
                engine_identity=self.default_engine_identity,
                parent_invocation_id=parent_invocation_id,
                provenance=invocation_provenance,
            )
        )
        if acknowledged is None:
            raise ExecutionTermination("cancelled")
        try:
            yield invocation_id
        except BaseException as error:
            terminal_status = (
                error.status
                if isinstance(error, ExecutionTermination)
                else "failed"
            )
            self.ledger.record(
                EngineInvocationTerminal(
                    invocation_id=invocation_id,
                    status=terminal_status,
                    error=_execution_error(error),
                )
            )
            raise
        else:
            self.ledger.record(
                EngineInvocationTerminal(
                    invocation_id=invocation_id,
                    status="succeeded",
                )
            )
            if self.ledger.cancellation_requested:
                raise ExecutionTermination("cancelled")
