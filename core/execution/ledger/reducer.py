"""Typed causal reducer for one Run Evidence Ledger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal, cast

from core.execution.ledger.codec import (
    contract_lock_digest,
    readiness_attestation_digest,
)
from core.execution.ledger.facts import (
    AttemptStatus,
    AvailabilityBound,
    CancellationRequested,
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    FactPayload,
    NodeAttemptStarted,
    NodeAttemptTerminal,
    NodeDisposition,
    OperationAttemptStarted,
    OperationAttemptTerminal,
    OutputsPublished,
    ReadinessAttested,
    RunAdmitted,
    RunScopeBound,
    RunStarted,
    RunTerminal,
    SelectionTerminal,
)
from core.execution.ledger.transitions import (
    PlanNodeEvidence,
)
from datatypes.exact_reference import ExactContractReference


def _causal_error() -> ValueError:
    return ValueError("Run evidence violates causal grammar")


def _typed_reference_key(
    reference: ExactContractReference,
) -> tuple[str, str, str, str]:
    return (
        reference.contract_kind,
        reference.contract_id,
        reference.contract_version,
        reference.contract_digest,
    )


def run_terminal_status(
    dispositions: Iterable[NodeDisposition],
    selection_terminals: tuple[SelectionTerminal, ...],
) -> Literal["succeeded", "failed", "cancelled", "interrupted"]:
    outcomes = {
        disposition.outcome for disposition in dispositions
    }
    if "failed" in outcomes or any(
        terminal.status == "failed"
        for terminal in selection_terminals
    ):
        return "failed"
    if "interrupted" in outcomes:
        return "interrupted"
    if "cancelled" in outcomes:
        return "cancelled"
    return "succeeded"


def _selection_result_keys(
    terminals: Iterable[SelectionTerminal],
) -> set[str]:
    return {
        terminal.result.selection_node_id
        for terminal in terminals
        if terminal.result is not None
    }


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


@dataclass(frozen=True, slots=True)
class LedgerReducer:
    """Pure causal transition owner for one admitted Run plan."""

    project_id: str
    run_id: str
    plan_evidence: tuple[PlanNodeEvidence, ...]

    @property
    def selection_consumer_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.plan_evidence
            if node.selection_consumer
        )

    def apply_facts(
        self,
        state: LedgerReducerState,
        facts: tuple[Fact, ...],
    ) -> LedgerReducerState:
        staged_state = state.clone()
        for fact in facts:
            payload = fact.payload
            staged_state.facts.append(fact)
            self._apply(staged_state, payload)
        return staged_state

    def replay_facts(
        self,
        state: LedgerReducerState,
        facts: tuple[Fact, ...],
    ) -> LedgerReducerState:
        self._validate_transaction_boundary(state, facts)
        staged_state = state.clone()
        for fact in facts:
            self._validate_causality(staged_state, fact.payload)
            staged_state.facts.append(fact)
            self._apply(staged_state, fact.payload)
        return staged_state

    def _required_input_blocker_set(
        self,
        state: LedgerReducerState,
        node_id: str,
    ) -> frozenset[str]:
        blockers: set[str] = set()
        required_inputs = next(
            node.required_input_sources
            for node in self.plan_evidence
            if node.node_id == node_id
        )
        for required_input in required_inputs:
            if any(
                source.output_port
                in state.nonempty_output_ports.get(source.node_id, set())
                for source in required_input.sources
            ):
                continue
            blockers.update(source.node_id for source in required_input.sources)
        return frozenset(blockers)

    def _validate_causality(
        self,
        state: LedgerReducerState,
        payload: FactPayload,
    ) -> None:
        plan_nodes = {node.node_id: node for node in self.plan_evidence}
        expected_binding_keys = {
            _typed_reference_key(node.binding)
            for node in self.plan_evidence
        }
        if state.run_terminal:
            raise _causal_error()
        if isinstance(payload, RunScopeBound):
            minimum_contract_root_keys = {
                _typed_reference_key(reference)
                for node in self.plan_evidence
                for reference in (
                    node.binding,
                    *((node.node_type,) if node.node_type is not None else ()),
                )
            }
            minimum_resolved_contract_keys = minimum_contract_root_keys | {
                _typed_reference_key(output.port_type)
                for node in self.plan_evidence
                for output in node.artifact_outputs
            }
            if (
                state.facts
                or payload.project_id != self.project_id
                or payload.run_id != self.run_id
                or tuple(
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                )
                != tuple(
                    sorted(
                        {
                            _typed_reference_key(reference)
                            for reference in payload.resolved_contracts
                        }
                    )
                )
                or tuple(
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                )
                != tuple(
                    sorted(
                        {
                            _typed_reference_key(reference)
                            for reference in payload.resolved_contract_roots
                        }
                    )
                )
                or not minimum_contract_root_keys
                <= {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                }
                or not minimum_resolved_contract_keys
                <= {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                }
                or not {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contract_roots
                }
                <= {
                    _typed_reference_key(reference)
                    for reference in payload.resolved_contracts
                }
                or payload.contract_lock_digest
                != contract_lock_digest(payload.resolved_contracts)
                or payload.selection_terminal_keys
                != self.selection_consumer_ids
            ):
                raise _causal_error()
            return
        if not state.facts:
            raise _causal_error()
        scope = cast(RunScopeBound, state.facts[0].payload)
        if isinstance(payload, AvailabilityBound):
            binding_key = _typed_reference_key(payload.binding)
            if (
                state.run_admitted
                or binding_key not in expected_binding_keys
                or binding_key in state.availability_by_binding
            ):
                raise _causal_error()
            return
        if isinstance(payload, RunAdmitted):
            if (
                state.run_admitted
                or state.run_started
                or payload.workflow_commit_id != scope.workflow_commit_id
                or payload.workflow_commit_revision
                != scope.workflow_commit_revision
                or set(state.availability_by_binding)
                != expected_binding_keys
            ):
                raise _causal_error()
            return
        if isinstance(payload, RunStarted):
            if not state.run_admitted or state.run_started:
                raise _causal_error()
            return
        if isinstance(payload, ReadinessAttested):
            binding_key = _typed_reference_key(payload.binding)
            availability = state.availability_by_binding.get(binding_key)
            if (
                not state.run_started
                or binding_key not in {
                    _typed_reference_key(node.binding)
                    for node in self.plan_evidence
                    if node.execution_route == "adapter"
                }
                or availability is None
                or availability.available is not True
                or binding_key in state.readiness_by_binding
                or payload.attestation_digest
                != readiness_attestation_digest(
                    binding=payload.binding,
                    readiness_contract_digest=(
                        payload.readiness_contract_digest
                    ),
                    observed_at=payload.observed_at,
                    conclusion=payload.conclusion,
                    proof_source=payload.proof_source,
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, CancellationRequested):
            if (
                not state.run_started
                or state.cancellation_sequence is not None
            ):
                raise _causal_error()
            return
        if isinstance(payload, NodeAttemptStarted):
            node_id = payload.node_id
            attempt_id = payload.node_attempt_id
            if (
                not state.run_started
                or state.cancellation_sequence is not None
                or node_id not in plan_nodes
                or node_id in state.node_attempt_by_node
                or node_id in state.dispositions
                or attempt_id in state.node_attempts
                or any(
                    upstream not in state.dispositions
                    for upstream in plan_nodes[node_id].dependencies
                )
                or self._required_input_blocker_set(state, node_id)
            ):
                raise _causal_error()
            return
        if isinstance(payload, OperationAttemptStarted):
            attempt_id = payload.node_attempt_id
            operation_id = payload.operation_attempt_id
            attempt = state.node_attempts.get(attempt_id)
            if attempt is None:
                raise _causal_error()
            node_id = attempt.node_id
            binding_key = _typed_reference_key(
                plan_nodes[node_id].binding
            )
            readiness = state.readiness_by_binding.get(binding_key)
            if (
                state.cancellation_sequence is not None
                or attempt.terminal is not None
                or operation_id in state.operations
                or any(
                    operation.node_attempt_id == attempt_id
                    for operation in state.operations.values()
                )
                or (
                    plan_nodes[node_id].execution_route == "adapter"
                    and (
                        readiness is None
                        or readiness.conclusion != "passing"
                    )
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, EngineInvocationStarted):
            operation_id = payload.operation_attempt_id
            invocation_id = payload.invocation_id
            parent_invocation_id = payload.parent_invocation_id
            operation = state.operations.get(operation_id)
            parent = (
                state.invocations.get(parent_invocation_id)
                if parent_invocation_id is not None
                else None
            )
            if (
                state.cancellation_sequence is not None
                or operation is None
                or operation.terminal is not None
                or invocation_id in state.invocations
                or (
                    parent_invocation_id is not None
                    and (
                        parent is None
                        or parent.operation_attempt_id != operation_id
                        or parent.terminal != "succeeded"
                    )
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, EngineInvocationTerminal):
            invocation = state.invocations.get(payload.invocation_id)
            if (
                invocation is None
                or invocation.terminal is not None
                or (
                    payload.status == "cancelled"
                    and state.cancellation_sequence is None
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, OperationAttemptTerminal):
            operation_id = payload.operation_attempt_id
            operation = state.operations.get(operation_id)
            if (
                operation is None
                or operation.terminal is not None
                or (
                    payload.status == "cancelled"
                    and state.cancellation_sequence is None
                )
                or any(
                    invocation.operation_attempt_id == operation_id
                    and invocation.terminal is None
                    for invocation in state.invocations.values()
                )
                or (
                    payload.status == "succeeded"
                    and any(
                        invocation.operation_attempt_id == operation_id
                        and invocation.terminal != "succeeded"
                        for invocation in state.invocations.values()
                    )
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, OutputsPublished):
            node_id = payload.node_id
            attempt_id = state.node_attempt_by_node.get(node_id)
            attempt = (
                state.node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if (
                state.cancellation_sequence is not None
                or attempt is None
                or attempt.terminal is not None
                or node_id in state.dispositions
                or node_id in state.nonempty_output_ports
            ):
                raise _causal_error()
            child_operations = [
                operation_id
                for operation_id, operation in state.operations.items()
                if operation.node_attempt_id == attempt_id
            ]
            if child_operations and any(
                state.operations[operation_id].terminal != "succeeded"
                for operation_id in child_operations
            ):
                raise _causal_error()
            return
        if isinstance(payload, NodeAttemptTerminal):
            attempt_id = payload.node_attempt_id
            attempt = state.node_attempts.get(attempt_id)
            child_operations = [
                operation
                for operation in state.operations.values()
                if operation.node_attempt_id == attempt_id
            ]
            if (
                attempt is None
                or attempt.terminal is not None
                or (
                    payload.status == "cancelled"
                    and state.cancellation_sequence is None
                )
                or any(operation.terminal is None for operation in child_operations)
                or (
                    payload.resolution == "cache_replayed"
                    and (
                        child_operations
                        or (
                            payload.status == "succeeded"
                            and attempt.node_id
                            not in state.nonempty_output_ports
                        )
                        or (
                            payload.status == "failed"
                            and attempt.node_id
                            in state.nonempty_output_ports
                        )
                    )
                )
                or (
                    payload.resolution == "executed"
                    and payload.status == "succeeded"
                    and len(child_operations) != 1
                )
                or (
                    payload.resolution == "executed"
                    and child_operations
                    and child_operations[-1].terminal != payload.status
                    and not (
                        payload.status == "failed"
                        and payload.failure_origin == "publication"
                        and child_operations[-1].terminal == "succeeded"
                    )
                    and not (
                        state.cancellation_sequence is not None
                        and payload.status
                        in {"cancelled", "interrupted", "outcome_unknown"}
                        and child_operations[-1].terminal
                        in {
                            "succeeded",
                            "cancelled",
                            "interrupted",
                            "outcome_unknown",
                        }
                    )
                )
            ):
                raise _causal_error()
            failure_origin = payload.failure_origin
            if failure_origin == "operation" and (
                payload.resolution != "executed"
                or len(child_operations) != 1
                or child_operations[0].terminal != "failed"
            ):
                raise _causal_error()
            if failure_origin == "attempt" and (
                payload.resolution != "executed" or child_operations
            ):
                raise _causal_error()
            if failure_origin == "binding" and (
                payload.resolution != "executed" or child_operations
            ):
                raise _causal_error()
            if failure_origin == "binding":
                node_id = attempt.node_id
                binding_key = _typed_reference_key(
                    plan_nodes[node_id].binding
                )
                availability = state.availability_by_binding.get(
                    binding_key
                )
                readiness = state.readiness_by_binding.get(binding_key)
                error = payload.error
                if (
                    error is None
                    or plan_nodes[node_id].execution_route != "adapter"
                    or (
                        error.code == "binding_unavailable"
                        and (
                            availability is None
                            or availability.available is not False
                        )
                    )
                    or (
                        error.code == "readiness_rejected"
                        and (
                            readiness is None
                            or readiness.conclusion != "failing"
                        )
                    )
                    or error.code
                    not in {"binding_unavailable", "readiness_rejected"}
                ):
                    raise _causal_error()
            if failure_origin == "publication" and (
                (
                    payload.resolution == "executed"
                    and (
                        len(child_operations) != 1
                        or child_operations[0].terminal != "succeeded"
                    )
                )
                or (
                    payload.resolution == "cache_replayed"
                    and child_operations
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, NodeDisposition):
            node_id = payload.node_id
            outcome = payload.outcome
            if (
                node_id not in plan_nodes
                or node_id in state.dispositions
            ):
                raise _causal_error()
            attempt_id = state.node_attempt_by_node.get(node_id)
            attempt = (
                state.node_attempts.get(attempt_id)
                if attempt_id is not None
                else None
            )
            if outcome == "blocked":
                blocked_by = frozenset(payload.blocked_by)
                if (
                    state.cancellation_sequence is not None
                    or attempt is not None
                    or not blocked_by
                    or any(
                        upstream not in state.dispositions
                        for upstream in plan_nodes[node_id].dependencies
                    )
                    or blocked_by != self._required_input_blocker_set(state, node_id)
                ):
                    raise _causal_error()
                return
            if (
                outcome == "succeeded"
                and state.cancellation_sequence is not None
            ):
                raise _causal_error()
            if (
                outcome == "cancelled"
                and state.cancellation_sequence is None
            ):
                raise _causal_error()
            if outcome == "cancelled" and attempt is None:
                return
            if outcome == "interrupted" and attempt is None:
                return
            if attempt is None or attempt.terminal is None:
                raise _causal_error()
            expected_outcome = {
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled",
                "interrupted": "interrupted",
                "outcome_unknown": "interrupted",
            }[attempt.terminal]
            if (
                expected_outcome != outcome
                or (
                    outcome == "succeeded"
                    and payload.resolution != attempt.resolution
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, SelectionTerminal):
            selection_key = (
                payload.result.selection_node_id
                if payload.result is not None
                else "__failed__"
            )
            if (
                not state.run_started
                or not state.expected_selection_terminal_keys
                or set(state.dispositions) != set(plan_nodes)
                or any(
                    disposition.outcome != "succeeded"
                    for disposition in state.dispositions.values()
                )
                or (
                    payload.status == "succeeded"
                    and (
                        selection_key
                        not in state.expected_selection_terminal_keys
                        or selection_key in _selection_result_keys(
                            state.selection_terminals
                        )
                    )
                )
                or (
                    payload.status == "failed"
                    and state.selection_terminals
                )
                or (
                    payload.status == "succeeded"
                    and any(
                        terminal.status == "failed"
                        for terminal in state.selection_terminals
                    )
                )
            ):
                raise _causal_error()
            return
        if isinstance(payload, RunTerminal):
            if (
                payload.status == "interrupted"
                and state.run_admitted
                and not state.run_terminal
            ):
                return
            expected_status = run_terminal_status(
                state.dispositions.values(),
                tuple(state.selection_terminals),
            )
            outcomes = {
                disposition.outcome
                for disposition in state.dispositions.values()
            }
            if (
                not state.run_started
                or set(state.dispositions) != set(plan_nodes)
                or any(
                    attempt.terminal is None
                    for attempt in state.node_attempts.values()
                )
                or any(
                    operation.terminal is None
                    for operation in state.operations.values()
                )
                or any(
                    invocation.terminal is None
                    for invocation in state.invocations.values()
                )
                or (
                    state.expected_selection_terminal_keys
                    and not outcomes.intersection(
                        {"failed", "interrupted", "cancelled"}
                    )
                    and payload.status == "succeeded"
                    and _selection_result_keys(
                        state.selection_terminals
                    )
                    != set(state.expected_selection_terminal_keys)
                )
                or payload.status != expected_status
            ):
                raise _causal_error()
            return
        raise _causal_error()

    def _apply(
        self,
        state: LedgerReducerState,
        payload: FactPayload,
    ) -> None:
        if isinstance(payload, RunScopeBound):
            state.expected_selection_terminal_keys = (
                payload.selection_terminal_keys
            )
        elif isinstance(payload, AvailabilityBound):
            state.availability_by_binding[
                _typed_reference_key(payload.binding)
            ] = payload
        elif isinstance(payload, ReadinessAttested):
            state.readiness_by_binding[
                _typed_reference_key(payload.binding)
            ] = payload
        elif isinstance(payload, RunAdmitted):
            state.run_admitted = True
        elif isinstance(payload, RunStarted):
            state.run_started = True
        elif isinstance(payload, CancellationRequested):
            state.cancellation_sequence = len(state.facts)
        elif isinstance(payload, NodeAttemptStarted):
            state.node_attempts[payload.node_attempt_id] = (
                NodeAttemptState(node_id=payload.node_id)
            )
            state.node_attempt_by_node[payload.node_id] = (
                payload.node_attempt_id
            )
        elif isinstance(payload, OperationAttemptStarted):
            state.operations[payload.operation_attempt_id] = (
                OperationAttemptState(node_attempt_id=payload.node_attempt_id)
            )
        elif isinstance(payload, EngineInvocationStarted):
            state.invocations[payload.invocation_id] = InvocationState(
                operation_attempt_id=payload.operation_attempt_id,
                parent_invocation_id=payload.parent_invocation_id,
            )
        elif isinstance(payload, EngineInvocationTerminal):
            invocation = state.invocations[payload.invocation_id]
            invocation.terminal = payload.status
        elif isinstance(payload, OperationAttemptTerminal):
            operation = state.operations[payload.operation_attempt_id]
            operation.terminal = payload.status
        elif isinstance(payload, NodeAttemptTerminal):
            attempt = state.node_attempts[payload.node_attempt_id]
            attempt.terminal = payload.status
            attempt.resolution = payload.resolution
        elif isinstance(payload, OutputsPublished):
            state.nonempty_output_ports[payload.node_id] = {
                output.output_port
                for output in payload.outputs
                if output.value_count > 0
            } | {artifact.output_port for artifact in payload.artifacts}
        elif isinstance(payload, NodeDisposition):
            state.dispositions[payload.node_id] = payload
        elif isinstance(payload, SelectionTerminal):
            state.selection_terminals.append(payload)
        elif isinstance(payload, RunTerminal):
            state.run_terminal = True

    def _validate_transaction_boundary(
        self,
        state: LedgerReducerState,
        facts: tuple[Fact, ...],
    ) -> None:
        closure_facts = [
            fact
            for fact in facts
            if isinstance(fact.payload, (SelectionTerminal, RunTerminal))
        ]
        if closure_facts:
            if (
                closure_facts != list(facts)
                or not isinstance(facts[-1].payload, RunTerminal)
                or any(
                    not isinstance(fact.payload, SelectionTerminal)
                    for fact in facts[:-1]
                )
            ):
                raise _causal_error()
            return
        operation_terminals = [
            fact
            for fact in facts
            if isinstance(fact.payload, OperationAttemptTerminal)
        ]
        node_terminals = [
            fact
            for fact in facts
            if isinstance(fact.payload, NodeAttemptTerminal)
        ]
        output_publications = [
            fact
            for fact in facts
            if isinstance(fact.payload, OutputsPublished)
        ]
        dispositions = [
            fact
            for fact in facts
            if isinstance(fact.payload, NodeDisposition)
        ]
        if not (operation_terminals or node_terminals or output_publications):
            return
        if (
            len(operation_terminals) > 1
            or len(node_terminals) != 1
            or len(dispositions) != 1
        ):
            raise _causal_error()
        node_terminal = cast(NodeAttemptTerminal, node_terminals[0].payload)
        attempt = state.node_attempts.get(
            node_terminal.node_attempt_id
        )
        disposition = cast(NodeDisposition, dispositions[0].payload)
        if (
            attempt is None
            or disposition.node_id != attempt.node_id
        ):
            raise _causal_error()
        terminal_succeeded = node_terminal.status == "succeeded"
        publication_node_ids = {
            fact.payload.node_id for fact in output_publications
        }
        if (
            terminal_succeeded != (len(output_publications) == 1)
            or (not terminal_succeeded and output_publications)
            or publication_node_ids - {attempt.node_id}
        ):
            raise _causal_error()
        open_operations = [
            operation_id
            for operation_id, operation in state.operations.items()
            if (
                operation.node_attempt_id == node_terminal.node_attempt_id
                and operation.terminal is None
            )
        ]
        if (
            bool(open_operations) != bool(operation_terminals)
            or (
                operation_terminals
                and cast(
                    OperationAttemptTerminal,
                    operation_terminals[0].payload,
                ).operation_attempt_id
                not in open_operations
            )
        ):
            raise _causal_error()
        expected_payload_types = [
            *(
                (OperationAttemptTerminal,)
                if operation_terminals
                else ()
            ),
            *((OutputsPublished,) if terminal_succeeded else ()),
            NodeAttemptTerminal,
            NodeDisposition,
        ]
        if [type(fact.payload) for fact in facts] != expected_payload_types:
            raise _causal_error()
