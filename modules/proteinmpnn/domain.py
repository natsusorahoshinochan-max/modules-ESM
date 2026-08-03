"""Repository-owned ProteinMPNN constraint and randomness domain rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any

from datatypes import (
    ProteinMPNNConstraints,
    ResidueLayout,
    validate_proteinmpnn_constraints,
)
from datatypes.protein import validate_residue_layout


_MAX_SEED = 9_007_199_254_740_991
_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


def normalize_design_parameters(
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, int | float]:
    """Validate and normalize the one shared v2 design parameter contract."""
    if binding_parameters or set(node_parameters) != {
        "effective_seed",
        "num_sequences",
        "temperature",
        "backbone_noise",
    }:
        raise ValueError(
            "ProteinMPNN design parameters are not fully resolved"
        )
    seed = node_parameters["effective_seed"]
    count = node_parameters["num_sequences"]
    temperature = node_parameters["temperature"]
    noise = node_parameters["backbone_noise"]
    if (
        type(seed) is not int
        or not 0 <= seed <= _MAX_SEED
        or type(count) is not int
        or not 1 <= count <= 100
        or isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(float(temperature))
        or not 0 < float(temperature) <= 10
        or isinstance(noise, bool)
        or not isinstance(noise, (int, float))
        or not math.isfinite(float(noise))
        or not 0 <= float(noise) <= 10
    ):
        raise ValueError(
            "ProteinMPNN design parameters are outside their contract"
        )
    return {
        "effective_seed": seed,
        "num_sequences": count,
        "temperature": float(temperature),
        "backbone_noise": float(noise),
    }


def validate_layout(
    value: object,
    *,
    subject: str = "layout",
) -> tuple[ResidueLayout, tuple[str, ...], tuple[str, ...]]:
    """Validate an identity-complete contiguous-chain layout."""
    layout = validate_residue_layout(value, subject=subject)
    assert layout.residue_ids is not None
    return (
        layout,
        tuple(layout.chain_id.split(",")),
        tuple(residue_id.split(":", 1)[0] for residue_id in layout.residue_ids),
    )


def _optional_list(value: object, name: str) -> list[Any] | None:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise ValueError(f"{name} must be an array")
    items = list(value)
    if name == "tied_residue_groups":
        items = [
            list(item)
            if isinstance(item, Sequence)
            and not isinstance(item, (str, bytes, bytearray))
            else item
            for item in items
        ]
    return items or None


def author_constraints(
    layout_value: object,
    parameters: Mapping[str, Any],
) -> ProteinMPNNConstraints:
    """Build and layout-validate one complete constraint value."""
    expected = {
        "designable_residue_ids",
        "fixed_residue_ids",
        "designed_chains",
        "fixed_chains",
        "omit_amino_acids",
        "tied_residue_groups",
        "bias_by_residue",
    }
    if set(parameters) != expected:
        raise ValueError(
            "constraint authoring parameters are not fully resolved"
        )
    layout, chain_order, residue_chains = validate_layout(layout_value)
    bias_entries = parameters["bias_by_residue"]
    if not isinstance(bias_entries, Sequence) or isinstance(
        bias_entries,
        (str, bytes, bytearray),
    ):
        raise ValueError("bias_by_residue must be an array")
    bias_by_residue: dict[str, dict[str, float]] = {}
    seen_biases: set[tuple[str, str]] = set()
    for index, entry in enumerate(bias_entries):
        if not isinstance(entry, Mapping) or set(entry) != {
            "residue_id",
            "amino_acid",
            "bias",
        }:
            raise ValueError(
                f"bias_by_residue[{index}] must contain residue_id, "
                "amino_acid, bias"
            )
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

    constraints = ProteinMPNNConstraints(
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
    validate_constraints_against_layout(
        constraints,
        layout=layout,
        chain_order=chain_order,
        residue_chains=residue_chains,
    )
    return constraints


def validate_constraints_against_layout(
    constraints: ProteinMPNNConstraints,
    *,
    layout: ResidueLayout,
    chain_order: Sequence[str] | None = None,
    residue_chains: Sequence[str] | None = None,
) -> None:
    """Apply every layout- and chain-dependent constraint invariant."""
    validate_proteinmpnn_constraints(constraints)
    if constraints.layout != layout:
        raise ValueError(
            "constraint layout identity does not match the target layout"
        )
    if _CANONICAL_AMINO_ACIDS <= set(
        constraints.omit_amino_acids or ()
    ):
        raise ValueError(
            "omit_amino_acids must leave at least one canonical amino acid"
        )
    if chain_order is None or residue_chains is None:
        _, resolved_order, resolved_residue_chains = validate_layout(layout)
        chain_order = resolved_order
        residue_chains = resolved_residue_chains
    known_chains = set(chain_order)
    requested_designed = set(constraints.designed_chains or ())
    requested_fixed = set(constraints.fixed_chains or ())
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

    residue_ids = list(layout.residue_ids or ())
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

    designable = set(constraints.designable_residue_ids or ())
    explicitly_fixed = set(constraints.fixed_residue_ids or ())
    for residue_id in sorted(designable):
        _, chain = validate_residue(residue_id, "designable")
        if chain not in effective_designed:
            raise ValueError(
                f"designable residue {residue_id} belongs to fixed chain {chain}"
            )
    for residue_id in sorted(explicitly_fixed):
        _, chain = validate_residue(residue_id, "fixed")
        if chain not in effective_designed:
            raise ValueError(
                f"fixed residue {residue_id} belongs to already-fixed chain {chain}"
            )
    effective_fixed = set(explicitly_fixed)
    if designable:
        effective_fixed.update(
            residue_id
            for residue_id, chain in zip(
                residue_ids,
                residue_chains,
                strict=True,
            )
            if chain in effective_designed and residue_id not in designable
        )
    for group_index, group in enumerate(
        constraints.tied_residue_groups or ()
    ):
        for residue_id in group:
            _, chain = validate_residue(residue_id, "tied")
            if chain not in effective_designed or residue_id in effective_fixed:
                raise ValueError(
                    f"tied residue group {group_index} includes non-designable "
                    f"residue {residue_id}"
                )
    for residue_id in (constraints.bias_by_residue or {}):
        _, chain = validate_residue(residue_id, "bias_by_residue")
        if chain not in effective_designed or residue_id in effective_fixed:
            raise ValueError(
                f"bias_by_residue {residue_id} is not designable"
            )


def random_fixed_positions(
    layout_value: object,
    *,
    effective_seed: object,
    fraction: object,
) -> ProteinMPNNConstraints:
    """Select a deterministic without-replacement subset by SHA-256 rank."""
    layout, _, _ = validate_layout(layout_value)
    if (
        type(effective_seed) is not int
        or effective_seed < 0
        or effective_seed > _MAX_SEED
    ):
        raise ValueError("effective_seed is outside the supported range")
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(float(fraction))
        or not 0 <= float(fraction) <= 1
    ):
        raise ValueError("fraction must be finite and in [0, 1]")
    count = int(layout.length * float(fraction))
    ranked = sorted(
        range(layout.length),
        key=lambda position: (
            hashlib.sha256(
                (
                    "protein-workbench-proteinmpnn-fixed/v2\0"
                    f"{effective_seed}\0"
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
