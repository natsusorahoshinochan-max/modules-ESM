"""Mutable in-process records owned by Run Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading

from core.execution.ledger import Ledger, V2RunError
from core.execution.resources import CancellationControl
from core.workflow.authoring import VerifiedWorkflowCommit


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
