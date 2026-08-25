"""SimpleFold adapter: wraps ml-simplefold for sequence folding and structure evaluation.

Fold: sequence -> structures + pLDDT (100M model, exact normalized num_steps).
Evaluate: structure -> pLDDT scores (larger model, no re-folding).
"""

from __future__ import annotations

import gc
import importlib
import os
import shutil
import sys
import threading
from argparse import Namespace
from copy import deepcopy
from functools import partial, wraps
from pathlib import Path
from typing import Any, Callable

import torch

from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure



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
    shutil.copyfile(model_dir / "ccd.pkl", cache / "ccd.pkl")


def _load_reviewed_torch_module(
    *,
    config_path: Path,
    checkpoint_path: Path,
    device: Any,
) -> Any:
    """Bind a reviewed checkpoint without retaining a copied state dictionary."""
    import hydra
    import omegaconf

    checkpoint = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
        mmap=True,
    )
    module = hydra.utils.instantiate(
        omegaconf.OmegaConf.load(config_path)
    )
    module.load_state_dict(checkpoint, strict=True, assign=True)
    module = module.to(device)
    module.eval()
    return module


def _load_reviewed_folding_models(
    model_dir: Path,
    device: Any,
) -> tuple[Any, dict[str, Any]]:
    """Load the exact folding and pLDDT modules with bounded residency."""
    architecture_root = Path("configs/model/architecture")
    folding_model = _load_reviewed_torch_module(
        config_path=architecture_root / "foldingdit_100M.yaml",
        checkpoint_path=model_dir / "simplefold_100M.ckpt",
        device=device,
    )
    return folding_model, _load_reviewed_plddt_models(model_dir, device)


def _load_reviewed_plddt_models(
    model_dir: Path,
    device: Any,
) -> dict[str, Any]:
    """Load only the exact pLDDT output and latent modules."""
    architecture_root = Path("configs/model/architecture")
    plddt_out_module = _load_reviewed_torch_module(
        config_path=architecture_root / "plddt_module.yaml",
        checkpoint_path=model_dir / "plddt.ckpt",
        device=device,
    )
    plddt_latent_module = _load_reviewed_torch_module(
        config_path=architecture_root / "foldingdit_1.6B.yaml",
        checkpoint_path=model_dir / "simplefold_1.6B.ckpt",
        device=device,
    )
    return {
        "plddt_out_module": plddt_out_module,
        "plddt_latent_module": plddt_latent_module,
    }


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
    num_steps: int,
    num_samples: int,
    staging_directory: Path,
    effective_seed: int,
    staged_model_root: Path,
    staged_esm2_source_root: Path,
    staged_esm2_model_root: Path,
    device: str,
) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
    """Fold a protein sequence using SimpleFold.

    Returns structures plus provider-native per-sample confidence data.

    num_steps is the exact Plan-normalized value admitted by the Binding.
    """
    artifacts = staging_directory / "simplefold_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    model_dir = staged_model_root
    esm2_source_root = staged_esm2_source_root
    esm2_model_dir = staged_esm2_model_root
    _setup_simplefold_imports()
    from simplefold.wrapper import InferenceWrapper
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

    torch_device = torch.device(device)

    # Initialize inference wrapper
    inf_wrapper = InferenceWrapper(
        output_dir=str(output_dir),
        prediction_dir="predictions",
        num_steps=num_steps,
        nsample_per_protein=num_samples,
        tau=0.1,
        device=torch_device,
        backend="torch",
    )

    struct_files = list(output_dir.glob("structures/*.npz"))

    prepared_inputs: list[tuple[Any, Any, Any]] = []
    for struct_file in struct_files:
        record_file = output_dir / "records" / f"{struct_file.stem}.json"
        prepared_inputs.append(
            process_one_inference_structure(
                struct_file,
                record_file,
                inf_wrapper.tokenizer,
                inf_wrapper.featurizer,
                inf_wrapper.processor,
                inf_wrapper.esm_model,
                inf_wrapper.esm_dict,
                inf_wrapper.af2_to_esm,
            )
        )

    # ESM2 is only needed to materialize the detached language-model features.
    # Release its 3B parameters before loading folding and pLDDT weights.
    inf_wrapper.esm_model = None
    inf_wrapper.esm_dict = None
    inf_wrapper.af2_to_esm = None
    gc.collect()

    model, plddt_models = _load_reviewed_folding_models(
        model_dir,
        torch_device,
    )

    structures: list[ProteinStructure] = []
    confidence_results: list[dict[str, Any]] = []

    for batch, structure, record in prepared_inputs:
        # Run inference
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
                torch_device,
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
    return structures, confidence_results
