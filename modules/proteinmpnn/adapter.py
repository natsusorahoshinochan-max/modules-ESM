"""ProteinMPNN adapter: thin wrapper around repositories/ProteinMPNN/ ."""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import torch

from datatypes import (
    ProteinMPNNConstraints,
    ProteinSequence,
)
from modules.proteinmpnn.constraint_validation import validate_constraints

# Path to ProteinMPNN repository
_PROTEINMPNN_DIR = Path(__file__).parent.parent.parent / "repositories" / "ProteinMPNN"

_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"
_ALPHABET_DICT = dict(zip(_ALPHABET, range(21)))
_SUPPORTED_MODELS = {"v_48_002", "v_48_010", "v_48_020", "v_48_030"}


@dataclass(frozen=True)
class ProteinMPNNDesignRequest:
    """Validated, provider-native inputs for one ProteinMPNN design call."""

    pdb_dict_list: list[dict[str, Any]]
    model_name: str
    num_sequences: int
    temperature: float
    backbone_noise: float
    chain_dict: dict[str, tuple[list[str], list[str]]]
    fixed_position_dict: dict[str, dict[str, list[int]]] | None
    tied_positions_dict: dict[str, list[dict[str, list[int]]]] | None
    bias_by_res_dict: dict[str, dict[str, list[list[float]]]] | None
    omit_amino_acids: list[str]
    reference_sequences: dict[str, str] | None


class ProteinMPNNProvider(Protocol):
    """External provider boundary used by the adapter."""

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        """Parse a PDB string into ProteinMPNN's structure representation."""

    def design(
        self, request: ProteinMPNNDesignRequest
    ) -> tuple[list[ProteinSequence], float | None]:
        """Execute one already-validated ProteinMPNN request."""


