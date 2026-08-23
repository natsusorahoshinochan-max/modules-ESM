"""Concrete Run-owned resources and bounded cancellation control."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import signal
import threading
import time
from typing import Any, ContextManager, Protocol

from core.operation import EngineInvocationProvenance
from core.project.manager import ProjectInputDescriptor, ProjectManager


CANCELLATION_TERM_GRACE_SECONDS = 0.25
CANCELLATION_KILL_GRACE_SECONDS = 0.25


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

    def __init__(self) -> None:
        self._active: tuple[str, Callable[[], None]] | None = None
        self._lock = threading.Lock()

    @contextmanager
    def use(
        self,
        provider_id: str,
        release: Callable[[], None],
    ) -> Iterator[None]:
        with self._lock:
            if self._active is None or self._active[0] != provider_id:
                if self._active is not None:
                    self._active[1]()
                self._active = (provider_id, release)
            yield


def _signal_process_group(
    process_group: int,
    process_signal: signal.Signals,
    *,
    fallback: Callable[[], None] | None = None,
) -> None:
    """Signal an isolated group without risking the backend's own group."""
    try:
        if process_group <= 1 or process_group == os.getpgrp():
            raise PermissionError
        os.killpg(process_group, process_signal)
    except (ProcessLookupError, PermissionError, OSError):
        if fallback is not None:
            fallback()


class CancellationControl:
    """Thread-safe owner of active process groups for one Run."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._cleanup_lock = threading.Lock()
        self._cleanup_complete = threading.Event()
        self._requested = False
        self._next_registration = 0
        self._cleanup_error: BaseException | None = None
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
                self._cleanup_complete.clear()
        if requested:
            threading.Thread(
                target=self.request,
                name=f"run-cancellation-cleanup-{registration}",
                daemon=True,
            ).start()
        return registration

    def unregister_process_group(self, registration: int) -> None:
        with self._condition:
            self._process_groups.pop(registration, None)
            self._condition.notify_all()

    @staticmethod
    def _process_group_active(process_group: int) -> bool:
        if process_group <= 1 or process_group == os.getpgrp():
            return True
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True
        return True

    def _active_groups(
        self,
    ) -> tuple[tuple[int, int, Callable[[], None] | None], ...]:
        with self._condition:
            for registration, (process_group, _) in tuple(
                self._process_groups.items()
            ):
                if not self._process_group_active(process_group):
                    self._process_groups.pop(registration, None)
            return tuple(
                (registration, process_group, fallback)
                for registration, (process_group, fallback) in (
                    self._process_groups.items()
                )
            )

    def _signal_all(self, process_signal: signal.Signals) -> None:
        for _, process_group, fallback in self._active_groups():
            try:
                _signal_process_group(
                    process_group,
                    process_signal,
                    fallback=fallback,
                )
            except BaseException as error:
                with self._condition:
                    if self._cleanup_error is None:
                        self._cleanup_error = error

    def _wait_for_exit(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while self._active_groups():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.01))
            return True

    def request(self) -> None:
        with self._cleanup_lock:
            self._cleanup_complete.clear()
            try:
                with self._condition:
                    self._requested = True
                self._signal_all(signal.SIGTERM)
                if self._wait_for_exit(CANCELLATION_TERM_GRACE_SECONDS):
                    return
                self._signal_all(signal.SIGKILL)
                if self._wait_for_exit(CANCELLATION_KILL_GRACE_SECONDS):
                    return
                with self._condition:
                    if self._cleanup_error is None:
                        self._cleanup_error = RuntimeError(
                            "Run process-group cleanup could not be confirmed"
                        )
            finally:
                self._cleanup_complete.set()

    def wait_for_cleanup(self) -> None:
        """Wait until the cancellation owner reaches a bounded conclusion."""
        timeout = (
            CANCELLATION_TERM_GRACE_SECONDS
            + CANCELLATION_KILL_GRACE_SECONDS
            + 0.25
        )
        if self._cleanup_complete.wait(timeout):
            return
        with self._condition:
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
        return self._projects.run_context(
            self.project_id,
            self.run_id,
            self.node_id,
        ).temporary_directory(prefix=prefix)

    def cleanup_temporary_work(self) -> None:
        self._projects.run_context(
            self.project_id,
            self.run_id,
            self.node_id,
        ).cleanup_temporary_work()

    def local_provider(
        self,
        provider_id: str,
        release: Callable[[], None],
    ) -> ContextManager[None]:
        return self._local_provider_memory.use(provider_id, release)

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
        try:
            yield
        finally:
            self._cancellation_control.unregister_process_group(registration)

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
