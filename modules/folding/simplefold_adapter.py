"""Exact local SimpleFold folding boundary for the shared folding package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core import ReadinessResult, RunResources
from modules.provider_contract import (
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
from .simplefold_contract import SIMPLEFOLD_FOLDING_ARTIFACTS


SIMPLEFOLD_MODEL = "simplefold_100M"
SIMPLEFOLD_DEVICE = "cpu"


@dataclass(frozen=True, slots=True)
class SimpleFoldSampleResult:
    """One provider-independent folded structure and canonical pLDDT."""

    structure: ProteinStructure
    per_residue_plddt: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "per_residue_plddt",
            tuple(self.per_residue_plddt),
        )


@dataclass(frozen=True, slots=True)
class SimpleFoldAdapterResult:
    """Complete canonical samples and actual effective call randomness."""

    samples: tuple[SimpleFoldSampleResult, ...]
    effective_call_seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))


class SimpleFoldAdapter(Protocol):
    """Canonical folding Operation boundary for local SimpleFold."""

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        num_steps: int,
        num_samples: int,
        derived_call_seed: int,
        engine_role: str,
    ) -> SimpleFoldAdapterResult: ...


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
    from .simplefold_runtime import validated_simplefold_esm2_root

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


def _decode_fold_result(
    *,
    raw_result: object,
    sequence: ProteinSequence,
    sample_count: int,
) -> tuple[SimpleFoldSampleResult, ...]:
    """Admit provider-native structures and high-level `[0,100]` scores."""
    from .adapter import _pdb_sequence

    if (
        not isinstance(raw_result, tuple)
        or len(raw_result) != 2
    ):
        raise ValueError("SimpleFold result is incomplete")
    structures, scores = raw_result
    if (
        not isinstance(structures, list)
        or len(structures) != sample_count
        or any(
            type(structure) is not ProteinStructure
            for structure in structures
        )
        or not isinstance(scores, Sequence)
    ):
        raise ValueError("SimpleFold result is incomplete")
    for structure in structures:
        if _pdb_sequence(structure.pdb_string) != sequence.sequence:
            raise ValueError("SimpleFold structure is malformed")
    by_sample: dict[int, tuple[float, ...]] = {}
    for entry in scores:
        if not isinstance(entry, Mapping) or set(entry) != {
            "sample_index",
            "per_residue",
        }:
            raise ValueError("SimpleFold confidence result is malformed")
        sample_index = entry.get("sample_index")
        values = entry.get("per_residue")
        if (
            type(sample_index) is not int
            or sample_index in by_sample
            or not isinstance(values, list)
            or len(values) != len(sequence.sequence)
        ):
            raise ValueError("SimpleFold confidence result is incomplete")
        normalized: list[float] = []
        for value in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 100.0
            ):
                raise ValueError(
                    "SimpleFold high-level pLDDT is outside [0,100]"
                )
            normalized.append(float(value))
        if not 0 <= sample_index < sample_count:
            raise ValueError("SimpleFold sample index is invalid")
        by_sample[sample_index] = tuple(normalized)
    if set(by_sample) != set(range(sample_count)):
        raise ValueError("SimpleFold confidence samples are incomplete")
    return tuple(
        SimpleFoldSampleResult(
            structure=structures[sample_index],
            per_residue_plddt=by_sample[sample_index],
        )
        for sample_index in range(sample_count)
    )


class LocalSimpleFoldAdapter:
    """Translate canonical folding values through exact local SimpleFold."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

    def _provider_call(
        self,
        *,
        sequence: ProteinSequence,
        num_steps: int,
        num_samples: int,
        effective_seed: int,
        staging_directory: Path,
    ) -> Callable[[], object]:
        client = self._environment.get("provider_client")
        if client is not None:
            def invoke_client() -> object:
                return client.fold(
                    sequence=sequence,
                    num_steps=num_steps,
                    num_samples=num_samples,
                    effective_seed=effective_seed,
                    staging_directory=staging_directory,
                )

            return invoke_client
        validated = validate_simplefold_folding_environment(
            self._environment
        )
        from .simplefold_runtime import fold_sequence

        def invoke_local_runtime() -> object:
            return fold_sequence(
                sequence=sequence,
                model_name=SIMPLEFOLD_MODEL,
                num_steps=num_steps,
                num_samples=num_samples,
                project_dir=str(staging_directory),
                effective_seed=effective_seed,
                model_root=validated["model_root"],
                esm2_source_root=validated["esm2_source_root"],
                esm2_model_root=validated["esm2_model_root"],
                required_device=SIMPLEFOLD_DEVICE,
                record_evidence=False,
            )

        return invoke_local_runtime

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        num_steps: int,
        num_samples: int,
        derived_call_seed: int,
        engine_role: str,
    ) -> SimpleFoldAdapterResult:
        """Invoke once, decode outside Invocation, and clean private work."""
        with self._resources.temporary_directory(
            prefix="simplefold-fold-"
        ) as staging_directory:
            provider_call = self._provider_call(
                sequence=sequence,
                num_steps=num_steps,
                num_samples=num_samples,
                effective_seed=derived_call_seed,
                staging_directory=staging_directory,
            )
            with self._resources.engine_invocation(
                engine_role=engine_role,
                invocation_provenance={
                    "effective_randomness": {
                        "control": "exact_seed",
                        "effective_seed": derived_call_seed,
                    }
                },
            ):
                raw_result = provider_call()
            samples = _decode_fold_result(
                raw_result=raw_result,
                sequence=sequence,
                sample_count=num_samples,
            )
        return SimpleFoldAdapterResult(
            samples=samples,
            effective_call_seed=derived_call_seed,
        )
