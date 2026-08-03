"""SimpleFold adapter: wraps ml-simplefold for sequence folding and structure evaluation.

Fold: sequence -> structures + pLDDT (100M model, num_steps capped at 50).
Evaluate: structure -> pLDDT scores (larger model, no re-folding).
"""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import subprocess
import sys
import threading
from argparse import Namespace
from copy import deepcopy
from functools import partial, wraps
from pathlib import Path
from typing import Any, Callable

import torch

from datatypes import (
    ProteinSequence,
    ProteinStructure,
)
from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_AUXILIARY_ARTIFACTS,
    SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
)
from .simplefold_contract import SIMPLEFOLD_FOLDING_ARTIFACTS


_SIMPLEFOLD_PROCESS_LOCK = threading.RLock()


def _setup_simplefold_imports() -> str:
    """Enter the provider package directory and return the prior directory."""
    import simplefold
    old_cwd = os.getcwd()
    sf_dir = os.path.abspath(os.path.dirname(simplefold.__file__))
    if sf_dir not in sys.path:
        sys.path.insert(0, sf_dir)
    os.chdir(sf_dir)
    return old_cwd

def _get_artifact_dir(project_dir: str) -> Path:
    """Get or create artifact directory for model checkpoints and outputs."""
    if not project_dir:
        raise ValueError("SimpleFold staging directory is required")
    base = Path(project_dir)
    artifacts = base / "simplefold_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def _sha256_file(
    path: Path,
    *,
    expected_bytes: int | None = None,
) -> str:
    digest = hashlib.sha256()
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise RuntimeError(
            f"SimpleFold artifact byte count mismatch: {path.name}"
        )
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stage_simplefold_model_dir(
    working_artifacts: Path,
    model_root: Path,
    *,
    required_artifacts: tuple[str, ...] | None = None,
) -> Path:
    """Stage provider objects already admitted by Binding readiness."""
    model_dir = model_root.expanduser()
    required_names = set(
        required_artifacts
        if required_artifacts is not None
        else (
            *SIMPLEFOLD_ARTIFACT_IDENTITIES,
            *SIMPLEFOLD_AUXILIARY_ARTIFACTS,
        )
    )
    working_artifacts.mkdir(parents=True, mode=0o700, exist_ok=True)
    staged = working_artifacts / "verified_provider"
    staged.mkdir(mode=0o700)
    for name in sorted(required_names):
        _copy_file(model_dir / name, staged / name)
    return staged


