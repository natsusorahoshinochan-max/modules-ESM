"""Serial execution engine for workflow DAGs."""

from __future__ import annotations

import asyncio
import hashlib
import pickle  # Compatibility seam for existing atomic-Cache tests.
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.cache_store import CachePublishStatus, CacheStore
from core.graph import NodeState, Workflow, WorkflowNode
from core.run_context import RunContext
from core.run_manifest import RunManifest, RunManifestStore, canonical_json
from core.storage import contained_path, validate_identifier
from core.workflow_module import WorkflowModule

if TYPE_CHECKING:
    from core.project import ProjectManager


class IncompleteNodeOutputError(RuntimeError):
    """A Module returned without satisfying its declared output Ports."""

    kind = "incomplete_node_output"


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
        self._lifecycle_callbacks: list[
            Callable[[str, str | None, dict[str, Any]], None]
        ] = []

    def on_state_change(
        self, callback: Callable[[str, NodeState, NodeState], None]
    ) -> None:
        """Register a callback for node state changes.

        Callback receives (node_id, old_state, new_state).
        """
        self._state_callbacks.append(callback)

    def on_lifecycle_event(
        self,
        callback: Callable[[str, str | None, dict[str, Any]], None],
    ) -> None:
        """Register an ordered observer for public run lifecycle facts."""
        self._lifecycle_callbacks.append(callback)

    def _emit_lifecycle(
        self,
        event_type: str,
        node_id: str | None = None,
        **details: Any,
    ) -> None:
        for callback in self._lifecycle_callbacks:
            try:
                callback(event_type, node_id, details)
            except Exception:
                continue

    def _set_node_state(
        self,
        node: WorkflowNode,
        new_state: NodeState,
        manifest_store: RunManifestStore | None = None,
        *,
        event_details: dict[str, Any] | None = None,
    ) -> None:
        """Transition a node to a new state and notify callbacks."""
        old_state = node.state
        node.state = new_state
        if manifest_store is not None:
            manifest_store.record_node_state(
                node.node_id,
                old_state.value,
                new_state.value,
            )
        for cb in self._state_callbacks:
            try:
                cb(node.node_id, old_state, new_state)
            except Exception:
                continue
        event_type = {
            NodeState.COMPLETED: "node_completed",
            NodeState.FAILED: "node_failed",
            NodeState.BLOCKED: "node_blocked",
            NodeState.CANCELLED: "node_cancelled",
        }.get(new_state, "node_state")
        self._emit_lifecycle(
            event_type,
            node.node_id,
            old_state=old_state.value,
            state=new_state.value,
            **(event_details or {}),
        )

    def _compute_cache_key(
        self,
        module_id: str,
        module_version: str,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        seed: int | None,
    ) -> str:
        """Compute a content-addressed cache key.

        The key is a hex digest of:
        module_id + module_version + input_hashes + normalized_parameters + seed.

        Inputs are hashed by their string representation. Parameters are
        sorted by key for deterministic hashing. Seed is included so
        different stochastic runs produce different cache entries.
        """
        input_hashes = {
            key: hashlib.sha256(repr(inputs[key]).encode()).hexdigest()
            for key in sorted(inputs)
        }
        identity = {
            "module_id": module_id,
            "module_version": module_version,
            "input_hashes": input_hashes,
            "parameters": parameters,
            "requested_seed": seed,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()[:32]

    def _get_cache_path(
        self, project_dir: str, node_id: str, cache_key: str
    ) -> Path:
        """Get the path to a cache file."""
        return self.cache_path(project_dir, node_id, cache_key)

    def cache_path(
        self,
        project_dir: str,
        node_id: str,
        cache_key: str,
    ) -> Path:
        """Return the public location of one direct-execution Cache entry."""
        with CacheStore(
            Path(project_dir) / "cache",
            node_id,
        ) as cache:
            return cache.path(cache_key)

    def _load_from_cache(self, cache_path: Path) -> dict[str, Any] | None:
        """Load cached outputs from a pickle file. Returns None on miss."""
        with CacheStore(
            cache_path.parents[1],
            cache_path.parent.name,
        ) as cache:
            return cache.load(cache_path.stem)

    @staticmethod
    def _require_complete_outputs(
        module: WorkflowModule,
        outputs: Any,
    ) -> dict[str, Any]:
        required = {
            port.name for port in module.definition.output_ports
        }
        supplied = set(outputs) if isinstance(outputs, dict) else set()
        missing = sorted(
            port
            for port in required
            if port not in supplied or outputs[port] is None
        )
        if not isinstance(outputs, dict) or missing:
            missing_description = ", ".join(missing or sorted(required))
            raise IncompleteNodeOutputError(
                f"Module '{module.definition.module_id}' did not produce "
                f"required output Ports: {missing_description}"
            )
        return outputs

    def _save_to_cache(
        self,
        cache_path: Path,
        outputs: dict[str, Any],
    ) -> bool:
        """Atomically publish one complete immutable cache entry."""
        with CacheStore(
            cache_path.parents[1],
            cache_path.parent.name,
        ) as cache:
            return (
                cache.save(cache_path.stem, outputs)
                != CachePublishStatus.FAILED
            )

    @staticmethod
    def _has_artifact_output(
        module: WorkflowModule,
        outputs: dict[str, Any],
    ) -> bool:
        artifact_ports = {
            port.name
            for port in module.definition.output_ports
            if port.type_id == "file.path"
        }
        return any(
            output_port in outputs
            for output_port in artifact_ports
        )

    @staticmethod
    def _record_output_facts(
        manifest_store: RunManifestStore,
        context: RunContext,
        node_id: str,
        module: WorkflowModule,
        outputs: dict[str, Any],
    ) -> None:
        port_types = {
            port.name: port.type_id
            for port in module.definition.output_ports
        }
        for output_port, value in outputs.items():
            describe = getattr(value, "manifest_facts", None)
            if callable(describe):
                for fact in describe():
                    if fact.get("kind") != "candidate_lineage":
                        continue
                    candidate_id = fact.get("candidate_id")
                    parent_ids = fact.get("parent_ids")
                    if (
                        not isinstance(candidate_id, str)
                        or not isinstance(parent_ids, list)
                        or not all(
                            isinstance(parent_id, str)
                            for parent_id in parent_ids
                        )
                    ):
                        continue
                    manifest_store.record_candidate_lineage(
                        node_id=node_id,
                        output_port=output_port,
                        candidate_id=candidate_id,
                        parent_ids=parent_ids,
                    )
            if (
                isinstance(value, (str, Path))
                and port_types.get(output_port) == "file.path"
            ):
                context.record_artifact(value)

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
        source_dir: str | Path | None = None,
        environment: dict[str, Any] | None = None,
        provider_readiness: dict[str, Any] | None = None,
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
        effective_project_id = project_id or Path(project_dir).resolve().name
        if project_manager is not None and project_id is not None:
            run_dir = project_manager.run_dir(project_id, run_id)
        else:
            run_dir = contained_path(
                project_dir,
                "runs",
                validate_identifier(run_id, "run_id"),
            )
        manifest = RunManifest.for_execution(
            project_id=effective_project_id,
            run_id=run_id,
            workflow=workflow,
            modules=modules,
            seed=seed,
            source_dir=source_dir or Path.cwd(),
            environment=environment,
        )

        with RunManifestStore(run_dir, manifest) as manifest_store:
            for provider, readiness in sorted(
                (provider_readiness or {}).items()
            ):
                if isinstance(readiness, dict):
                    details = dict(readiness)
                    ready = bool(details.pop("ready", False))
                else:
                    ready = bool(readiness)
                    details = {}
                manifest_store.record_provider_readiness(
                    provider=provider,
                    ready=ready,
                    details=details,
                )
            manifest_store.set_status("running")
            self._emit_lifecycle(
                "run_started",
                status="running",
                node_order=order,
            )

            # Reset all nodes to IDLE
            for node in workflow.nodes.values():
                node.reset()

            # Phase 1: mark all nodes as queued
            for node_id in order:
                node = workflow.nodes[node_id]
                self._set_node_state(
                    node,
                    NodeState.QUEUED,
                    manifest_store,
                )

            # Track which nodes have failed
            failed_nodes: set[str] = set()

            try:
                # Phase 2: execute in order
                for node_id in order:
                    node = workflow.nodes[node_id]

                    # Check if any upstream node failed -> block this node
                    upstream = workflow.get_upstream_nodes(node_id)
                    if any(u in failed_nodes for u in upstream):
                        blocking_upstream = sorted(
                            upstream_node_id
                            for upstream_node_id in upstream
                            if upstream_node_id in failed_nodes
                        )
                        reason = manifest_store.record_blocked(
                            node_id=node_id,
                            upstream_node_ids=blocking_upstream,
                        )
                        self._set_node_state(
                            node,
                            NodeState.BLOCKED,
                            manifest_store,
                            event_details={"reason": reason},
                        )
                        failed_nodes.add(node_id)
                        continue

                    module = modules.get(node.module_id)
                    if module is None:
                        manifest_store.record_failure(
                            node_id=node_id,
                            kind="module_unavailable",
                            message=(
                                f"Module '{node.module_id}' is not available"
                            ),
                        )
                        self._set_node_state(
                            node,
                            NodeState.FAILED,
                            manifest_store,
                        )
                        failed_nodes.add(node_id)
                        continue

                    self._set_node_state(
                        node,
                        NodeState.RUNNING,
                        manifest_store,
                    )

                    try:
                        cache_outcome = "bypass"
                        inputs = workflow.get_inputs_for_node(node_id)
                        configured_seed = node.parameters.get("seed")
                        effective_seed = (
                            seed
                            if configured_seed is None
                            else configured_seed
                        )
                        if project_manager is not None and project_id is not None:
                            context = project_manager.run_context(
                                project_id,
                                run_id,
                                node_id,
                                seed=effective_seed,
                            )
                        else:
                            context = RunContext(
                                project_dir=project_dir,
                                node_id=node_id,
                                run_id=run_id,
                                seed=effective_seed,
                            )
                        context._manifest_store = manifest_store

                        # Check cache (skip if force re-run)
                        cache_key = self._compute_cache_key(
                            node.module_id,
                            module.definition.version,
                            inputs,
                            node.parameters,
                            effective_seed,
                        )
                        if project_manager is not None and project_id is not None:
                            cache_root = project_manager.cache_dir(project_id)
                        else:
                            cache_root = Path(project_dir) / "cache"
                        output_ports = [
                            {"name": port.name, "type_id": port.type_id}
                            for port in module.definition.output_ports
                        ]
                        with CacheStore(cache_root, node_id) as cache_store:
                            if node_id not in force_rerun_nodes:
                                cached = cache_store.load(
                                    cache_key,
                                    module_id=node.module_id,
                                    module_version=module.definition.version,
                                    output_ports=output_ports,
                                )
                                if (
                                    cached is not None
                                    and self._has_artifact_output(
                                        module,
                                        cached,
                                    )
                                ):
                                    cache_store.remove(cache_key)
                                    cached = None
                                if cached is not None:
                                    try:
                                        cached = self._require_complete_outputs(
                                            module,
                                            cached,
                                        )
                                    except IncompleteNodeOutputError:
                                        cache_store.remove(cache_key)
                                        cached = None
                                if cached is not None:
                                    cache_outcome = "hit"
                                    manifest_store.record_cache(
                                        node_id=node_id,
                                        cache_key=cache_key,
                                        outcome="hit",
                                    )
                                    node.outputs = cached
                                    self._record_output_facts(
                                        manifest_store,
                                        context,
                                        node_id,
                                        module,
                                        cached,
                                    )
                                    self._set_node_state(
                                        node,
                                        NodeState.COMPLETED,
                                        manifest_store,
                                        event_details={
                                            "cache": {"outcome": "hit"}
                                        },
                                    )
                                    continue
                                cache_store.remove(cache_key)
                                cache_outcome = "miss"
                                manifest_store.record_cache(
                                    node_id=node_id,
                                    cache_key=cache_key,
                                    outcome="miss",
                                )
                            else:
                                cache_outcome = "bypass"
                                manifest_store.record_cache(
                                    node_id=node_id,
                                    cache_key=cache_key,
                                    outcome="bypass",
                                )

                            # Validate first (optional)
                            issues = module.validate(inputs, node.parameters)
                            if issues and any(
                                "error" in issue.lower()
                                for issue in issues
                            ):
                                raise RuntimeError(
                                    "Node validation failed"
                                )

                            context_token = context.activate()
                            try:
                                outputs = await module.run_async(
                                    inputs,
                                    node.parameters,
                                    context,
                                )
                            finally:
                                context.deactivate(context_token)
                            outputs = self._require_complete_outputs(
                                module,
                                outputs,
                            )

                            # Store outputs
                            node.outputs = outputs
                            self._record_output_facts(
                                manifest_store,
                                context,
                                node_id,
                                module,
                                outputs,
                            )

                            # Save to cache on success
                            if (
                                not self._has_artifact_output(module, outputs)
                                and cache_store.save(
                                    cache_key,
                                    outputs,
                                    module_id=node.module_id,
                                    module_version=(
                                        module.definition.version
                                    ),
                                    output_ports=output_ports,
                                )
                                == CachePublishStatus.CREATED
                            ):
                                manifest_store.mark_cache_published(
                                    node_id,
                                    cache_key,
                                )

                        self._set_node_state(
                            node,
                            NodeState.COMPLETED,
                            manifest_store,
                            event_details={
                                "cache": {"outcome": cache_outcome}
                            },
                        )

                    except asyncio.CancelledError:
                        self._set_node_state(
                            node,
                            NodeState.CANCELLED,
                            manifest_store,
                            event_details={
                                "reason": {
                                    "kind": "cancellation_requested",
                                    "message": "Run cancellation was requested",
                                }
                            },
                        )
                        failed_nodes.add(node_id)
                        # Mark remaining queued nodes as blocked
                        for remaining_id in order[order.index(node_id) + 1:]:
                            remaining = workflow.nodes[remaining_id]
                            if remaining.state == NodeState.QUEUED:
                                self._set_node_state(
                                    remaining,
                                    NodeState.CANCELLED,
                                    manifest_store,
                                    event_details={
                                        "reason": {
                                            "kind": "run_cancelled",
                                            "message": (
                                                "Run ended before Node execution"
                                            ),
                                        }
                                    },
                                )
                        raise

                    except Exception as error:
                        kind = getattr(
                            error,
                            "kind",
                            type(error).__name__,
                        )
                        message = (
                            str(error)
                            if isinstance(error, IncompleteNodeOutputError)
                            else f"Node execution failed ({kind})"
                        )
                        manifest_store.record_failure(
                            node_id=node_id,
                            kind=kind,
                            message=message,
                        )
                        self._set_node_state(
                            node,
                            NodeState.FAILED,
                            manifest_store,
                            event_details={
                                "diagnostic": {
                                    "kind": kind,
                                    "message": message,
                                    "module_id": node.module_id,
                                    "retryable": False,
                                }
                            },
                        )
                        failed_nodes.add(node_id)
            except asyncio.CancelledError:
                manifest_store.set_status("cancelled")
                self._emit_lifecycle("run_cancelled", status="cancelled")
                raise
            except Exception:
                manifest_store.set_status("failed")
                self._emit_lifecycle(
                    "run_failed",
                    status="failed",
                    diagnostic={
                        "kind": "run_execution_error",
                        "message": "Run execution failed",
                        "retryable": False,
                    },
                )
                raise
            else:
                terminal_status = (
                    "completed"
                    if all(
                        node.state == NodeState.COMPLETED
                        for node in workflow.nodes.values()
                    )
                    else "failed"
                )
                manifest_store.set_status(terminal_status)
                self._emit_lifecycle(
                    (
                        "run_completed"
                        if terminal_status == "completed"
                        else "run_failed"
                    ),
                    status=terminal_status,
                )

            # Return outputs for all completed nodes
            return {
                nid: node.outputs
                for nid, node in workflow.nodes.items()
                if node.state == NodeState.COMPLETED
            }
