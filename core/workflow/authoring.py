"""Project-scoped Workflow persistence and explicit authoring transitions."""

from __future__ import annotations

from core.catalog.result_adoption import AdoptedObservation, with_adopted_definitions
from core.project.adopted_input import read_adopted_snapshot
from core.project.storage import StoragePathError, validate_identifier

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, cast
import uuid

from datatypes.i_json import freeze_i_json, thaw_i_json
from core.catalog.model import FrozenCatalog
from core.catalog.declarations import NodeTypeDefinition
from core.project.manager import (
    CANONICAL_3GB1_PROJECT_ID,
    WEBUI_3GB1_PROJECT_ID,
    ProjectManager,
    ProjectInputDescriptor,
    ProjectMeta,
    ProtectedProjectError,
)
from core.project.storage import write_new_file, write_new_file_durable
from core.workflow.compiler import CompilationRequest, compile
from core.workflow.document import (
    WorkflowDocument,
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
class ProjectWorkspace:
    """One current or retained authoring position and its exact UI snapshot."""

    project_id: str
    workspace_revision: int
    draft: WorkflowDraft | None
    ui_state_revision: int
    ui_state: Mapping[str, Any]
    source_version_id: str | None
    return_workspace_revision: int | None


@dataclass(frozen=True, slots=True)
class _WorkspaceHead:
    workspace_revision: int = 0
    draft_revision: int = 0
    ui_state_revision: int = 0
    source_version_id: str | None = None
    return_workspace_revision: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowVersion:
    """A name for one immutable Draft and UI snapshot, without compilation."""

    project_id: str
    version_id: str
    name: str
    created_at: str
    workspace_revision: int
    draft_revision: int
    ui_state_revision: int


@dataclass(frozen=True, slots=True)
class WorkflowCommit:
    """One immutable Workflow Commit rooted by one stable ID."""

    project_id: str
    workflow_commit_id: str
    source_draft_revision: int
    workflow: WorkflowDocument
    scientific_definitions: tuple[Mapping[str, Any], ...]
    scientific_identity: Mapping[str, Any]


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


def _scientific_identity(plan: ExecutionPlan) -> Mapping[str, Any]:
    """Freeze admitted scientific content independent of canvas and list order."""
    return freeze_i_json({
        "nodes": [
            {
                "node_id": node.node_id,
                "node_parameters": {
                    key: thaw_i_json(value) for key, value in node.node_parameters.items()
                    if key not in node.result_identity_plan_facts.node_parameter_indirections
                },
                "project_input_parameters": list(node._runtime.project_input_parameters),
                "binding_parameters": thaw_i_json(node.binding_parameters),
                "result_identity_plan_facts": node.result_identity_plan_facts.canonical_projection(),
                "inputs": {
                    port: [
                        {"node_id": source.node_id, "output_port": source.output_port}
                        for source in sources
                    ]
                    for port, sources in sorted(node._runtime.input_sources.items())
                },
            }
            for node in sorted(plan.nodes, key=lambda item: item.node_id)
        ],
        "scientific_definitions": [thaw_i_json(item) for item in plan.scientific_definitions],
    })


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
        """Load the current workspace's Draft without compiling it."""
        self._require_project(project_id)
        head = self._read_workspace_head(project_id)
        return self._load_draft_revision(
            project_id, self._require_draft_revision(project_id, head),
        )

    @staticmethod
    def _require_draft_revision(project_id: str, head: _WorkspaceHead) -> int:
        revision = head.draft_revision
        if revision == 0:
            raise WorkflowAuthoringError(
                "workflow_draft_not_found",
                "Workflow Draft was not found",
                details={
                    "resource_kind": "workflow_draft",
                    "resource_id": project_id,
                },
            )
        return revision

    def _load_draft_revision(self, project_id: str, revision: int) -> WorkflowDraft:
        payload = self._read_record(project_id, "drafts", revision)
        workflow = workflow_document_from_canonical(payload["workflow"])
        if workflow.workflow_id != project_id:
            raise ValueError("Workflow Draft belongs to another Project")
        return self._draft_value(project_id, revision, workflow)

    def _read_workspace_head(
        self, project_id: str, revision: int | None = None,
    ) -> _WorkspaceHead:
        selected = (
            self._latest_record_revision(project_id, "workspaces")
            if revision is None else revision
        )
        if selected == 0:
            return _WorkspaceHead()
        try:
            record = self._read_record(project_id, "workspaces", selected)
        except FileNotFoundError as error:
            raise WorkflowAuthoringError(
                "workspace_not_found", "Retained workspace was not found",
                details={"resource_kind": "workspace", "resource_id": str(selected)},
            ) from error
        return _WorkspaceHead(
            selected, record["draft_revision"], record["ui_state_revision"],
            record["source_version_id"], record["return_workspace_revision"],
        )

    def _publish_workspace(
        self, project_id: str, head: _WorkspaceHead,
    ) -> _WorkspaceHead:
        """Make prepared immutable content current without reading it back."""
        revision = self._latest_record_revision(project_id, "workspaces") + 1
        self._write_record(project_id, "workspaces", revision, {
            "draft_revision": head.draft_revision,
            "ui_state_revision": head.ui_state_revision,
            "source_version_id": head.source_version_id,
            "return_workspace_revision": head.return_workspace_revision,
        })
        return replace(head, workspace_revision=revision)

    def _load_ui_state(self, project_id: str, revision: int) -> Mapping[str, Any]:
        if revision == 0:
            return freeze_i_json({})
        return freeze_i_json(self._read_record(project_id, "ui-states", revision))

    def _publish_ui_state(
        self, project_id: str, ui_state: Mapping[str, Any],
    ) -> int:
        revision = self._latest_record_revision(project_id, "ui-states") + 1
        self._write_record(project_id, "ui-states", revision, thaw_i_json(ui_state))
        return revision

    def load_workspace(
        self, project_id: str, *, revision: int | None = None,
    ) -> ProjectWorkspace:
        """Read one retained workspace; reads never switch the current work."""
        self._require_project(project_id)
        return self._workspace_value(
            project_id, self._read_workspace_head(project_id, revision),
        )

    def _workspace_value(
        self, project_id: str, head: _WorkspaceHead, *,
        draft: WorkflowDraft | None = None,
        ui_state: Mapping[str, Any] | None = None,
    ) -> ProjectWorkspace:
        if draft is None and head.draft_revision:
            draft = self._load_draft_revision(project_id, head.draft_revision)
        return ProjectWorkspace(
            project_id, head.workspace_revision, draft, head.ui_state_revision,
            self._load_ui_state(project_id, head.ui_state_revision)
            if ui_state is None else freeze_i_json(ui_state),
            head.source_version_id, head.return_workspace_revision,
        )

    def list_versions(self, project_id: str) -> tuple[WorkflowVersion, ...]:
        """List immutable named Draft/UI snapshots, newest first."""
        self._require_project(project_id)
        return self._read_versions(project_id)

    def _read_versions(self, project_id: str) -> tuple[WorkflowVersion, ...]:
        return tuple(
            WorkflowVersion(**self._read_record(project_id, "versions", revision))
            for revision in range(
                self._latest_record_revision(project_id, "versions"), 0, -1,
            )
        )

    def load_version(self, project_id: str, version_id: str) -> WorkflowVersion:
        self._require_project(project_id)
        return self._read_version(project_id, version_id)

    def _read_version(self, project_id: str, version_id: str) -> WorkflowVersion:
        for version in self._read_versions(project_id):
            if version.version_id == version_id:
                return version
        raise WorkflowAuthoringError(
            "workflow_version_not_found", "Named Workflow version was not found",
            details={"resource_kind": "workflow_version", "resource_id": version_id},
        )

    def name_version(self, project_id: str, *, name: str) -> WorkflowVersion:
        """Name the current exact Draft and UI snapshot without compiling."""
        self._require_writable_project(project_id)
        self._require_project(project_id)
        head = self._read_workspace_head(project_id)
        draft_revision = self._require_draft_revision(project_id, head)
        version = WorkflowVersion(
            project_id, f"version-{uuid.uuid4().hex}", name,
            datetime.now(timezone.utc).isoformat(),
            head.workspace_revision, draft_revision, head.ui_state_revision,
        )
        self._write_record(
            project_id, "versions",
            self._latest_record_revision(project_id, "versions") + 1,
            {
                "project_id": version.project_id, "version_id": version.version_id,
                "name": version.name, "created_at": version.created_at,
                "workspace_revision": version.workspace_revision,
                "draft_revision": version.draft_revision,
                "ui_state_revision": version.ui_state_revision,
            },
        )
        self._projects.touch(project_id)
        return version

    def fork_version(
        self, project_id: str, *, version_id: str,
        return_workspace_revision: int, workflow: WorkflowDocument,
        ui_state: Mapping[str, Any],
    ) -> ProjectWorkspace:
        """Publish the first old-version edit while preserving its return point."""
        self._require_project(project_id)
        self._require_writable_project(project_id)
        self._read_version(project_id, version_id)
        self._read_workspace_head(project_id, return_workspace_revision)
        self._validate_draft_submission(project_id, workflow)
        return self._save_workspace_content(
            project_id,
            _WorkspaceHead(
                source_version_id=version_id,
                return_workspace_revision=return_workspace_revision,
            ),
            workflow=workflow, ui_state=ui_state,
        )

    def return_workspace(
        self, project_id: str, *, workspace_revision: int,
    ) -> ProjectWorkspace:
        """Make retained work current without deleting the work being left."""
        self._require_project(project_id)
        self._require_writable_project(project_id)
        target = self._read_workspace_head(project_id, workspace_revision)
        head = self._publish_workspace(project_id, target)
        self._projects.touch(project_id)
        return self._workspace_value(project_id, head)

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

    def _compilation_request(self, project_id: str, workflow: WorkflowDocument, *, editing: bool = False) -> CompilationRequest:
        declarations = {source.node_type_id: source for source in self._catalog.result_sources}
        observations: dict[str, tuple[AdoptedObservation, ...]] = {}
        definitions: dict[tuple[str, str], Mapping[str, Any]] = {}
        for node in workflow.nodes:
            source = declarations.get(node.node_type_id)
            if source is None or 'project_input_ref' not in node.node_parameters:
                continue
            reference = node.node_parameters['project_input_ref']
            try:
                validate_identifier(reference, 'project_input_ref')
                _, payload = self._projects.read_input(project_id, reference)
            except (StoragePathError, FileNotFoundError) as error:
                if editing:
                    continue
                raise WorkflowCompileError('project_input_not_found', 'Adopted Project Input is unavailable',
                    node_id=node.node_id, field_path=('node_parameters', 'project_input_ref')) from error
            snapshot = read_adopted_snapshot(payload)
            if source.observations is not None:
                observations[node.node_id] = source.observations(snapshot['canonical_value'].encode('utf-8'))
            for saved in (snapshot, *snapshot['dependencies']):
                for definition in saved['definitions']:
                    key = (definition['contract_kind'], definition['contract_id'])
                    if key in definitions and definitions[key] != definition:
                        raise WorkflowCompileError('adopted_definition_conflict', f'Adopted inputs disagree on {key}')
                    definitions[key] = definition
        return CompilationRequest(workflow, observations, tuple(definitions.values()))

    def observation_options(self, project_id: str, workflow: WorkflowDocument, *, ranking: bool) -> list[dict[str, Any]]:
        from core.workflow.compiler import observation_options

        self._require_project(project_id)
        try:
            request = self._compilation_request(project_id, workflow, editing=True)
            try:
                catalog = with_adopted_definitions(self._catalog, request.adopted_definitions)
            except ValueError as error:
                raise WorkflowCompileError('adopted_definition_conflict', str(error)) from error
            return observation_options(workflow, catalog, ranking=ranking, adopted_observations=request.adopted_observations)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error

    def save_workspace(
        self,
        project_id: str,
        *,
        workflow: WorkflowDocument | None = None,
        ui_state: Mapping[str, Any] | None = None,
        expected_draft_revision: int | None = None,
        expected_workspace_revision: int | None = None,
    ) -> ProjectWorkspace:
        """Publish all submitted parts of one edit in a single workspace record."""
        self._require_project(project_id)
        self._require_writable_project(project_id)
        if workflow is not None:
            self._validate_draft_submission(project_id, workflow)
        current = self._read_workspace_head(project_id)
        if (
            expected_workspace_revision is not None
            and expected_workspace_revision != current.workspace_revision
        ):
            raise WorkflowAuthoringError(
                "malformed_request", "Workspace changed while the editor was open; reopen before saving",
                details={"field_path": ["expected_workspace_revision"]},
            )
        if expected_draft_revision is not None and expected_draft_revision != current.draft_revision:
            raise WorkflowAuthoringError(
                "malformed_request", "Workflow changed while the editor was open; reopen before saving",
                details={"field_path": ["expected_draft_revision"]},
            )
        return self._save_workspace_content(
            project_id, current, workflow=workflow, ui_state=ui_state,
        )

    def _save_workspace_content(
        self, project_id: str, current: _WorkspaceHead, *,
        workflow: WorkflowDocument | None = None,
        ui_state: Mapping[str, Any] | None = None,
    ) -> ProjectWorkspace:
        """Append admitted content, publish once, then touch Project metadata."""
        draft = self._append_draft(project_id, workflow) if workflow is not None else None
        ui_revision = (
            self._publish_ui_state(project_id, ui_state)
            if ui_state is not None else current.ui_state_revision
        )
        head = self._publish_workspace(
            project_id, replace(
                current,
                draft_revision=draft.draft_revision if draft is not None else current.draft_revision,
                ui_state_revision=ui_revision,
            ),
        )
        self._projects.touch(project_id)
        return self._workspace_value(project_id, head, draft=draft, ui_state=ui_state)

    def copy_project(
        self, source_project_id: str, *, name: str,
        workflow: WorkflowDocument | None = None,
        ui_state: Mapping[str, Any] | None = None,
        inputs: Mapping[str, tuple[ProjectInputDescriptor, bytes]] | None = None,
    ) -> ProjectMeta:
        """Create the first personal copy of one protected example Project."""
        source = self._require_project(source_project_id)
        if source_project_id != WEBUI_3GB1_PROJECT_ID or not source.seed:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "Only the immutable WebUI example Project can be copied",
                details={"requested_project_id": source_project_id},
            )
        return self._copy_workspace(
            source_project_id, name, workflow=workflow, ui_state=ui_state, inputs=inputs,
        )

    def duplicate_project(self, source_project_id: str, *, name: str) -> ProjectMeta:
        """Copy current authoring content and Inputs, without versions or results."""
        self._require_project(source_project_id)
        return self._copy_workspace(source_project_id, name)

    def _copy_workspace(
        self, source_project_id: str, name: str,
        *, workflow: WorkflowDocument | None = None,
        ui_state: Mapping[str, Any] | None = None,
        inputs: Mapping[str, tuple[ProjectInputDescriptor, bytes]] | None = None,
    ) -> ProjectMeta:
        head = self._read_workspace_head(source_project_id)
        source_draft = self._load_draft_revision(
            source_project_id, self._require_draft_revision(source_project_id, head),
        )
        source_workspace = self._workspace_value(
            source_project_id, head, draft=source_draft,
        )
        selected_workflow = workflow if workflow is not None else source_draft.workflow
        self._validate_draft_submission(source_project_id, selected_workflow)
        new_inputs = inputs if inputs is not None else {}
        if set(new_inputs) & set(self._projects.stored_input_references(source_project_id)):
            raise WorkflowAuthoringError(
                "malformed_request", "New Inputs must use unused references",
                details={"field_path": ["inputs"]},
            )
        referenced_inputs = self._copy_input_references(source_project_id, selected_workflow)
        with self._projects.copy_destination(
            name, copied_from_project_id=source_project_id,
        ) as target:
            for input_reference in sorted(referenced_inputs - new_inputs.keys()):
                descriptor, payload = self._projects.read_input(
                    source_project_id, input_reference,
                )
                self._projects.publish_input(
                    target.id, input_reference, payload, filename=descriptor.filename,
                )
            for input_reference, (descriptor, payload) in new_inputs.items():
                self._projects.publish_input(
                    target.id, input_reference, payload, filename=descriptor.filename,
                )
            workflow_projection = selected_workflow.canonical_projection()
            workflow_projection["workflow_id"] = target.id
            workflow = workflow_document_from_canonical(workflow_projection)
            ui_revision = self._publish_ui_state(
                target.id, ui_state if ui_state is not None else source_workspace.ui_state,
            )
            draft = self._append_draft(target.id, workflow)
            self._publish_workspace(target.id, _WorkspaceHead(
                draft_revision=draft.draft_revision, ui_state_revision=ui_revision,
            ))
        return target

    def _copy_input_references(
        self, project_id: str, workflow: WorkflowDocument,
    ) -> set[str]:
        recorded: dict[str, Mapping[str, Any]] = {}
        if self._latest_record_revision(project_id, "commits"):
            recorded = {
                definition["contract_id"]: definition["descriptor"]["node_parameters"]
                for definition in self._load_active_commit_record(project_id).scientific_definitions
                if definition["contract_kind"] == "node_type"
            }
        references: set[str] = set()
        for index, node in enumerate(workflow.nodes):
            contract = self._catalog.get_contract("node_type", node.node_type_id)
            parameters = (
                cast(NodeTypeDefinition, contract.definition).node_parameters
                if contract is not None else recorded.get(node.node_type_id)
            )
            if parameters is None:
                raise _commit_error(WorkflowCompileError(
                    "unknown_contract",
                    f"Cannot copy inputs for {node.node_type_id}: restore its module or provide a saved Node declaration",
                    node_id=node.node_id, field_path=("nodes", index, "node_type_id"),
                ))
            references.update(
                node.node_parameters[name] for name, declaration in parameters.items()
                if declaration.get("resource_kind") == "project_input" and name in node.node_parameters
            )
        return references

    def _append_draft(
        self,
        project_id: str,
        workflow: WorkflowDocument,
    ) -> WorkflowDraft:
        draft_revision = self._latest_record_revision(project_id, "drafts") + 1
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
            scientific_identity=_scientific_identity(plan),
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
            scientific_identity=freeze_i_json(commit_projection["scientific_identity"]),
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

    def load_commit(
        self, project_id: str, *, workflow_commit_id: str,
    ) -> WorkflowCommit:
        """Read immutable evidence snapshots without recompiling their science."""
        self._require_project(project_id)
        for revision in range(self._latest_record_revision(project_id, "commits"), 0, -1):
            commit = self._load_commit_revision_record(project_id, revision)
            if commit.workflow_commit_id == workflow_commit_id:
                return commit
        raise WorkflowAuthoringError(
            "workflow_commit_not_found", "Workflow Commit was not found",
            details={"resource_kind": "workflow_commit", "resource_id": workflow_commit_id},
        )

    def compare_commit_science(
        self, project_id: str, *, workflow_commit_id: str,
        workflow_project_id: str, workflow: WorkflowDocument,
    ) -> dict[str, Any]:
        """Compare current admitted Draft science to the original Commit facts."""
        original = self.load_commit(project_id, workflow_commit_id=workflow_commit_id)
        self._require_project(workflow_project_id)
        self._validate_draft_submission(workflow_project_id, workflow)
        result: dict[str, Any] = {
            "project_id": project_id, "workflow_commit_id": workflow_commit_id,
            "workflow_project_id": workflow_project_id,
            "status": "unknown", "issues": [],
        }
        try:
            plan = compile(self._compilation_request(workflow_project_id, workflow), self._catalog)
            current_identity = self._science_with_input_contents(workflow_project_id, _scientific_identity(plan))
            original_identity = self._science_with_input_contents(project_id, original.scientific_identity)
        except WorkflowCompileError as error:
            result["issues"] = [error.issue()]
            return result
        result["status"] = (
            "current" if current_identity == original_identity else "stale"
        )
        return result

    def _science_with_input_contents(
        self, project_id: str, identity: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        resolved = thaw_i_json(identity)
        for node in resolved["nodes"]:
            resources = []
            for parameter in node.pop("project_input_parameters"):
                reference = node["node_parameters"].pop(parameter)
                try:
                    descriptor = self._projects.read_input_descriptor(project_id, reference)
                except FileNotFoundError as error:
                    raise WorkflowCompileError(
                        "project_input_not_found", "Referenced Project Input is unavailable",
                        node_id=node["node_id"], field_path=("node_parameters", parameter),
                    ) from error
                resources.append({
                    "resource_kind": "project_input", "parameter_name": parameter,
                    "content_digest": descriptor.content_digest, "size": descriptor.size,
                })
            node["resolved_resource_inputs"] = resources
        return resolved

    def forget_project(self, project_id: str) -> None:
        """Release cached Commit state after permanent Project deletion."""
        self._active_commits.pop(project_id, None)
        self._verified_commits = {
            key: value for key, value in self._verified_commits.items() if key[0] != project_id
        }

    def _hydrate_verified_commit(
        self,
        commit: WorkflowCommit,
    ) -> VerifiedWorkflowCommit:
        key = (commit.project_id, commit.workflow_commit_id)
        verified = self._verified_commits.get(key)
        if verified is not None:
            return verified
        try:
            plan = compile(self._compilation_request(commit.project_id, commit.workflow), self._catalog)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        return self._admit_existing_commit(commit, plan)

    def _admit_existing_commit(
        self,
        commit: WorkflowCommit,
        plan: ExecutionPlan,
    ) -> VerifiedWorkflowCommit:
        """Retain an existing Commit only when its compiled science agrees.

        Callers compile the Commit's Workflow, or establish equality with
        the shipped Workflow before passing its Plan here.
        """
        if (
            plan.scientific_definitions != commit.scientific_definitions
            or _scientific_identity(plan) != commit.scientific_identity
        ):
            raise WorkflowAuthoringError(
                "workflow_commit_identity_mismatch",
                "Workflow Commit scientific definitions do not match the "
                "current Catalog",
                details={
                    "workflow_commit_id": commit.workflow_commit_id,
                },
            )
        verified = VerifiedWorkflowCommit(commit, plan)
        self._verified_commits[
            (commit.project_id, commit.workflow_commit_id)
        ] = verified
        return verified

    def commit(
        self,
        project_id: str,
        *,
        workflow: WorkflowDocument,
    ) -> WorkflowCommit:
        """Save, compile, and publish one runnable Workflow Commit."""
        draft = cast(WorkflowDraft, self.save_workspace(project_id, workflow=workflow).draft)
        commit_record_revision = (
            self._latest_record_revision(project_id, "commits") + 1
        )
        try:
            plan = compile(self._compilation_request(project_id, draft.workflow), self._catalog)
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
                        thaw_i_json(definition)
                        for definition in commit.scientific_definitions
                    ],
                    "scientific_identity": thaw_i_json(commit.scientific_identity),
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
        if commit_revision:
            # Installed teaching work is immutable history, not a request to run it
            # against today's module definitions. Execution validates separately.
            return self._active_commit(project_id)
        self._validate_draft_submission(project_id, workflow)
        try:
            plan = compile(self._compilation_request(project_id, workflow), self._catalog)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        draft = cast(WorkflowDraft, self._save_workspace_content(
            project_id, self._read_workspace_head(project_id), workflow=workflow,
        ).draft)
        commit = self._commit_value(
            project_id=project_id,
            workflow=workflow,
            plan=plan,
            source_draft_revision=draft.draft_revision,
        )
        self._publish_commit(commit, plan, 1)
        return commit

    def install_webui_example_commit(
        self,
        *,
        workflow: WorkflowDocument,
        input_sources: Mapping[str, str | Path],
    ) -> WorkflowCommit | None:
        """Install the distinct protected WebUI example Draft and Commit."""
        project_id = WEBUI_3GB1_PROJECT_ID
        if workflow.workflow_id != project_id:
            raise WorkflowAuthoringError(
                "cross_scope_access_denied",
                "WebUI example installation requires its fixed Project identity",
                details={"requested_project_id": workflow.workflow_id},
            )
        inputs = {}
        for reference, source in input_sources.items():
            path = Path(source)
            payload = path.read_bytes()
            descriptor = self._projects._input_descriptor(reference, payload, filename=path.name)
            inputs[reference] = (descriptor, payload)
        project = self._projects.ensure_webui_example_project(inputs=inputs)
        if project is None:
            return None
        commit_revision = self._latest_record_revision(project_id, "commits")
        if commit_revision:
            # Installed teaching work is immutable history, not a request to run it
            # against today's module definitions. Execution validates separately.
            return self._active_commit(project_id)
        self._validate_draft_submission(project_id, workflow)
        try:
            plan = compile(self._compilation_request(project_id, workflow), self._catalog)
        except WorkflowCompileError as error:
            raise _commit_error(error) from error
        draft = cast(WorkflowDraft, self._save_workspace_content(
            project_id, self._read_workspace_head(project_id), workflow=workflow,
        ).draft)
        commit = self._commit_value(
            project_id=project_id,
            workflow=workflow,
            plan=plan,
            source_draft_revision=draft.draft_revision,
        )
        self._publish_commit(commit, plan, 1)
        return commit

    def webui_example_records(self) -> tuple[tuple[tuple[str, str], bytes], ...]:
        """Snapshot the protected example's original authoring record bytes."""
        project = self._projects.require_meta(WEBUI_3GB1_PROJECT_ID)
        if not project.seed:
            raise ValueError("Example records require the protected WebUI Project")
        root = self._projects.workflow_storage_root(WEBUI_3GB1_PROJECT_ID)
        return tuple(
            ((collection, path.name), path.read_bytes())
            for collection in ("drafts", "commits", "workspaces", "ui-states")
            for path in sorted((root / collection).glob("*.json"))
        )

    def install_webui_example_records(
        self, records: tuple[tuple[tuple[str, str], bytes], ...],
    ) -> None:
        """Install original example records without regenerating a Commit ID."""
        project = self._projects.require_meta(WEBUI_3GB1_PROJECT_ID)
        if not project.seed:
            raise ValueError("Example records require the protected WebUI Project")
        destination = self._projects.workflow_storage_root(WEBUI_3GB1_PROJECT_ID)
        if destination.exists():
            if dict(self.webui_example_records()) != dict(records):
                raise ValueError("Existing WebUI example authoring records differ from the resource")
            return
        staging = Path(tempfile.mkdtemp(prefix=".webui-records-", dir=destination.parent))
        try:
            for parts, payload in records:
                write_new_file_durable(staging, parts, payload)
            staging.rename(destination)
            descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self.forget_project(WEBUI_3GB1_PROJECT_ID)

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
        return self._hydrate_verified_commit(self.load_commit(
            project_id, workflow_commit_id=workflow_commit_id,
        ))
