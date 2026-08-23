"""Public-wire projections for tests exercising typed Run Ledger APIs."""

from __future__ import annotations

from typing import Any

from protein_workbench_public.ledger_codec import (
    encode_event,
    encode_run_projection,
)


def public_run_projection(
    runtime: Any,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Encode one typed projection for an explicit public-wire assertion."""
    return encode_run_projection(runtime.projection(project_id, run_id))


def public_run_events(
    runtime: Any,
    project_id: str,
    run_id: str,
) -> tuple[dict[str, Any], ...]:
    """Encode typed runtime events only for explicit public-wire assertions."""
    return tuple(
        encode_event(
            project_id=project_id,
            run_id=run_id,
            fact=fact,
        )
        for fact in runtime.events(project_id, run_id)
    )
