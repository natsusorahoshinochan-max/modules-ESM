"""Current public Workflow request and response wire codec."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datatypes.i_json import admit_i_json, thaw_i_json
from core.workflow.authoring import (
    ProjectWorkspace, WorkflowCommit, WorkflowDraft, WorkflowVersion,
)
from core.workflow.document import (
    WORKFLOW_SCHEMA_VERSION,
    WorkflowDocument,
    WorkflowDocumentError,
    workflow_document_from_canonical,
)
from protein_workbench_public.protocol import (
    validate_schema,
)


def decode_workflow_document(payload: Mapping[str, Any]) -> WorkflowDocument:
    """Validate and decode one closed current public Workflow document."""
    try:
        payload = admit_i_json(payload)
        validate_schema("#/$defs/WorkflowDocument", payload)
    except ValueError as error:
        if payload.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
            code = "unsupported_schema_version"
        else:
            code = "malformed_request"
        raise WorkflowDocumentError(
            code,
            f"Workflow document is invalid: {error}",
        ) from error
    return workflow_document_from_canonical(payload)


def encode_workflow_document(workflow: WorkflowDocument) -> dict[str, Any]:
    """Encode one typed Workflow as the current public wire document."""
    return workflow.canonical_projection()


def encode_workflow_draft(draft: WorkflowDraft) -> dict[str, Any]:
    """Encode one typed Draft response in the current public schema."""
    return {
        "project_id": draft.project_id,
        "draft_revision": draft.draft_revision,
        "workflow": draft.workflow.canonical_projection(),
    }


def encode_project_workspace(workspace: ProjectWorkspace) -> dict[str, Any]:
    """Expose independently persisted Draft and opaque UI revision identities."""
    return {
        "project_id": workspace.project_id,
        "workspace_revision": workspace.workspace_revision,
        "draft": encode_workflow_draft(workspace.draft) if workspace.draft else None,
        "ui_state_revision": workspace.ui_state_revision,
        "ui_state": thaw_i_json(workspace.ui_state),
        "source_version_id": workspace.source_version_id,
        "return_workspace_revision": workspace.return_workspace_revision,
    }


def encode_workflow_version(version: WorkflowVersion) -> dict[str, Any]:
    return {
        "project_id": version.project_id, "version_id": version.version_id,
        "name": version.name, "created_at": version.created_at,
        "workspace_revision": version.workspace_revision,
        "draft_revision": version.draft_revision,
        "ui_state_revision": version.ui_state_revision,
    }


def encode_workflow_commit_receipt(
    commit: WorkflowCommit,
) -> dict[str, Any]:
    """Encode one typed Commit as the compact current public receipt."""
    return {
        "accepted": True,
        "workflow_commit_id": commit.workflow_commit_id,
        "source_draft_revision": commit.source_draft_revision,
        "workflow": commit.workflow.canonical_projection(),
        "scientific_definitions": [
            thaw_i_json(definition) for definition in commit.scientific_definitions
        ],
        "issues": [],
    }


def encode_workflow_commit_snapshot(commit: WorkflowCommit) -> dict[str, Any]:
    """Expose original persisted interpretation facts without new admission."""
    return {
        "project_id": commit.project_id,
        "workflow_commit_id": commit.workflow_commit_id,
        "source_draft_revision": commit.source_draft_revision,
        "workflow": commit.workflow.canonical_projection(),
        "scientific_definitions": [thaw_i_json(item) for item in commit.scientific_definitions],
        "scientific_identity": thaw_i_json(commit.scientific_identity),
    }
