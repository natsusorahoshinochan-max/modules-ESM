"""Typed output access and durable waits through the runtime seam."""

from __future__ import annotations
import time
from typing import Any
from core.execution.runtime import V2RunService
from core.catalog.model import FrozenCatalog

TERMINAL_WAIT_SECONDS = 5.0


def retrieve_service_typed_output_canonical_bytes(
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
    value_index: int,
) -> bytes:
    """Retrieve one canonical value through the service public behavior seam."""
    _, payload = service.typed_value(
        projection["project_id"],
        projection["run_id"],
        output["node_id"],
        output["output_port"],
        value_index,
    )
    return payload


def decode_service_typed_output_value(
    service: V2RunService,
    catalog: FrozenCatalog,
    projection: dict[str, Any],
    output: dict[str, Any],
    value_index: int = 0,
) -> Any:
    """Decode exact retrieved bytes through the descriptor's registered codec."""
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
    )
    return port_type.decode(
        retrieve_service_typed_output_canonical_bytes(
            service,
            projection,
            output,
            value_index,
        )
    )


def wait_for_service_run_terminal_events(
    service: V2RunService,
    project_id: str,
    run_id: str,
    timeout_seconds: float = TERMINAL_WAIT_SECONDS,
) -> None:
    """Wait until the durable public event ledger records Run termination."""
    deadline = time.monotonic() + timeout_seconds
    after_sequence = 0
    terminal = False
    while not terminal:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("public Run did not reach a durable terminal")
        _, after_sequence, terminal = service.wait_for_events(
            project_id,
            run_id,
            after_sequence,
            timeout_seconds=remaining,
        )
