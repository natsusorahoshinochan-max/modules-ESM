"""Concrete local Adapter for the pinned ProteinMPNN provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import importlib.metadata
import os
from pathlib import Path
from typing import Any, cast

from core.operation import (
    OperationResources,
    EngineInvocationProvenance,
    InvocationRandomness,
    ProviderResidueProjection,
    ProviderResidueProjectionEntry,
    ReadinessResult,
)
from modules.proteinmpnn.assets import proteinmpnn_provider_identity
from datatypes.sequence import ProteinSequence
from datatypes.structure import ResolvedStructureResidueAxis
from modules.proteinmpnn.domain import ProteinMPNNConstraints

from .provider_runtime import (
    ProteinMPNNDesignRequest,
    ProteinMPNNProvider,
    _LocalProteinMPNNProvider,
    _prepare_design_request,
    check_proteinmpnn_readiness,
)


PROTEINMPNN_MODEL = "v_48_020"
PROTEINMPNN_CHECKPOINT = "vanilla_model_weights/v_48_020.pt"
PROTEINMPNN_DEVICE = "cpu"
PROTEINMPNN_TORCH_VERSION = "2.13.0"
PROTEINMPNN_SCORING_SEED = 42
_PROVIDER_CHAIN_IDS = tuple(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)
_PROVIDER_BACKBONE_ATOMS = ("N", "CA", "C", "O")
_INSTALLED_GATE_RESIDENT_MODELS: dict[
    tuple[str, float, Path],
    tuple[Any, Any],
] = {}


@dataclass(frozen=True, slots=True)
class _ProviderStructureProjection:
    pdb_string: str
    workbench_chain_order: tuple[str, ...]
    provider_structure_chain_order: tuple[str, ...]
    residue_identity_mapping: tuple[tuple[str, int, str, int], ...]


def _provider_atom_line(
    *,
    serial: int,
    atom_name: str,
    residue_name: str,
    provider_chain_id: str,
    provider_position: int,
    coordinate: tuple[float, float, float] | None,
) -> str:
    x, y, z = coordinate or (float("nan"),) * 3
    return (
        f"ATOM  {serial:5d} {atom_name:^4} {residue_name:>3} "
        f"{provider_chain_id}{provider_position:5d}   "
        f"{x:8.3f}{y:8.3f}{z:8.3f}"
        f"{1.0:6.2f}{0.0:6.2f}          {atom_name[0]:>2}  "
    )


def _stage_provider_structure(
    residue_axis: ResolvedStructureResidueAxis,
) -> _ProviderStructureProjection:
    """Render every authoritative covalent segment as one provider chain."""
    workbench_chain_order = tuple(residue_axis.layout.chain_id.split(","))
    if len(residue_axis.segments) > len(_PROVIDER_CHAIN_IDS):
        raise ValueError("resolved residue axis has too many provider chains")
    provider_structure_chain_order = _PROVIDER_CHAIN_IDS[
        : len(residue_axis.segments)
    ]
    residue_name_by_id = dict(
        zip(
            cast(tuple[str, ...], residue_axis.layout.residue_ids),
            residue_axis.residue_names,
            strict=True,
        )
    )
    coordinates_by_residue = {
        residue.residue_id: {
            atom.atom_name: atom.coordinate
            for atom in residue.atom_coordinates
        }
        for residue in residue_axis.residue_coordinates
    }
    lines: list[str] = []
    mapping: list[tuple[str, int, str, int]] = []
    atom_serial = 0
    for segment, provider_chain in zip(
        residue_axis.segments,
        provider_structure_chain_order,
        strict=True,
    ):
        if lines:
            lines.append("TER")
        for provider_position, residue_id in enumerate(
            segment.residue_ids,
            start=1,
        ):
            mapping.append(
                (
                    residue_id,
                    segment.segment_index,
                    provider_chain,
                    provider_position,
                )
            )
            selected_coordinates = coordinates_by_residue[residue_id]
            for atom_name in _PROVIDER_BACKBONE_ATOMS:
                atom_serial = atom_serial % 99_999 + 1
                lines.append(
                    _provider_atom_line(
                        serial=atom_serial,
                        atom_name=atom_name,
                        residue_name=residue_name_by_id[residue_id],
                        provider_chain_id=provider_chain,
                        provider_position=provider_position,
                        coordinate=selected_coordinates.get(atom_name),
                    )
                )
    lines.extend(("TER", "END"))
    return _ProviderStructureProjection(
        pdb_string="\n".join(lines) + "\n",
        workbench_chain_order=workbench_chain_order,
        provider_structure_chain_order=provider_structure_chain_order,
        residue_identity_mapping=tuple(mapping),
    )


def proteinmpnn_readiness(
    environment: Mapping[str, Any],
) -> ReadinessResult:
    """Validate prerequisites without constructing or loading the model."""
    try:
        torch_version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    if torch_version != PROTEINMPNN_TORCH_VERSION:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    if environment.get("device") != PROTEINMPNN_DEVICE:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    provider_root = environment.get("provider_root")
    if not isinstance(provider_root, Path):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    readiness = check_proteinmpnn_readiness(
        provider_root,
    )
    if not readiness.ready:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="proteinmpnn_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def _provider_for_environment(
    environment: Mapping[str, Any],
    staging_directory: Path,
    model_cache: dict[tuple[str, float, Path], tuple[Any, Any]],
) -> ProteinMPNNProvider:
    """Resolve the declared provider seam without accepting Workflow paths."""
    return _LocalProteinMPNNProvider(
        temp_dir=staging_directory,
        provider_root=cast(Path, environment["provider_root"]),
        model_cache=model_cache,
    )


def _prepare_local_design_request(
    *,
    provider: ProteinMPNNProvider,
    residue_axis: ResolvedStructureResidueAxis,
    num_sequences: int,
    temperature: float,
    backbone_noise: float,
    seed: int,
    constraints: ProteinMPNNConstraints | None,
    reference_sequence: ProteinSequence | None,
) -> ProteinMPNNDesignRequest:
    """Translate admitted design inputs into one provider request."""
    projection = _stage_provider_structure(residue_axis)
    parsed = provider.parse_structure(projection.pdb_string)
    request = _prepare_design_request(
        parsed,
        PROTEINMPNN_MODEL,
        num_sequences,
        temperature,
        backbone_noise,
        seed,
        constraints,
        (
            reference_sequence.sequence
            if reference_sequence is not None
            else None
        ),
        target_layout=residue_axis.layout,
        residue_identity_mapping=projection.residue_identity_mapping,
        workbench_chain_order=projection.workbench_chain_order,
        provider_structure_chain_order=(
            projection.provider_structure_chain_order
        ),
    )
    omitted = list(request.omit_amino_acids)
    if "X" not in omitted:
        omitted.append("X")
    return replace(request, omit_amino_acids=omitted)


def _provider_residue_projection(
    request: ProteinMPNNDesignRequest,
) -> ProviderResidueProjection:
    """Project the exact Workbench layout used by one provider invocation."""
    return ProviderResidueProjection(
        workbench_chain_order=request.workbench_chain_order,
        provider_structure_chain_order=(
            request.provider_structure_chain_order
        ),
        provider_chain_order=request.provider_chain_order,
        entries=tuple(
            ProviderResidueProjectionEntry(
                residue_id=residue_id,
                segment_index=segment_index,
                provider_chain_id=provider_chain_id,
                provider_position=provider_position,
            )
            for (
                residue_id,
                segment_index,
                provider_chain_id,
                provider_position,
            ) in request.residue_identity_mapping
        ),
    )


def _restore_structure_chain_order(
    sequence: str,
    *,
    request: ProteinMPNNDesignRequest,
) -> str:
    chain_lengths = {
        chain: len(request.pdb_dict_list[0][f"seq_chain_{chain}"])
        for chain in request.provider_chain_order
    }
    provider_sequences: dict[str, str] = {}
    offset = 0
    for chain in request.provider_chain_order:
        chain_end = offset + chain_lengths[chain]
        provider_sequences[chain] = sequence[offset:chain_end]
        offset = chain_end
    return "".join(
        provider_sequences[provider_chain][provider_position - 1]
        for _, _, provider_chain, provider_position in (
            request.residue_identity_mapping
        )
    )


def _admit_design_result(
    raw_sequences: list[ProteinSequence],
    *,
    request: ProteinMPNNDesignRequest,
) -> list[ProteinSequence]:
    """Translate the one official design result into canonical sequences."""
    residue_ids = cast(tuple[str, ...], request.target_layout.residue_ids)
    sequences = [
        ProteinSequence(
            _restore_structure_chain_order(
                sequence.sequence,
                request=request,
            ),
            residue_ids,
        )
        for sequence in raw_sequences
    ]
    return sequences


def _prepare_local_scoring_request(
    *,
    provider: ProteinMPNNProvider,
    residue_axis: ResolvedStructureResidueAxis,
    sequence: ProteinSequence,
) -> ProteinMPNNDesignRequest:
    """Translate one admitted Candidate pair into the scoring request."""
    projection = _stage_provider_structure(residue_axis)
    parsed = provider.parse_structure(projection.pdb_string)
    request = _prepare_design_request(
        parsed,
        PROTEINMPNN_MODEL,
        1,
        0.1,
        0.0,
        PROTEINMPNN_SCORING_SEED,
        None,
        sequence.sequence,
        target_layout=residue_axis.layout,
        residue_identity_mapping=projection.residue_identity_mapping,
        workbench_chain_order=projection.workbench_chain_order,
        provider_structure_chain_order=(
            projection.provider_structure_chain_order
        ),
    )
    return request


class LocalProteinMPNNAdapter:
    """Translate canonical scientific values to one pinned local provider."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
        provider_factory: Callable[
            [
                Mapping[str, Any],
                Path,
                dict[tuple[str, float, Path], tuple[Any, Any]],
            ],
            ProteinMPNNProvider,
        ] = _provider_for_environment,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._provider_factory = provider_factory
        if (
            os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER")
            == "installed-proteinmpnn"
        ):
            self._resident_models = _INSTALLED_GATE_RESIDENT_MODELS
        else:
            self._resident_models: dict[
                tuple[str, float, Path],
                tuple[Any, Any],
            ] = {}

    def design(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        num_sequences: int,
        temperature: float,
        backbone_noise: float,
        seed: int,
        constraints: ProteinMPNNConstraints | None,
        reference_sequence: ProteinSequence | None,
        engine_role: str,
    ) -> tuple[ProteinSequence, ...]:
        """Run one design call and admit its provider-native result."""
        with self._resources.temporary_directory(
            prefix="proteinmpnn-design-"
        ) as staging_directory:
            provider = self._provider_factory(
                self._environment,
                staging_directory,
                self._resident_models,
            )
            request = _prepare_local_design_request(
                provider=provider,
                residue_axis=residue_axis,
                num_sequences=num_sequences,
                temperature=temperature,
                backbone_noise=backbone_noise,
                seed=seed,
                constraints=constraints,
                reference_sequence=reference_sequence,
            )
            with self._resources.engine_invocation(
                engine_role=engine_role,
                invocation_provenance=EngineInvocationProvenance(
                    effective_randomness=InvocationRandomness(
                        control="exact_seed",
                        effective_seed=seed,
                    ),
                    provider_residue_projection=(
                        _provider_residue_projection(request)
                    ),
                ),
            ):
                raw_sequences = provider.design(request)
            sequences = _admit_design_result(
                raw_sequences,
                request=request,
            )
        return tuple(sequences)

    def score(
        self,
        *,
        residue_axis: ResolvedStructureResidueAxis,
        sequence: ProteinSequence,
    ) -> float:
        """Run one exact sequence scoring call and admit its native scale."""
        with self._resources.temporary_directory(
            prefix="proteinmpnn-score-"
        ) as staging_directory:
            provider = self._provider_factory(
                self._environment,
                staging_directory,
                self._resident_models,
            )
            request = _prepare_local_scoring_request(
                provider=provider,
                residue_axis=residue_axis,
                sequence=sequence,
            )
            with self._resources.engine_invocation(
                engine_role="score_subject",
                invocation_provenance=EngineInvocationProvenance(
                    effective_randomness=InvocationRandomness(
                        control="exact_seed",
                        effective_seed=PROTEINMPNN_SCORING_SEED,
                    ),
                    provider_residue_projection=(
                        _provider_residue_projection(request)
                    ),
                ),
            ):
                return provider.score(request, sequence)

    def close(self) -> None:
        """Release operation-scoped resident models after the Operation."""
        if self._resident_models is not _INSTALLED_GATE_RESIDENT_MODELS:
            self._resident_models.clear()
