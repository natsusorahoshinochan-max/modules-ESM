"""Typed execution interface for one resolved scientific operation."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ContextManager, Literal, Protocol

from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)

if TYPE_CHECKING:
    from core.scoring.observation_plan import ResolvedProducedObservation
    from core.scoring.selection import (
        ResolvedObservationSelector,
        ResolvedSelectionObjective,
    )


PortMultiplicity = Literal["one", "many"]
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")


def _freeze_container(value: Any) -> Any:
    """Freeze caller-owned containers without changing scientific value types."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_container(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_container(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ArtifactPayload:
    """Exact artifact bytes returned by a scientific operation."""

    body: bytes
    media_type: str
    filename: str
    candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class InvocationRandomness:
    """Effective randomness observed at an engine boundary."""

    control: Literal["exact_seed", "provider_uncontrolled"]
    effective_seed: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderResidueProjectionEntry:
    """One Workbench-to-provider residue association."""

    residue_id: str
    segment_index: int
    provider_chain_id: str
    provider_position: int


@dataclass(frozen=True, slots=True)
class ProviderResidueProjection:
    """Chain order and residue mapping observed at a provider boundary."""

    workbench_chain_order: tuple[str, ...]
    provider_structure_chain_order: tuple[str, ...]
    provider_chain_order: tuple[str, ...]
    entries: tuple[ProviderResidueProjectionEntry, ...]
    position_semantics: Literal["one_based_chain_local"] = (
        "one_based_chain_local"
    )


@dataclass(frozen=True, slots=True)
class EngineInvocationProvenance:
    """Closed provenance supplied when an operation crosses an engine seam."""

    effective_randomness: InvocationRandomness | None = None
    project_input_filename: str | None = None
    provider_residue_projection: ProviderResidueProjection | None = None


@dataclass(frozen=True, slots=True)
class BindingEnvironment(Mapping[str, Any]):
    """Trusted private configuration for one exact execution Binding."""

    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.values, Mapping):
            raise TypeError("Binding Environment values must be a Mapping")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class ReadinessCheckInput:
    """Closed private checker input for one selected Binding."""

    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.values, Mapping):
            raise TypeError("Readiness values must be a Mapping")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """One direct readiness conclusion at an operation boundary."""

    passing: bool
    proof_source: str = "direct-observation"
    reason_code: str = "prerequisite_unavailable"

    def __post_init__(self) -> None:
        if type(self.passing) is not bool:
            raise TypeError("Readiness conclusion must be boolean")
        if any(
            not isinstance(value, str)
            or len(value) > 128
            or _PUBLIC_IDENTIFIER.fullmatch(value) is None
            for value in (self.proof_source, self.reason_code)
        ):
            raise ValueError("Readiness metadata must use public identifiers")


