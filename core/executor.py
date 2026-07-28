"""Serial execution engine for workflow DAGs."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace
import hashlib
import multiprocessing
import os
import pickle  # Compatibility seam for existing atomic-Cache tests.
from pathlib import Path
import signal
import time
from typing import TYPE_CHECKING, Any, Callable

from core.cache_store import CachePublishStatus, CacheStore
from core.graph import NodeState, Workflow, WorkflowNode
from core.lifecycle_events import RunEventType
from core.process_control import signal_process_group
from core.recovery_types import RecoveryProvenance
from core.run_context import RunContext
from core.run_manifest import RunManifest, RunManifestStore, canonical_json
from core.storage import (
    contained_path,
    remove_private_regular_file,
    validate_identifier,
    validate_relative_path,
)
from core.workflow_module import WorkflowModule

if TYPE_CHECKING:
    from core.project import ProjectManager


class IncompleteNodeOutputError(RuntimeError):
    """A Module returned without satisfying its declared output Ports."""

    kind = "incomplete_node_output"


class CancellationTimeoutError(RuntimeError):
    """Cancellation could not stop active Module work within the safe timeout."""

    kind = "cancellation_timeout"

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        super().__init__(
            "Active Module work did not stop before cancellation timeout"
        )


class _ProcessCancellationTimeout(RuntimeError):
    """A worker process required forceful termination after cancellation."""


class _ProcessModuleError(RuntimeError):
    """A safe local representation of a Module failure in a worker process."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Module worker failed ({kind})")


@dataclass(frozen=True)
class _ManifestWorkerMessage:
    method: str
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class _ResultWorkerMessage:
    outputs: dict[str, Any]


@dataclass(frozen=True)
class _CancelledWorkerMessage:
    pass


@dataclass(frozen=True)
class _ErrorWorkerMessage:
    kind: str


_TerminalWorkerMessage = (
    _ResultWorkerMessage
    | _CancelledWorkerMessage
    | _ErrorWorkerMessage
)
_WORKER_EXIT_TIMEOUT_SECONDS = 1.0


