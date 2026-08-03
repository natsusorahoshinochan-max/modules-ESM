"""Validation for the public ProteinMPNN constraints value contract."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from datatypes.protein import (
    ProteinMPNNConstraints,
    ResidueLayout,
    residue_identity_chain,
)


PROTEINMPNN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")


def _residue_ids(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be an immutable residue sequence")
    for residue_id in value:
        residue_identity_chain(
            residue_id,
            subject=f"{name} entry",
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicate residue identities")
    return value


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be an immutable string sequence")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicates")
    return value


def _tied_residue_groups(value: Any) -> tuple[tuple[str, ...], ...]:
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise ValueError(
            "tied_residue_groups must be immutable residue identity groups"
        )
    tied_groups: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for group_index, group_value in enumerate(value):
        group = _residue_ids(
            group_value,
            f"tied_residue_groups group {group_index}",
        )
        if len(group) < 2:
            raise ValueError(
                f"tied_residue_groups group {group_index} must contain "
                "at least two residue identities"
            )
        overlap = seen & set(group)
        if overlap:
            raise ValueError(
                "tied_residue_groups cannot reuse residues across groups: "
                + ", ".join(sorted(overlap))
            )
        seen.update(group)
        tied_groups.append(group)
    return tuple(tied_groups)


def _biases(value: Any) -> Mapping[str, Mapping[str, float]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(
            "bias_by_residue must map residue identities to amino-acid biases"
        )
    for residue_id, amino_acid_biases in value.items():
        residue_identity_chain(
            residue_id,
            subject="bias_by_residue key",
        )
        if not isinstance(amino_acid_biases, Mapping) or not amino_acid_biases:
            raise ValueError(
                f"bias_by_residue {residue_id} must map amino acids to biases"
            )
        for amino_acid, bias in amino_acid_biases.items():
            if amino_acid not in PROTEINMPNN_ALPHABET:
                raise ValueError(
                    "bias_by_residue contains unsupported amino acid "
                    f"{amino_acid!r}"
                )
            if isinstance(bias, bool) or not isinstance(bias, (int, float)):
                raise ValueError(
                    f"bias_by_residue bias for {residue_id}/{amino_acid} "
                    "must be numeric"
                )
            if not isfinite(float(bias)):
                raise ValueError(
                    f"bias_by_residue bias for {residue_id}/{amino_acid} "
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

    designable = _residue_ids(
        constraints.designable_residue_ids,
        "designable_residue_ids",
    )
    fixed = _residue_ids(
        constraints.fixed_residue_ids,
        "fixed_residue_ids",
    )
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

    tied_groups = _tied_residue_groups(constraints.tied_residue_groups)
    biases = _biases(constraints.bias_by_residue)
    overlapping_residues = sorted(set(designable) & set(fixed))
    if overlapping_residues:
        raise ValueError(
            "residues cannot be both designable and fixed: "
            + ", ".join(overlapping_residues)
        )
    overlapping_chains = sorted(
        set(designed_chains) & set(fixed_chains)
    )
    if overlapping_chains:
        raise ValueError(
            "chains cannot be both designed and fixed: "
            + ", ".join(overlapping_chains)
        )
    for residue_id, amino_acid_biases in biases.items():
        for group_index, group in enumerate(tied_groups):
            if residue_id in group:
                raise ValueError(
                    f"bias_by_residue {residue_id} belongs to tied "
                    f"residue group {group_index}"
                )
        for amino_acid in amino_acid_biases:
            if amino_acid in omitted:
                raise ValueError(
                    f"bias_by_residue {residue_id} targets globally "
                    f"omitted amino acid {amino_acid}"
                )
