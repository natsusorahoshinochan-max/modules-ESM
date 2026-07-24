"""ProteinMPNN adapter: thin wrapper around repositories/ProteinMPNN/ ."""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import torch

from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)

# Path to ProteinMPNN repository
_PROTEINMPNN_DIR = Path(__file__).parent.parent.parent / "repositories" / "ProteinMPNN"

_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"
_ALPHABET_DICT = dict(zip(_ALPHABET, range(21)))


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


def _load_model(model_name: str = "v_48_020") -> Any:
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
        augment_eps=0.05,
        dropout=0.1,
    )
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()
    return model, device


def _parse_structure(pdb_string: str) -> list[dict[str, Any]]:
    """Convert a PDB string to ProteinMPNN's pdb_dict_list format."""
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import parse_PDB

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pdb", delete=False
    ) as tmp:
        tmp.write(pdb_string)
        pdb_path = tmp.name

    try:
        pdb_dict_list = parse_PDB(pdb_path)
        return pdb_dict_list
    finally:
        Path(pdb_path).unlink(missing_ok=True)


def _featurize(
    pdb_dict_list: list[dict[str, Any]],
    device: torch.device,
    constraints: ProteinMPNNConstraints | None = None,
) -> dict[str, Any]:
    """Featurize parsed PDB data into tensors for ProteinMPNN."""
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import tied_featurize

    # Build constraint dicts
    chain_dict = None
    fixed_position_dict = None
    omit_AA_dict = None
    tied_positions_dict = None
    bias_by_res_dict = None

    if constraints is not None:
        if constraints.designable_positions or constraints.fixed_positions:
            fixed_position_dict = {}
            if constraints.fixed_positions:
                for pos in constraints.fixed_positions:
                    fixed_position_dict.setdefault("A", []).append(pos)
            if constraints.designable_positions:
                # Mark non-designable positions as fixed
                pass  # designable = not fixed; fixed_positions handles it

        if constraints.omit_amino_acids:
            omit_AA_dict = {"A": [c for c in constraints.omit_amino_acids]}

        if constraints.tied_positions:
            tied_positions_dict = {
                "A": [tuple(pair) for pair in constraints.tied_positions]
            }

        if constraints.bias_by_res:
            bias_by_res_dict = {"A": constraints.bias_by_res}

    batch = tied_featurize(
        pdb_dict_list,
        device,
        chain_dict,
        fixed_position_dict,
        omit_AA_dict,
        tied_positions_dict,
        None,  # pssm_dict
        bias_by_res_dict,
    )
    return batch


def _run_design(
    model: Any,
    batch: dict[str, Any],
    num_sequences: int,
    temperature: float,
    device: torch.device,
) -> list[ProteinSequence]:
    """Run ProteinMPNN design and return list of ProteinSequence objects."""
    mpnn_path = str(_PROTEINMPNN_DIR)
    if mpnn_path not in sys.path:
        sys.path.insert(0, mpnn_path)

    from protein_mpnn_utils import _scores, _S_to_seq

    alphabet = "ACDEFGHIKLMNPQRSTVWYX"
    omit_AAs_np = np.array([False] * 21, dtype=np.float32)
    bias_AAs_np = np.zeros(21, dtype=np.float32)

    X = batch["X"]
    S = batch["S"]
    mask = batch["mask"]
    chain_M = batch["chain_M"]
    chain_encoding_all = batch["chain_encoding_all"]
    residue_idx = batch["residue_idx"]
    chain_M_pos = batch["chain_M_pos"]
    tied_pos = batch.get("tied_pos", None) if hasattr(batch, "get") else None

    sequences: list[ProteinSequence] = []

    for _ in range(num_sequences):
        randn = torch.randn(chain_M.shape, device=device)
        randn_2 = torch.randn(chain_M.shape, device=device)

        # tied_pos_list format: list of lists of positions
        tied_pos_list = None
        if tied_pos is not None:
            tied_pos_list = [[int(p[0]), int(p[1])] for p in tied_pos]

        sample_out = model.tied_sample(
            X, randn, S, chain_M, chain_encoding_all, residue_idx,
            mask=mask, temperature=temperature,
            omit_AAs_np=omit_AAs_np, bias_AAs_np=bias_AAs_np,
            chain_M_pos=chain_M_pos, tied_pos=tied_pos_list,
            tied_beta=torch.ones(X.shape[1], device=device),
        )

        # Decode sequences
        S_sample = sample_out["S"]
        seq_str = _S_to_seq(S_sample, mask)[0]
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
    score = float(_scores(seq_encoded, log_probs, mask_for_loss).cpu().numpy()[0])
    return score


def design_sequences(
    pdb_string: str,
    model_name: str = "v_48_020",
    num_sequences: int = 1,
    temperature: float = 0.1,
    constraints: ProteinMPNNConstraints | None = None,
) -> tuple[list[ProteinSequence], float | None]:
    """Run ProteinMPNN design and return generated sequences with score.

    Returns (sequences, average_score).
    """
    model, device = _load_model(model_name)
    pdb_dict_list = _parse_structure(pdb_string)

    if len(pdb_dict_list) == 0:
        raise ValueError("No valid chains found in PDB structure")

    batch = _featurize(pdb_dict_list, device, constraints)
    sequences = _run_design(model, batch, num_sequences, temperature, device)

    # Compute scores for native-like comparison using first PDB dict's sequence
    native_seq = pdb_dict_list[0].get("seq", "")
    avg_score = None
    try:
        native_score = _compute_score(model, batch, native_seq, device)
        avg_score = native_score
    except Exception:
        pass

    return sequences, avg_score


def score_sequence(
    pdb_string: str,
    sequence: str,
    model_name: str = "v_48_020",
) -> float:
    """Score how well a sequence fits a structure."""
    model, device = _load_model(model_name)
    pdb_dict_list = _parse_structure(pdb_string)

    if len(pdb_dict_list) == 0:
        raise ValueError("No valid chains found in PDB structure")

    batch = _featurize(pdb_dict_list, device)
    return _compute_score(model, batch, sequence, device)