def _get_checkpoint_path(model_name: str) -> str:
    """Get the path to a ProteinMPNN model checkpoint."""
    candidates = [
        _PROTEINMPNN_DIR / "vanilla_model_weights" / f"{model_name}.pt",
        _PROTEINMPNN_DIR / "soluble_model_weights" / f"{model_name}.pt",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    raise FileNotFoundError(
        f"ProteinMPNN checkpoint not found for {model_name}. "
        f"Looked in vanilla_model_weights/ and soluble_model_weights/"
    )


def _load_model(
    model_name: str = "v_48_020",
    backbone_noise: float = 0.0,
) -> Any:
    """Load a ProteinMPNN model from checkpoint."""
    # Add ProteinMPNN dir to path temporarily for imports
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import ProteinMPNN as MPNNModel

    checkpoint_path = _get_checkpoint_path(model_name)
    device = torch.device("cpu")

    model = MPNNModel(
        num_letters=21,
        node_features=128,
        edge_features=128,
        hidden_dim=128,
        num_encoder_layers=3,
        num_decoder_layers=3,
        vocab=21,
        k_neighbors=48,
        augment_eps=backbone_noise,
        dropout=0.1,
    )
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()
    return model, device


def _parse_structure(
    pdb_string: str,
    temp_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Convert a PDB string to ProteinMPNN's pdb_dict_list format."""
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import parse_PDB

    temporary_root = Path(temp_dir) if temp_dir is not None else None
    if temporary_root is not None:
        temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".pdb",
        delete=False,
        dir=temporary_root,
    ) as tmp:
        tmp.write(pdb_string)
        pdb_path = tmp.name

    try:
        pdb_dict_list = parse_PDB(pdb_path)
        return pdb_dict_list
    finally:
        Path(pdb_path).unlink(missing_ok=True)


def _featurize(
    request: ProteinMPNNDesignRequest,
    device: torch.device,
) -> dict[str, Any]:
    """Featurize parsed PDB data into tensors for ProteinMPNN.
    
    Converts tied_featurize's tuple output to a dict keyed by field name.
    """
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import tied_featurize

    result = tied_featurize(
        request.pdb_dict_list,
        device,
        request.chain_dict,
        request.fixed_position_dict,
        None,  # global omit rules are applied by tied_sample
        request.tied_positions_dict,
        None,  # pssm_dict
        request.bias_by_res_dict,
    )
    # tied_featurize returns a tuple; convert to dict for downstream use
    keys = [
        "X", "S", "mask", "lengths", "chain_M", "chain_encoding_all",
        "letter_list_list", "visible_list_list", "masked_list_list",
        "masked_chain_length_list_list", "chain_M_pos", "omit_AA_mask",
        "residue_idx", "dihedral_mask", "tied_pos_list_of_lists_list",
        "pssm_coef_all", "pssm_bias_all", "pssm_log_odds_all",
        "bias_by_res_all", "tied_beta",
    ]
    return dict(zip(keys, result))


def _run_design(
    model: Any,
    batch: dict[str, Any],
    num_sequences: int,
    temperature: float,
    device: torch.device,
    omit_amino_acids: list[str],
) -> list[ProteinSequence]:
    """Run ProteinMPNN design and return list of ProteinSequence objects."""
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import _S_to_seq

    alphabet = "ACDEFGHIKLMNPQRSTVWYX"
    omit_AAs_np = np.array(
        [amino_acid in omit_amino_acids for amino_acid in alphabet],
        dtype=np.float32,
    )
    bias_AAs_np = np.zeros(21, dtype=np.float32)

    X = batch["X"]
    S = batch["S"]
    mask = batch["mask"]
    chain_M = batch["chain_M"]
    chain_encoding_all = batch["chain_encoding_all"]
    residue_idx = batch["residue_idx"]
    chain_M_pos = batch["chain_M_pos"]
    tied_position_batches = batch.get("tied_pos_list_of_lists_list")

    sequences: list[ProteinSequence] = []

    for _ in range(num_sequences):
        randn = torch.randn(chain_M.shape, device=device)
        tied_pos_list = (
            [
                [int(position) for position in group]
                for group in tied_position_batches[0]
            ]
            if tied_position_batches
            else []
        )

        bias_by_res = batch.get("bias_by_res_all",
            torch.zeros((1, X.shape[1], 21), device=device))
        if isinstance(bias_by_res, torch.Tensor) and bias_by_res.dim() == 0:
            bias_by_res = torch.zeros((1, X.shape[1], 21), device=device)

        sample_out = model.tied_sample(
            X, randn, S, chain_M, chain_encoding_all, residue_idx,
            mask=mask, temperature=temperature,
            omit_AAs_np=omit_AAs_np, bias_AAs_np=bias_AAs_np,
            chain_M_pos=chain_M_pos, tied_pos=tied_pos_list,
            tied_beta=torch.ones(X.shape[1], device=device),
            bias_by_res=bias_by_res,
        )

        # Decode sequences — _S_to_seq expects 1D tensors, squeeze batch dim
        S_sample = sample_out["S"]
        seq_str = _S_to_seq(S_sample[0], mask[0])
        sequences.append(ProteinSequence(sequence=seq_str))

    return sequences


def _compute_score(
    model: Any,
    batch: dict[str, Any],
    sequence: str,
    device: torch.device,
) -> float:
    """Score a sequence against a structure using ProteinMPNN."""
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import _scores

    alphabet = "ACDEFGHIKLMNPQRSTVWYX"
    alphabet_dict = dict(zip(alphabet, range(21)))

    X = batch["X"]
    mask = batch["mask"]
    chain_M = batch["chain_M"]
    chain_encoding_all = batch["chain_encoding_all"]
    residue_idx = batch["residue_idx"]

    # Encode sequence
    seq_encoded = torch.zeros((1, X.shape[1]), dtype=torch.int64, device=device)
    for i, aa in enumerate(sequence):
        if i < X.shape[1] and aa in alphabet_dict:
            seq_encoded[0, i] = alphabet_dict[aa]

    randn = torch.randn(chain_M.shape, device=device)

    # Forward pass
    log_probs = model.forward(
        X, seq_encoded, mask, chain_M, residue_idx, chain_encoding_all, randn
    )
    mask_for_loss = mask * chain_M
    score = float(_scores(seq_encoded, log_probs, mask_for_loss).detach().cpu().numpy()[0])
    return score


class _LocalProteinMPNNProvider:
    def __init__(self, temp_dir: str | Path | None = None) -> None:
        self._temp_dir = temp_dir

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        return _parse_structure(pdb_string, temp_dir=self._temp_dir)

    def design(
        self, request: ProteinMPNNDesignRequest
    ) -> tuple[list[ProteinSequence], float | None]:
        model, device = _load_model(request.model_name, request.backbone_noise)
        batch = _featurize(request, device)
        if request.reference_sequences is not None:
            offset = 0
            for chain in batch["letter_list_list"][0]:
                chain_sequence = request.reference_sequences[str(chain)]
                encoded = torch.tensor(
                    [_ALPHABET_DICT[amino_acid] for amino_acid in chain_sequence],
                    dtype=torch.int64,
                    device=device,
                )
                chain_end = offset + len(chain_sequence)
                batch["S"][0, offset:chain_end] = encoded
                offset = chain_end
        sequences = _run_design(
            model,
            batch,
            request.num_sequences,
            request.temperature,
            device,
            request.omit_amino_acids,
        )

        native_seq = request.pdb_dict_list[0].get("seq", "")
        avg_score = None
        try:
            native_score = _compute_score(model, batch, native_seq, device)
            avg_score = native_score
        except Exception as e:
            import warnings
            warnings.warn(f"ProteinMPNN score computation failed: {e}")

        return sequences, avg_score


def _chain_sequences(
    pdb_entry: dict[str, Any],
) -> list[tuple[str, str]]:
    return [
        (key.removeprefix("seq_chain_"), str(value))
        for key, value in pdb_entry.items()
        if key.startswith("seq_chain_")
    ]


def _position_to_chain(
    position: int,
    chains: list[tuple[str, str]],
) -> tuple[str, int]:
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ValueError(
            f"residue position {position!r} must be a non-negative zero-based integer"
        )
    offset = 0
    for chain, sequence in chains:
        next_offset = offset + len(sequence)
        if position < next_offset:
            return chain, position - offset
        offset = next_offset
    raise ValueError(
        f"residue position {position} is outside target layout of length {offset}"
    )


def validate_design_parameters(
    model_name: str,
    num_sequences: int,
    temperature: float,
    backbone_noise: float,
) -> None:
    """Reject unsupported ProteinMPNN sampling parameters."""
    if model_name not in _SUPPORTED_MODELS:
        raise ValueError(
            f"model_name must be one of {sorted(_SUPPORTED_MODELS)}, got {model_name!r}"
        )
    if isinstance(num_sequences, bool) or not isinstance(num_sequences, int):
        raise ValueError("num_sequences must be an integer")
    if num_sequences < 1:
        raise ValueError("num_sequences must be at least 1")
    if not isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be a finite number greater than 0")
    if not isfinite(backbone_noise) or backbone_noise < 0:
        raise ValueError("backbone_noise must be a finite number at least 0")


def _structure_target(
    pdb_dict_list: list[dict[str, Any]],
) -> tuple[str, list[tuple[str, str]]]:
    if len(pdb_dict_list) != 1:
        raise ValueError("structure must parse to exactly one ProteinMPNN target")
    pdb_entry = pdb_dict_list[0]
    chains = _chain_sequences(pdb_entry)
    if not chains:
        raise ValueError("No valid chains found in PDB structure")
    return str(pdb_entry["name"]), chains


def _chain_partition(
    chains: list[tuple[str, str]],
    constraints: ProteinMPNNConstraints,
) -> tuple[list[str], list[str]]:
    chain_ids = [chain for chain, _ in chains]
    requested_designed = list(constraints.designed_chains or [])
    requested_fixed = list(constraints.fixed_chains or [])
    unknown_chains = sorted(
        (set(requested_designed) | set(requested_fixed)) - set(chain_ids)
    )
    if unknown_chains:
        raise ValueError(
            "constraint chain IDs are not present in the structure: "
            + ", ".join(unknown_chains)
        )
    if requested_designed:
        fixed_chains = [
            chain for chain in chain_ids if chain not in set(requested_designed)
        ]
        if requested_fixed and set(requested_fixed) != set(fixed_chains):
            raise ValueError(
                "designed_chains and fixed_chains must partition all structure chains"
            )
        return requested_designed, fixed_chains
    elif requested_fixed:
        designed_chains = [
            chain for chain in chain_ids if chain not in set(requested_fixed)
        ]
        return designed_chains, requested_fixed
    return chain_ids, []


def _fixed_position_payload(
    name: str,
    chains: list[tuple[str, str]],
    designed_chains: list[str],
    constraints: ProteinMPNNConstraints,
) -> dict[str, dict[str, list[int]]] | None:
    raw_fixed_positions = list(constraints.fixed_positions or [])
    fixed_positions = set(raw_fixed_positions)
    if constraints.designable_positions:
        raw_designable_positions = list(constraints.designable_positions)
        designable_positions = set(raw_designable_positions)
        for position in designable_positions:
            chain, _ = _position_to_chain(position, chains)
            if chain not in designed_chains:
                raise ValueError(
                    f"designable position {position} belongs to fixed chain {chain}"
                )
        target_position = 0
        for chain, sequence in chains:
            if chain in designed_chains:
                fixed_positions.update(
                    position
                    for position in range(
                        target_position, target_position + len(sequence)
                    )
                    if position not in designable_positions
                )
            target_position += len(sequence)

    if not fixed_positions:
        return None
    fixed_by_chain = {chain: [] for chain, _ in chains}
    for position in sorted(fixed_positions):
        chain, local_position = _position_to_chain(position, chains)
        if chain not in designed_chains:
            raise ValueError(
                f"fixed position {position} belongs to already-fixed chain {chain}"
            )
        fixed_by_chain[chain].append(local_position + 1)
    return {name: fixed_by_chain}


def _tied_position_payload(
    name: str,
    chains: list[tuple[str, str]],
    designed_chains: list[str],
    constraints: ProteinMPNNConstraints,
    fixed_position_dict: dict[str, dict[str, list[int]]] | None,
) -> dict[str, list[dict[str, list[int]]]] | None:
    if not constraints.tied_positions:
        return None
    tied_groups: list[dict[str, list[int]]] = []
    for group_index, group in enumerate(constraints.tied_positions):
        chain_positions: dict[str, list[int]] = {}
        for position in group:
            chain, local_position = _position_to_chain(position, chains)
            chain_positions.setdefault(chain, []).append(local_position + 1)
        fixed_positions = (fixed_position_dict or {}).get(name, {})
        for chain, positions in chain_positions.items():
            conflict = sorted(set(positions) & set(fixed_positions.get(chain, [])))
            if conflict:
                raise ValueError(
                    f"tied position group {group_index} includes fixed position "
                    f"{chain}:{conflict[0]}"
                )
        if not set(chain_positions) & set(designed_chains):
            raise ValueError(
                f"tied position group {group_index} contains no designable chain"
            )
        for chain, positions in chain_positions.items():
            if chain not in designed_chains:
                raise ValueError(
                    f"tied position group {group_index} includes fixed-chain "
                    f"position {chain}:{positions[0]}"
                )
        tied_groups.append(chain_positions)
    return {name: tied_groups}


def _bias_payload(
    name: str,
    chains: list[tuple[str, str]],
    designed_chains: list[str],
    constraints: ProteinMPNNConstraints,
    fixed_position_dict: dict[str, dict[str, list[int]]] | None,
) -> dict[str, dict[str, list[list[float]]]] | None:
    if not constraints.bias_by_res:
        return None
    bias_by_chain = {
        chain: [[0.0] * len(_ALPHABET) for _ in sequence]
        for chain, sequence in chains
    }
    for position, amino_acid_biases in constraints.bias_by_res.items():
        chain, local_position = _position_to_chain(position, chains)
        if chain not in designed_chains:
            raise ValueError(
                f"bias_by_res position {position} belongs to fixed chain {chain}"
            )
        fixed_positions = (fixed_position_dict or {}).get(name, {}).get(chain, [])
        if local_position + 1 in fixed_positions:
            raise ValueError(
                f"bias_by_res position {position} is fixed by the effective "
                "position mask"
            )
        for amino_acid, bias in amino_acid_biases.items():
            numeric_bias = float(bias)
            amino_acid_index = _ALPHABET_DICT[amino_acid]
            bias_by_chain[chain][local_position][amino_acid_index] = numeric_bias
    return {name: bias_by_chain}


def _omitted_amino_acids(
    constraints: ProteinMPNNConstraints,
) -> list[str]:
    return list(constraints.omit_amino_acids or [])


def _reference_sequences(
    chains: list[tuple[str, str]],
    reference_sequence: str | None,
) -> dict[str, str] | None:
    if reference_sequence is None:
        return None
    structure_length = sum(len(sequence) for _, sequence in chains)
    if len(reference_sequence) != structure_length:
        raise ValueError(
            "reference sequence length "
            f"{len(reference_sequence)} does not match structure length "
            f"{structure_length}; padding and truncation are not supported"
        )
    unsupported = sorted(set(reference_sequence) - set(_ALPHABET))
    if unsupported:
        raise ValueError(
            "reference sequence contains unsupported amino acids: "
            + ", ".join(unsupported)
        )
    split_reference = {}
    offset = 0
    for chain, structure_sequence in chains:
        chain_end = offset + len(structure_sequence)
        split_reference[chain] = reference_sequence[offset:chain_end]
        offset = chain_end
    return split_reference


def _prepare_design_request(
    pdb_dict_list: list[dict[str, Any]],
    model_name: str,
    num_sequences: int,
    temperature: float,
    backbone_noise: float,
    constraints: ProteinMPNNConstraints | None,
    reference_sequence: str | None,
) -> ProteinMPNNDesignRequest:
    validate_design_parameters(
        model_name, num_sequences, temperature, backbone_noise
    )
    name, chains = _structure_target(pdb_dict_list)
    selected_constraints = (
        ProteinMPNNConstraints() if constraints is None else constraints
    )
    validate_constraints(selected_constraints)
    designed_chains, fixed_chains = _chain_partition(
        chains, selected_constraints
    )
    fixed_position_dict = _fixed_position_payload(
        name, chains, designed_chains, selected_constraints
    )
    return ProteinMPNNDesignRequest(
        pdb_dict_list=pdb_dict_list,
        model_name=model_name,
        num_sequences=num_sequences,
        temperature=temperature,
        backbone_noise=backbone_noise,
        chain_dict={name: (designed_chains, fixed_chains)},
        fixed_position_dict=fixed_position_dict,
        tied_positions_dict=_tied_position_payload(
            name,
            chains,
            designed_chains,
            selected_constraints,
            fixed_position_dict,
        ),
        bias_by_res_dict=_bias_payload(
            name,
            chains,
            designed_chains,
            selected_constraints,
            fixed_position_dict,
        ),
        omit_amino_acids=_omitted_amino_acids(selected_constraints),
        reference_sequences=_reference_sequences(chains, reference_sequence),
    )


def design_sequences(
    pdb_string: str,
    model_name: str = "v_48_020",
    num_sequences: int = 1,
    temperature: float = 0.1,
    backbone_noise: float = 0.0,
    constraints: ProteinMPNNConstraints | None = None,
    reference_sequence: str | None = None,
    provider: ProteinMPNNProvider | None = None,
    temp_dir: str | Path | None = None,
) -> tuple[list[ProteinSequence], float | None]:
    """Run ProteinMPNN design and return generated sequences with score.

    Returns (sequences, average_score).
    """
    selected_provider = provider or _LocalProteinMPNNProvider(temp_dir=temp_dir)
    pdb_dict_list = selected_provider.parse_structure(pdb_string)
    request = _prepare_design_request(
        pdb_dict_list,
        model_name,
        num_sequences,
        temperature,
        backbone_noise,
        constraints,
        reference_sequence,
    )
    return selected_provider.design(request)


def score_sequence(
    pdb_string: str,
    sequence: str,
    model_name: str = "v_48_020",
    temp_dir: str | Path | None = None,
) -> float:
    """Score how well a sequence fits a structure."""
    model, device = _load_model(model_name)
    pdb_dict_list = _parse_structure(pdb_string, temp_dir=temp_dir)

    if len(pdb_dict_list) == 0:
        raise ValueError("No valid chains found in PDB structure")

    request = _prepare_design_request(
        pdb_dict_list,
        model_name,
        1,
        0.1,
        0.0,
        None,
        None,
    )
    batch = _featurize(request, device)
    return _compute_score(model, batch, sequence, device)
