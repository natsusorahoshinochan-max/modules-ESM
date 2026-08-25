"""Acceptance: all local ESM-3 v2 generation modes through public contracts."""

from pathlib import Path

import pytest

from tests.acceptance.retained_evidence import retain_service_run


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_local_esm3_all_generation_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.local_torch_device import expected_local_torch_device
    import esm.pretrained as esm_pretrained
    import esm.utils.constants.esm3 as esm3_constants

    from modules.esm3.local_adapter import (
        LOCAL_ESM3_SNAPSHOT_REVISION,
    )
    from protein_workbench_public.provider_environment import (
        provider_environment_configuration,
    )
    from tests.fixtures.esm3_generation import (
        decode_output,
        generation_catalog,
        run_generation,
    )

    def forbidden_data_root(_model: str) -> Path:
        pytest.fail(
            "explicit local ESM-3 execution must not use an SDK data fallback"
        )

    monkeypatch.setattr(esm3_constants, "data_root", forbidden_data_root)
    monkeypatch.setattr(esm_pretrained, "data_root", forbidden_data_root)
    monkeypatch.setattr(
        esm3_constants,
        "snapshot_download",
        lambda **_kwargs: pytest.fail(
            "explicit local ESM-3 execution must not access Hugging Face"
        ),
    )

    process_configuration = provider_environment_configuration()
    environment = process_configuration[
        ("esm3.generate_sequence.local_open", "9.0.0")
    ]["values"]
    assert all(
        process_configuration[(f"esm3.{operation}.local_open", "9.0.0")][
            "values"
        ]
        == environment
        for operation in (
            "generate_paired",
            "generate_sequence",
            "generate_structure",
        )
    )
    results = {}
    shared_catalog = generation_catalog(include_protein_io=True)
    for operation, sequence in (
        ("generate_paired", None),
        ("generate_sequence", None),
        ("generate_structure", "ACD"),
    ):
        service, catalog, projection, events = run_generation(
            tmp_path / operation,
            operation=operation,
            client=None,
            num_samples=1,
            sequence=sequence,
            binding_route="local_open",
            environment_overrides=environment,
            generation_parameters={
                "num_steps": 1,
                "temperature": 0.0,
            },
            catalog=shared_catalog,
        )
        assert projection["status"] == "succeeded"
        assert esm3_constants.data_root is forbidden_data_root
        binding_id = f"esm3.{operation}.local_open"
        binding = catalog.require_contract(
            "binding",
            binding_id,
            "9.0.0",
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
            and event["event"]["binding"]["contract_version"] == "9.0.0"
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
        results[operation] = (service, catalog, projection, events)

    paired_service, paired_catalog, paired_projection, _paired_events = results[
        "generate_paired"
    ]
    paired_outputs = {
        output["output_port"]: output
        for output in paired_projection["outputs"]
        if output["node_id"] == "generate"
    }
    sequences = decode_output(
        paired_service,
        paired_catalog,
        paired_projection,
        paired_outputs["sequence_candidates"],
    )
    structures = decode_output(
        paired_service,
        paired_catalog,
        paired_projection,
        paired_outputs["structure_candidates"],
    )
    pairing = decode_output(
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
    for operation in (
        "generate_paired",
        "generate_sequence",
        "generate_structure",
    ):
        service, catalog, projection, events = results[operation]
        retain_service_run(
            f"local-esm3-{operation.replace('_', '-')}",
            catalog=catalog,
            service=service,
            projection=projection,
            events=events,
        )
