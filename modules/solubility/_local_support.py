"""Shared local-process mechanics for solubility providers."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
from typing import cast

from core.operation import OperationResources


class SolubilityReadinessUnavailable(RuntimeError):
    """A solubility Provider prerequisite is unavailable."""


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
    timeout_seconds: float,
) -> int:
    """Run one solubility Provider process through the core managed owner."""
    result = resources.run_managed_local_process(
        command=command,
        cwd=staging_directory,
        timeout_seconds=timeout_seconds,
        path_entries=path_entries,
        capture_output=False,
    )
    return cast(int, result.returncode)
