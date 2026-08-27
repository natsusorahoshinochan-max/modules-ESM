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
import shutil
import subprocess
import sys
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.execution.resources import (
    CancellationControl,
    ManagedProcessTimeout,
    _process_group_active,
)
from core.operation import secondary_cleanup_exception_types
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
