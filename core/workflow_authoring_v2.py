"""Project-scoped persistence and explicit authoring transitions for v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any

from core.parameter_contract import find_environment_parameter_field
from core.port_types import FrozenCatalog
from core.project import (
    CANONICAL_3GB1_PROJECT_ID,
    ProjectManager,
    ProjectMeta,
    ProtectedProjectError,
)
from core.storage import write_new_file
from core.workflow_v2 import (
    CompiledWorkflow,
    WorkflowCompileError,
    WorkflowDocument,
    compile_workflow,
    parse_workflow_document,
    relock_workflow,
)


_AUTHORING_RECORD_SCHEMA_VERSION = "2.1.0"
_DRAFT_RECORD_KIND = "workflow_draft"
_COMMIT_RECORD_KIND = "workflow_commit"
_REVISION_FILENAME_WIDTH = 20
_CANONICAL_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKFLOW_COMMIT_ID = re.compile(r"^workflow-commit-[0-9a-f]{64}$")


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
    """One immutable revision of an unlocked authoring Draft."""

    project_id: str
    draft_revision: int
    draft_digest: str
    workflow: WorkflowDocument

    def __post_init__(self) -> None:
        if type(self.draft_revision) is not int or self.draft_revision < 1:
            raise ValueError("Workflow Draft revision must be positive")
        if (
            type(self.draft_digest) is not str
            or _CANONICAL_DIGEST.fullmatch(self.draft_digest) is None
        ):
            raise ValueError("Workflow Draft digest must be canonical")
        if self.workflow.workflow_id != self.project_id:
            raise ValueError("Workflow Draft identity does not match Project")
        if self.workflow.contract_lock:
            raise ValueError("Workflow Draft must not contain a Contract Lock")
        if self.workflow.digest != self.draft_digest:
            raise ValueError("Workflow Draft digest does not match its Workflow")

    def to_public(self) -> dict[str, Any]:
        """Project the typed Draft to its public wire representation."""
        return {
            "project_id": self.project_id,
            "draft_revision": self.draft_revision,
            "draft_digest": self.draft_digest,
            "workflow": self.workflow.to_public(),
        }


@dataclass(frozen=True, slots=True)
class WorkflowCommit:
    """One immutable active Workflow Commit and its exact identity."""

    project_id: str
    workflow_commit_id: str
    workflow_commit_revision: int
    source_draft_revision: int
    source_draft_digest: str
    locked_workflow: WorkflowDocument
    workflow_digest: str
    catalog_contract_digest: str
    contract_lock_digest: str
    execution_plan_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.workflow_commit_revision) is not int
            or self.workflow_commit_revision < 1
        ):
            raise ValueError("Workflow Commit revision must be positive")
        if (
            type(self.source_draft_revision) is not int
            or self.source_draft_revision < 1
        ):
            raise ValueError("Workflow Commit source Draft must be positive")
        if (
            type(self.workflow_commit_id) is not str
            or _WORKFLOW_COMMIT_ID.fullmatch(self.workflow_commit_id) is None
        ):
            raise ValueError("Workflow Commit ID must be canonical")
        for field_name in (
            "source_draft_digest",
            "workflow_digest",
            "catalog_contract_digest",
            "contract_lock_digest",
            "execution_plan_digest",
        ):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or _CANONICAL_DIGEST.fullmatch(value) is None
            ):
                raise ValueError(
                    f"Workflow Commit {field_name} must be canonical"
                )
        if self.locked_workflow.workflow_id != self.project_id:
            raise ValueError("Workflow Commit identity does not match Project")
        if self.locked_workflow.digest != self.workflow_digest:
            raise ValueError("Workflow Commit Workflow digest mismatch")
        if (
            self.locked_workflow.contract_lock_digest
            != self.contract_lock_digest
        ):
            raise ValueError("Workflow Commit Contract Lock digest mismatch")
        expected_id = self.execution_plan_digest.replace(
            "sha256:",
            "workflow-commit-",
        )
        if self.workflow_commit_id != expected_id:
            raise ValueError("Workflow Commit identity digest mismatch")

    def to_public(self) -> dict[str, Any]:
        """Project the compact Commit receipt without its private Workflow."""
        return {
            "accepted": True,
            "workflow_commit_id": self.workflow_commit_id,
            "workflow_commit_revision": self.workflow_commit_revision,
            "source_draft_revision": self.source_draft_revision,
            "source_draft_digest": self.source_draft_digest,
            "workflow_digest": self.workflow_digest,
            "catalog_contract_digest": self.catalog_contract_digest,
            "contract_lock_digest": self.contract_lock_digest,
            "execution_plan_digest": self.execution_plan_digest,
            "issues": [],
        }


def _generation_error(error: WorkflowCompileError) -> WorkflowAuthoringError:
    code = (
        error.code
        if error.code in {
            "contract_digest_mismatch",
            "inactive_generation",
        }
        else "compile_rejected"
    )
    return WorkflowAuthoringError(
        code,
        str(error),
        details={"issues": [error.issue()]},
    )


def _commit_error(error: WorkflowCompileError) -> WorkflowAuthoringError:
    if error.code in {"contract_digest_mismatch", "inactive_generation"}:
        return _generation_error(error)
    return WorkflowAuthoringError(
        "compile_rejected",
        str(error),
        details={"issues": [error.issue()]},
    )


class WorkflowAuthoringService:
    """Persist exact revisions and retain immutable compiled plans privately."""

    def __init__(
        self,
        project_manager: ProjectManager,
        catalog: FrozenCatalog,
    ) -> None:
        self._projects = project_manager
        self._catalog = catalog
        self._active_commits: dict[str, WorkflowCommit] = {}
        self._committed_plans: dict[tuple[str, str], CompiledWorkflow] = {}

    def _require_project(self, project_id: str) -> ProjectMeta:
        try:
            project = self._projects.load_meta(project_id)
        except ValueError as error:
            raise WorkflowAuthoringError(
                "unsupported_schema_version",
                "Project metadata is not a supported exact v2 artifact",
                details={
                    "artifact_kind": "project",
                    "expected_schema_version": "2.1.0",
                    "received_schema_version": "unknown",
                },
            ) from error
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
        return (
            self._projects.project_dir(project_id)
            / "workflow-v2"
            / collection
        )

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
        project_dir = self._projects.project_dir(project_id)
        path = project_dir.joinpath(
            "workflow-v2",
            collection,
            self._record_name(revision),
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
            self._projects.project_dir(project_id),
            (
                "workflow-v2",
                collection,
                self._record_name(revision),
            ),
            descriptor,
        )

    @staticmethod
    def _draft_value(
        project_id: str,
        draft_revision: int,
        workflow: WorkflowDocument,
    ) -> WorkflowDraft:
        return WorkflowDraft(
            project_id=project_id,
            draft_revision=draft_revision,
            draft_digest=workflow.digest,
            workflow=workflow,
        )

    def load_draft(self, project_id: str) -> WorkflowDraft:
        """Load the latest exact unlocked Draft without compiling it."""
        self._require_project(project_id)
        return self._load_draft(project_id)

    def _load_draft(self, project_id: str) -> WorkflowDraft:
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
        return self._load_draft_revision_record(project_id, revision)

    def _load_draft_revision_record(
        self,
        project_id: str,
        revision: int,
    ) -> WorkflowDraft:
        try:
            payload = self._read_record(project_id, "drafts", revision)
            if (
                set(payload)
                != {
                    "schema_version",
                    "artifact_kind",
                    "draft_revision",
                    "draft_digest",
                    "workflow",
                }
                or payload.get("schema_version")
                != _AUTHORING_RECORD_SCHEMA_VERSION
                or payload.get("artifact_kind") != _DRAFT_RECORD_KIND
                or type(payload.get("draft_revision")) is not int
                or payload.get("draft_revision") != revision
                or not isinstance(payload.get("draft_digest"), str)
                or not isinstance(payload.get("workflow"), dict)
            ):
                raise ValueError("closed Workflow Draft schema mismatch")
            workflow = parse_workflow_document(payload["workflow"])
            if workflow.contract_lock or workflow.digest != payload["draft_digest"]:
                raise ValueError("Workflow Draft identity mismatch")
            return self._draft_value(project_id, revision, workflow)
        except (OSError, ValueError) as error:
            raise WorkflowAuthoringError(
                "unsupported_schema_version",
                "Persisted Workflow Draft is not a supported exact artifact",
                details={
                    "artifact_kind": "workflow_draft",
                    "expected_schema_version": _AUTHORING_RECORD_SCHEMA_VERSION,
                    "received_schema_version": "unknown",
                },
            ) from error

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
        for index, node in enumerate(workflow.nodes):
            for field_name, values in (
                ("node_parameters", node.node_parameters),
                ("binding_parameters", node.binding_parameters),
            ):
                unsafe_path = find_environment_parameter_field(values)
                if unsafe_path is not None:
                    raise WorkflowAuthoringError(
                        "malformed_request",
                        (
                            "Workflow parameters cannot contain Environment "
                            "Configuration, credentials, runtime paths, or "
                            "model identity"
                        ),
                        details={
                            "field_path": [
                                "workflow",
                                "nodes",
                                index,
                                field_name,
                                *unsafe_path,
                            ]
                        },
                    )
        if workflow.workflow_id != project_id:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Workflow identity must equal its Project scope",
                details={"field_path": ["workflow", "workflow_id"]},
            )
        if workflow.contract_lock:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Workflow Draft must not contain a Contract Lock",
                details={"field_path": ["workflow", "contract_lock"]},
            )

    def save_draft(
        self,
        project_id: str,
        *,
        workflow: WorkflowDocument,
    ) -> WorkflowDraft:
        """Persist an unlocked Draft without requiring it to compile."""
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
        draft = self._draft_value(
            project_id,
            draft_revision,
            workflow,
        )
        self._write_record(
            project_id,
            "drafts",
            draft_revision,
            {
                "schema_version": _AUTHORING_RECORD_SCHEMA_VERSION,
                "artifact_kind": _DRAFT_RECORD_KIND,
                "draft_revision": draft_revision,
                "draft_digest": draft.draft_digest,
                "workflow": draft.workflow.to_public(),
            },
        )
        return draft

    @staticmethod
    def _commit_value(
        *,
        project_id: str,
        locked_workflow: WorkflowDocument,
        compiled: CompiledWorkflow,
        workflow_commit_revision: int,
        source_draft_revision: int,
        source_draft_digest: str,
    ) -> WorkflowCommit:
        plan = compiled.execution_plan
        return WorkflowCommit(
            project_id=project_id,
            workflow_commit_id=plan.execution_plan_digest.replace(
                "sha256:",
                "workflow-commit-",
            ),
            workflow_commit_revision=workflow_commit_revision,
            source_draft_revision=source_draft_revision,
            source_draft_digest=source_draft_digest,
            locked_workflow=locked_workflow,
            workflow_digest=plan.workflow_digest,
            catalog_contract_digest=plan.catalog_contract_digest,
            contract_lock_digest=plan.contract_lock_digest,
            execution_plan_digest=plan.execution_plan_digest,
        )

    def _load_active_commit_record(
        self,
        project_id: str,
    ) -> WorkflowCommit:
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

    def _load_commit_revision_record(
        self,
        project_id: str,
        revision: int,
    ) -> WorkflowCommit:
        """Load one exact immutable Workflow Commit revision."""
        try:
            payload = self._read_record(project_id, "commits", revision)
            if (
                set(payload)
                != {
                    "schema_version",
                    "artifact_kind",
                    "workflow_commit_revision",
                    "source_draft_revision",
                    "source_draft_digest",
                    "workflow",
                    "receipt",
                }
                or payload.get("schema_version")
                != _AUTHORING_RECORD_SCHEMA_VERSION
                or payload.get("artifact_kind") != _COMMIT_RECORD_KIND
                or type(payload.get("workflow_commit_revision")) is not int
                or payload.get("workflow_commit_revision") != revision
                or type(payload.get("source_draft_revision")) is not int
                or payload["source_draft_revision"] < 1
                or not isinstance(payload.get("source_draft_digest"), str)
                or not isinstance(payload.get("workflow"), dict)
                or not isinstance(payload.get("receipt"), dict)
            ):
                raise ValueError("closed Workflow Commit schema mismatch")
            workflow = parse_workflow_document(payload["workflow"])
            receipt = payload["receipt"]
            expected_receipt_fields = {
                "accepted",
                "workflow_commit_id",
                "workflow_commit_revision",
                "source_draft_revision",
                "source_draft_digest",
                "workflow_digest",
                "catalog_contract_digest",
                "contract_lock_digest",
                "execution_plan_digest",
                "issues",
            }
            if set(receipt) != expected_receipt_fields:
                raise ValueError("Workflow Commit receipt schema mismatch")
            commit = WorkflowCommit(
                project_id=project_id,
                workflow_commit_id=receipt["workflow_commit_id"],
                workflow_commit_revision=receipt[
                    "workflow_commit_revision"
                ],
                source_draft_revision=receipt["source_draft_revision"],
                source_draft_digest=receipt["source_draft_digest"],
                locked_workflow=workflow,
                workflow_digest=receipt["workflow_digest"],
                catalog_contract_digest=receipt[
                    "catalog_contract_digest"
                ],
                contract_lock_digest=receipt["contract_lock_digest"],
                execution_plan_digest=receipt["execution_plan_digest"],
            )
            if (
                receipt.get("accepted") is not True
                or receipt.get("issues") != []
                or commit.workflow_commit_revision != revision
                or commit.source_draft_revision
                != payload["source_draft_revision"]
                or commit.source_draft_digest
                != payload["source_draft_digest"]
                or commit.to_public() != receipt
            ):
                raise ValueError("Workflow Commit identity mismatch")
        except (OSError, TypeError, ValueError) as error:
            raise WorkflowAuthoringError(
                "unsupported_schema_version",
                "Persisted Workflow Commit is not a supported exact artifact",
                details={
                    "artifact_kind": "workflow_commit",
                    "expected_schema_version": _AUTHORING_RECORD_SCHEMA_VERSION,
                    "received_schema_version": "unknown",
                },
            ) from error
        return commit

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

    def _hydrate_compiled_commit(
        self,
        commit: WorkflowCommit,
    ) -> CompiledWorkflow:
        key = (commit.project_id, commit.workflow_commit_id)
        compiled = self._committed_plans.get(key)
        if compiled is None:
            try:
                compiled = compile_workflow(
                    commit.locked_workflow,
                    workflow_commit_revision=(
                        commit.workflow_commit_revision
                    ),
                    catalog=self._catalog,
                )
            except WorkflowCompileError as error:
                raise _commit_error(error) from error
        expected_commit = self._commit_value(
            project_id=commit.project_id,
            locked_workflow=commit.locked_workflow,
            compiled=compiled,
            workflow_commit_revision=commit.workflow_commit_revision,
            source_draft_revision=commit.source_draft_revision,
            source_draft_digest=commit.source_draft_digest,
        )
        if expected_commit != commit:
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                (
                    "Persisted Workflow Commit does not match the exact "
                    "Execution Plan resolved from its record"
                ),
                details={
                    "workflow_commit_id": commit.workflow_commit_id,
                },
            )
        self._committed_plans[key] = compiled
        return compiled

    def commit(
        self,
        project_id: str,
        *,
        workflow: WorkflowDocument,
    ) -> WorkflowCommit:
        """Save, lock, compile, and publish one runnable Workflow Commit."""
        self._require_project(project_id)
        self._require_writable_project(project_id)
        self._validate_draft_submission(project_id, workflow)
        current_draft_revision = self._latest_record_revision(
            project_id,
            "drafts",
        )
        draft = self._publish_draft(
            project_id,
            current_draft_revision + 1,
            workflow,
        )
        workflow_commit_revision = (
            self._latest_record_revision(project_id, "commits") + 1
        )
        try:
            locked = relock_workflow(draft.workflow, self._catalog)
            compiled = compile_workflow(
                locked,
                workflow_commit_revision=workflow_commit_revision,
                catalog=self._catalog,
            )
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        commit = self._commit_value(
            project_id=project_id,
            locked_workflow=locked,
            compiled=compiled,
            workflow_commit_revision=workflow_commit_revision,
            source_draft_revision=draft.draft_revision,
            source_draft_digest=draft.draft_digest,
        )
        self._publish_commit(commit, compiled)
        return commit

    def _publish_commit(
        self,
        commit: WorkflowCommit,
        compiled: CompiledWorkflow,
    ) -> None:
        self._write_record(
            commit.project_id,
            "commits",
            commit.workflow_commit_revision,
            {
                "schema_version": _AUTHORING_RECORD_SCHEMA_VERSION,
                "artifact_kind": _COMMIT_RECORD_KIND,
                "workflow_commit_revision": (
                    commit.workflow_commit_revision
                ),
                "source_draft_revision": commit.source_draft_revision,
                "source_draft_digest": commit.source_draft_digest,
                "workflow": commit.locked_workflow.to_public(),
                "receipt": commit.to_public(),
            },
        )
        self._committed_plans[
            (commit.project_id, commit.workflow_commit_id)
        ] = compiled
        self._active_commits[commit.project_id] = commit

    def install_seed_commit(
        self,
        *,
        locked_workflow: WorkflowDocument,
        input_sources: Mapping[str, str | Path],
    ) -> WorkflowCommit | None:
        """Install or verify the exact immutable canonical seed Commit."""
        project_id = CANONICAL_3GB1_PROJECT_ID
        if locked_workflow.workflow_id != project_id:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "Seed Commit installation requires the canonical Project identity",
                details={
                    "requested_project_id": locked_workflow.workflow_id,
                },
            )
        unlocked_workflow = replace(locked_workflow, contract_lock=())
        self._validate_draft_submission(project_id, unlocked_workflow)
        try:
            relocked = relock_workflow(unlocked_workflow, self._catalog)
            if relocked != locked_workflow:
                raise WorkflowCompileError(
                    "contract_digest_mismatch",
                    (
                        "Seed Workflow Contract Lock does not equal the "
                        "current reachable Catalog closure"
                    ),
                    field_path=("contract_lock",),
                )
            compiled = compile_workflow(
                locked_workflow,
                workflow_commit_revision=1,
                catalog=self._catalog,
            )
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
        legacy_path = self._projects.project_dir(project_id) / "workflow-v2.json"
        if legacy_path.exists():
            raise WorkflowAuthoringError(
                "unsupported_schema_version",
                "Legacy seed Workflow state cannot be adopted or rewritten",
                details={
                    "artifact_kind": "workflow",
                    "expected_schema_version": (
                        _AUTHORING_RECORD_SCHEMA_VERSION
                    ),
                    "received_schema_version": "unknown",
                },
            )
        expected_draft = self._draft_value(
            project_id,
            1,
            unlocked_workflow,
        )
        expected_commit = self._commit_value(
            project_id=project_id,
            locked_workflow=locked_workflow,
            compiled=compiled,
            workflow_commit_revision=1,
            source_draft_revision=1,
            source_draft_digest=expected_draft.draft_digest,
        )
        draft_revision = self._latest_record_revision(project_id, "drafts")
        commit_revision = self._latest_record_revision(project_id, "commits")
        if draft_revision == 0 and commit_revision == 0:
            self._publish_draft(project_id, 1, unlocked_workflow)
            self._publish_commit(expected_commit, compiled)
            return expected_commit
        persisted = self._active_commit(project_id)
        if persisted != expected_commit:
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                "Seed Workflow Commit does not match the shipped Workflow",
                details={
                    "workflow_commit_id": persisted.workflow_commit_id,
                },
            )
        self._committed_plans[
            (project_id, persisted.workflow_commit_id)
        ] = compiled
        return persisted

    def require_compiled(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
    ) -> CompiledWorkflow:
        """Resolve or exactly hydrate the active immutable Execution Plan."""
        self._require_project(project_id)
        commit = self._active_commit(project_id)
        if commit.workflow_commit_id != workflow_commit_id:
            raise WorkflowAuthoringError(
                "workflow_commit_not_found",
                "The requested Workflow Commit is not active",
                details={
                    "resource_kind": "workflow_commit",
                    "resource_id": workflow_commit_id,
                },
            )
        return self._hydrate_compiled_commit(commit)

    def require_compiled_revision(
        self,
        project_id: str,
        *,
        workflow_commit_id: str,
        workflow_commit_revision: int,
    ) -> CompiledWorkflow:
        """Hydrate the exact immutable Commit named by durable Run scope."""
        self._require_project(project_id)
        commit = self._load_commit_revision_record(
            project_id,
            workflow_commit_revision,
        )
        if commit.workflow_commit_id != workflow_commit_id:
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                "Workflow Commit revision does not match Run evidence",
                details={"workflow_commit_id": workflow_commit_id},
            )
        return self._hydrate_compiled_commit(commit)
