"""SimpleFold adapter: wraps ml-simplefold for sequence folding and structure evaluation.

Fold: sequence -> structures + pLDDT (100M model, num_steps capped at 50).
Evaluate: structure -> pLDDT scores (larger model, no re-folding).
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import torch

from datatypes import (
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)


def _setup_simplefold_imports() -> None:
    """Ensure simplefold internal absolute imports resolve correctly."""
    import simplefold
    sf_dir = os.path.abspath(os.path.dirname(simplefold.__file__))
    if sf_dir not in sys.path:
        sys.path.insert(0, sf_dir)

def _get_artifact_dir(project_dir: str | None) -> Path:
    """Get or create artifact directory for model checkpoints and outputs."""
    if project_dir:
        base = Path(project_dir)
    else:
        base = Path(tempfile.gettempdir())
    artifacts = base / "simplefold_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def fold_sequence(
    sequence: ProteinSequence,
    model_name: str = "simplefold_100M",
    num_steps: int = 50,
    num_samples: int = 1,
    project_dir: str | None = None,
    context: "RunContext | None" = None,
) -> tuple[list[ProteinStructure], ScoreCollection]:
    """Fold a protein sequence using SimpleFold.

    Returns (list of ProteinStructure, ScoreCollection).
    Each sample produces one structure with per-residue pLDDT.

    num_steps is capped at 50 per ADR 0013.
    """
    old_cwd = _setup_simplefold_imports()
    from simplefold.wrapper import ModelWrapper, InferenceWrapper
    from simplefold.utils.boltz_utils import (
        process_structure,
        save_structure,
        to_pdb as sf_to_pdb,
    )
    from simplefold.utils.fasta_utils import (
        download_fasta_utilities,
        process_fastas,
    )
    from simplefold.utils.datamodule_utils import process_one_inference_structure

    num_steps = min(num_steps, 50)
    artifacts = _get_artifact_dir(project_dir)
    output_dir = artifacts / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = artifacts / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    # Write sequence to FASTA
    fasta_path = cache / "input.fasta"
    fasta_path.write_text(f">A|Protein\n{sequence.sequence}\n")

    # Download FASTA utilities if needed
    download_fasta_utilities(cache)

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
        ckpt_dir=str(artifacts),
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
        if context is not None:
            context.record_provider_call(
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

    os.chdir(old_cwd)
    return structures, ScoreCollection(
        collection_id=str(uuid.uuid4()),
        entries=all_score_entries,
    )


def evaluate_structure(
    structure: ProteinStructure,
    model_name: str = "simplefold_360M",
    project_dir: str | None = None,
    context: "RunContext | None" = None,
) -> ScoreCollection:
    """Evaluate an existing structure to produce pLDDT scores without re-folding.

    Extracts the sequence from the PDB, runs the data pipeline,
    feeds existing coordinates through the folding model for latent extraction,
    then runs the pLDDT head.
    """
    old_cwd = _setup_simplefold_imports()
    from simplefold.wrapper import ModelWrapper
    from simplefold.utils.fasta_utils import (
        download_fasta_utilities,
        process_fastas,
    )
    from simplefold.utils.datamodule_utils import process_one_inference_structure
    from simplefold.utils.boltz_utils import save_structure
    from simplefold.processor.protein_processor import ProteinDataProcessor
    from simplefold.utils.esm_utils import esm_registry, _af2_to_esm
    from simplefold.boltz_data_pipeline.feature.featurizer import BoltzFeaturizer
    from simplefold.boltz_data_pipeline.tokenize.boltz_protein import BoltzTokenizer
    from simplefold.model.flow import LinearPath

    artifacts = _get_artifact_dir(project_dir)
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

    # Download FASTA utilities if needed
    download_fasta_utilities(cache)

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
        ckpt_dir=str(artifacts),
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

        if context is not None:
            context.record_provider_call(
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
