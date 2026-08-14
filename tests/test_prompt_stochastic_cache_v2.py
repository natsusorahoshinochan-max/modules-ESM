"""Cache and Result Identity contracts for stochastic prompt authoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.workflow_v2 import WorkflowEdge
from tests.fixtures.prompt_authoring_v2 import (
    prepare_operation,
    run_operation,
)
from tests.fixtures.public_v2 import decode_service_typed_output_value


_SOURCE_EDGE = (
    WorkflowEdge(
        "source",
        "protein_prompt",
        "author",
        "protein_prompt",
    ),
)


def _projected_prompt(
    tmp_path: Path,
    *,
    operation: str,
    parameters: dict[str, Any],
) -> tuple[str, object]:
    catalog, service, projection, _ = run_operation(
        tmp_path,
        operation=operation,
        node_parameters=parameters,
        source_edges=_SOURCE_EDGE,
    )
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
        and output["output_port"] == "protein_prompt"
    )
    return (
        output["result_identity"],
        decode_service_typed_output_value(
            service,
            catalog,
            projection,
            output,
        ),
    )


def test_exact_effective_randomness_replays_byte_equivalent_cached_prompt(
    tmp_path: Path,
) -> None:
    prepared = prepare_operation(
        tmp_path,
        operation="random_mask",
        node_parameters={
            "effective_seed": 73,
            "count": 2,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        source_edges=_SOURCE_EDGE,
    )
    try:
        first, _ = prepared.start("stochastic-first")
        second, second_events = prepared.start("stochastic-second")
    finally:
        prepared.service.shutdown()

    first_output = next(
        output
        for output in first["outputs"]
        if output["node_id"] == "author"
    )
    second_output = next(
        output
        for output in second["outputs"]
        if output["node_id"] == "author"
    )
    assert decode_service_typed_output_value(
        prepared.service,
        prepared.catalog,
        second,
        second_output,
    ) == decode_service_typed_output_value(
        prepared.service,
        prepared.catalog,
        first,
        first_output,
    )
    assert second_output["result_identity"] == first_output["result_identity"]
    assert (
        second_output["producer_provenance"]["producer_run_id"]
        == first["run_id"]
    )
    assert any(
        event["event"]["type"] == "node_attempt_terminal"
        and event["event"].get("resolution") == "cache_replayed"
        for event in second_events
    )


def test_every_stochastic_parameter_participates_in_result_identity(
    tmp_path: Path,
) -> None:
    variants = (
        {
            "effective_seed": 73,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 74,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 73,
            "count": 2,
            "track": "sequence",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 73,
            "count": 1,
            "track": "secondary_structure",
            "eligible_residue_ids": [],
        },
        {
            "effective_seed": 73,
            "count": 1,
            "track": "sequence",
            "eligible_residue_ids": ["A:1", "A:2"],
        },
    )
    outcomes = [
        _projected_prompt(
            tmp_path / str(index),
            operation="random_mask",
            parameters=parameters,
        )
        for index, parameters in enumerate((*variants, variants[0]))
    ]
    identities = [identity for identity, _ in outcomes]
    values = [value for _, value in outcomes]

    assert len(set(identities[:5])) == 5
    assert identities[-1] == identities[0]
    assert values[-1] == values[0]


@pytest.mark.parametrize(
    ("operation", "first_eligibility", "second_eligibility"),
    (
        (
            "random_mask",
            ["B:1", "A:2", "A:1"],
            ["A:1", "A:2", "B:1"],
        ),
        ("random_insert_masked", ["B", "A"], ["A", "B"]),
    ),
)
def test_effective_eligibility_set_order_does_not_change_result_identity(
    tmp_path: Path,
    operation: str,
    first_eligibility: list[str],
    second_eligibility: list[str],
) -> None:
    parameter_name = (
        "eligible_residue_ids"
        if operation == "random_mask"
        else "eligible_chain_ids"
    )
    common: dict[str, Any] = {"effective_seed": 73, "count": 1}
    if operation == "random_mask":
        common["track"] = "sequence"
    first = _projected_prompt(
        tmp_path / "first",
        operation=operation,
        parameters={**common, parameter_name: first_eligibility},
    )
    second = _projected_prompt(
        tmp_path / "second",
        operation=operation,
        parameters={**common, parameter_name: second_eligibility},
    )

    assert first == second


@pytest.mark.parametrize(
    ("operation", "explicit_eligibility"),
    (
        ("random_mask", ["A:1", "A:2", "B:1"]),
        ("random_insert_masked", ["A", "B"]),
    ),
)
def test_empty_eligibility_resolves_to_the_same_effective_full_set(
    tmp_path: Path,
    operation: str,
    explicit_eligibility: list[str],
) -> None:
    parameter_name = (
        "eligible_residue_ids"
        if operation == "random_mask"
        else "eligible_chain_ids"
    )
    common: dict[str, Any] = {"effective_seed": 73, "count": 1}
    if operation == "random_mask":
        common["track"] = "sequence"
    shorthand = _projected_prompt(
        tmp_path / "shorthand",
        operation=operation,
        parameters={**common, parameter_name: []},
    )
    explicit = _projected_prompt(
        tmp_path / "explicit",
        operation=operation,
        parameters={**common, parameter_name: explicit_eligibility},
    )

    assert shorthand == explicit
