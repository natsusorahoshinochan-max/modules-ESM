"""SimpleFold adapter: wraps ml-simplefold for sequence folding and structure evaluation.

Fold: sequence -> structures + pLDDT (100M model, exact normalized num_steps).
Evaluate: structure -> pLDDT scores (larger model, no re-folding).
"""

from __future__ import annotations

import gc
import importlib
import os
import sys
import threading
from argparse import Namespace
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial, wraps
from pathlib import Path
from typing import Any, Callable

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
    import torch

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


def _load_reviewed_torch_module(
    *,
    config_path: Path,
    checkpoint_path: Path,
    device: Any,
) -> Any:
    """Bind a reviewed checkpoint without retaining a copied state dictionary."""
    import hydra
    import omegaconf
    import torch

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
def activate_fold_sequence(
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
) -> ActivatedSimpleFoldFolding:
    """Import SimpleFold, load ESM2, and prepare its fixed request."""
    import torch

    artifacts = staging_directory / "simplefold_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    model_dir = staged_model_root
    esm2_source_root = staged_esm2_source_root
    esm2_model_dir = staged_esm2_model_root
    _setup_simplefold_imports()
    provider_directory = Path.cwd()
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

    fasta_path = cache / "input.fasta"
    fasta_path.write_text(f">A|Protein\n{sequence.sequence}\n")
    process_fastas(
        data=[fasta_path],
        out_dir=output_dir,
        ccd_path=model_dir / "ccd.pkl",
    )
    return ActivatedSimpleFoldFolding(
        provider_directory=provider_directory,
        model_directory=model_dir,
        output_directory=output_dir,
        inference_wrapper=inf_wrapper,
        process_one_inference_structure=process_one_inference_structure,
        torch_device=torch_device,
        torch_module=torch,
        effective_seed=effective_seed,
        num_samples=num_samples,
        process_structure=process_structure,
        to_pdb=sf_to_pdb,
    )


@dataclass(slots=True)
class ActivatedSimpleFoldFolding:
    """The two serial scientific engines of one SimpleFold folding call."""

    provider_directory: Path
    model_directory: Path
    output_directory: Path
    inference_wrapper: Any
    process_one_inference_structure: Callable[..., tuple[Any, Any, Any]]
    torch_device: Any
    torch_module: Any
    effective_seed: int
    num_samples: int
    process_structure: Callable[..., Any]
    to_pdb: Callable[..., str]
    prepared_inputs: tuple[tuple[Any, Any, Any], ...] = field(init=False)
    folding_model: Any = field(init=False)
    plddt_models: dict[str, Any] = field(init=False)

    @_restore_process_cwd
    def prepare_inputs(self) -> None:
        """Run the ESM2 feature engine and release its resident model."""
        os.chdir(self.provider_directory)
        try:
            self.prepared_inputs = tuple(
                self.process_one_inference_structure(
                    struct_file,
                    self.output_directory
                    / "records"
                    / f"{struct_file.stem}.json",
                    self.inference_wrapper.tokenizer,
                    self.inference_wrapper.featurizer,
                    self.inference_wrapper.processor,
                    self.inference_wrapper.esm_model,
                    self.inference_wrapper.esm_dict,
                    self.inference_wrapper.af2_to_esm,
                )
                for struct_file in self.output_directory.glob(
                    "structures/*.npz"
                )
            )
        finally:
            self.inference_wrapper.esm_model = None
            self.inference_wrapper.esm_dict = None
            self.inference_wrapper.af2_to_esm = None
            gc.collect()

    @_restore_process_cwd
    def activate_final_models(self) -> None:
        """Load the folding and confidence models after ESM2 is released."""
        os.chdir(self.provider_directory)
        self.folding_model, self.plddt_models = (
            _load_reviewed_folding_models(
                self.model_directory,
                self.torch_device,
            )
        )

    @_restore_process_cwd
    def invoke(
        self,
    ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
        """Enter the already-activated provider's scientific engine once."""
        os.chdir(self.provider_directory)
        structures: list[ProteinStructure] = []
        confidence_results: list[dict[str, Any]] = []

        for batch, structure, record in self.prepared_inputs:
            fork_devices = (
                [
                    self.torch_device.index
                    if self.torch_device.index is not None
                    else self.torch_module.cuda.current_device()
                ]
                if self.torch_device.type == "cuda"
                else []
            )
            with self.torch_module.random.fork_rng(devices=fork_devices):
                self.torch_module.manual_seed(self.effective_seed)
                results = self.inference_wrapper.run_inference(
                    batch,
                    self.folding_model,
                    self.plddt_models,
                    self.torch_device,
                )

            sampled_coord = results["sampled_coord"]
            pad_mask = results["pad_mask"]
            plddts = results["plddts"]

            for sample_index in range(self.num_samples):
                structure_save = self.process_structure(
                    deepcopy(structure),
                    sampled_coord[sample_index],
                    pad_mask[sample_index],
                    record,
                    backend="torch",
                )
                pdb_string = self.to_pdb(
                    structure_save,
                    plddts=plddts[sample_index],
                )
                structures.append(ProteinStructure(pdb_string=pdb_string))
                confidence_results.append(
                    {
                        "per_residue": plddts[sample_index]
                        .detach()
                        .cpu()
                        .tolist(),
                        "sample_index": sample_index,
                    }
                )
        return structures, confidence_results