class _ManifestProcessProxy:
    """Forward child-process RunContext facts to the parent manifest owner."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        self._connection.send(_ManifestWorkerMessage(method, kwargs))

    def record_provider_readiness(self, **kwargs: Any) -> None:
        self._record("record_provider_readiness", kwargs)

    def record_provider_call(self, **kwargs: Any) -> None:
        self._record("record_provider_call", kwargs)

    def record_artifact(self, **kwargs: Any) -> bool:
        self._record("record_artifact", kwargs)
        return True

    def record_artifacts(self, **kwargs: Any) -> bool:
        self._record("record_artifacts", kwargs)
        return True


async def _run_module_worker(
    module: WorkflowModule,
    inputs: dict[str, Any],
    parameters: dict[str, Any],
    context: RunContext,
    cancellation_connection: Any,
) -> dict[str, Any]:
    async def wait_for_cancellation() -> None:
        while not cancellation_connection.poll():
            await asyncio.sleep(0.01)

    work = asyncio.create_task(
        module.run_async(inputs, parameters, context)
    )
    cancellation_waiter = asyncio.create_task(
        wait_for_cancellation()
    )
    try:
        done, _ = await asyncio.wait(
            {work, cancellation_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if work in done and not cancellation_connection.poll():
            return await work
        work.cancel()
        return await work
    finally:
        cancellation_waiter.cancel()
        with suppress(asyncio.CancelledError):
            await cancellation_waiter


def _module_process_entry(
    module: WorkflowModule,
    inputs: dict[str, Any],
    parameters: dict[str, Any],
    context: RunContext,
    cancellation_connection: Any,
    connection: Any,
) -> None:
    from core.process_control import enter_module_worker_process_group

    with suppress(OSError):
        enter_module_worker_process_group()
    try:
        child_context = replace(
            context,
            _manifest_store=_ManifestProcessProxy(connection),
        )
        token = child_context.activate()
        try:
            outputs = asyncio.run(_run_module_worker(
                module,
                inputs,
                parameters,
                child_context,
                cancellation_connection,
            ))
        except asyncio.CancelledError:
            with suppress(BrokenPipeError, EOFError, OSError):
                connection.send(_CancelledWorkerMessage())
        except BaseException as error:
            kind = str(getattr(error, "kind", type(error).__name__))
            with suppress(BrokenPipeError, EOFError, OSError):
                connection.send(_ErrorWorkerMessage(kind))
        else:
            try:
                connection.send(_ResultWorkerMessage(outputs))
            except BaseException as error:
                kind = f"result_serialization_{type(error).__name__}"
                with suppress(BrokenPipeError, EOFError, OSError):
                    connection.send(_ErrorWorkerMessage(kind))
        finally:
            child_context.deactivate(token)
    finally:
        cancellation_connection.close()
        connection.close()


def _receive_module_process(
    connection: Any,
) -> tuple[list[_ManifestWorkerMessage], _TerminalWorkerMessage]:
    manifest_events: list[_ManifestWorkerMessage] = []
    while True:
        try:
            message = connection.recv()
        except (EOFError, OSError):
            return manifest_events, _ErrorWorkerMessage(
                "worker_channel_closed"
            )
        if isinstance(message, _ManifestWorkerMessage):
            manifest_events.append(message)
            continue
        if isinstance(
            message,
            (
                _ResultWorkerMessage,
                _CancelledWorkerMessage,
                _ErrorWorkerMessage,
            ),
        ):
            return manifest_events, message
        return manifest_events, _ErrorWorkerMessage(
            "invalid_worker_message"
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
        self._lifecycle_callbacks: list[
            Callable[[RunEventType, str | None, dict[str, Any]], None]
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
        callback: Callable[
            [RunEventType, str | None, dict[str, Any]],
            None,
        ],
    ) -> None:
        """Register an ordered observer for public run lifecycle facts."""
        self._lifecycle_callbacks.append(callback)

    def _emit_lifecycle(
        self,
        event_type: RunEventType,
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
            NodeState.COMPLETED: RunEventType.NODE_COMPLETED,
            NodeState.FAILED: RunEventType.NODE_FAILED,
            NodeState.BLOCKED: RunEventType.NODE_BLOCKED,
            NodeState.CANCELLED: RunEventType.NODE_CANCELLED,
        }.get(new_state, RunEventType.NODE_STATE)
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
        grouped = {
            port_name
            for group in module.definition.output_groups
            for alternative in group.alternatives
            for port_name in alternative
        }
        required = {
            port.name
            for port in module.definition.output_ports
            if port.required and port.name not in grouped
        }
        if isinstance(outputs, dict):
            present = {
                port_name
                for port_name, value in outputs.items()
                if value is not None
            }
        else:
            present = set()
        missing = sorted(
            port
            for port in required
            if port not in present
        )
        incomplete_groups = []
        for group in module.definition.output_groups:
            complete_alternatives = [
                alternative
                for alternative in group.alternatives
                if all(port_name in present for port_name in alternative)
            ]
            group_ports = {
                port_name
                for alternative in group.alternatives
                for port_name in alternative
            }
            completed_ports = {
                port_name
                for alternative in complete_alternatives
                for port_name in alternative
            }
            has_partial_alternative = bool(
                (present & group_ports) - completed_ports
            )
            if (
                len(complete_alternatives) != 1
                or has_partial_alternative
            ):
                alternatives = " or ".join(
                    f"({', '.join(alternative)})"
                    for alternative in group.alternatives
                )
                incomplete_groups.append(
                    f"{group.name}: {alternatives}"
                )
        if (
            not isinstance(outputs, dict)
            or missing
            or incomplete_groups
        ):
            problems = list(missing)
            problems.extend(incomplete_groups)
            missing_description = ", ".join(
                problems or sorted(required)
            )
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
            if port.type_id in {"file.path", "file.path.collection"}
        }
        return any(
            output_port in outputs
            for output_port in artifact_ports
        )

    @staticmethod
    def _artifact_location(
        context: RunContext,
        artifact: str | Path,
    ) -> tuple[Path, tuple[str, ...], str]:
        output_root = Path(context.output_dir or "").absolute()
        supplied = Path(artifact)
        candidate = Path(os.path.abspath(
            supplied if supplied.is_absolute() else output_root / supplied
        ))
        reference = candidate.relative_to(output_root).as_posix()
        relative_parts = validate_relative_path(
            reference,
            "artifact_path",
        )
        return output_root, relative_parts, reference

    @staticmethod
    def _remove_unpublished_artifact(
        context: RunContext,
        artifact: str | Path,
    ) -> None:
        output_root, relative_parts, _ = Executor._artifact_location(
            context,
            artifact,
        )
        remove_private_regular_file(
            output_root,
            relative_parts,
            field="artifact_path",
        )

    @staticmethod
    def _publish_file_artifact(
        manifest_store: RunManifestStore,
        context: RunContext,
        node_id: str,
        artifact: str | Path,
        *,
        output_port: str,
        candidate_id: str | None,
        artifact_kind: str | None,
    ) -> None:
        _, _, reference = Executor._artifact_location(context, artifact)
        was_declared = any(
            current.get("reference") == reference
            for current in manifest_store.manifest.artifacts
        )
        try:
            if not manifest_store.record_artifact(
                node_id=node_id,
                path=artifact,
                output_dir=context.output_dir or "",
                candidate_id=candidate_id,
                output_port=output_port,
                artifact_kind=artifact_kind,
            ):
                raise RuntimeError(
                    "Artifact output could not be recorded"
                )
        except Exception:
            if not was_declared:
                with suppress(Exception):
                    Executor._remove_unpublished_artifact(
                        context,
                        artifact,
                    )
            raise

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
        artifact_kinds = {
            port.name: port.artifact_kind
            for port in module.definition.output_ports
        }
        candidate_bindings = Executor._record_domain_output_facts(
            manifest_store,
            node_id,
            outputs,
            port_types,
        )
        artifact_binding = (
            candidate_bindings[0]
            if len(candidate_bindings) == 1
            else None
        )
        for output_port, value in outputs.items():
            if (
                not isinstance(value, (str, Path))
                or port_types.get(output_port) != "file.path"
            ):
                continue
            if artifact_kinds.get(output_port) == "standalone":
                candidate_port, candidate_id = output_port, None
                artifact_kind = "standalone"
            elif artifact_binding is not None:
                candidate_port, candidate_id = artifact_binding
                artifact_kind = None
            else:
                continue
            Executor._publish_file_artifact(
                manifest_store,
                context,
                node_id,
                value,
                output_port=candidate_port,
                candidate_id=candidate_id,
                artifact_kind=artifact_kind,
            )

    @staticmethod
    def _record_domain_output_facts(
        manifest_store: RunManifestStore,
        node_id: str,
        outputs: dict[str, Any],
        port_types: dict[str, str],
    ) -> list[tuple[str, str]]:
        candidate_bindings: list[tuple[str, str]] = []
        for output_port, value in outputs.items():
            describe = getattr(value, "manifest_facts", None)
            if not callable(describe):
                continue
            facts = describe()
            if port_types.get(output_port) == "score.collection":
                manifest_store.record_scores(
                    node_id=node_id,
                    output_port=output_port,
                    facts=facts,
                )
                continue
            for fact in facts:
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
                candidate_bindings.append((output_port, candidate_id))
        return candidate_bindings

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
        recovery: RecoveryProvenance | None = None,
        cancellation_requested: asyncio.Event | None = None,
        cancellation_timeout: float = 5.0,
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
        started_monotonic = time.monotonic()
        cancellation_observed = False

        def elapsed_ms() -> int:
            return max(
                0,
                int((time.monotonic() - started_monotonic) * 1000),
            )

        def observe_cancellation(
            manifest_store: RunManifestStore,
        ) -> None:
            nonlocal cancellation_observed
            if cancellation_observed:
                return
            manifest_store.set_status("cancellation_requested")
            self._emit_lifecycle(
                RunEventType.RUN_CANCELLATION_REQUESTED,
                status="cancellation_requested",
            )
            cancellation_observed = True

        async def run_module_process(
            module: WorkflowModule,
            inputs: dict[str, Any],
            parameters: dict[str, Any],
            context: RunContext,
            manifest_store: RunManifestStore,
        ) -> dict[str, Any]:
            process_context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = process_context.Pipe(
                duplex=False
            )
            cancellation_connection = None
            cancellation_sender = None
            process = None
            try:
                cancellation_connection, cancellation_sender = (
                    process_context.Pipe(duplex=False)
                )
                process = process_context.Process(
                    target=_module_process_entry,
                    args=(
                        module,
                        inputs,
                        parameters,
                        replace(context, _manifest_store=None),
                        cancellation_connection,
                        child_connection,
                    ),
                )
                process.start()
            except BaseException:
                parent_connection.close()
                child_connection.close()
                if cancellation_connection is not None:
                    cancellation_connection.close()
                if cancellation_sender is not None:
                    cancellation_sender.close()
                if process is not None:
                    process.close()
                raise
            assert cancellation_connection is not None
            assert cancellation_sender is not None
            assert process is not None
            child_connection.close()
            cancellation_connection.close()
            receiver = asyncio.create_task(
                asyncio.to_thread(
                    _receive_module_process,
                    parent_connection,
                )
            )
            manifest_events: list[_ManifestWorkerMessage] = []

            def apply_manifest_events() -> None:
                def record_worker_artifacts(**kwargs: Any) -> None:
                    output_root = Path(kwargs["output_dir"]).absolute()

                    def rollback() -> None:
                        for artifact in reversed(kwargs["artifacts"]):
                            supplied = Path(artifact["path"])
                            candidate = Path(os.path.abspath(
                                supplied
                                if supplied.is_absolute()
                                else output_root / supplied
                            ))
                            try:
                                reference = candidate.relative_to(
                                    output_root
                                ).as_posix()
                            except ValueError:
                                continue
                            remove_private_regular_file(
                                output_root,
                                validate_relative_path(
                                    reference,
                                    "artifact_path",
                                ),
                                field="artifact_path",
                            )

                    try:
                        recorded = manifest_store.record_artifacts(**kwargs)
                        if not recorded:
                            raise RuntimeError(
                                "Worker artifact batch was incomplete"
                            )
                    except Exception:
                        rollback()
                        raise

                handlers = {
                    "record_provider_readiness": (
                        manifest_store.record_provider_readiness
                    ),
                    "record_provider_call": (
                        manifest_store.record_provider_call
                    ),
                    "record_artifact": manifest_store.record_artifact,
                    "record_artifacts": record_worker_artifacts,
                }
                for event in manifest_events:
                    handler = handlers.get(event.method)
                    if handler is not None:
                        handler(**event.kwargs)

            def kill_worker_group() -> None:
                fallback = process.kill if process.is_alive() else None
                signal_process_group(
                    process.pid,
                    signal.SIGKILL,
                    fallback=fallback,
                )

            try:
                manifest_events, outcome = await asyncio.shield(receiver)
                await asyncio.to_thread(
                    process.join,
                    _WORKER_EXIT_TIMEOUT_SECONDS,
                )
                kill_worker_group()
                if process.is_alive():
                    await asyncio.to_thread(
                        process.join,
                        _WORKER_EXIT_TIMEOUT_SECONDS,
                    )
            except asyncio.CancelledError:
                with suppress(BrokenPipeError, EOFError, OSError):
                    cancellation_sender.send_bytes(b"\0")
                await asyncio.to_thread(
                    process.join,
                    cancellation_timeout,
                )
                timed_out = process.is_alive()
                kill_worker_group()
                if process.is_alive():
                    await asyncio.to_thread(
                        process.join,
                        _WORKER_EXIT_TIMEOUT_SECONDS,
                    )
                try:
                    manifest_events, _ = await asyncio.wait_for(
                        asyncio.shield(receiver),
                        timeout=_WORKER_EXIT_TIMEOUT_SECONDS,
                    )
                except Exception:
                    pass
                apply_manifest_events()
                if timed_out:
                    raise _ProcessCancellationTimeout from None
                raise
            finally:
                parent_connection.close()
                cancellation_sender.close()
                if not receiver.done():
                    receiver.cancel()
                if not process.is_alive():
                    process.close()

            apply_manifest_events()
            if isinstance(outcome, _ResultWorkerMessage):
                return outcome.outputs
            if isinstance(outcome, _CancelledWorkerMessage):
                raise asyncio.CancelledError
            raise _ProcessModuleError(outcome.kind)

        async def run_module(
            module: WorkflowModule,
            inputs: dict[str, Any],
            parameters: dict[str, Any],
            context: RunContext,
            manifest_store: RunManifestStore,
        ) -> dict[str, Any]:
            if cancellation_requested is None:
                return await module.run_async(
                    inputs,
                    parameters,
                    context,
                )
            work = asyncio.create_task(run_module_process(
                module,
                inputs,
                parameters,
                context,
                manifest_store,
            ))

            request_waiter = asyncio.create_task(
                cancellation_requested.wait()
            )
            try:
                done, _ = await asyncio.wait(
                    {work, request_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if (
                    work in done
                    and not cancellation_requested.is_set()
                ):
                    return await work

                work.cancel()
                observation_error: Exception | None = None
                try:
                    observe_cancellation(manifest_store)
                except Exception as error:
                    observation_error = error
                stopped, _ = await asyncio.wait(
                    {work},
                    timeout=cancellation_timeout + 2,
                )
                if not stopped:
                    work.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await work
                    raise CancellationTimeoutError(cancellation_timeout)
                try:
                    await work
                except _ProcessCancellationTimeout:
                    raise CancellationTimeoutError(
                        cancellation_timeout
                    ) from None
                except (asyncio.CancelledError, Exception):
                    pass
                if observation_error is not None:
                    raise observation_error
                raise asyncio.CancelledError
            except asyncio.CancelledError:
                if not work.done():
                    work.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.shield(work)
                raise
            finally:
                request_waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await request_waiter

        order = workflow.topological_sort()

        def cancel_queued_nodes(
            node_ids: list[str],
            manifest_store: RunManifestStore,
        ) -> None:
            for queued_node_id in node_ids:
                queued_node = workflow.nodes[queued_node_id]
                if queued_node.state == NodeState.QUEUED:
                    self._set_node_state(
                        queued_node,
                        NodeState.CANCELLED,
                        manifest_store,
                        event_details={
                            "reason": {
                                "kind": "run_cancelled",
                                "message": "Run ended before Node execution",
                            }
                        },
                    )

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
            recovery=recovery,
        )

        with RunManifestStore(run_dir, manifest) as manifest_store:
            try:
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
                    RunEventType.RUN_STARTED,
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
            except Exception:
                try:
                    manifest_store.set_status("failed")
                except Exception:
                    pass
                self._emit_lifecycle(
                    RunEventType.RUN_FAILED,
                    status="failed",
                    duration_ms=elapsed_ms(),
                    error={
                        "kind": "run_setup_error",
                        "message": "Run setup failed",
                        "retryable": False,
                    },
                )
                raise

            # Track Nodes that prevent dependent execution.
            blocking_nodes: set[str] = set()

            try:
                # Phase 2: execute in order
                for node_index, node_id in enumerate(order):
                    node = workflow.nodes[node_id]
                    if (
                        cancellation_requested is not None
                        and cancellation_requested.is_set()
                    ):
                        observe_cancellation(manifest_store)
                        cancel_queued_nodes(
                            order[node_index:],
                            manifest_store,
                        )
                        raise asyncio.CancelledError

                    # Check if any upstream node failed -> block this node
                    upstream = workflow.get_upstream_nodes(node_id)
                    if any(u in blocking_nodes for u in upstream):
                        blocking_upstream = sorted(
                            upstream_node_id
                            for upstream_node_id in upstream
                            if upstream_node_id in blocking_nodes
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
                        blocking_nodes.add(node_id)
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
                            event_details={
                                "error": {
                                    "kind": "module_unavailable",
                                    "message": (
                                        f"Module '{node.module_id}' is not "
                                        "available"
                                    ),
                                    "module_id": node.module_id,
                                    "retryable": False,
                                }
                            },
                        )
                        blocking_nodes.add(node_id)
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
                                            "output_summary": {
                                                "output_ports": sorted(cached),
                                                "cache": {"outcome": "hit"},
                                            }
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
                                outputs = await run_module(
                                    module,
                                    inputs,
                                    node.parameters,
                                    context,
                                    manifest_store,
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
                                "output_summary": {
                                    "output_ports": sorted(node.outputs),
                                    "cache": {
                                        "outcome": cache_outcome
                                    },
                                }
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
                        blocking_nodes.add(node_id)
                        # Mark remaining queued nodes as blocked
                        cancel_queued_nodes(
                            order[node_index + 1:],
                            manifest_store,
                        )
                        raise

                    except CancellationTimeoutError as error:
                        manifest_store.record_failure(
                            node_id=node_id,
                            kind=error.kind,
                            message=(
                                "Active Module work did not stop before "
                                "cancellation timeout"
                            ),
                        )
                        self._set_node_state(
                            node,
                            NodeState.FAILED,
                            manifest_store,
                            event_details={
                                "error": {
                                    "kind": error.kind,
                                    "message": (
                                        "Active Module work did not stop before "
                                        "cancellation timeout"
                                    ),
                                    "timeout_ms": int(
                                        error.timeout * 1000
                                    ),
                                    "module_id": node.module_id,
                                    "retryable": False,
                                }
                            },
                        )
                        cancel_queued_nodes(
                            order[node_index + 1:],
                            manifest_store,
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
                                "error": {
                                    "kind": kind,
                                    "message": message,
                                    "module_id": node.module_id,
                                    "retryable": False,
                                }
                            },
                        )
                        blocking_nodes.add(node_id)
            except CancellationTimeoutError as error:
                try:
                    manifest_store.set_status("failed")
                except Exception:
                    pass
                self._emit_lifecycle(
                    RunEventType.RUN_FAILED,
                    status="failed",
                    duration_ms=elapsed_ms(),
                    error={
                        "kind": error.kind,
                        "message": (
                            "Active Module work did not stop before "
                            "cancellation timeout"
                        ),
                        "timeout_ms": int(error.timeout * 1000),
                        "retryable": False,
                    },
                )
                raise
            except asyncio.CancelledError:
                try:
                    manifest_store.set_status("cancelled")
                except Exception:
                    try:
                        manifest_store.set_status("failed")
                    except Exception:
                        pass
                    self._emit_lifecycle(
                        RunEventType.RUN_FAILED,
                        status="failed",
                        duration_ms=elapsed_ms(),
                        error={
                            "kind": "terminal_persistence_error",
                            "message": "Run terminal state could not be persisted",
                            "retryable": False,
                        },
                    )
                else:
                    self._emit_lifecycle(
                        RunEventType.RUN_CANCELLED,
                        status="cancelled",
                        duration_ms=elapsed_ms(),
                    )
                raise
            except Exception:
                try:
                    manifest_store.set_status("failed")
                except Exception:
                    pass
                self._emit_lifecycle(
                    RunEventType.RUN_FAILED,
                    status="failed",
                    duration_ms=elapsed_ms(),
                    error={
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
                try:
                    manifest_store.set_status(terminal_status)
                except Exception:
                    try:
                        manifest_store.set_status("failed")
                    except Exception:
                        pass
                    self._emit_lifecycle(
                        RunEventType.RUN_FAILED,
                        status="failed",
                        duration_ms=elapsed_ms(),
                        error={
                            "kind": "terminal_persistence_error",
                            "message": (
                                "Run terminal state could not be persisted"
                            ),
                            "retryable": False,
                        },
                    )
                    raise
                self._emit_lifecycle(
                    (
                        RunEventType.RUN_COMPLETED
                        if terminal_status == "completed"
                        else RunEventType.RUN_FAILED
                    ),
                    status=terminal_status,
                    duration_ms=elapsed_ms(),
                    **(
                        {}
                        if terminal_status == "completed"
                        else {
                            "error": {
                                "kind": "node_failure",
                                "message": (
                                    "One or more required Nodes did not "
                                    "complete"
                                ),
                                "retryable": False,
                            }
                        }
                    ),
                )

            # Return outputs for all completed nodes
            return {
                nid: node.outputs
                for nid, node in workflow.nodes.items()
                if node.state == NodeState.COMPLETED
            }
