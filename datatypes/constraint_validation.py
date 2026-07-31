"""Validation for the public ProteinMPNN constraints value contract."""

from __future__ import annotations

from math import isfinite
from typing import Any

from datatypes.protein import ProteinMPNNConstraints, ResidueLayout


PROTEINMPNN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")


def _positions(value: Any, name: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
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


def _strings(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicates")
    return value


def _tied_positions(value: Any) -> list[list[int]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tied_positions must be a list of position groups")
    tied_groups: list[list[int]] = []
    seen: set[int] = set()
    for group_index, group_value in enumerate(value):
        group = _positions(
            group_value,
            f"tied_positions group {group_index}",
        )
        if len(group) < 2:
            raise ValueError(
                f"tied_positions group {group_index} must contain "
                "at least two positions"
            )
        overlap = seen & set(group)
        if overlap:
            raise ValueError(
                "tied_positions cannot reuse positions across groups: "
                + ", ".join(str(position) for position in sorted(overlap))
            )
        seen.update(group)
        tied_groups.append(group)
    return tied_groups


def _biases(value: Any) -> dict[int, dict[str, float]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("bias_by_res must map positions to amino-acid biases")
    for position, amino_acid_biases in value.items():
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 0
        ):
            raise ValueError(
                "bias_by_res positions must be non-negative zero-based integers"
            )
        if not isinstance(amino_acid_biases, dict) or not amino_acid_biases:
            raise ValueError(
                f"bias_by_res position {position} must map amino acids to biases"
            )
        for amino_acid, bias in amino_acid_biases.items():
            if amino_acid not in PROTEINMPNN_ALPHABET:
                raise ValueError(
                    "bias_by_res contains unsupported amino acid "
                    f"{amino_acid!r}"
                )
            if isinstance(bias, bool) or not isinstance(bias, (int, float)):
                raise ValueError(
                    f"bias_by_res bias for {position}/{amino_acid} "
                    "must be numeric"
                )
            if not isfinite(float(bias)):
                raise ValueError(
                    f"bias_by_res bias for {position}/{amino_acid} "
                    "must be finite"
                )
    return value


def validate_proteinmpnn_constraints(
    constraints: ProteinMPNNConstraints,
) -> None:
    """Validate all structure-independent ProteinMPNN constraint rules."""
    if not isinstance(constraints, ProteinMPNNConstraints):
        raise ValueError("constraints must be ProteinMPNNConstraints")
    if type(constraints.layout) is not ResidueLayout:
        raise ValueError("constraints layout must be a ResidueLayout")

    designable = _positions(
        constraints.designable_positions,
        "designable_positions",
    )
    fixed = _positions(constraints.fixed_positions, "fixed_positions")
    designed_chains = _strings(
        constraints.designed_chains,
        "designed_chains",
    )
    fixed_chains = _strings(constraints.fixed_chains, "fixed_chains")
    omitted = _strings(
        constraints.omit_amino_acids,
        "omit_amino_acids",
    )
    unsupported_omissions = sorted(
        set(omitted) - PROTEINMPNN_ALPHABET
    )
    if unsupported_omissions:
        raise ValueError(
            "omit_amino_acids contains unsupported amino acids: "
            + ", ".join(unsupported_omissions)
        )
    if len(omitted) == len(PROTEINMPNN_ALPHABET):
        raise ValueError(
            "omit_amino_acids must leave at least one amino acid available"
        )

    tied_groups = _tied_positions(constraints.tied_positions)
    biases = _biases(constraints.bias_by_res)
    overlapping_positions = sorted(set(designable) & set(fixed))
    if overlapping_positions:
        raise ValueError(
            "positions cannot be both designable and fixed: "
            + ", ".join(str(position) for position in overlapping_positions)
        )
    overlapping_chains = sorted(
        set(designed_chains) & set(fixed_chains)
    )
    if overlapping_chains:
        raise ValueError(
            "chains cannot be both designed and fixed: "
            + ", ".join(overlapping_chains)
        )
    for position, amino_acid_biases in biases.items():
        for group_index, group in enumerate(tied_groups):
            if position in group:
                raise ValueError(
                    f"bias_by_res position {position} belongs to tied "
                    f"position group {group_index}"
                )
        for amino_acid in amino_acid_biases:
            if amino_acid in omitted:
                raise ValueError(
                    f"bias_by_res position {position} targets globally "
                    f"omitted amino acid {amino_acid}"
                )
