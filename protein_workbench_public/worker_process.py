"""Launch a subprocess under the machine supervisor and wait for full cleanup."""
from collections.abc import Callable, Sequence
from pathlib import Path
import subprocess
import sys
import time


def run_worker(command: Sequence[str], *, cwd: Path, log_path: Path,
               cancelled: Callable[[], bool], label: str) -> None:
    """Return on success; report cancellation or a bounded worker diagnostic.

    The supervisor alone owns the resource lock and descendant process cleanup.
    The caller retains ownership of command configuration and result files.
    """
    with log_path.open('w') as log:
        process = subprocess.Popen(
            [sys.executable, '-m', 'protein_workbench_public.model_validation', '--', *command],
            cwd=cwd, stderr=log,
        )
        try:
            while process.poll() is None:
                if cancelled():
                    raise ValueError(f'{label} cancelled')
                time.sleep(.1)
            if process.returncode:
                log.flush()
                with log_path.open('rb') as reader:
                    reader.seek(max(0, log_path.stat().st_size - 4096))
                    lines = reader.read().decode(errors='replace').splitlines()
                detail = next((line for line in reversed(lines)
                               if line.strip() and not line.startswith('Model processes exited')),
                              'No worker diagnostic was returned')
                raise ValueError(f'{label} failed (exit {process.returncode}): {detail}')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
