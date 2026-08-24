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

    temp_dir: str

    @classmethod
    def for_node(cls, run_directory: Path, node_id: str) -> RunContext:
        """Construct one Node context from its exact Project Run scope."""
        safe_node_id = validate_identifier(node_id, "node_id")
        return cls(temp_dir=str(run_directory / "temp" / safe_node_id))

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
