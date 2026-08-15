"""Provider-independent exact Method contracts for protein folding."""

from __future__ import annotations

from core import MethodDefinition
from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
)

from .esmfold2_contract import (
    ESM_SDK_REVISION,
    LOCAL_ESMC_ARTIFACT_SHA256,
    LOCAL_ESMC_MODEL,
    LOCAL_ESMC_PRECISION,
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_ARTIFACT_SHA256,
    LOCAL_ESMFOLD2_MODEL,
    LOCAL_ESMFOLD2_REVISION,
    REMOTE_ESMFOLD2_MODEL,
    TRANSFORMERS_REVISION,
)
from .simplefold_contract import (
    SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
    SIMPLEFOLD_MODEL,
    simplefold_confidence_artifact_sha256,
    simplefold_confidence_esm2_artifact_sha256,
    simplefold_folding_artifact_sha256,
)


FOLD_METHOD_VERSION = "4.0.0"
LOCAL_ESMFOLD2_METHOD_VERSION = "6.0.0"
CONFIDENCE_METHOD_VERSION = "3.0.0"


def _method(route: str) -> MethodDefinition:
    if route == "remote":
        return MethodDefinition(
            method_id="folding.fold.esmfold2_fast_biohub_2026_05",
            version=FOLD_METHOD_VERSION,
            algorithm_identity={
                "name": "ESMFold2 sequence-to-structure diffusion",
                "num_loops": 20,
                "num_sampling_steps": 100,
                "lm_dropout": 0.3,
                "lm_mask_pct": 0.1,
                "msa_max_depth": 1024,
                "msa_column_mask_rate": 0.1,
                "include_pae": True,
                "randomness_contract": (
                    "Biohub exposes no seed control; Engine Invocation is "
                    "provider-uncontrolled and no effective seed is published"
                ),
            },
            model_identity={
                "model": REMOTE_ESMFOLD2_MODEL,
                "source": "Biohub",
                "release": "2026-05",
            },
            checkpoint_identity={
                "kind": "provider_managed_exact_model_id",
                "model": REMOTE_ESMFOLD2_MODEL,
            },
            featurization_identity={
                "input": "single-chain canonical protein sequence",
                "output": "provider atom37 PDB",
                "prediction_residue_axis": {
                    "supplied_residue_ids": "preserve_exact_order",
                    "absent_residue_ids": "ordinal_A:1..N",
                    "source": "admitted_input_ProteinSequence",
                },
            },
            source_identity={
                "sdk": "esm",
                "sdk_source_revision": ESM_SDK_REVISION,
                "service": "Biohub",
            },
            scale_contract={
                "ptm": "provider_native_[0,1]",
                "plddt": "provider_native_[0,1]_multiply_100",
                "pae": "provider_native_angstrom",
            },
        )
    return MethodDefinition(
        method_id="folding.fold.esmfold2_hf_1ebf0e3",
        version=LOCAL_ESMFOLD2_METHOD_VERSION,
        algorithm_identity={
            "name": "ESMFold2 sequence-to-structure diffusion",
            "num_loops": 20,
            "num_sampling_steps": 100,
            "lm_dropout": 0.3,
            "lm_mask_pct": 0.1,
            "msa_max_depth": 1024,
            "msa_column_mask_rate": 0.1,
            "include_pae": True,
            "randomness_contract": (
                "exact 32-bit seed derived by protein-workbench-esmfold2-call/v3 "
                "SHA-256 from configured base seed, canonical parent sequence "
                "content digest, and parent-sample slot; the first four digest "
                "bytes are interpreted as one unsigned big-endian integer for "
                "the provider's Python, NumPy MT19937, and Torch seed context"
            ),
        },
        model_identity={
            "model": LOCAL_ESMFOLD2_MODEL,
            "source": "Hugging Face",
            "snapshot_revision": LOCAL_ESMFOLD2_REVISION,
            "language_model": LOCAL_ESMC_MODEL,
            "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
            "language_model_precision": LOCAL_ESMC_PRECISION,
        },
        checkpoint_identity={
            "kind": "immutable_huggingface_snapshots",
            "esmfold2_artifact_sha256": dict(
                sorted(LOCAL_ESMFOLD2_ARTIFACT_SHA256.items())
            ),
            "esmc_artifact_sha256": dict(
                sorted(LOCAL_ESMC_ARTIFACT_SHA256.items())
            ),
        },
        featurization_identity={
            "input": "ESMFold2 StructurePredictionInput single protein",
            "output": "MolecularComplex protein-only PDB",
            "prediction_residue_axis": {
                "supplied_residue_ids": "preserve_exact_order",
                "absent_residue_ids": "ordinal_A:1..N",
                "source": "admitted_input_ProteinSequence",
            },
        },
        source_identity={
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "transformers_source_revision": TRANSFORMERS_REVISION,
            "service": "local_huggingface",
        },
        scale_contract={
            "ptm": "provider_native_[0,1]",
            "plddt": "provider_native_[0,1]_multiply_100",
            "pae": "provider_native_angstrom",
        },
    )


