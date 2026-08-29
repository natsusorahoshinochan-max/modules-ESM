"""Provider execution contract — Batch 1 core infrastructure verification.

Covers the local-process profile and source-boundary check from
``docs/provider-execution-contract.md``:

- production Module Packages do not directly own ``subprocess.run`` or
  ``subprocess.Popen``; the one core managed-process owner is the only
  production exception;
- cancellation owns the complete process group — leader-first exit leaves no
  descendant performing Provider work;
- each Adapter passes one fixed positive finite timeout constant to the core
  owner, and a timeout terminates the whole group and raises
  ``ManagedProcessTimeout``;
- temporary-directory cleanup failure never replaces the primary Operation
  error (it is retained as ordered secondary cleanup causality).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.execution.resources import (
    CancellationControl,
    ManagedProcessTimeout,
    _process_group_active,
)
from core.execution.results.cache import ResultIndexError
from core.operation import secondary_cleanup_exception_types
from protein_workbench_public.ledger_codec import encode_event
from tests.support.application import create_application
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal
from tests.test_run_runtime import (
    _commit_one_node,
    _direct_catalog,
)


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MODULES_ROOT = REPOSITORY_ROOT / "modules"
CORE_ROOT = REPOSITORY_ROOT / "core"


def _imports_subprocess(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    return True
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            return True
    return False


def test_production_module_packages_do_not_own_subprocess_lifecycle() -> None:
    """Module Packages must not import subprocess directly (#84)."""
    offenders = sorted(
        str(path.relative_to(REPOSITORY_ROOT))
        for path in MODULES_ROOT.rglob("*.py")
        if _imports_subprocess(path)
    )
    assert offenders == [], offenders


def test_core_managed_process_owner_is_the_only_subprocess_exception() -> None:
    """Only the one core managed-process owner imports subprocess (#84)."""
    owners = sorted(
        str(path.relative_to(REPOSITORY_ROOT))
        for path in CORE_ROOT.rglob("*.py")
        if _imports_subprocess(path)
    )
    assert owners == ["core/execution/resources.py"], owners


def _start(
    client: TestClient,
    project_id: str,
    committed: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": committed["workflow_commit_id"],
            "client_request_id": request_id,
        },
    )
    assert response.status_code == 202
    return response.json()


