"""Exact local SimpleFold folding boundary for the shared folding package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from collections.abc import Mapping
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
    simplefold_provider_identity,
    validate_installed_provider_checkout,
)
from datatypes import ProteinSequence, ProteinStructure


SIMPLEFOLD_MODEL = "simplefold_100M"
SIMPLEFOLD_DEVICE = "cpu"
SIMPLEFOLD_FOLDING_ARTIFACTS = (
    "ccd.pkl",
    "plddt.ckpt",
    "simplefold_1.6B.ckpt",
    "simplefold_100M.ckpt",
)


def simplefold_folding_artifact_sha256() -> dict[str, str]:
    """Return the exact checkpoint closure used by the folding Binding."""
    return {
        name: SIMPLEFOLD_ARTIFACT_SHA256[name]
        for name in SIMPLEFOLD_FOLDING_ARTIFACTS
    }


def simplefold_folding_provider_identity() -> dict[str, Any]:
    """Return evidence for only the assets actually used by this Binding."""
    return simplefold_provider_identity(
        simplefold_folding_artifact_sha256()
    )


def configured_runtime_fingerprint() -> str:
    """Return the path-free exact identity of the selected folding runtime."""
    payload = {
        "schema_namespace": "protein-workbench-simplefold-runtime/v2",
        "provider_source_revision": SIMPLEFOLD_REVISION,
        "model": SIMPLEFOLD_MODEL,
        "device": SIMPLEFOLD_DEVICE,
        "simplefold_artifact_sha256": simplefold_folding_artifact_sha256(),
        "esm2_source_revision": SIMPLEFOLD_ESM2_REVISION,
        "esm2_source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
        "esm2_artifact_sha256": dict(
            sorted(SIMPLEFOLD_ESM2_ARTIFACT_SHA256.items())
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def simplefold_runtime_structurally_available() -> bool:
    """Probe import/install structure without importing or loading a model."""
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
            f"SimpleFold asset is unavailable: {path.name}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise FileNotFoundError(
                f"SimpleFold asset is unavailable: {path.name}"
            )
        if expected_bytes is not None and metadata.st_size != expected_bytes:
            raise RuntimeError(
                f"SimpleFold asset byte count mismatch: {path.name}"
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
        raise FileNotFoundError("SimpleFold asset root is unavailable")
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
                f"SimpleFold asset SHA-256 mismatch: {name}"
            )
    return root


def validate_simplefold_folding_environment(
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the exact selected folding assets without staging a model."""
    if environment.get("device") != SIMPLEFOLD_DEVICE:
        raise RuntimeError("SimpleFold device identity does not match")
    fingerprint = environment.get("resolved_runtime_fingerprint")
    if fingerprint != configured_runtime_fingerprint():
        raise RuntimeError("SimpleFold runtime fingerprint does not match")
    model_root = _validated_file_set(
        environment.get("model_root"),
        simplefold_folding_artifact_sha256(),
        SIMPLEFOLD_ARTIFACT_IDENTITIES,
    )
    esm2_model_root = _validated_file_set(
        environment.get("esm2_model_root"),
        SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
        SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    )
    source_root = environment.get("esm2_source_root")
    if not isinstance(source_root, Path):
        raise FileNotFoundError("SimpleFold ESM2 source root is unavailable")
    from modules.simplefold_adapter import validated_simplefold_esm2_root

    observed_source = validated_simplefold_esm2_root(source_root)
    if Path(observed_source).resolve() != source_root.resolve():
        raise RuntimeError("SimpleFold ESM2 source identity changed")
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": source_root,
        "resolved_runtime_fingerprint": fingerprint,
    }


def simplefold_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    try:
        validate_installed_provider_checkout(
            "simplefold",
            SIMPLEFOLD_REVISION,
        )
        validate_simplefold_folding_environment(environment)
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
            reason_code="simplefold_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def provider_identity() -> dict[str, Any]:
    return simplefold_folding_provider_identity()


def fold(
    *,
    sequence: ProteinSequence,
    num_steps: int,
    num_samples: int,
    effective_seed: int,
    staging_directory: Path,
    environment: Mapping[str, Any],
    call_details: dict[str, Any],
) -> tuple[list[ProteinStructure], Any]:
    """Cross the provider folding seam inside one private staging directory."""
    client = environment.get("provider_client")
    if client is not None:
        return client.fold(
            sequence=sequence,
            num_steps=num_steps,
            num_samples=num_samples,
            effective_seed=effective_seed,
            staging_directory=staging_directory,
            call_details=call_details,
        )
    validated = validate_simplefold_folding_environment(environment)
    from modules.simplefold_adapter import fold_sequence

    return fold_sequence(
        sequence=sequence,
        model_name=SIMPLEFOLD_MODEL,
        num_steps=num_steps,
        num_samples=num_samples,
        project_dir=str(staging_directory),
        call_details=call_details,
        effective_seed=effective_seed,
        model_root=validated["model_root"],
        esm2_source_root=validated["esm2_source_root"],
        esm2_model_root=validated["esm2_model_root"],
        required_device=SIMPLEFOLD_DEVICE,
        record_evidence=False,
    )
