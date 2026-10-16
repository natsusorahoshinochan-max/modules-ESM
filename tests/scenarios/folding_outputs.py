"""Read the folding scenario outputs without choosing a real or controlled tool."""

from __future__ import annotations

from typing import Any
from tests.scenarios.folding import _decode_output


def _fold_outputs(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
) -> tuple[Any, Any, Any]:
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    materialized = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "materialize-confidence"
        and output["output_port"] == "observations"
    )
    return (
        _decode_output(
            service,
            catalog,
            projection,
            outputs["structure_candidates"],
        ),
        _decode_output(service, catalog, projection, materialized),
        _decode_output(
            service,
            catalog,
            projection,
            outputs["confidence_facts"],
        ),
    )
