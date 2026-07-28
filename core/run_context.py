"""Run context passed to each module during execution."""

import os
import secrets
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
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
    _provider_evidence_details: dict[str, Any] = field(
        default_factory=dict,
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

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        """Yield and remove one private invocation directory without links."""
        safe_prefix = validate_identifier(prefix, "temporary_directory_prefix")
        temp_dir = Path(self.temp_dir or "").absolute()
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        current_fd = os.open(temp_dir.anchor, directory_flags)
        invocation_name: str | None = None
        body_error: BaseException | None = None
        try:
            for component in temp_dir.parts[1:]:
                try:
                    next_fd = os.open(
                        component,
                        directory_flags,
                        dir_fd=current_fd,
                    )
                except FileNotFoundError:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    try:
                        next_fd = os.open(
                            component,
                            directory_flags,
                            dir_fd=current_fd,
                        )
                    except OSError as exc:
                        raise StoragePathError(
                            "temporary_directory",
                            "Invalid temporary_directory",
                        ) from exc
                except OSError as exc:
                    raise StoragePathError(
                        "temporary_directory",
                        "Invalid temporary_directory",
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd

            root_metadata = os.fstat(current_fd)
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or root_metadata.st_uid != os.getuid()
            ):
                raise StoragePathError(
                    "temporary_directory",
                    "Invalid temporary_directory",
                )
            os.fchmod(current_fd, 0o700)
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError(
                    "Private temporary directory cleanup is unavailable"
                )

            for _ in range(100):
                candidate = f"{safe_prefix}-{secrets.token_hex(12)}"
                try:
                    os.mkdir(candidate, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    continue
                invocation_name = candidate
                break
            if invocation_name is None:
                raise FileExistsError(
                    "Unable to allocate a unique temporary directory"
                )

            invocation_fd = os.open(
                invocation_name,
                directory_flags,
                dir_fd=current_fd,
            )
            try:
                metadata = os.fstat(invocation_fd)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o700
                ):
                    raise StoragePathError(
                        "temporary_directory",
                        "Invalid temporary_directory",
                    )
            finally:
                os.close(invocation_fd)
            os.fsync(current_fd)
            yield temp_dir / invocation_name
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                if invocation_name is not None:
                    try:
                        shutil.rmtree(invocation_name, dir_fd=current_fd)
                    except FileNotFoundError:
                        pass
                    os.fsync(current_fd)
            except BaseException as exc:
                cleanup_error = exc
            try:
                os.close(current_fd)
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            if cleanup_error is not None:
                if body_error is not None:
                    body_error.add_note(
                        "Temporary directory cleanup also failed: "
                        f"{type(cleanup_error).__name__}"
                    )
                else:
                    raise cleanup_error

    def cleanup_temporary_work(self) -> None:
        """Remove this Node's temp namespace after its worker is terminated."""
        temp_dir = Path(self.temp_dir or "").absolute()
        if temp_dir == Path(temp_dir.anchor):
            raise StoragePathError(
                "temporary_directory",
                "Invalid temporary_directory",
            )
        parent = temp_dir.parent
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        current_fd = os.open(parent.anchor, directory_flags)
        try:
            for component in parent.parts[1:]:
                try:
                    next_fd = os.open(
                        component,
                        directory_flags,
                        dir_fd=current_fd,
                    )
                except FileNotFoundError:
                    return
                except OSError as exc:
                    raise StoragePathError(
                        "temporary_directory",
                        "Invalid temporary_directory",
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
            try:
                metadata = os.stat(
                    temp_dir.name,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or not shutil.rmtree.avoids_symlink_attacks
            ):
                raise StoragePathError(
                    "temporary_directory",
                    "Invalid temporary_directory",
                )
            shutil.rmtree(temp_dir.name, dir_fd=current_fd)
            os.fsync(current_fd)
        finally:
            os.close(current_fd)

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
        self._provider_evidence_details = {
            "run_id": self.run_id,
            "node_id": self.node_id,
            **{
                key: value
                for key, value in (details or {}).items()
                if key in {
                    "candidate_id",
                    "candidate_ids",
                    "parent_candidate_id",
                }
            },
        }
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
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record one adapter-boundary call with Candidate provenance."""
        context = _ACTIVE_RUN_CONTEXT.get()
        if context is not None:
            context.record_provider_call(
                provider,
                operation,
                model=model,
                details=details,
            )

    @staticmethod
    def active_provider_evidence() -> dict[str, Any]:
        """Return bounded run lineage for the current adapter call."""
        context = _ACTIVE_RUN_CONTEXT.get()
        if context is None:
            return {}
        return {
            "run_id": context.run_id,
            "node_id": context.node_id,
            **context._provider_evidence_details,
        }

    def record_artifact(
        self,
        artifact: str | Path,
        *,
        candidate_id: str | None = None,
        output_port: str | None = None,
    ) -> bool:
        """Record one Candidate-bound artifact from Module code."""
        if candidate_id is None:
            raise ValueError(
                "Module artifact recording requires a Candidate ID"
            )
        if self._manifest_store is None or self.output_dir is None:
            return False
        return self._manifest_store.record_artifact(
            node_id=self.node_id,
            path=artifact,
            output_dir=self.output_dir,
            candidate_id=candidate_id,
            output_port=output_port,
        )

    def record_artifacts(
        self,
        artifacts: list[dict[str, Any]],
    ) -> bool:
        """Record one complete Candidate-bound artifact collection."""
        if any(
            artifact.get("candidate_id") is None
            or artifact.get("artifact_kind") is not None
            for artifact in artifacts
        ):
            raise ValueError(
                "Module artifact batches require Candidate bindings"
            )
        if self._manifest_store is None or self.output_dir is None:
            return False
        return self._manifest_store.record_artifacts(
            node_id=self.node_id,
            output_dir=self.output_dir,
            artifacts=artifacts,
        )

    @property
    def records_manifest(self) -> bool:
        """Whether this context has an in-process or worker manifest sink."""
        return self._manifest_store is not None
