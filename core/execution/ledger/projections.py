"""Typed domain projections derived exclusively from admitted Ledger facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core.execution.ledger.facts import (
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    NodeAttemptStarted,
    NodeAttemptTerminal,
    NodeDisposition,
    OperationAttemptStarted,
    OperationAttemptTerminal,
    OutputsPublished,
    PublishedArtifact,
    PublishedOutput,
    ReadinessAttested,
    RunAdmitted,
    RunScopeBound,
    RunStarted,
    RunTerminal,
    SelectionResult,
    SelectionTerminal,
    StructuredError,
)


_EVENT_PAYLOAD_TYPES = (
    ReadinessAttested,
    RunAdmitted,
    RunStarted,
    NodeAttemptStarted,
    OperationAttemptStarted,
    EngineInvocationStarted,
    EngineInvocationTerminal,
    OperationAttemptTerminal,
    NodeAttemptTerminal,
    NodeDisposition,
    SelectionTerminal,
    RunTerminal,
)


@dataclass(frozen=True, slots=True)
class RunCursor:
    """Opaque cursor value owned and validated by one Run Ledger."""

    value: str


@dataclass(frozen=True, slots=True)
class NodeDispositionProjection:
    node_id: str
    outcome: Literal[
        "succeeded",
        "failed",
        "blocked",
        "cancelled",
        "interrupted",
    ]
    blocked_by: tuple[str, ...]
    resolution: Literal["executed", "cache_replayed"] | None
    terminal_sequence: int


@dataclass(frozen=True, slots=True)
class RunProjection:
    project_id: str
    run_id: str
    workflow_commit_id: str
    workflow_commit_revision: int
    workflow_digest: str
    status: Literal[
        "admitted",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
    ]
    ledger_cursor: RunCursor
    node_dispositions: tuple[NodeDispositionProjection, ...]
    outputs: tuple[PublishedOutput, ...]
    artifacts: tuple[PublishedArtifact, ...]
    selection_results: tuple[SelectionResult, ...] | None = None
    selection_error: StructuredError | None = None
    terminal_sequence: int | None = None
    derived_from_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class CancellationDecision:
    outcome: Literal[
        "cancellation_requested",
        "already_requested",
        "completed_before_cancel",
        "already_terminal",
    ]
    decision_sequence: int
    cursor: RunCursor


@dataclass(frozen=True, slots=True)
class ReplayWindow:
    after_sequence: int
    after_cursor: RunCursor
    through_sequence: int
    through_cursor: RunCursor
    events: tuple[Fact, ...]
    terminal: bool


def event_facts(
    facts: Sequence[Fact],
    *,
    after_sequence: int = 0,
    through_sequence: int | None = None,
) -> tuple[Fact, ...]:
    upper = (
        len(facts)
        if through_sequence is None
        else min(through_sequence, len(facts))
    )
    return tuple(
        fact
        for fact in facts[after_sequence:upper]
        if isinstance(fact.payload, _EVENT_PAYLOAD_TYPES)
    )


def project_run(
    *,
    project_id: str,
    run_id: str,
    plan_node_order: tuple[str, ...],
    facts: Sequence[Fact],
    cursor: RunCursor,
) -> RunProjection:
    if not facts or not isinstance(facts[0].payload, RunScopeBound):
        raise ValueError("Run Ledger scope is unavailable")
    scope = facts[0].payload
    dispositions: list[NodeDispositionProjection] = []
    published_by_node: dict[
        str,
        tuple[tuple[PublishedOutput, ...], tuple[PublishedArtifact, ...]],
    ] = {}
    status: Literal[
        "admitted",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
    ] = "admitted"
    selection_results: list[SelectionResult] = []
    selection_error: StructuredError | None = None
    terminal_sequence: int | None = None
    for fact in facts:
        payload = fact.payload
        if isinstance(payload, RunStarted):
            status = "running"
        elif isinstance(payload, NodeDisposition):
            dispositions.append(
                NodeDispositionProjection(
                    node_id=payload.node_id,
                    outcome=payload.outcome,
                    blocked_by=payload.blocked_by,
                    resolution=payload.resolution,
                    terminal_sequence=fact.sequence,
                )
            )
        elif isinstance(payload, OutputsPublished):
            published_by_node[payload.node_id] = (
                payload.outputs,
                payload.artifacts,
            )
        elif isinstance(payload, SelectionTerminal):
            if payload.result is not None:
                selection_results.append(payload.result)
            else:
                selection_error = payload.error
        elif isinstance(payload, RunTerminal):
            status = payload.status
            terminal_sequence = fact.sequence
    successful_nodes = {
        disposition.node_id
        for disposition in dispositions
        if disposition.outcome == "succeeded"
    }
    outputs = tuple(
        output
        for node_id in plan_node_order
        if node_id in successful_nodes
        for output in published_by_node.get(node_id, ((), ()))[0]
    )
    artifacts = tuple(
        artifact
        for node_id in plan_node_order
        if node_id in successful_nodes
        for artifact in published_by_node.get(node_id, ((), ()))[1]
    )
    return RunProjection(
        project_id=project_id,
        run_id=run_id,
        workflow_commit_id=scope.workflow_commit_id,
        workflow_commit_revision=scope.workflow_commit_revision,
        workflow_digest=scope.workflow_digest,
        status=status,
        ledger_cursor=cursor,
        node_dispositions=tuple(dispositions),
        outputs=outputs,
        artifacts=artifacts,
        selection_results=(
            tuple(selection_results) if scope.selection_required else None
        ),
        selection_error=selection_error,
        terminal_sequence=terminal_sequence,
        derived_from_run_id=(
            scope.derived_from.source_run_id
            if scope.derived_from is not None
            else None
        ),
    )
