"""Serial execution engine for workflow DAGs."""

from __future__ import annotations

import asyncio
import hashlib
import os
import pickle
import stat
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, Callable

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


class _SafeCacheUnpickler(pickle.Unpickler):
    """Deserialize only the workbench's inert data-transfer classes."""

    _DATATYPE_NAMES = {
        "Candidate",
        "CandidateCollection",
        "FunctionAnnotations",
        "ProteinMPNNConstraints",
        "ProteinPrompt",
        "ProteinSequence",
        "ProteinStructure",
        "ResidueLayout",
        "ResidueMap",
        "ResidueTrack",
        "Score",
        "ScoreCollection",
        "StructureAlignment",
    }

    def find_class(self, module: str, name: str) -> Any:
        if module == "datatypes.protein" and name in self._DATATYPE_NAMES:
            from datatypes import protein

            return getattr(protein, name)
        raise pickle.UnpicklingError(
            f"Cache global is not permitted: {module}.{name}"
        )


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

    def _set_node_state(
        self,
        node: WorkflowNode,
        new_state: NodeState,
        manifest_store: RunManifestStore | None = None,
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

        # Normalize nested parameter dictionaries recursively.
        hasher.update(canonical_json(parameters))

        hasher.update(str(seed).encode())
        return hasher.hexdigest()[:32]

    def _get_cache_path(
        self, project_dir: str, node_id: str, cache_key: str
    ) -> Path:
        """Get the path to a cache file."""
        cache_dir = (
            Path(project_dir)
            / "cache"
            / validate_identifier(node_id, "node_id")
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{validate_identifier(cache_key, 'cache_key')}.pkl"

    def _load_from_cache(self, cache_path: Path) -> dict[str, Any] | None:
        """Load cached outputs from a pickle file. Returns None on miss."""
        if not cache_path.exists():
            return None
        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(cache_path, flags)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return None
            with os.fdopen(descriptor, "rb", closefd=True) as cache_file:
                descriptor = None
                cached = _SafeCacheUnpickler(cache_file).load()
            return cached if isinstance(cached, dict) else None
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _require_complete_outputs(
        module: WorkflowModule,
        outputs: Any,
    ) -> dict[str, Any]:
        required = {
            port.name for port in module.definition.output_ports
        }
        supplied = set(outputs) if isinstance(outputs, dict) else set()
        missing = sorted(required - supplied)
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
        temporary_path: Path | None = None
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{cache_path.name}.",
                suffix=".tmp",
                dir=cache_path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                pickle.dump(outputs, temporary_file)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            try:
                os.link(temporary_path, cache_path)
            except FileExistsError:
                pass
        except Exception:
            return False  # Cache write failure is non-fatal
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return cache_path.is_file()

    @staticmethod
    def _has_artifact_reference(value: Any, key: str = "") -> bool:
        if isinstance(value, dict):
            return any(
                Executor._has_artifact_reference(child, str(child_key))
                for child_key, child in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(
                Executor._has_artifact_reference(child, key)
                for child in value
            )
        return (
            isinstance(value, (str, Path))
            and key in {
                "file_path",
                "artifact_path",
                "artifact_reference",
            }
        )

    @staticmethod
    def _record_output_facts(
        manifest_store: RunManifestStore,
        context: RunContext,
        node_id: str,
        outputs: dict[str, Any],
    ) -> None:
        from datatypes import Candidate, CandidateCollection

        def visit(value: Any, output_port: str, key: str = "") -> None:
            if isinstance(value, CandidateCollection):
                for candidate in value.items:
                    visit(candidate, output_port)
                return
            if isinstance(value, Candidate):
                manifest_store.record_candidate_lineage(
                    node_id=node_id,
                    output_port=output_port,
                    candidate_id=value.candidate_id,
                    parent_ids=value.parent_ids,
                )
                return
            if isinstance(value, dict):
                for child_key, child in value.items():
                    visit(child, output_port, str(child_key))
                return
            if isinstance(value, (list, tuple)):
                for child in value:
                    visit(child, output_port, key)
                return
            if (
                isinstance(value, (str, Path))
                and key in {
                    "file_path",
                    "artifact_path",
                    "artifact_reference",
                }
            ):
                context.record_artifact(value)

        for output_port, value in outputs.items():
            visit(value, output_port, output_port)

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
                        self._set_node_state(
                            node,
                            NodeState.BLOCKED,
                            manifest_store,
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
                        context._manifest_store = manifest_store

                        # Check cache (skip if force re-run)
                        cache_key = self._compute_cache_key(
                            node.module_id,
                            module.definition.version,
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
                            cache_existed = cache_path.exists()
                            cached = self._load_from_cache(cache_path)
                            if cache_existed and cached is None:
                                cache_path.unlink(missing_ok=True)
                            if (
                                cached is not None
                                and self._has_artifact_reference(cached)
                            ):
                                cache_path.unlink(missing_ok=True)
                                cached = None
                            if cached is not None:
                                try:
                                    cached = self._require_complete_outputs(
                                        module,
                                        cached,
                                    )
                                except IncompleteNodeOutputError:
                                    cache_path.unlink(missing_ok=True)
                                    cached = None
                            if cached is not None:
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
                                    cached,
                                )
                                self._set_node_state(
                                    node,
                                    NodeState.COMPLETED,
                                    manifest_store,
                                )
                                continue
                            manifest_store.record_cache(
                                node_id=node_id,
                                cache_key=cache_key,
                                outcome="miss",
                            )
                        else:
                            manifest_store.record_cache(
                                node_id=node_id,
                                cache_key=cache_key,
                                outcome="bypass",
                            )

                        # Validate first (optional)
                        issues = module.validate(inputs, node.parameters)
                        if issues and any("error" in i.lower() for i in issues):
                            raise RuntimeError(
                                f"Validation failed: {'; '.join(issues)}"
                            )

                        outputs = await module.run_async(
                            inputs,
                            node.parameters,
                            context,
                        )
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
                            outputs,
                        )

                        # Save to cache on success
                        if (
                            not self._has_artifact_reference(outputs)
                            and self._save_to_cache(cache_path, outputs)
                        ):
                            manifest_store.mark_cache_published(
                                node_id,
                                cache_key,
                            )

                        self._set_node_state(
                            node,
                            NodeState.COMPLETED,
                            manifest_store,
                        )

                    except asyncio.CancelledError:
                        self._set_node_state(
                            node,
                            NodeState.CANCELLED,
                            manifest_store,
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
                                )
                        raise

                    except Exception as error:
                        manifest_store.record_failure(
                            node_id=node_id,
                            kind=getattr(
                                error,
                                "kind",
                                type(error).__name__,
                            ),
                            message=str(error),
                        )
                        self._set_node_state(
                            node,
                            NodeState.FAILED,
                            manifest_store,
                        )
                        failed_nodes.add(node_id)
                        # Block direct downstream nodes; unrelated branches continue
                        for downstream_id in workflow.get_downstream_nodes(node_id):
                            downstream = workflow.nodes[downstream_id]
                            if downstream.state not in (
                                NodeState.COMPLETED,
                                NodeState.RUNNING,
                            ):
                                self._set_node_state(
                                    downstream,
                                    NodeState.BLOCKED,
                                    manifest_store,
                                )
                                failed_nodes.add(downstream_id)
            except asyncio.CancelledError:
                manifest_store.set_status("cancelled")
                raise
            except Exception:
                manifest_store.set_status("failed")
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

            # Return outputs for all completed nodes
            return {
                nid: node.outputs
                for nid, node in workflow.nodes.items()
                if node.state == NodeState.COMPLETED
            }
