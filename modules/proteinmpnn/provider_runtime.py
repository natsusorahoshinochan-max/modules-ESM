"""Pinned ProteinMPNN upstream runtime engine."""

from __future__ import annotations

import importlib.util
import tempfile
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from datatypes.sequence import ProteinSequence

from . import provider_request as _provider_request
from .assets import _checkpoint_path
from .provider_request import (
    _ALPHABET_DICT,
    ProteinMPNNDesignRequest,
)


@lru_cache(maxsize=None)
def _load_provider_module(provider_root: Path) -> ModuleType:
    """Load the external provider from one already-validated checkout."""
    provider_file = provider_root / "protein_mpnn_utils.py"
    spec = importlib.util.spec_from_file_location(
        "_protein_workbench_protein_mpnn_utils",
        provider_file,
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(
            f"Unable to load ProteinMPNN provider module from {provider_file}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider_module(provider_root: Path) -> ModuleType:
    return _load_provider_module(provider_root)


def load_proteinmpnn_checkpoint(path: str | Path) -> dict[str, Any]:
    """Load a validated checkpoint through PyTorch's data-only loader."""
    import torch

    return torch.load(str(path), map_location="cpu", weights_only=True)


def _load_model(
    model_name: str,
    backbone_noise: float,
    provider_root: Path,
) -> Any:
    """Load a ProteinMPNN model from checkpoint."""
    import torch

    MPNNModel = _provider_module(provider_root).ProteinMPNN

    checkpoint_path = _checkpoint_path(provider_root)
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
    checkpoint = load_proteinmpnn_checkpoint(checkpoint_path)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()
    return model, device


def _parse_structure(
    pdb_string: str,
    *,
    temp_dir: Path,
    provider_root: Path,
) -> list[dict[str, Any]]:
    """Convert a PDB string to ProteinMPNN's pdb_dict_list format."""
    parse_PDB = _provider_module(provider_root).parse_PDB

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".pdb",
        delete=False,
        dir=temp_dir,
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
    provider_root: Path,
) -> dict[str, Any]:
    """Featurize parsed PDB data into tensors for ProteinMPNN.

    Converts tied_featurize's tuple output to a dict keyed by field name.
    """
    tied_featurize = _provider_module(provider_root).tied_featurize

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
    import numpy as np
    import torch

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
    tied_position_batches = batch["tied_pos_list_of_lists_list"]

    designable_without_backbone = (
        (chain_M > 0) & (chain_M_pos > 0) & (mask <= 0)
    )
    if bool(designable_without_backbone.any().item()):
        provider_positions = [
            int(position) + 1
            for position in torch.nonzero(
                designable_without_backbone[0], as_tuple=False
            ).flatten().tolist()
        ]
        raise RuntimeError(
            "ProteinMPNN cannot design provider positions without complete "
            "backbone coordinates: "
            + ", ".join(str(position) for position in provider_positions)
        )

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

        bias_by_res = batch["bias_by_res_all"]

        sample_out = model.tied_sample(
            X, randn, S, chain_M, chain_encoding_all, residue_idx,
            mask=mask, temperature=temperature,
            omit_AAs_np=omit_AAs_np, bias_AAs_np=bias_AAs_np,
            chain_M_pos=chain_M_pos, tied_pos=tied_pos_list,
            tied_beta=torch.ones(X.shape[1], device=device),
            bias_by_res=bias_by_res,
        )

        S_sample = sample_out["S"]
        target_length = int(batch["lengths"][0])
        sampled_indices = S_sample[0, :target_length].detach().cpu().tolist()
        seq_str = "".join(alphabet[index] for index in sampled_indices)
        sequences.append(ProteinSequence(sequence=seq_str))

    return sequences


def _compute_score(
    model: Any,
    batch: dict[str, Any],
    sequence: str,
    device: torch.device,
    provider_root: Path,
) -> float:
    """Score a sequence against a structure using ProteinMPNN."""
    import torch

    _scores = _provider_module(provider_root)._scores

    X = batch["X"]
    mask = batch["mask"]
    chain_M = batch["chain_M"]
    chain_encoding_all = batch["chain_encoding_all"]
    residue_idx = batch["residue_idx"]

    seq_encoded = torch.zeros((1, X.shape[1]), dtype=torch.int64, device=device)
    seq_encoded[0, : len(sequence)] = torch.tensor(
        [_ALPHABET_DICT[amino_acid] for amino_acid in sequence],
        dtype=torch.int64,
        device=device,
    )

    randn = torch.randn(chain_M.shape, device=device)

    # Forward pass
    log_probs = model.forward(
        X, seq_encoded, mask, chain_M, residue_idx, chain_encoding_all, randn
    )
    chain_M_pos = batch["chain_M_pos"]
    mask_for_loss = mask * chain_M * chain_M_pos
    score = float(_scores(seq_encoded, log_probs, mask_for_loss).detach().cpu().numpy()[0])
    return score


class _LocalProteinMPNNProvider:
    def __init__(
        self,
        *,
        provider_root: Path,
        temp_dir: Path,
        model_cache: dict[
            tuple[str, float, Path],
            tuple[Any, Any],
        ],
    ) -> None:
        self._temp_dir = temp_dir
        self._provider_root = provider_root
        self._model_cache = model_cache

    def _resident_model(
        self,
        model_name: str,
        backbone_noise: float,
    ) -> tuple[Any, Any]:
        key = (model_name, backbone_noise, self._provider_root)
        resident = self._model_cache.get(key)
        if resident is None:
            self._model_cache.clear()
            resident = _load_model(
                model_name,
                backbone_noise,
                self._provider_root,
            )
            self._model_cache[key] = resident
        return resident

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        return _parse_structure(
            pdb_string,
            temp_dir=self._temp_dir,
            provider_root=self._provider_root,
        )

    def design(
        self, request: ProteinMPNNDesignRequest
    ) -> list[ProteinSequence]:
        import torch

        with torch.random.fork_rng():
            model, device = self._resident_model(
                request.model_name,
                request.backbone_noise,
            )
            torch.manual_seed(request.seed)
            batch = _featurize(
                request,
                device,
                self._provider_root,
            )
            if request.reference_sequences is not None:
                offset = 0
                for chain in batch["letter_list_list"][0]:
                    chain_sequence = request.reference_sequences[chain]
                    encoded = torch.tensor(
                        [
                            _ALPHABET_DICT[amino_acid]
                            for amino_acid in chain_sequence
                        ],
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
        return sequences

    def score(
        self,
        request: ProteinMPNNDesignRequest,
        sequence: ProteinSequence,
    ) -> float:
        import torch

        with torch.random.fork_rng():
            model, device = self._resident_model(
                request.model_name,
                request.backbone_noise,
            )
            torch.manual_seed(request.seed)
            batch = _featurize(
                request,
                device,
                self._provider_root,
            )
            return _compute_score(
                model,
                batch,
                _provider_request._sequence_in_provider_chain_order(
                    sequence.sequence,
                    request,
                ),
                device,
                self._provider_root,
            )
