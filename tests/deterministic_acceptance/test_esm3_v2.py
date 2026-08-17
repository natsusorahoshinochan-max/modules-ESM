"""Deterministic fixture acceptance for the cohesive remote ESM-3 package."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.esm3_generation import (
    ProviderClient,
    ProviderResponse,
    decode_output,
    run_generation,
    three_residue_pdb,
)


pytestmark = pytest.mark.deterministic_acceptance


def _structure_response() -> ProviderResponse:
    import torch

    return ProviderResponse(
        "ACD",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor(0.75),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pdb_string=three_residue_pdb(),
    )


def test_remote_esm3_all_modes_and_ten_pairs_are_stable_across_runs(
    tmp_path: Path,
) -> None:
    first_client = ProviderClient([ProviderResponse("ACD")])
    first_service, first_catalog, first_projection, _ = run_generation(
        tmp_path / "first",
        operation="generate_sequence",
        client=first_client,
        num_samples=1,
    )
    second_client = ProviderClient([ProviderResponse("ACD")])
    second_service, second_catalog, second_projection, _ = run_generation(
        tmp_path / "second",
        operation="generate_sequence",
        client=second_client,
        num_samples=1,
    )
    first_output = next(
        output
        for output in first_projection["outputs"]
        if output["node_id"] == "generate"
        and output["output_port"] == "sequence_candidates"
    )
    second_output = next(
        output
        for output in second_projection["outputs"]
        if output["node_id"] == "generate"
        and output["output_port"] == "sequence_candidates"
    )
    first_candidates = decode_output(
        first_service,
        first_catalog,
        first_projection,
        first_output,
    )
    second_candidates = decode_output(
        second_service,
        second_catalog,
        second_projection,
        second_output,
    )
    assert first_output["result_identity"] == second_output["result_identity"]
    assert [
        candidate.candidate_id for candidate in first_candidates.items
    ] == [
        candidate.candidate_id for candidate in second_candidates.items
    ]
    assert first_client.calls and second_client.calls

    structure_client = ProviderClient([_structure_response()])
    _, _, structure_projection, _ = run_generation(
        tmp_path / "structure",
        operation="generate_structure",
        client=structure_client,
        num_samples=1,
        sequence="ACD",
    )
    assert structure_projection["status"] == "succeeded"
    assert [call[1].track for call in structure_client.calls] == ["structure"]

    paired_client = ProviderClient(
        [
            response
            for _ in range(10)
            for response in (
                ProviderResponse("ACD"),
                _structure_response(),
            )
        ]
    )
    paired_service, paired_catalog, paired_projection, _ = run_generation(
        tmp_path / "paired",
        operation="generate_paired",
        client=paired_client,
        num_samples=10,
    )
    paired_outputs = {
        output["output_port"]: output
        for output in paired_projection["outputs"]
        if output["node_id"] == "generate"
    }
    pairs = decode_output(
        paired_service,
        paired_catalog,
        paired_projection,
        paired_outputs["counterpart_pairs"],
    )
    assert paired_projection["status"] == "succeeded"
    assert len(pairs.entries) == 10
    assert [call[1].track for call in paired_client.calls] == [
        track
        for _ in range(10)
        for track in ("sequence", "structure")
    ]
