"""ProteinMPNN provider-native request and constraint translation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datatypes.residue import ResidueLayout

from .domain import ProteinMPNNConstraints


_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"
_ALPHABET_DICT = dict(zip(_ALPHABET, range(21)))


@dataclass(frozen=True)
class ProteinMPNNDesignRequest:
    """Validated, provider-native inputs for one ProteinMPNN design call."""

    pdb_dict_list: list[dict[str, Any]]
    model_name: str
    num_sequences: int
    temperature: float
    backbone_noise: float
    seed: int
    target_length: int
    target_layout: ResidueLayout
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...]
    workbench_chain_order: tuple[str, ...]
    provider_structure_chain_order: tuple[str, ...]
    provider_chain_order: tuple[str, ...]
    chain_dict: dict[str, tuple[list[str], list[str]]]
    fixed_position_dict: dict[str, dict[str, list[int]]] | None
    tied_positions_dict: dict[str, list[dict[str, list[int]]]] | None
    bias_by_res_dict: dict[str, dict[str, list[list[float]]]] | None
    omit_amino_acids: list[str]
    reference_sequences: dict[str, str] | None


def _chain_sequences(
    pdb_entry: dict[str, Any],
) -> list[tuple[str, str]]:
    return [
        (key.removeprefix("seq_chain_"), value)
        for key, value in pdb_entry.items()
        if key.startswith("seq_chain_")
    ]


def _structure_target(
    pdb_dict_list: list[dict[str, Any]],
) -> tuple[str, list[tuple[str, str]]]:
    pdb_entry = pdb_dict_list[0]
    chains = _chain_sequences(pdb_entry)
    return pdb_entry["name"], chains


def _provider_chains_by_workbench_chain(
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...],
    *,
    workbench_chain_order: tuple[str, ...],
    provider_structure_chain_order: tuple[str, ...],
) -> dict[str, list[str]]:
    provider_chains_by_workbench_chain = {
        chain: [] for chain in workbench_chain_order
    }
    workbench_chain_by_provider_chain: dict[str, str] = {}
    for residue_id, _, provider_chain, _ in residue_identity_mapping:
        workbench_chain_by_provider_chain.setdefault(
            provider_chain,
            residue_id.split(":", 1)[0],
        )
    for provider_chain in provider_structure_chain_order:
        workbench_chain = workbench_chain_by_provider_chain[provider_chain]
        provider_chains_by_workbench_chain[workbench_chain].append(
            provider_chain
        )
    return provider_chains_by_workbench_chain


def _chain_partition(
    chains: list[tuple[str, str]],
    constraints: ProteinMPNNConstraints,
    *,
    workbench_chain_order: tuple[str, ...],
    provider_chains_by_workbench_chain: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    provider_chain_ids = [chain for chain, _ in chains]
    requested_designed = list(constraints.designed_chains or [])
    requested_fixed = list(constraints.fixed_chains or [])
    if requested_designed:
        requested_designed_set = set(requested_designed)
        designed_workbench_chains = [
            chain
            for chain in workbench_chain_order
            if chain in requested_designed_set
        ]
        fixed_workbench_chains = [
            chain
            for chain in workbench_chain_order
            if chain not in requested_designed_set
        ]
        return (
            [
                provider_chain
                for chain in designed_workbench_chains
                for provider_chain in provider_chains_by_workbench_chain[chain]
            ],
            [
                provider_chain
                for chain in fixed_workbench_chains
                for provider_chain in provider_chains_by_workbench_chain[chain]
            ],
        )
    elif requested_fixed:
        requested_fixed_set = set(requested_fixed)
        designed_workbench_chains = [
            chain
            for chain in workbench_chain_order
            if chain not in requested_fixed_set
        ]
        fixed_workbench_chains = [
            chain
            for chain in workbench_chain_order
            if chain in requested_fixed_set
        ]
        return (
            [
                provider_chain
                for chain in designed_workbench_chains
                for provider_chain in provider_chains_by_workbench_chain[chain]
            ],
            [
                provider_chain
                for chain in fixed_workbench_chains
                for provider_chain in provider_chains_by_workbench_chain[chain]
            ],
        )
    return provider_chain_ids, []


def _sequence_in_provider_chain_order(
    sequence: str,
    request: ProteinMPNNDesignRequest,
) -> str:
    sequence_by_provider_chain = {
        chain: [""] * len(request.pdb_dict_list[0][f"seq_chain_{chain}"])
        for chain in request.provider_structure_chain_order
    }
    for amino_acid, (_, _, provider_chain, provider_position) in zip(
        sequence,
        request.residue_identity_mapping,
        strict=True,
    ):
        sequence_by_provider_chain[provider_chain][provider_position - 1] = (
            amino_acid
        )
    return "".join(
        "".join(sequence_by_provider_chain[chain])
        for chain in request.provider_chain_order
    )


def _fixed_position_payload(
    name: str,
    chains: list[tuple[str, str]],
    designed_chains: list[str],
    constraints: ProteinMPNNConstraints,
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...],
) -> dict[str, dict[str, list[int]]] | None:
    provider_position_by_residue = {
        residue_id: (provider_chain, provider_position)
        for residue_id, _, provider_chain, provider_position in (
            residue_identity_mapping
        )
    }
    fixed_positions = {
        provider_position_by_residue[residue_id]
        for residue_id in constraints.fixed_residue_ids or ()
    }
    if constraints.designable_residue_ids:
        designable_positions = {
            provider_position_by_residue[residue_id]
            for residue_id in constraints.designable_residue_ids
        }
        for chain, sequence in chains:
            if chain in designed_chains:
                fixed_positions.update(
                    (chain, provider_position)
                    for provider_position in range(1, len(sequence) + 1)
                    if (chain, provider_position) not in designable_positions
                )

    if not fixed_positions:
        return None
    fixed_by_chain = {chain: [] for chain, _ in chains}
    for chain, provider_position in sorted(fixed_positions):
        fixed_by_chain[chain].append(provider_position)
    return {name: fixed_by_chain}


def _tied_position_payload(
    name: str,
    constraints: ProteinMPNNConstraints,
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...],
) -> dict[str, list[dict[str, list[int]]]] | None:
    if not constraints.tied_residue_groups:
        return None
    provider_position_by_residue = {
        residue_id: (provider_chain, provider_position)
        for residue_id, _, provider_chain, provider_position in (
            residue_identity_mapping
        )
    }
    tied_groups: list[dict[str, list[int]]] = []
    for group in constraints.tied_residue_groups:
        chain_positions: dict[str, list[int]] = {}
        for residue_id in group:
            chain, provider_position = provider_position_by_residue[residue_id]
            chain_positions.setdefault(chain, []).append(provider_position)
        tied_groups.append(chain_positions)
    return {name: tied_groups}


def _bias_payload(
    name: str,
    chains: list[tuple[str, str]],
    constraints: ProteinMPNNConstraints,
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...],
) -> dict[str, dict[str, list[list[float]]]] | None:
    if not constraints.bias_by_residue:
        return None
    provider_position_by_residue = {
        residue_id: (provider_chain, provider_position)
        for residue_id, _, provider_chain, provider_position in (
            residue_identity_mapping
        )
    }
    bias_by_chain = {
        chain: [[0.0] * len(_ALPHABET) for _ in sequence]
        for chain, sequence in chains
    }
    for residue_id, amino_acid_biases in (
        constraints.bias_by_residue.items()
    ):
        chain, provider_position = provider_position_by_residue[residue_id]
        for amino_acid, bias in amino_acid_biases.items():
            numeric_bias = float(bias)
            amino_acid_index = _ALPHABET_DICT[amino_acid]
            bias_by_chain[chain][provider_position - 1][amino_acid_index] = (
                numeric_bias
            )
    return {name: bias_by_chain}


def _reference_sequences(
    reference_sequence: str | None,
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...],
    provider_structure_chain_order: tuple[str, ...],
) -> dict[str, str] | None:
    if reference_sequence is None:
        return None
    split_reference = {
        chain: [] for chain in provider_structure_chain_order
    }
    for amino_acid, (_, _, provider_chain, _) in zip(
        reference_sequence,
        residue_identity_mapping,
        strict=True,
    ):
        split_reference[provider_chain].append(amino_acid)
    return {
        chain: "".join(split_reference[chain])
        for chain in provider_structure_chain_order
    }


def _prepare_design_request(
    pdb_dict_list: list[dict[str, Any]],
    model_name: str,
    num_sequences: int,
    temperature: float,
    backbone_noise: float,
    seed: int,
    constraints: ProteinMPNNConstraints | None,
    reference_sequence: str | None,
    *,
    target_layout: ResidueLayout,
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...],
    workbench_chain_order: tuple[str, ...],
    provider_structure_chain_order: tuple[str, ...],
) -> ProteinMPNNDesignRequest:
    name, chains = _structure_target(pdb_dict_list)
    selected_constraints = (
        ProteinMPNNConstraints(layout=target_layout)
        if constraints is None
        else constraints
    )
    provider_chains_by_workbench_chain = (
        _provider_chains_by_workbench_chain(
            residue_identity_mapping,
            workbench_chain_order=workbench_chain_order,
            provider_structure_chain_order=provider_structure_chain_order,
        )
    )
    designed_chains, fixed_chains = _chain_partition(
        chains,
        selected_constraints,
        workbench_chain_order=workbench_chain_order,
        provider_chains_by_workbench_chain=(
            provider_chains_by_workbench_chain
        ),
    )
    fixed_position_dict = _fixed_position_payload(
        name,
        chains,
        designed_chains,
        selected_constraints,
        residue_identity_mapping,
    )
    return ProteinMPNNDesignRequest(
        pdb_dict_list=pdb_dict_list,
        model_name=model_name,
        num_sequences=num_sequences,
        temperature=temperature,
        backbone_noise=backbone_noise,
        seed=seed,
        target_length=target_layout.length,
        target_layout=target_layout,
        residue_identity_mapping=residue_identity_mapping,
        workbench_chain_order=workbench_chain_order,
        provider_structure_chain_order=provider_structure_chain_order,
        provider_chain_order=tuple(
            (*sorted(designed_chains), *sorted(fixed_chains))
        ),
        chain_dict={name: (designed_chains, fixed_chains)},
        fixed_position_dict=fixed_position_dict,
        tied_positions_dict=_tied_position_payload(
            name,
            selected_constraints,
            residue_identity_mapping,
        ),
        bias_by_res_dict=_bias_payload(
            name,
            chains,
            selected_constraints,
            residue_identity_mapping,
        ),
        omit_amino_acids=list(selected_constraints.omit_amino_acids or []),
        reference_sequences=_reference_sequences(
            reference_sequence,
            residue_identity_mapping,
            provider_structure_chain_order,
        ),
    )
