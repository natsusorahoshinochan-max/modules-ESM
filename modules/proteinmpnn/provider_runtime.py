"""ProteinMPNN provider runtime owned by the cohesive package."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from modules.provider_contract import (
    PROTEINMPNN_REVISION,
)
from datatypes import (
    ProteinMPNNConstraints,
    ProteinSequence,
    ResidueLayout,
    validate_proteinmpnn_constraints,
)

_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"
_ALPHABET_DICT = dict(zip(_ALPHABET, range(21)))
_SUPPORTED_MODELS = {"v_48_002", "v_48_010", "v_48_020", "v_48_030"}
_LOCAL_PROVIDER_IDENTITY = "local-proteinmpnn"
_PROTEINMPNN_COMMIT = PROTEINMPNN_REVISION
_CHECKPOINT_SHA256 = {
    "vanilla_model_weights/v_48_002.pt": (
        "925f2ca1007bf9b02e0e7f420ff00eb91f50fcc2722f64b42e644ae95adaa131"
    ),
    "vanilla_model_weights/v_48_010.pt": (
        "db866fae956a28661f926053d630610c55e9fc4bc03922f2aeeb98a37435ccce"
    ),
    "vanilla_model_weights/v_48_020.pt": (
        "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd"
    ),
    "vanilla_model_weights/v_48_030.pt": (
        "c34b7bfb38418ea30989fda3314f4781ac4e3920f9825731cf555f1fed44ac66"
    ),
    "soluble_model_weights/v_48_002.pt": (
        "0877f840978fe770be6fcec025784d8f50c438571db3260c05e41aa207a7c448"
    ),
    "soluble_model_weights/v_48_010.pt": (
        "79562f7444f72c84595a1c96010713864865a616f4f3967633493041e169fa6e"
    ),
    "soluble_model_weights/v_48_020.pt": (
        "7af52d090172c230c7f0e9d21e02203f6b3a38b16db58d3c7a3960e0a9a6e31a"
    ),
    "soluble_model_weights/v_48_030.pt": (
        "1dd63f1e9fc68a133cc9ef859edf43b489e5ac581cb5624e0b9ec848ff062421"
    ),
}


def _run_provider_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise FileNotFoundError(
            f"ProteinMPNN provider root is not a usable locked Git checkout: {root}"
        ) from exc
    return completed.stdout.strip()


def _verify_provider_checkout(root: Path, expected_commit: str) -> None:
    provider_file = root / "protein_mpnn_utils.py"
    if provider_file.is_symlink() or not provider_file.is_file():
        raise FileNotFoundError(
            "Configured ProteinMPNN provider root must contain a regular, "
            "non-symlink protein_mpnn_utils.py"
        )
    repository_root = Path(
        _run_provider_git(root, "rev-parse", "--show-toplevel")
    ).resolve()
    if repository_root != root:
        raise RuntimeError("ProteinMPNN provider root must be the Git checkout root")
    commit = _run_provider_git(root, "rev-parse", "HEAD")
    if commit != expected_commit:
        raise RuntimeError(
            f"ProteinMPNN checkout commit {commit} does not match "
            f"locked commit {expected_commit}"
        )
    if _run_provider_git(root, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("ProteinMPNN checkout has modified tracked files")


def _proteinmpnn_dir() -> Path:
    """Resolve the explicitly configured, externally managed provider checkout."""
    configured = os.environ.get("PROTEIN_WORKBENCH_PROTEINMPNN_ROOT")
    if not configured:
        raise FileNotFoundError(
            "ProteinMPNN provider root is not configured; set "
            "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT to the locked external checkout"
        )
    configured_root = Path(configured).expanduser()
    if configured_root.is_symlink():
        raise FileNotFoundError(
            "Configured ProteinMPNN provider root must not be a symlink"
        )
    return validate_proteinmpnn_checkout(configured_root, _PROTEINMPNN_COMMIT)


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


def _provider_module(provider_root: Path | None = None) -> ModuleType:
    return _load_provider_module(provider_root or _proteinmpnn_dir())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ProteinMPNNReadiness:
    ready: bool
    provider_root: Path | None = None
    checkpoint_path: Path | None = None
    detail: str | None = None


def validate_proteinmpnn_checkout(root: Path, expected_commit: str) -> Path:
    """Validate one external checkout against an explicit source identity."""
    if root.expanduser().is_symlink():
        raise FileNotFoundError(
            "Configured ProteinMPNN provider root must not be a symlink"
        )
    resolved_root = root.expanduser().resolve()
    _verify_provider_checkout(resolved_root, expected_commit)
    return resolved_root


def validate_proteinmpnn_checkpoint(
    path: Path,
    expected_sha256: str,
) -> Path:
    """Validate one checkpoint as a regular file with an exact digest."""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            f"ProteinMPNN checkpoint must be a regular non-symlink file: {path}"
        )
    digest = _sha256_file(path)
    if digest != expected_sha256:
        raise RuntimeError(
            f"ProteinMPNN checkpoint SHA-256 mismatch for {path.name}: "
            f"expected {expected_sha256}, got {digest}"
        )
    return path


def load_proteinmpnn_checkpoint(path: str | Path) -> dict[str, Any]:
    """Load a validated checkpoint through PyTorch's data-only loader."""
    import torch

    return torch.load(str(path), map_location="cpu", weights_only=True)


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
    residue_identity_mapping: tuple[tuple[str, str, int], ...]
    structure_chain_order: tuple[str, ...]
    provider_chain_order: tuple[str, ...]
    chain_dict: dict[str, tuple[list[str], list[str]]]
    fixed_position_dict: dict[str, dict[str, list[int]]] | None
    tied_positions_dict: dict[str, list[dict[str, list[int]]]] | None
    bias_by_res_dict: dict[str, dict[str, list[list[float]]]] | None
    omit_amino_acids: list[str]
    reference_sequences: dict[str, str] | None


