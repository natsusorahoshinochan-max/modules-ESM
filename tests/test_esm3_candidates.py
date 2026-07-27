"""Public ESM3 Candidate contracts for backend repair ticket 03."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import torch

from core.run_context import RunContext
from datatypes import ProteinSequence, ProteinStructure
from tests.test_esm3 import _make_prompt


def _provider_response(
    *,
    sequence: str | None,
    coordinates: object | None = None,
    ptm: object | None = None,
    plddt: object | None = None,
    pae: object | None = None,
    pdb_string: str = "HEADER    SAMPLED\nEND\n",
) -> SimpleNamespace:
    return SimpleNamespace(
        sequence=sequence,
        coordinates=coordinates,
        ptm=ptm,
        plddt=plddt,
        pae=pae,
        to_pdb_string=MagicMock(return_value=pdb_string),
    )


def test_coordinate_free_sequence_candidate_is_truthful_and_complete() -> None:
    from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule

    response = _provider_response(sequence="AGS")
    client = MagicMock()
    client.generate.return_value = response

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateSequenceModule().run(
            {"protein_prompt": _make_prompt(3)},
            {
                "model_name": "esm3-medium-2024-08",
                "num_samples": 1,
            },
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    candidate = result["candidates"].items[0]
    assert isinstance(candidate.data, ProteinSequence)
    assert candidate.data.sequence == "AGS"
    assert candidate.metadata == {
        "provider": "biohub",
        "model": "esm3-medium-2024-08",
        "operation": "generate(track=sequence)",
        "sample_index": 0,
        "classification": "absent",
    }
    assert result["scores"].entries == []
    assert client.generate.call_args.args[1].track == "sequence"
    response.to_pdb_string.assert_not_called()


def test_coordinate_conditioned_sequence_records_reconstruction_source() -> None:
    from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule

    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
    )
    client = MagicMock()
    client.generate.return_value = response

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateSequenceModule().run(
            {"protein_prompt": _make_prompt(3, with_structure=True)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    candidate = result["candidates"].items[0]
    assert candidate.metadata["operation"] == "generate(track=sequence)"
    assert candidate.metadata["classification"] == "prompt_reconstruction"
    response.to_pdb_string.assert_not_called()


def test_coordinate_conditioned_sequence_requires_reconstruction_evidence() -> None:
    from modules.esm3_adapter import ESM3ProviderResponseError
    from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule

    response = _provider_response(
        sequence="AGS",
        coordinates=None,
        ptm=None,
        plddt=None,
    )
    client = MagicMock()
    client.generate.return_value = response

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderResponseError) as error,
    ):
        ESM3GenerateSequenceModule().run(
            {"protein_prompt": _make_prompt(3, with_structure=True)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic["field"] == "coordinates"
    response.to_pdb_string.assert_not_called()


def test_paired_outputs_are_sampled_sequence_then_structure_by_index() -> None:
    from modules.esm3_generate.module import ESM3GenerateModule

    sequence_0 = _provider_response(sequence="AGS")
    structure_0 = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.81]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pae=torch.tensor(
            [
                [0.0, 1.0, 2.0],
                [1.0, 0.0, 3.0],
                [2.0, 3.0, 0.0],
            ]
        ),
        pdb_string="HEADER    SAMPLE-0\nEND\n",
    )
    sequence_1 = _provider_response(sequence="WYC")
    structure_1 = _provider_response(
        sequence="WYC",
        coordinates=torch.ones((3, 37, 3)),
        ptm=torch.tensor([0.72]),
        plddt=torch.tensor([0.6, 0.7, 0.8]),
        pae=torch.tensor(
            [
                [0.0, 4.0, 5.0],
                [4.0, 0.0, 6.0],
                [5.0, 6.0, 0.0],
            ]
        ),
        pdb_string="HEADER    SAMPLE-1\nEND\n",
    )
    client = MagicMock()
    client.generate.side_effect = [
        sequence_0,
        structure_0,
        sequence_1,
        structure_1,
    ]

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateModule().run(
            {"protein_prompt": _make_prompt(3)},
            {
                "model_name": "esm3-medium-2024-08",
                "num_samples": 2,
            },
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert [call.args[1].track for call in client.generate.call_args_list] == [
        "sequence",
        "structure",
        "sequence",
        "structure",
    ]
    sequences = result["sequence_candidates"].items
    structures = result["structure_candidates"].items
    assert [candidate.data.sequence for candidate in sequences] == ["AGS", "WYC"]
    assert all(isinstance(candidate.data, ProteinStructure) for candidate in structures)
    assert [candidate.metadata["sample_index"] for candidate in sequences] == [0, 1]
    assert [candidate.metadata["sample_index"] for candidate in structures] == [0, 1]
    assert [candidate.metadata["operation"] for candidate in sequences] == [
        "generate(track=sequence)",
        "generate(track=sequence)",
    ]
    assert [candidate.metadata["operation"] for candidate in structures] == [
        "generate(track=structure)",
        "generate(track=structure)",
    ]
    assert [candidate.metadata["classification"] for candidate in structures] == [
        "sampled_structure",
        "sampled_structure",
    ]
    assert [candidate.parent_ids for candidate in structures] == [
        [sequences[0].candidate_id],
        [sequences[1].candidate_id],
    ]


def test_paired_structure_sampling_does_not_reuse_prompt_coordinates() -> None:
    from modules.esm3_generate.module import ESM3GenerateModule

    sequence_response = _provider_response(
        sequence="AGS",
        coordinates=torch.full((3, 37, 3), 9.0),
        ptm=torch.tensor([0.75]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
    )
    structure_response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pdb_string="HEADER    SAMPLED\nEND\n",
    )
    client = MagicMock()
    client.generate.side_effect = [sequence_response, structure_response]

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateModule().run(
            {"protein_prompt": _make_prompt(3, with_structure=True)},
            {"num_samples": 1},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    structure_input = client.generate.call_args_list[1].args[0]
    assert structure_input.sequence == "AGS"
    assert structure_input.coordinates is None
    assert (
        result["structure_candidates"].items[0].metadata["classification"]
        == "sampled_structure"
    )


def test_coordinate_free_structure_operation_is_classified_as_sampled() -> None:
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
    )
    client = MagicMock()
    client.generate.return_value = response

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateStructureModule().run(
            {"protein_prompt": _make_prompt(3)},
            {"model_name": "esm3-medium-2024-08"},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    candidate = result["candidates"].items[0]
    assert candidate.data.source == "esm3"
    assert candidate.metadata == {
        "provider": "biohub",
        "model": "esm3-medium-2024-08",
        "operation": "generate(track=structure)",
        "sample_index": 0,
        "classification": "sampled_structure",
    }


def test_structure_metrics_publish_documented_axes_and_units() -> None:
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pae=torch.tensor(
            [
                [0.0, 1.0, 2.0],
                [1.0, 0.0, 3.0],
                [2.0, 3.0, 0.0],
            ]
        ),
    )
    client = MagicMock()
    client.generate.return_value = response

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateStructureModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    scores = {score.score_id: score for score in result["scores"].entries}
    assert scores["ptm"].value == pytest.approx(0.8)
    assert scores["ptm"].details == {
        "units": "dimensionless",
        "residue_axes": [],
    }
    assert scores["pae"].value == pytest.approx(4.0 / 3.0)
    assert scores["pae"].details == {
        "matrix": [
            [0.0, 1.0, 2.0],
            [1.0, 0.0, 3.0],
            [2.0, 3.0, 0.0],
        ],
        "units": "angstrom",
        "residue_axes": ["sequence_residue", "sequence_residue"],
        "summary": "mean",
    }


def test_local_sdk_pae_special_token_axes_are_normalized_exactly() -> None:
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    raw_pae = torch.full((1, 5, 5), 99.0)
    raw_pae[0, 1:-1, 1:-1] = torch.tensor(
        [
            [0.0, 1.0, 2.0],
            [1.0, 0.0, 3.0],
            [2.0, 3.0, 0.0],
        ]
    )
    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pae=raw_pae,
    )
    client = MagicMock()
    client.generate.return_value = response

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateStructureModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    pae = next(score for score in result["scores"].entries if score.score_id == "pae")
    assert pae.details["matrix"] == [
        [0.0, 1.0, 2.0],
        [1.0, 0.0, 3.0],
        [2.0, 3.0, 0.0],
    ]


@pytest.mark.parametrize(
    ("field", "ptm", "pae", "received_shape"),
    [
        ("ptm", torch.tensor([[0.8]]), None, [1, 1]),
        ("pae", torch.tensor([0.8]), torch.zeros((1, 3, 3)), [1, 3, 3]),
    ],
)
def test_malformed_metric_shapes_fail_with_structured_diagnostic(
    field: str,
    ptm: torch.Tensor,
    pae: torch.Tensor | None,
    received_shape: list[int],
) -> None:
    from modules.esm3_adapter import ESM3ProviderResponseError
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=ptm,
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pae=pae,
    )
    client = MagicMock()
    client.generate.return_value = response

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderResponseError) as error,
    ):
        ESM3GenerateStructureModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic["code"] == "esm3_provider_response_invalid"
    assert error.value.diagnostic["field"] == field
    assert error.value.diagnostic["received"] == {"shape": received_shape}


def test_missing_declared_structure_fails_before_pdb_serialization() -> None:
    from modules.esm3_adapter import ESM3ProviderResponseError
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    response = _provider_response(
        sequence="AGS",
        coordinates=None,
        ptm=None,
        plddt=None,
        pae=None,
    )
    client = MagicMock()
    client.generate.return_value = response

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderResponseError) as error,
    ):
        ESM3GenerateStructureModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic["field"] == "coordinates"
    response.to_pdb_string.assert_not_called()


def test_returned_provider_error_fails_with_provider_diagnostic() -> None:
    from esm.sdk.api import ESMProteinError

    from modules.esm3_adapter import ESM3ProviderOperationError
    from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule

    client = MagicMock()
    client.generate.return_value = ESMProteinError(
        error_code=429,
        error_msg="provider capacity exhausted",
    )

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderOperationError) as error,
    ):
        ESM3GenerateSequenceModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic == {
        "code": "esm3_provider_operation_failed",
        "operation": "generate(track=sequence)",
        "provider_error_code": 429,
        "message": "provider capacity exhausted",
    }


def test_missing_declared_sequence_fails_with_structured_diagnostic() -> None:
    from modules.esm3_adapter import ESM3ProviderResponseError
    from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule

    client = MagicMock()
    client.generate.return_value = _provider_response(sequence=None)

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderResponseError) as error,
    ):
        ESM3GenerateSequenceModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic == {
        "code": "esm3_provider_response_invalid",
        "field": "sequence",
        "message": "sequence operation returned no sequence",
        "expected": "non-empty amino-acid sequence",
        "received": {"value": None},
    }


def test_paired_structure_sequence_mismatch_fails_the_operation() -> None:
    from modules.esm3_adapter import ESM3ProviderResponseError
    from modules.esm3_generate.module import ESM3GenerateModule

    sequence_response = _provider_response(sequence="AGS")
    structure_response = _provider_response(
        sequence="WYC",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
    )
    client = MagicMock()
    client.generate.side_effect = [sequence_response, structure_response]

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderResponseError) as error,
    ):
        ESM3GenerateModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic["field"] == "sequence"
    assert error.value.diagnostic["expected"] == "AGS"
    structure_response.to_pdb_string.assert_not_called()


def test_structure_operation_missing_declared_confidence_fails_closed() -> None:
    from modules.esm3_adapter import ESM3ProviderResponseError
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=None,
        plddt=torch.tensor([0.7, 0.8, 0.9]),
    )
    client = MagicMock()
    client.generate.return_value = response

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderResponseError) as error,
    ):
        ESM3GenerateStructureModule().run(
            {"protein_prompt": _make_prompt(3)},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic["field"] == "ptm"
    assert error.value.diagnostic["received"] == {"value": None}


def test_fully_hidden_template_is_not_classified_as_reconstruction() -> None:
    from modules.esm3_generate_structure.module import ESM3GenerateStructureModule

    prompt = _make_prompt(3, with_structure=True)
    assert prompt.structure_visibility_track is not None
    prompt.structure_visibility_track.values = [False, False, False]
    response = _provider_response(
        sequence="AGS",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.8]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
    )
    client = MagicMock()
    client.generate.return_value = response

    with patch(
        "modules.esm3_adapter.create_esm3_client",
        return_value=client,
    ):
        result = ESM3GenerateStructureModule().run(
            {"protein_prompt": prompt},
            {},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert (
        result["candidates"].items[0].metadata["classification"] == "sampled_structure"
    )


def test_late_provider_failure_does_not_return_partial_candidate_pairs() -> None:
    from esm.sdk.api import ESMProteinError

    from modules.esm3_adapter import ESM3ProviderOperationError
    from modules.esm3_generate.module import ESM3GenerateModule

    client = MagicMock()
    client.generate.side_effect = [
        _provider_response(sequence="AGS"),
        _provider_response(
            sequence="AGS",
            coordinates=torch.zeros((3, 37, 3)),
            ptm=torch.tensor([0.8]),
            plddt=torch.tensor([0.7, 0.8, 0.9]),
        ),
        _provider_response(sequence="WYC"),
        ESMProteinError(
            error_code=503,
            error_msg="structure sampling unavailable",
        ),
    ]

    with (
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=client,
        ),
        pytest.raises(ESM3ProviderOperationError) as error,
    ):
        ESM3GenerateModule().run(
            {"protein_prompt": _make_prompt(3)},
            {"num_samples": 2},
            RunContext("/tmp/test", "esm3-node", run_id="run-03"),
        )

    assert error.value.diagnostic["operation"] == "generate(track=structure)"
    assert [call.args[1].track for call in client.generate.call_args_list] == [
        "sequence",
        "structure",
        "sequence",
        "structure",
    ]
