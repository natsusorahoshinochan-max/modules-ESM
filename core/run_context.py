"""Run context passed to each module during execution."""

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, Optional
import uuid

from core.storage import (
    StoragePathError,
    contained_path,
    validate_identifier,
    validate_relative_path,
)

if TYPE_CHECKING:
    from core.run_manifest import RunManifestStore

_ACTIVE_RUN_CONTEXT: ContextVar["RunContext | None"] = ContextVar(
    "protein_workbench_run_context",
    default=None,
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
    _manifest_store: Optional["RunManifestStore"] = field(
        default=None,
        repr=False,
    )

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
            field="artifact_name",
        )

    def input_path(self, input_reference: str) -> Path:
        """Resolve an uploaded input reference beneath this project."""
        inputs_dir = contained_path(self.project_dir, "inputs")
        supplied = Path(input_reference)
        if supplied.is_absolute():
            resolved = supplied.resolve()
            if not resolved.is_relative_to(inputs_dir):
                raise StoragePathError("input_path", "Invalid input_path")
            relative_parts = resolved.relative_to(inputs_dir).parts
        else:
            relative_parts = validate_relative_path(
                input_reference,
                "input_path",
            )
            if relative_parts[:1] == ("inputs",):
                relative_parts = relative_parts[1:]
            if not relative_parts:
                raise StoragePathError("input_path", "Invalid input_path")
        return contained_path(
            inputs_dir,
            *relative_parts,
            field="input_path",
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

    def record_provider_readiness(
        self,
        provider: str,
        ready: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record readiness as a fact distinct from an actual provider call."""
        if self._manifest_store is not None:
            self._manifest_store.record_provider_readiness(
                provider=provider,
                ready=ready,
                details=details,
            )

    def record_provider_call(
        self,
        provider: str,
        operation: str,
        *,
        model: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an actual external provider operation for this Node."""
        if self._manifest_store is not None:
            call_details = {"node_id": self.node_id, **(details or {})}
            self._manifest_store.record_provider_call(
                provider=provider,
                operation=operation,
                model=model,
                details=call_details,
            )

    def activate(self) -> Token["RunContext | None"]:
        """Make this context visible to nested provider adapters."""
        return _ACTIVE_RUN_CONTEXT.set(self)

    @staticmethod
    def deactivate(token: Token["RunContext | None"]) -> None:
        _ACTIVE_RUN_CONTEXT.reset(token)

    @staticmethod
    def record_active_provider_call(
        provider: str,
        operation: str,
        *,
        model: str | None = None,
    ) -> None:
        """Record at an adapter boundary without changing adapter signatures."""
        context = _ACTIVE_RUN_CONTEXT.get()
        if context is not None:
            context.record_provider_call(
                provider,
                operation,
                model=model,
            )

    def record_artifact(
        self,
        artifact: str | Path,
        *,
        candidate_id: str | None = None,
        output_port: str | None = None,
    ) -> bool:
        """Record one output artifact by run-relative reference and digest."""
        if self._manifest_store is None or self.output_dir is None:
            return False
        return self._manifest_store.record_artifact(
            node_id=self.node_id,
            path=artifact,
            output_dir=self.output_dir,
            candidate_id=candidate_id,
            output_port=output_port,
        )
