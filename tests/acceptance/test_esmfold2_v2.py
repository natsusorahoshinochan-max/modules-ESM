"""Source-bound acceptance for the shared v2 ESMFold2 folding Node."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from modules.provider_contract import (
    ESM_SDK_REVISION,
    read_biohub_token,
    validate_installed_provider_checkout,
)
from tests.acceptance.conftest import (
    PROJECT_ROOT,
    SEQUENCE_3GB1_SHA256,
    require_ready,
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
    catalog: Any,
    projection: dict[str, Any],
) -> tuple[Any, Any, Any]:
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    return (
        _decode_output(catalog, outputs["structure_candidates"]),
        _decode_output(catalog, outputs["confidence_observations"]),
        _decode_output(catalog, outputs["pae_observations"]),
    )


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_remote_esmfold2_v2_folds_3gb1_through_exact_binding(
    readiness: dict[str, bool],
    tmp_path: Path,
) -> None:
    """Exercise the exact remote Binding, normalization, and typed outputs."""
    require_ready("biohub", readiness)
    validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    assert hashlib.sha256(SEQUENCE_3GB1.encode()).hexdigest() == (
        SEQUENCE_3GB1_SHA256
    )

    from esm.sdk.forge import SequenceStructureForgeInferenceClient
    from modules.folding.adapter import REMOTE_ESMFOLD2_MODEL

    client = SequenceStructureForgeInferenceClient(
        model=REMOTE_ESMFOLD2_MODEL,
        token=read_biohub_token(str(PROJECT_ROOT)),
    )
    catalog, projection, events = _run_fold(
        tmp_path,
        route="remote",
        client=client,
        source_sequence=SEQUENCE_3GB1,
    )

    assert projection["status"] == "succeeded"
    structures, confidence, pae = _fold_outputs(catalog, projection)
    assert len(structures.items) == 1
    candidate = structures.items[0]
    assert candidate.metadata["route"] == "remote"
    assert candidate.metadata["model"] == REMOTE_ESMFOLD2_MODEL
    assert candidate.parent_ids
    assert len(candidate.data.pdb_string) > 0
    values = {
        observation.metric.contract_id: observation.value
        for observation in confidence.entries
    }
    assert set(values) == {
        "structure.ptm",
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
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
    assert len(pae.entries) == 1
    assert len(pae.entries[0].value) == len(SEQUENCE_3GB1)
    assert all(
        len(row) == len(SEQUENCE_3GB1)
        and all(value >= 0.0 for value in row)
        for row in pae.entries[0].value
    )
    selected_invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "folding.esmfold2_remote."
        )
    ]
    assert len(selected_invocations) == 1
    assert not any(
        event["event"].get("engine_identity", "").startswith(
            "folding.esmfold2_local."
        )
        for event in events
    )


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
    from modules.folding.adapter import (
        TRANSFORMERS_REVISION,
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
    environment["provider_client"] = client
    catalog, projection, events = _run_fold(
        tmp_path,
        route="local",
        client=client,
        environment_overrides=environment,
    )

    assert projection["status"] == "succeeded"
    structures, confidence, pae = _fold_outputs(catalog, projection)
    assert len(client.calls) == 1
    assert client.calls[0][0] == "AG"
    assert structures.items[0].metadata["route"] == "local"
    values = {
        observation.metric.contract_id: observation.value
        for observation in confidence.entries
    }
    assert values["structure.plddt.per_residue"] == pytest.approx(
        [70.0, 80.0]
    )
    assert values["structure.plddt.mean_residue"] == pytest.approx(75.0)
    assert values["structure.ptm"] == 0.625
    assert pae.entries[0].value == [[0.0, 1.0], [1.0, 0.0]]
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.esmfold2_local"
        and event["event"]["binding"]["contract_version"] == "2.1.0"
        and event["event"]["conclusion"] == "passing"
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "folding.esmfold2_local."
        )
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
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] == started[0]
    )
    assert readiness_index < invocation_index
    assert {
        observation.method.contract_id
        for observation in (*confidence.entries, *pae.entries)
    } == {"folding.fold.esmfold2_hf_1ebf0e3"}
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
    assert not any(
        event["event"].get("engine_identity", "").startswith(
            "folding.esmfold2_remote."
        )
        for event in events
    )


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_local_esmfold2_v2_invokes_exact_source_bound_assets(
    tmp_path: Path,
) -> None:
    """Invoke the real local Engine; a fixture cannot satisfy this gate."""
    from modules.folding.adapter import (
        LOCAL_ESMC_ARTIFACT_SHA256,
        LOCAL_ESMC_REVISION,
        LOCAL_ESMFOLD2_ARTIFACT_SHA256,
        LOCAL_ESMFOLD2_REVISION,
        configured_local_runtime_fingerprint,
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
    runtime_directory = tmp_path / "runtime"
    runtime_directory.mkdir()
    fingerprint = configured_local_runtime_fingerprint()
    environment = {
        "model_snapshot_path": model_snapshot,
        "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
        "language_model_snapshot_path": language_snapshot,
        "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
        "device": "cpu",
        "runtime_directory": runtime_directory,
        "resolved_runtime_fingerprint": fingerprint,
    }
    catalog, projection, events = _run_fold(
        tmp_path,
        route="local",
        client=None,
        environment_overrides=environment,
        safe_environment_fingerprint=fingerprint,
    )

    assert projection["status"] == "succeeded", projection
    structures, confidence, pae = _fold_outputs(catalog, projection)
    assert len(structures.items) == 1
    assert structures.items[0].metadata["route"] == "local"
    assert structures.items[0].data.pdb_string
    assert {
        observation.method.contract_id
        for observation in (*confidence.entries, *pae.entries)
    } == {"folding.fold.esmfold2_hf_1ebf0e3"}
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.esmfold2_local"
        and event["event"]["conclusion"] == "passing"
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "folding.esmfold2_local."
        )
    ]
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] == started[0]["invocation_id"]
    ]
    assert len(started) == 1
    assert [event["status"] for event in terminal] == ["succeeded"]
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
    assert not any(
        event["event"].get("engine_identity", "").startswith(
            "folding.esmfold2_remote."
        )
        for event in events
    )
