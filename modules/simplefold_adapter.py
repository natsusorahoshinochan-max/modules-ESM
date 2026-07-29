"""SimpleFold adapter: wraps ml-simplefold for sequence folding and structure evaluation.

Fold: sequence -> structures + pLDDT (100M model, num_steps capped at 50).
Evaluate: structure -> pLDDT scores (larger model, no re-folding).
"""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from argparse import Namespace
from copy import deepcopy
from functools import partial, wraps
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch

from datatypes import (
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)
from core.provider_contract import (
    SIMPLEFOLD_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_AUXILIARY_ARTIFACTS,
    SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_EXECUTION_ENABLED,
    SIMPLEFOLD_REVISION,
    simplefold_provider_identity,
    validate_installed_provider_checkout,
)


def _setup_simplefold_imports() -> str:
    """Enter the provider package directory and return the prior directory."""
    import simplefold
    old_cwd = os.getcwd()
    sf_dir = os.path.abspath(os.path.dirname(simplefold.__file__))
    if sf_dir not in sys.path:
        sys.path.insert(0, sf_dir)
    os.chdir(sf_dir)
    return old_cwd

def _get_artifact_dir(project_dir: str | None) -> Path:
    """Get or create artifact directory for model checkpoints and outputs."""
    if project_dir:
        base = Path(project_dir)
    else:
        base = Path(tempfile.gettempdir())
    artifacts = base / "simplefold_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def _sha256_regular_file(
    path: Path,
    *,
    expected_bytes: int | None = None,
) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(
                f"SimpleFold artifact is not a regular file: {path.name}"
            )
        if expected_bytes is not None and file_stat.st_size != expected_bytes:
            raise RuntimeError(
                f"SimpleFold artifact byte count mismatch: {path.name}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def validated_simplefold_model_dir(
    working_artifacts: Path,
    model_root: Path | None = None,
    *,
    required_artifacts: tuple[str, ...] | None = None,
) -> Path:
    """Resolve only immutable, locally provisioned SimpleFold provider objects."""
    configured = (
        model_root
        if model_root is not None
        else os.environ.get("PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT")
    )
    if configured is None:
        raise FileNotFoundError(
            "SimpleFold model root is not explicitly configured"
        )
    model_dir = Path(configured).expanduser()
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise FileNotFoundError(
            "SimpleFold model root is unavailable or is a symlink"
        )
    required_names = set(
        required_artifacts
        if required_artifacts is not None
        else (
            *SIMPLEFOLD_ARTIFACT_IDENTITIES,
            *SIMPLEFOLD_AUXILIARY_ARTIFACTS,
        )
    )
    if not SIMPLEFOLD_EXECUTION_ENABLED:
        raise RuntimeError(
            "SimpleFold real-provider execution remains disabled pending "
            "reviewed artifact and runtime containment"
        )
    missing_contract = required_names - SIMPLEFOLD_ARTIFACT_SHA256.keys()
    if missing_contract:
        raise RuntimeError(
            "SimpleFold real-provider SHA-256 contract is incomplete: "
            + ", ".join(sorted(missing_contract))
        )
    for name in sorted(required_names):
        artifact = model_dir / name
        expected_bytes = SIMPLEFOLD_ARTIFACT_IDENTITIES.get(name, {}).get("bytes")
        if artifact.is_symlink() or not artifact.is_file():
            raise FileNotFoundError(
                f"SimpleFold model artifact is missing or incomplete: {name}"
            )
        if _sha256_regular_file(
            artifact,
            expected_bytes=expected_bytes,
        ) != SIMPLEFOLD_ARTIFACT_SHA256[name]:
            raise RuntimeError(
                f"SimpleFold artifact SHA-256 mismatch: {name}"
            )
    validate_installed_provider_checkout("simplefold", SIMPLEFOLD_REVISION)
    working_artifacts.mkdir(parents=True, mode=0o700, exist_ok=True)
    staged = working_artifacts / "verified_provider"
    staged.mkdir(mode=0o700)
    for name in sorted(required_names):
        _copy_regular_file(model_dir / name, staged / name)
        expected_bytes = SIMPLEFOLD_ARTIFACT_IDENTITIES.get(name, {}).get("bytes")
        if _sha256_regular_file(
            staged / name,
            expected_bytes=expected_bytes,
        ) != SIMPLEFOLD_ARTIFACT_SHA256[name]:
            raise RuntimeError(
                f"Staged SimpleFold artifact SHA-256 mismatch: {name}"
            )
    return staged


