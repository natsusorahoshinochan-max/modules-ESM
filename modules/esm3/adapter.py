"""Exact Workbench-to-provider ESM-3 translation and result admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from core import (
    EngineInvocationProvenance,
    InvocationRandomness,
    RunResources,
)
from datatypes import (
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
)


ESM_SDK_REVISION = "917af90b624535eed1e072d343c717e3ec11fef4"
BIOHUB_ESM3_MEDIUM_MODEL = "esm3-medium-2024-08"
BIOHUB_ESM3_OPEN_MODEL = "esm3-open-2024-03"
_ATOM37_INDEX = {
    atom_name: index
    for index, atom_name in enumerate(
        (
            "N",
            "CA",
            "C",
            "CB",
            "O",
            "CG",
            "CG1",
            "CG2",
            "OG",
            "OG1",
            "SG",
            "CD",
            "CD1",
            "CD2",
            "ND1",
            "ND2",
            "OD1",
            "OD2",
            "SD",
            "CE",
            "CE1",
            "CE2",
            "CE3",
            "NE",
            "NE1",
            "NE2",
            "OE1",
            "OE2",
            "CH2",
            "NH1",
            "NH2",
            "OH",
            "CZ",
            "CZ2",
            "CZ3",
            "NZ",
            "OXT",
        )
    )
}
_PROVIDER_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYXBZUO")


@dataclass(frozen=True, slots=True)
class ESM3CallParameters:
    """Provider-independent scientific parameters for one track call."""

    num_steps: int
    temperature: float
    top_p: float
    schedule: str
    strategy: str
    temperature_annealing: bool


@dataclass(frozen=True, slots=True)
class ESM3Confidence:
    """Canonical confidence values admitted from one structure response."""

    ptm: float
    plddt_per_residue: tuple[float, ...]
    pae: tuple[tuple[float, ...], ...] | None


@dataclass(frozen=True, slots=True)
class ESM3SequenceResult:
    """Provider-independent result of one sequence-track invocation."""

    sequence: ProteinSequence
    reconstruction: ProteinStructure | None
    confidence: ESM3Confidence | None
    effective_num_steps: int
    effective_call_seed: int | None


@dataclass(frozen=True, slots=True)
class ESM3StructureResult:
    """Provider-independent result of one structure-track invocation."""

    sequence: ProteinSequence
    structure: ProteinStructure
    confidence: ESM3Confidence
    effective_num_steps: int
    effective_call_seed: int | None


@dataclass(frozen=True, slots=True)
class ESM3PairResult:
    """One terminal sequence and its exact sampled structure counterpart."""

    sequence: ESM3SequenceResult
    structure: ESM3StructureResult


class ESM3GenerationAdapter(Protocol):
    """The package seam implemented by Biohub and local-open Adapters."""

    def __enter__(self) -> ESM3GenerationAdapter: ...

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None: ...

    def generate_sequence(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        derived_call_seed: int | None,
    ) -> ESM3SequenceResult: ...

    def generate_structure(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        derived_call_seed: int | None,
    ) -> ESM3StructureResult: ...

    def generate_pair(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        sequence_derived_call_seed: int | None,
        structure_derived_call_seed: int | None,
    ) -> ESM3PairResult: ...


def _sequence_track(prompt: ProteinPrompt) -> str:
    values = (
        [None] * prompt.num_residues
        if prompt.sequence_track is None
        else prompt.sequence_track.values
    )
    symbols: list[str] = []
    for position, value in enumerate(values):
        if value is None:
            symbols.append("_")
            continue
        if value not in _PROVIDER_SEQUENCE_ALPHABET:
            raise ValueError(
                f"ESM-3 cannot represent sequence symbol {value!r} "
                f"at residue {position}"
            )
        symbols.append(value)
    return "".join(symbols)


def _secondary_structure_track(
    prompt: ProteinPrompt,
) -> str | None:
    if prompt.secondary_structure_track is None:
        return None
    symbols: list[str] = []
    for value in prompt.secondary_structure_track.values:
        if value is None:
            symbols.append("_")
            continue
        if value == "-":
            symbols.append("C")
            continue
        symbols.append(value)
    return "".join(symbols)


def _sasa_track(prompt: ProteinPrompt) -> list[float | None] | None:
    if prompt.sasa_track is None:
        return None
    return [
        None if value is None else float(value)
        for value in prompt.sasa_track.values
    ]


def _coordinates(prompt: ProteinPrompt) -> Any | None:
    if prompt.structure_track is None:
        return None
    import torch

    visibility = (
        [True] * prompt.num_residues
        if prompt.structure_visibility_track is None
        else [
            value is True
            for value in prompt.structure_visibility_track.values
        ]
    )
    coordinates = torch.full(
        (prompt.num_residues, 37, 3),
        float("nan"),
        dtype=torch.float32,
    )
    any_visible_atom = False
    for position, residue in enumerate(prompt.structure_track.values):
        is_visible = visibility[position]
        if residue is None or not is_visible:
            continue
        for atom_name, raw_coordinate in residue.items():
            atom_index = _ATOM37_INDEX.get(atom_name)
            if atom_index is None:
                raise ValueError(
                    f"ESM-3 atom37 cannot represent atom {atom_name!r} "
                    f"at residue {position}"
                )
            coordinates[position, atom_index] = torch.tensor(
                raw_coordinate,
                dtype=torch.float32,
            )
            any_visible_atom = True
    return coordinates if any_visible_atom else None


def _function_annotations(prompt: ProteinPrompt) -> list[Any] | None:
    if not prompt.function_annotations.annotations:
        return None
    from esm.utils.types import FunctionAnnotation as ProviderFunctionAnnotation

    result: list[Any] = []
    for annotation in prompt.function_annotations.annotations:
        result.append(
            ProviderFunctionAnnotation(
                label=annotation.label,
                start=annotation.start,
                end=annotation.end,
            )
        )
    return result


def protein_prompt_to_provider(prompt: ProteinPrompt) -> Any:
    """Translate one exact ProteinPrompt without silently mutating tracks."""
    if "," in prompt.target_layout.chain_id:
        raise ValueError(
            "The locked ESM SDK cannot preserve multi-chain aligned tracks"
        )
    from esm.sdk.api import ESMProtein

    return ESMProtein(
        sequence=_sequence_track(prompt),
        secondary_structure=_secondary_structure_track(prompt),
        sasa=_sasa_track(prompt),
        function_annotations=_function_annotations(prompt),
        coordinates=_coordinates(prompt),
    )


def generation_config(
    track: str,
    parameters: ESM3CallParameters,
) -> Any:
    """Build only the exact provider operation declared by the Node Type."""
    from esm.sdk.api import GenerationConfig

    return GenerationConfig(
        track=track,
        num_steps=parameters.num_steps,
        temperature=parameters.temperature,
        top_p=parameters.top_p,
        schedule=parameters.schedule,
        strategy=parameters.strategy,
        temperature_annealing=parameters.temperature_annealing,
        condition_on_coordinates_only=True,
    )


def require_provider_protein(result: Any, operation: str) -> Any:
    """Reject provider error values before post-processing."""
    from esm.sdk.api import ESMProteinError

    if isinstance(result, ESMProteinError):
        raise RuntimeError(
            f"ESM-3 provider operation {operation} failed with a provider error"
        ) from result
    return result


def call_remote_provider(
    client: Any,
    protein: Any,
    config: Any,
    operation: str,
) -> Any:
    """Cross only the remote engine boundary and classify its return."""
    from esm.sdk.api import ESMProteinError

    try:
        result = client.generate(protein, config)
    except ESMProteinError as error:
        raise RuntimeError(
            f"ESM-3 provider operation {operation} failed"
        ) from error
    return require_provider_protein(result, operation)


def complete_sequence(
    result: Any,
    prompt: ProteinPrompt,
) -> ProteinSequence:
    """Translate the documented provider sequence onto the Prompt axis."""
    layout = prompt.target_layout
    return ProteinSequence(
        sequence=result.sequence,
        residue_ids=list(layout.residue_ids),
    )


def response_has_structure(result: Any) -> bool:
    return result.coordinates is not None


def complete_structure(
    result: Any,
) -> ProteinStructure:
    """Translate SDK PDB serialization to the canonical terminal record."""
    return ProteinStructure(pdb_string=result.to_pdb_string())


def biohub_confidence(
    result: Any,
) -> ESM3Confidence:
    """Translate the fixed Biohub scalar-pTM and residue-axis tensors."""
    ptm = float(result.ptm.detach().cpu().item())
    plddt = tuple(
        float(value) * 100.0
        for value in result.plddt.detach().cpu().tolist()
    )
    pae = (
        None
        if result.pae is None
        else tuple(
            tuple(float(value) for value in row)
            for row in result.pae.detach().cpu().tolist()
        )
    )
    return ESM3Confidence(ptm=ptm, plddt_per_residue=plddt, pae=pae)


def structure_prompt_for_sequence(
    provider_prompt: Any,
    sequence: str,
) -> Any:
    """Preserve every non-structure condition for one paired structure call."""
    from esm.sdk.api import ESMProtein

    return ESMProtein(
        sequence=sequence,
        secondary_structure=provider_prompt.secondary_structure,
        sasa=provider_prompt.sasa,
        function_annotations=provider_prompt.function_annotations,
        coordinates=provider_prompt.coordinates,
    )


class _BaseESM3Adapter:
    """Package-local Adapter implementation shared by the two real routes."""

    def __init__(
        self,
        *,
        resources: RunResources,
        model_name: str,
        exact_seed_control: bool,
    ) -> None:
        self._resources = resources
        self._model_name = model_name
        self._exact_seed_control = exact_seed_control

    def __enter__(self) -> _BaseESM3Adapter:
        return self

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        del exception_type, exception, traceback

    def _client(self) -> Any:
        raise NotImplementedError

    def _call_provider(
        self,
        client: Any,
        provider_prompt: Any,
        config: Any,
        provider_operation: str,
        *,
        effective_call_seed: int | None,
    ) -> Any:
        raise NotImplementedError

    def _admit_confidence(self, result: Any) -> ESM3Confidence:
        raise NotImplementedError

    def _invoke(
        self,
        provider_prompt: Any,
        config: Any,
        *,
        role: str,
        provider_operation: str,
        derived_call_seed: int | None,
        parent_invocation_id: str | None = None,
    ) -> tuple[Any, str, int, int | None]:
        client = self._client()
        effective_call_seed = (
            derived_call_seed if self._exact_seed_control else None
        )
        randomness = InvocationRandomness(
            control=(
                "exact_seed"
                if effective_call_seed is not None
                else "provider_uncontrolled"
            ),
            effective_seed=effective_call_seed,
        )
        with self._resources.engine_invocation(
            engine_role=role,
            parent_invocation_id=parent_invocation_id,
            invocation_provenance=EngineInvocationProvenance(
                effective_randomness=randomness
            ),
        ) as invocation_id:
            result = self._call_provider(
                client,
                provider_prompt,
                config,
                provider_operation,
                effective_call_seed=effective_call_seed,
            )
        effective_num_steps = config.num_steps
        return (
            result,
            invocation_id,
            effective_num_steps,
            effective_call_seed,
        )

    def _admit_sequence_result(
        self,
        prompt: ProteinPrompt,
        result: Any,
        effective_num_steps: int,
        effective_call_seed: int | None,
    ) -> ESM3SequenceResult:
        sequence = complete_sequence(result, prompt)
        reconstruction: ProteinStructure | None = None
        confidence: ESM3Confidence | None = None
        if response_has_structure(result):
            reconstruction = complete_structure(result)
            confidence = self._admit_confidence(result)
        return ESM3SequenceResult(
            sequence=sequence,
            reconstruction=reconstruction,
            confidence=confidence,
            effective_num_steps=effective_num_steps,
            effective_call_seed=effective_call_seed,
        )

    def _admit_structure_result(
        self,
        prompt: ProteinPrompt,
        result: Any,
        effective_num_steps: int,
        effective_call_seed: int | None,
    ) -> ESM3StructureResult:
        sequence = complete_sequence(result, prompt)
        return ESM3StructureResult(
            sequence=sequence,
            structure=complete_structure(result),
            confidence=self._admit_confidence(result),
            effective_num_steps=effective_num_steps,
            effective_call_seed=effective_call_seed,
        )

    def generate_sequence(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        derived_call_seed: int | None,
    ) -> ESM3SequenceResult:
        """Invoke and admit one sequence sample without leaking SDK values."""
        provider_prompt = protein_prompt_to_provider(prompt)
        result, _, effective_num_steps, effective_call_seed = self._invoke(
            provider_prompt,
            generation_config("sequence", parameters),
            role="sequence_sample",
            provider_operation="generate(track=sequence)",
            derived_call_seed=derived_call_seed,
        )
        return self._admit_sequence_result(
            prompt,
            result,
            effective_num_steps,
            effective_call_seed,
        )

    def generate_structure(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        derived_call_seed: int | None,
    ) -> ESM3StructureResult:
        """Invoke and admit one structure sample without leaking SDK values."""
        provider_prompt = protein_prompt_to_provider(prompt)
        result, _, effective_num_steps, effective_call_seed = self._invoke(
            provider_prompt,
            generation_config("structure", parameters),
            role="structure_sample",
            provider_operation="generate(track=structure)",
            derived_call_seed=derived_call_seed,
        )
        return self._admit_structure_result(
            prompt,
            result,
            effective_num_steps,
            effective_call_seed,
        )

    def generate_pair(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        sequence_derived_call_seed: int | None,
        structure_derived_call_seed: int | None,
    ) -> ESM3PairResult:
        """Invoke one causally linked sequence/structure provider pair."""
        provider_prompt = protein_prompt_to_provider(prompt)
        (
            sequence_response,
            sequence_invocation_id,
            sequence_effective_num_steps,
            sequence_effective_call_seed,
        ) = self._invoke(
            provider_prompt,
            generation_config("sequence", parameters),
            role="sequence_parent",
            provider_operation="generate(track=sequence)",
            derived_call_seed=sequence_derived_call_seed,
        )
        sequence = self._admit_sequence_result(
            prompt,
            sequence_response,
            sequence_effective_num_steps,
            sequence_effective_call_seed,
        )
        (
            structure_response,
            _,
            structure_effective_num_steps,
            structure_effective_call_seed,
        ) = self._invoke(
            structure_prompt_for_sequence(
                provider_prompt,
                sequence.sequence.sequence,
            ),
            generation_config("structure", parameters),
            role="structure_child",
            provider_operation="generate(track=structure)",
            derived_call_seed=structure_derived_call_seed,
            parent_invocation_id=sequence_invocation_id,
        )
        return ESM3PairResult(
            sequence=sequence,
            structure=self._admit_structure_result(
                prompt,
                structure_response,
                structure_effective_num_steps,
                structure_effective_call_seed,
            ),
        )


class BiohubESM3Adapter(_BaseESM3Adapter):
    """Translate canonical ESM-3 calls to one exact Biohub model."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
        model_name: str,
    ) -> None:
        super().__init__(
            resources=resources,
            model_name=model_name,
            exact_seed_control=False,
        )
        self._environment = environment
        self._resolved_client: Any | None = None

    def _client(self) -> Any:
        if self._resolved_client is not None:
            return self._resolved_client
        client = self._environment.get("provider_client")
        if client is not None:
            self._resolved_client = client
            return client
        client = self._environment["client_factory"](
            model_name=self._model_name,
            endpoint_id=self._environment["endpoint_id"],
            credential_handle=self._environment["credential_handle"],
        )
        self._resolved_client = client
        return client

    def _call_provider(
        self,
        client: Any,
        provider_prompt: Any,
        config: Any,
        provider_operation: str,
        *,
        effective_call_seed: int | None,
    ) -> Any:
        del effective_call_seed
        return call_remote_provider(
            client,
            provider_prompt,
            config,
            provider_operation,
        )

    def _admit_confidence(self, result: Any) -> ESM3Confidence:
        return biohub_confidence(result)
