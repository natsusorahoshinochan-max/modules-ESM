"""Workflow DAG model: nodes, edges, validation, and topological sort."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.module_definition import PortDefinition
    from core.module_registry import ModuleRegistry


class NodeState(str, Enum):
    """States a workflow node transitions through during execution."""

    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass
class WorkflowNode:
    """A single module instance in a workflow with bound parameters."""

    node_id: str
    module_id: str
    module_version: str
    parameters: dict[str, Any] = field(default_factory=dict)
    state: NodeState = NodeState.IDLE
    outputs: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        """Reset node to initial state for re-execution."""
        self.state = NodeState.IDLE
        self.outputs = {}


@dataclass
class WorkflowEdge:
    """Connection from one node+port to another node+port."""

    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str


class WorkflowValidationErrorKind(str, Enum):
    """Stable public kinds for pre-execution Workflow errors."""

    WORKFLOW_CYCLE = "workflow_cycle"
    MODULE_UNAVAILABLE = "module_unavailable"
    MODULE_VERSION_MISMATCH = "module_version_mismatch"
    SOURCE_PORT_NOT_FOUND = "source_port_not_found"
    TARGET_PORT_NOT_FOUND = "target_port_not_found"
    PORT_TYPE_MISMATCH = "port_type_mismatch"
    REQUIRED_INPUT_MISSING = "required_input_missing"
    REQUIRED_INPUT_GROUP_MISSING = "required_input_group_missing"
    DUPLICATE_INPUT_CONNECTION = "duplicate_input_connection"
    CONFLICTING_INPUT_CONNECTIONS = "conflicting_input_connections"
    DUPLICATE_NODE_ID = "duplicate_node_id"
    EDGE_NODE_NOT_FOUND = "edge_node_not_found"
    MALFORMED_WORKFLOW = "malformed_workflow"


@dataclass(frozen=True)
class WorkflowValidationError:
    """A safe, structured description of one invalid Workflow element."""

    kind: WorkflowValidationErrorKind
    message: str
    node_id: str | None = None
    module_id: str | None = None
    port: str | None = None
    ports: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind.value,
            "message": self.message,
        }
        for name in ("node_id", "module_id", "port"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        if self.ports:
            result["ports"] = list(self.ports)
        return result


@dataclass(frozen=True)
class WorkflowValidationResult:
    """The authoritative result of validating a Workflow before execution."""

    errors: tuple[WorkflowValidationError, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass
class Workflow:
    """A directed acyclic graph of nodes connected by edges."""

    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    edges: list[WorkflowEdge] = field(default_factory=list)

    def add_node(self, node: WorkflowNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(f"Node ID '{node.node_id}' already exists in workflow")
        self.nodes[node.node_id] = node

    def add_edge(self, edge: WorkflowEdge) -> None:
        if edge.source_node_id not in self.nodes:
            raise ValueError(f"Source node '{edge.source_node_id}' not found")
        if edge.target_node_id not in self.nodes:
            raise ValueError(f"Target node '{edge.target_node_id}' not found")
        self.edges.append(edge)

    def get_upstream_nodes(self, node_id: str) -> list[str]:
        """Return node_ids of all direct upstream nodes."""
        return [
            e.source_node_id
            for e in self.edges
            if e.target_node_id == node_id
        ]

    def get_downstream_nodes(self, node_id: str) -> list[str]:
        """Return node_ids of all direct downstream nodes."""
        return [
            e.target_node_id
            for e in self.edges
            if e.source_node_id == node_id
        ]

    def get_inputs_for_node(self, node_id: str) -> dict[str, Any]:
        """Collect outputs from upstream nodes keyed by target port name.

        Only includes ports from which an upstream node actually has output.
        """
        inputs: dict[str, Any] = {}
        for edge in self.edges:
            if edge.target_node_id == node_id:
                upstream = self.nodes.get(edge.source_node_id)
                if upstream and edge.source_port in upstream.outputs:
                    inputs[edge.target_port] = upstream.outputs[edge.source_port]
        return inputs

    def _resolve_edge_port(
        self,
        registry: ModuleRegistry,
        *,
        node_id: str,
        port_name: str,
        source: bool,
    ) -> tuple[
        WorkflowNode | None,
        PortDefinition | None,
        WorkflowValidationError | None,
    ]:
        """Resolve one edge endpoint against its Module Port contract."""
        node = self.nodes.get(node_id)
        definition = (
            registry.get(node.module_id) if node is not None else None
        )
        if node is None or definition is None:
            return node, None, None

        declared_ports = (
            definition.output_ports if source else definition.input_ports
        )
        port = next(
            (
                candidate
                for candidate in declared_ports
                if candidate.name == port_name
            ),
            None,
        )
        if port is not None:
            return node, port, None

        direction = "Source" if source else "Target"
        kind = (
            WorkflowValidationErrorKind.SOURCE_PORT_NOT_FOUND
            if source
            else WorkflowValidationErrorKind.TARGET_PORT_NOT_FOUND
        )
        return node, None, WorkflowValidationError(
            kind=kind,
            message=(
                f"{direction} Port '{port_name}' is not declared by "
                f"Module '{node.module_id}'"
            ),
            node_id=node.node_id,
            module_id=node.module_id,
            port=port_name,
        )

    def validate(self, registry: ModuleRegistry) -> WorkflowValidationResult:
        """Validate the Workflow's declared graph against registered Modules."""
        errors: list[WorkflowValidationError] = []
        for node_id in self.validate_acyclic():
            node = self.nodes[node_id]
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.WORKFLOW_CYCLE,
                message="Node participates in a Workflow cycle",
                node_id=node.node_id,
                module_id=node.module_id,
            ))
        for edge in self.edges:
            _, source_port, source_error = self._resolve_edge_port(
                registry,
                node_id=edge.source_node_id,
                port_name=edge.source_port,
                source=True,
            )
            if source_error is not None:
                errors.append(source_error)
            target, target_port, target_error = self._resolve_edge_port(
                registry,
                node_id=edge.target_node_id,
                port_name=edge.target_port,
                source=False,
            )
            if target_error is not None:
                errors.append(target_error)
            if (
                target is not None
                and source_port is not None
                and target_port is not None
                and source_port.type_id != target_port.type_id
            ):
                errors.append(WorkflowValidationError(
                    kind=WorkflowValidationErrorKind.PORT_TYPE_MISMATCH,
                    message=(
                        f"Source Port type '{source_port.type_id}' does not "
                        f"exactly match target Port type '{target_port.type_id}'"
                    ),
                    node_id=target.node_id,
                    module_id=target.module_id,
                    port=target_port.name,
                ))
        incoming = {
            (edge.target_node_id, edge.target_port)
            for edge in self.edges
        }
        for node in self.nodes.values():
            definition = registry.get(node.module_id)
            if definition is None:
                errors.append(WorkflowValidationError(
                    kind=WorkflowValidationErrorKind.MODULE_UNAVAILABLE,
                    message=f"Module '{node.module_id}' is not available",
                    node_id=node.node_id,
                    module_id=node.module_id,
                ))
                continue
            if node.module_version != definition.version:
                errors.append(WorkflowValidationError(
                    kind=WorkflowValidationErrorKind.MODULE_VERSION_MISMATCH,
                    message=(
                        f"Node requires Module '{node.module_id}' version "
                        f"'{node.module_version}'; available version is "
                        f"'{definition.version}'"
                    ),
                    node_id=node.node_id,
                    module_id=node.module_id,
                ))
            for port in definition.input_ports:
                if port.required and (node.node_id, port.name) not in incoming:
                    errors.append(WorkflowValidationError(
                        kind=WorkflowValidationErrorKind.REQUIRED_INPUT_MISSING,
                        message=f"Required input Port '{port.name}' is not connected",
                        node_id=node.node_id,
                        module_id=node.module_id,
                        port=port.name,
                    ))
                connection_count = sum(
                    edge.target_node_id == node.node_id
                    and edge.target_port == port.name
                    for edge in self.edges
                )
                if connection_count > 1 and not port.allow_multiple:
                    errors.append(WorkflowValidationError(
                        kind=WorkflowValidationErrorKind.DUPLICATE_INPUT_CONNECTION,
                        message=f"Input Port '{port.name}' accepts only one connection",
                        node_id=node.node_id,
                        module_id=node.module_id,
                        port=port.name,
                    ))
            for group in definition.input_groups:
                connected_alternatives = [
                    alternative
                    for alternative in group.alternatives
                    if any(
                        (node.node_id, port_name) in incoming
                        for port_name in alternative
                    )
                ]
                complete_alternatives = [
                    alternative
                    for alternative in group.alternatives
                    if all(
                        (node.node_id, port_name) in incoming
                        for port_name in alternative
                    )
                ]
                group_ports = tuple(dict.fromkeys(
                    port_name
                    for alternative in group.alternatives
                    for port_name in alternative
                ))
                alternatives_description = " or ".join(
                    f"({', '.join(alternative)})"
                    for alternative in group.alternatives
                )
                if group.required and not complete_alternatives:
                    errors.append(WorkflowValidationError(
                        kind=(
                            WorkflowValidationErrorKind.REQUIRED_INPUT_GROUP_MISSING
                        ),
                        message=(
                            f"Input group '{group.name}' requires one complete "
                            f"alternative: {alternatives_description}"
                        ),
                        node_id=node.node_id,
                        module_id=node.module_id,
                        ports=group_ports,
                    ))
                elif (
                    len(connected_alternatives) > 1
                    and not group.allow_multiple
                ):
                    errors.append(WorkflowValidationError(
                        kind=(
                            WorkflowValidationErrorKind.CONFLICTING_INPUT_CONNECTIONS
                        ),
                        message=(
                            f"Input group '{group.name}' accepts only one "
                            f"alternative: {alternatives_description}"
                        ),
                        node_id=node.node_id,
                        module_id=node.module_id,
                        ports=group_ports,
                    ))
        return WorkflowValidationResult(tuple(errors))

    def validate_acyclic(self) -> list[str]:
        """Validate the graph is acyclic. Returns cycle node IDs if found."""
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            if edge.source_node_id in adjacency:
                adjacency[edge.source_node_id].append(edge.target_node_id)

        cycle_nodes: list[str] = []
        for start in self.nodes:
            pending = deque(adjacency[start])
            visited: set[str] = set()
            while pending:
                node_id = pending.popleft()
                if node_id == start:
                    cycle_nodes.append(start)
                    break
                if node_id in visited:
                    continue
                visited.add(node_id)
                pending.extend(adjacency.get(node_id, []))
        return cycle_nodes

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order. Raises ValueError on cycle."""
        cycle = self.validate_acyclic()
        if cycle:
            raise ValueError(
                f"Workflow contains a cycle involving nodes: {cycle}"
            )

        # Kahn's algorithm (repeat for the sorted order)
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for edge in self.edges:
            in_degree[edge.target_node_id] = in_degree.get(edge.target_node_id, 0) + 1

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        result: list[str] = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)
            for edge in self.edges:
                if edge.source_node_id == node_id:
                    target = edge.target_node_id
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        return result
