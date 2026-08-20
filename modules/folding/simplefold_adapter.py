"""Exact local SimpleFold folding boundary for the shared folding package."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, Protocol, TypedDict, TypeAlias

from core import (
    EngineInvocationProvenance,
    InvocationRandomness,
    ReadinessResult,
    RunResources,
)
from datatypes import ProteinSequence, ProteinStructure

from . import simplefold_contract
from .simplefold_asset_closure import (
    SimpleFoldAssetClosureAdmissionError,
    StagedSimpleFoldProviderAssetClosure,
    admit_simplefold_provider_asset_closure,
    stage_simplefold_provider_asset_closure,
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

    sample_index: int
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
    return (
        simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE
        .provider_identity()
    )


def simplefold_runtime_structurally_available() -> bool:
    """Probe import/install structure without importing or loading a model."""
    return not (
        importlib.util.find_spec("simplefold") is None
        or importlib.util.find_spec("torch") is None
    )


def simplefold_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    if environment.get("device") != simplefold_contract.SIMPLEFOLD_DEVICE:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="simplefold_runtime_unavailable",
        )
    try:
        admit_simplefold_provider_asset_closure(
            simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
            environment,
        )
    except SimpleFoldAssetClosureAdmissionError:
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
) -> tuple[SimpleFoldSampleResult, ...]:
    """Admit provider-native structures and high-level `[0,100]` scores."""
    structures, scores = raw_result
    return tuple(
        SimpleFoldSampleResult(
            sample_index=entry["sample_index"],
            structure=_translate_provider_structure(
                structures[entry["sample_index"]]
            ),
            per_residue_plddt=tuple(
                float(value) for value in entry["per_residue"]
            ),
        )
        for entry in scores
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
        staged_closure: StagedSimpleFoldProviderAssetClosure,
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
                        staging_directory=staged_closure.root,
                    ),
                )

            return invoke_client
        configured = {
            "model_root": staged_closure.group_root("simplefold_models"),
            "esm2_source_root": staged_closure.group_root("esm2_source"),
            "esm2_model_root": staged_closure.group_root("esm2_models"),
        }
        from .simplefold_runtime import fold_sequence

        def invoke_local_runtime() -> _SimpleFoldNativeResult:
            return cast(
                _SimpleFoldNativeResult,
                fold_sequence(
                    sequence=sequence,
                    model_name=simplefold_contract.SIMPLEFOLD_MODEL,
                    num_steps=num_steps,
                    num_samples=num_samples,
                    project_dir=str(staging_directory),
                    effective_seed=effective_seed,
                    staged_model_root=configured["model_root"],
                    staged_esm2_source_root=configured["esm2_source_root"],
                    staged_esm2_model_root=configured["esm2_model_root"],
                    required_device=simplefold_contract.SIMPLEFOLD_DEVICE,
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
            staged_closure = stage_simplefold_provider_asset_closure(
                simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
                self._environment,
                staging_directory,
            )
            provider_call = self._provider_call(
                sequence=sequence,
                num_steps=num_steps,
                num_samples=num_samples,
                effective_seed=derived_call_seed,
                staging_directory=staging_directory,
                staged_closure=staged_closure,
            )
            with self._resources.engine_invocation(
                engine_role=engine_role,
                invocation_provenance=EngineInvocationProvenance(
                    effective_randomness=InvocationRandomness(
                        control="exact_seed",
                        effective_seed=derived_call_seed,
                    )
                ),
            ):
                raw_result = provider_call()
            samples = _decode_fold_result(
                raw_result=raw_result,
            )
        return SimpleFoldAdapterResult(
            samples=samples,
            effective_call_seed=derived_call_seed,
        )
