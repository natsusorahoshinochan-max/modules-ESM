"""The single admission seam for all raw scientific Operation outputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from core.catalog.port_contract import PortValueError
from core.execution.output_admission.artifacts import (
    AdmittedArtifactPublicationPlan,
    ArtifactOutputDeclaration,
    _artifact_publication_plan,
)
from core.execution.output_admission.candidate_identity import (
    _candidate_values,
    _normalize_candidate_outputs,
)
from core.execution.output_admission.identity import (
    _FreshOutputIdentityEncoder,
)
from core.execution.output_admission.port_values import (
    _FreshValueProjections,
    _admit_fresh_port,
)
from core.operation import (
    AdmittedPort,
    CandidateMetadataIdentity,
    OutputIdentityIntent,
    PortMultiplicity,
)
from core.scoring.observation_admission import admit_produced_observations
from core.scoring.observation_plan import ProducedObservationPlan
from datatypes.exact_reference import ExactContractReference, ResidueAxisReference


@dataclass(frozen=True, slots=True)
class OutputPortPlan:
    """Compiler-resolved nominal contract for one Operation output Port."""

    required: bool
    multiplicity: PortMultiplicity
    port_type: Any = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class NodeOutputPlan:
    """Closed compiler facts needed by one Output Admission invocation."""

    node_id: str
    producing_method: ExactContractReference
    output_ports: Mapping[str, OutputPortPlan]
    candidate_data_port_types: Mapping[str, Any] = field(
        repr=False,
        compare=False,
    )
    produced_observations: ProducedObservationPlan = field(
        repr=False,
        compare=False,
    )
    artifact_outputs: tuple[ArtifactOutputDeclaration, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_ports",
            MappingProxyType(dict(self.output_ports)),
        )
        object.__setattr__(
            self,
            "candidate_data_port_types",
            MappingProxyType(dict(self.candidate_data_port_types)),
        )
        object.__setattr__(
            self,
            "artifact_outputs",
            tuple(self.artifact_outputs),
        )


@dataclass(frozen=True, slots=True)
class AdmittedOutputDescriptor:
    """Result evidence descriptor produced by Output Admission."""

    node_id: str
    output_port: str
    port_type: Mapping[str, Any]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "port_type",
            MappingProxyType(dict(self.port_type)),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "output_port": self.output_port,
            "port_type": dict(self.port_type),
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class AdmittedNodeOutput:
    """Closed trusted result of one complete Output Admission invocation."""

    node_id: str
    result_identity: str
    ports: Mapping[str, AdmittedPort]
    evidence_descriptors: tuple[AdmittedOutputDescriptor, ...]
    artifact_publication_plan: AdmittedArtifactPublicationPlan

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ports",
            MappingProxyType(dict(self.ports)),
        )
        object.__setattr__(
            self,
            "evidence_descriptors",
            tuple(self.evidence_descriptors),
        )

    @property
    def runtime_ports(self) -> Mapping[tuple[str, str], AdmittedPort]:
        return MappingProxyType(
            {
                (self.node_id, output_port): admitted
                for output_port, admitted in self.ports.items()
            }
        )


@dataclass(frozen=True, slots=True)
class _ResolvedIdentityOutputs:
    values: Mapping[str, tuple[Any, ...]]
    candidate_metadata: tuple[CandidateMetadataIdentity, ...]
    scientific_axes: Mapping[
        tuple[str, int],
        tuple[ResidueAxisReference, ...] | None,
    ]


def _resolve_identity_intents(
    *,
    declarations: Mapping[str, OutputPortPlan],
    raw_outputs: Mapping[str, Any],
    identity_encoder: _FreshOutputIdentityEncoder,
) -> _ResolvedIdentityOutputs:
    resolved_outputs: dict[str, tuple[Any, ...]] = {}
    candidate_metadata: list[CandidateMetadataIdentity] = []
    scientific_axes: dict[
        tuple[str, int],
        tuple[ResidueAxisReference, ...] | None,
    ] = {}
    for output_port, supplied in raw_outputs.items():
        declaration = declarations[output_port]
        if declaration.multiplicity == "many":
            if not isinstance(supplied, (list, tuple)):
                raise PortValueError(
                    f"Output Port {output_port!r} requires many values"
                )
            values = tuple(supplied)
        else:
            values = (supplied,)
        materialized_values: list[Any] = []
        for value_index, value in enumerate(values):
            if type(value) is not OutputIdentityIntent:
                materialized_values.append(value)
                continue
            identities = identity_encoder.encode_intent_sources(
                tuple(value.identity_sources),
                declaration.port_type.output_identity_source_port_types,
            )
            resolved = declaration.port_type.materialize_output_identity(
                value.relation,
                identities,
            )
            materialized_values.append(resolved.value)
            candidate_metadata.extend(resolved.candidate_metadata)
            scientific_axes[(output_port, value_index)] = (
                resolved.scientific_axes
            )
        resolved_outputs[output_port] = tuple(materialized_values)
    return _ResolvedIdentityOutputs(
        values=MappingProxyType(resolved_outputs),
        candidate_metadata=tuple(candidate_metadata),
        scientific_axes=MappingProxyType(scientific_axes),
    )


def _closed_admitted_node_output(
    *,
    plan: NodeOutputPlan,
    result_identity: str,
    ports: Mapping[str, AdmittedPort],
) -> AdmittedNodeOutput:
    descriptors = tuple(
        AdmittedOutputDescriptor(
            node_id=plan.node_id,
            output_port=output_port,
            port_type=admitted.port_type,
            content_digest=admitted.content_digest,
        )
        for output_port, admitted in ports.items()
    )
    return AdmittedNodeOutput(
        node_id=plan.node_id,
        result_identity=result_identity,
        ports=ports,
        evidence_descriptors=descriptors,
        artifact_publication_plan=_artifact_publication_plan(
            declarations=plan.artifact_outputs,
            outputs=ports,
        ),
    )


def restore_node_output(
    *,
    plan: NodeOutputPlan,
    result_identity: str,
    ports: Mapping[str, AdmittedPort],
) -> AdmittedNodeOutput:
    """Close already-restored trusted Ports without fresh admission."""
    return _closed_admitted_node_output(
        plan=plan,
        result_identity=result_identity,
        ports=ports,
    )


def admit_node_output(
    *,
    node_plan: NodeOutputPlan,
    admitted_inputs: Mapping[str, AdmittedPort],
    raw_outputs: object,
    result_identity: str,
) -> AdmittedNodeOutput:
    """Admit every raw output through one complete scientific boundary."""
    if not isinstance(raw_outputs, Mapping):
        raise PortValueError("Direct implementation output must be an object")
    declarations = node_plan.output_ports
    if set(raw_outputs) - set(declarations):
        raise PortValueError("Direct implementation returned unknown outputs")
    for output_port, declaration in declarations.items():
        if declaration.required and output_port not in raw_outputs:
            raise PortValueError(
                f"Required output Port {output_port!r} is missing"
            )

    identity_encoder = _FreshOutputIdentityEncoder()
    materialized = _resolve_identity_intents(
        declarations=declarations,
        raw_outputs=raw_outputs,
        identity_encoder=identity_encoder,
    )
    normalized = _normalize_candidate_outputs(
        result_identity=result_identity,
        inputs=admitted_inputs,
        outputs=materialized.values,
        candidate_data_port_types=node_plan.candidate_data_port_types,
        identity_encoder=identity_encoder,
        candidate_metadata=materialized.candidate_metadata,
        observation_propagation=node_plan.produced_observations.propagation,
    )
    admitted: dict[str, AdmittedPort] = {}
    for output_port, declaration in declarations.items():
        if output_port not in normalized.values:
            continue
        values = normalized.values[output_port]
        value_projections: list[_FreshValueProjections | None] = []
        for value_index, value in enumerate(values):
            candidates = _candidate_values(value)
            candidate_data = (
                tuple(
                    normalized.candidate_data[candidate.candidate_id]
                    for candidate in candidates
                )
                if candidates
                else None
            )
            scientific_axes = materialized.scientific_axes.get(
                (output_port, value_index)
            )
            value_projections.append(
                _FreshValueProjections(
                    candidate_data=candidate_data,
                    scientific_axes=scientific_axes,
                )
                if candidate_data is not None or scientific_axes is not None
                else None
            )
        snapshot = _admit_fresh_port(
            port_type=declaration.port_type,
            multiplicity=declaration.multiplicity,
            values=values,
            candidate_data_port_types=node_plan.candidate_data_port_types,
            projections=tuple(value_projections),
        )
        if (
            declaration.port_type.type_id != "score.collection"
            and declaration.port_type.observation_method_projection is not None
            and any(
                method != node_plan.producing_method
                for method in snapshot.observation_methods
            )
        ):
            raise PortValueError(
                "Output Observation Method projection does not equal the "
                "producing Binding Method"
            )
        admitted[output_port] = snapshot

    admitted_ports = MappingProxyType(admitted)
    for output_port, snapshot in admitted_ports.items():
        declaration = declarations[output_port]
        if declaration.port_type.type_id != "score.collection":
            continue
        for value in snapshot.values:
            admit_produced_observations(
                plan=node_plan.produced_observations,
                output_port=output_port,
                collection=value.value,
                inputs=admitted_inputs,
                outputs=admitted_ports,
            )
    return _closed_admitted_node_output(
        plan=node_plan,
        result_identity=result_identity,
        ports=admitted_ports,
    )
