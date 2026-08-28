"""Concrete Run-owned resources and bounded cancellation control."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, ContextManager, Protocol, cast

from core.operation import (
    EngineInvocationProvenance,
    ExecutionTermination,
    ManagedProcessResult,
)
from core.execution.run_context import RunContext
from core.project.manager import ProjectInputDescriptor, ProjectManager


CANCELLATION_TERM_GRACE_SECONDS = 0.25
CANCELLATION_KILL_GRACE_SECONDS = 0.25


class ManagedProcessTimeout(RuntimeError):
    """One core-managed local Provider process exceeded its closed budget."""


def _process_group_active(process_group: int) -> bool:
    """Report whether any member of one isolated process group is alive."""
    if process_group <= 1 or process_group == os.getpgrp():
        return True
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _conclude_process_group(
    process_group: int,
    *,
    fallback: Callable[[], None] | None,
    term_grace_seconds: float = CANCELLATION_TERM_GRACE_SECONDS,
    kill_grace_seconds: float = CANCELLATION_KILL_GRACE_SECONDS,
) -> None:
    """Bounded SIGTERM then SIGKILL escalation of one whole process group."""
    for process_signal, grace_seconds in (
        (signal.SIGTERM, term_grace_seconds),
        (signal.SIGKILL, kill_grace_seconds),
    ):
        if not _process_group_active(process_group):
            return
        _signal_process_group(
            process_group,
            process_signal,
            fallback=fallback,
        )
        deadline = time.monotonic() + grace_seconds
        while _process_group_active(process_group):
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)


class _InvocationRecorder(Protocol):
    def invoke(
        self,
        *,
        engine_role: str,
        parent_invocation_id: str | None,
        invocation_provenance: EngineInvocationProvenance | None,
    ) -> ContextManager[str]: ...


class LocalProviderMemory:
    """Keep memory resident only for the active local Provider."""

    def __init__(self, *, torch_module: Any | None = None) -> None:
        self._active_provider_id: str | None = None
        self._state: dict[object, object] = {}
        self._torch_module = torch_module

    @contextmanager
    def use(
        self,
        provider_id: str,
    ) -> Iterator[dict[object, object]]:
        if self._active_provider_id != provider_id:
            self.release()
            self._state = {}
            self._active_provider_id = provider_id
        yield self._state

    def release(self) -> None:
        had_active_provider = self._active_provider_id is not None
        self._state.clear()
        self._active_provider_id = None
        if not had_active_provider:
            return
        torch_module = self._torch_module or sys.modules.get("torch")
        if torch_module is None:
            return
        cuda = torch_module.cuda
        if cuda.is_available():
            cuda.empty_cache()


def _signal_process_group(
    process_group: int,
    process_signal: signal.Signals,
    *,
    fallback: Callable[[], None] | None = None,
) -> bool:
    """Signal an isolated group without risking the backend's own group."""
    try:
        if process_group <= 1 or process_group == os.getpgrp():
            raise PermissionError
        os.killpg(process_group, process_signal)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        if fallback is not None:
            fallback()
            return True
        return False
    return True


