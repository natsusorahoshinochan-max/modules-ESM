"""ProteinMPNN Constraints: produces a constraints data object."""

import json
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinMPNNConstraints
from modules.proteinmpnn.constraint_validation import validate_constraints


def _json_parameter(parameters: dict[str, Any], name: str, default: str) -> Any:
    raw = parameters.get(name, default)
    if raw == "":
        raw = default
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be provided as JSON text")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} must be valid JSON: {error.msg}") from error


def _optional_parameter(
    parameters: dict[str, Any],
    name: str,
) -> Any:
    value = _json_parameter(parameters, name, "[]")
    return None if value == [] else value


def _bias_parameter(parameters: dict[str, Any]) -> Any:
    bias_value = _json_parameter(parameters, "bias_by_res", "{}")
    if not isinstance(bias_value, dict):
        return bias_value
    bias_by_res: dict[int, Any] = {}
    for raw_position, amino_acid_biases in bias_value.items():
        position = _bias_position(raw_position)
        bias_by_res[position] = amino_acid_biases
    return bias_by_res or None


def _bias_position(raw_position: Any) -> int:
    try:
        position = int(raw_position)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"bias_by_res position {raw_position!r} must be an integer"
        ) from error
    if position < 0 or str(position) != str(raw_position):
        raise ValueError(
            f"bias_by_res position {raw_position!r} must be a "
            "non-negative zero-based integer"
        )
    return position


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
        constraints = ProteinMPNNConstraints(
            designable_positions=_optional_parameter(
                parameters, "designable_positions"
            ),
            fixed_positions=_optional_parameter(
                parameters, "fixed_positions"
            ),
            designed_chains=_optional_parameter(
                parameters, "designed_chains"
            ),
            fixed_chains=_optional_parameter(parameters, "fixed_chains"),
            omit_amino_acids=_optional_parameter(
                parameters, "omit_amino_acids"
            ),
            tied_positions=_optional_parameter(parameters, "tied_positions"),
            bias_by_res=_bias_parameter(parameters),
        )
        validate_constraints(constraints)
        return {"constraints": constraints}
