"""Source-bound acceptance for the shared v2 ESMFold2 folding Node."""

from __future__ import annotations

import hashlib
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
    assert not any(
        event["event"].get("engine_identity", "").startswith(
            "folding.esmfold2_remote."
        )
        for event in events
    )
