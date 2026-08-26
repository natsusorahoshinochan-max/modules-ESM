"""Structured terminal errors owned by Node Execution Attempt."""

from __future__ import annotations

from typing import Any, Literal
import uuid

from core.execution.ledger import StructuredError, V2RunError
from core.operation import secondary_cleanup_exception_types


def _execution_error(error: BaseException) -> StructuredError:
    details: dict[str, Any] = {"exception_type": type(error).__name__}
    cleanup_exception_types = secondary_cleanup_exception_types(error)
    if cleanup_exception_types:
        details["cleanup_exception_types"] = list(cleanup_exception_types)
    return StructuredError(
        code="node_execution_failed",
        message="Node execution failed safely",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details=details,
    )


def _binding_error(error: V2RunError) -> StructuredError:
    """Preserve one failed Binding gate without inventing an Operation."""
    return StructuredError(
        code=error.code,
        message=str(error),
        retryable=True,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details=error.details,
    )


def _publication_error(
    *,
    node_id: str,
    stage: Literal[
        "typed_value_object",
        "artifact_object",
        "manifest",
    ],
) -> StructuredError:
    return StructuredError(
        code="node_publication_failed",
        message="Node result publication failed",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details={
            "node_id": node_id,
            "publication_stage": stage,
        },
    )
