"""Typed execution interface for one resolved scientific operation."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    ContextManager,
    Literal,
    Protocol,
)

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
class OutputIdentitySource:
    """One fresh scientific value whose canonical identity is needed."""

    identity_id: str
    source_role: str
    value: object


@dataclass(frozen=True, slots=True)
class EncodedOutputIdentity:
    """Exact identity fact produced by Output Admission's one source encode."""

    identity_id: str
    port_type: ExactContractReference
    content_digest: str


@dataclass(frozen=True, slots=True)
class EncodedOutputIdentities:
    """Closed identity facts supplied to one intent materialization."""

    entries: tuple[EncodedOutputIdentity, ...]
    _by_id: Mapping[str, EncodedOutputIdentity] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        by_id = {entry.identity_id: entry for entry in entries}
        if len(by_id) != len(entries):
            raise ValueError("encoded output identities contain a duplicate ID")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    def require(self, identity_id: str) -> EncodedOutputIdentity:
        try:
            return self._by_id[identity_id]
        except KeyError as error:
            raise ValueError(
                f"output identity source {identity_id!r} was not encoded"
            ) from error


@dataclass(frozen=True, slots=True)
class CandidateMetadataIdentity:
    """One resolved identity string to attach to a fresh Candidate."""

    candidate_id: str
    field_name: str
    value: str


@dataclass(frozen=True, slots=True)
class ResolvedOutputIdentity:
    """Final runtime value and projections materialized from encoded sources."""

    value: object
    candidate_metadata: tuple[CandidateMetadataIdentity, ...] = ()
    scientific_axes: tuple[ResidueAxisReference, ...] | None = None

    def __post_init__(self) -> None:
        candidate_metadata = tuple(self.candidate_metadata)
        object.__setattr__(self, "candidate_metadata", candidate_metadata)
        if self.scientific_axes is not None:
            object.__setattr__(
                self,
                "scientific_axes",
                tuple(self.scientific_axes),
            )


@dataclass(frozen=True, slots=True)
class OutputIdentityIntent:
    """Data-only relation resolved by the exact output Port contract."""

    identity_sources: tuple[OutputIdentitySource, ...]
    relation: object

    def __post_init__(self) -> None:
        sources = tuple(self.identity_sources)
        object.__setattr__(self, "identity_sources", sources)


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

    def __post_init__(self) -> None:
        if (
            type(self.residue_id) is not str
            or not self.residue_id
            or type(self.provider_chain_id) is not str
            or not self.provider_chain_id
        ):
            raise TypeError("provider residue identities must be nonempty strings")
        if (
            type(self.segment_index) is not int
            or self.segment_index < 0
            or type(self.provider_position) is not int
            or self.provider_position < 1
        ):
            raise ValueError("provider residue positions must be canonical")


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

    def __post_init__(self) -> None:
        for field_name in (
            "workbench_chain_order",
            "provider_structure_chain_order",
            "provider_chain_order",
        ):
            values = tuple(getattr(self, field_name))
            if any(type(value) is not str or not value for value in values):
                raise TypeError("provider chain orders require nonempty strings")
            object.__setattr__(self, field_name, values)
        entries = tuple(self.entries)
        if any(
            type(entry) is not ProviderResidueProjectionEntry
            for entry in entries
        ):
            raise TypeError(
                "provider residue projection entries require exact typed values"
            )
        object.__setattr__(self, "entries", entries)
        if self.position_semantics != "one_based_chain_local":
            raise ValueError("provider residue position semantics are unsupported")


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
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """One direct readiness conclusion at an operation boundary."""

    passing: bool
    proof_source: str = "direct-observation"
    reason_code: str | None = None


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
        object.__setattr__(self, "candidate_data", tuple(self.candidate_data))
        object.__setattr__(self, "scientific_axes", tuple(self.scientific_axes))
        object.__setattr__(
            self, "observation_methods", tuple(self.observation_methods)
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
        object.__setattr__(self, "values", tuple(self.values))

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


@dataclass(frozen=True, slots=True)
class OperationCall:
    """Immutable admitted values supplied to one scientific operation call."""

    inputs: Mapping[str, AdmittedPort]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    effective_randomness: Mapping[str, Any]

    def __post_init__(self) -> None:
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
