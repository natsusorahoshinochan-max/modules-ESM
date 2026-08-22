"""Typed causal reducer state for one Run Evidence Ledger."""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.execution.ledger.facts import (
    AttemptStatus,
    AvailabilityBound,
    Fact,
    NodeDisposition,
    ReadinessAttested,
    SelectionTerminal,
)


@dataclass(slots=True)
class NodeAttemptState:
    node_id: str
    terminal: AttemptStatus | None = None
    resolution: str | None = None


@dataclass(slots=True)
class OperationAttemptState:
    node_attempt_id: str
    terminal: AttemptStatus | None = None


@dataclass(slots=True)
class InvocationState:
    operation_attempt_id: str
    parent_invocation_id: str | None
    terminal: AttemptStatus | None = None


@dataclass(slots=True)
class LedgerReducerState:
    facts: list[Fact]
    availability_by_binding: dict[
        tuple[str, str, str, str], AvailabilityBound
    ]
    readiness_by_binding: dict[
        tuple[str, str, str, str], ReadinessAttested
    ]
    node_attempts: dict[str, NodeAttemptState]
    node_attempt_by_node: dict[str, str]
    operations: dict[str, OperationAttemptState]
    invocations: dict[str, InvocationState]
    dispositions: dict[str, NodeDisposition]
    nonempty_output_ports: dict[str, set[str]]
    run_admitted: bool
    run_started: bool
    expected_selection_terminal_keys: tuple[str, ...]
    selection_terminals: list[SelectionTerminal]
    run_terminal: bool
    cancellation_sequence: int | None

    @classmethod
    def empty(cls) -> LedgerReducerState:
        return cls(
            facts=[], availability_by_binding={}, readiness_by_binding={},
            node_attempts={}, node_attempt_by_node={}, operations={},
            invocations={}, dispositions={},
            nonempty_output_ports={}, run_admitted=False, run_started=False,
            expected_selection_terminal_keys=(),
            selection_terminals=[],
            run_terminal=False, cancellation_sequence=None,
        )

    def clone(self) -> LedgerReducerState:
        return LedgerReducerState(
            facts=list(self.facts),
            availability_by_binding=dict(self.availability_by_binding),
            readiness_by_binding=dict(self.readiness_by_binding),
            node_attempts={
                key: replace(value)
                for key, value in self.node_attempts.items()
            },
            node_attempt_by_node=dict(self.node_attempt_by_node),
            operations={
                key: replace(value) for key, value in self.operations.items()
            },
            invocations={
                key: replace(value) for key, value in self.invocations.items()
            },
            dispositions=dict(self.dispositions),
            nonempty_output_ports={
                key: set(value)
                for key, value in self.nonempty_output_ports.items()
            },
            run_admitted=self.run_admitted,
            run_started=self.run_started,
            expected_selection_terminal_keys=(
                self.expected_selection_terminal_keys
            ),
            selection_terminals=list(self.selection_terminals),
            run_terminal=self.run_terminal,
            cancellation_sequence=self.cancellation_sequence,
        )
