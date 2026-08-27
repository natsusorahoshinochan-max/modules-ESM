"""Typed execution interface for one resolved scientific operation."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
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
from datatypes.residue import residue_identity_chain

if TYPE_CHECKING:
    from core.scoring.observation_plan import ResolvedProducedObservation
    from core.scoring.selection import (
        ResolvedObservationSelector,
        ResolvedSelectionObjective,
    )


PortMultiplicity = Literal["one", "many"]
_CLEANUP_EXCEPTION_TYPES_ATTRIBUTE = (
    "_protein_workbench_cleanup_exception_types"
)


def retain_secondary_cleanup_exception(
    primary: BaseException,
    cleanup: BaseException,
) -> None:
    """Attach one ordered cleanup exception type to the primary exception."""
    if cleanup is primary:
        return
    retained = getattr(primary, _CLEANUP_EXCEPTION_TYPES_ATTRIBUTE, ())
    setattr(
        primary,
        _CLEANUP_EXCEPTION_TYPES_ATTRIBUTE,
        (*retained, type(cleanup).__name__),
    )


def secondary_cleanup_exception_types(
    error: BaseException,
) -> tuple[str, ...]:
    """Return ordered cleanup causality retained on one primary exception."""
    return getattr(error, _CLEANUP_EXCEPTION_TYPES_ATTRIBUTE, ())


@dataclass(frozen=True, slots=True)
class ManagedProcessResult:
    """Terminal record of one core-managed local Provider process."""

    returncode: int
    stdout: bytes
    stderr: bytes


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
        by_id = {entry.identity_id: entry for entry in self.entries}
        if len(by_id) != len(self.entries):
            raise ValueError("encoded output identities contain a duplicate ID")
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    def require(self, identity_id: str) -> EncodedOutputIdentity:
        return self._by_id[identity_id]


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


@dataclass(frozen=True, slots=True)
class OutputIdentityIntent:
    """Data-only relation resolved by the exact output Port contract."""

    identity_sources: tuple[OutputIdentitySource, ...]
    relation: object


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
        object.__setattr__(self, "entries", entries)
        if self.position_semantics != "one_based_chain_local":
            raise ValueError("provider residue position semantics are unsupported")
        workbench_order = self.workbench_chain_order
        structure_order = self.provider_structure_chain_order
        provider_order = self.provider_chain_order
        if (
            not entries
            or not workbench_order
            or not structure_order
            or not provider_order
            or len(set(workbench_order)) != len(workbench_order)
            or len(set(structure_order)) != len(structure_order)
            or len(set(provider_order)) != len(provider_order)
            or set(structure_order) != set(provider_order)
        ):
            raise ValueError("provider residue projection is incomplete")
        residue_ids: set[str] = set()
        provider_positions: set[tuple[str, int]] = set()
        observed_workbench_chains: set[str] = set()
        observed_provider_chains: set[str] = set()
        workbench_segment_order: list[str] = []
        current_segment = -1
        current_position = 0
        for entry in entries:
            chain = residue_identity_chain(
                entry.residue_id,
                subject="provider projection residue identity",
            )
            coordinate = (entry.provider_chain_id, entry.provider_position)
            if (
                chain not in workbench_order
                or entry.provider_chain_id not in provider_order
                or entry.segment_index < current_segment
                or entry.segment_index > current_segment + 1
                or entry.segment_index >= len(structure_order)
                or entry.provider_chain_id
                != structure_order[entry.segment_index]
                or entry.residue_id in residue_ids
                or coordinate in provider_positions
            ):
                raise ValueError("provider residue projection is inconsistent")
            if entry.segment_index != current_segment:
                if entry.provider_position != 1:
                    raise ValueError(
                        "provider residue projection must begin at position 1"
                    )
                current_segment = entry.segment_index
                current_position = 1
                workbench_segment_order.append(chain)
            elif (
                entry.provider_position != current_position + 1
                or workbench_segment_order[-1] != chain
            ):
                raise ValueError("provider residue projection is not contiguous")
            else:
                current_position = entry.provider_position
            residue_ids.add(entry.residue_id)
            provider_positions.add(coordinate)
            observed_workbench_chains.add(chain)
            observed_provider_chains.add(entry.provider_chain_id)
        collapsed_workbench_order = tuple(
            chain
            for index, chain in enumerate(workbench_segment_order)
            if index == 0 or chain != workbench_segment_order[index - 1]
        )
        if (
            observed_workbench_chains != set(workbench_order)
            or observed_provider_chains != set(structure_order)
            or current_segment != len(structure_order) - 1
            or collapsed_workbench_order != workbench_order
        ):
            raise ValueError("provider residue projection closure is incomplete")


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

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)


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

    def local_provider(
        self,
        provider_id: str,
    ) -> ContextManager[dict[object, object]]: ...

    def cancellable_process_group(
        self,
        process_group: int,
        *,
        fallback: Callable[[], None] | None = None,
    ) -> ContextManager[None]: ...

    def run_managed_local_process(
        self,
        *,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
        path_entries: Sequence[Path] = (),
        capture_output: bool = False,
    ) -> ManagedProcessResult: ...

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


@dataclass(frozen=True, slots=True)
class AdmittedPort:
    """Complete admitted record for one exact input or output Port."""

    port_type: ExactContractReference
    multiplicity: PortMultiplicity
    values: tuple[AdmittedValue, ...]
    content_digest: str

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


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Resolved facts available while constructing one scientific operation."""

    method: ExactContractReference
    produced_observations: tuple[ResolvedProducedObservation, ...]
    selection_objectives: tuple[ResolvedSelectionObjective, ...]
    observation_selectors: tuple[ResolvedObservationSelector, ...]
    environment: BindingEnvironment
    resources: OperationResources


@dataclass(frozen=True, slots=True)
class OperationCall:
    """Immutable admitted values supplied to one scientific operation call."""

    inputs: Mapping[str, AdmittedPort]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    effective_randomness: Mapping[str, Any]


class ScientificOperation(Protocol):
    """One canonical scientific implementation behind a Binding."""

    def execute(self, call: OperationCall) -> Mapping[str, Any]: ...
