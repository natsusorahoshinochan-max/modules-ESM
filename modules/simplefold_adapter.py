"""SimpleFold adapter: wraps ml-simplefold for sequence folding and structure evaluation.

Fold: sequence -> structures + pLDDT (100M model, num_steps capped at 50).
Evaluate: structure -> pLDDT scores (larger model, no re-folding).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tempfile
import uuid
from copy import deepcopy
from functools import wraps
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


def validated_simplefold_model_dir(working_artifacts: Path) -> Path:
    """Resolve only immutable, locally provisioned SimpleFold provider objects."""
    configured = os.environ.get("PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT")
    if not configured:
        raise FileNotFoundError(
            "SimpleFold model root is not explicitly configured"
        )
    model_dir = Path(configured).expanduser()
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise FileNotFoundError(
            "SimpleFold model root is unavailable or is a symlink"
        )
    required_names = {
        *SIMPLEFOLD_ARTIFACT_IDENTITIES,
        *SIMPLEFOLD_AUXILIARY_ARTIFACTS,
    }
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


def _prepare_simplefold_cache(model_dir: Path, cache: Path) -> None:
    """Populate a fresh cache from verified objects; never invoke a downloader."""
    for name in SIMPLEFOLD_AUXILIARY_ARTIFACTS:
        _copy_regular_file(model_dir / name, cache / name)


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
    model_dir = validated_simplefold_model_dir(artifacts)
    old_cwd = _setup_simplefold_imports()
    from simplefold.wrapper import ModelWrapper, InferenceWrapper
    from simplefold.utils.boltz_utils import (
        process_structure,
        save_structure,
        to_pdb as sf_to_pdb,
    )
    from simplefold.utils.fasta_utils import process_fastas
    from simplefold.utils.datamodule_utils import process_one_inference_structure

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

        RunContext.record_active_provider_call(
            "simplefold",
            "fold_sequence",
            model=model_name,
        )
        results = inf_wrapper.run_inference(batch, model, plddt_models, device)

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
        record_provider_call_result(
            provider="simplefold",
            operation="fold_sequence",
            model=model_name,
            provider_identity=simplefold_provider_identity(
                SIMPLEFOLD_ARTIFACT_SHA256
            ),
            effective_seed=None,
            seed_control="unsupported_by_adapter",
            result_summary={
                "input_sequence_length": len(sequence.sequence),
                "input_sequence_sha256": hashlib.sha256(
                    sequence.sequence.encode()
                ).hexdigest(),
                "structure_count": len(produced),
                "pdb_bytes": [
                    len(structure.pdb_string.encode()) for structure in produced
                ],
                "pdb_sha256": [
                    hashlib.sha256(structure.pdb_string.encode()).hexdigest()
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
