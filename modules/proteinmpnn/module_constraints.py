"""ProteinMPNN Constraints: produces a constraints data object."""

import json
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinMPNNConstraints


class ProteinMPNNConstraintsModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition_constraints.yaml"
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
        # Parse optional JSON parameters
        def _parse_json_list(val: str) -> list[int] | None:
            if not val or val == "[]":
                return None
            return json.loads(val)

        def _parse_json_str_list(val: str) -> list[str] | None:
            if not val or val == "[]":
                return None
            return json.loads(val)

        designable = _parse_json_list(str(parameters.get("designable_positions", "")))
        fixed = _parse_json_list(str(parameters.get("fixed_positions", "")))
        omit = _parse_json_str_list(str(parameters.get("omit_amino_acids", "")))
        tied_raw = str(parameters.get("tied_positions", ""))
        tied = _parse_json_list(tied_raw) if tied_raw and tied_raw != "[]" else None
        tied_pairs: list[list[int]] | None = None
        if tied:
            # Parse as pairs: [[a,b], [c,d]]
            tied_pairs = [[int(p[0]), int(p[1])] for p in tied] if tied else None

        constraints = ProteinMPNNConstraints(
            designable_positions=designable,
            fixed_positions=fixed,
            omit_amino_acids=omit,
            tied_positions=tied_pairs,
        )
        return {"constraints": constraints}