def _simplefold_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="folding.fold.simplefold_100m_c7a5570",
        version=FOLD_METHOD_VERSION,
        algorithm_identity={
            "name": "SimpleFold Euler-Maruyama sequence folding",
            "sampler": "Euler-Maruyama",
            "t_start": 0.0001,
            "tau": 0.1,
            "log_timesteps": True,
            "w_cutoff": 0.99,
            "maximum_num_steps": 50,
            "randomness_contract": (
                "one exact Torch seed per parent batched call derived from "
                "configured base seed, canonical parent sequence content "
                "digest, and parent slot; samples follow provider order"
            ),
        },
        model_identity={
            "folding_model": SIMPLEFOLD_MODEL,
            "confidence_latent_model": "simplefold_1.6B",
            "confidence_output_head": "plddt_module_1.6B",
            "language_model": "esm2_t36_3B_UR50D",
        },
        checkpoint_identity={
            "simplefold_artifact_sha256": (
                simplefold_folding_artifact_sha256()
            ),
            "esm2_artifact_sha256": dict(
                sorted(SIMPLEFOLD_ESM2_ARTIFACT_SHA256.items())
            ),
        },
        featurization_identity={
            "input": "single-chain canonical protein sequence",
            "format": "SimpleFold FASTA A|Protein",
            "ccd_sha256": SIMPLEFOLD_ARTIFACT_SHA256["ccd.pkl"],
            "processor_scale": 16.0,
            "processor_reference_scale": 5.0,
            "prediction_residue_axis": {
                "supplied_residue_ids": "preserve_exact_order",
                "absent_residue_ids": "ordinal_A:1..N",
                "source": "admitted_input_ProteinSequence",
            },
        },
        source_identity={
            "provider": "ml-simplefold",
            "source_revision": SIMPLEFOLD_REVISION,
            "esm2_source_revision": SIMPLEFOLD_ESM2_REVISION,
            "esm2_source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        },
        scale_contract={
            "plddt": "provider_high_level_[0,100]_identity",
        },
    )


def _simplefold_confidence_method() -> MethodDefinition:
    return MethodDefinition(
        method_id=(
            "folding.simplefold_confidence."
            "existing_structure_1_6b_c7a5570"
        ),
        version=CONFIDENCE_METHOD_VERSION,
        algorithm_identity={
            "name": "SimpleFold direct existing-structure confidence",
            "operation": "confidence_only_no_coordinate_generation",
            "latent_time": 1.0,
            "valid_residue_mask": (
                "protein_and_token_present_and_resolved_CA"
            ),
        },
        model_identity={
            "confidence_latent_model": "simplefold_1.6B.ckpt",
            "confidence_output_head": "plddt_module_1.6B.ckpt",
            "language_model": "esm2_t36_3B_UR50D.pt",
        },
        checkpoint_identity={
            "simplefold_artifact_sha256": (
                simplefold_confidence_artifact_sha256()
            ),
            "esm2_artifact_sha256": (
                simplefold_confidence_esm2_artifact_sha256()
            ),
        },
        featurization_identity={
            "contract": SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
            "input": "resolved structure residue axis",
            "axis_contract": (
                "structure_transform.resolved_residue_axis@4.0.0"
            ),
            "association_key": "exact-CandidateDataReference",
            "provider_features": (
                "segments_sequence_named_coordinates_and_masks"
            ),
            "raw_pdb_reparse": "forbidden",
            "ccd_sha256": SIMPLEFOLD_ARTIFACT_SHA256["ccd.pkl"],
            "processor_scale": 16.0,
            "processor_reference_scale": 5.0,
            "encoder_mode": "representation_only_no_contacts",
        },
        source_identity={
            "provider": "ml-simplefold",
            "source_revision": SIMPLEFOLD_REVISION,
            "esm2_source_revision": SIMPLEFOLD_ESM2_REVISION,
            "esm2_source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        },
        scale_contract={
            "plddt": "direct_confidence_head_[0,1]_multiply_100",
        },
    )


REMOTE_ESMFOLD2_FOLD_METHOD = _method("remote")
LOCAL_ESMFOLD2_FOLD_METHOD = _method("local")
SIMPLEFOLD_FOLD_METHOD = _simplefold_method()
SIMPLEFOLD_CONFIDENCE_METHOD = _simplefold_confidence_method()