def _wait_terminal(
    client: TestClient,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    return wait_for_testclient_run_terminal(client, project_id, run_id)


def _public_events(
    app: Any,
    project_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    return [
        encode_event(
            project_id=project_id,
            run_id=run_id,
            fact=fact,
        )["event"]
        for fact in app.state.run_runtime.events(project_id, run_id)
    ]


_LEADER_THEN_SURVIVING_CHILD = (
    "import os,signal,subprocess,sys;"
    "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
    "child=subprocess.Popen([sys.executable,'-c',"
    "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
    "time.sleep(60)']);"
    "open(sys.argv[1],'w').write(str(child.pid))"
)


def _assert_process_dead(pid: int, *, grace_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    raise AssertionError(f"process {pid} still alive")


def test_managed_local_process_leader_first_exit_leaves_no_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leader exit must not close group ownership while descendants live (#83)."""
    captured: dict[str, int] = {}

    def execute_with_managed_owner(resources: Any) -> None:
        with resources.temporary_directory(
            prefix="managed-leader-"
        ) as workspace:
            marker = workspace / "child-pid"
            resources.run_managed_local_process(
                command=[
                    sys.executable,
                    "-c",
                    _LEADER_THEN_SURVIVING_CHILD,
                    str(marker),
                ],
                cwd=workspace,
                timeout_seconds=60.0,
                capture_output=False,
            )
            assert marker.exists()
            captured["child"] = int(marker.read_text())
            _assert_process_dead(captured["child"])

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_with_managed_owner,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "managed-leader-exit")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "succeeded"
    with pytest.raises(ProcessLookupError):
        os.kill(captured["child"], 0)


def test_managed_local_process_timeout_terminates_group_and_raises_managed_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded timeout concludes the whole group and raises ManagedProcessTimeout."""
    captured: dict[str, Any] = {}

    def execute_with_timeout(resources: Any) -> None:
        with resources.temporary_directory(prefix="managed-timeout-") as workspace:
            marker = workspace / "pid"
            script = (
                "import os,time;"
                f"path={str(marker)!r};"
                "open(path,'w').write(str(os.getpid()));"
                "time.sleep(60)"
            )
            try:
                resources.run_managed_local_process(
                    command=[sys.executable, "-c", script],
                    cwd=workspace,
                    timeout_seconds=0.5,
                    capture_output=False,
                )
                captured["error"] = "no-timeout-raised"
                return
            except ManagedProcessTimeout:
                captured["error"] = "timeout"
            except BaseException as error:  # noqa: BLE001
                captured["error"] = f"{type(error).__name__}: {error}"
                raise
            if not marker.exists():
                captured["error"] = "marker-missing"
                raise AssertionError(captured["error"])
            captured["pid"] = int(marker.read_text())
            try:
                _assert_process_dead(captured["pid"])
            except AssertionError as error:
                captured["error"] = f"survivor: {error}"
                raise

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_with_timeout,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "managed-timeout")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "succeeded", captured
    assert captured.get("error") == "timeout", captured
    with pytest.raises(ProcessLookupError):
        os.kill(captured["pid"], 0)


def test_non_cancelled_process_group_cleanup_failure_cannot_publish_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed normal-path group conclusion is a failed Node outcome."""
    import core.execution.resources as resources_module

    monkeypatch.setattr(
        resources_module,
        "_process_group_active",
        lambda _process_group: True,
    )
    monkeypatch.setattr(
        resources_module,
        "_conclude_process_group",
        lambda _process_group, *, fallback: None,
    )

    def execute_managed_provider(resources: Any) -> None:
        with resources.temporary_directory(
            prefix="failed-normal-cleanup-"
        ) as workspace:
            resources.run_managed_local_process(
                command=[sys.executable, "-c", "pass"],
                cwd=workspace,
                timeout_seconds=60.0,
            )

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_managed_provider,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "failed-normal-cleanup")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "failed"
    node_terminal = next(
        event
        for event in _public_events(app, project_id, receipt["run_id"])
        if event["type"] == "node_attempt_terminal"
    )
    assert node_terminal["error"]["details"] == {
        "exception_type": "RuntimeError",
    }


def test_generic_process_group_cleanup_failure_cannot_publish_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic core ownership seam preserves the same cleanup gate."""
    import core.execution.resources as resources_module

    monkeypatch.setattr(
        resources_module,
        "_process_group_active",
        lambda _process_group: True,
    )
    monkeypatch.setattr(
        resources_module,
        "_conclude_process_group",
        lambda _process_group, *, fallback: None,
    )

    def execute_owned_group(resources: Any) -> None:
        with resources.cancellable_process_group(20_000, fallback=None):
            pass

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_owned_group,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "failed-generic-cleanup")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "failed"
    node_terminal = next(
        event
        for event in _public_events(app, project_id, receipt["run_id"])
        if event["type"] == "node_attempt_terminal"
    )
    assert node_terminal["error"]["details"] == {
        "exception_type": "RuntimeError",
    }


def test_generic_process_group_cleanup_is_secondary_to_its_body_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic owner retains one primary and one cleanup cause."""
    import core.execution.resources as resources_module

    monkeypatch.setattr(
        resources_module,
        "_process_group_active",
        lambda _process_group: True,
    )
    monkeypatch.setattr(
        resources_module,
        "_conclude_process_group",
        lambda _process_group, *, fallback: None,
    )

    def execute_owned_group(resources: Any) -> None:
        with resources.cancellable_process_group(20_001, fallback=None):
            raise ValueError("primary provider failure")

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_owned_group,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "generic-primary-error")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "failed"
    node_terminal = next(
        event
        for event in _public_events(app, project_id, receipt["run_id"])
        if event["type"] == "node_attempt_terminal"
    )
    assert node_terminal["error"]["details"] == {
        "exception_type": "ValueError",
        "cleanup_exception_types": ["RuntimeError"],
    }


def test_handled_body_error_cannot_hide_process_group_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handled body error cannot erase the Run-owned cleanup failure."""
    import core.execution.resources as resources_module

    monkeypatch.setattr(
        resources_module,
        "_process_group_active",
        lambda _process_group: True,
    )
    monkeypatch.setattr(
        resources_module,
        "_conclude_process_group",
        lambda _process_group, *, fallback: None,
    )

    def execute_owned_group(resources: Any) -> None:
        try:
            with resources.cancellable_process_group(20_002, fallback=None):
                raise ValueError("handled provider failure")
        except ValueError:
            pass

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_owned_group,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "handled-body-error")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "failed"
    node_terminal = next(
        event
        for event in _public_events(app, project_id, receipt["run_id"])
        if event["type"] == "node_attempt_terminal"
    )
    assert node_terminal["error"]["details"] == {
        "exception_type": "RuntimeError",
    }


def test_unregister_concludes_surviving_descendants_directly(
    tmp_path: Path,
) -> None:
    """CancellationControl.unregister gates on whole-group liveness (#83)."""
    marker = tmp_path / "child-pid"
    leader = subprocess.Popen(
        [sys.executable, "-c", _LEADER_THEN_SURVIVING_CHILD, str(marker)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process_group = leader.pid
    leader.wait(timeout=5)
    assert marker.exists()
    child_pid = int(marker.read_text())

    control = CancellationControl()
    registration = control.register_process_group(
        process_group,
        fallback=None,
    )
    assert _process_group_active(process_group)
    control.unregister_process_group(registration)

    _assert_process_dead(child_pid)
    assert not _process_group_active(process_group)


def test_cancellation_cleanup_does_not_finish_while_unregister_concludes_group(
    tmp_path: Path,
) -> None:
    """Cleanup completion retains ownership until the process group is inactive."""
    marker = tmp_path / "child-pid"
    term_observed = tmp_path / "term-observed"
    child_ready = tmp_path / "child-ready"
    child_script = (
        "import pathlib,signal,sys,time;"
        "signal.signal(signal.SIGTERM,lambda *_:"
        "pathlib.Path(sys.argv[1]).write_text('term'));"
        "pathlib.Path(sys.argv[2]).write_text('ready');"
        "time.sleep(30)"
    )
    leader_script = (
        "import pathlib,subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2],"
        "sys.argv[3],sys.argv[4]]);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))"
    )
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            leader_script,
            str(marker),
            child_script,
            str(term_observed),
            str(child_ready),
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process_group = leader.pid
    leader.wait(timeout=5)
    assert marker.exists()
    deadline = time.monotonic() + 2
    while not child_ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_ready.exists()

    control = CancellationControl()
    registration = control.register_process_group(process_group, fallback=None)
    unregister = threading.Thread(
        target=control.unregister_process_group,
        args=(registration,),
    )
    unregister.start()
    deadline = time.monotonic() + 2
    while not term_observed.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert term_observed.exists()

    control.request()
    control.wait_for_cleanup()

    assert not _process_group_active(process_group)
    unregister.join(timeout=2)
    assert not unregister.is_alive()


def test_late_registration_waits_for_its_cleanup_generation() -> None:
    """An older cleanup request cannot complete a later registration."""

    class SequencedCancellationControl(CancellationControl):
        def __init__(self) -> None:
            super().__init__()
            self.first_wait_started = threading.Event()
            self.second_wait_started = threading.Event()
            self.finish_first_wait = threading.Event()
            self.finish_second_wait = threading.Event()
            self.wait_count = 0

        def _wait_for_exit(
            self,
            timeout_seconds: float,
            registrations: tuple[int, ...] | None = None,
        ) -> bool:
            del registrations
            del timeout_seconds
            self.wait_count += 1
            if self.wait_count == 1:
                self.first_wait_started.set()
                assert self.finish_first_wait.wait(timeout=2)
            else:
                self.second_wait_started.set()
                assert self.finish_second_wait.wait(timeout=2)
            return True

    control = SequencedCancellationControl()
    first_registration = control.register_process_group(
        os.getpgrp(),
        fallback=lambda: None,
    )
    first_request = threading.Thread(target=control.request)
    first_request.start()
    assert control.first_wait_started.wait(timeout=2)

    cleanup_wait = threading.Thread(target=control.wait_for_cleanup)
    cleanup_wait.start()
    time.sleep(0.05)
    assert cleanup_wait.is_alive()

    second_registration = control.register_process_group(
        os.getpgrp(),
        fallback=lambda: None,
    )
    control.finish_first_wait.set()
    first_request.join(timeout=2)
    assert not first_request.is_alive()
    assert control.second_wait_started.wait(timeout=2)

    time.sleep(0.05)
    assert cleanup_wait.is_alive()

    control.finish_second_wait.set()
    cleanup_wait.join(timeout=2)
    assert not cleanup_wait.is_alive()
    control.unregister_process_group(first_registration)
    control.unregister_process_group(second_registration)


def test_late_registration_is_not_killed_by_an_earlier_cleanup_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each late registration receives its own complete TERM/KILL protocol."""
    import core.execution.resources as resources_module

    first_group = 31_001
    second_group = 31_002
    active_groups = {first_group}
    signals: list[tuple[int, signal.Signals]] = []
    first_wait_started = threading.Event()
    continue_first_wait = threading.Event()

    monkeypatch.setattr(
        resources_module,
        "CANCELLATION_TERM_GRACE_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        resources_module,
        "CANCELLATION_KILL_GRACE_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        resources_module,
        "_process_group_active",
        lambda process_group: process_group in active_groups,
    )

    def signal_group(
        process_group: int,
        process_signal: signal.Signals,
        *,
        fallback: Any,
    ) -> bool:
        del fallback
        signals.append((process_group, process_signal))
        if process_signal == signal.SIGKILL or (
            process_group == second_group
            and process_signal == signal.SIGTERM
        ):
            active_groups.discard(process_group)
        return True

    monkeypatch.setattr(resources_module, "_signal_process_group", signal_group)

    class SequencedCancellationControl(CancellationControl):
        def __init__(self) -> None:
            super().__init__()
            self.wait_count = 0

        def _wait_for_exit(
            self,
            timeout_seconds: float,
            registrations: tuple[int, ...] | None = None,
        ) -> bool:
            self.wait_count += 1
            if self.wait_count == 1:
                first_wait_started.set()
                assert continue_first_wait.wait(timeout=2)
            if registrations is None:
                return super()._wait_for_exit(timeout_seconds)
            return super()._wait_for_exit(timeout_seconds, registrations)

    control = SequencedCancellationControl()
    first_registration = control.register_process_group(
        first_group,
        fallback=None,
    )
    first_request = threading.Thread(target=control.request)
    first_request.start()
    assert first_wait_started.wait(timeout=2)

    active_groups.add(second_group)
    second_registration = control.register_process_group(
        second_group,
        fallback=None,
    )
    continue_first_wait.set()
    control.wait_for_cleanup()
    first_request.join(timeout=2)

    assert not first_request.is_alive()
    assert control.cleanup_error is None
    assert [
        process_signal
        for process_group, process_signal in signals
        if process_group == second_group
    ] == [signal.SIGTERM]
    control.unregister_process_group(first_registration)
    control.unregister_process_group(second_registration)


def test_wait_for_cleanup_gives_each_serial_generation_its_bounded_budget(
) -> None:
    """A later cleanup generation receives a fresh bounded wait budget."""
    import core.execution.resources as resources_module

    class SequencedCancellationControl(CancellationControl):
        def __init__(self) -> None:
            super().__init__()
            self.first_wait_started = threading.Event()
            self.second_generation_done = threading.Event()
            self.wait_count = 0

        def _signal_all(
            self,
            process_signal: signal.Signals,
            registrations: tuple[int, ...] | None = None,
        ) -> None:
            del process_signal, registrations

        def _wait_for_exit(
            self,
            timeout_seconds: float,
            registrations: tuple[int, ...] | None = None,
        ) -> bool:
            del registrations
            self.wait_count += 1
            if self.wait_count == 1:
                self.first_wait_started.set()
            time.sleep(timeout_seconds * 0.9)
            if self.wait_count == 4:
                self.second_generation_done.set()
            return self.wait_count % 2 == 0

    control = SequencedCancellationControl()
    first_registration = control.register_process_group(
        os.getpgrp(),
        fallback=None,
    )
    first_request = threading.Thread(target=control.request)
    first_request.start()
    assert control.first_wait_started.wait(timeout=2)

    second_registration = control.register_process_group(
        os.getpgrp(),
        fallback=None,
    )
    cleanup_returned = threading.Event()

    def wait_for_cleanup() -> None:
        control.wait_for_cleanup()
        cleanup_returned.set()

    cleanup_wait = threading.Thread(target=wait_for_cleanup)
    cleanup_wait.start()
    single_generation_budget = (
        resources_module.CANCELLATION_TERM_GRACE_SECONDS
        + resources_module.CANCELLATION_KILL_GRACE_SECONDS
        + 0.25
    )
    returned_before_second_generation = cleanup_returned.wait(
        timeout=single_generation_budget + 0.03
    )
    assert control.second_generation_done.wait(timeout=2)
    control.wait_for_cleanup()
    cleanup_wait.join(timeout=2)
    first_request.join(timeout=2)

    assert returned_before_second_generation is False
    assert control.cleanup_error is None
    assert not cleanup_wait.is_alive()
    assert not first_request.is_alive()
    control.unregister_process_group(first_registration)
    control.unregister_process_group(second_registration)


def test_cancelled_managed_process_records_cancelled_engine_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run cancellation classifies a killed Provider process as cancelled."""
    marker = tmp_path / "provider-started"

    def execute_managed_provider(resources: Any) -> None:
        with resources.temporary_directory(prefix="cancel-provider-") as workspace:
            result = resources.run_managed_local_process(
                command=[
                    sys.executable,
                    "-c",
                    (
                        "import pathlib,sys,time;"
                        "pathlib.Path(sys.argv[1]).write_text('started');"
                        "time.sleep(30)"
                    ),
                    str(marker),
                ],
                cwd=workspace,
                timeout_seconds=60.0,
            )
            if result.returncode != 0:
                raise RuntimeError("Provider process failed")

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_managed_provider,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-provider")
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    terminal_statuses = [
        event["status"]
        for event in _public_events(app, project_id, receipt["run_id"])
        if event["type"]
        in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    ]
    assert terminal_statuses == ["cancelled", "cancelled", "cancelled"]


@pytest.mark.parametrize(
    ("failure_stage", "exception_type"),
    (
        ("operation", "ExecutionTermination"),
        ("factory", "ResultIndexError"),
    ),
)
def test_cleanup_error_concluded_while_waiting_is_retained_in_terminal_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    exception_type: str,
) -> None:
    """Terminal publication observes cancellation cleanup after its wait."""
    registration_ready = threading.Event()
    cleanup_started = threading.Event()
    finish_operation = threading.Event()
    release_registration = threading.Event()
    holder_threads: list[threading.Thread] = []
    holder_cleanup_errors: list[RuntimeError] = []

    def execute_during_failed_cleanup(resources: Any) -> None:
        def hold_registration() -> None:
            try:
                with resources.cancellable_process_group(
                    os.getpgrp(),
                    fallback=cleanup_started.set,
                ):
                    registration_ready.set()
                    assert release_registration.wait(timeout=3)
            except RuntimeError as error:
                holder_cleanup_errors.append(error)

        holder = threading.Thread(target=hold_registration)
        holder.start()
        holder_threads.append(holder)
        assert registration_ready.wait(timeout=2)
        assert finish_operation.wait(timeout=2)
        if failure_stage == "factory":
            raise ResultIndexError("private-factory-failure")

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    action_argument = (
        {"execution_action": execute_during_failed_cleanup}
        if failure_stage == "operation"
        else {"factory_action": execute_during_failed_cleanup}
    )
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            **action_argument,
        ),
        v2_environment_configuration={
            "test.direct.local": {"credential": "credential-value"}
        },
    )

    cancel_response: dict[str, Any] = {}
    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cleanup-evidence")
        assert registration_ready.wait(timeout=2)

        def cancel() -> None:
            cancel_response["value"] = client.post(
                f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
                json={},
            )

        cancellation = threading.Thread(target=cancel)
        cancellation.start()
        assert cleanup_started.wait(timeout=2)
        finish_operation.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])
        cancellation.join(timeout=2)
        release_registration.set()
        for holder in holder_threads:
            holder.join(timeout=2)

    assert cancel_response["value"].status_code == 200
    assert [str(error) for error in holder_cleanup_errors] == [
        "Run process-group cleanup could not be confirmed"
    ]
    assert projection["status"] == "failed"
    terminals = {
        event["type"]: event
        for event in _public_events(app, project_id, receipt["run_id"])
        if event["type"]
        in {
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    }
    for terminal in terminals.values():
        assert terminal["status"] == "failed"
        assert terminal["error"]["details"] == {
            "exception_type": exception_type,
            "cleanup_exception_types": ["RuntimeError"],
        }


def test_temporary_directory_cleanup_failure_preserves_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup failure never replaces the primary Operation error (#87)."""
    from core.execution.run_context import RunContext

    def boom(path: Any, *args: Any, **kwargs: Any) -> None:
        raise OSError("private-cleanup-detail")

    monkeypatch.setattr(shutil, "rmtree", boom)

    context = RunContext(temp_dir=str(tmp_path))
    primary = RuntimeError("primary-operation-error")
    with pytest.raises(RuntimeError) as raised:
        with context.temporary_directory(prefix="cleanup-fail"):
            raise primary

    assert raised.value is primary
    retained = secondary_cleanup_exception_types(primary)
    assert "OSError" in retained
