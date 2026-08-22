"""Current public Workflow request and response wire codec."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.workflow.authoring import WorkflowCommit, WorkflowDraft
from core.workflow.document import (
    WORKFLOW_SCHEMA_VERSION,
    WorkflowDocument,
    WorkflowDocumentError,
    workflow_document_from_canonical,
)
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    validate_schema,
)


def decode_workflow_document(payload: Mapping[str, Any]) -> WorkflowDocument:
    """Validate and decode one closed current public Workflow document."""
    try:
        validate_schema("#/$defs/WorkflowDocument", payload)
    except ProtocolValidationError as error:
        if payload.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
            code = "unsupported_schema_version"
        elif error.path.startswith("$.contract_lock"):
            code = "contract_digest_mismatch"
        else:
            code = "malformed_request"
        raise WorkflowDocumentError(
            code,
            f"Workflow document is invalid: {error.reason}",
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
        "draft_digest": draft.draft_digest,
        "workflow": draft.workflow.canonical_projection(),
    }


def encode_workflow_commit_receipt(
    commit: WorkflowCommit,
) -> dict[str, Any]:
    """Encode one typed Commit as the compact current public receipt."""
    return {
        "accepted": True,
        "workflow_commit_id": commit.workflow_commit_id,
        "workflow_commit_revision": commit.workflow_commit_revision,
        "source_draft_revision": commit.source_draft_revision,
        "source_draft_digest": commit.source_draft_digest,
        "workflow_digest": commit.workflow_digest,
        "catalog_contract_digest": commit.catalog_contract_digest,
        "contract_lock_digest": commit.contract_lock_digest,
        "execution_plan_digest": commit.execution_plan_digest,
        "issues": [],
    }
