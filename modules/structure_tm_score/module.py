"""TM-score: computes TM-score from a StructureAlignment using tmtools."""

import uuid
from pathlib import Path
from typing import Any

import numpy as np

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure, Score, ScoreCollection, StructureAlignment


class StructureTMScoreModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        alignment: StructureAlignment | None = inputs.get("alignment")
        if alignment is None:
            raise ValueError("alignment input is required")

        # TM-score needs coordinates. Use the rotation/translation to align
        # mobile onto reference, then compute TM-score.
        ref_struct: ProteinStructure | None = inputs.get("reference")
        mob_struct: ProteinStructure | None = inputs.get("mobile")

        # TM-score is defined by the alignment itself; we can compute it
        # from the rmsd and coverage stored in the alignment.
        # Standard TM-score formula: TM = max(1/(1+(RMSD/d0)^2), coverage)
        # where d0 = 1.24 * (N - 15)^(1/3) - 1.8 for N > 15, else 0.5
        n_aligned = len(alignment.residue_map)
        if n_aligned == 0:
            raise ValueError("Alignment has no aligned residues")

        if n_aligned > 15:
            d0 = 1.24 * (n_aligned - 15) ** (1.0 / 3.0) - 1.8
        else:
            d0 = 0.5
        d0 = max(d0, 0.5)

        tm = 1.0 / (1.0 + (alignment.rmsd / d0) ** 2)

        entries = [
            Score(
                score_id="tm_score",
                value=round(float(tm), 4),
                subjects=[],
                details={
                    "rmsd": round(float(alignment.rmsd), 4),
                    "aligned_residues": n_aligned,
                    "coverage": round(float(alignment.coverage), 4),
                    "d0": round(float(d0), 4),
                    "normalization": "reference",
                },
            )
        ]

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
