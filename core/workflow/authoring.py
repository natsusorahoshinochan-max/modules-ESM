"""Project-scoped Workflow persistence and explicit authoring transitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import uuid

from core.catalog.model import FrozenCatalog
from core.project.manager import (
    CANONICAL_3GB1_PROJECT_ID,
    ProjectManager,
    ProjectMeta,
    ProtectedProjectError,
)
from core.project.storage import write_new_file
from core.workflow.compiler import CompilationRequest, compile
from core.workflow.document import (
    WorkflowDocument,
    _thaw_json,
    workflow_document_from_canonical,
)
from core.workflow.errors import WorkflowCompileError
from core.workflow.plan import ExecutionPlan


_REVISION_FILENAME_WIDTH = 20


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


@dataclass(frozen=True, slots=True)
class WorkflowDraft:
    """One immutable revision of an authoring Draft."""

    project_id: str
    draft_revision: int
    workflow: WorkflowDocument


@dataclass(frozen=True, slots=True)
class WorkflowCommit:
    """One immutable Workflow Commit rooted by one stable ID."""

    project_id: str
    workflow_commit_id: str
    source_draft_revision: int
    workflow: WorkflowDocument
    scientific_definitions: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class VerifiedWorkflowCommit:
    """One Commit paired with its current executable plan."""

    commit: WorkflowCommit
    execution_plan: ExecutionPlan


def _commit_error(error: WorkflowCompileError) -> WorkflowAuthoringError:
    return WorkflowAuthoringError(
        "compile_rejected",
        str(error),
        details={"issues": [error.issue()]},
    )


class WorkflowAuthoringService:
    """Persist immutable Workflow revisions and retain executable plans."""

    def __init__(
        self,
        project_manager: ProjectManager,
        catalog: FrozenCatalog,
    ) -> None:
        self._projects = project_manager
        self._catalog = catalog
        self._active_commits: dict[str, WorkflowCommit] = {}
        self._verified_commits: dict[
            tuple[str, str],
            VerifiedWorkflowCommit,
        ] = {}

    def _require_project(self, project_id: str) -> ProjectMeta:
        project = self._projects.load_meta(project_id)
        if project is None:
            raise WorkflowAuthoringError(
                "project_not_found",
                "Project was not found",
                details={
                    "resource_kind": "project",
                    "resource_id": project_id,
                },
            )
        return project

    def _record_directory(self, project_id: str, collection: str) -> Path:
        return self._projects.workflow_storage_root(project_id) / collection

    @staticmethod
    def _record_name(revision: int) -> str:
        return f"{revision:0{_REVISION_FILENAME_WIDTH}d}.json"

    def _latest_record_revision(
        self,
        project_id: str,
        collection: str,
    ) -> int:
        directory = self._record_directory(project_id, collection)
        if not directory.is_dir():
            return 0
        revisions = [
            int(path.stem)
            for path in directory.iterdir()
            if path.is_file()
            and len(path.stem) == _REVISION_FILENAME_WIDTH
            and path.stem.isascii()
            and path.stem.isdecimal()
            and path.suffix == ".json"
            and int(path.stem) >= 1
        ]
        return max(revisions, default=0)

    def _read_record(
        self,
        project_id: str,
        collection: str,
        revision: int,
    ) -> Mapping[str, Any]:
        path = (
            self._projects.workflow_storage_root(project_id)
            / collection
            / self._record_name(revision)
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Workflow authoring record must be an object")
        return payload

    def _write_record(
        self,
        project_id: str,
        collection: str,
        revision: int,
        payload: Mapping[str, Any],
    ) -> None:
        descriptor = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        write_new_file(
            self._projects.workflow_storage_root(project_id),
            (collection, self._record_name(revision)),
            descriptor,
        )

    @staticmethod
    def _draft_value(
        project_id: str,
        draft_revision: int,
        workflow: WorkflowDocument,
    ) -> WorkflowDraft:
        return WorkflowDraft(project_id, draft_revision, workflow)

    def load_draft(self, project_id: str) -> WorkflowDraft:
        """Load the latest Draft without compiling it."""
        self._require_project(project_id)
        revision = self._latest_record_revision(project_id, "drafts")
        if revision == 0:
            raise WorkflowAuthoringError(
                "workflow_draft_not_found",
                "Workflow Draft was not found",
                details={
                    "resource_kind": "workflow_draft",
                    "resource_id": project_id,
                },
            )
        payload = self._read_record(project_id, "drafts", revision)
        workflow = workflow_document_from_canonical(payload["workflow"])
        if workflow.workflow_id != project_id:
            raise ValueError("Workflow Draft belongs to another Project")
        return self._draft_value(project_id, revision, workflow)

    def _require_writable_project(self, project_id: str) -> None:
        try:
            self._projects.assert_writable(project_id)
        except ProtectedProjectError as error:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "Protected Project cannot be changed through this scope",
                details={"requested_project_id": project_id},
            ) from error

    @staticmethod
    def _validate_draft_submission(
        project_id: str,
        workflow: WorkflowDocument,
    ) -> None:
        if workflow.workflow_id != project_id:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Workflow identity must equal its Project scope",
                details={"field_path": ["workflow", "workflow_id"]},
            )

    def save_draft(
        self,
        project_id: str,
        *,
        workflow: WorkflowDocument,
    ) -> WorkflowDraft:
        """Persist a Draft without requiring it to compile."""
        self._require_project(project_id)
        self._require_writable_project(project_id)
        self._validate_draft_submission(project_id, workflow)
        revision = self._latest_record_revision(project_id, "drafts") + 1
        return self._publish_draft(project_id, revision, workflow)

    def _publish_draft(
        self,
        project_id: str,
        draft_revision: int,
        workflow: WorkflowDocument,
    ) -> WorkflowDraft:
        draft = self._draft_value(project_id, draft_revision, workflow)
        self._write_record(
            project_id,
            "drafts",
            draft_revision,
            {"workflow": draft.workflow.canonical_projection()},
        )
        return draft

    @staticmethod
    def _commit_value(
        *,
        project_id: str,
        workflow: WorkflowDocument,
        plan: ExecutionPlan,
        source_draft_revision: int,
        workflow_commit_id: str | None = None,
    ) -> WorkflowCommit:
        return WorkflowCommit(
            project_id=project_id,
            workflow_commit_id=(
                workflow_commit_id
                if workflow_commit_id is not None
                else f"workflow-commit-{uuid.uuid4().hex}"
            ),
            source_draft_revision=source_draft_revision,
            workflow=workflow,
            scientific_definitions=plan.scientific_definitions,
        )

    def _load_commit_revision_record(
        self,
        project_id: str,
        revision: int,
    ) -> WorkflowCommit:
        payload = self._read_record(project_id, "commits", revision)
        workflow = workflow_document_from_canonical(payload["workflow"])
        commit_projection = payload["commit"]
        commit_id = commit_projection["workflow_commit_id"]
        source_draft_revision = commit_projection["source_draft_revision"]
        definitions = commit_projection["scientific_definitions"]
        if (
            type(commit_id) is not str
            or type(source_draft_revision) is not int
            or not isinstance(definitions, list)
            or workflow.workflow_id != project_id
        ):
            raise ValueError("Workflow Commit record is invalid")
        return WorkflowCommit(
            project_id=project_id,
            workflow_commit_id=commit_id,
            source_draft_revision=source_draft_revision,
            workflow=workflow,
            scientific_definitions=tuple(definitions),
        )

    def _load_active_commit_record(self, project_id: str) -> WorkflowCommit:
        revision = self._latest_record_revision(project_id, "commits")
        if revision == 0:
            raise WorkflowAuthoringError(
                "workflow_commit_not_found",
                "Workflow Commit was not found",
                details={
                    "resource_kind": "workflow_commit",
                    "resource_id": project_id,
                },
            )
        return self._load_commit_revision_record(project_id, revision)

    def _active_commit(self, project_id: str) -> WorkflowCommit:
        commit = self._active_commits.get(project_id)
        if commit is None:
            commit = self._load_active_commit_record(project_id)
            self._active_commits[project_id] = commit
        return commit

    def load_active_commit(self, project_id: str) -> WorkflowCommit:
        """Load the active immutable Workflow Commit."""
        self._require_project(project_id)
        return self._active_commit(project_id)

    def _hydrate_verified_commit(
        self,
        commit: WorkflowCommit,
    ) -> VerifiedWorkflowCommit:
        key = (commit.project_id, commit.workflow_commit_id)
        verified = self._verified_commits.get(key)
        if verified is not None:
            return verified
        try:
            plan = compile(CompilationRequest(commit.workflow), self._catalog)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        if plan.scientific_definitions != commit.scientific_definitions:
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                "Workflow Commit scientific definitions do not match the "
                "current Catalog",
                details={
                    "workflow_commit_id": commit.workflow_commit_id,
                },
            )
        verified = VerifiedWorkflowCommit(commit, plan)
        self._verified_commits[key] = verified
        return verified

    def commit(
        self,
        project_id: str,
        *,
        workflow: WorkflowDocument,
    ) -> WorkflowCommit:
        """Save, compile, and publish one runnable Workflow Commit."""
        self._require_project(project_id)
        self._require_writable_project(project_id)
        self._validate_draft_submission(project_id, workflow)
        draft = self._publish_draft(
            project_id,
            self._latest_record_revision(project_id, "drafts") + 1,
            workflow,
        )
        commit_record_revision = (
            self._latest_record_revision(project_id, "commits") + 1
        )
        try:
            plan = compile(CompilationRequest(draft.workflow), self._catalog)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        commit = self._commit_value(
            project_id=project_id,
            workflow=workflow,
            plan=plan,
            source_draft_revision=draft.draft_revision,
        )
        self._publish_commit(commit, plan, commit_record_revision)
        return commit

    def _publish_commit(
        self,
        commit: WorkflowCommit,
        plan: ExecutionPlan,
        commit_record_revision: int,
    ) -> None:
        self._write_record(
            commit.project_id,
            "commits",
            commit_record_revision,
            {
                "workflow": commit.workflow.canonical_projection(),
                "commit": {
                    "workflow_commit_id": commit.workflow_commit_id,
                    "source_draft_revision": commit.source_draft_revision,
                    "scientific_definitions": [
                        _thaw_json(definition)
                        for definition in commit.scientific_definitions
                    ],
                },
            },
        )
        verified = VerifiedWorkflowCommit(commit, plan)
        self._verified_commits[
            (commit.project_id, commit.workflow_commit_id)
        ] = verified
        self._active_commits[commit.project_id] = commit

    def install_seed_commit(
        self,
        *,
        workflow: WorkflowDocument,
        input_sources: Mapping[str, str | Path],
    ) -> WorkflowCommit | None:
        """Install the canonical seed Workflow Commit."""
        project_id = CANONICAL_3GB1_PROJECT_ID
        if workflow.workflow_id != project_id:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "Seed Commit installation requires the canonical Project identity",
                details={"requested_project_id": workflow.workflow_id},
            )
        self._validate_draft_submission(project_id, workflow)
        try:
            plan = compile(CompilationRequest(workflow), self._catalog)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        project = self._projects.ensure_seed_project_v2(
            input_sources=input_sources,
        )
        if project is None:
            return None
        if not project.seed:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "Seed Commit installation requires the protected seed Project",
                details={"requested_project_id": project_id},
            )
        commit_revision = self._latest_record_revision(project_id, "commits")
        if commit_revision == 0:
            draft = self._publish_draft(project_id, 1, workflow)
            commit = self._commit_value(
                project_id=project_id,
                workflow=workflow,
                plan=plan,
                source_draft_revision=draft.draft_revision,
            )
            self._publish_commit(commit, plan, 1)
            return commit
        persisted = self._active_commit(project_id)
        if persisted.workflow != workflow:
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                "Seed Workflow Commit does not match the shipped Workflow",
                details={"workflow_commit_id": persisted.workflow_commit_id},
            )
        if persisted.scientific_definitions != plan.scientific_definitions:
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                "Seed Workflow Commit scientific definitions do not match "
                "the current Catalog",
                details={"workflow_commit_id": persisted.workflow_commit_id},
            )
        verified = VerifiedWorkflowCommit(persisted, plan)
        self._verified_commits[
            (project_id, persisted.workflow_commit_id)
        ] = verified
        return persisted

    def require_verified_commit(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
    ) -> VerifiedWorkflowCommit:
        """Resolve the immutable Commit named by its sole execution ID."""
        self._require_project(project_id)
        cached = self._verified_commits.get((project_id, workflow_commit_id))
        if cached is not None:
            return cached
        for revision in range(
            self._latest_record_revision(project_id, "commits"),
            0,
            -1,
        ):
            commit = self._load_commit_revision_record(project_id, revision)
            if commit.workflow_commit_id == workflow_commit_id:
                return self._hydrate_verified_commit(commit)
        raise WorkflowAuthoringError(
            "workflow_commit_not_found",
            "Workflow Commit was not found",
            details={
                "resource_kind": "workflow_commit",
                "resource_id": workflow_commit_id,
            },
        )
