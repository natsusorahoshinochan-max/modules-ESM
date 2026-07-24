"""Serial execution engine for workflow DAGs."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from core.graph import NodeState, Workflow, WorkflowNode
from core.run_context import RunContext
from core.workflow_module import WorkflowModule


class Executor:
    """Serial executor for workflow DAGs.

    Executes nodes in topological order, one at a time.
    Passes upstream outputs to downstream nodes.
    Manages the node state machine: idle → queued → running → completed/failed/cancelled.
    Failed nodes block direct downstream nodes; unrelated branches continue.
    """

    def __init__(self) -> None:
        self._state_callbacks: list[Callable[[str, NodeState, NodeState], None]] = []

    def on_state_change(
        self, callback: Callable[[str, NodeState, NodeState], None]
    ) -> None:
        """Register a callback for node state changes.

        Callback receives (node_id, old_state, new_state).
        """
        self._state_callbacks.append(callback)

    def _set_node_state(self, node: WorkflowNode, new_state: NodeState) -> None:
        """Transition a node to a new state and notify callbacks."""
        old_state = node.state
        node.state = new_state
        for cb in self._state_callbacks:
            cb(node.node_id, old_state, new_state)

    async def execute(
        self,
        workflow: Workflow,
        modules: dict[str, WorkflowModule],
        project_dir: str,
        run_id: str,
        seed: int = 42,
    ) -> dict[str, dict[str, Any]]:
        """Execute a workflow and return all node outputs.

        Args:
            workflow: the workflow DAG to execute.
            modules: dict mapping module_id → WorkflowModule instance.
            project_dir: root directory for RunContext.
            run_id: unique identifier for this run.
            seed: random seed.

        Returns:
            dict mapping node_id → dict of output port → value.
        """
        order = workflow.topological_sort()

        # Reset all nodes to IDLE
        for node in workflow.nodes.values():
            node.reset()

        # Phase 1: mark all nodes as queued
        for node_id in order:
            node = workflow.nodes[node_id]
            self._set_node_state(node, NodeState.QUEUED)

        # Track which nodes have failed
        failed_nodes: set[str] = set()

        # Phase 2: execute in order
        for node_id in order:
            node = workflow.nodes[node_id]

            # Check if any upstream node failed → block this node
            upstream = workflow.get_upstream_nodes(node_id)
            if any(u in failed_nodes for u in upstream):
                self._set_node_state(node, NodeState.BLOCKED)
                failed_nodes.add(node_id)
                continue

            module = modules.get(node.module_id)
            if module is None:
                self._set_node_state(node, NodeState.FAILED)
                failed_nodes.add(node_id)
                continue

            self._set_node_state(node, NodeState.RUNNING)

            try:
                inputs = workflow.get_inputs_for_node(node_id)
                context = RunContext(
                    project_dir=project_dir,
                    node_id=node_id,
                    run_id=run_id,
                    seed=seed,
                )

                # Validate first (optional)
                issues = module.validate(inputs, node.parameters)
                if issues and any("error" in i.lower() for i in issues):
                    raise RuntimeError(f"Validation failed: {'; '.join(issues)}")

                outputs = module.run(inputs, node.parameters, context)

                # Store outputs
                node.outputs = outputs
                self._set_node_state(node, NodeState.COMPLETED)

            except asyncio.CancelledError:
                self._set_node_state(node, NodeState.CANCELLED)
                failed_nodes.add(node_id)
                # Mark remaining queued nodes as blocked
                for remaining_id in order[order.index(node_id) + 1:]:
                    remaining = workflow.nodes[remaining_id]
                    if remaining.state == NodeState.QUEUED:
                        self._set_node_state(remaining, NodeState.CANCELLED)
                raise

            except Exception:
                self._set_node_state(node, NodeState.FAILED)
                failed_nodes.add(node_id)
                # Block direct downstream nodes; unrelated branches continue
                for downstream_id in workflow.get_downstream_nodes(node_id):
                    downstream = workflow.nodes[downstream_id]
                    if downstream.state not in (NodeState.COMPLETED, NodeState.RUNNING):
                        self._set_node_state(downstream, NodeState.BLOCKED)
                        failed_nodes.add(downstream_id)

        # Return outputs for all completed nodes
        return {
            nid: node.outputs
            for nid, node in workflow.nodes.items()
            if node.state == NodeState.COMPLETED
        }
