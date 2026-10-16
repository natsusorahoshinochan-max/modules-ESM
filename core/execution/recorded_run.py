"""Durable completed Run readings without execution-plan replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, cast

from core.execution.ledger.codec import (
    decode_cursor, fact_from_canonical, fact_to_canonical,
    payload_from_canonical, payload_to_canonical,
)
from core.execution.ledger.facts import (
    EngineInvocationStarted, EngineInvocationTerminal, Fact, NodeAttemptStarted,
    NodeAttemptTerminal, NodeDisposition, OperationAttemptStarted,
    OperationAttemptTerminal, OutputsPublished, ReadinessAttested, RunAdmitted,
    RunStarted, RunTerminal, StructuredError,
)
from core.execution.ledger.ledger import V2RunError, run_cursor
from core.execution.ledger.projections import (
    CancellationDecision, NodeDispositionProjection, ReplayWindow, RunCursor, RunProjection,
)
from core.execution.scope import RunExecutionScope
from core.project.manager import ProjectManager
from core.project.storage import write_new_file_durable
from datatypes.i_json import thaw_i_json


_RECORDED_EVENT_TYPES = (
    ReadinessAttested, RunAdmitted, RunStarted, NodeAttemptStarted,
    OperationAttemptStarted, EngineInvocationStarted, EngineInvocationTerminal,
    OperationAttemptTerminal, NodeAttemptTerminal, NodeDisposition, RunTerminal,
)


@dataclass(frozen=True, slots=True)
class RecordedRun:
    """An immutable terminal projection and its generic event readings."""

    _projection: RunProjection
    _events: tuple[Fact, ...]
    _terminal_sequence: int

    @property
    def terminal(self) -> bool:
        return True

    @property
    def cursor(self) -> RunCursor:
        return self._projection.ledger_cursor

    def projection(self) -> RunProjection:
        return self._projection

    def ensure_evidence_available(self) -> None:
        """The complete reading was admitted when this immutable value loaded."""

    def wake_waiters(self) -> None:
        """Completed readings have no waiting writers."""

    def events(self, *, after_sequence: int = 0,
               through_sequence: int | None = None) -> tuple[Fact, ...]:
        upper = self._terminal_sequence if through_sequence is None else through_sequence
        return tuple(fact for fact in self._events if after_sequence < fact.sequence <= upper)

    def sequence_for_cursor(self, cursor: RunCursor | None) -> int:
        if cursor is None:
            return 0
        try:
            decoded = decode_cursor(cursor)
            valid = (
                decoded.project_id == self._projection.project_id
                and decoded.run_id == self._projection.run_id
                and decoded.sequence <= self._terminal_sequence
                and self._cursor_at(decoded.sequence) == cursor
            )
        except ValueError:
            valid = False
        if not valid:
            raise V2RunError("invalid_cursor", "Run Event Stream cursor is invalid",
                             details={"after_sequence": cursor.value})
        return decoded.sequence

    def _cursor_at(self, sequence: int) -> RunCursor:
        return run_cursor(sequence, project_id=self._projection.project_id, run_id=self._projection.run_id)

    def replay(self, cursor: RunCursor | None) -> ReplayWindow:
        after = self.sequence_for_cursor(cursor)
        return ReplayWindow(after, self._cursor_at(after), self._terminal_sequence,
                            self.cursor, self.events(after_sequence=after), True)

    def wait_for_events(self, after_sequence: int, *, timeout_seconds: float) -> tuple[tuple[Fact, ...], int, bool]:
        del timeout_seconds
        return self.events(after_sequence=after_sequence), self._terminal_sequence, True

    def request_cancellation(self, after_cursor: RunCursor | None) -> CancellationDecision:
        after = self.sequence_for_cursor(after_cursor)
        sequence = self._terminal_sequence
        return CancellationDecision(
            "completed_before_cancel" if after_cursor is not None and after < sequence else "already_terminal",
            sequence, self.cursor,
        )

    @classmethod
    def load(cls, projects: ProjectManager, project_id: str, run_id: str) -> RecordedRun | None:
        path = projects.run_storage_directory(project_id, run_id) / "reading.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_bytes())
            if raw["schema_version"] != 1:
                raise ValueError("Unsupported Run reading version")
            value = raw["projection"]
            if value["project_id"] != project_id or value["run_id"] != run_id:
                raise ValueError("Run reading identity mismatch")
            if value["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
                raise ValueError("Run reading is not terminal")
            sequence = value["terminal_sequence"]
            if type(sequence) is not int or sequence < 1:
                raise ValueError("Run reading terminal sequence is invalid")
            if value["ledger_cursor"] != run_cursor(sequence, project_id=project_id, run_id=run_id).value:
                raise ValueError("Run reading cursor is invalid")
            projection = RunProjection(
                project_id=project_id, run_id=run_id,
                workflow_commit_id=value["workflow_commit_id"], status=value["status"],
                ledger_cursor=RunCursor(value["ledger_cursor"]),
                node_dispositions=tuple(NodeDispositionProjection(
                    node_id=item["node_id"], outcome=item["outcome"],
                    blocked_by=tuple(item["blocked_by"]), resolution=item["resolution"],
                    terminal_sequence=item["terminal_sequence"],
                ) for item in value["node_dispositions"]),
                publications=tuple(cast(OutputsPublished, payload_from_canonical("outputs_published", item))
                                   for item in value["publications"]),
                terminal_sequence=value["terminal_sequence"],
                derived_from_run_id=value["derived_from_run_id"],
                execution_scope=(RunExecutionScope(
                    mode=value["execution_scope"]["mode"],
                    selected_node_ids=tuple(value["execution_scope"]["selected_node_ids"]),
                    execution_node_ids=tuple(value["execution_scope"]["execution_node_ids"]),
                    reused_node_ids=tuple(value["execution_scope"]["reused_node_ids"]),
                    out_of_scope_node_ids=tuple(value["execution_scope"]["out_of_scope_node_ids"]),
                    out_of_scope_selection_ids=(),
                    source_run_id=value["execution_scope"].get("source_run_id"),
                )
                                 if value["execution_scope"] is not None else None),
                diagnostic=(StructuredError(**value["diagnostic"])
                                 if value["diagnostic"] is not None else None),
            )
            events = tuple(fact_from_canonical(item) for item in raw["events"])
            return cls(projection, events, sequence)
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Completed Run reading is invalid") from error


def preserve_run_reading(projects: ProjectManager, projection: RunProjection, events: tuple[Fact, ...]) -> None:
    """Write the generic reading once; retain original execution records unchanged."""
    if projection.terminal_sequence is None:
        raise ValueError("Only terminal Runs have immutable readings")
    value: dict[str, Any] = {
        "project_id": projection.project_id, "run_id": projection.run_id,
        "workflow_commit_id": projection.workflow_commit_id, "status": projection.status,
        "ledger_cursor": projection.ledger_cursor.value,
        "node_dispositions": [asdict(item) for item in projection.node_dispositions],
        "publications": [payload_to_canonical(item) for item in projection.publications],
        "terminal_sequence": projection.terminal_sequence,
        "derived_from_run_id": projection.derived_from_run_id,
        "execution_scope": ({key: value for key, value in projection.execution_scope.projection().items()
                             if key != "out_of_scope_selection_ids"} if projection.execution_scope is not None else None),
        "diagnostic": ({
            "code": projection.diagnostic.code,
            "message": projection.diagnostic.message,
            "retryable": projection.diagnostic.retryable,
            "correlation_id": projection.diagnostic.correlation_id,
            "details": thaw_i_json(projection.diagnostic.details),
        } if projection.diagnostic is not None else None),
    }
    generic_events = [fact_to_canonical(fact) for fact in events
                      if isinstance(fact.payload, _RECORDED_EVENT_TYPES)]
    payload = json.dumps({"schema_version": 1, "projection": value, "events": generic_events},
                         sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    write_new_file_durable(projects.run_storage_directory(projection.project_id, projection.run_id),
                           ("reading.json",), payload)
