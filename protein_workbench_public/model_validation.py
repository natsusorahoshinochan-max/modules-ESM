"""Run a real-model check under the shared machine resource lock (POSIX)."""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


LOCK_PATH = Path("/tmp/protein-workbench-model-validation.lock")


def _signal_group(group: int, signum: int) -> None:
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def _group_has_resources(group: int) -> bool:
    # Orphaned zombies may await the OS reaper; they hold no model resources.
    try:
        processes = subprocess.run(
            ["ps", "-axo", "pgid=,stat="], check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.SubprocessError):
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        return True
    for line in processes.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and int(fields[0]) == group and not fields[1].startswith("Z"):
            return True
    return False


def _cleanup(process: subprocess.Popen) -> None:
    _signal_group(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 1
    while True:
        process.poll()  # Reap the direct child before inspecting remaining services.
        if not _group_has_resources(process.pid):
            break
        if time.monotonic() >= deadline:
            _signal_group(process.pid, signal.SIGKILL)
        time.sleep(.05)
    process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    cancelled = 0

    def cancel(signum: int, _frame: object) -> None:
        nonlocal cancelled
        cancelled = cancelled or signum

    handlers = {sig: signal.signal(sig, cancel) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        # Fixed absolute path also covers other checkouts and different TMPDIR values.
        descriptor = os.open(LOCK_PATH, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        with os.fdopen(descriptor, "r") as lock:
            print(f"Waiting for model resource: {LOCK_PATH}", file=sys.stderr, flush=True)
            while not cancelled:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.05)
            if cancelled:
                return 128 + cancelled
            print("Model resource acquired", file=sys.stderr, flush=True)
            process = subprocess.Popen(command, start_new_session=True)
            try:
                while process.poll() is None and not cancelled:
                    time.sleep(.05)
            finally:
                _cleanup(process)
            print("Model processes exited; resource released", file=sys.stderr, flush=True)
            if cancelled:
                return 128 + cancelled
            return process.returncode if process.returncode >= 0 else 128 - process.returncode
    except OSError as error:
        print(f"Model validation failed: {error}", file=sys.stderr)
        return 126
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