class ProteinMPNNProvider(Protocol):
    """External provider boundary used by the adapter."""

    provider_identity: str

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        """Parse a PDB string into ProteinMPNN's structure representation."""

    def design(
        self, request: ProteinMPNNDesignRequest
    ) -> tuple[list[ProteinSequence], list[float]]:
        """Execute one already-validated ProteinMPNN request."""

    def score(
        self,
        request: ProteinMPNNDesignRequest,
        sequence: ProteinSequence,
    ) -> float:
        """Score one exact sequence on one already-validated target."""


def _get_checkpoint_path(
    model_name: str,
    provider_root: Path | None = None,
) -> str:
    """Get the path to a ProteinMPNN model checkpoint."""
    resolved_root = provider_root or _proteinmpnn_dir()
    candidate_names = [f"vanilla_model_weights/{model_name}.pt"]
    for candidate_name in candidate_names:
        path = resolved_root / candidate_name
        if not path.is_file():
            continue
        validated = validate_proteinmpnn_checkpoint(
            path,
            _CHECKPOINT_SHA256[candidate_name],
        )
        return str(validated)
    raise FileNotFoundError(
        f"ProteinMPNN checkpoint not found for {model_name}. "
        "Looked in vanilla_model_weights/"
    )

def check_proteinmpnn_readiness(
    model_name: str = "v_48_020",
    provider_root: Path | None = None,
) -> ProteinMPNNReadiness:
    """Report whether the locked provider and selected checkpoint are usable."""
    try:
        resolved_root = (
            _proteinmpnn_dir()
            if provider_root is None
            else validate_proteinmpnn_checkout(
                provider_root,
                _PROTEINMPNN_COMMIT,
            )
        )
        checkpoint_path = Path(
            _get_checkpoint_path(model_name, resolved_root)
        )
    except (FileNotFoundError, RuntimeError) as exc:
        return ProteinMPNNReadiness(ready=False, detail=str(exc))
    return ProteinMPNNReadiness(
        ready=True,
        provider_root=resolved_root,
        checkpoint_path=checkpoint_path,
    )


def _load_model(
    model_name: str = "v_48_020",
    backbone_noise: float = 0.0,
    provider_root: Path | None = None,
) -> Any:
    """Load a ProteinMPNN model from checkpoint."""
    import torch

    MPNNModel = _provider_module(provider_root).ProteinMPNN

    checkpoint_path = _get_checkpoint_path(model_name, provider_root)
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
    temp_dir: str | Path | None = None,
    provider_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Convert a PDB string to ProteinMPNN's pdb_dict_list format."""
    parse_PDB = _provider_module(provider_root).parse_PDB

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
    provider_root: Path | None = None,
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
    tied_position_batches = batch.get("tied_pos_list_of_lists_list")

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

        S_sample = sample_out["S"]
        target_length = int(batch["lengths"][0])
        if S_sample.shape[0] != 1 or S_sample.shape[1] < target_length:
            raise RuntimeError(
                "ProteinMPNN sampled tensor does not match the parsed target layout"
            )
        sampled_indices = S_sample[0, :target_length].detach().cpu().tolist()
        if any(
            not isinstance(index, int) or not 0 <= index < len(alphabet)
            for index in sampled_indices
        ):
            raise RuntimeError(
                "ProteinMPNN sampled tensor contains an invalid amino-acid index"
            )
        seq_str = "".join(alphabet[index] for index in sampled_indices)
        sequences.append(ProteinSequence(sequence=seq_str))

    return sequences


