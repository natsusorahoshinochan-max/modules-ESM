"""Shared local-process mechanics for solubility providers."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import signal
import subprocess
from typing import cast

from core.operation import OperationResources


class SolubilityReadinessUnavailable(RuntimeError):
    """A solubility Provider prerequisite is unavailable."""


class LocalProviderTimeout(RuntimeError):
    """One local provider exceeded its closed execution budget."""


def _require_file(
    path: Path,
    *,
    provider_name: str = "SoluProt",
) -> Path:
    if not path.is_file():
        raise SolubilityReadinessUnavailable(
            f"configured {provider_name} asset is unavailable"
        )
    return path


def _require_executable(
    path: Path,
    *,
    provider_name: str,
) -> Path:
    """Require one configured executable without binding its platform bytes."""
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SolubilityReadinessUnavailable(
            f"configured {provider_name} executable is unavailable"
        )
    return path


def _provider_sequence_id(index: int) -> str:
    """Return the exact staged FASTA identity shared with Provider output."""
    return f"candidate_{index}"


def _write_fasta(path: Path, sequences: Sequence[str]) -> None:
    with path.open("x", encoding="ascii", newline="\n") as handle:
        for index, sequence in enumerate(sequences):
            handle.write(f">{_provider_sequence_id(index)}\n{sequence}\n")


def _run_local_process(
    *,
    command: Sequence[str],
    staging_directory: Path,
    resources: OperationResources,
    path_entries: Sequence[Path] = (),
) -> int:
    process = subprocess.Popen(
        list(command),
        cwd=staging_directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            "HOME": str(staging_directory),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.pathsep.join(
                (*map(str, path_entries), os.defpath)
            ),
        },
        start_new_session=True,
    )
    try:
        with resources.cancellable_process_group(
            process.pid,
            fallback=process.kill,
        ):
            process.communicate(timeout=300)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise LocalProviderTimeout(
            "Local provider invocation timed out safely"
        ) from error
    return cast(int, process.returncode)