class CancellationControl:
    """Thread-safe owner of active process groups for one Run."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._cleanup_lock = threading.Lock()
        self._requested = False
        self._cleanup_generation = 0
        self._completed_cleanup_generation = 0
        self._next_registration = 0
        self._cleanup_error: BaseException | None = None
        self._cancelled_registrations: set[int] = set()
        self._process_groups: dict[
            int,
            tuple[int, Callable[[], None] | None],
        ] = {}

    def register_process_group(
        self,
        process_group: int,
        *,
        fallback: Callable[[], None] | None,
    ) -> int:
        with self._condition:
            self._next_registration += 1
            registration = self._next_registration
            self._process_groups[registration] = (process_group, fallback)
            requested = self._requested
            if requested:
                self._cleanup_generation += 1
        if requested:
            threading.Thread(
                target=self.request,
                name=f"run-cancellation-cleanup-{registration}",
                daemon=True,
            ).start()
        return registration

    def unregister_process_group(self, registration: int) -> bool:
        with self._condition:
            entry = self._process_groups.get(registration)
        if entry is None:
            return False
        process_group, fallback = entry
        # The host's own process group is not an owned Provider descendant and
        # is never concluded by unregister; only isolated Provider groups are.
        if process_group <= 1 or process_group == os.getpgrp():
            with self._condition:
                was_cancelled = registration in self._cancelled_registrations
                self._process_groups.pop(registration, None)
                self._cancelled_registrations.discard(registration)
                self._condition.notify_all()
            return was_cancelled
        if not _process_group_active(process_group):
            with self._condition:
                was_cancelled = registration in self._cancelled_registrations
                self._process_groups.pop(registration, None)
                self._cancelled_registrations.discard(registration)
                self._condition.notify_all()
            return was_cancelled
        # Leader exit alone must not close ownership while descendants remain.
        _conclude_process_group(process_group, fallback=fallback)
        with self._condition:
            was_cancelled = registration in self._cancelled_registrations
            if _process_group_active(process_group):
                if self._cleanup_error is None:
                    self._cleanup_error = RuntimeError(
                        "Run process-group cleanup could not be confirmed"
                    )
            else:
                self._process_groups.pop(registration, None)
                self._cancelled_registrations.discard(registration)
            self._condition.notify_all()
            return was_cancelled

    @staticmethod
    def _process_group_active(process_group: int) -> bool:
        return _process_group_active(process_group)

    def _active_groups(
        self,
        registrations: tuple[int, ...],
    ) -> tuple[tuple[int, int, Callable[[], None] | None], ...]:
        with self._condition:
            return tuple(
                (registration, entry[0], entry[1])
                for registration in registrations
                if (entry := self._process_groups.get(registration))
                is not None
                if self._process_group_active(entry[0])
            )

    def _signal_all(
        self,
        process_signal: signal.Signals,
        registrations: tuple[int, ...],
    ) -> None:
        for registration, process_group, fallback in self._active_groups(
            registrations
        ):
            try:
                with self._condition:
                    if registration not in self._process_groups:
                        continue
                    signalled = _signal_process_group(
                        process_group,
                        process_signal,
                        fallback=fallback,
                    )
                    if signalled:
                        self._cancelled_registrations.add(registration)
            except BaseException as error:
                with self._condition:
                    if self._cleanup_error is None:
                        self._cleanup_error = error

    def _wait_for_exit(
        self,
        timeout_seconds: float,
        registrations: tuple[int, ...],
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while self._active_groups(registrations):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.01))
            return True

    def request(self) -> None:
        with self._cleanup_lock:
            with self._condition:
                if not self._requested:
                    self._requested = True
                    self._cleanup_generation += 1
                if (
                    self._completed_cleanup_generation
                    >= self._cleanup_generation
                ):
                    return
                generation = self._cleanup_generation
                registrations = tuple(self._process_groups)
            try:
                self._signal_all(signal.SIGTERM, registrations)
                if self._wait_for_exit(
                    CANCELLATION_TERM_GRACE_SECONDS,
                    registrations,
                ):
                    return
                self._signal_all(signal.SIGKILL, registrations)
                if self._wait_for_exit(
                    CANCELLATION_KILL_GRACE_SECONDS,
                    registrations,
                ):
                    return
                with self._condition:
                    if self._cleanup_error is None:
                        self._cleanup_error = RuntimeError(
                            "Run process-group cleanup could not be confirmed"
                        )
            finally:
                with self._condition:
                    self._completed_cleanup_generation = max(
                        self._completed_cleanup_generation,
                        generation,
                    )
                    self._condition.notify_all()

    def wait_for_cleanup(self) -> None:
        """Wait until the cancellation owner reaches a bounded conclusion."""
        timeout = (
            CANCELLATION_TERM_GRACE_SECONDS
            + CANCELLATION_KILL_GRACE_SECONDS
            + 0.25
        )
        with self._condition:
            completed_generation = self._completed_cleanup_generation
            deadline = time.monotonic() + timeout
            while (
                self._completed_cleanup_generation
                < self._cleanup_generation
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
                if (
                    self._completed_cleanup_generation
                    > completed_generation
                ):
                    completed_generation = (
                        self._completed_cleanup_generation
                    )
                    deadline = time.monotonic() + timeout
            if (
                self._completed_cleanup_generation
                >= self._cleanup_generation
            ):
                return
            if self._cleanup_error is None:
                self._cleanup_error = RuntimeError(
                    "Run cancellation cleanup did not reach a conclusion"
                )

    @property
    def cleanup_error(self) -> BaseException | None:
        with self._condition:
            return self._cleanup_error


@dataclass(frozen=True, slots=True)
class RunResources:
    """Concrete Project/Run-contained resources for one operation."""

    project_id: str
    run_id: str
    node_id: str
    _projects: ProjectManager = field(repr=False, compare=False)
    _invocation_recorder: _InvocationRecorder = field(
        repr=False,
        compare=False,
    )
    _cancellation_control: CancellationControl = field(
        repr=False,
        compare=False,
    )
    _local_provider_memory: LocalProviderMemory = field(
        default_factory=LocalProviderMemory,
        repr=False,
        compare=False,
    )
    _project_inputs: Mapping[
        str,
        tuple[ProjectInputDescriptor, bytes],
    ] = field(default_factory=dict, repr=False, compare=False)
    _project_input_identities: tuple[Mapping[str, Any], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _run_context: RunContext = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_run_context",
            RunContext.for_node(
                self._projects.run_storage_directory(
                    self.project_id,
                    self.run_id,
                ),
                self.node_id,
            ),
        )

    def read_project_input(
        self,
        input_reference: str,
    ) -> tuple[ProjectInputDescriptor, bytes]:
        """Read one declared input from this Run's exact Project scope."""
        return self._project_inputs[input_reference]

    @property
    def result_identity_inputs(self) -> tuple[Mapping[str, Any], ...]:
        """Return path-free immutable resource identities for this Node."""
        return tuple(dict(identity) for identity in self._project_input_identities)

    def temporary_directory(self, *, prefix: str):
        """Create one temporary workspace in this Run and Node namespace."""
        return self._run_context.temporary_directory(prefix=prefix)

    def cleanup_temporary_work(self) -> None:
        self._run_context.cleanup_temporary_work()

    def local_provider(
        self,
        provider_id: str,
    ) -> ContextManager[dict[object, object]]:
        return self._local_provider_memory.use(provider_id)

    @contextmanager
    def cancellable_process_group(
        self,
        process_group: int,
        *,
        fallback: Callable[[], None] | None = None,
    ):
        """Register one isolated process group for Run cancellation."""
        registration = self._cancellation_control.register_process_group(
            process_group,
            fallback=fallback,
        )
        primary_error: BaseException | None = None
        try:
            yield
        except BaseException as error:
            primary_error = error
            raise
        finally:
            was_cancelled = (
                self._cancellation_control.unregister_process_group(
                    registration
                )
            )
            cleanup_error = self._cancellation_control.cleanup_error
            if cleanup_error is not None and cleanup_error is not primary_error:
                if primary_error is None:
                    raise cleanup_error
            if was_cancelled and primary_error is None:
                raise ExecutionTermination("cancelled")

    def run_managed_local_process(
        self,
        *,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
        path_entries: Sequence[Path] = (),
        capture_output: bool = False,
    ) -> ManagedProcessResult:
        """Own one isolated local Provider process through bounded termination.

        Adapters pass their own fixed positive finite timeout constant; this
        owner owns the process-group lifecycle, bounded escalation, and the
        wait for the whole group to disappear before unregistering it.
        """
        stdout_target = (
            subprocess.PIPE if capture_output else subprocess.DEVNULL
        )
        stderr_target = (
            subprocess.PIPE if capture_output else subprocess.DEVNULL
        )
        env = {
            "HOME": str(cwd),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.pathsep.join(
                (*map(str, path_entries), os.defpath)
            ),
        }
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=stdout_target,
            stderr=stderr_target,
            env=env,
            start_new_session=True,
        )
        process_group = process.pid

        def _safe_kill() -> None:
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass

        registration = self._cancellation_control.register_process_group(
            process_group,
            fallback=_safe_kill,
        )
        timed_out = False
        was_cancelled = False
        try:
            try:
                stdout_data, stderr_data = process.communicate(
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                # Conclude the whole group and reap the leader before the
                # registration context exits, so unregister observes no live
                # or zombie member of the owned group.
                _conclude_process_group(process_group, fallback=_safe_kill)
                try:
                    process.wait(
                        timeout=CANCELLATION_KILL_GRACE_SECONDS + 0.5,
                    )
                except subprocess.TimeoutExpired:
                    pass
                timed_out = True
        finally:
            was_cancelled = (
                self._cancellation_control.unregister_process_group(
                    registration
                )
            )
        if was_cancelled:
            raise ExecutionTermination("cancelled")
        if timed_out:
            raise ManagedProcessTimeout(
                "Local provider invocation timed out safely"
            )
        cleanup_error = self._cancellation_control.cleanup_error
        if cleanup_error is not None:
            raise cleanup_error
        return ManagedProcessResult(
            returncode=cast(int, process.returncode),
            stdout=stdout_data or b"",
            stderr=stderr_data or b"",
        )

    @contextmanager
    def engine_invocation(
        self,
        *,
        engine_role: str = "primary",
        parent_invocation_id: str | None = None,
        invocation_provenance: EngineInvocationProvenance | None = None,
    ):
        """Record one explicit crossing of a scientific engine boundary."""
        with self._invocation_recorder.invoke(
            engine_role=engine_role,
            parent_invocation_id=parent_invocation_id,
            invocation_provenance=invocation_provenance,
        ) as invocation_id:
            yield invocation_id
