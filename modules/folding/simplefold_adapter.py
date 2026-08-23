"""Exact local SimpleFold folding boundary for the shared folding package."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, Protocol, TypedDict, TypeAlias

from core.operation import (
    OperationResources,
    EngineInvocationProvenance,
    InvocationRandomness,
    ReadinessResult,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure

from . import simplefold_contract
from .simplefold_asset_closure import (
    SimpleFoldAssetClosureAdmissionError,
    admit_simplefold_provider_asset_closure,
    bind_simplefold_provider_asset_closure,
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


@dataclass(frozen=True, slots=True)
class SimpleFoldAdapterResult:
    """Complete canonical samples and actual effective call randomness."""

    samples: tuple[SimpleFoldSampleResult, ...]
    effective_call_seed: int


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
    provider_sentinel = "\n" + " " * 80
    if not structure.pdb_string.endswith(provider_sentinel):
        raise ValueError("SimpleFold PDB lacks its exact padded sentinel")
    return ProteinStructure(
        structure.pdb_string.removesuffix(provider_sentinel) + "\n"
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
    if environment["device"] != simplefold_contract.SIMPLEFOLD_DEVICE:
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
        for entry in sorted(scores, key=lambda item: item["sample_index"])
    )


class LocalSimpleFoldAdapter:
    """Translate canonical folding values through exact local SimpleFold."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

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
            bound_closure = bind_simplefold_provider_asset_closure(
                simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
                self._environment,
            )
            from .simplefold_runtime import fold_sequence

            with self._resources.engine_invocation(
                engine_role=engine_role,
                invocation_provenance=EngineInvocationProvenance(
                    effective_randomness=InvocationRandomness(
                        control="exact_seed",
                        effective_seed=derived_call_seed,
                    )
                ),
            ):
                raw_result = cast(
                    _SimpleFoldNativeResult,
                    fold_sequence(
                        sequence=sequence,
                        num_steps=num_steps,
                        num_samples=num_samples,
                        staging_directory=staging_directory,
                        effective_seed=derived_call_seed,
                        staged_model_root=bound_closure.group_root(
                            "simplefold_models"
                        ),
                        staged_esm2_source_root=bound_closure.group_root(
                            "esm2_source"
                        ),
                        staged_esm2_model_root=bound_closure.group_root(
                            "esm2_models"
                        ),
                    ),
                )
            samples = _decode_fold_result(
                raw_result=raw_result,
            )
        return SimpleFoldAdapterResult(
            samples=samples,
            effective_call_seed=derived_call_seed,
        )