def _compute_score(
    model: Any,
    batch: dict[str, Any],
    sequence: str,
    device: torch.device,
    provider_root: Path | None = None,
) -> float:
    """Score a sequence against a structure using ProteinMPNN."""
    import torch

    _scores = _provider_module(provider_root)._scores

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


def _validate_generated_sequences(
    sequences: list[ProteinSequence],
    *,
    expected_count: int,
    target_length: int,
) -> None:
    if len(sequences) != expected_count:
        raise RuntimeError(
            "ProteinMPNN provider returned "
            f"{len(sequences)} sequences; expected {expected_count}"
        )
    for sample_index, sequence in enumerate(sequences):
        if not isinstance(sequence, ProteinSequence):
            raise RuntimeError(
                f"ProteinMPNN sample {sample_index} is not a ProteinSequence"
            )
        if len(sequence.sequence) != target_length:
            raise RuntimeError(
                f"ProteinMPNN sample {sample_index} sequence length "
                f"{len(sequence.sequence)} does not match target length "
                f"{target_length}"
            )


class _LocalProteinMPNNProvider:
    provider_identity = _LOCAL_PROVIDER_IDENTITY

    def __init__(
        self,
        temp_dir: str | Path | None = None,
        provider_root: Path | None = None,
    ) -> None:
        self._temp_dir = temp_dir
        self._provider_root = provider_root

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        return _parse_structure(
            pdb_string,
            temp_dir=self._temp_dir,
            provider_root=self._provider_root,
        )

    def design(
        self, request: ProteinMPNNDesignRequest
    ) -> tuple[list[ProteinSequence], list[float]]:
        import torch

        with torch.random.fork_rng():
            torch.manual_seed(request.seed)
            model, device = _load_model(
                request.model_name,
                request.backbone_noise,
                self._provider_root,
            )
            batch = _featurize(
                request,
                device,
                self._provider_root,
            )
            if request.reference_sequences is not None:
                offset = 0
                for chain in batch["letter_list_list"][0]:
                    chain_sequence = request.reference_sequences[str(chain)]
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
            _validate_generated_sequences(
                sequences,
                expected_count=request.num_sequences,
                target_length=request.target_length,
            )
            scores = [
                _compute_score(
                    model,
                    batch,
                    sequence.sequence,
                    device,
                    self._provider_root,
                )
                for sequence in sequences
            ]
        return sequences, scores

    def score(
        self,
        request: ProteinMPNNDesignRequest,
        sequence: ProteinSequence,
    ) -> float:
        import torch

        with torch.random.fork_rng():
            torch.manual_seed(request.seed)
            model, device = _load_model(
                request.model_name,
                request.backbone_noise,
                self._provider_root,
            )
            batch = _featurize(
                request,
                device,
                self._provider_root,
            )
            return float(
                _compute_score(
                    model,
                    batch,
                    sequence.sequence,
                    device,
                    self._provider_root,
                )
            )


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
    seed: int = 42,
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
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")


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


def _layout_from_chains(
    chains: list[tuple[str, str]],
) -> ResidueLayout:
    chain_order = [chain for chain, _ in chains]
    residue_ids = [
        f"{chain}:{position}"
        for chain, sequence in chains
        for position in range(1, len(sequence) + 1)
    ]
    return ResidueLayout(
        chain_id=",".join(chain_order),
        length=len(residue_ids),
        residue_ids=residue_ids,
    )


