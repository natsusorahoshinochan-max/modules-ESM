"""Current public Workflow document wire decoder."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.workflow.document import (
    WORKFLOW_SCHEMA_VERSION,
    WorkflowDocument,
    WorkflowDocumentError,
    workflow_document_from_projection,
)
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    validate_schema,
)


def decode_workflow_document(payload: Mapping[str, Any]) -> WorkflowDocument:
    """Decode one closed current public Workflow document."""
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
    return workflow_document_from_projection(payload)