class OperationProjectInput(Protocol):
    """Project Input identity visible to a scientific operation."""

    @property
    def project_input_ref(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def size(self) -> int: ...

    @property
    def content_digest(self) -> str: ...


class OperationResources(Protocol):
    """Project- and Run-contained capabilities available to an operation."""

    project_id: str
    run_id: str
    node_id: str

    def read_project_input(
        self,
        input_reference: str,
    ) -> tuple[OperationProjectInput, bytes]: ...

    @property
    def result_identity_inputs(self) -> tuple[Mapping[str, Any], ...]: ...

    def temporary_directory(self, *, prefix: str) -> ContextManager[Path]: ...

    def cleanup_temporary_work(self) -> None: ...

    def cancellable_process_group(
        self,
        process_group: int,
        *,
        fallback: Callable[[], None] | None = None,
    ) -> ContextManager[None]: ...

    def engine_invocation(
        self,
        *,
        engine_role: str = "primary",
        parent_invocation_id: str | None = None,
        invocation_provenance: EngineInvocationProvenance | None = None,
    ) -> ContextManager[str]: ...


@dataclass(frozen=True, slots=True)
class AdmittedValue:
    """One immutable canonical value and every Port-owned projection."""

    value: Any
    canonical_bytes: bytes
    content_digest: str
    candidate_data: tuple[CandidateDataReference, ...] = ()
    scientific_axes: tuple[ResidueAxisReference, ...] = ()
    observation_methods: tuple[ExactContractReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze_container(self.value))
        object.__setattr__(self, "canonical_bytes", bytes(self.canonical_bytes))
        candidate_data = tuple(self.candidate_data)
        if any(
            type(reference) is not CandidateDataReference
            for reference in candidate_data
        ):
            raise TypeError(
                "candidate_data entries must be CandidateDataReference values"
            )
        object.__setattr__(self, "candidate_data", candidate_data)
        scientific_axes = tuple(self.scientific_axes)
        if any(
            type(reference) is not ResidueAxisReference
            for reference in scientific_axes
        ):
            raise TypeError(
                "scientific_axes entries must be ResidueAxisReference values"
            )
        object.__setattr__(self, "scientific_axes", scientific_axes)
        observation_methods = tuple(self.observation_methods)
        if any(
            type(reference) is not ExactContractReference
            or reference.contract_kind != "method"
            for reference in observation_methods
        ):
            raise TypeError(
                "observation_methods entries must be exact Method references"
            )
        object.__setattr__(
            self,
            "observation_methods",
            observation_methods,
        )


@dataclass(frozen=True, slots=True)
class AdmittedPort:
    """Complete admitted record for one exact input or output Port."""

    port_type: Mapping[str, Any]
    multiplicity: PortMultiplicity
    values: tuple[AdmittedValue, ...]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "port_type",
            MappingProxyType(dict(self.port_type)),
        )
        values = tuple(self.values)
        if any(type(value) is not AdmittedValue for value in values):
            raise TypeError("values must contain exact AdmittedValue records")
        if self.multiplicity not in {"one", "many"}:
            raise ValueError("multiplicity must be one or many")
        object.__setattr__(self, "values", values)

    @property
    def value(self) -> Any:
        """Return the admitted scientific value in its declared multiplicity."""
        if self.multiplicity == "many":
            return tuple(item.value for item in self.values)
        return self.values[0].value

    def __bool__(self) -> bool:
        return bool(self.values)

    @property
    def value_content_digests(self) -> tuple[str, ...]:
        return tuple(value.content_digest for value in self.values)

    @property
    def candidate_data(self) -> tuple[CandidateDataReference, ...]:
        return tuple(
            reference
            for value in self.values
            for reference in value.candidate_data
        )

    @property
    def scientific_axes(self) -> tuple[ResidueAxisReference, ...]:
        return tuple(
            reference
            for value in self.values
            for reference in value.scientific_axes
        )

    @property
    def observation_methods(self) -> tuple[ExactContractReference, ...]:
        return tuple(
            reference
            for value in self.values
            for reference in value.observation_methods
        )


@dataclass(frozen=True, slots=True)
class CandidatePairingIntentEntry:
    """Raw producer identities intended to form one exact Candidate pair."""

    subject_candidate_id: str
    reference_candidate_id: str


@dataclass(frozen=True, slots=True)
class CandidatePairingIntent:
    """Pre-admission pairing projected after Candidate identity normalization."""

    entries: tuple[CandidatePairingIntentEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Resolved facts available while constructing one scientific operation."""

    method: ExactContractReference
    produced_observations: tuple[ResolvedProducedObservation, ...]
    selection_objectives: tuple[ResolvedSelectionObjective, ...]
    observation_selectors: tuple[ResolvedObservationSelector, ...]
    environment: BindingEnvironment
    resources: OperationResources

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "produced_observations",
            tuple(self.produced_observations),
        )
        object.__setattr__(
            self,
            "selection_objectives",
            tuple(self.selection_objectives),
        )
        object.__setattr__(
            self,
            "observation_selectors",
            tuple(self.observation_selectors),
        )
        if type(self.environment) is not BindingEnvironment:
            raise TypeError("environment must be an admitted BindingEnvironment")


@dataclass(frozen=True, slots=True)
class OperationCall:
    """Immutable admitted values supplied to one scientific operation call."""

    inputs: Mapping[str, AdmittedPort]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    effective_randomness: Mapping[str, Any]

    def __post_init__(self) -> None:
        if any(
            type(port_name) is not str or type(record) is not AdmittedPort
            for port_name, record in self.inputs.items()
        ):
            raise TypeError("inputs must contain complete AdmittedPort records")
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
        )
        object.__setattr__(
            self,
            "node_parameters",
            _freeze_container(self.node_parameters),
        )
        object.__setattr__(
            self,
            "binding_parameters",
            _freeze_container(self.binding_parameters),
        )
        object.__setattr__(
            self,
            "effective_randomness",
            _freeze_container(self.effective_randomness),
        )


class ScientificOperation(Protocol):
    """One canonical scientific implementation behind a Binding."""

    def execute(self, call: OperationCall) -> Mapping[str, Any]: ...
