"""Acceptance: one offline, source-bound local ESM3 inference."""

import pytest

from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_local_esm3_sequence_boundary(readiness):
    require_ready("local_esm3", readiness)

    from esm.sdk.api import ESMProtein, GenerationConfig
    from modules.esm3_adapter import call_esm3_provider, create_esm3_client

    client = create_esm3_client("esm3_sm_open_v1")
    result = call_esm3_provider(
        client,
        ESMProtein(sequence="A_A"),
        GenerationConfig(track="sequence", num_steps=1, temperature=0.0),
        "generate(track=sequence)",
        model_name="esm3_sm_open_v1",
        effective_seed=731,
    )

    assert isinstance(result.sequence, str)
    assert len(result.sequence) == 3
