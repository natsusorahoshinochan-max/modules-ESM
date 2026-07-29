"""Project-scoped persistence and explicit authoring transitions for v2."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from core.port_types import FrozenCatalog
from core.project import ProjectManager, ProtectedProjectError
from core.workflow_v2 import (
    CompiledWorkflow,
    WorkflowDocument,
    compile_workflow,
    parse_workflow_document,
    relock_workflow,
)


class WorkflowAuthoringError(RuntimeError):
    """One stable project-scoped authoring failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any],
    ) -> None:
        self.code = code
        self.details = dict(details)
        super().__init__(message)


class WorkflowAuthoringService:
    """Persist exact revisions and retain immutable compiled plans privately."""

    def __init__(
        self,
        project_manager: ProjectManager,
        catalog: FrozenCatalog,
    ) -> None:
        self._projects = project_manager
        self._catalog = catalog
        self._plans: dict[tuple[str, int, str], CompiledWorkflow] = {}

    def _require_project(self, project_id: str) -> None:
        if self._projects.load_meta(project_id) is None:
            raise WorkflowAuthoringError(
                "project_not_found",
                "Project was not found",
                details={
                    "resource_kind": "project",
                    "resource_id": project_id,
                },
            )

    def _path(self, project_id: str) -> Path:
        return self._projects.project_dir(project_id) / "workflow-v2.json"

    @staticmethod
    def _snapshot(
        project_id: str,
        workflow_revision: int,
        workflow: WorkflowDocument,
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "workflow_revision": workflow_revision,
            "workflow_digest": workflow.digest,
            "workflow": workflow.to_public(),
        }

    @staticmethod
    def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise WorkflowAuthoringError(
                "malformed_request",
                "Workflow storage target is unsafe",
                details={"field_path": ["workflow"]},
            )
        descriptor = {
            "schema_version": "2.0.0",
            **payload,
        }
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".workflow-v2-",
            suffix=".json",
            dir=path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    descriptor,
                    stream,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def load(self, project_id: str) -> dict[str, Any]:
        """Load exactly the last persisted v2 revision without repair."""
        self._require_project(project_id)
        path = self._path(project_id)
        if not path.is_file() or path.is_symlink():
            raise WorkflowAuthoringError(
                "workflow_not_found",
                "Workflow was not found",
                details={
                    "resource_kind": "workflow",
                    "resource_id": project_id,
                },
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != "2.0.0"
                or type(payload.get("workflow_revision")) is not int
                or payload["workflow_revision"] < 1
                or not isinstance(payload.get("workflow"), dict)
                or set(payload)
                != {"schema_version", "workflow_revision", "workflow"}
            ):
                raise ValueError("closed persisted Workflow schema mismatch")
            workflow = parse_workflow_document(payload["workflow"])
        except (OSError, ValueError) as error:
            raise WorkflowAuthoringError(
                "unsupported_schema_version",
                "Persisted Workflow is not a supported exact v2 artifact",
                details={
                    "artifact_kind": "workflow",
                    "expected_schema_version": "2.0.0",
                    "received_schema_version": "unknown",
                },
            ) from error
        return self._snapshot(
            project_id,
            payload["workflow_revision"],
            workflow,
        )

    def save(
        self,
        project_id: str,
        *,
        expected_workflow_revision: int,
        workflow: WorkflowDocument,
    ) -> dict[str, Any]:
        """Persist an author-supplied document without changing its Lock."""
        self._require_project(project_id)
        try:
            self._projects.assert_writable(project_id)
        except ProtectedProjectError as error:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "Protected Project cannot be changed through this scope",
                details={"requested_project_id": project_id},
            ) from error
        path = self._path(project_id)
        if path.exists():
            current = self.load(project_id)
            current_revision = current["workflow_revision"]
        else:
            current_revision = 0
        if current_revision != expected_workflow_revision:
            raise WorkflowAuthoringError(
                "compile_rejected",
                "Workflow revision does not match the persisted revision",
                details={
                    "issues": [
                        {
                            "code": "workflow_revision_conflict",
                            "severity": "error",
                            "message": (
                                "Expected Workflow revision "
                                f"{expected_workflow_revision}, observed "
                                f"{current_revision}"
                            ),
                            "field_path": ["expected_workflow_revision"],
                        }
                    ]
                },
            )
        if workflow.workflow_id != project_id:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Workflow identity must equal its Project scope",
                details={"field_path": ["workflow", "workflow_id"]},
            )
        revision = current_revision + 1
        self._atomic_write(
            path,
            {
                "workflow_revision": revision,
                "workflow": workflow.to_public(),
            },
        )
        self._plans = {
            key: compiled
            for key, compiled in self._plans.items()
            if key[0] != project_id
        }
        return self._snapshot(project_id, revision, workflow)

    def relock(
        self,
        project_id: str,
        *,
        workflow_revision: int,
    ) -> dict[str, Any]:
        """Explicitly create a new revision locked to the current Catalog."""
        current = self.load(project_id)
        if current["workflow_revision"] != workflow_revision:
            raise WorkflowAuthoringError(
                "compile_rejected",
                "Workflow revision does not match the persisted revision",
                details={
                    "issues": [
                        {
                            "code": "workflow_revision_conflict",
                            "severity": "error",
                            "message": "Relock requires the latest exact revision",
                            "field_path": ["workflow_revision"],
                        }
                    ]
                },
            )
        workflow = parse_workflow_document(current["workflow"])
        locked = relock_workflow(workflow, self._catalog)
        return self.save(
            project_id,
            expected_workflow_revision=workflow_revision,
            workflow=locked,
        )

    def compile(
        self,
        project_id: str,
        *,
        workflow_revision: int,
        workflow: WorkflowDocument,
    ) -> CompiledWorkflow:
        """Compile only the exact persisted revision and retain its plan."""
        current = self.load(project_id)
        if (
            current["workflow_revision"] != workflow_revision
            or current["workflow_digest"] != workflow.digest
        ):
            raise WorkflowAuthoringError(
                "compile_rejected",
                "Compile request does not match the persisted Workflow revision",
                details={
                    "issues": [
                        {
                            "code": "workflow_revision_conflict",
                            "severity": "error",
                            "message": (
                                "Compile requires the exact persisted Workflow "
                                "revision and digest"
                            ),
                            "field_path": ["workflow_revision"],
                        }
                    ]
                },
            )
        compiled = compile_workflow(
            workflow,
            workflow_revision=workflow_revision,
            catalog=self._catalog,
        )
        key = (
            project_id,
            workflow_revision,
            compiled.receipt["compile_id"],
        )
        self._plans[key] = compiled
        return compiled
