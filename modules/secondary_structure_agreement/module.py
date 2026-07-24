"""Secondary Structure Agreement: compares expected vs observed DSSP tracks."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ResidueTrack, Score, ScoreCollection

# DSSP codes grouped into three coarse classes for comparison
_HELIX = {"H", "G", "I"}
_SHEET = {"B", "E"}
_COIL = {"-", "T", "S", " "}


def _coarse_class(ss: str) -> str:
    if ss in _HELIX:
        return "helix"
    elif ss in _SHEET:
        return "sheet"
    else:
        return "coil"


class SecondaryStructureAgreementModule(WorkflowModule):
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
        expected: ResidueTrack | None = inputs.get("expected")
        observed: ResidueTrack | None = inputs.get("observed")

        if expected is None:
            raise ValueError("expected input is required")
        if observed is None:
            raise ValueError("observed input is required")

        use_coarse = bool(parameters.get("coarse", True))

        n = min(len(expected), len(observed))
        if n == 0:
            raise ValueError("Both tracks are empty")

        matches = []
        for i in range(n):
            exp_val = expected.values[i] if i < len(expected.values) else None
            obs_val = observed.values[i] if i < len(observed.values) else None

            if exp_val is None or obs_val is None:
                matches.append(False)
                continue

            if use_coarse:
                matches.append(_coarse_class(str(exp_val)) == _coarse_class(str(obs_val)))
            else:
                matches.append(str(exp_val) == str(obs_val))

        overlap = sum(matches) / n if n > 0 else 0.0

        entries = [
            Score(
                score_id="ss_overlap",
                value=round(float(overlap), 4),
                subjects=[],
                details={
                    "matched": sum(matches),
                    "compared": n,
                    "coverage": n / max(len(expected), len(observed)) if max(len(expected), len(observed)) > 0 else 1.0,
                    "per_residue_match": matches,
                    "coarse": use_coarse,
                },
            )
        ]

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