def _copy_regular_file(source: Path, destination: Path) -> None:
    source_flags = os.O_RDONLY
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
        destination_flags |= os.O_NOFOLLOW
    source_descriptor = os.open(source, source_flags)
    try:
        if not stat.S_ISREG(os.fstat(source_descriptor).st_mode):
            raise RuntimeError("SimpleFold source artifact is not regular")
        destination_descriptor = os.open(
            destination,
            destination_flags,
            0o600,
        )
        try:
            with (
                os.fdopen(source_descriptor, "rb", closefd=False) as source_file,
                os.fdopen(
                    destination_descriptor,
                    "wb",
                    closefd=False,
                ) as destination_file,
            ):
                shutil.copyfileobj(source_file, destination_file)
        finally:
            os.close(destination_descriptor)
    finally:
        os.close(source_descriptor)


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
    source_root: Path | None = None,
) -> Path:
    """Resolve the exact local ESM2 checkout used by SimpleFold."""
    configured = (
        source_root
        if source_root is not None
        else os.environ.get("PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT")
    )
    if configured is None:
        raise FileNotFoundError(
            "SimpleFold ESM2 source root is not explicitly configured"
        )
    source_root = Path(configured).expanduser()
    hubconf = source_root / "hubconf.py"
    if (
        source_root.is_symlink()
        or not source_root.is_dir()
        or hubconf.is_symlink()
        or not hubconf.is_file()
    ):
        raise FileNotFoundError(
            "SimpleFold ESM2 source root must be a regular Git checkout"
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
    tracked = {
        relative
        for relative in _run_simplefold_esm2_git(
            source_root,
            "ls-files",
            "--",
            "hubconf.py",
            "esm",
        ).splitlines()
        if relative
    }
    candidates = [source_root / "hubconf.py", *(source_root / "esm").rglob("*")]
    actual: dict[str, Path] = {}
    for path in candidates:
        if path.is_symlink():
            raise RuntimeError("SimpleFold ESM2 runtime source contains a symlink")
        if path.is_file():
            relative = path.relative_to(source_root).as_posix()
            actual[relative] = path
    if not actual or set(actual) != tracked:
        raise RuntimeError(
            "SimpleFold ESM2 runtime source inventory does not match Git"
        )
    return sorted(actual.items())


def _simplefold_esm2_source_tree_sha256(
    runtime_files: list[tuple[str, Path]],
) -> str:
    digest = hashlib.sha256()
    for relative, path in sorted(runtime_files):
        digest.update(relative.encode() + b"\0")
        digest.update(bytes.fromhex(_sha256_regular_file(path)))
    return digest.hexdigest()


def _stage_simplefold_esm2_source(
    source_root: Path,
    working_artifacts: Path,
) -> Path:
    runtime_files = _simplefold_esm2_runtime_files(source_root)
    if (
        _simplefold_esm2_source_tree_sha256(runtime_files)
        != SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256
    ):
        raise RuntimeError(
            "SimpleFold ESM2 runtime source changed before staging"
        )
    working_artifacts.mkdir(parents=True, mode=0o700, exist_ok=True)
    staged_root = working_artifacts / "verified_esm2_source"
    staged_root.mkdir(mode=0o700)
    for relative, source in runtime_files:
        destination = staged_root / relative
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        _copy_regular_file(source, destination)
    staged_files = _simplefold_esm2_runtime_files_without_git(staged_root)
    if (
        [relative for relative, _ in staged_files]
        != [relative for relative, _ in runtime_files]
        or _simplefold_esm2_source_tree_sha256(staged_files)
        != SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256
    ):
        raise RuntimeError("Staged SimpleFold ESM2 source failed verification")
    return staged_root


def _simplefold_esm2_runtime_files_without_git(
    source_root: Path,
) -> list[tuple[str, Path]]:
    candidates = [source_root / "hubconf.py", *(source_root / "esm").rglob("*")]
    runtime_files: list[tuple[str, Path]] = []
    for path in candidates:
        if path.is_symlink():
            raise RuntimeError("Staged SimpleFold ESM2 source contains a symlink")
        if path.is_file():
            runtime_files.append((
                path.relative_to(source_root).as_posix(),
                path,
            ))
    return sorted(runtime_files)


def validated_simplefold_esm2_model_dir(
    working_artifacts: Path,
    model_root: Path | None = None,
) -> Path:
    """Stage only reviewed ESM2 pickle inputs into the isolated run root."""
    configured = (
        model_root
        if model_root is not None
        else os.environ.get(
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
        )
    )
    if configured is None:
        raise FileNotFoundError(
            "SimpleFold ESM2 model root is not explicitly configured"
        )
    model_root = Path(configured).expanduser()
    if model_root.is_symlink() or not model_root.is_dir():
        raise FileNotFoundError(
            "SimpleFold ESM2 model root is unavailable or is a symlink"
        )
    for name, identity in sorted(
        SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES.items()
    ):
        artifact = model_root / name
        if artifact.is_symlink() or not artifact.is_file():
            raise FileNotFoundError(
                f"SimpleFold ESM2 artifact is missing: {name}"
            )
        if _sha256_regular_file(
            artifact,
            expected_bytes=identity["bytes"],
        ) != SIMPLEFOLD_ESM2_ARTIFACT_SHA256[name]:
            raise RuntimeError(
                f"SimpleFold ESM2 artifact SHA-256 mismatch: {name}"
            )
    working_artifacts.mkdir(parents=True, mode=0o700, exist_ok=True)
    staged = working_artifacts / "verified_esm2_models"
    staged.mkdir(mode=0o700)
    for name, identity in sorted(
        SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES.items()
    ):
        _copy_regular_file(model_root / name, staged / name)
        if _sha256_regular_file(
            staged / name,
            expected_bytes=identity["bytes"],
        ) != SIMPLEFOLD_ESM2_ARTIFACT_SHA256[name]:
            raise RuntimeError(
                f"Staged SimpleFold ESM2 artifact SHA-256 mismatch: {name}"
            )
    return staged


def validated_simplefold_esm2_runtime(
    working_artifacts: Path,
    source_root: Path | None = None,
    model_root: Path | None = None,
) -> tuple[Path, Path]:
    """Stage reviewed ESM2 source and weights before provider import."""
    source_root = validated_simplefold_esm2_root(source_root)
    staged_source = _stage_simplefold_esm2_source(
        source_root,
        working_artifacts,
    )
    staged_models = validated_simplefold_esm2_model_dir(
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
        module_path = Path(pretrained.__file__).resolve()
        if not module_path.is_relative_to(source_root.resolve()):
            raise RuntimeError(
                "SimpleFold ESM2 import escaped the staged source tree"
            )
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
        if source.is_file() and not source.is_symlink():
            _copy_regular_file(source, cache / name)


def _restore_process_cwd(function: Callable[..., Any]) -> Callable[..., Any]:
    """Restore process-global CWD even when the provider raises."""
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        original_cwd = os.getcwd()
        try:
            return function(*args, **kwargs)
        finally:
            os.chdir(original_cwd)

    return wrapped


@_restore_process_cwd
def fold_sequence(
    sequence: ProteinSequence,
    model_name: str = "simplefold_100M",
    num_steps: int = 50,
    num_samples: int = 1,
    project_dir: str | None = None,
    call_details: dict[str, Any] | None = None,
    effective_seed: int | None = None,
    model_root: Path | None = None,
    esm2_source_root: Path | None = None,
    esm2_model_root: Path | None = None,
    required_device: str | None = None,
    record_evidence: bool = True,
) -> tuple[list[ProteinStructure], ScoreCollection]:
    """Fold a protein sequence using SimpleFold.

    Returns (list of ProteinStructure, ScoreCollection).
    Each sample produces one structure with per-residue pLDDT.

    num_steps is capped at 50 per ADR 0013.
    """
    if model_name != "simplefold_100M":
        raise ValueError("SimpleFold folding requires simplefold_100M")
    num_steps = min(num_steps, 50)
    artifacts = _get_artifact_dir(project_dir)
    if model_root is None:
        model_dir = validated_simplefold_model_dir(artifacts)
    else:
        model_dir = validated_simplefold_model_dir(
            artifacts,
            model_root,
            required_artifacts=(
                "ccd.pkl",
                "plddt.ckpt",
                "simplefold_1.6B.ckpt",
                "simplefold_100M.ckpt",
            ),
        )
    if esm2_source_root is None and esm2_model_root is None:
        esm2_source_root, esm2_model_dir = validated_simplefold_esm2_runtime(
            artifacts
        )
    else:
        esm2_source_root, esm2_model_dir = validated_simplefold_esm2_runtime(
            artifacts,
            esm2_source_root,
            esm2_model_root,
        )
    old_cwd = _setup_simplefold_imports()
    from simplefold.wrapper import ModelWrapper, InferenceWrapper
    from simplefold.utils.boltz_utils import (
        process_structure,
        save_structure,
        to_pdb as sf_to_pdb,
    )
    from simplefold.utils.fasta_utils import process_fastas
    from simplefold.utils.datamodule_utils import process_one_inference_structure

    runtime_esm_utils = sys.modules.get("utils.esm_utils")
    runtime_esm_registry = getattr(runtime_esm_utils, "esm_registry", None)
    if not isinstance(runtime_esm_registry, dict):
        raise RuntimeError("SimpleFold ESM2 runtime registry is unavailable")
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
    if required_device is not None and str(device) != required_device:
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
    all_score_entries: list[Score] = []

    # Process each structure file
    struct_files = list(output_dir.glob("structures/*.npz"))
    if not struct_files:
        raise ValueError("No structure files generated from FASTA processing")

    for struct_file in struct_files:
        structure_start = len(structures)
        score_start = len(all_score_entries)
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
        from core.run_context import RunContext

        if record_evidence:
            RunContext.record_active_provider_call(
                "simplefold",
                "fold_sequence",
                model=model_name,
                details=call_details,
            )
        resolved_seed = 42 if effective_seed is None else effective_seed
        if (
            type(resolved_seed) is not int
            or not 0 <= resolved_seed <= 9_007_199_254_740_991
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
            torch.manual_seed(resolved_seed)
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
            plddt_i = plddts[i] if plddts is not None else None

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
            ps = ProteinStructure(pdb_string=pdb_string, source="simplefold")
            structures.append(ps)

            # Collect pLDDT scores
            if plddt_i is not None:
                if isinstance(plddt_i, torch.Tensor):
                    plddt_arr = plddt_i.detach().cpu().numpy()
                elif isinstance(plddt_i, np.ndarray):
                    plddt_arr = plddt_i
                else:
                    plddt_arr = np.array(plddt_i)

                mean_plddt = float(np.mean(plddt_arr)) if plddt_arr.size > 0 else 0.0
                cid = str(uuid.uuid4())
                all_score_entries.append(Score(
                    score_id="plddt",
                    value=mean_plddt,
                    subjects=[cid],
                    details={
                        "per_residue": plddt_arr.tolist() if plddt_arr.size > 0 else [],
                        "sample_index": i,
                    },
                ))
        from core.provider_evidence import record_provider_call_result

        produced = structures[structure_start:]
        if record_evidence:
            record_provider_call_result(
                provider="simplefold",
                operation="fold_sequence",
                model=model_name,
                provider_identity=simplefold_provider_identity(
                    SIMPLEFOLD_ARTIFACT_SHA256
                ),
                effective_seed=resolved_seed,
                seed_control="torch_local",
                result_summary={
                    "input_sequence_length": len(sequence.sequence),
                    "input_sequence_sha256": hashlib.sha256(
                        sequence.sequence.encode()
                    ).hexdigest(),
                    "structure_count": len(produced),
                    "pdb_bytes": [
                        len(structure.pdb_string.encode())
                        for structure in produced
                    ],
                    "pdb_sha256": [
                        hashlib.sha256(
                            structure.pdb_string.encode()
                        ).hexdigest()
                        for structure in produced
                    ],
                    "score_count": len(all_score_entries) - score_start,
                    "num_steps": num_steps,
                },
            )

    os.chdir(old_cwd)
    return structures, ScoreCollection(
        collection_id=str(uuid.uuid4()),
        entries=all_score_entries,
    )


@_restore_process_cwd
def evaluate_structure(
    structure: ProteinStructure,
    model_name: str = "simplefold_360M",
    project_dir: str | None = None,
    call_details: dict[str, Any] | None = None,
) -> ScoreCollection:
    """Evaluate an existing structure to produce pLDDT scores without re-folding.

    Extracts the sequence from the PDB, runs the data pipeline,
    feeds existing coordinates through the folding model for latent extraction,
    then runs the pLDDT head.
    """
    if model_name != "simplefold_360M":
        raise ValueError("SimpleFold evaluation requires simplefold_360M")
    artifacts = _get_artifact_dir(project_dir)
    model_dir = validated_simplefold_model_dir(artifacts)
    esm2_source_root, esm2_model_dir = validated_simplefold_esm2_runtime(
        artifacts
    )
    old_cwd = _setup_simplefold_imports()
    from simplefold.wrapper import ModelWrapper
    from simplefold.utils.fasta_utils import process_fastas
    from simplefold.utils.datamodule_utils import process_one_inference_structure
    from simplefold.utils.boltz_utils import save_structure
    from simplefold.processor.protein_processor import ProteinDataProcessor
    from simplefold.utils.esm_utils import esm_registry, _af2_to_esm
    from simplefold.boltz_data_pipeline.feature.featurizer import BoltzFeaturizer
    from simplefold.boltz_data_pipeline.tokenize.boltz_protein import BoltzTokenizer
    from simplefold.model.flow import LinearPath

    _bind_simplefold_esm2_source(
        esm_registry,
        esm2_source_root,
        esm2_model_dir,
    )

    output_dir = artifacts / "eval_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = artifacts / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    # Write the PDB structure to a temp file for processing
    pdb_path = cache / "eval_input.pdb"
    pdb_path.write_text(structure.pdb_string)

    # Extract sequence from PDB
    seq = _extract_sequence_from_pdb(structure.pdb_string)
    if not seq:
        raise ValueError("Could not extract sequence from PDB structure")

    # Write FASTA
    fasta_path = cache / "eval.fasta"
    fasta_path.write_text(f">A|Protein\n{seq}\n")

    _prepare_simplefold_cache(model_dir, cache)

    # Process FASTA through standard pipeline
    process_fastas(
        data=[fasta_path],
        out_dir=output_dir,
        ccd_path=cache / "ccd.pkl",
    )

    # Initialize model (larger model for evaluation)
    model_wrapper = ModelWrapper(
        simplefold_model=model_name,
        plddt=True,
        ckpt_dir=str(model_dir),
        backend="torch",
    )
    model = model_wrapper.from_pretrained_folding_model()
    plddt_models = model_wrapper.from_pretrained_plddt_model()
    device = model_wrapper.device

    plddt_latent_module = plddt_models["plddt_latent_module"]
    plddt_out_module = plddt_models["plddt_out_module"]

    # Initialize ESM model and components
    esm_model, esm_dict = esm_registry["esm2_3B"]()
    af2_to_esm = _af2_to_esm(esm_dict)
    esm_model = esm_model.to(device).eval()
    af2_to_esm = af2_to_esm.to(device)

    tokenizer = BoltzTokenizer()
    featurizer = BoltzFeaturizer()
    processor = ProteinDataProcessor(
        device=device,
        scale=16.0,
        ref_scale=5.0,
        multiplicity=1,
        inference_multiplicity=1,
        backend="torch",
    )

    struct_files = list(output_dir.glob("structures/*.npz"))
    if not struct_files:
        raise ValueError("No structure files generated from FASTA processing")

    entries: list[Score] = []

    for struct_file in struct_files:
        score_start = len(entries)
        record_file = output_dir / "records" / f"{struct_file.stem}.json"

        batch, structure_data, record = process_one_inference_structure(
            struct_file,
            record_file,
            tokenizer,
            featurizer,
            processor,
            esm_model,
            esm_dict,
            af2_to_esm,
        )

        # Feed existing coordinates through model for latent extraction
        # (not denoising — evaluate only)
        batch_coords = batch["coords"].to(device)
        t = torch.ones(batch_coords.shape[0], device=device)

        from core.run_context import RunContext

        RunContext.record_active_provider_call(
            "simplefold",
            "evaluate_structure",
            model=model_name,
            details=call_details,
        )
        out_feat = plddt_latent_module(batch_coords, t, batch)
        plddt_out_dict = plddt_out_module(out_feat["latent"].detach(), batch)

        # Scale pLDDT to [0, 100]
        plddts = plddt_out_dict["plddt"] * 100.0
        plddt_arr = plddts.detach().cpu().numpy()

        mean_plddt = float(np.mean(plddt_arr)) if plddt_arr.size > 0 else 0.0
        cid = str(uuid.uuid4())
        entries.append(Score(
            score_id="plddt",
            value=mean_plddt,
            subjects=[cid],
            details={
                "per_residue": plddt_arr.tolist() if plddt_arr.size > 0 else [],
                "model": model_name,
            },
        ))
        from core.provider_evidence import record_provider_call_result

        produced_scores = entries[score_start:]
        record_provider_call_result(
            provider="simplefold",
            operation="evaluate_structure",
            model=model_name,
            provider_identity=simplefold_provider_identity(
                SIMPLEFOLD_ARTIFACT_SHA256
            ),
            effective_seed=None,
            seed_control="deterministic_existing_coordinates",
            result_summary={
                "input_pdb_sha256": hashlib.sha256(
                    structure.pdb_string.encode()
                ).hexdigest(),
                "score_count": len(produced_scores),
                "score_ids": [
                    score.score_id for score in produced_scores
                ],
                "score_values": [
                    float(score.value) for score in produced_scores
                ],
            },
        )

    os.chdir(old_cwd)
    return ScoreCollection(
        collection_id=str(uuid.uuid4()),
        entries=entries,
    )


def _extract_sequence_from_pdb(pdb_string: str) -> str:
    """Extract amino acid sequence from PDB ATOM records.

    Uses three-letter codes from CA atoms, grouped by residue.
    """
    aa_3to1 = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    seen: set[str] = set()
    residues: list[str] = []

    for line in pdb_string.splitlines():
        if line.startswith("ATOM") or line.startswith("HETATM"):
            res_name = line[17:20].strip()
            chain = line[21:22]
            res_seq = line[22:26].strip()
            key = f"{chain}_{res_seq}"
            if key not in seen:
                seen.add(key)
                aa = aa_3to1.get(res_name, "X")
                residues.append(aa)

    return "".join(residues)
