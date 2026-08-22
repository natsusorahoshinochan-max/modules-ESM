"""Structured terminal errors owned by Node Execution Attempt."""

from __future__ import annotations

import re
from typing import Literal
import uuid

from core.execution.ledger import StructuredError, V2RunError


_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")


def _execution_error(error: BaseException) -> StructuredError:
    error_type = type(error).__name__
    if (
        len(error_type) > 128
        or _PUBLIC_IDENTIFIER.fullmatch(error_type) is None
    ):
        error_type = "Exception"
    return StructuredError(
        code="node_execution_failed",
        message="Node execution failed safely",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details={"exception_type": error_type},
    )


def _binding_error(error: V2RunError) -> StructuredError:
    """Preserve one failed Binding gate without inventing an Operation."""
    return StructuredError(
        code=error.code,
        message=str(error),
        retryable={
            "binding_unavailable": False,
            "readiness_rejected": True,
        }[error.code],
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
