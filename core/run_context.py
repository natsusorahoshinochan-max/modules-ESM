"""Run context passed to each module during execution."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Optional
import uuid

from core.storage import (
    contained_path,
    validate_identifier,
    validate_relative_path,
)

@dataclass
class RunContext:
    """Execution context for a single node run.

    project_dir: root directory of the project being executed.
    node_id: the executing node's ID.
    run_id: unique identifier for this execution run.
    seed: random seed for reproducibility.
    temp_dir: temporary working directory for this node.
    """

    project_dir: str
    node_id: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    seed: int = 42
    temp_dir: Optional[str] = None
    output_dir: Optional[str] = None
    log_dir: Optional[str] = None

    def __post_init__(self) -> None:
        safe_run_id = validate_identifier(self.run_id, "run_id")
        safe_node_id = validate_identifier(self.node_id, "node_id")
        project_dir = Path(self.project_dir).resolve()
        self.project_dir = str(project_dir)

        if self.temp_dir is None:
            self.temp_dir = str(contained_path(
                project_dir,
                "runs",
                safe_run_id,
                "temp",
                safe_node_id,
            ))
        else:
            self.temp_dir = str(Path(self.temp_dir).resolve())
        if self.output_dir is None:
            self.output_dir = str(contained_path(
                project_dir,
                "outputs",
                safe_run_id,
            ))
        else:
            self.output_dir = str(Path(self.output_dir).resolve())
        if self.log_dir is None:
            self.log_dir = str(contained_path(
                project_dir,
                "runs",
                safe_run_id,
                "logs",
            ))
        else:
            self.log_dir = str(Path(self.log_dir).resolve())

    def output_path(self, artifact_name: str) -> Path:
        """Resolve an artifact beneath this run's output namespace."""
        artifact_parts = validate_relative_path(
            artifact_name,
            "artifact_name",
        )
        return contained_path(
            self.output_dir or "",
            *artifact_parts,
        )

    def input_path(self, input_reference: str) -> Path:
        """Resolve an uploaded input reference beneath this project."""
        inputs_dir = contained_path(self.project_dir, "inputs")
        supplied = Path(input_reference)
        if supplied.is_absolute():
            return supplied
        relative_parts = validate_relative_path(
            input_reference,
            "input_path",
        )
        if relative_parts[:1] == ("inputs",):
            relative_parts = relative_parts[1:]
        return contained_path(
            inputs_dir,
            *relative_parts,
        )

    def temporary_file(self, *, mode: str, suffix: str, delete: bool):
        """Create a temporary file inside this run and Node namespace."""
        temp_dir = Path(self.temp_dir or "")
        temp_dir.mkdir(parents=True, exist_ok=True)
        return tempfile.NamedTemporaryFile(
            mode=mode,
            suffix=suffix,
            delete=delete,
            dir=temp_dir,
        )

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        """Yield and remove one invocation directory."""
        safe_prefix = validate_identifier(prefix, "temporary_directory_prefix")
        temp_dir = Path(self.temp_dir or "")
        temp_dir.mkdir(parents=True, exist_ok=True)
        invocation_dir = Path(
            tempfile.mkdtemp(prefix=f"{safe_prefix}-", dir=temp_dir)
        )
        try:
            yield invocation_dir
        finally:
            shutil.rmtree(invocation_dir)

    def cleanup_temporary_work(self) -> None:
        """Remove this Node's temp namespace after its worker is terminated."""
        temp_dir = Path(self.temp_dir or "")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
