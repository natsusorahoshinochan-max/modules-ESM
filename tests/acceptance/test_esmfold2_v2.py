"""Source-bound acceptance for the shared v2 ESMFold2 folding Node."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from core.provider_support import validate_installed_provider_checkout
from modules.folding.esmfold2_contract import ESM_SDK_REVISION
from tests.acceptance.biohub_environment import read_biohub_token
from tests.acceptance.conftest import (
    PROJECT_ROOT,
    SEQUENCE_3GB1_SHA256,
)
from tests.test_folding_v2 import (
    _decode_output,
    _run_fold,
    _write_local_runtime_fixture,
)


SEQUENCE_3GB1 = (
    "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
)


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


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_remote_esmfold2_v2_folds_3gb1_through_exact_binding(
    tmp_path: Path,
) -> None:
    """Exercise the exact remote Binding, normalization, and typed outputs."""
    assert hashlib.sha256(SEQUENCE_3GB1.encode()).hexdigest() == (
        SEQUENCE_3GB1_SHA256
    )

    from esm.sdk.forge import SequenceStructureForgeInferenceClient
    from modules.folding.esmfold2_contract import REMOTE_ESMFOLD2_MODEL

    delegate = SequenceStructureForgeInferenceClient(
        model=REMOTE_ESMFOLD2_MODEL,
        token=read_biohub_token(),
    )
    provider_calls: list[dict[str, Any]] = []

    class RecordingClient:
        def fold(
            self,
            *,
            sequence: str,
            model_name: str,
            config: Any,
        ) -> Any:
            provider_calls.append({
                "sequence": sequence,
                "model_name": model_name,
                "config_type": (
                    f"{type(config).__module__}.{type(config).__qualname__}"
                ),
                "include_pae": config.include_pae,
                "include_embeddings": config.include_embeddings,
                "num_sampling_steps": config.num_sampling_steps,
                "num_loops": config.num_loops,
                "lm_dropout": config.lm_dropout,
                "lm_mask_pct": config.lm_mask_pct,
                "msa_max_depth": config.msa_max_depth,
                "msa_column_mask_rate": config.msa_column_mask_rate,
            })
            return delegate.fold(
                sequence=sequence,
                model_name=model_name,
                config=config,
            )

    service, catalog, projection, events = _run_fold(
        tmp_path,
        route="remote",
        client=RecordingClient(),
        source_sequence=SEQUENCE_3GB1,
    )

    assert projection["status"] == "succeeded"
    assert provider_calls == [{
        "sequence": SEQUENCE_3GB1,
        "model_name": REMOTE_ESMFOLD2_MODEL,
        "config_type": "esm.sdk.api.FoldingConfig",
        "include_pae": True,
        "include_embeddings": False,
        "num_sampling_steps": 100,
        "num_loops": 20,
        "lm_dropout": 0.3,
        "lm_mask_pct": 0.1,
        "msa_max_depth": 1024,
        "msa_column_mask_rate": 0.1,
    }]
    structures, observations, facts = _fold_outputs(
        service,
        catalog,
        projection,
    )
    assert len(structures.items) == 1
    candidate = structures.items[0]
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
        "configured_base_seed",
        "effective_call_seed",
    }.isdisjoint(candidate.metadata)
    assert candidate.parent_ids
    assert len(candidate.data.pdb_string) > 0
    values = {
        observation.metric.contract_id: observation.value
        for observation in observations.entries
    }
    assert set(values) == {
        "structure.ptm",
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
        "structure.pae",
    }
    assert 0.0 <= values["structure.ptm"] <= 1.0
    assert len(values["structure.plddt.per_residue"]) == len(SEQUENCE_3GB1)
    assert all(
        0.0 <= value <= 100.0
        for value in values["structure.plddt.per_residue"]
    )
    assert values["structure.plddt.mean_residue"] == pytest.approx(
        sum(values["structure.plddt.per_residue"]) / len(SEQUENCE_3GB1)
    )
    pae = values["structure.pae"]
    assert len(pae) == len(SEQUENCE_3GB1)
    assert all(
        len(row) == len(SEQUENCE_3GB1)
        and all(value >= 0.0 for value in row)
        for row in pae
    )
    assert len(facts.entries) == 1
    assert facts.entries[0].prediction_key == candidate.metadata[
        "prediction_key"
    ]
    assert all(
        observation.subject.candidate_id == candidate.candidate_id
        for observation in observations.entries
    )
    assert all(
        observation.residue_axis is None
        if observation.metric.contract_id == "structure.ptm"
        else observation.residue_axis is not None
        and observation.residue_axis.layout.length == len(SEQUENCE_3GB1)
        for observation in observations.entries
    )
    binding = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        "9.0.0",
    )
    method_ref = binding.descriptor["method"]
    method = catalog.require_contract(
        "method",
        method_ref["contract_id"],
        method_ref["contract_version"],
    )
    selected_invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0_sample_0"
    ]
    assert len(selected_invocations) == 1
    assert selected_invocations[0]["engine_identity"] == (
        method.contract_digest
    )
    assert selected_invocations[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "provider_uncontrolled",
        }
    }


@pytest.mark.acceptance
def test_local_esmfold2_v2_source_contract_and_native_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the installed local sources and provider-native v2 boundary."""
    from esm.utils.structure.molecular_complex import (
        MolecularComplex,
        MolecularComplexMetadata,
        MolecularComplexResult,
    )
    from modules.folding.esmfold2_contract import TRANSFORMERS_REVISION
    from modules.folding.esmfold2_local import (
        transformers_esmfold2_runtime_is_exact,
    )

    validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    assert TRANSFORMERS_REVISION == (
        "ef32577f55da19a4989cd7b22e004dc43a4998cb"
    )
    assert transformers_esmfold2_runtime_is_exact()

    native_complex = MolecularComplex(
        id="source-bound-fixture",
        sequence=["ALA", "GLY"],
        atom_positions=np.array(
            [[0.0, 0.0, 0.0], [3.8, 0.0, 0.0]],
            dtype=np.float32,
        ),
        atom_elements=np.array(["C", "C"]),
        token_to_atoms=np.array([[0, 1], [1, 2]]),
        chain_id=np.array([0, 0]),
        plddt=np.array([0.7, 0.8], dtype=np.float32),
        metadata=MolecularComplexMetadata(
            entity_lookup={0: "protein"},
            chain_lookup={0: "A"},
        ),
        atom_names=np.array(["CA", "CA"]),
        atom_hetero=np.array([False, False]),
    )
    native_result = MolecularComplexResult(
        complex=native_complex,
        plddt=torch.tensor([0.7, 0.8]),
        ptm=0.625,
        pae=torch.tensor([[0.0, 1.0], [1.0, 0.0]]),
    )

    class LocalBoundary:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def fold(
            self,
            *,
            sequence: str,
            effective_seed: int,
        ) -> MolecularComplexResult:
            self.calls.append((sequence, effective_seed))
            return native_result

    client = LocalBoundary()
    environment = _write_local_runtime_fixture(tmp_path, monkeypatch)
    service, catalog, projection, events = _run_fold(
        tmp_path,
        route="local",
        client=client,
        environment_overrides=environment,
    )

    assert projection["status"] == "succeeded"
    structures, observations, facts = _fold_outputs(
        service,
        catalog,
        projection,
    )
    assert len(client.calls) == 1
    assert client.calls[0][0] == "AG"
    metadata = structures.items[0].metadata
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(metadata)
    assert "configured_base_seed" not in metadata
    assert metadata["effective_call_seed"] == client.calls[0][1]
    values = {
        observation.metric.contract_id: observation.value
        for observation in observations.entries
    }
    assert values["structure.plddt.per_residue"] == pytest.approx(
        [70.0, 80.0]
    )
    assert values["structure.plddt.mean_residue"] == pytest.approx(75.0)
    assert values["structure.ptm"] == 0.625
    assert values["structure.pae"] == ((0.0, 1.0), (1.0, 0.0))
    assert len(facts.entries) == 1
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.esmfold2_local"
        and event["event"]["binding"]["contract_version"] == "11.0.0"
        and event["event"]["conclusion"] == "passing"
    )
    binding = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "11.0.0",
    )
    method_ref = binding.descriptor["method"]
    method = catalog.require_contract(
        "method",
        method_ref["contract_id"],
        method_ref["contract_version"],
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0_sample_0"
    ]
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {item["invocation_id"] for item in started}
    ]
    assert len(started) == len(terminals) == 1
    assert terminals[0]["status"] == "succeeded"
    assert started[0]["engine_identity"] == method.contract_digest
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": metadata["effective_call_seed"],
        }
    }
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started[0]
    )
    assert readiness_index < invocation_index
    assert {
        observation.method.contract_id
        for observation in observations.entries
    } == {"folding.fold.esmfold2_hf_1ebf0e3"}
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_local_esmfold2_v2_invokes_exact_source_bound_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.local_torch_device import expected_local_torch_device
    """Invoke the real local Engine; a fixture cannot satisfy this gate."""
    import esm.models.esmfold2 as esmfold2
    from modules.folding.esmfold2_contract import (
        LOCAL_ESMC_ARTIFACT_SHA256,
        LOCAL_ESMC_REVISION,
        LOCAL_ESMFOLD2_ARTIFACT_SHA256,
        LOCAL_ESMFOLD2_REVISION,
    )

    real_local_input_builder = esmfold2.ESMFold2InputBuilder
    provider_calls: list[dict[str, Any]] = []

    def recording_local_input_builder(
        *,
        ccd_cache: Path,
    ) -> Any:
        delegate = real_local_input_builder(ccd_cache=ccd_cache)

        class RecordingBuilder:
            def fold(
                self,
                model: Any,
                provider_input: Any,
                **kwargs: Any,
            ) -> Any:
                provider_calls.append({
                    "model_type": (
                        f"{type(model).__module__}."
                        f"{type(model).__qualname__}"
                    ),
                    "model_name_or_path": model.config._name_or_path,
                    "input_type": (
                        f"{type(provider_input).__module__}."
                        f"{type(provider_input).__qualname__}"
                    ),
                    "sequences": tuple(
                        (item.id, item.sequence)
                        for item in provider_input.sequences
                    ),
                    "fold_parameters": dict(kwargs),
                })
                return delegate.fold(model, provider_input, **kwargs)

        return RecordingBuilder()

    monkeypatch.setattr(
        esmfold2,
        "ESMFold2InputBuilder",
        recording_local_input_builder,
    )

    model_snapshot = Path(
        os.environ["PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT"]
    )
    language_snapshot = Path(
        os.environ["PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT"]
    )
    required = [
        *(model_snapshot / name for name in LOCAL_ESMFOLD2_ARTIFACT_SHA256),
        *(language_snapshot / name for name in LOCAL_ESMC_ARTIFACT_SHA256),
    ]
    missing = [str(path) for path in required if not path.exists()]
    assert missing == [], (
        "required locked local ESMFold2 assets are unavailable: "
        + ", ".join(missing)
    )
    environment = {
        "model_snapshot_path": model_snapshot,
        "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
        "language_model_snapshot_path": language_snapshot,
        "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
        "device": expected_local_torch_device(),
    }
    service, catalog, projection, events = _run_fold(
        tmp_path,
        route="local",
        client=None,
        environment_overrides=environment,
    )

    assert projection["status"] == "succeeded", projection
    structures, observations, facts = _fold_outputs(
        service,
        catalog,
        projection,
    )
    assert len(structures.items) == 1
    metadata = structures.items[0].metadata
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(metadata)
    assert "configured_base_seed" not in metadata
    assert type(metadata["effective_call_seed"]) is int
    assert len(provider_calls) == 1
    provider_call = provider_calls[0]
    assert provider_call["model_type"] == (
        "transformers.models.esmfold2.modeling_esmfold2.ESMFold2Model"
    )
    assert Path(provider_call["model_name_or_path"]).resolve() == (
        model_snapshot.resolve()
    )
    assert provider_call["input_type"] == (
        "esm.models.esmfold2."
        "StructurePredictionInput"
    )
    assert provider_call["sequences"] == (("A", "AG"),)
    assert provider_call["fold_parameters"] == {
        "num_loops": 20,
        "num_sampling_steps": 100,
        "num_diffusion_samples": 1,
        "seed": metadata["effective_call_seed"],
        "lm_dropout": 0.3,
        "lm_mask_pct": 0.1,
        "msa_max_depth": 1024,
        "msa_column_mask_rate": 0.1,
        "complex_id": "protein-workbench-fold",
    }
    assert structures.items[0].data.pdb_string
    assert {
        observation.method.contract_id
        for observation in observations.entries
    } == {"folding.fold.esmfold2_hf_1ebf0e3"}
    assert len(facts.entries) == 1
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.esmfold2_local"
        and event["event"]["binding"]["contract_version"] == "11.0.0"
        and event["event"]["conclusion"] == "passing"
    )
    binding = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "11.0.0",
    )
    method_ref = binding.descriptor["method"]
    method = catalog.require_contract(
        "method",
        method_ref["contract_id"],
        method_ref["contract_version"],
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0_sample_0"
    ]
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] == started[0]["invocation_id"]
    ]
    assert len(started) == 1
    assert [event["status"] for event in terminal] == ["succeeded"]
    assert started[0]["engine_identity"] == method.contract_digest
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": metadata["effective_call_seed"],
        },
    }
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started[0]
    )
    assert readiness_index < invocation_index
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
