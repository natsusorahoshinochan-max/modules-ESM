"""Serial execution engine for workflow DAGs."""

from __future__ import annotations

import asyncio
import hashlib
import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.graph import NodeState, Workflow, WorkflowNode
from core.run_context import RunContext
from core.workflow_module import WorkflowModule

if TYPE_CHECKING:
    from core.project import ProjectManager


class Executor:
    """Serial executor for workflow DAGs.

    Executes nodes in topological order, one at a time.
    Passes upstream outputs to downstream nodes.
    Manages the node state machine: idle -> queued -> running -> completed/failed/cancelled.
    Failed nodes block direct downstream nodes; unrelated branches continue.

    Content-addressed cache: before executing a node, the executor computes
    a cache key from (module_id, module_version, inputs, normalized_parameters, seed)
    and checks for a cached result. On hit, skips execution. On success,
    writes outputs to cache. Failed nodes are never cached.
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

    def _compute_cache_key(
        self,
        module_id: str,
        module_version: str,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        seed: int,
    ) -> str:
        """Compute a content-addressed cache key.

        The key is a hex digest of:
        module_id + module_version + input_hashes + normalized_parameters + seed.

        Inputs are hashed by their string representation. Parameters are
        sorted by key for deterministic hashing. Seed is included so
        different stochastic runs produce different cache entries.
        """
        hasher = hashlib.sha256()
        hasher.update(module_id.encode())
        hasher.update(module_version.encode())

        # Hash inputs by their repr
        for key in sorted(inputs.keys()):
            hasher.update(key.encode())
            val = inputs[key]
            hasher.update(repr(val).encode())

        # Hash parameters sorted by key
        for key in sorted(parameters.keys()):
            hasher.update(key.encode())
            hasher.update(repr(parameters[key]).encode())

        hasher.update(str(seed).encode())
        return hasher.hexdigest()[:32]

    def _get_cache_path(
        self, project_dir: str, node_id: str, cache_key: str
    ) -> Path:
        """Get the path to a cache file."""
        cache_dir = Path(project_dir) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{node_id}_{cache_key}.pkl"

    def _load_from_cache(self, cache_path: Path) -> dict[str, Any] | None:
        """Load cached outputs from a pickle file. Returns None on miss."""
        if not cache_path.exists():
            return None
        try:
            with open(cache_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None

    def _save_to_cache(self, cache_path: Path, outputs: dict[str, Any]) -> None:
        """Save outputs to a cache pickle file."""
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(outputs, f)
        except Exception:
            pass  # Cache write failure is non-fatal

    async def execute(
        self,
        workflow: Workflow,
        modules: dict[str, WorkflowModule],
        project_dir: str,
        run_id: str,
        seed: int = 42,
        force_rerun_nodes: set[str] | None = None,
        project_manager: ProjectManager | None = None,
        project_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Execute a workflow and return all node outputs.

        Args:
            workflow: the workflow DAG to execute.
            modules: dict mapping module_id -> WorkflowModule instance.
            project_dir: root directory for RunContext.
            run_id: unique identifier for this run.
            seed: random seed.
            force_rerun_nodes: optional set of node_ids to force re-run
                (skip cache lookup for these nodes).

        Returns:
            dict mapping node_id -> dict of output port -> value.
        """
        if force_rerun_nodes is None:
            force_rerun_nodes = set()

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

            # Check if any upstream node failed -> block this node
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
                if project_manager is not None and project_id is not None:
                    context = project_manager.run_context(
                        project_id,
                        run_id,
                        node_id,
                        seed=seed,
                    )
                else:
                    context = RunContext(
                        project_dir=project_dir,
                        node_id=node_id,
                        run_id=run_id,
                        seed=seed,
                    )

                # Check cache (skip if force re-run)
                cache_key = self._compute_cache_key(
                    node.module_id,
                    node.module_version,
                    inputs,
                    node.parameters,
                    seed,
                )
                if project_manager is not None and project_id is not None:
                    cache_path = project_manager.cache_path(
                        project_id,
                        node_id,
                        cache_key,
                    )
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                else:
                    cache_path = self._get_cache_path(
                        project_dir, node_id, cache_key
                    )

                if node_id not in force_rerun_nodes:
                    cached = self._load_from_cache(cache_path)
                    if cached is not None:
                        node.outputs = cached
                        self._set_node_state(node, NodeState.COMPLETED)
                        continue

                # Validate first (optional)
                issues = module.validate(inputs, node.parameters)
                if issues and any("error" in i.lower() for i in issues):
                    raise RuntimeError(f"Validation failed: {'; '.join(issues)}")

                outputs = await module.run_async(inputs, node.parameters, context)

                # Store outputs
                node.outputs = outputs

                # Save to cache on success
                self._save_to_cache(cache_path, outputs)

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
