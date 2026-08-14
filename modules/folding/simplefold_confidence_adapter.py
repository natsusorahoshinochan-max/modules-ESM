"""Exact existing-structure SimpleFold confidence engine boundary."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import pickle
import shutil
import sys
from argparse import Namespace
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any, cast, Protocol, TypedDict

from core import ReadinessResult, RunResources
from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
    validate_installed_provider_checkout,
)
from datatypes import (
    ResolvedStructureResidueAxis,
    StructureAxisSegment,
)
from .adapter import normalize_residue_plddt
from .simplefold_contract import (
    SIMPLEFOLD_CONFIDENCE_ADAPTER,
    SIMPLEFOLD_CONFIDENCE_ARTIFACTS,
    SIMPLEFOLD_CONFIDENCE_DEVICE,
    SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS,
    SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
)


class _SimpleFoldConfidenceNativeResult(TypedDict):
    native_plddt: list[float]
    valid_protein_residues: list[bool]


@dataclass(frozen=True, slots=True)
class SimpleFoldConfidenceAdapterResult:
    """Canonical pLDDT values admitted from one provider invocation."""

    per_residue_plddt: tuple[float | None, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "per_residue_plddt",
            tuple(self.per_residue_plddt),
        )


class SimpleFoldConfidenceAdapter(Protocol):
    """Resolved-axis existing-structure confidence Operation boundary."""

    def evaluate(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        engine_role: str,
    ) -> SimpleFoldConfidenceAdapterResult: ...


def validated_simplefold_esm2_root(
    source_root: Path | None = None,
) -> Path:
    """Lazily cross the installed ESM2 source validator boundary."""
    from .simplefold_runtime import (
        validated_simplefold_esm2_root as validate,
    )

    return validate(source_root)


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


def _runtime_fingerprint(
    exact_provider_identity: Mapping[str, Any],
) -> str:
    payload = {
        "schema_namespace": (
            "protein-workbench-simplefold-confidence-runtime/v2"
        ),
        "provider_identity": exact_provider_identity,
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


def configured_runtime_fingerprint() -> str:
    """Return the path-free declared identity of the confidence runtime."""
    return _runtime_fingerprint(provider_identity())


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
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise RuntimeError(
            "SimpleFold confidence asset byte count mismatch: "
            f"{path.name}"
        )
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_file_digest(
    path: Path,
    *,
    expected_digest: str,
    identities: Mapping[str, Mapping[str, Any]],
    changed_message: str,
) -> str:
    expected_bytes = identities.get(path.name, {}).get("bytes")
    observed_digest = _sha256_file(
        path,
        expected_bytes=(
            expected_bytes
            if isinstance(expected_bytes, int)
            else None
        ),
    )
    if observed_digest != expected_digest:
        raise RuntimeError(f"{changed_message}: {path.name}")
    return observed_digest


def _validated_file_set(
    root: object,
    expected: Mapping[str, str],
    identities: Mapping[str, Mapping[str, Any]],
) -> tuple[Path, dict[str, str]]:
    if not isinstance(root, Path) or not root.is_dir():
        raise FileNotFoundError(
            "SimpleFold confidence asset root is unavailable"
        )
    observed: dict[str, str] = {}
    for name, expected_digest in sorted(expected.items()):
        observed[name] = _validated_file_digest(
            root / name,
            expected_digest=expected_digest,
            identities=identities,
            changed_message=(
                "SimpleFold confidence asset SHA-256 mismatch"
            ),
        )
    return root, observed


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
    model_root, observed_model_digests = _validated_file_set(
        environment.get("model_root"),
        simplefold_confidence_artifact_sha256(),
        SIMPLEFOLD_ARTIFACT_IDENTITIES,
    )
    esm2_model_root, observed_esm2_digests = _validated_file_set(
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
    resolved_provider_identity = {
        **provider_identity(),
        "artifact_sha256": dict(sorted(observed_model_digests.items())),
        "esm2_artifact_sha256": dict(
            sorted(observed_esm2_digests.items())
        ),
    }
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": source_root,
        "resolved_runtime_fingerprint": fingerprint,
        "resolved_provider_identity": resolved_provider_identity,
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


def _copy_file(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def _stage_file_set(
    source_root: Path,
    destination_root: Path,
    expected: Mapping[str, str],
) -> Path:
    destination_root.mkdir(mode=0o700)
    for name in sorted(expected):
        _copy_file(source_root / name, destination_root / name)
    return destination_root


def _stage_esm2_source(source_root: Path, destination_root: Path) -> Path:
    from .simplefold_runtime import (
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


def _provider_chain_ids(
    segments: tuple[StructureAxisSegment, ...],
) -> tuple[str, ...]:
    reserved = {
        segment.chain_id.strip()
        for segment in segments
        if segment.chain_id.strip()
    }
    assigned: list[str] = []
    used: set[str] = set()
    for segment in segments:
        chain_id = segment.chain_id.strip()
        if not chain_id or chain_id in used:
            chain_id = next(
                (
                    candidate
                    for candidate in (
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "abcdefghijklmnopqrstuvwxyz"
                        "0123456789"
                    )
                    if candidate not in reserved and candidate not in used
                ),
                "",
            )
            if not chain_id:
                raise ValueError(
                    "SimpleFold confidence cannot assign a blank chain"
                )
            reserved.add(chain_id)
        assigned.append(chain_id)
        used.add(chain_id)
    return tuple(assigned)


def _segment_sequences(
    residue_axis: ResolvedStructureResidueAxis,
) -> tuple[str, ...]:
    residue_ids = residue_axis.layout.residue_ids
    assert residue_ids is not None
    sequence_by_residue = dict(
        zip(residue_ids, residue_axis.sequence, strict=True)
    )
    return tuple(
        "".join(
            sequence_by_residue[residue_id]
            for residue_id in segment.residue_ids
        )
        for segment in residue_axis.segments
    )


def _coordinates_by_residue(
    residue_axis: ResolvedStructureResidueAxis,
) -> dict[str, dict[str, tuple[float, float, float]]]:
    return {
        residue.residue_id: {
            atom.atom_name: atom.coordinate
            for atom in residue.atom_coordinates
        }
        for residue in residue_axis.residue_coordinates
    }


def _native_existing_structure_confidence(
    *,
    residue_axis: ResolvedStructureResidueAxis,
    staging_directory: Path,
    validated: Mapping[str, Any],
) -> _SimpleFoldConfidenceNativeResult:
    """Run only the latent confidence path over supplied coordinates."""
    import numpy as np
    import torch

    from .simplefold_runtime import (
        _restore_process_cwd,
        _setup_simplefold_imports,
    )

    @_restore_process_cwd
    def run() -> _SimpleFoldConfidenceNativeResult:
        residue_ids = residue_axis.layout.residue_ids
        assert residue_ids is not None
        input_coordinates = _coordinates_by_residue(residue_axis)
        artifact_root = staging_directory / "simplefold-confidence-assets"
        artifact_root.mkdir(mode=0o700)
        model_dir = _stage_file_set(
            validated["model_root"],
            artifact_root / "verified-provider",
            simplefold_confidence_artifact_sha256(),
        )
        esm2_model_dir = _stage_file_set(
            validated["esm2_model_root"],
            artifact_root / "verified-esm2-model",
            simplefold_confidence_esm2_artifact_sha256(),
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
            from simplefold.boltz_data_pipeline.parse.fasta import (
                parse_fasta,
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
            _copy_file(model_dir / "ccd.pkl", cache / "ccd.pkl")
            fasta_path = cache / "existing.fasta"
            fasta_path.write_text(
                "".join(
                    f">{chain_id}|Protein\n"
                    f"{sequence}\n"
                    for chain_id, sequence in zip(
                        _provider_chain_ids(residue_axis.segments),
                        _segment_sequences(residue_axis),
                        strict=True,
                    )
                )
            )
            with (cache / "ccd.pkl").open("rb") as handle:
                ccd = pickle.load(handle)
            target = parse_fasta(fasta_path, ccd)
            for chain in target.record.chains:
                chain.msa_id = -1
            structure_dir = output_dir / "structures"
            record_dir = output_dir / "records"
            structure_dir.mkdir()
            record_dir.mkdir()
            structure_file = structure_dir / f"{target.record.id}.npz"
            record_file = record_dir / f"{target.record.id}.json"
            target.structure.dump(structure_file)
            record_file.write_text(
                json.dumps(asdict(target.record), sort_keys=True)
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
                structure_file,
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
            raw_coordinates = torch.zeros_like(batch["coords"])
            atom_mask = torch.zeros_like(
                batch["atom_resolved_mask"],
                dtype=torch.bool,
            )
            valid_residue_mask = list(residue_axis.ca_coordinate_mask)
            for residue_index, residue in enumerate(
                provider_structure.residues
            ):
                atom_start = int(residue["atom_idx"])
                atom_count = int(residue["atom_num"])
                supplied = input_coordinates[residue_ids[residue_index]]
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


def _normalize_native_confidence(
    *,
    native_plddt: list[float],
    valid_protein_residues: list[bool],
) -> tuple[float | None, ...]:
    """Apply the fixed direct-head scale after exact validity masking."""
    values, _, _ = normalize_residue_plddt(
        native_plddt=native_plddt,
        valid_residues=valid_protein_residues,
        native_maximum=1.0,
        project_to_valid_residues=False,
    )
    return values


class LocalSimpleFoldConfidenceAdapter:
    """Translate one resolved structure axis through the confidence head."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._validated_environment: Mapping[str, Any] | None = None

    @staticmethod
    def normalize_native_confidence(
        *,
        native_plddt: list[float],
        valid_protein_residues: list[bool],
    ) -> tuple[float | None, ...]:
        return _normalize_native_confidence(
            native_plddt=native_plddt,
            valid_protein_residues=valid_protein_residues,
        )

    def _validated(self) -> Mapping[str, Any]:
        if self._validated_environment is None:
            self._validated_environment = {
                "model_root": cast(Path, self._environment["model_root"]),
                "esm2_model_root": cast(
                    Path,
                    self._environment["esm2_model_root"],
                ),
                "esm2_source_root": cast(
                    Path,
                    self._environment["esm2_source_root"],
                ),
                "resolved_provider_identity": provider_identity(),
            }
        return self._validated_environment

    def _provider_call(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        staging_directory: Path,
        validated: Mapping[str, Any],
    ) -> Callable[[], _SimpleFoldConfidenceNativeResult]:
        client = self._environment.get("provider_client")
        if client is not None:
            def invoke_client() -> _SimpleFoldConfidenceNativeResult:
                return cast(
                    _SimpleFoldConfidenceNativeResult,
                    client.evaluate(
                        residue_axis=residue_axis,
                        staging_directory=staging_directory,
                        resolved_provider_identity=validated[
                            "resolved_provider_identity"
                        ],
                    ),
                )

            return invoke_client

        def invoke_local_runtime() -> _SimpleFoldConfidenceNativeResult:
            return _native_existing_structure_confidence(
                residue_axis=residue_axis,
                staging_directory=staging_directory,
                validated=validated,
            )

        return invoke_local_runtime

    def evaluate(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        engine_role: str,
    ) -> SimpleFoldConfidenceAdapterResult:
        """Invoke once, then decode and normalize outside Invocation."""
        validated = self._validated()
        with self._resources.temporary_directory(
            prefix="simplefold-confidence-"
        ) as staging_directory:
            provider_call = self._provider_call(
                residue_axis=residue_axis,
                staging_directory=staging_directory,
                validated=validated,
            )
            with self._resources.engine_invocation(
                engine_role=engine_role,
            ):
                raw_result = provider_call()
            values = _normalize_native_confidence(
                native_plddt=raw_result["native_plddt"],
                valid_protein_residues=raw_result[
                    "valid_protein_residues"
                ],
            )
        return SimpleFoldConfidenceAdapterResult(
            per_residue_plddt=values,
        )
