"""Controlled providers for one fresh canonical 3GB1 Workflow run."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Iterator
from unittest.mock import patch

import torch

from core.run_context import RunContext
from datatypes import (
    ProteinSequence,
    ProteinStructure,
    ResidueTrack,
    Score,
    ScoreCollection,
)
from modules.compute_dssp.module import ComputeDSSPModule
from modules.proteinmpnn.adapter import ProteinMPNNDesignRequest


SEQUENCE_71 = (
    "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
    "GGGGGGGGGGGGGGG"
)
TM_VS_3GB1 = [0.0017] * 10
TM_VS_ESM3 = [
    1.0,
    1.0,
    0.9998,
    0.9996,
    0.9993,
    0.9988,
    0.9983,
    0.9977,
    0.9971,
    0.9963,
]
PROTEINMPNN_SCORES = [
    -1.0,
    -1.1,
    -1.2,
    -1.3,
    -1.4,
    -2.0,
    -2.1,
    -2.2,
    -2.3,
    -2.4,
    -3.0,
    -3.1,
    -3.2,
    -3.3,
    -3.4,
]


def _no_sleep(_: float) -> None:
    """Keep controlled canonical fixtures independent of wall-clock pacing."""

_AA3 = dict(
    zip(
        "ACDEFGHIKLMNPQRSTVWY",
        (
            "ALA",
            "CYS",
            "ASP",
            "GLU",
            "PHE",
            "GLY",
            "HIS",
            "ILE",
            "LYS",
            "LEU",
            "MET",
            "ASN",
            "PRO",
            "GLN",
            "ARG",
            "SER",
            "THR",
            "VAL",
            "TRP",
            "TYR",
        ),
        strict=True,
    )
)
_AA1 = {value: key for key, value in _AA3.items()}


def pdb_for_sequence(sequence: str, *, offset: float = 0.0) -> str:
    """Return a small, valid, deterministic all-backbone PDB."""
    lines = ["HEADER    CONTROLLED PROVIDER FIXTURE"]
    serial = 1
    for index, amino_acid in enumerate(sequence):
        x = index * 3.8 + offset
        residue = _AA3[amino_acid]
        for atom in ("N", "CA", "C", "O"):
            lines.append(
                f"ATOM  {serial:5d}  {atom:<3s} {residue} A{index + 1:4d}    "
                f"{x:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00           "
                f"{atom[0]:>1s}"
            )
            serial += 1
    lines.extend(("TER", "END"))
    return "\n".join(lines) + "\n"


@dataclass
class ControlledESMProtein:
    """Subset of the ESM SDK response contract used by the workbench."""

    sequence: str
    coordinates: torch.Tensor | None = None
    secondary_structure: str | None = None
    sasa: object | None = None
    function_annotations: object | None = None
    ptm: torch.Tensor | None = None
    plddt: torch.Tensor | None = None
    pae: torch.Tensor | None = None
    pdb_string: str | None = None

    def to_pdb_string(self) -> str:
        return self.pdb_string or pdb_for_sequence(self.sequence)


class ControlledESMClient:
    """Ten index-paired sequence/structure responses, independent of Cache."""

    def __init__(self) -> None:
        self.sequence_calls = 0
        self.structure_calls = 0

    def generate(
        self,
        protein: ControlledESMProtein,
        config: SimpleNamespace,
    ) -> ControlledESMProtein:
        if config.track == "sequence":
            sample_index = self.sequence_calls
            self.sequence_calls += 1
        elif config.track == "structure":
            sample_index = self.structure_calls
            self.structure_calls += 1
        else:
            raise AssertionError(f"Unexpected ESM3 track {config.track!r}")
        if sample_index >= 10:
            raise AssertionError("Controlled ESM3 fixture exhausted")
        return ControlledESMProtein(
            sequence=SEQUENCE_71,
            coordinates=torch.zeros((len(SEQUENCE_71), 37, 3)),
            ptm=torch.tensor([0.80 + sample_index * 0.01]),
            plddt=torch.tensor(
                [0.90 - sample_index * 0.001] * len(SEQUENCE_71)
            ),
            pdb_string=pdb_for_sequence(
                SEQUENCE_71,
                offset=sample_index * 0.01,
            ),
        )


@contextmanager
def installed_esm_sdk() -> Iterator[None]:
    """Install only the documented SDK construction surface in sys.modules."""

    class ControlledESMProteinError(Exception):
        pass

    class GenerationConfig(SimpleNamespace):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)

    esm_module = ModuleType("esm")
    sdk_module = ModuleType("esm.sdk")
    api_module = ModuleType("esm.sdk.api")
    api_module.ESMProtein = ControlledESMProtein
    api_module.ESMProteinError = ControlledESMProteinError
    api_module.GenerationConfig = GenerationConfig
    esm_module.sdk = sdk_module
    sdk_module.api = api_module
    with patch.dict(
        "sys.modules",
        {
            "esm": esm_module,
            "esm.sdk": sdk_module,
            "esm.sdk.api": api_module,
        },
    ):
        yield


class ControlledFoldProvider:
    """Ten initial plus fifteen final ESMFold2 responses."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        sequence: ProteinSequence,
        *,
        model_name: str,
        include_pae: bool,
        include_embeddings: bool,
        project_dir: str,
        call_details: dict[str, object] | None = None,
    ) -> tuple[ProteinStructure, ScoreCollection]:
        del include_pae, include_embeddings, project_dir
        call_index = self.calls
        self.calls += 1
        if call_index >= 25:
            raise AssertionError("Controlled ESMFold2 fixture exhausted")
        RunContext.record_active_provider_call(
            "biohub",
            "fold",
            model=model_name,
            details=call_details,
        )
        structure = ProteinStructure(
            pdb_string=pdb_for_sequence(
                sequence.sequence,
                offset=0.0 if call_index < 10 else call_index * 0.001,
            ),
            source="esmfold2",
        )
        return structure, ScoreCollection(
            collection_id=f"fold-scores-{call_index}",
            entries=[
                Score(
                    score_id="ptm",
                    value=0.95 - call_index * 0.001,
                    subjects=["provider-placeholder"],
                ),
                Score(
                    score_id="plddt",
                    value=0.90 - call_index * 0.001,
                    subjects=["provider-placeholder"],
                    details={
                        "per_residue": [0.9] * len(sequence.sequence),
                    },
                ),
            ],
        )


