"""Exact existing-structure SimpleFold confidence engine boundary."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import os
import stat
import sys
from argparse import Namespace
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from core import ReadinessResult
from core.provider_contract import (
    SIMPLEFOLD_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
    validate_installed_provider_checkout,
)
from datatypes import ProteinStructure
from modules.simplefold_adapter import validated_simplefold_esm2_root


SIMPLEFOLD_CONFIDENCE_ARTIFACTS = (
    "ccd.pkl",
    "plddt.ckpt",
    "simplefold_1.6B.ckpt",
)
SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS = (
    "esm2_t36_3B_UR50D.pt",
)
SIMPLEFOLD_CONFIDENCE_DEVICE = "cpu"
SIMPLEFOLD_CONFIDENCE_FEATURIZATION = (
    "simplefold-existing-structure-featurization/v1"
)
SIMPLEFOLD_CONFIDENCE_ADAPTER = (
    "protein-workbench-simplefold-confidence-adapter/v1"
)


def simplefold_confidence_artifact_sha256() -> dict[str, str]:
    """Return the exact SimpleFold model/data closure used by confidence."""
    return {
        name: SIMPLEFOLD_ARTIFACT_SHA256[name]
        for name in SIMPLEFOLD_CONFIDENCE_ARTIFACTS
    }


def simplefold_confidence_esm2_artifact_sha256() -> dict[str, str]:
    """Return the representation-only ESM2 weight closure."""
    return {
        name: SIMPLEFOLD_ESM2_ARTIFACT_SHA256[name]
        for name in SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS
    }


def provider_identity() -> dict[str, Any]:
    """Return only scientific assets crossed by this engine boundary."""
    return {
        "source": "ml-simplefold",
        "source_revision": SIMPLEFOLD_REVISION,
        "esm2_source_revision": SIMPLEFOLD_ESM2_REVISION,
        "esm2_source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        "esm2_artifact_sha256": (
            simplefold_confidence_esm2_artifact_sha256()
        ),
        "artifact_sha256": simplefold_confidence_artifact_sha256(),
    }


def configured_runtime_fingerprint() -> str:
    """Return the path-free exact identity of the confidence runtime."""
    payload = {
        "schema_namespace": (
            "protein-workbench-simplefold-confidence-runtime/v2"
        ),
        "provider_identity": provider_identity(),
        "device": SIMPLEFOLD_CONFIDENCE_DEVICE,
        "featurization": SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
        "adapter": SIMPLEFOLD_CONFIDENCE_ADAPTER,
        "native_to_canonical_scale": (
            "direct_confidence_head_[0,1]_multiply_100"
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def simplefold_confidence_runtime_structurally_available() -> bool:
    """Probe package structure without probing or loading any model asset."""
    if (
        importlib.util.find_spec("simplefold") is None
        or importlib.util.find_spec("torch") is None
    ):
        return False
    try:
        validate_installed_provider_checkout(
            "simplefold",
            SIMPLEFOLD_REVISION,
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return True


def _sha256_file(path: Path, *, expected_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise FileNotFoundError(
            f"SimpleFold confidence asset is unavailable: {path.name}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise FileNotFoundError(
                f"SimpleFold confidence asset is unavailable: {path.name}"
            )
        if expected_bytes is not None and metadata.st_size != expected_bytes:
            raise RuntimeError(
                "SimpleFold confidence asset byte count mismatch: "
                f"{path.name}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _validated_file_set(
    root: object,
    expected: Mapping[str, str],
    identities: Mapping[str, Mapping[str, Any]],
) -> Path:
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise FileNotFoundError(
            "SimpleFold confidence asset root is unavailable"
        )
    for name, expected_digest in sorted(expected.items()):
        expected_bytes = identities.get(name, {}).get("bytes")
        if _sha256_file(
            root / name,
            expected_bytes=(
                expected_bytes
                if isinstance(expected_bytes, int)
                else None
            ),
        ) != expected_digest:
            raise RuntimeError(
                f"SimpleFold confidence asset SHA-256 mismatch: {name}"
            )
    return root


def validate_simplefold_confidence_environment(
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve and validate the exact confidence assets without model load."""
    if environment.get("device") != SIMPLEFOLD_CONFIDENCE_DEVICE:
        raise RuntimeError("SimpleFold confidence device identity changed")
    fingerprint = environment.get("resolved_runtime_fingerprint")
    if fingerprint != configured_runtime_fingerprint():
        raise RuntimeError(
            "SimpleFold confidence runtime fingerprint changed"
        )
    model_root = _validated_file_set(
        environment.get("model_root"),
        simplefold_confidence_artifact_sha256(),
        SIMPLEFOLD_ARTIFACT_IDENTITIES,
    )
    esm2_model_root = _validated_file_set(
        environment.get("esm2_model_root"),
        simplefold_confidence_esm2_artifact_sha256(),
        SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    )
    source_root = environment.get("esm2_source_root")
    if not isinstance(source_root, Path):
        raise FileNotFoundError(
            "SimpleFold confidence ESM2 source root is unavailable"
        )
    observed_source = validated_simplefold_esm2_root(source_root)
    if Path(observed_source).resolve() != source_root.resolve():
        raise RuntimeError("SimpleFold confidence ESM2 source identity changed")
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": source_root,
        "resolved_runtime_fingerprint": fingerprint,
        "resolved_provider_identity": provider_identity(),
    }


