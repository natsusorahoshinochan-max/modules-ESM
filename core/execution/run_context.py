"""Contained mutable workspace for one Run and Node execution attempt."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

from core.project.storage import validate_identifier


@dataclass(frozen=True, slots=True)
class RunContext:
    """Own the contained mutable namespaces for one exact Run and Node."""

    project_dir: str
    node_id: str
    run_id: str
    seed: int
    temp_dir: str
    output_dir: str
    log_dir: str

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, "run_id")
        validate_identifier(self.node_id, "node_id")
        object.__setattr__(self, "project_dir", str(Path(self.project_dir).resolve()))
        object.__setattr__(self, "temp_dir", str(Path(self.temp_dir).resolve()))
        object.__setattr__(self, "output_dir", str(Path(self.output_dir).resolve()))
        object.__setattr__(self, "log_dir", str(Path(self.log_dir).resolve()))

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        """Yield and remove one owned invocation directory."""
        safe_prefix = validate_identifier(prefix, "temporary_directory_prefix")
        temporary_root = Path(self.temp_dir)
        temporary_root.mkdir(parents=True, exist_ok=True)
        invocation_directory = Path(
            tempfile.mkdtemp(prefix=f"{safe_prefix}-", dir=temporary_root)
        )
        try:
            yield invocation_directory
        finally:
            shutil.rmtree(invocation_directory)

    def cleanup_temporary_work(self) -> None:
        """Remove this Node's temporary namespace after worker termination."""
        temporary_root = Path(self.temp_dir)
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
