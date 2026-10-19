"""Exercise the resource owner through its command-line boundary."""

import os
import shutil
import signal
from pathlib import Path
import subprocess
import sys

import pytest


def validation(
    command: str, *, cwd: Path | None = None, module_root: Path | None = None
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(module_root or Path(__file__).resolve().parents[1])
    return subprocess.Popen(
        [sys.executable, "-m", "protein_workbench_public.model_validation", "--", sys.executable, "-c", command],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_command_runs_in_requested_worktree_and_preserves_failure(tmp_path):
    process = validation("import os, sys; print(os.getcwd()); sys.exit(7)", cwd=tmp_path)
    stdout, stderr = process.communicate(timeout=10)
    assert (process.returncode, stdout.strip()) == (7, str(tmp_path.resolve()))


def test_other_worktrees_queue_until_failed_command_releases_resource(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    source = Path(__file__).resolve().parents[1] / "protein_workbench_public"
    for checkout in (first_dir, second_dir):
        package = checkout / "protein_workbench_public"
        package.mkdir()
        for name in ("__init__.py", "model_validation.py"):
            shutil.copyfile(source / name, package / name)
    release = tmp_path / "release"
    owner = validation(
        "from pathlib import Path; import time, sys; print('loaded', flush=True); "
        f"p = Path({str(release)!r})\n"
        "while not p.exists(): time.sleep(.02)\n"
        "sys.exit(9)",
        cwd=first_dir,
        module_root=first_dir,
    )
    queued = None
    try:
        assert owner.stdout.readline().strip() == "loaded"
        queued = validation("print('next model')", cwd=second_dir, module_root=second_dir)
        with pytest.raises(subprocess.TimeoutExpired):
            queued.communicate(timeout=.25)
        release.touch()
        owner.communicate(timeout=10)
        stdout, _ = queued.communicate(timeout=10)
        assert (owner.returncode, queued.returncode, stdout.strip()) == (9, 0, "next model")
    finally:
        release.touch()
        owner.communicate(timeout=10)
        if queued is not None:
            queued.communicate(timeout=10)


@pytest.mark.parametrize("exit_status", [0, 8])
def test_exited_command_cleans_lingering_model_service_before_unlocking(exit_status):
    service_code = (
        "import os, signal, socket, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); "
        "print(os.getpid(), s.getsockname()[1], flush=True); time.sleep(30)"
    )
    owner = validation(
        "import subprocess, sys; "
        f"p = subprocess.Popen([sys.executable, '-c', {service_code!r}], "
        "stdout=subprocess.PIPE, text=True); print(p.stdout.readline().strip(), flush=True); "
        f"sys.exit({exit_status})"
    )
    service_pid = None
    try:
        service_pid, port = map(int, owner.stdout.readline().split())
        owner.communicate(timeout=10)
        next_check = validation(
            "import socket; s = socket.socket(); "
            f"s.bind(('127.0.0.1', {port})); print('resource returned')"
        )
        stdout, stderr = next_check.communicate(timeout=10)
        assert (owner.returncode, next_check.returncode, stdout.strip()) == (exit_status, 0, "resource returned")
    finally:
        if service_pid:
            try:
                os.kill(service_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        owner.communicate(timeout=10)


@pytest.mark.parametrize("cancel_signal", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_cancellation_stops_model_process_and_returns_resource(cancel_signal):
    owner = validation(
        "import os, signal, socket, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); "
        "print(os.getpid(), s.getsockname()[1], flush=True); time.sleep(30)"
    )
    model_pid = None
    try:
        model_pid, port = map(int, owner.stdout.readline().split())
        owner.send_signal(cancel_signal)
        owner.communicate(timeout=10)
        next_check = validation(
            "import socket; s = socket.socket(); "
            f"s.bind(('127.0.0.1', {port})); print('resource returned')"
        )
        stdout, _ = next_check.communicate(timeout=10)
        assert (owner.returncode, next_check.returncode, stdout.strip()) == (128 + cancel_signal, 0, "resource returned")
    finally:
        if model_pid:
            try:
                os.kill(model_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        owner.communicate(timeout=10)


def test_cancelled_waiter_does_not_start_or_release_current_owner(tmp_path):
    release = tmp_path / "release"
    owner = validation(
        "from pathlib import Path; import time; print('loaded', flush=True); "
        f"p = Path({str(release)!r})\n"
        "while not p.exists(): time.sleep(.02)"
    )
    waiter = None
    try:
        assert owner.stdout.readline().strip() == "loaded"
        waiter = validation("print('must not load')")
        assert waiter.stderr.readline().startswith("Waiting for model resource:")
        waiter.send_signal(signal.SIGTERM)
        stdout, _ = waiter.communicate(timeout=10)
        assert (waiter.returncode, stdout, owner.poll()) == (143, "", None)
    finally:
        release.touch()
        owner.communicate(timeout=10)
        if waiter is not None:
            waiter.communicate(timeout=10)


def test_command_launch_failure_reports_reason_and_releases_resource(tmp_path):
    missing = tmp_path / "missing-model-check"
    failed = subprocess.run(
        [sys.executable, "-m", "protein_workbench_public.model_validation", "--", str(missing)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    next_check = validation("print('can load')")
    stdout, _ = next_check.communicate(timeout=10)
    assert (failed.returncode, str(missing) in failed.stderr, next_check.returncode, stdout.strip()) == (
        126, True, 0, "can load"
    )
