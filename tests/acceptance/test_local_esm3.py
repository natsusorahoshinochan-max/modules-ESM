"""Acceptance: all local ESM-3 v2 generation modes through public contracts."""

from pathlib import Path

import pytest

from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_local_esm3_all_generation_modes(
    readiness: dict[str, bool],
    tmp_path: Path,
) -> None:
    require_ready("local_esm3", readiness)

    from modules.provider_contract import validate_local_esm3_snapshot
    from modules.esm3.local_adapter import (
        LOCAL_ESM3_MODEL,
        LOCAL_ESM3_SNAPSHOT_REVISION,
        configured_runtime_fingerprint,
        load_local_esm3_client,
        release_local_esm3_client,
    )
    from tests.test_esm3_v2 import (
        _decode_output,
        _run_generation,
    )

    snapshot = validate_local_esm3_snapshot()
    runtime_directory = tmp_path / "runtime"
    runtime_directory.mkdir()
    fingerprint = configured_runtime_fingerprint(device="cpu")
    environment = {
        "model_snapshot_path": snapshot,
        "model_snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
        "device": "cpu",
        "runtime_directory": runtime_directory,
        "performance_settings": {},
        "resolved_runtime_fingerprint": fingerprint,
    }
    results = {}
    shared_client = None
    try:
        for operation, sequence in (
            ("generate_paired", None),
            ("generate_sequence", None),
            ("generate_structure", "ACD"),
        ):
            if operation != "generate_paired" and shared_client is None:
                shared_client = load_local_esm3_client(
                    environment,
                    model_name=LOCAL_ESM3_MODEL,
                )
            catalog, projection, events = _run_generation(
                tmp_path / operation,
                operation=operation,
                client=(
                    None if operation == "generate_paired" else shared_client
                ),
                num_samples=1,
                sequence=sequence,
                binding_route="local_open",
                environment_overrides=environment,
                generation_parameters={
                    "num_steps": 1,
                    "temperature": 0.0,
                },
                safe_environment_fingerprint=fingerprint,
                invalidation_token=fingerprint,
            )
            assert projection["status"] == "succeeded"
            invocations = [
                event["event"]
                for event in events
                if event["event"]["type"] == "engine_invocation_started"
                and event["event"]["engine_identity"].startswith(
                    "esm3.local_open."
                )
            ]
            assert len(invocations) == (
                2 if operation == "generate_paired" else 1
            )
            terminals = [
                event["event"]
                for event in events
                if event["event"]["type"] == "engine_invocation_terminal"
                and event["event"]["invocation_id"]
                in {invocation["invocation_id"] for invocation in invocations}
            ]
            assert len(terminals) == len(invocations)
            assert all(
                terminal["status"] == "succeeded" for terminal in terminals
            )
            results[operation] = (catalog, projection)
    finally:
        if shared_client is not None:
            release_local_esm3_client(shared_client)

    paired_catalog, paired_projection = results["generate_paired"]
    paired_outputs = {
        output["output_port"]: output
        for output in paired_projection["outputs"]
        if output["node_id"] == "generate"
    }
    sequences = _decode_output(
        paired_catalog,
        paired_outputs["sequence_candidates"],
    )
    structures = _decode_output(
        paired_catalog,
        paired_outputs["structure_candidates"],
    )
    pairing = _decode_output(
        paired_catalog,
        paired_outputs["counterpart_pairs"],
    )
    assert len(sequences.items) == len(structures.items) == 1
    assert structures.items[0].parent_ids == [
        sequences.items[0].candidate_id
    ]
    assert pairing.entries[0].subject_candidate_id == (
        sequences.items[0].candidate_id
    )
    assert pairing.entries[0].reference_candidate_id == (
        structures.items[0].candidate_id
    )