class ControlledProteinMPNNProvider:
    """Three parent calls with five deterministic children and scores each."""

    provider_identity = "controlled-proteinmpnn"

    def __init__(self) -> None:
        self.parent_calls = 0
        self.requests: list[ProteinMPNNDesignRequest] = []

    def parse_structure(self, pdb_string: str) -> list[dict[str, object]]:
        sequence = "".join(
            _AA1.get(line[17:20].strip(), "X")
            for line in pdb_string.splitlines()
            if line.startswith("ATOM") and line[12:16].strip() == "CA"
        )
        return [{
            "name": "controlled-target",
            "seq_chain_A": sequence,
        }]

    def design(
        self,
        request: ProteinMPNNDesignRequest,
    ) -> tuple[list[ProteinSequence], list[float]]:
        parent_index = self.parent_calls
        self.parent_calls += 1
        self.requests.append(request)
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        sequences = [
            ProteinSequence(
                sequence="".join(
                    alphabet[
                        (position + parent_index * 5 + sample_index)
                        % len(alphabet)
                    ]
                    for position in range(request.target_length)
                )
            )
            for sample_index in range(request.num_sequences)
        ]
        scores = [
            -(parent_index + 1.0) - sample_index / 10
            for sample_index in range(request.num_sequences)
        ]
        return sequences, scores


class ControlledDSSPModule(ComputeDSSPModule):
    """One deterministic local-tool boundary without spawning a subprocess."""

    async def run_async(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        del inputs, parameters
        context.record_provider_call(
            "mkdssp",
            "secondary_structure",
            model="controlled-mkdssp",
        )
        return {
            "secondary_structure_track": ResidueTrack(
                values=["E"] * 10 + ["H"] * 10 + ["E"] * 36,
                sentinel=None,
            )
        }


def canonical_modules(
    mpnn_provider: ControlledProteinMPNNProvider,
) -> dict[str, object]:
    """Build the real canonical Modules around controlled provider seams."""
    from modules.apply_residue_edits import ApplyResidueEditsModule
    from modules.assemble_protein_prompt import AssembleProteinPromptModule
    from modules.build_residue_layout import BuildResidueLayoutModule
    from modules.esm3_generate.module import ESM3GenerateModule
    from modules.esmfold2_fold.module import ESMFold2FoldModule
    from modules.export_structure import ExportStructureModule
    from modules.import_structure import ImportStructureModule
    from modules.merge_scores.module import MergeScoresModule
    from modules.override_residue_track import OverrideResidueTrackModule
    from modules.prompt_random_fixed_positions.module import (
        RandomFixedPositionsModule,
    )
    from modules.prompt_random_insert_masked.module import RandomInsertMaskedModule
    from modules.prompt_random_mask.module import RandomMaskModule
    from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
    from modules.structure_batch_tm_score.module import BatchTMScoreModule
    from modules.structure_pairwise_align.module import PairwiseAlignModule
    from modules.top_k.module import TopKModule
    from modules.weighted_rank.module import WeightedRankModule

    return {
        "import.structure": ImportStructureModule(),
        "prompt.build_residue_layout": BuildResidueLayoutModule(),
        "prompt.apply_residue_edits": ApplyResidueEditsModule(),
        "prompt.random_mask": RandomMaskModule(),
        "prompt.random_insert_masked": RandomInsertMaskedModule(),
        "prompt.random_fixed_positions": RandomFixedPositionsModule(),
        "prompt.override_residue_track": OverrideResidueTrackModule(),
        "prompt.assemble_protein_prompt": AssembleProteinPromptModule(),
        "compute.dssp": ControlledDSSPModule(),
        "esm3.generate": ESM3GenerateModule(),
        "esmfold2.fold": ESMFold2FoldModule(sleep=_no_sleep),
        "structure.pairwise_align": PairwiseAlignModule(),
        "structure.batch_tm_score": BatchTMScoreModule(),
        "scoring.merge": MergeScoresModule(),
        "selection.weighted_rank": WeightedRankModule(),
        "selection.top_k": TopKModule(),
        "proteinmpnn.design": ProteinMPNNDesignModule(
            provider=mpnn_provider
        ),
        "export.structure": ExportStructureModule(),
    }