def simplefold_confidence_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    try:
        validate_installed_provider_checkout(
            "simplefold",
            SIMPLEFOLD_REVISION,
        )
        validate_simplefold_confidence_environment(environment)
    except (
        FileNotFoundError,
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="simplefold_confidence_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def invocation_identity() -> str:
    """Bind the exact verified asset closure to public Invocation evidence."""
    return (
        "folding.simplefold_confidence.assets."
        f"{configured_runtime_fingerprint()}"
    )


def _copy_regular_file(source: Path, destination: Path) -> None:
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    source_descriptor = os.open(source, source_flags)
    try:
        if not stat.S_ISREG(os.fstat(source_descriptor).st_mode):
            raise RuntimeError(
                "SimpleFold confidence source asset is not regular"
            )
        destination_descriptor = os.open(
            destination,
            destination_flags,
            0o600,
        )
        try:
            while chunk := os.read(source_descriptor, 1024 * 1024):
                written = 0
                while written < len(chunk):
                    count = os.write(
                        destination_descriptor,
                        chunk[written:],
                    )
                    if count <= 0:
                        raise OSError(
                            "SimpleFold confidence asset copy stalled"
                        )
                    written += count
        finally:
            os.close(destination_descriptor)
    finally:
        os.close(source_descriptor)


def _stage_file_set(
    source_root: Path,
    destination_root: Path,
    expected: Mapping[str, str],
    identities: Mapping[str, Mapping[str, Any]],
) -> Path:
    destination_root.mkdir(mode=0o700)
    for name, expected_digest in sorted(expected.items()):
        destination = destination_root / name
        _copy_regular_file(source_root / name, destination)
        expected_bytes = identities.get(name, {}).get("bytes")
        if _sha256_file(
            destination,
            expected_bytes=(
                expected_bytes
                if isinstance(expected_bytes, int)
                else None
            ),
        ) != expected_digest:
            raise RuntimeError(
                f"Staged SimpleFold confidence asset changed: {name}"
            )
    return destination_root


def _stage_esm2_source(source_root: Path, destination_root: Path) -> Path:
    from modules.simplefold_adapter import (
        _stage_simplefold_esm2_source,
    )

    return _stage_simplefold_esm2_source(
        source_root,
        destination_root,
    )


def _load_representation_only_esm2(
    source_root: Path,
    model_path: Path,
) -> tuple[Any, Any]:
    """Load ESM2 representations without opening contact-regression weights."""
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
        module_path = Path(pretrained.__file__).resolve()
        if not module_path.is_relative_to(source_root.resolve()):
            raise RuntimeError(
                "SimpleFold confidence ESM2 import escaped reviewed source"
            )
        with torch.serialization.safe_globals([Namespace]):
            model_data = torch.load(
                str(model_path),
                map_location="cpu",
                weights_only=True,
            )
        return pretrained.load_model_and_alphabet_core(
            model_path.stem,
            model_data,
            None,
        )[:2]
    finally:
        if source_entry in sys.path:
            sys.path.remove(source_entry)
        for module_name in tuple(sys.modules):
            if module_name == "esm" or module_name.startswith("esm."):
                sys.modules.pop(module_name, None)
        sys.modules.update(prior_esm_modules)


def _pdb_residues(
    pdb_string: str,
) -> tuple[str, list[dict[str, tuple[float, float, float]]]]:
    letters = {
        "ALA": "A",
        "ARG": "R",
        "ASN": "N",
        "ASP": "D",
        "CYS": "C",
        "GLN": "Q",
        "GLU": "E",
        "GLY": "G",
        "HIS": "H",
        "ILE": "I",
        "LEU": "L",
        "LYS": "K",
        "MET": "M",
        "PHE": "F",
        "PRO": "P",
        "SER": "S",
        "THR": "T",
        "TRP": "W",
        "TYR": "Y",
        "VAL": "V",
    }
    order: list[tuple[str, str, str]] = []
    names: dict[tuple[str, str, str], str] = {}
    coordinates: dict[
        tuple[str, str, str],
        dict[str, tuple[float, float, float]],
    ] = {}
    for line in pdb_string.splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54:
            continue
        altloc = line[16]
        if altloc not in {" ", "A"}:
            continue
        identity = (line[21], line[22:26].strip(), line[26])
        residue_name = line[17:20].strip().upper()
        atom_name = line[12:16].strip()
        if residue_name not in letters or not atom_name:
            continue
        try:
            coordinate = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
        except ValueError as error:
            raise ValueError(
                "SimpleFold confidence PDB has malformed coordinates"
            ) from error
        if not all(math.isfinite(value) for value in coordinate):
            raise ValueError(
                "SimpleFold confidence PDB has non-finite coordinates"
            )
        if identity not in coordinates:
            order.append(identity)
            names[identity] = residue_name
            coordinates[identity] = {}
        elif names[identity] != residue_name:
            raise ValueError(
                "SimpleFold confidence PDB residue identity is ambiguous"
            )
        if atom_name in coordinates[identity]:
            raise ValueError(
                "SimpleFold confidence PDB has duplicate atom identity"
            )
        coordinates[identity][atom_name] = coordinate
    if not order:
        raise ValueError(
            "SimpleFold confidence requires protein ATOM coordinates"
        )
    return (
        "".join(letters[names[identity]] for identity in order),
        [coordinates[identity] for identity in order],
    )


def _native_existing_structure_confidence(
    *,
    structure: ProteinStructure,
    staging_directory: Path,
    validated: Mapping[str, Any],
) -> dict[str, Any]:
    """Run only the latent confidence path over supplied coordinates."""
    import numpy as np
    import torch

    from modules.simplefold_adapter import (
        _restore_process_cwd,
        _setup_simplefold_imports,
    )

    @_restore_process_cwd
    def run() -> dict[str, Any]:
        sequence, input_residues = _pdb_residues(structure.pdb_string)
        artifact_root = staging_directory / "simplefold-confidence-assets"
        artifact_root.mkdir(mode=0o700)
        model_dir = _stage_file_set(
            validated["model_root"],
            artifact_root / "verified-provider",
            simplefold_confidence_artifact_sha256(),
            SIMPLEFOLD_ARTIFACT_IDENTITIES,
        )
        esm2_model_dir = _stage_file_set(
            validated["esm2_model_root"],
            artifact_root / "verified-esm2-model",
            simplefold_confidence_esm2_artifact_sha256(),
            SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
        )
        esm2_source_root = _stage_esm2_source(
            validated["esm2_source_root"],
            artifact_root / "esm2-source-work",
        )
        old_cwd = _setup_simplefold_imports()
        try:
            from simplefold.boltz_data_pipeline import const
            from simplefold.boltz_data_pipeline.feature.featurizer import (
                BoltzFeaturizer,
            )
            from simplefold.boltz_data_pipeline.tokenize.boltz_protein import (
                BoltzTokenizer,
            )
            from simplefold.processor.protein_processor import (
                ProteinDataProcessor,
            )
            from simplefold.utils.datamodule_utils import (
                process_one_inference_structure,
            )
            from simplefold.utils.esm_utils import _af2_to_esm, esm_registry
            from simplefold.utils.fasta_utils import process_fastas
            from simplefold.wrapper import ModelWrapper

            esm_registry["esm2_3B"] = partial(
                _load_representation_only_esm2,
                esm2_source_root,
                esm2_model_dir / "esm2_t36_3B_UR50D.pt",
            )
            cache = staging_directory / "confidence-input"
            output_dir = staging_directory / "confidence-features"
            cache.mkdir(mode=0o700)
            output_dir.mkdir(mode=0o700)
            _copy_regular_file(model_dir / "ccd.pkl", cache / "ccd.pkl")
            fasta_path = cache / "existing.fasta"
            fasta_path.write_text(f">A|Protein\n{sequence}\n")
            process_fastas(
                data=[fasta_path],
                out_dir=output_dir,
                ccd_path=cache / "ccd.pkl",
            )
            struct_files = list(output_dir.glob("structures/*.npz"))
            if len(struct_files) != 1:
                raise RuntimeError(
                    "SimpleFold confidence featurization is incomplete"
                )
            record_file = (
                output_dir / "records" / f"{struct_files[0].stem}.json"
            )
            wrapper = ModelWrapper(
                simplefold_model="simplefold_1.6B",
                plddt=True,
                ckpt_dir=str(model_dir),
                backend="torch",
            )
            plddt_models = wrapper.from_pretrained_plddt_model()
            device = wrapper.device
            if str(device) != SIMPLEFOLD_CONFIDENCE_DEVICE:
                raise RuntimeError(
                    "SimpleFold confidence provider device changed"
                )
            esm_model, esm_dict = esm_registry["esm2_3B"]()
            esm_model = esm_model.to(device).eval()
            af2_to_esm = _af2_to_esm(esm_dict).to(device)
            batch, provider_structure, _ = process_one_inference_structure(
                struct_files[0],
                record_file,
                BoltzTokenizer(),
                BoltzFeaturizer(),
                ProteinDataProcessor(
                    device=device,
                    scale=16.0,
                    ref_scale=5.0,
                    multiplicity=1,
                    inference_multiplicity=1,
                    backend="torch",
                ),
                esm_model,
                esm_dict,
                af2_to_esm,
            )
            if len(provider_structure.residues) != len(input_residues):
                raise ValueError(
                    "SimpleFold confidence residue featurization changed"
                )
            raw_coordinates = torch.zeros_like(batch["coords"])
            atom_mask = torch.zeros_like(
                batch["atom_resolved_mask"],
                dtype=torch.bool,
            )
            valid_residue_mask: list[bool] = []
            for residue_index, residue in enumerate(
                provider_structure.residues
            ):
                atom_start = int(residue["atom_idx"])
                atom_count = int(residue["atom_num"])
                supplied = input_residues[residue_index]
                for atom_index in range(atom_start, atom_start + atom_count):
                    encoded_name = provider_structure.atoms[atom_index][
                        "name"
                    ]
                    atom_name = "".join(
                        chr(int(value) + 32)
                        for value in encoded_name
                        if int(value) != 0
                    )
                    coordinate = supplied.get(atom_name)
                    if coordinate is None:
                        continue
                    raw_coordinates[0, atom_index] = torch.tensor(
                        coordinate,
                        device=raw_coordinates.device,
                        dtype=raw_coordinates.dtype,
                    )
                    atom_mask[0, atom_index] = True
                valid_residue_mask.append("CA" in supplied)
            if not any(valid_residue_mask):
                raise ValueError(
                    "SimpleFold confidence has no valid protein residues"
                )
            center = raw_coordinates[0, atom_mask[0]].mean(dim=0)
            raw_coordinates[0, atom_mask[0]] -= center
            batch["coords"] = raw_coordinates / 16.0
            batch["atom_resolved_mask"] = atom_mask.to(
                batch["atom_resolved_mask"].dtype
            )
            token_valid = (
                batch["token_pad_mask"].bool()
                & batch["token_resolved_mask"].bool()
                & (
                    batch["mol_type"]
                    == const.chain_type_ids["PROTEIN"]
                )
            )
            supplied_valid = torch.zeros_like(token_valid)
            supplied_valid[0, : len(valid_residue_mask)] = torch.tensor(
                valid_residue_mask,
                device=supplied_valid.device,
            )
            token_valid &= supplied_valid
            latent_module = plddt_models["plddt_latent_module"]
            output_module = plddt_models["plddt_out_module"]
            with torch.inference_mode():
                t = torch.ones(
                    batch["coords"].shape[0],
                    device=batch["coords"].device,
                )
                latent = latent_module(batch["coords"], t, batch)
                direct = output_module(
                    latent["latent"].detach(),
                    batch,
                )["plddt"]
            native = direct.detach().cpu().numpy().reshape(-1)
            valid = token_valid.detach().cpu().numpy().reshape(-1)
            return {
                "native_plddt": [
                    float(value)
                    for value in np.asarray(native).tolist()
                ],
                "valid_protein_residues": [
                    bool(value)
                    for value in np.asarray(valid).tolist()
                ],
            }
        finally:
            os.chdir(old_cwd)

    return run()


def evaluate(
    *,
    structure: ProteinStructure,
    staging_directory: Path,
    environment: Mapping[str, Any],
    call_details: Mapping[str, Any],
) -> dict[str, Any]:
    """Cross exactly one existing-structure confidence engine seam."""
    del call_details
    validated = validate_simplefold_confidence_environment(environment)
    client = environment.get("provider_client")
    if client is not None:
        result = client.evaluate(
            structure=structure,
            staging_directory=staging_directory,
            resolved_provider_identity=validated[
                "resolved_provider_identity"
            ],
        )
        if not isinstance(result, Mapping):
            raise ValueError(
                "SimpleFold confidence provider result is malformed"
            )
        return dict(result)
    return _native_existing_structure_confidence(
        structure=structure,
        staging_directory=staging_directory,
        validated=validated,
    )
