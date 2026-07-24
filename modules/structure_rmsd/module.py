"""RMSD: reads RMSD from a StructureAlignment and emits it as a score."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import Score, ScoreCollection, StructureAlignment


class StructureRMSDModule(WorkflowModule):
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

        entries = [
            Score(
                score_id="rmsd",
                value=round(float(alignment.rmsd), 4),
                subjects=[],
                details={
                    "aligned_residues": len(alignment.residue_map),
                    "coverage": round(float(alignment.coverage), 4),
                    "unit": "angstroms",
                },
            )
        ]

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
