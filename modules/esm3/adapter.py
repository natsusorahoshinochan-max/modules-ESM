"""Exact Workbench-to-provider ESM-3 translation and result admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import struct
from typing import Any, Literal, Protocol

from core.catalog.canonical import canonical_sha256
from core.operation import (
    OperationResources,
    EngineInvocationProvenance,
    InvocationRandomness,
)
from datatypes.prompt import FunctionAnnotation, ProteinPrompt
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


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


def build_biohub_esm3_client(
    *,
    model_name: str,
    credential_handle: object,
) -> Any:
    """Construct the configured SDK client from trusted deployment values."""
    from esm.sdk import client

    return client(
        model=model_name,
        url="https://biohub.ai",
        token=credential_handle,
        request_timeout=150,
    )


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
        base_seed: int | None,
        sample_index: int,
    ) -> ESM3SequenceResult: ...

    def generate_structure(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        base_seed: int | None,
        sample_index: int,
    ) -> ESM3StructureResult: ...

    def generate_pair(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        base_seed: int | None,
        sample_index: int,
    ) -> ESM3PairResult: ...


def _provider_sequence(prompt: ProteinPrompt) -> str:
    symbols: list[str] = []
    for position, value in enumerate(prompt.sequence):
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


def _provider_secondary_structure(
    prompt: ProteinPrompt,
) -> str | None:
    if prompt.secondary_structure is None:
        return None
    symbols: list[str] = []
    for value in prompt.secondary_structure:
        if value is None:
            symbols.append("_")
            continue
        symbols.append(value)
    return "".join(symbols)


def _provider_sasa(prompt: ProteinPrompt) -> tuple[float | None, ...] | None:
    if prompt.sasa is None:
        return None
    return tuple(
        None if value is None else float(value)
        for value in prompt.sasa
    )


def _atom37_entries(
    prompt: ProteinPrompt,
) -> tuple[tuple[int, int, tuple[float, float, float]], ...]:
    entries: list[tuple[int, int, tuple[float, float, float]]] = []
    for position, residue in enumerate(prompt.coordinates):
        if residue is None:
            continue
        for atom_name, raw_coordinate in residue.atoms:
            atom_index = _ATOM37_INDEX.get(atom_name)
            if atom_index is None:
                continue
            entries.append(
                (
                    position,
                    atom_index,
                    tuple(float(value) for value in raw_coordinate),
                )
            )
    return tuple(sorted(entries))


def _function_annotation_provider_interval(
    prompt: ProteinPrompt,
    annotation: FunctionAnnotation,
) -> tuple[int, int]:
    """Resolve identity-addressed annotation bounds to provider indices.

    Provider FunctionAnnotation uses one-based inclusive integer bounds. The
    bounds are looked up in the prompt layout; an absent identity is an
    internal invariant violation (the aggregate validator guarantees
    membership), so it fails fast.
    """
    residue_ids = prompt.layout.residue_ids
    try:
        start = residue_ids.index(annotation.start_residue_id) + 1
    except ValueError:
        raise ValueError(
            f"function annotation start residue "
            f"{annotation.start_residue_id!r} is absent from the prompt layout"
        )
    try:
        end = residue_ids.index(annotation.end_residue_id) + 1
    except ValueError:
        raise ValueError(
            f"function annotation end residue "
            f"{annotation.end_residue_id!r} is absent from the prompt layout"
        )
    return start, end


@dataclass(frozen=True, slots=True)
class _ConditioningProjection:
    """One immutable ESM-3 view feeding identity and SDK input encodings."""

    sequence: str
    secondary_structure: str | None
    sasa: tuple[float | None, ...] | None
    function_annotations: tuple[tuple[str, int, int], ...]
    atom37_entries: tuple[tuple[int, int, tuple[float, float, float]], ...]

    @classmethod
    def from_prompt(cls, prompt: ProteinPrompt) -> _ConditioningProjection:
        if len(prompt.layout.chain_ids) > 1:
            raise ValueError(
                "The ESM SDK cannot preserve multi-chain aligned tracks"
            )
        return cls(
            sequence=_provider_sequence(prompt),
            secondary_structure=_provider_secondary_structure(prompt),
            sasa=_provider_sasa(prompt),
            function_annotations=tuple(
                (annotation.label, *_function_annotation_provider_interval(
                    prompt, annotation,
                ))
                for annotation in prompt.function_annotations
            ),
            atom37_entries=_atom37_entries(prompt),
        )

    def functional_input_digest(self) -> str:
        """Retain the exact scientific input encoding used by call randomness."""
        return canonical_sha256(
            {
                "schema_namespace": "protein-workbench-esm3-functional-input/v1",
                "sequence": self.sequence,
                "secondary_structure": self.secondary_structure,
                "sasa_float64": (
                    None if self.sasa is None else [
                        None if value is None else struct.pack("!d", value).hex()
                        for value in self.sasa
                    ]
                ),
                "function_annotations": [
                    {"label": label, "start": start, "end": end}
                    for label, start, end in self.function_annotations
                ],
                "atom37_float32": (
                    None if not self.atom37_entries else [
                        {
                            "position": position,
                            "atom_index": atom_index,
                            "coordinate": [
                                struct.pack("!f", value).hex()
                                for value in coordinate
                            ],
                        }
                        for position, atom_index, coordinate in self.atom37_entries
                    ]
                ),
            }
        )

    def call_seed(
        self,
        base_seed: int | None,
        sample_index: int,
        track: Literal["sequence", "structure"],
    ) -> int | None:
        functional_input_digest = self.functional_input_digest()
        if base_seed is None:
            return None
        digest = hashlib.sha256(
            (
                "protein-workbench-esm3-call-seed/v2:"
                f"{base_seed}:{functional_input_digest}:{sample_index}:{track}"
            ).encode("ascii")
        ).digest()
        return int.from_bytes(digest[:6], "big")

    def provider_input(self) -> Any:
        """Encode a fresh SDK value without sharing mutable Provider state."""
        from esm.sdk.api import ESMProtein
        from esm.utils.types import FunctionAnnotation as ProviderFunctionAnnotation

        coordinates = None
        if self.atom37_entries:
            import torch

            coordinates = torch.full(
                (len(self.sequence), 37, 3), float("nan"), dtype=torch.float32,
            )
            for position, atom_index, coordinate in self.atom37_entries:
                coordinates[position, atom_index] = torch.tensor(
                    coordinate, dtype=torch.float32,
                )
        return ESMProtein(
            sequence=self.sequence,
            secondary_structure=self.secondary_structure,
            sasa=None if self.sasa is None else list(self.sasa),
            function_annotations=(
                [
                    ProviderFunctionAnnotation(label=label, start=start, end=end)
                    for label, start, end in self.function_annotations
                ]
                if self.function_annotations else None
            ),
            coordinates=coordinates,
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
    layout = prompt.layout
    return ProteinSequence(
        sequence=result.sequence,
        residue_ids=list(layout.residue_ids),
    )


def complete_structure(
    result: Any,
) -> ProteinStructure:
    """Translate the SDK PDB body to the canonical terminal record."""
    return ProteinStructure(pdb_string=f"{result.to_pdb_string()}END\n")


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


class _BaseESM3Adapter:
    """Package-local Adapter implementation shared by the two real routes."""

    def __init__(
        self,
        *,
        resources: OperationResources,
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
        if result.coordinates is not None:
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
        base_seed: int | None,
        sample_index: int,
    ) -> ESM3SequenceResult:
        """Invoke and admit one sequence sample without leaking SDK values."""
        conditioning = _ConditioningProjection.from_prompt(prompt)
        provider_prompt = conditioning.provider_input()
        result, _, effective_num_steps, effective_call_seed = self._invoke(
            provider_prompt,
            generation_config("sequence", parameters),
            role="sequence_sample",
            provider_operation="generate(track=sequence)",
            derived_call_seed=conditioning.call_seed(
                base_seed, sample_index, "sequence",
            ),
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
        base_seed: int | None,
        sample_index: int,
    ) -> ESM3StructureResult:
        """Invoke and admit one structure sample without leaking SDK values."""
        conditioning = _ConditioningProjection.from_prompt(prompt)
        provider_prompt = conditioning.provider_input()
        result, _, effective_num_steps, effective_call_seed = self._invoke(
            provider_prompt,
            generation_config("structure", parameters),
            role="structure_sample",
            provider_operation="generate(track=structure)",
            derived_call_seed=conditioning.call_seed(
                base_seed, sample_index, "structure",
            ),
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
        base_seed: int | None,
        sample_index: int,
    ) -> ESM3PairResult:
        """Invoke one causally linked sequence/structure provider pair."""
        conditioning = _ConditioningProjection.from_prompt(prompt)
        provider_prompt = conditioning.provider_input()
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
            derived_call_seed=conditioning.call_seed(
                base_seed, sample_index, "sequence",
            ),
        )
        sequence = self._admit_sequence_result(
            prompt,
            sequence_response,
            sequence_effective_num_steps,
            sequence_effective_call_seed,
        )
        structure_conditioning = replace(
            conditioning, sequence=sequence.sequence.sequence,
        )
        (
            structure_response,
            _,
            structure_effective_num_steps,
            structure_effective_call_seed,
        ) = self._invoke(
            structure_conditioning.provider_input(),
            generation_config("structure", parameters),
            role="structure_child",
            provider_operation="generate(track=structure)",
            derived_call_seed=structure_conditioning.call_seed(
                base_seed, sample_index, "structure",
            ),
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
        resources: OperationResources,
        model_name: str,
    ) -> None:
        super().__init__(
            resources=resources,
            model_name=model_name,
            exact_seed_control=False,
        )
        self._environment = environment
        self._resolved_client: Any | None = None

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        del exception_type, exception, traceback
        if self._resolved_client is not None:
            client = self._resolved_client
            self._resolved_client = None
            client.close()

    def _client(self) -> Any:
        if self._resolved_client is not None:
            return self._resolved_client
        client = build_biohub_esm3_client(
            model_name=self._model_name,
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