def _copy_file(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def _run_simplefold_esm2_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise RuntimeError(
            "SimpleFold ESM2 source is not a usable locked Git checkout"
        ) from exc
    return completed.stdout.strip()


def validated_simplefold_esm2_root(
    source_root: Path,
) -> Path:
    """Resolve the exact local ESM2 checkout used by SimpleFold."""
    source_root = source_root.expanduser()
    hubconf = source_root / "hubconf.py"
    if not source_root.is_dir() or not hubconf.is_file():
        raise FileNotFoundError(
            "SimpleFold ESM2 source root must be a Git checkout"
        )
    checkout = Path(
        _run_simplefold_esm2_git(
            source_root,
            "rev-parse",
            "--show-toplevel",
        )
    ).resolve()
    if checkout != source_root.resolve():
        raise RuntimeError(
            "SimpleFold ESM2 source root must be the Git checkout root"
        )
    if (
        _run_simplefold_esm2_git(source_root, "rev-parse", "HEAD")
        != SIMPLEFOLD_ESM2_REVISION
    ):
        raise RuntimeError(
            "SimpleFold ESM2 checkout does not match the locked revision"
        )
    if _run_simplefold_esm2_git(
        source_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
    ):
        raise RuntimeError("SimpleFold ESM2 checkout is not clean")
    runtime_files = _simplefold_esm2_runtime_files(source_root)
    if (
        _simplefold_esm2_source_tree_sha256(runtime_files)
        != SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256
    ):
        raise RuntimeError(
            "SimpleFold ESM2 runtime source does not match the reviewed tree"
        )
    return source_root


def _simplefold_esm2_runtime_files(
    source_root: Path,
) -> list[tuple[str, Path]]:
    tracked = sorted({
        relative
        for relative in _run_simplefold_esm2_git(
            source_root,
            "ls-files",
            "--",
            "hubconf.py",
            "esm",
        ).splitlines()
        if relative
    })
    return [(relative, source_root / relative) for relative in tracked]


def _simplefold_esm2_source_tree_sha256(
    runtime_files: list[tuple[str, Path]],
) -> str:
    digest = hashlib.sha256()
    for relative, path in sorted(runtime_files):
        digest.update(relative.encode() + b"\0")
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _stage_simplefold_esm2_source(
    source_root: Path,
    working_artifacts: Path,
) -> Path:
    runtime_files = _simplefold_esm2_runtime_files(source_root)
    working_artifacts.mkdir(parents=True, mode=0o700, exist_ok=True)
    staged_root = working_artifacts / "verified_esm2_source"
    staged_root.mkdir(mode=0o700)
    for relative, source in runtime_files:
        destination = staged_root / relative
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        _copy_file(source, destination)
    return staged_root


def stage_simplefold_esm2_model_dir(
    working_artifacts: Path,
    model_root: Path,
) -> Path:
    """Stage ESM2 weights already admitted by Binding readiness."""
    model_root = model_root.expanduser()
    working_artifacts.mkdir(parents=True, mode=0o700, exist_ok=True)
    staged = working_artifacts / "verified_esm2_models"
    staged.mkdir(mode=0o700)
    for name in sorted(SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES):
        _copy_file(model_root / name, staged / name)
    return staged


def stage_simplefold_esm2_runtime(
    working_artifacts: Path,
    source_root: Path,
    model_root: Path,
) -> tuple[Path, Path]:
    """Stage the ESM2 source and weights admitted by Binding readiness."""
    staged_source = _stage_simplefold_esm2_source(
        source_root,
        working_artifacts,
    )
    staged_models = stage_simplefold_esm2_model_dir(
        working_artifacts,
        model_root,
    )
    return staged_source, staged_models


def _load_reviewed_simplefold_esm2(
    source_root: Path,
    model_path: Path,
) -> tuple[Any, Any]:
    """Load Facebook ESM2 locally after replacing Biohub's `esm` namespace."""
    prior_esm_modules = {
        module_name: module
        for module_name, module in tuple(sys.modules.items())
        if module_name == "esm" or module_name.startswith("esm.")
    }
    for module_name in prior_esm_modules:
        sys.modules.pop(module_name, None)
    source_entry = str(source_root)
    sys.path.insert(0, source_entry)
    importlib.invalidate_caches()
    try:
        pretrained = importlib.import_module("esm.pretrained")
        regression_path = model_path.with_name(
            f"{model_path.stem}-contact-regression.pt"
        )
        with torch.serialization.safe_globals([Namespace]):
            model_data = torch.load(
                str(model_path),
                map_location="cpu",
                weights_only=True,
            )
            regression_data = torch.load(
                str(regression_path),
                map_location="cpu",
                weights_only=True,
            )
        return pretrained.load_model_and_alphabet_core(
            model_path.stem,
            model_data,
            regression_data,
        )[:2]
    finally:
        if source_entry in sys.path:
            sys.path.remove(source_entry)
        for module_name in tuple(sys.modules):
            if module_name == "esm" or module_name.startswith("esm."):
                sys.modules.pop(module_name, None)
        sys.modules.update(prior_esm_modules)


def _bind_simplefold_esm2_source(
    esm_registry: dict[str, Any],
    source_root: Path,
    model_dir: Path,
) -> None:
    """Replace the mutable upstream loader with staged source and weights."""
    esm_registry["esm2_3B"] = partial(
        _load_reviewed_simplefold_esm2,
        source_root,
        model_dir / "esm2_t36_3B_UR50D.pt",
    )


def _prepare_simplefold_cache(model_dir: Path, cache: Path) -> None:
    """Populate a fresh cache from verified objects; never invoke a downloader."""
    for name in SIMPLEFOLD_AUXILIARY_ARTIFACTS:
        source = model_dir / name
        if source.is_file():
            _copy_file(source, cache / name)


def _restore_process_cwd(function: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize and restore the provider's process-global import state."""
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with _SIMPLEFOLD_PROCESS_LOCK:
            original_cwd = os.getcwd()
            try:
                return function(*args, **kwargs)
            finally:
                os.chdir(original_cwd)

    return wrapped


@_restore_process_cwd
def fold_sequence(
    sequence: ProteinSequence,
    *,
    model_name: str,
    num_steps: int,
    num_samples: int,
    project_dir: str,
    effective_seed: int,
    model_root: Path,
    esm2_source_root: Path,
    esm2_model_root: Path,
    required_device: str,
    record_evidence: bool,
) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
    """Fold a protein sequence using SimpleFold.

    Returns structures plus provider-native per-sample confidence data.

    num_steps is capped at 50 per ADR 0013.
    """
    if model_name != "simplefold_100M":
        raise ValueError("SimpleFold folding requires simplefold_100M")
    num_steps = min(num_steps, 50)
    artifacts = _get_artifact_dir(project_dir)
    model_dir = stage_simplefold_model_dir(
        artifacts,
        model_root,
        required_artifacts=SIMPLEFOLD_FOLDING_ARTIFACTS,
    )
    esm2_source_root, esm2_model_dir = stage_simplefold_esm2_runtime(
        artifacts,
        esm2_source_root,
        esm2_model_root,
    )
    old_cwd = _setup_simplefold_imports()
    from simplefold.wrapper import ModelWrapper, InferenceWrapper
    from simplefold.utils.boltz_utils import (
        process_structure,
        to_pdb as sf_to_pdb,
    )
    from simplefold.utils.fasta_utils import process_fastas
    from simplefold.utils.datamodule_utils import process_one_inference_structure

    runtime_esm_registry = sys.modules["utils.esm_utils"].esm_registry
    _bind_simplefold_esm2_source(
        runtime_esm_registry,
        esm2_source_root,
        esm2_model_dir,
    )

    output_dir = artifacts / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = artifacts / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    # Write sequence to FASTA
    fasta_path = cache / "input.fasta"
    fasta_path.write_text(f">A|Protein\n{sequence.sequence}\n")

    _prepare_simplefold_cache(model_dir, cache)

    # Process FASTA
    process_fastas(
        data=[fasta_path],
        out_dir=output_dir,
        ccd_path=cache / "ccd.pkl",
    )

    # Initialize model
    model_wrapper = ModelWrapper(
        simplefold_model=model_name,
        plddt=True,
        ckpt_dir=str(model_dir),
        backend="torch",
    )
    model = model_wrapper.from_pretrained_folding_model()
    plddt_models = model_wrapper.from_pretrained_plddt_model()
    device = model_wrapper.device
    if str(device) != required_device:
        raise RuntimeError(
            "SimpleFold provider device does not match the Binding"
        )

    # Initialize inference wrapper
    inf_wrapper = InferenceWrapper(
        output_dir=str(output_dir),
        prediction_dir="predictions",
        num_steps=num_steps,
        nsample_per_protein=num_samples,
        tau=0.1,
        device=device,
        backend="torch",
    )

    structures: list[ProteinStructure] = []
    confidence_results: list[dict[str, Any]] = []

    # Process each structure file
    struct_files = list(output_dir.glob("structures/*.npz"))
    if not struct_files:
        raise ValueError("No structure files generated from FASTA processing")

    for struct_file in struct_files:
        record_file = output_dir / "records" / f"{struct_file.stem}.json"

        batch, structure, record = process_one_inference_structure(
            struct_file,
            record_file,
            inf_wrapper.tokenizer,
            inf_wrapper.featurizer,
            inf_wrapper.processor,
            inf_wrapper.esm_model,
            inf_wrapper.esm_dict,
            inf_wrapper.af2_to_esm,
        )

        # Run inference
        if (
            type(effective_seed) is not int
            or not 0 <= effective_seed <= 9_007_199_254_740_991
        ):
            raise ValueError("SimpleFold effective seed is invalid")
        torch_device = torch.device(device)
        fork_devices = (
            [
                torch_device.index
                if torch_device.index is not None
                else torch.cuda.current_device()
            ]
            if torch_device.type == "cuda"
            else []
        )
        with torch.random.fork_rng(devices=fork_devices):
            torch.manual_seed(effective_seed)
            results = inf_wrapper.run_inference(
                batch,
                model,
                plddt_models,
                device,
            )

        sampled_coord = results["sampled_coord"]
        pad_mask = results["pad_mask"]
        plddts = results["plddts"]

        for i in range(num_samples):
            coord_i = sampled_coord[i]
            mask_i = pad_mask[i]
            plddt_i = plddts[i]

            # Process and save structure
            structure_save = process_structure(
                deepcopy(structure),
                coord_i,
                mask_i,
                record,
                backend="torch",
            )

            # Get PDB string
            pdb_string = sf_to_pdb(structure_save, plddts=plddt_i)
            ps = ProteinStructure(pdb_string=pdb_string)
            structures.append(ps)

            # Collect pLDDT scores
            confidence_results.append(
                {
                    "per_residue": plddt_i.detach().cpu().tolist(),
                    "sample_index": i,
                }
            )
        if record_evidence:
            raise RuntimeError(
                "SimpleFold evidence is recorded only by the v2 Run engine"
            )
    os.chdir(old_cwd)
    return structures, confidence_results
