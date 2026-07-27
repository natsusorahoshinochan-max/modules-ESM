"""ProteinMPNN Constraints: produces a constraints data object."""

import json
from math import isfinite
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinMPNNConstraints

_ALPHABET = set("ACDEFGHIKLMNPQRSTVWYX")


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


def _position_list(value: Any, name: str) -> list[int] | None:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON list")
    if not value:
        return None
    if any(
        isinstance(position, bool)
        or not isinstance(position, int)
        or position < 0
        for position in value
    ):
        raise ValueError(
            f"{name} entries must be non-negative zero-based integers"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicate positions")
    return value


def _string_list(value: Any, name: str) -> list[str] | None:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON list")
    if not value:
        return None
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicates")
    return value


def _tied_positions(parameters: dict[str, Any]) -> list[list[int]] | None:
    tied_value = _json_parameter(parameters, "tied_positions", "[]")
    if not isinstance(tied_value, list):
        raise ValueError("tied_positions must be a JSON list of position groups")
    tied_groups = []
    seen_tied_positions: set[int] = set()
    for group_index, group_value in enumerate(tied_value):
        group = _position_list(
            group_value,
            f"tied_positions group {group_index}",
        )
        if group is None or len(group) < 2:
            raise ValueError(
                f"tied_positions group {group_index} must contain at least two positions"
            )
        overlap = seen_tied_positions & set(group)
        if overlap:
            raise ValueError(
                "tied_positions cannot reuse positions across groups: "
                + ", ".join(str(position) for position in sorted(overlap))
            )
        seen_tied_positions.update(group)
        tied_groups.append(group)
    return tied_groups or None


def _residue_biases(
    parameters: dict[str, Any],
) -> dict[int, dict[str, float]] | None:
    bias_value = _json_parameter(parameters, "bias_by_res", "{}")
    if not isinstance(bias_value, dict):
        raise ValueError("bias_by_res must be a JSON object")
    bias_by_res: dict[int, dict[str, float]] = {}
    for raw_position, amino_acid_biases in bias_value.items():
        position = _bias_position(raw_position)
        bias_by_res[position] = _amino_acid_biases(
            position, amino_acid_biases
        )
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


def _amino_acid_biases(
    position: int,
    amino_acid_biases: Any,
) -> dict[str, float]:
    if not isinstance(amino_acid_biases, dict) or not amino_acid_biases:
        raise ValueError(
            f"bias_by_res position {position} must map amino acids to biases"
        )
    parsed: dict[str, float] = {}
    for amino_acid, bias in amino_acid_biases.items():
        if amino_acid not in _ALPHABET:
            raise ValueError(
                f"bias_by_res contains unsupported amino acid {amino_acid!r}"
            )
        if isinstance(bias, bool) or not isinstance(bias, (int, float)):
            raise ValueError(
                f"bias_by_res bias for {position}/{amino_acid} must be numeric"
            )
        numeric_bias = float(bias)
        if not isfinite(numeric_bias):
            raise ValueError(
                f"bias_by_res bias for {position}/{amino_acid} must be finite"
            )
        parsed[amino_acid] = numeric_bias
    return parsed


def _reject_overlaps(
    designable: list[int] | None,
    fixed: list[int] | None,
    designed_chains: list[str] | None,
    fixed_chains: list[str] | None,
) -> None:
    overlapping_positions = sorted(set(designable or []) & set(fixed or []))
    if overlapping_positions:
        raise ValueError(
            "positions cannot be both designable and fixed: "
            + ", ".join(str(position) for position in overlapping_positions)
        )
    overlapping_chains = sorted(
        set(designed_chains or []) & set(fixed_chains or [])
    )
    if overlapping_chains:
        raise ValueError(
            "chains cannot be both designed and fixed: "
            + ", ".join(overlapping_chains)
        )


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
        designable = _position_list(
            _json_parameter(parameters, "designable_positions", "[]"),
            "designable_positions",
        )
        fixed = _position_list(
            _json_parameter(parameters, "fixed_positions", "[]"),
            "fixed_positions",
        )
        designed_chains = _string_list(
            _json_parameter(parameters, "designed_chains", "[]"),
            "designed_chains",
        )
        fixed_chains = _string_list(
            _json_parameter(parameters, "fixed_chains", "[]"),
            "fixed_chains",
        )
        omit = _string_list(
            _json_parameter(parameters, "omit_amino_acids", "[]"),
            "omit_amino_acids",
        )
        unsupported_omissions = sorted(set(omit or []) - _ALPHABET)
        if unsupported_omissions:
            raise ValueError(
                "omit_amino_acids contains unsupported amino acids: "
                + ", ".join(unsupported_omissions)
            )

        tied_groups = _tied_positions(parameters)
        bias_by_res = _residue_biases(parameters)
        _reject_overlaps(designable, fixed, designed_chains, fixed_chains)

        constraints = ProteinMPNNConstraints(
            designable_positions=designable,
            fixed_positions=fixed,
            designed_chains=designed_chains,
            fixed_chains=fixed_chains,
            omit_amino_acids=omit,
            tied_positions=tied_groups,
            bias_by_res=bias_by_res,
        )
        return {"constraints": constraints}
