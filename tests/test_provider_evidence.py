"""Provider evidence is emitted only by completed adapter-boundary calls."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from core import Workflow
from core.run_context import RunContext
from core.run_manifest import RunManifest, RunManifestStore, read_run_manifest
from datatypes import ProteinSequence, ProteinStructure, StructureAlignment


_AMBIGUOUS_REFERENCE_SEQUENCE = (
    "GTSAGTATSTSTGGSTGGGAGTAGTSGASGTGGGGSAATS"
)
_AMBIGUOUS_MOBILE_SEQUENCE = (
    "SATSGTTSSASAAGTAAASTTGSTSGSSSGTTTTTASAAGSGSS"
)


def _repetitive_alignment_pdb(sequence: str) -> str:
    residue_names = {
        "A": "ALA",
        "G": "GLY",
        "S": "SER",
        "T": "THR",
    }
    return "\n".join([
        *[
            (
                f"ATOM  {index:5d}  CA  "
                f"{residue_names[amino_acid]} A{index:4d}    "
                f"{index * 1.5:8.3f}{index % 3:8.3f}"
                f"{index % 2:8.3f}  1.00  0.00           C"
            )
            for index, amino_acid in enumerate(sequence, start=1)
        ],
        "END",
        "",
    ])


def _enable_gate(monkeypatch, tmp_path: Path, tier: str) -> Path:
    evidence_path = tmp_path / "provider-calls.jsonl"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE",
        str(evidence_path),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_REAL_GATE_NONCE", "fresh-test-nonce")
    monkeypatch.setenv("PROTEIN_WORKBENCH_VERIFICATION_TIER", tier)
    return evidence_path


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_esm3_boundary_records_completed_call_not_prompt_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.esm3_adapter import call_esm3_provider

    evidence_path = _enable_gate(monkeypatch, tmp_path, "live-provider")
    client = MagicMock()
    provider_result = MagicMock()
    provider_result.sequence = "PRIVATESEQUENCE"
    client.generate.return_value = provider_result

    result = call_esm3_provider(
        client,
        MagicMock(),
        MagicMock(),
        "esm3.generate_sequence",
        model_name="esm3-medium-2024-08",
        effective_seed=None,
    )

    assert result is provider_result
    events = _events(evidence_path)
    assert len(events) == 1
    assert events[0]["provider"] == "biohub"
    assert events[0]["operation"] == "esm3.generate_sequence"
    assert events[0]["result"]["status"] == "succeeded"
    assert events[0]["result"]["summary"]["output_sequence_length"] == 15
    assert len(
        events[0]["result"]["summary"]["output_sequence_sha256"]
    ) == 64
    assert "PRIVATESEQUENCE" not in evidence_path.read_text()


def test_esmfold_boundary_records_result_digest_without_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.esmfold2_adapter import fold_sequence

    evidence_path = _enable_gate(monkeypatch, tmp_path, "live-provider")
    provider_result = MagicMock()
    provider_result.ptm = None
    provider_result.plddt = None
    provider_result.pae = None
    provider_result.output_embedding_pair_pooled = None
    chain = MagicMock()
    chain.infer_oxygen.return_value = chain
    chain.to_pdb_string.return_value = (
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000\nEND\n"
    )
    provider_result.to_protein_chain.return_value = chain
    client = MagicMock()
    client.fold.return_value = provider_result

    with (
        patch(
            "modules.esmfold2_adapter.read_biohub_token",
            return_value="secret-test-token",
        ),
        patch(
            "esm.sdk.forge.SequenceStructureForgeInferenceClient",
            return_value=client,
        ),
    ):
        fold_sequence(ProteinSequence(sequence="AAA"))

    event = _events(evidence_path)[0]
    assert event["operation"] == "esmfold2.fold"
    assert event["result"]["summary"]["input_sequence_length"] == 3
    assert len(event["result"]["summary"]["input_sequence_sha256"]) == 64
    assert event["result"]["summary"]["pdb_bytes"] > 0
    assert len(event["result"]["summary"]["pdb_sha256"]) == 64
    assert "secret-test-token" not in evidence_path.read_text()


def test_proteinmpnn_design_boundary_records_seed_and_result_digests(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.proteinmpnn.adapter import design_sequences

    class Provider:
        provider_identity = "local-proteinmpnn"

        def parse_structure(self, pdb_string: str) -> list[dict]:
            return [{"name": "target", "seq": "AAA", "seq_chain_A": "AAA"}]

        def design(self, request) -> tuple[list[ProteinSequence], list[float]]:
            return [ProteinSequence(sequence="GAA")], [-1.25]

    evidence_path = _enable_gate(monkeypatch, tmp_path, "heavy-model")
    sequences, scores = design_sequences(
        pdb_string="PRIVATE PDB INPUT",
        num_sequences=1,
        seed=731,
        provider=Provider(),
    )

    assert sequences[0].sequence == "GAA"
    assert scores == [-1.25]
    event = _events(evidence_path)[0]
    assert event["operation"] == "design_sequences"
    assert event["effective_seed"] == 731
    assert event["result"]["summary"]["sequence_count"] == 1
    assert len(event["result"]["summary"]["input_pdb_sha256"]) == 64
    assert len(event["result"]["summary"]["sequence_sha256"][0]) == 64
    retained = evidence_path.read_text()
    assert "PRIVATE PDB INPUT" not in retained
    assert '"GAA"' not in retained


def test_proteinmpnn_scoring_boundary_records_completed_score(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.proteinmpnn.adapter import score_sequence

    evidence_path = _enable_gate(monkeypatch, tmp_path, "heavy-model")
    with (
        patch(
            "modules.proteinmpnn.adapter._load_model",
            return_value=(object(), "cpu"),
        ),
        patch(
            "modules.proteinmpnn.adapter._parse_structure",
            return_value=[
                {"name": "target", "seq": "AAA", "seq_chain_A": "AAA"}
            ],
        ),
        patch("modules.proteinmpnn.adapter._featurize", return_value=object()),
        patch("modules.proteinmpnn.adapter._compute_score", return_value=-2.5),
    ):
        score = score_sequence(
            pdb_string="PRIVATE PDB INPUT",
            sequence="AAA",
            model_name="v_48_020",
        )

    assert score == -2.5
    event = _events(evidence_path)[0]
    assert event["operation"] == "score_sequence"
    assert event["effective_seed"] == 42
    assert event["result"]["summary"] == {
        "input_pdb_sha256": (
            "6a16b293eb04c4f0a69b87f5c6b51996b04e35a3976de47522d681aa34fb2660"
        ),
        "input_sequence_sha256": (
            "cb1ad2119d8fafb69566510ee712661f9f14b83385006ef92aec47f523a38358"
        ),
        "score": -2.5,
        "sequence_length": 3,
    }


def test_proteinmpnn_scoring_applies_the_recorded_effective_seed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import torch
    from modules.proteinmpnn.adapter import score_sequence

    _enable_gate(monkeypatch, tmp_path, "heavy-model")
    with (
        patch(
            "modules.proteinmpnn.adapter._load_model",
            return_value=(object(), "cpu"),
        ),
        patch(
            "modules.proteinmpnn.adapter._parse_structure",
            return_value=[
                {"name": "target", "seq": "AAA", "seq_chain_A": "AAA"}
            ],
        ),
        patch("modules.proteinmpnn.adapter._featurize", return_value=object()),
        patch(
            "modules.proteinmpnn.adapter._compute_score",
            side_effect=lambda *args: float(torch.rand(())),
        ),
    ):
        first = score_sequence("PRIVATE", "AAA")
        second = score_sequence("PRIVATE", "AAA")

    assert first == second


def test_structure_alignment_boundary_records_lengths_not_coordinates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.structure_alignment import align_structures

    evidence_path = _enable_gate(monkeypatch, tmp_path, "local-provider")
    project_root = Path(__file__).parent.parent
    reference = ProteinStructure(
        pdb_string=(project_root / "pdbs" / "3GB1.pdb").read_text(),
    )
    mobile = ProteinStructure(
        pdb_string=(project_root / "pdbs" / "1PGA-75-gen1_0690.pdb").read_text(),
    )

    alignment = align_structures(reference, mobile)

    assert len(alignment.residue_map) > 0
    event = _events(evidence_path)[0]
    assert event["provider"] == "biopython-svd"
    assert event["operation"] == "structure_align"
    assert event["result"]["summary"]["aligned_residues"] > 0
    assert "aligned_reference_coordinates" not in evidence_path.read_text()


def test_tmtools_boundary_records_reference_normalized_score(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.structure_alignment import align_structures
    from modules.structure_tm_score.scoring import (
        calculate_reference_normalized_tm_score,
    )

    evidence_path = _enable_gate(monkeypatch, tmp_path, "local-provider")
    project_root = Path(__file__).parent.parent
    alignment = align_structures(
        ProteinStructure(
            pdb_string=(project_root / "pdbs" / "3GB1.pdb").read_text(),
        ),
        ProteinStructure(
            pdb_string=(project_root / "pdbs" / "1PGA-75-gen1_0690.pdb").read_text(),
        ),
    )

    score = calculate_reference_normalized_tm_score(alignment)

    assert 0.0 <= score.value <= 1.0
    tm_event = [
        event for event in _events(evidence_path)
        if event["operation"] == "tm_score"
    ][0]
    assert tm_event["provider"] == "tmtools"
    assert tm_event["result"]["summary"]["normalization"] == "reference"
    assert tm_event["result"]["summary"]["value"] == score.value


def test_mkdssp_boundary_records_completed_subprocess_without_input(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.compute_dssp.module import ComputeDSSPModule

    class Process:
        returncode = 0
        pid = 123

        async def communicate(self) -> tuple[bytes, bytes]:
            return (
                b"loop_\n"
                b"_dssp_struct_summary.entry_id\n"
                b"_dssp_struct_summary.label_asym_id\n"
                b"_dssp_struct_summary.label_seq_id\n"
                b"_dssp_struct_summary.label_comp_id\n"
                b"_dssp_struct_summary.secondary_structure\n"
                b"_dssp_struct_summary.accessibility\n"
                b"nohd A 1 ALA H 100\n",
                b"",
            )

    async def fake_subprocess(*args, **kwargs) -> Process:
        return Process()

    evidence_path = _enable_gate(monkeypatch, tmp_path, "local-provider")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

    result = ComputeDSSPModule().run(
        {
            "structure": ProteinStructure(
                pdb_string="PRIVATE PDB INPUT",
            )
        },
        {"dssp_binary": "/opt/homebrew/bin/mkdssp"},
        RunContext(str(tmp_path), "dssp", run_id="test-run"),
    )

    assert result["secondary_structure_track"].values == ["H"]
    event = _events(evidence_path)[0]
    assert event["provider"] == "mkdssp"
    assert event["operation"] == "secondary_structure"
    assert event["result"]["summary"]["return_code"] == 0
    assert "PRIVATE PDB INPUT" not in evidence_path.read_text()


def test_simplefold_boundary_records_folding_result_digests(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import torch
    from modules import simplefold_adapter

    class ModelWrapper:
        device = "cpu"

        def __init__(self, **kwargs) -> None:
            pass

        def from_pretrained_folding_model(self):
            return object()

        def from_pretrained_plddt_model(self):
            return object()

    class InferenceWrapper:
        tokenizer = object()
        featurizer = object()
        processor = object()
        esm_model = object()
        esm_dict = object()
        af2_to_esm = object()

        def __init__(self, **kwargs) -> None:
            pass

        def run_inference(self, batch, model, plddt_models, device):
            return {
                "sampled_coord": [torch.zeros((1, 3))],
                "pad_mask": [torch.ones((1,))],
                "plddts": [torch.tensor([91.0])],
            }

    wrapper = ModuleType("simplefold.wrapper")
    wrapper.ModelWrapper = ModelWrapper
    wrapper.InferenceWrapper = InferenceWrapper
    boltz = ModuleType("simplefold.utils.boltz_utils")
    boltz.process_structure = lambda *args, **kwargs: object()
    boltz.save_structure = lambda *args, **kwargs: None
    boltz.to_pdb = lambda *args, **kwargs: (
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000\nEND\n"
    )
    fasta = ModuleType("simplefold.utils.fasta_utils")
    fasta.download_fasta_utilities = lambda cache: None

    def process_fastas(*, data, out_dir, ccd_path) -> None:
        (out_dir / "structures").mkdir(parents=True)
        (out_dir / "records").mkdir(parents=True)
        (out_dir / "structures" / "input.npz").write_bytes(b"npz")
        (out_dir / "records" / "input.json").write_text("{}")

    fasta.process_fastas = process_fastas
    datamodule = ModuleType("simplefold.utils.datamodule_utils")
    datamodule.process_one_inference_structure = (
        lambda *args, **kwargs: ({}, object(), {})
    )
    monkeypatch.setitem(sys.modules, "simplefold.wrapper", wrapper)
    monkeypatch.setitem(sys.modules, "simplefold.utils.boltz_utils", boltz)
    monkeypatch.setitem(sys.modules, "simplefold.utils.fasta_utils", fasta)
    monkeypatch.setitem(
        sys.modules,
        "simplefold.utils.datamodule_utils",
        datamodule,
    )
    runtime_esm_utils = ModuleType("utils.esm_utils")
    runtime_esm_utils.esm_registry = {}
    monkeypatch.setitem(sys.modules, "utils.esm_utils", runtime_esm_utils)
    monkeypatch.setattr(
        simplefold_adapter,
        "_setup_simplefold_imports",
        lambda: os.getcwd(),
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validated_simplefold_model_dir",
        lambda artifacts: artifacts,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validated_simplefold_esm2_runtime",
        lambda artifacts: (tmp_path, tmp_path),
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "_bind_simplefold_esm2_source",
        lambda registry, source_root, model_root: None,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "_prepare_simplefold_cache",
        lambda model_dir, cache: None,
    )
    evidence_path = _enable_gate(monkeypatch, tmp_path, "heavy-model")

    structures, scores = simplefold_adapter.fold_sequence(
        ProteinSequence(sequence="AAA"),
        num_steps=2,
        num_samples=1,
        project_dir=str(tmp_path),
    )

    assert len(structures) == 1
    assert len(scores.entries) == 1
    event = _events(evidence_path)[0]
    assert event["provider"] == "simplefold"
    assert event["operation"] == "fold_sequence"
    assert len(event["result"]["summary"]["input_sequence_sha256"]) == 64
    assert len(event["result"]["summary"]["pdb_sha256"][0]) == 64


def test_simplefold_boundary_records_structure_evaluation_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import torch
    from modules import simplefold_adapter

    class ModelWrapper:
        device = "cpu"

        def __init__(self, **kwargs) -> None:
            pass

        def from_pretrained_folding_model(self):
            return object()

        def from_pretrained_plddt_model(self):
            return {
                "plddt_latent_module": (
                    lambda coords, time, batch: {"latent": torch.ones((1, 1))}
                ),
                "plddt_out_module": (
                    lambda latent, batch: {"plddt": torch.tensor([0.91])}
                ),
            }

    wrapper = ModuleType("simplefold.wrapper")
    wrapper.ModelWrapper = ModelWrapper
    fasta = ModuleType("simplefold.utils.fasta_utils")
    fasta.download_fasta_utilities = lambda cache: None

    def process_fastas(*, data, out_dir, ccd_path) -> None:
        (out_dir / "structures").mkdir(parents=True)
        (out_dir / "records").mkdir(parents=True)
        (out_dir / "structures" / "input.npz").write_bytes(b"npz")
        (out_dir / "records" / "input.json").write_text("{}")

    fasta.process_fastas = process_fastas
    datamodule = ModuleType("simplefold.utils.datamodule_utils")
    datamodule.process_one_inference_structure = (
        lambda *args, **kwargs: (
            {"coords": torch.zeros((1, 1, 3))},
            object(),
            {},
        )
    )
    boltz = ModuleType("simplefold.utils.boltz_utils")
    boltz.save_structure = lambda *args, **kwargs: None
    processor = ModuleType("simplefold.processor.protein_processor")
    processor.ProteinDataProcessor = lambda **kwargs: object()
    esm_utils = ModuleType("simplefold.utils.esm_utils")

    class ESMModel:
        def to(self, device):
            return self

        def eval(self):
            return self

    esm_utils.esm_registry = {"esm2_3B": lambda: (ESMModel(), object())}
    esm_utils._af2_to_esm = lambda esm_dict: torch.tensor([0])
    featurizer = ModuleType(
        "simplefold.boltz_data_pipeline.feature.featurizer"
    )
    featurizer.BoltzFeaturizer = lambda: object()
    tokenizer = ModuleType(
        "simplefold.boltz_data_pipeline.tokenize.boltz_protein"
    )
    tokenizer.BoltzTokenizer = lambda: object()
    flow = ModuleType("simplefold.model.flow")
    flow.LinearPath = object
    for name, module in {
        "simplefold.wrapper": wrapper,
        "simplefold.utils.fasta_utils": fasta,
        "simplefold.utils.datamodule_utils": datamodule,
        "simplefold.utils.boltz_utils": boltz,
        "simplefold.processor.protein_processor": processor,
        "simplefold.utils.esm_utils": esm_utils,
        "simplefold.boltz_data_pipeline.feature.featurizer": featurizer,
        "simplefold.boltz_data_pipeline.tokenize.boltz_protein": tokenizer,
        "simplefold.model.flow": flow,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        simplefold_adapter,
        "_setup_simplefold_imports",
        lambda: os.getcwd(),
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validated_simplefold_model_dir",
        lambda artifacts: artifacts,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validated_simplefold_esm2_runtime",
        lambda artifacts: (tmp_path, tmp_path),
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "_bind_simplefold_esm2_source",
        lambda registry, source_root, model_root: None,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "_prepare_simplefold_cache",
        lambda model_dir, cache: None,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "_extract_sequence_from_pdb",
        lambda pdb: "AAA",
    )
    evidence_path = _enable_gate(monkeypatch, tmp_path, "heavy-model")

    scores = simplefold_adapter.evaluate_structure(
        ProteinStructure(pdb_string="PRIVATE PDB INPUT"),
        project_dir=str(tmp_path),
    )

    assert scores.entries[0].value == 91.0
    event = _events(evidence_path)[0]
    assert event["operation"] == "evaluate_structure"
    assert len(event["result"]["summary"]["input_pdb_sha256"]) == 64
    assert event["result"]["summary"]["score_count"] == 1
    assert "PRIVATE PDB INPUT" not in evidence_path.read_text()


def test_simplefold_import_setup_returns_and_switches_from_original_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules.simplefold_adapter import _setup_simplefold_imports

    fake_package = ModuleType("simplefold")
    fake_package.__file__ = str(tmp_path / "simplefold" / "__init__.py")
    (tmp_path / "simplefold").mkdir()
    monkeypatch.setitem(sys.modules, "simplefold", fake_package)
    original_cwd = os.getcwd()
    try:
        returned_cwd = _setup_simplefold_imports()
        assert returned_cwd == original_cwd
        assert os.getcwd() == str(tmp_path / "simplefold")
    finally:
        os.chdir(original_cwd)


def test_reviewed_simplefold_manifest_is_enabled() -> None:
    from core.provider_contract import (
        SIMPLEFOLD_ARTIFACT_SHA256,
        SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
        SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        SIMPLEFOLD_EXECUTION_ENABLED,
    )

    assert SIMPLEFOLD_EXECUTION_ENABLED is True
    assert SIMPLEFOLD_ARTIFACT_SHA256 == {
        "simplefold_100M.ckpt": (
            "4cd0b8a0b317a6ab8634444fffd78ce84cfd49c20fe927b83c76c36fda5f54bd"
        ),
        "simplefold_360M.ckpt": (
            "517338ec36b10ecc774f36b592ffe0fee6a24fa5c7d2fcfa3e3009282d48a49b"
        ),
        "simplefold_1.6B.ckpt": (
            "aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b"
        ),
        "plddt.ckpt": (
            "cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f"
        ),
        "ccd.pkl": (
            "2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4"
        ),
        "boltz1_conf.ckpt": (
            "219a73ac67535ad0535b9d3fb11fc7dbbcb7a0b71e4b4bb28f0c50cc2ac7f4ee"
        ),
    }
    assert SIMPLEFOLD_ESM2_ARTIFACT_SHA256 == {
        "esm2_t36_3B_UR50D.pt": (
            "7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500"
        ),
        "esm2_t36_3B_UR50D-contact-regression.pt": (
            "4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e"
        ),
    }
    assert SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256 == (
        "da1fd5e94771906950ccc9b4e789d50b0e8f8c4594608898dbcb14f14e3c50ba"
    )


def test_simplefold_invalid_model_root_does_not_enter_provider_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules import simplefold_adapter

    original_cwd = os.getcwd()
    model_root = tmp_path / "models"
    model_root.mkdir()
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        str(model_root),
    )

    setup = MagicMock(side_effect=AssertionError("provider import attempted"))
    monkeypatch.setattr(simplefold_adapter, "_setup_simplefold_imports", setup)

    with pytest.raises(FileNotFoundError, match="artifact is missing"):
        simplefold_adapter.fold_sequence(ProteinSequence(sequence="AAA"))

    setup.assert_not_called()
    assert os.getcwd() == original_cwd


def test_simplefold_size_only_artifacts_fail_closed_on_sha_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from core.provider_contract import (
        SIMPLEFOLD_ARTIFACT_IDENTITIES,
        SIMPLEFOLD_AUXILIARY_ARTIFACTS,
    )
    from modules.simplefold_adapter import validated_simplefold_model_dir

    model_root = tmp_path / "models"
    model_root.mkdir()
    for name, identity in SIMPLEFOLD_ARTIFACT_IDENTITIES.items():
        with (model_root / name).open("wb") as artifact:
            artifact.truncate(identity["bytes"])
    for name in SIMPLEFOLD_AUXILIARY_ARTIFACTS:
        (model_root / name).write_bytes(b"unreviewed-bytes")
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        str(model_root),
    )

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        validated_simplefold_model_dir(tmp_path / "working")


def test_simplefold_verified_artifacts_are_staged_as_independent_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules import simplefold_adapter

    main_names = (
        "simplefold_100M.ckpt",
        "simplefold_360M.ckpt",
        "simplefold_1.6B.ckpt",
        "plddt.ckpt",
    )
    auxiliary_names = ("ccd.pkl", "boltz1_conf.ckpt")
    artifact_bytes = {
        name: f"reviewed:{name}".encode()
        for name in (*main_names, *auxiliary_names)
    }
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(artifact_bytes[name])}
            for name in main_names
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_AUXILIARY_ARTIFACTS",
        auxiliary_names,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(content).hexdigest()
            for name, content in artifact_bytes.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_EXECUTION_ENABLED",
        True,
    )
    validate_checkout = MagicMock()
    monkeypatch.setattr(
        simplefold_adapter,
        "validate_installed_provider_checkout",
        validate_checkout,
    )

    model_root = tmp_path / "reviewed-models"
    model_root.mkdir()
    for name, content in artifact_bytes.items():
        (model_root / name).write_bytes(content)
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        str(model_root),
    )
    working_artifacts = tmp_path / "working"

    staged = simplefold_adapter.validated_simplefold_model_dir(
        working_artifacts
    )

    validate_checkout.assert_called_once()
    assert staged == working_artifacts / "verified_provider"
    assert not staged.is_symlink()
    for name, content in artifact_bytes.items():
        source = model_root / name
        destination = staged / name
        assert destination.read_bytes() == content
        assert not destination.is_symlink()
        assert destination.stat().st_ino != source.stat().st_ino
        assert destination.stat().st_nlink == 1


def test_simplefold_esm2_uses_locked_local_checkout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules import simplefold_adapter

    source_root = tmp_path / "esm2-source"
    source_root.mkdir()
    (source_root / "hubconf.py").write_text("# reviewed hub entrypoint\n")
    (source_root / "esm").mkdir()
    (source_root / "esm" / "__init__.py").write_text("# reviewed package\n")
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
        str(source_root),
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ESM2_REVISION",
        "locked-esm2-revision",
    )

    def git_result(root: Path, *args: str) -> str:
        assert root == source_root
        if args == ("rev-parse", "--show-toplevel"):
            return str(source_root)
        if args == ("rev-parse", "HEAD"):
            return "locked-esm2-revision"
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        if args == ("ls-files", "--", "hubconf.py", "esm"):
            return "esm/__init__.py\nhubconf.py"
        raise AssertionError(args)

    monkeypatch.setattr(
        simplefold_adapter,
        "_run_simplefold_esm2_git",
        git_result,
    )
    reviewed_tree = simplefold_adapter._simplefold_esm2_source_tree_sha256([
        ("esm/__init__.py", source_root / "esm" / "__init__.py"),
        ("hubconf.py", source_root / "hubconf.py"),
    ])
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256",
        reviewed_tree,
    )
    loader = MagicMock(return_value=("model", "alphabet"))
    monkeypatch.setattr(
        simplefold_adapter,
        "_load_reviewed_simplefold_esm2",
        loader,
    )

    validated = simplefold_adapter.validated_simplefold_esm2_root()
    staged = simplefold_adapter._stage_simplefold_esm2_source(
        validated,
        tmp_path / "working",
    )
    model_root = tmp_path / "models"
    model_root.mkdir()
    model_path = model_root / "esm2_t36_3B_UR50D.pt"
    model_path.write_bytes(b"reviewed")
    registry: dict[str, object] = {}
    simplefold_adapter._bind_simplefold_esm2_source(
        registry,
        staged,
        model_root,
    )
    result = registry["esm2_3B"]()

    assert result == ("model", "alphabet")
    assert (staged / "hubconf.py").stat().st_ino != (
        source_root / "hubconf.py"
    ).stat().st_ino
    loader.assert_called_once_with(staged, model_path)


def test_simplefold_esm2_weights_are_staged_as_independent_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules import simplefold_adapter

    artifacts = {
        "esm2_t36_3B_UR50D.pt": b"reviewed-esm2-model",
        "esm2_t36_3B_UR50D-contact-regression.pt": b"reviewed-regression",
    }
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(content)}
            for name, content in artifacts.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ESM2_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(content).hexdigest()
            for name, content in artifacts.items()
        },
    )
    source_root = tmp_path / "esm2-weights"
    source_root.mkdir()
    for name, content in artifacts.items():
        (source_root / name).write_bytes(content)
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
        str(source_root),
    )

    staged = simplefold_adapter.validated_simplefold_esm2_model_dir(
        tmp_path / "working"
    )

    for name, content in artifacts.items():
        source = source_root / name
        destination = staged / name
        assert destination.read_bytes() == content
        assert destination.stat().st_ino != source.stat().st_ino
        assert destination.stat().st_nlink == 1


def test_simplefold_esm2_loader_replaces_incompatible_biohub_namespace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules import simplefold_adapter

    source_root = tmp_path / "reviewed-esm2-source"
    package_root = source_root / "esm"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text(
        "from . import pretrained\n"
    )
    (package_root / "pretrained.py").write_text(
        "import argparse\n"
        "import torch\n"
        "\n"
        "def load_model_and_alphabet_core(name, model_data, regression_data):\n"
        "    return ('facebook-model', (name, model_data, regression_data))\n"
    )
    biohub_esm = ModuleType("esm")
    biohub_esm.__path__ = []
    biohub_pretrained = ModuleType("esm.pretrained")
    biohub_sdk = ModuleType("esm.sdk")
    biohub_sdk.__path__ = []
    biohub_sdk_api = ModuleType("esm.sdk.api")
    monkeypatch.setitem(sys.modules, "esm", biohub_esm)
    monkeypatch.setitem(sys.modules, "esm.pretrained", biohub_pretrained)
    monkeypatch.setitem(sys.modules, "esm.sdk", biohub_sdk)
    monkeypatch.setitem(sys.modules, "esm.sdk.api", biohub_sdk_api)
    model_path = tmp_path / "esm2_t36_3B_UR50D.pt"
    model_path.write_bytes(b"staged")
    regression_path = (
        tmp_path / "esm2_t36_3B_UR50D-contact-regression.pt"
    )
    regression_path.write_bytes(b"staged-regression")
    load_results = iter(["model-data", "regression-data"])

    def safe_torch_load(*args, **kwargs):
        import argparse
        import torch

        assert argparse.Namespace in torch.serialization.get_safe_globals()
        return next(load_results)

    torch_load = MagicMock(side_effect=safe_torch_load)
    monkeypatch.setattr(simplefold_adapter.torch, "load", torch_load)

    result = simplefold_adapter._load_reviewed_simplefold_esm2(
        source_root,
        model_path,
    )

    assert result == (
        "facebook-model",
        (
            "esm2_t36_3B_UR50D",
            "model-data",
            "regression-data",
        ),
    )
    assert torch_load.call_args_list == [
        (
            (str(model_path),),
            {"map_location": "cpu", "weights_only": True},
        ),
        (
            (str(regression_path),),
            {"map_location": "cpu", "weights_only": True},
        ),
    ]
    assert sys.modules["esm"] is biohub_esm
    assert sys.modules["esm.pretrained"] is biohub_pretrained
    assert importlib.import_module("esm.sdk.api") is biohub_sdk_api


def test_simplefold_readiness_requires_locked_esm2_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from modules import simplefold_adapter
    from tests.acceptance.conftest import _check_simplefold_ready

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        simplefold_adapter,
        "validated_simplefold_model_dir",
        lambda working_artifacts: working_artifacts,
    )
    validate_esm2_runtime = MagicMock(
        side_effect=FileNotFoundError("missing locked ESM2 source")
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validated_simplefold_esm2_runtime",
        validate_esm2_runtime,
    )

    assert _check_simplefold_ready() is False
    validate_esm2_runtime.assert_called_once_with(
        tmp_path / "simplefold_artifacts"
    )


def test_simplefold_gate_models_are_constrained() -> None:
    from modules.simplefold_adapter import evaluate_structure, fold_sequence

    with pytest.raises(ValueError, match="requires simplefold_100M"):
        fold_sequence(
            ProteinSequence(sequence="AAA"),
            model_name="simplefold_1.6B",
        )
    with pytest.raises(ValueError, match="requires simplefold_360M"):
        evaluate_structure(
            ProteinStructure(pdb_string="PRIVATE"),
            model_name="simplefold_1.6B",
        )


def test_provider_evidence_rejects_raw_payload_fields(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from core.provider_evidence import record_provider_call_result

    _enable_gate(monkeypatch, tmp_path, "live-provider")
    with pytest.raises(ValueError, match="non-allowlisted"):
        record_provider_call_result(
            provider="biohub",
            operation="esm3.generate_sequence",
            model="esm3-medium-2024-08",
            provider_identity={
                "sdk": "esm",
                "sdk_source_revision": (
                    "917af90b624535eed1e072d343c717e3ec11fef4"
                ),
                "service": "Biohub",
            },
            effective_seed=None,
            seed_control="unsupported_by_provider",
            result_summary={
                "result_type": "ESMProtein",
                "sequence": "PRIVATESEQUENCE",
            },
        )


def test_fresh_provider_evidence_binds_run_node_and_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from core.provider_contract import esm_provider_identity
    from core.provider_evidence import record_provider_call_result

    evidence_path = _enable_gate(
        monkeypatch,
        tmp_path,
        "fresh-remote-3gb1",
    )
    context = RunContext(
        str(tmp_path),
        "final_fold",
        run_id="fresh-run",
    )
    token = context.activate()
    try:
        context.record_provider_call(
            "biohub",
            "fold",
            model="esmfold2-fast-2026-05",
            details={
                "candidate_id": "final-1",
                "parent_candidate_id": "mpnn-1",
            },
        )
        record_provider_call_result(
            provider="biohub",
            operation="esmfold2.fold",
            model="esmfold2-fast-2026-05",
            provider_identity=esm_provider_identity(),
            effective_seed=None,
            seed_control="unsupported_by_provider",
            result_summary={
                "input_sequence_length": 3,
                "input_sequence_sha256": "1" * 64,
                "pdb_bytes": 80,
                "pdb_sha256": "2" * 64,
                "score_ids": ["ptm"],
            },
        )
    finally:
        context.deactivate(token)

    event = _events(evidence_path)[0]
    assert event["run_id"] == "fresh-run"
    assert event["node_id"] == "final_fold"
    assert event["candidate_id"] == "final-1"
    assert event["parent_candidate_id"] == "mpnn-1"
    retained = evidence_path.read_text()
    assert "secret" not in retained
    assert "sequence" not in event
    assert "pdb_string" not in event


def test_source_bound_scientific_calls_are_concurrent_run_isolated_and_redacted(
    tmp_path: Path,
) -> None:
    from core.provider_evidence import record_provider_call_result

    def record(run_id: str, candidate_id: str) -> tuple[bool, dict]:
        run_dir = tmp_path / "runs" / run_id
        manifest = RunManifest.for_execution(
            project_id="scientific-project",
            run_id=run_id,
            workflow=Workflow(),
            modules={},
            seed=42,
            source_dir=tmp_path,
        )
        with RunManifestStore(run_dir, manifest) as store:
            context = RunContext(
                str(tmp_path),
                "align",
                run_id=run_id,
                _manifest_store=store,
            )
            token = context.activate()
            try:
                appended_outer_evidence = record_provider_call_result(
                    provider="biopython-svd",
                    operation="structure_align",
                    model="PairwiseAligner+SVDSuperimposer",
                    provider_identity={
                        "algorithm": "sequence-aware-svd",
                    },
                    effective_seed=None,
                    seed_control="deterministic_no_rng",
                    result_summary={
                        "reference_length": 56,
                        "mobile_length": 56,
                        "aligned_residues": 56,
                        "rmsd": 0.5,
                        "coverage": 1.0,
                    },
                    manifest_details={
                        "candidate_id": candidate_id,
                        "input_identity": {
                            "reference_pdb_bytes": 80,
                            "reference_pdb_sha256": "1" * 64,
                            "mobile_pdb_bytes": 80,
                            "mobile_pdb_sha256": "2" * 64,
                        },
                    },
                )
            finally:
                context.deactivate(token)
        return appended_outer_evidence, read_run_manifest(run_dir)

    raw_secret = "sk-123456789ABCDE"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(record, "run-a", "candidate-a")
        second = pool.submit(record, "run-b", raw_secret)
        first_outer, first_manifest = first.result(timeout=5)
        second_outer, second_manifest = second.result(timeout=5)

    assert first_outer is second_outer is False
    assert first_manifest["run_id"] == "run-a"
    assert second_manifest["run_id"] == "run-b"
    assert [
        call["details"]["candidate_id"]
        for call in first_manifest["providers"]["calls"]
    ] == ["candidate-a"]
    assert [
        call["details"]["candidate_id"]
        for call in second_manifest["providers"]["calls"]
    ] == ["[REDACTED]"]
    assert raw_secret not in json.dumps(second_manifest, sort_keys=True)
    for manifest in (first_manifest, second_manifest):
        assert manifest["providers"]["calls"][0]["details"]["result"] == {
            "status": "succeeded",
            "summary": {
                "aligned_residues": 56,
                "coverage": 1.0,
                "mobile_length": 56,
                "reference_length": 56,
                "rmsd": 0.5,
            },
        }


def test_ambiguous_alignment_records_tmtools_tiebreak_in_run_manifest(
    tmp_path: Path,
) -> None:
    from modules.structure_align.module import StructureAlignModule

    run_dir = tmp_path / "runs" / "ambiguous-alignment"
    manifest = RunManifest.for_execution(
        project_id="scientific-project",
        run_id="ambiguous-alignment",
        workflow=Workflow(),
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    with RunManifestStore(run_dir, manifest) as store:
        context = RunContext(
            str(tmp_path),
            "align",
            run_id="ambiguous-alignment",
            _manifest_store=store,
        )
        token = context.activate()
        try:
            StructureAlignModule().run(
                {
                    "reference": ProteinStructure(
                        pdb_string=_repetitive_alignment_pdb(
                            _AMBIGUOUS_REFERENCE_SEQUENCE
                        ),
                    ),
                    "mobile": ProteinStructure(
                        pdb_string=_repetitive_alignment_pdb(
                            _AMBIGUOUS_MOBILE_SEQUENCE
                        ),
                    ),
                },
                {},
                context,
            )
        finally:
            context.deactivate(token)

    persisted = read_run_manifest(run_dir)
    assert [
        (call["provider"], call["operation"])
        for call in persisted["providers"]["calls"]
    ] == [
        ("tmtools", "structure_align_tiebreak"),
        ("biopython-svd", "structure_align"),
    ]


def test_failed_public_svd_alignment_is_manifested_before_node_failure(
    tmp_path: Path,
) -> None:
    from Bio.SVDSuperimposer import SVDSuperimposer
    from modules.structure_align.module import StructureAlignModule

    class SensitiveEngineError(RuntimeError):
        pass

    SensitiveEngineError.__name__ = "sk-sensitive-error-token"
    pdb = (Path(__file__).parent.parent / "pdbs" / "3GB1.pdb").read_text()
    run_dir = tmp_path / "runs" / "failed-svd"
    manifest = RunManifest.for_execution(
        project_id="scientific-project",
        run_id="failed-svd",
        workflow=Workflow(),
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    with RunManifestStore(run_dir, manifest) as store:
        context = RunContext(
            str(tmp_path),
            "align",
            run_id="failed-svd",
            _manifest_store=store,
        )
        token = context.activate()
        try:
            with patch.object(
                SVDSuperimposer,
                "run",
                side_effect=SensitiveEngineError(
                    "Bearer secret-engine-token /private/secret/input.pdb"
                ),
            ), pytest.raises(SensitiveEngineError):
                StructureAlignModule().run(
                    {
                        "reference": ProteinStructure(pdb_string=pdb),
                        "mobile": ProteinStructure(pdb_string=pdb),
                    },
                    {},
                    context,
                )
        finally:
            context.deactivate(token)

        persisted = read_run_manifest(run_dir)
        assert persisted["failures"] == []
        assert len(persisted["providers"]["calls"]) == 1
        failed_call = persisted["providers"]["calls"][0]
        assert (failed_call["provider"], failed_call["operation"]) == (
            "biopython-svd",
            "structure_align",
        )
        assert failed_call["details"]["node_id"] == "align"
        assert failed_call["details"]["result"] == {
            "status": "failed",
            "error": {"type": "Exception"},
        }
        retained = json.dumps(persisted, sort_keys=True)
        assert "sk-sensitive-error-token" not in retained
        assert "secret-engine-token" not in retained
        assert "/private/secret/input.pdb" not in retained
        assert len(retained.encode()) < 16 * 1024


def test_failed_tmtools_alignment_tiebreak_records_both_terminals(
    tmp_path: Path,
) -> None:
    from modules.structure_align.module import StructureAlignModule

    class SensitiveTiebreakError(RuntimeError):
        pass

    run_dir = tmp_path / "runs" / "failed-tiebreak"
    manifest = RunManifest.for_execution(
        project_id="scientific-project",
        run_id="failed-tiebreak",
        workflow=Workflow(),
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    with RunManifestStore(run_dir, manifest) as store:
        context = RunContext(
            str(tmp_path),
            "align",
            run_id="failed-tiebreak",
            _manifest_store=store,
        )
        token = context.activate()
        try:
            with patch(
                "tmtools.tm_align",
                side_effect=SensitiveTiebreakError(
                    "password=secret-tiebreak /private/secret/tie.bin"
                ),
            ), pytest.raises(SensitiveTiebreakError):
                StructureAlignModule().run(
                    {
                        "reference": ProteinStructure(
                            pdb_string=_repetitive_alignment_pdb(
                                _AMBIGUOUS_REFERENCE_SEQUENCE
                            ),
                        ),
                        "mobile": ProteinStructure(
                            pdb_string=_repetitive_alignment_pdb(
                                _AMBIGUOUS_MOBILE_SEQUENCE
                            ),
                        ),
                    },
                    {},
                    context,
                )
        finally:
            context.deactivate(token)

        persisted = read_run_manifest(run_dir)
        assert persisted["failures"] == []
        calls = persisted["providers"]["calls"]
        assert [
            (call["provider"], call["operation"])
            for call in calls
        ] == [
            ("tmtools", "structure_align_tiebreak"),
            ("biopython-svd", "structure_align"),
        ]
        assert [
            call["details"]["result"]
            for call in calls
        ] == [
            {
                "status": "failed",
                "error": {"type": "SensitiveTiebreakError"},
            },
            {
                "status": "failed",
                "error": {"type": "SensitiveTiebreakError"},
            },
        ]
        retained = json.dumps(persisted, sort_keys=True)
        assert "secret-tiebreak" not in retained
        assert "/private/secret/tie.bin" not in retained
        assert len(retained.encode()) < 24 * 1024


def test_failed_public_tm_score_is_manifested_before_node_failure(
    tmp_path: Path,
) -> None:
    from modules.structure_tm_score.module import StructureTMScoreModule

    class SensitiveTMError(RuntimeError):
        pass

    alignment = StructureAlignment(
        residue_map=[
            ("A:1", "A:1"),
            ("A:2", "A:2"),
            ("A:3", "A:3"),
        ],
        reference_length=3,
        mobile_length=3,
        aligned_reference_indices=[0, 1, 2],
        aligned_mobile_indices=[0, 1, 2],
        aligned_reference_coordinates=[
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        aligned_mobile_coordinates=[
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        aligned_distances=[0.0, 0.0, 0.0],
    )
    run_dir = tmp_path / "runs" / "failed-tm"
    manifest = RunManifest.for_execution(
        project_id="scientific-project",
        run_id="failed-tm",
        workflow=Workflow(),
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    with RunManifestStore(run_dir, manifest) as store:
        context = RunContext(
            str(tmp_path),
            "tm-score",
            run_id="failed-tm",
            _manifest_store=store,
        )
        token = context.activate()
        try:
            with patch(
                "modules.structure_tm_score.scoring.tm_align",
                side_effect=SensitiveTMError(
                    "api_key=secret-tm-key /private/secret/alignment.bin"
                ),
            ), pytest.raises(SensitiveTMError):
                StructureTMScoreModule().run(
                    {"alignment": alignment},
                    {
                        "candidate_id": "candidate-a",
                        "score_id": "tm_score",
                    },
                    context,
                )
        finally:
            context.deactivate(token)

        persisted = read_run_manifest(run_dir)
        assert persisted["failures"] == []
        assert len(persisted["providers"]["calls"]) == 1
        failed_call = persisted["providers"]["calls"][0]
        assert (failed_call["provider"], failed_call["operation"]) == (
            "tmtools",
            "tm_score",
        )
        assert failed_call["details"]["node_id"] == "tm-score"
        assert failed_call["details"]["result"] == {
            "status": "failed",
            "error": {"type": "SensitiveTMError"},
        }
        assert len(
            failed_call["details"]["input_identity"][
                "tm_align_input_sha256"
            ]
        ) == 64
        retained = json.dumps(persisted, sort_keys=True)
        assert "secret-tm-key" not in retained
        assert "/private/secret/alignment.bin" not in retained
        assert len(retained.encode()) < 16 * 1024


def test_scientific_manifest_details_reject_forged_node_attribution() -> None:
    from core.provider_evidence import record_provider_call_result

    with pytest.raises(ValueError, match="non-allowlisted"):
        record_provider_call_result(
            provider="biopython-svd",
            operation="structure_align",
            model="PairwiseAligner+SVDSuperimposer",
            provider_identity={"algorithm": "sequence-aware-svd"},
            effective_seed=None,
            seed_control="deterministic_no_rng",
            result_summary={
                "reference_length": 3,
                "mobile_length": 3,
                "aligned_residues": 3,
                "rmsd": 0.0,
                "coverage": 1.0,
            },
            manifest_details={
                "node_id": "forged-node",
                "input_identity": {
                    "reference_pdb_bytes": 80,
                    "reference_pdb_sha256": "1" * 64,
                    "mobile_pdb_bytes": 80,
                    "mobile_pdb_sha256": "2" * 64,
                },
            },
        )


def test_tm_manifest_digest_binds_complete_engine_coordinates(
    tmp_path: Path,
) -> None:
    from modules.structure_tm_score.scoring import (
        calculate_reference_normalized_tm_score,
    )

    run_dir = tmp_path / "runs" / "tm-input-digests"
    manifest = RunManifest.for_execution(
        project_id="scientific-project",
        run_id="tm-input-digests",
        workflow=Workflow(),
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    base_coordinates = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    shifted_coordinates = [
        [coordinate + 10.0 for coordinate in point]
        for point in base_coordinates
    ]
    with RunManifestStore(run_dir, manifest) as store:
        context = RunContext(
            str(tmp_path),
            "tm-score",
            run_id="tm-input-digests",
            _manifest_store=store,
        )
        token = context.activate()
        try:
            for candidate_id, reference_coordinates in (
                ("candidate-a", base_coordinates),
                ("candidate-b", shifted_coordinates),
            ):
                calculate_reference_normalized_tm_score(
                    StructureAlignment(
                        residue_map=[
                            ("A:1", "A:1"),
                            ("A:2", "A:2"),
                            ("A:3", "A:3"),
                        ],
                        reference_length=3,
                        mobile_length=3,
                        aligned_reference_indices=[0, 1, 2],
                        aligned_mobile_indices=[0, 1, 2],
                        aligned_reference_coordinates=reference_coordinates,
                        aligned_mobile_coordinates=base_coordinates,
                        aligned_distances=[0.0, 0.0, 0.0],
                    ),
                    call_details={"candidate_id": candidate_id},
                )
        finally:
            context.deactivate(token)

    calls = read_run_manifest(run_dir)["providers"]["calls"]
    assert len(calls) == 2
    assert len({
        call["details"]["input_identity"]["tm_align_input_sha256"]
        for call in calls
    }) == 2


def test_provider_evidence_redacts_token_shaped_candidate_ids(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from core.provider_contract import esm_provider_identity
    from core.provider_evidence import record_provider_call_result

    evidence_path = _enable_gate(
        monkeypatch,
        tmp_path,
        "fresh-remote-3gb1",
    )
    candidate_id = "sk-123456789ABCDE"
    context = RunContext(
        str(tmp_path),
        "final_fold",
        run_id="fresh-run",
    )
    token = context.activate()
    try:
        context.record_provider_call(
            "biohub",
            "fold",
            model="esmfold2-fast-2026-05",
            details={"candidate_id": candidate_id},
        )
        record_provider_call_result(
            provider="biohub",
            operation="esmfold2.fold",
            model="esmfold2-fast-2026-05",
            provider_identity=esm_provider_identity(),
            effective_seed=None,
            seed_control="unsupported_by_provider",
            result_summary={
                "input_sequence_length": 3,
                "input_sequence_sha256": "1" * 64,
                "pdb_bytes": 80,
                "pdb_sha256": "2" * 64,
                "score_ids": ["ptm"],
            },
        )
    finally:
        context.deactivate(token)

    event = _events(evidence_path)[0]
    assert event["candidate_id"] == "[REDACTED]"
    assert candidate_id not in evidence_path.read_text()


def test_required_provider_unavailability_is_a_failure(monkeypatch) -> None:
    from tests.acceptance.conftest import require_ready

    monkeypatch.setenv("PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL", "1")
    with pytest.raises(pytest.fail.Exception, match="is not available"):
        require_ready("simplefold", {"simplefold": False})


def test_local_esm3_loader_is_bound_to_validated_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import esm.pretrained as esm_pretrained
    from esm.models.esm3 import ESM3
    from modules import esm3_adapter

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    monkeypatch.setattr(
        esm3_adapter,
        "validate_installed_provider_checkout",
        lambda *args: tmp_path,
    )
    monkeypatch.setattr(
        esm3_adapter,
        "validate_local_esm3_snapshot",
        lambda: snapshot,
    )

    class Client:
        def float(self):
            return self

    observed = {}

    def fake_from_pretrained(model_name, device):
        observed["root"] = esm_pretrained.data_root("esm3")
        return Client()

    monkeypatch.setattr(ESM3, "from_pretrained", fake_from_pretrained)

    client = esm3_adapter.create_esm3_client("esm3_sm_open_v1")

    assert isinstance(client, Client)
    assert observed["root"] == snapshot


def test_normal_vcs_provider_install_verifies_record_hashes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from core import provider_contract

    package_file = tmp_path / "esm" / "__init__.py"
    package_file.parent.mkdir()
    package_file.write_text("LOCKED = True\n")
    digest = hashlib.sha256(package_file.read_bytes()).digest()

    class File:
        hash = type("Hash", (), {
            "mode": "sha256",
            "value": base64.urlsafe_b64encode(digest).decode().rstrip("="),
        })()

        def __str__(self) -> str:
            return "esm/__init__.py"

    class Distribution:
        files = [File()]

        def read_text(self, name: str) -> str:
            assert name == "direct_url.json"
            return json.dumps({
                "url": "https://example.invalid/esm.git",
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": provider_contract.ESM_SDK_REVISION,
                    "requested_revision": provider_contract.ESM_SDK_REVISION,
                },
            })

        def locate_file(self, item) -> Path:
            return tmp_path / str(item)

    monkeypatch.setattr(
        provider_contract.importlib.metadata,
        "distribution",
        lambda name: Distribution(),
    )
    monkeypatch.setitem(
        provider_contract.PROVIDER_PACKAGE_TREE_SHA256,
        "esm",
        provider_contract._package_tree_sha256([
            ("__init__.py", package_file),
        ]),
    )

    resolved = provider_contract.validate_installed_provider_checkout(
        "esm",
        provider_contract.ESM_SDK_REVISION,
    )

    assert resolved == package_file.parent

    (package_file.parent / "injected.py").write_text("raise RuntimeError\n")
    with pytest.raises(RuntimeError, match="absent from RECORD"):
        provider_contract.validate_installed_provider_checkout(
            "esm",
            provider_contract.ESM_SDK_REVISION,
        )
