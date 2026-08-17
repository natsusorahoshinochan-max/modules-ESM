"""Exact local SimpleFold folding boundary for the shared folding package."""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, Protocol, TypedDict, TypeAlias

from core import ReadinessResult, RunResources
from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
    simplefold_provider_identity,
    validate_installed_provider_checkout,
)
from datatypes import ProteinSequence, ProteinStructure
from .simplefold_contract import (
    SIMPLEFOLD_DEVICE,
    SIMPLEFOLD_MODEL,
    simplefold_folding_artifact_sha256,
)


class _SimpleFoldNativeScore(TypedDict):
    sample_index: int
    per_residue: list[float]


_SimpleFoldNativeResult: TypeAlias = tuple[
    list[ProteinStructure],
    list[_SimpleFoldNativeScore],
]


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


def _translate_provider_structure(structure: ProteinStructure) -> ProteinStructure:
    """Translate the pinned writer's padded sentinel into canonical PDB text."""
    lines = structure.pdb_string.split("\n")
    if (
        len(lines) < 2
        or lines[-2:] != ["END".ljust(80), " " * 80]
    ):
        raise ValueError(
            "SimpleFold provider PDB tail is outside the pinned source contract"
        )
    return ProteinStructure("\n".join(lines[:-1]) + "\n")


def simplefold_folding_provider_identity() -> dict[str, Any]:
    """Return evidence for only the assets actually used by this Binding."""
    return simplefold_provider_identity(
        simplefold_folding_artifact_sha256()
    )


def simplefold_runtime_structurally_available() -> bool:
    """Probe import/install structure without importing or loading a model."""
    return not (
        importlib.util.find_spec("simplefold") is None
        or importlib.util.find_spec("torch") is None
    )


def _sha256_file(path: Path, *, expected_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise RuntimeError(
            f"SimpleFold asset byte count mismatch: {path.name}"
        )
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_file_set(
    root: object,
    expected: Mapping[str, str],
    identities: Mapping[str, Mapping[str, Any]],
) -> Path:
    if not isinstance(root, Path) or not root.is_dir():
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
    raw_result: _SimpleFoldNativeResult,
    sample_count: int,
) -> tuple[SimpleFoldSampleResult, ...]:
    """Admit provider-native structures and high-level `[0,100]` scores."""
    structures, scores = raw_result
    by_sample = {
        entry["sample_index"]: tuple(
            float(value) for value in entry["per_residue"]
        )
        for entry in scores
    }
    return tuple(
        SimpleFoldSampleResult(
            structure=_translate_provider_structure(
                structures[sample_index]
            ),
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
    ) -> Callable[[], _SimpleFoldNativeResult]:
        client = self._environment.get("provider_client")
        if client is not None:
            def invoke_client() -> _SimpleFoldNativeResult:
                return cast(
                    _SimpleFoldNativeResult,
                    client.fold(
                        sequence=sequence,
                        num_steps=num_steps,
                        num_samples=num_samples,
                        effective_seed=effective_seed,
                        staging_directory=staging_directory,
                    ),
                )

            return invoke_client
        configured = {
            "model_root": cast(Path, self._environment["model_root"]),
            "esm2_source_root": cast(
                Path,
                self._environment["esm2_source_root"],
            ),
            "esm2_model_root": cast(
                Path,
                self._environment["esm2_model_root"],
            ),
        }
        from .simplefold_runtime import fold_sequence

        def invoke_local_runtime() -> _SimpleFoldNativeResult:
            return cast(
                _SimpleFoldNativeResult,
                fold_sequence(
                    sequence=sequence,
                    model_name=SIMPLEFOLD_MODEL,
                    num_steps=num_steps,
                    num_samples=num_samples,
                    project_dir=str(staging_directory),
                    effective_seed=effective_seed,
                    model_root=configured["model_root"],
                    esm2_source_root=configured["esm2_source_root"],
                    esm2_model_root=configured["esm2_model_root"],
                    required_device=SIMPLEFOLD_DEVICE,
                    record_evidence=False,
                ),
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
                sample_count=num_samples,
            )
        return SimpleFoldAdapterResult(
            samples=samples,
            effective_call_seed=derived_call_seed,
        )
