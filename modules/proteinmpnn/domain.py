"""Repository-owned ProteinMPNN constraint and randomness domain rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from math import isfinite
from typing import Any, Optional, cast

from datatypes.i_json import FrozenList, freeze_i_json
from datatypes.residue import (
    ResidueLayout,
    residue_identity_chain,
    validate_residue_layout,
)


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)


@dataclass(frozen=True, slots=True)
class ProteinMPNNConstraints:
    """Residue-level constraints for ProteinMPNN design.

    Residues are addressed by stable identities from the complete target
    layout. The ProteinMPNN Adapter performs the single conversion to upstream
    one-based, chain-qualified positions.

    ``designable_residue_ids`` is a whitelist within the designed chains;
    unlisted residues are fixed. ``fixed_residue_ids`` fixes individual
    residues. ``designed_chains`` and ``fixed_chains`` select the chain
    partition. ``omit_amino_acids`` is a global sampling exclusion.
    ``tied_residue_groups`` contains identity groups sampled as the same amino
    acid. ``bias_by_residue`` maps identities to per-amino-acid logit biases.
    None means no constraint in that dimension.
    """
    layout: ResidueLayout
    designable_residue_ids: Optional[tuple[str, ...]] = None
    fixed_residue_ids: Optional[tuple[str, ...]] = None
    designed_chains: Optional[tuple[str, ...]] = None
    fixed_chains: Optional[tuple[str, ...]] = None
    omit_amino_acids: Optional[tuple[str, ...]] = None
    tied_residue_groups: Optional[tuple[tuple[str, ...], ...]] = None
    bias_by_residue: Optional[Mapping[str, Mapping[str, float]]] = None

    def __post_init__(self) -> None:
        for name in (
            "designable_residue_ids",
            "fixed_residue_ids",
            "designed_chains",
            "fixed_chains",
            "omit_amino_acids",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _ordered_list(value, field_name=name),
                )
        if self.tied_residue_groups is not None:
            object.__setattr__(
                self,
                "tied_residue_groups",
                FrozenList(
                    _ordered_list(
                        group,
                        field_name="tied_residue_groups entry",
                    )
                    for group in _ordered_list(
                        self.tied_residue_groups,
                        field_name="tied_residue_groups",
                    )
                ),
            )
        if self.bias_by_residue is not None:
            object.__setattr__(
                self,
                "bias_by_residue",
                freeze_i_json(self.bias_by_residue),
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
    """Validate one complete ProteinMPNN constraint value."""
    layout = validate_residue_layout(
        constraints.layout,
        subject="constraints layout",
    )

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
    known_chains = set(layout.chain_id.split(","))
    requested_designed = set(designed_chains)
    requested_fixed = set(fixed_chains)
    unknown = sorted((requested_designed | requested_fixed) - known_chains)
    if unknown:
        raise ValueError(
            "constraint chain IDs are not present in the layout: "
            + ", ".join(unknown)
        )
    if requested_designed and requested_fixed and (
        requested_designed | requested_fixed
    ) != known_chains:
        raise ValueError(
            "designed_chains and fixed_chains must partition every layout chain"
        )
    effective_designed = (
        requested_designed
        if requested_designed
        else known_chains - requested_fixed
    )
    if not effective_designed:
        raise ValueError("constraints must leave at least one designed chain")

    residue_ids = cast(tuple[str, ...], layout.residue_ids)
    residue_chains = tuple(
        residue_id.split(":", 1)[0] for residue_id in residue_ids
    )
    position_by_id = {
        residue_id: position
        for position, residue_id in enumerate(residue_ids)
    }

    def validate_residue(residue_id: str, name: str) -> tuple[int, str]:
        position = position_by_id.get(residue_id)
        if position is None:
            raise ValueError(
                f"{name} residue {residue_id} is not present in the layout"
            )
        return position, residue_chains[position]

    designable_set = set(designable)
    fixed_set = set(fixed)
    for residue_id in sorted(designable_set):
        _, chain = validate_residue(residue_id, "designable")
        if chain not in effective_designed:
            raise ValueError(
                f"designable residue {residue_id} belongs to fixed chain {chain}"
            )
    for residue_id in sorted(fixed_set):
        _, chain = validate_residue(residue_id, "fixed")
        if chain not in effective_designed:
            raise ValueError(
                f"fixed residue {residue_id} belongs to already-fixed chain {chain}"
            )
    effective_fixed = set(fixed_set)
    if designable_set:
        effective_fixed.update(
            residue_id
            for residue_id, chain in zip(
                residue_ids,
                residue_chains,
                strict=True,
            )
            if chain in effective_designed and residue_id not in designable_set
        )
    for group_index, group in enumerate(tied_groups):
        for residue_id in group:
            _, chain = validate_residue(residue_id, "tied")
            if chain not in effective_designed or residue_id in effective_fixed:
                raise ValueError(
                    f"tied residue group {group_index} includes non-designable "
                    f"residue {residue_id}"
                )
    for residue_id in biases:
        _, chain = validate_residue(residue_id, "bias_by_residue")
        if chain not in effective_designed or residue_id in effective_fixed:
            raise ValueError(
                f"bias_by_residue {residue_id} is not designable"
            )


def _optional_list(value: object, name: str) -> list[Any] | None:
    items = list(value)
    if name == "tied_residue_groups":
        items = [list(item) for item in items]
    return items or None


def author_constraints(
    layout_value: object,
    parameters: Mapping[str, Any],
) -> ProteinMPNNConstraints:
    """Build one constraint value from an admitted layout and Plan values."""
    layout = cast(ResidueLayout, layout_value)
    bias_entries = parameters["bias_by_residue"]
    bias_by_residue: dict[str, dict[str, float]] = {}
    seen_biases: set[tuple[str, str]] = set()
    for entry in bias_entries:
        residue_id = entry["residue_id"]
        amino_acid = entry["amino_acid"]
        bias = entry["bias"]
        pair = (residue_id, amino_acid)
        if pair in seen_biases:
            raise ValueError(
                "bias_by_residue cannot repeat one residue/amino-acid pair"
            )
        seen_biases.add(pair)
        bias_by_residue.setdefault(residue_id, {})[amino_acid] = bias

    return ProteinMPNNConstraints(
        layout=layout,
        designable_residue_ids=_optional_list(
            parameters["designable_residue_ids"],
            "designable_residue_ids",
        ),
        fixed_residue_ids=_optional_list(
            parameters["fixed_residue_ids"],
            "fixed_residue_ids",
        ),
        designed_chains=_optional_list(
            parameters["designed_chains"],
            "designed_chains",
        ),
        fixed_chains=_optional_list(
            parameters["fixed_chains"],
            "fixed_chains",
        ),
        omit_amino_acids=_optional_list(
            parameters["omit_amino_acids"],
            "omit_amino_acids",
        ),
        tied_residue_groups=_optional_list(
            parameters["tied_residue_groups"],
            "tied_residue_groups",
        ),
        bias_by_residue=bias_by_residue or None,
    )


def random_fixed_positions(
    layout_value: object,
    *,
    effective_seed: object,
    fraction: object,
) -> ProteinMPNNConstraints:
    """Select a deterministic without-replacement subset by SHA-256 rank."""
    layout = cast(ResidueLayout, layout_value)
    seed = cast(int, effective_seed)
    selected_fraction = cast(float, fraction)
    count = int(layout.length * selected_fraction)
    ranked = sorted(
        range(layout.length),
        key=lambda position: (
            hashlib.sha256(
                (
                    "protein-workbench-proteinmpnn-fixed/v2\0"
                    f"{seed}\0"
                    f"{layout.residue_ids[position]}\0"
                    f"{position}"
                ).encode()
            ).digest(),
            position,
        ),
    )
    return ProteinMPNNConstraints(
        layout=layout,
        fixed_residue_ids=[
            layout.residue_ids[position]
            for position in sorted(ranked[:count])
        ],
    )
