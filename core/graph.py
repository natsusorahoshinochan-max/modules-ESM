"""Workflow DAG model: nodes, edges, validation, and topological sort."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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

    def validate_acyclic(self) -> list[str]:
        """Validate the graph is acyclic. Returns cycle node IDs if found."""
        # Kahn's algorithm
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for edge in self.edges:
            in_degree[edge.target_node_id] = in_degree.get(edge.target_node_id, 0) + 1

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        sorted_nodes: list[str] = []

        while queue:
            node_id = queue.popleft()
            sorted_nodes.append(node_id)
            for edge in self.edges:
                if edge.source_node_id == node_id:
                    target = edge.target_node_id
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        if len(sorted_nodes) != len(self.nodes):
            # Return nodes involved in cycle
            cycle_nodes = [
                nid for nid, deg in in_degree.items() if deg > 0
            ]
            return cycle_nodes

        return []

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