def _residue_identity_mapping(
    layout: ResidueLayout,
    chains: list[tuple[str, str]],
) -> tuple[tuple[str, str, int], ...]:
    residue_ids = list(layout.residue_ids or ())
    expected_length = sum(len(sequence) for _, sequence in chains)
    if len(residue_ids) != expected_length:
        raise ValueError(
            "constraint layout cardinality does not match the parsed "
            "structure cardinality"
        )
    if layout.chain_id != ",".join(chain for chain, _ in chains):
        raise ValueError(
            "constraint layout chain order does not match the parsed structure"
        )
    mapping: list[tuple[str, str, int]] = []
    offset = 0
    for chain, sequence in chains:
        for provider_position in range(1, len(sequence) + 1):
            residue_id = residue_ids[offset]
            residue_chain, separator, _ = residue_id.partition(":")
            if separator != ":" or residue_chain != chain:
                raise ValueError(
                    f"constraint residue identity {residue_id} does not "
                    f"correspond to parsed chain {chain}"
                )
            mapping.append((residue_id, chain, provider_position))
            offset += 1
    if len({residue_id for residue_id, _, _ in mapping}) != len(mapping):
        raise ValueError("constraint layout contains duplicate residue identities")
    return tuple(mapping)


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
        requested_designed_set = set(requested_designed)
        designed_chains = [
            chain for chain in chain_ids if chain in requested_designed_set
        ]
        fixed_chains = [
            chain for chain in chain_ids if chain not in requested_designed_set
        ]
        if requested_fixed and set(requested_fixed) != set(fixed_chains):
            raise ValueError(
                "designed_chains and fixed_chains must partition all structure chains"
            )
        return designed_chains, fixed_chains
    elif requested_fixed:
        requested_fixed_set = set(requested_fixed)
        designed_chains = [
            chain for chain in chain_ids if chain not in requested_fixed_set
        ]
        fixed_chains = [
            chain for chain in chain_ids if chain in requested_fixed_set
        ]
        return designed_chains, fixed_chains
    return chain_ids, []


def _fixed_position_payload(
    name: str,
    chains: list[tuple[str, str]],
    designed_chains: list[str],
    constraints: ProteinMPNNConstraints,
) -> dict[str, dict[str, list[int]]] | None:
    residue_ids = list(constraints.layout.residue_ids or ())
    position_by_id = {
        residue_id: position
        for position, residue_id in enumerate(residue_ids)
    }
    fixed_positions = {
        position_by_id[residue_id]
        for residue_id in constraints.fixed_residue_ids or ()
    }
    if constraints.designable_residue_ids:
        designable_positions = {
            position_by_id[residue_id]
            for residue_id in constraints.designable_residue_ids
        }
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
    if not constraints.tied_residue_groups:
        return None
    position_by_id = {
        residue_id: position
        for position, residue_id in enumerate(
            constraints.layout.residue_ids or ()
        )
    }
    tied_groups: list[dict[str, list[int]]] = []
    for group_index, group in enumerate(constraints.tied_residue_groups):
        chain_positions: dict[str, list[int]] = {}
        for residue_id in group:
            position = position_by_id[residue_id]
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
    if not constraints.bias_by_residue:
        return None
    position_by_id = {
        residue_id: position
        for position, residue_id in enumerate(
            constraints.layout.residue_ids or ()
        )
    }
    bias_by_chain = {
        chain: [[0.0] * len(_ALPHABET) for _ in sequence]
        for chain, sequence in chains
    }
    for residue_id, amino_acid_biases in (
        constraints.bias_by_residue.items()
    ):
        position = position_by_id[residue_id]
        chain, local_position = _position_to_chain(position, chains)
        if chain not in designed_chains:
            raise ValueError(
                f"bias_by_residue {residue_id} belongs to fixed chain {chain}"
            )
        fixed_positions = (fixed_position_dict or {}).get(name, {}).get(chain, [])
        if local_position + 1 in fixed_positions:
            raise ValueError(
                f"bias_by_residue {residue_id} is fixed by the effective "
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
    seed: int,
    constraints: ProteinMPNNConstraints | None,
    reference_sequence: str | None,
) -> ProteinMPNNDesignRequest:
    validate_design_parameters(
        model_name, num_sequences, temperature, backbone_noise, seed
    )
    name, chains = _structure_target(pdb_dict_list)
    provider_layout = _layout_from_chains(chains)
    selected_constraints = (
        ProteinMPNNConstraints(layout=provider_layout)
        if constraints is None
        else constraints
    )
    validate_proteinmpnn_constraints(selected_constraints)
    target_layout = selected_constraints.layout
    identity_mapping = _residue_identity_mapping(target_layout, chains)
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
        seed=seed,
        target_length=sum(len(sequence) for _, sequence in chains),
        target_layout=target_layout,
        residue_identity_mapping=identity_mapping,
        structure_chain_order=tuple(chain for chain, _ in chains),
        provider_chain_order=tuple((*designed_chains, *fixed_chains)),
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
