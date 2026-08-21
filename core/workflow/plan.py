"""Typed compiler output and runtime-ready Workflow plan facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from core.catalog.port_contract import canonical_sha256
from core.parameters.model import AdmittedParameterValues
from core.scoring.observation_plan import ProducedObservationPlan
from core.scoring.selection import (
    ObservationSelector,
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    SelectionObjective,
)
from core.workflow.document import (
    ContractLockEntry,
    WorkflowEdge,
    _freeze_json,
    _thaw_json,
)


EXECUTION_PLAN_NAMESPACE = "protein-workbench-execution-plan/v3"
RESULT_IDENTITY_PLAN_FACTS_NAMESPACE = (
    "protein-workbench-result-identity-plan-facts/v1"
)


@dataclass(frozen=True, slots=True)
class _ExecutionPlanPort:
    """One compiler-resolved typed Port plan."""

    reference: ContractLockEntry
    multiplicity: str
    required: bool
    artifact_kind: str | None
    artifact_media_type: str | None
    port_type: Any = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ArtifactOutputPlan:
    """Typed output-publication facts admitted during compilation."""

    output_port: str
    artifact_kind: str
    artifact_media_type: str | None
    port_type: ContractLockEntry
    accepted_media_types: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class _ExecutionPlanValueSource:
    """One compile-resolved upstream value source."""

    node_id: str
    output_port: str

@dataclass(frozen=True, slots=True)
class ResultIdentityPlanFacts:
    """Immutable compile-resolved static facts for one Result Identity."""

    identity_facts: Mapping[str, Any]
    node_parameter_indirections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity_facts",
            _freeze_json(self.identity_facts),
        )
        object.__setattr__(
            self,
            "node_parameter_indirections",
            tuple(sorted(set(self.node_parameter_indirections))),
        )

    def identity_projection(self) -> dict[str, Any]:
        """Return one isolated canonical projection shared by runtime users."""
        return _thaw_json(self.identity_facts)

    def canonical_projection(self) -> dict[str, Any]:
        """Return the complete compiler-owned plan facts contract."""
        return {
            "schema_namespace": RESULT_IDENTITY_PLAN_FACTS_NAMESPACE,
            "identity_facts": self.identity_projection(),
            "node_parameter_indirections": list(
                self.node_parameter_indirections
            ),
        }

    def cache_contract_metadata(self) -> dict[str, Any]:
        """Project the exact static identity facts stored beside Cache data."""
        return {
            "result_identity_plan_facts": self.canonical_projection()
        }

    @property
    def digest(self) -> str:
        """Identify the exact compiler-owned facts recorded in Run evidence."""
        return canonical_sha256(self.canonical_projection())

@dataclass(frozen=True, slots=True)
class _ExecutionPlanNodeRuntime:
    """Private executable facts excluded from the public Plan digest."""

    factory: Any = field(repr=False, compare=False)
    readiness_declaration: Any = field(repr=False, compare=False)
    effective_randomness_resolver: Any | None = field(
        repr=False,
        compare=False,
    )
    execution_route: str
    cacheable: bool
    deterministic: bool
    effective_randomness_parameters: tuple[str, ...]
    input_ports: Mapping[str, _ExecutionPlanPort] = field(
        repr=False,
        compare=False,
    )
    output_ports: Mapping[str, _ExecutionPlanPort] = field(
        repr=False,
        compare=False,
    )
    input_sources: Mapping[
        str,
        tuple[_ExecutionPlanValueSource, ...],
    ] = field(repr=False, compare=False)
    required_input_sources: Mapping[
        str,
        tuple[_ExecutionPlanValueSource, ...],
    ] = field(repr=False, compare=False)
    dependencies: tuple[str, ...]
    project_input_parameters: tuple[str, ...]
    produced_observation_plan: ProducedObservationPlan = field(
        repr=False,
        compare=False,
    )
    selection_objectives: tuple[ResolvedSelectionObjective, ...] = field(
        repr=False,
        compare=False,
    )
    observation_selectors: tuple[ResolvedObservationSelector, ...] = field(
        repr=False,
        compare=False,
    )
    selection_candidate_output_port: str | None
    artifact_outputs: tuple[ArtifactOutputPlan, ...]

    def __post_init__(self) -> None:
        for name in ("input_ports", "output_ports"):
            object.__setattr__(
                self,
                name,
                MappingProxyType(dict(getattr(self, name))),
            )
        for name in ("input_sources", "required_input_sources"):
            object.__setattr__(
                self,
                name,
                MappingProxyType(
                    {
                        port_name: tuple(sources)
                        for port_name, sources in getattr(self, name).items()
                    }
                ),
            )
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(
            self,
            "effective_randomness_parameters",
            tuple(self.effective_randomness_parameters),
        )
        object.__setattr__(
            self,
            "project_input_parameters",
            tuple(self.project_input_parameters),
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
        object.__setattr__(
            self,
            "artifact_outputs",
            tuple(self.artifact_outputs),
        )

@dataclass(frozen=True, slots=True)
class _ExecutionPlanRuntime:
    """Private Workflow-wide facts resolved atomically during compilation."""

    candidate_data_port_types: Mapping[str, Any] = field(
        repr=False,
        compare=False,
    )
    selection_objectives: tuple[ResolvedSelectionObjective, ...] = field(
        repr=False,
        compare=False,
    )
    observation_selectors: tuple[ResolvedObservationSelector, ...] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_data_port_types",
            MappingProxyType(dict(self.candidate_data_port_types)),
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
class ExecutionPlanNode:
    """One fully resolved immutable private plan Node."""

    node_id: str
    node_type: ContractLockEntry
    binding: ContractLockEntry
    method: ContractLockEntry
    node_parameters: AdmittedParameterValues
    binding_parameters: AdmittedParameterValues
    result_identity_plan_facts: ResultIdentityPlanFacts
    _runtime: _ExecutionPlanNodeRuntime = field(repr=False, compare=False)

@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Private immutable result of one successful compilation."""

    workflow_id: str
    workflow_commit_revision: int
    workflow_digest: str
    catalog_contract_digest: str
    contract_lock_digest: str
    execution_plan_digest: str
    nodes: tuple[ExecutionPlanNode, ...]
    edges: tuple[WorkflowEdge, ...]
    node_order: tuple[str, ...]
    resolved_contracts: tuple[ContractLockEntry, ...]
    _runtime: _ExecutionPlanRuntime = field(repr=False, compare=False)
    observation_selectors: tuple[ObservationSelector, ...] = ()
    selection_objectives: tuple[SelectionObjective, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "nodes",
            "edges",
            "node_order",
            "resolved_contracts",
            "observation_selectors",
            "selection_objectives",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
