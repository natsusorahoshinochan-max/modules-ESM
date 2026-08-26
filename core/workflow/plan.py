"""Typed compiler output and runtime-ready Workflow plan facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.parameters.model import AdmittedParameterValues
from core.scoring.observation_plan import ProducedObservationPlan
from core.scoring.selection import (
    ObservationSelector,
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    SelectionObjective,
)
from core.workflow.document import (
    WorkflowEdge,
    _thaw_json,
)
from datatypes.exact_reference import ExactContractReference


@dataclass(frozen=True, slots=True)
class _ExecutionPlanPort:
    """One compiler-resolved typed Port plan."""

    reference: ExactContractReference
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
    port_type: ExactContractReference
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
    node_parameter_indirections: tuple[str, ...]

    def identity_projection(self) -> dict[str, Any]:
        """Return one isolated canonical projection shared by runtime users."""
        return _thaw_json(self.identity_facts)

    def canonical_projection(self) -> dict[str, Any]:
        """Return the complete compiler-owned scientific plan facts."""
        return {
            "identity_facts": self.identity_projection(),
            "node_parameter_indirections": list(
                self.node_parameter_indirections
            ),
        }

    def result_identity_projection(
        self,
        *,
        input_value_content_digests: Mapping[str, tuple[str, ...]],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
        deterministic: bool,
        effective_randomness: Mapping[str, Any],
        resolved_resource_inputs: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]:
        """Build the canonical scientific identity for one resolved result."""
        canonical_plan_facts = self.canonical_projection()
        declared_inputs = {
            port["input_port"]: port
            for port in canonical_plan_facts["identity_facts"][
                "input_contracts"
            ]
        }
        descriptor: dict[str, Any] = {
            "result_identity_plan_facts": canonical_plan_facts,
            "inputs": [
                {
                    "input_port": port_name,
                    "port_type": declared_inputs[port_name]["port_type"],
                    "multiplicity": declared_inputs[port_name][
                        "multiplicity"
                    ],
                    "value_content_digests": list(
                        input_value_content_digests[port_name]
                    ),
                }
                for port_name in sorted(input_value_content_digests)
            ],
            "node_parameters": _thaw_json(node_parameters),
            "binding_parameters": _thaw_json(binding_parameters),
            "determinism": {
                "deterministic": deterministic,
                "effective_randomness": _thaw_json(effective_randomness),
            },
        }
        if resolved_resource_inputs:
            descriptor["resolved_resource_inputs"] = _thaw_json(
                resolved_resource_inputs
            )
        return descriptor

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

@dataclass(frozen=True, slots=True)
class _ExecutionPlanRuntime:
    """Private Workflow-wide facts resolved atomically during compilation."""

    candidate_data_port_types: Mapping[str, Any] = field(
        repr=False,
        compare=False,
    )

@dataclass(frozen=True, slots=True)
class ExecutionPlanNode:
    """One fully resolved immutable private plan Node."""

    node_id: str
    node_type: ExactContractReference
    binding: ExactContractReference
    method: ExactContractReference
    node_parameters: AdmittedParameterValues
    binding_parameters: AdmittedParameterValues
    result_identity_plan_facts: ResultIdentityPlanFacts
    _runtime: _ExecutionPlanNodeRuntime = field(repr=False, compare=False)

@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Private immutable result of one successful compilation."""

    workflow_id: str
    nodes: tuple[ExecutionPlanNode, ...]
    edges: tuple[WorkflowEdge, ...]
    node_order: tuple[str, ...]
    scientific_definitions: tuple[Mapping[str, Any], ...]
    _runtime: _ExecutionPlanRuntime = field(repr=False, compare=False)
    observation_selectors: tuple[ObservationSelector, ...]
    selection_objectives: tuple[SelectionObjective, ...]
