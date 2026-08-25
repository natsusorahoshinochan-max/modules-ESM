"""Translate the installed process environment into application storage roots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path


class ApplicationEnvironmentError(RuntimeError):
    """The installed application storage environment is not configured."""


@dataclass(frozen=True, slots=True)
class ApplicationStorageRoots:
    """The four storage scopes derived from one stable application root."""

    data: Path
    projects: Path
    cache: Path
    outputs: Path
    runs: Path


def application_storage_roots(
    environment: Mapping[str, str] | None = None,
) -> ApplicationStorageRoots:
    """Require one absolute data root and derive every application store."""
    values = os.environ if environment is None else environment
    configured = values.get("PROTEIN_WORKBENCH_DATA_ROOT")
    if configured is None:
        raise ApplicationEnvironmentError(
            "PROTEIN_WORKBENCH_DATA_ROOT is required"
        )
    data_root = Path(configured).expanduser()
    if not data_root.is_absolute():
        raise ApplicationEnvironmentError(
            "PROTEIN_WORKBENCH_DATA_ROOT must be absolute"
        )
    return ApplicationStorageRoots(
        data=data_root,
        projects=data_root / "projects",
        cache=data_root / "cache",
        outputs=data_root / "outputs",
        runs=data_root / "runs",
    )
