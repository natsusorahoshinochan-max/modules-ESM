"""Shared local-process mechanics for solubility providers."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import os
from pathlib import Path
import signal
import subprocess

from core.operation import OperationResources


class SolubilityReadinessUnavailable(RuntimeError):
    """An exact solubility Provider prerequisite cannot be admitted."""


class LocalProviderTimeout(RuntimeError):
    """One local provider exceeded its closed execution budget."""


class LocalProviderOutputUnavailable(RuntimeError):
    """One local provider produced no readable output."""


def _regular_file_sha256(
    path: Path,
    *,
    executable: bool = False,
    provider_name: str = "SoluProt",
) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise SolubilityReadinessUnavailable(
            f"configured {provider_name} asset is unavailable"
        ) from error
    if executable and not os.access(path, os.X_OK):
        raise SolubilityReadinessUnavailable(
            f"configured {provider_name} executable is unavailable"
        )
    return digest.hexdigest()


def _require_digest(
    path: Path,
    expected: str,
    *,
    executable: bool = False,
    provider_name: str = "SoluProt",
) -> Path:
    if (
        _regular_file_sha256(
            path,
            executable=executable,
            provider_name=provider_name,
        )
        != expected
    ):
        raise SolubilityReadinessUnavailable(
            f"configured {provider_name} asset identity changed"
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
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
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
    return process.returncode
