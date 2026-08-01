"""Exact Workbench-to-Biohub ESM-3 translation and response validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any, Protocol

from core import RunResources
from datatypes import (
    FunctionAnnotation,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
)
from modules.prompt_authoring.prompts import validate_protein_prompt


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
_PROVIDER_SS8 = frozenset("GHITEBSC")
_PDB_TO_SEQUENCE = {
    "ALA": "A",
    "ARG": "R",
    "ASX": "B",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "GLX": "Z",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "PYL": "O",
    "SEC": "U",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "UNK": "X",
}


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
        derived_call_seed: int,
    ) -> ESM3SequenceResult: ...

    def generate_structure(
        self,
        prompt: ProteinPrompt,
        *,
        expected_sequence: str,
        parameters: ESM3CallParameters,
        derived_call_seed: int,
    ) -> ESM3StructureResult: ...

    def generate_pair(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        sequence_derived_call_seed: int,
        structure_derived_call_seed: int,
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
        if (
            type(value) is not str
            or value not in _PROVIDER_SEQUENCE_ALPHABET
        ):
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
    for position, value in enumerate(
        prompt.secondary_structure_track.values
    ):
        if value is None:
            symbols.append("_")
            continue
        if value == "-":
            symbols.append("C")
            continue
        if type(value) is not str or value not in _PROVIDER_SS8:
            raise ValueError(
                "ESM-3 cannot represent secondary-structure symbol "
                f"{value!r} at residue {position}"
            )
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
    for position, (residue, is_visible) in enumerate(
        zip(
            prompt.structure_track.values,
            visibility,
            strict=True,
        )
    ):
        if residue is None or not is_visible:
            continue
        if not isinstance(residue, Mapping):
            raise ValueError(
                f"ESM-3 structure residue {position} is not a named-atom map"
            )
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
        if type(annotation) is not FunctionAnnotation:
            raise ValueError(
                "ESM-3 function annotations must be canonical values"
            )
        result.append(
            ProviderFunctionAnnotation(
                label=annotation.label,
                start=annotation.start,
                end=annotation.end,
            )
        )
    return result


def protein_prompt_to_provider(prompt: object) -> Any:
    """Translate one exact ProteinPrompt without silently mutating tracks."""
    source = validate_protein_prompt(prompt)
    if "," in source.target_layout.chain_id:
        raise ValueError(
            "The locked ESM SDK cannot preserve multi-chain aligned tracks"
        )
    from esm.sdk.api import ESMProtein

    return ESMProtein(
        sequence=_sequence_track(source),
        secondary_structure=_secondary_structure_track(source),
        sasa=_sasa_track(source),
        function_annotations=_function_annotations(source),
        coordinates=_coordinates(source),
    )


def generation_config(
    track: str,
    parameters: Mapping[str, Any],
) -> Any:
    """Build only the exact provider operation declared by the Node Type."""
    if track not in {"sequence", "structure"}:
        raise ValueError("ESM-3 generation track is not declared")
    from esm.sdk.api import GenerationConfig

    return GenerationConfig(
        track=track,
        num_steps=parameters["num_steps"],
        temperature=parameters["temperature"],
        top_p=parameters["top_p"],
        schedule=parameters["schedule"],
        strategy=parameters["strategy"],
        temperature_annealing=parameters["temperature_annealing"],
        condition_on_coordinates_only=True,
    )


def require_sequence_mask(provider_prompt: Any) -> None:
    """Fail before a remote sequence call that the provider cannot sample."""
    sequence = getattr(provider_prompt, "sequence", None)
    if not isinstance(sequence, str) or "_" not in sequence:
        raise ValueError(
            "ESM-3 sequence generation requires at least one masked residue"
        )


def require_provider_protein(result: Any, operation: str) -> Any:
    """Reject provider error values before post-processing."""
    from esm.sdk.api import ESMProteinError

    if isinstance(result, ESMProteinError):
        raise RuntimeError(
            f"ESM-3 provider operation {operation} failed with a provider error"
        )
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
    """Validate one complete provider sequence on the exact Prompt axis."""
    sequence = getattr(result, "sequence", None)
    if not isinstance(sequence, str) or not sequence:
        raise ValueError("ESM-3 provider response has no complete sequence")
    if (
        len(sequence) != prompt.num_residues
        or any(
            symbol not in _PROVIDER_SEQUENCE_ALPHABET
            for symbol in sequence
        )
    ):
        raise ValueError(
            "ESM-3 provider sequence is incomplete or misaligned"
        )
    layout = prompt.target_layout
    assert layout is not None and layout.residue_ids is not None
    return ProteinSequence(
        sequence=sequence,
        residue_ids=list(layout.residue_ids),
    )


def response_has_structure(result: Any) -> bool:
    return getattr(result, "coordinates", None) is not None


def reject_silent_sequence_fields(result: Any) -> None:
    """Do not discard confidence without a corresponding structure output."""
    if response_has_structure(result):
        return
    unexpected = [
        name
        for name in ("ptm", "plddt", "pae")
        if getattr(result, name, None) is not None
    ]
    if unexpected:
        raise ValueError(
            "ESM-3 sequence response contains confidence without structure"
        )


def complete_structure(
    result: Any,
    prompt: ProteinPrompt,
    *,
    expected_sequence: str,
) -> ProteinStructure:
    """Validate provider coordinates and serialized residues before publication."""
    sequence = complete_sequence(result, prompt).sequence
    if sequence != expected_sequence:
        raise ValueError(
            "ESM-3 structure response is not the exact requested sequence"
        )
    coordinates = getattr(result, "coordinates", None)
    try:
        shape = tuple(coordinates.shape)
    except (AttributeError, TypeError) as error:
        raise ValueError(
            "ESM-3 structure response has no coordinate tensor"
        ) from error
    if shape != (prompt.num_residues, 37, 3):
        raise ValueError(
            "ESM-3 coordinates do not match the exact atom37 residue axis"
        )
    try:
        import torch

        backbone = coordinates[:, (0, 1, 2), :]
        complete_backbone = bool(torch.isfinite(backbone).all())
    except (AttributeError, IndexError, TypeError) as error:
        raise ValueError("ESM-3 coordinates are not a valid tensor") from error
    if not complete_backbone:
        raise ValueError(
            "ESM-3 structure response lacks complete N, CA, and C coordinates"
        )
    try:
        pdb_string = result.to_pdb_string()
    except Exception as error:
        raise ValueError(
            "ESM-3 structure response could not be serialized"
        ) from error
    if not isinstance(pdb_string, str) or not pdb_string.strip():
        raise ValueError("ESM-3 structure response has no PDB text")
    residues: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in pdb_string.splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27:
            continue
        identity = (line[21], line[22:26], line[26])
        if identity in seen:
            continue
        seen.add(identity)
        residue_name = line[17:20].strip()
        symbol = _PDB_TO_SEQUENCE.get(residue_name)
        if symbol is None:
            raise ValueError(
                "ESM-3 PDB contains an unsupported protein residue"
            )
        residues.append((*identity, symbol))
    if (
        len(residues) != prompt.num_residues
        or "".join(residue[3] for residue in residues) != sequence
    ):
        raise ValueError(
            "ESM-3 PDB residue identities contradict the response sequence"
        )
    return ProteinStructure(pdb_string=pdb_string)


def normalized_confidence(
    result: Any,
    *,
    residue_count: int,
) -> tuple[float, list[float], list[list[float]] | None]:
    """Normalize only exact documented ESM-3 confidence shapes."""
    import torch

    raw_ptm = getattr(result, "ptm", None)
    if isinstance(raw_ptm, torch.Tensor):
        if tuple(raw_ptm.shape) == ():
            ptm = float(raw_ptm.detach().cpu().item())
        elif tuple(raw_ptm.shape) == (1,):
            ptm = float(raw_ptm.detach().cpu()[0].item())
        else:
            raise ValueError("ESM-3 pTM has an undocumented shape")
    elif (
        isinstance(raw_ptm, (int, float))
        and not isinstance(raw_ptm, bool)
    ):
        ptm = float(raw_ptm)
    else:
        raise ValueError("ESM-3 structure response has no scalar pTM")
    if not math.isfinite(ptm) or not 0 <= ptm <= 1:
        raise ValueError("ESM-3 pTM is outside its native [0, 1] scale")

    raw_plddt = getattr(result, "plddt", None)
    if (
        not isinstance(raw_plddt, torch.Tensor)
        or tuple(raw_plddt.shape) != (residue_count,)
        or not bool(torch.isfinite(raw_plddt).all())
        or bool((raw_plddt < 0).any())
        or bool((raw_plddt > 1).any())
    ):
        raise ValueError(
            "ESM-3 pLDDT must be one native [0, 1] value per residue"
        )
    per_residue = [
        float(value) * 100.0
        for value in raw_plddt.detach().cpu().tolist()
    ]
    raw_pae = getattr(result, "pae", None)
    pae: list[list[float]] | None = None
    if raw_pae is not None:
        if not isinstance(raw_pae, torch.Tensor):
            raise ValueError("ESM-3 PAE is not a tensor")
        shape = tuple(raw_pae.shape)
        if shape == (residue_count, residue_count):
            normalized = raw_pae.detach().cpu()
        elif shape == (1, residue_count + 2, residue_count + 2):
            normalized = raw_pae.detach().cpu()[0, 1:-1, 1:-1]
        else:
            raise ValueError("ESM-3 PAE has an undocumented shape")
        if (
            not bool(torch.isfinite(normalized).all())
            or bool((normalized < 0).any())
            or bool((normalized > 31.75).any())
        ):
            raise ValueError(
                "ESM-3 PAE is outside the locked angstrom scale"
            )
        pae = [
            [float(value) for value in row]
            for row in normalized.tolist()
        ]
    return ptm, per_residue, pae


def structure_prompt_for_sequence(
    provider_prompt: Any,
    sequence: str,
) -> Any:
    """Preserve every non-structure condition for one paired structure call."""
    from esm.sdk.api import ESMProtein

    return ESMProtein(
        sequence=sequence,
        secondary_structure=getattr(
            provider_prompt,
            "secondary_structure",
            None,
        ),
        sasa=getattr(provider_prompt, "sasa", None),
        function_annotations=getattr(
            provider_prompt,
            "function_annotations",
            None,
        ),
        coordinates=getattr(provider_prompt, "coordinates", None),
    )


def _call_parameter_values(
    parameters: ESM3CallParameters,
) -> dict[str, Any]:
    if type(parameters) is not ESM3CallParameters:
        raise ValueError("ESM-3 Adapter requires exact call parameters")
    return {
        "num_steps": parameters.num_steps,
        "temperature": parameters.temperature,
        "top_p": parameters.top_p,
        "schedule": parameters.schedule,
        "strategy": parameters.strategy,
        "temperature_annealing": parameters.temperature_annealing,
    }


def _admit_confidence(result: Any, residue_count: int) -> ESM3Confidence:
    ptm, per_residue, pae = normalized_confidence(
        result,
        residue_count=residue_count,
    )
    return ESM3Confidence(
        ptm=ptm,
        plddt_per_residue=tuple(per_residue),
        pae=(
            None
            if pae is None
            else tuple(tuple(row) for row in pae)
        ),
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

    def _invoke(
        self,
        provider_prompt: Any,
        config: Any,
        *,
        role: str,
        operation: str,
        derived_call_seed: int,
        parent_invocation_id: str | None = None,
    ) -> tuple[Any, str, int, int | None]:
        provider_operation = {
            "generate_sequence": "generate(track=sequence)",
            "generate_structure": "generate(track=structure)",
        }[operation]
        client = self._client()
        effective_call_seed = (
            derived_call_seed if self._exact_seed_control else None
        )
        randomness: dict[str, Any] = {
            "control": (
                "exact_seed"
                if effective_call_seed is not None
                else "provider_uncontrolled"
            )
        }
        if effective_call_seed is not None:
            randomness["effective_seed"] = effective_call_seed
        with self._resources.engine_invocation(
            engine_role=role,
            parent_invocation_id=parent_invocation_id,
            invocation_provenance={"effective_randomness": randomness},
        ) as invocation_id:
            result = self._call_provider(
                client,
                provider_prompt,
                config,
                provider_operation,
                effective_call_seed=effective_call_seed,
            )
        effective_num_steps = getattr(config, "num_steps", None)
        if type(effective_num_steps) is not int or effective_num_steps < 1:
            raise RuntimeError(
                "ESM-3 provider left an invalid effective num_steps"
            )
        return (
            result,
            invocation_id,
            effective_num_steps,
            effective_call_seed,
        )

    def _admit_sequence_result(
        self,
        prompt: ProteinPrompt,
        provider_prompt: Any,
        result: Any,
        effective_num_steps: int,
        effective_call_seed: int | None,
    ) -> ESM3SequenceResult:
        sequence = complete_sequence(result, prompt)
        reconstruction: ProteinStructure | None = None
        confidence: ESM3Confidence | None = None
        if response_has_structure(result):
            if getattr(provider_prompt, "coordinates", None) is None:
                raise ValueError(
                    "sequence generation returned structure fields without "
                    "coordinate-conditioned input"
                )
            reconstruction = complete_structure(
                result,
                prompt,
                expected_sequence=sequence.sequence,
            )
            confidence = _admit_confidence(result, len(sequence.sequence))
        else:
            reject_silent_sequence_fields(result)
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
        *,
        expected_sequence: str,
    ) -> ESM3StructureResult:
        return ESM3StructureResult(
            structure=complete_structure(
                result,
                prompt,
                expected_sequence=expected_sequence,
            ),
            confidence=_admit_confidence(result, prompt.num_residues),
            effective_num_steps=effective_num_steps,
            effective_call_seed=effective_call_seed,
        )

    def generate_sequence(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        derived_call_seed: int,
    ) -> ESM3SequenceResult:
        """Invoke and admit one sequence sample without leaking SDK values."""
        provider_prompt = protein_prompt_to_provider(prompt)
        require_sequence_mask(provider_prompt)
        result, _, effective_num_steps, effective_call_seed = self._invoke(
            provider_prompt,
            generation_config(
                "sequence",
                _call_parameter_values(parameters),
            ),
            role="sequence_sample",
            operation="generate_sequence",
            derived_call_seed=derived_call_seed,
        )
        return self._admit_sequence_result(
            prompt,
            provider_prompt,
            result,
            effective_num_steps,
            effective_call_seed,
        )

    def generate_structure(
        self,
        prompt: ProteinPrompt,
        *,
        expected_sequence: str,
        parameters: ESM3CallParameters,
        derived_call_seed: int,
    ) -> ESM3StructureResult:
        """Invoke and admit one structure sample without leaking SDK values."""
        provider_prompt = protein_prompt_to_provider(prompt)
        result, _, effective_num_steps, effective_call_seed = self._invoke(
            provider_prompt,
            generation_config(
                "structure",
                _call_parameter_values(parameters),
            ),
            role="structure_sample",
            operation="generate_structure",
            derived_call_seed=derived_call_seed,
        )
        return self._admit_structure_result(
            prompt,
            result,
            effective_num_steps,
            effective_call_seed,
            expected_sequence=expected_sequence,
        )

    def generate_pair(
        self,
        prompt: ProteinPrompt,
        *,
        parameters: ESM3CallParameters,
        sequence_derived_call_seed: int,
        structure_derived_call_seed: int,
    ) -> ESM3PairResult:
        """Invoke one causally linked sequence/structure provider pair."""
        provider_prompt = protein_prompt_to_provider(prompt)
        require_sequence_mask(provider_prompt)
        (
            sequence_response,
            sequence_invocation_id,
            sequence_effective_num_steps,
            sequence_effective_call_seed,
        ) = self._invoke(
            provider_prompt,
            generation_config(
                "sequence",
                _call_parameter_values(parameters),
            ),
            role="sequence_parent",
            operation="generate_sequence",
            derived_call_seed=sequence_derived_call_seed,
        )
        sequence = self._admit_sequence_result(
            prompt,
            provider_prompt,
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
            generation_config(
                "structure",
                _call_parameter_values(parameters),
            ),
            role="structure_child",
            operation="generate_structure",
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
                expected_sequence=sequence.sequence.sequence,
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
        if model_name not in {
            BIOHUB_ESM3_MEDIUM_MODEL,
            BIOHUB_ESM3_OPEN_MODEL,
        }:
            raise ValueError("Biohub ESM-3 model identity is not exact")
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
        if callable(getattr(client, "generate", None)):
            self._resolved_client = client
            return client
        client_factory = self._environment.get("client_factory")
        if callable(client_factory):
            client = client_factory(
                model_name=self._model_name,
                endpoint_id=self._environment["endpoint_id"],
                credential_handle=self._environment["credential_handle"],
            )
            self._resolved_client = client
            return client
        raise RuntimeError(
            "remote ESM-3 requires an injected provider client or client "
            "factory"
        )

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
