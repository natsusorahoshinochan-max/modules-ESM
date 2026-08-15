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
    shared_client = load_local_esm3_client(
        environment,
        model_name=LOCAL_ESM3_MODEL,
    )
    try:
        for operation, sequence in (
            ("generate_paired", None),
            ("generate_sequence", None),
            ("generate_structure", "ACD"),
        ):
            service, catalog, projection, events = _run_generation(
                tmp_path / operation,
                operation=operation,
                client=shared_client,
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
            binding_id = f"esm3.{operation}.local_open"
            binding = catalog.require_contract(
                "binding",
                binding_id,
                "7.0.0",
            )
            assert binding.descriptor["method"]["contract_id"] == (
                f"esm3.{operation}.esm3_sm_open_v1_local"
            )
            assert binding.descriptor["implementation_identity"][
                "snapshot_revision"
            ] == LOCAL_ESM3_SNAPSHOT_REVISION
            assert binding.descriptor["implementation_identity"][
                "weight_sha256"
            ]
            readiness_index = next(
                index
                for index, event in enumerate(events)
                if event["event"]["type"] == "readiness_attested"
                and event["event"]["binding"]["contract_id"] == binding_id
                and event["event"]["binding"]["contract_version"] == "7.0.0"
                and event["event"]["conclusion"] == "passing"
            )
            invocations = [
                event["event"]
                for event in events
                if event["event"]["type"] == "engine_invocation_started"
                and event["event"]["engine_role"]
                in {
                    "sequence_sample",
                    "structure_sample",
                    "sequence_parent",
                    "structure_child",
                }
            ]
            assert len(invocations) == (
                2 if operation == "generate_paired" else 1
            )
            method = catalog.require_contract(
                "method",
                binding.descriptor["method"]["contract_id"],
                binding.descriptor["method"]["contract_version"],
            )
            assert {
                invocation["engine_identity"] for invocation in invocations
            } == {method.contract_digest}
            assert all(
                invocation["invocation_provenance"][
                    "effective_randomness"
                ]["control"]
                == "exact_seed"
                and type(
                    invocation["invocation_provenance"][
                        "effective_randomness"
                    ]["effective_seed"]
                )
                is int
                for invocation in invocations
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
            invocation_index = next(
                index
                for index, event in enumerate(events)
                if event["event"] == invocations[0]
            )
            assert readiness_index < invocation_index
            assert [
                event["event"]["status"]
                for event in events
                if event["event"]["type"] == "run_terminal"
            ] == ["succeeded"]
            results[operation] = (service, catalog, projection)
    finally:
        if shared_client is not None:
            release_local_esm3_client(shared_client)

    paired_service, paired_catalog, paired_projection = results[
        "generate_paired"
    ]
    paired_outputs = {
        output["output_port"]: output
        for output in paired_projection["outputs"]
        if output["node_id"] == "generate"
    }
    sequences = _decode_output(
        paired_service,
        paired_catalog,
        paired_projection,
        paired_outputs["sequence_candidates"],
    )
    structures = _decode_output(
        paired_service,
        paired_catalog,
        paired_projection,
        paired_outputs["structure_candidates"],
    )
    pairing = _decode_output(
        paired_service,
        paired_catalog,
        paired_projection,
        paired_outputs["counterpart_pairs"],
    )
    assert len(sequences.items) == len(structures.items) == 1
    assert structures.items[0].parent_ids == (
        sequences.items[0].candidate_id,
    )
    assert pairing.entries[0].subject.candidate_id == (
        sequences.items[0].candidate_id
    )
    assert pairing.entries[0].reference.candidate_id == (
        structures.items[0].candidate_id
    )
