"""Result identity and Output Admission plan facts for Node Attempt."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from core.catalog.canonical import canonical_sha256
from core.execution.output_admission.admission import (
    NodeOutputPlan,
    OutputPortPlan,
)
from core.execution.output_admission.artifacts import (
    ArtifactOutputDeclaration,
)
from core.execution._node_attempt_models import _EffectiveRandomnessSnapshot
from core.operation import AdmittedPort
from core.workflow.plan import ExecutionPlanNode
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json, thaw_i_json

def _resolve_effective_randomness(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
) -> _EffectiveRandomnessSnapshot:
    node_parameters = dict(node.node_parameters)
    binding_parameters = dict(node.binding_parameters)
    declared_randomness = node._runtime.effective_randomness_parameters
    if declared_randomness:
        resolver = node._runtime.effective_randomness_resolver
        if resolver is None:
            resolved_randomness: Mapping[str, Any] = {
                parameter_name: node_parameters[parameter_name]
                if parameter_name in node_parameters
                else binding_parameters[parameter_name]
                for parameter_name in declared_randomness
            }
        else:
            resolved_randomness = resolver.resolve(
                inputs=inputs,
                node_parameters=node_parameters,
                binding_parameters=binding_parameters,
            )
            if set(resolved_randomness) != set(declared_randomness):
                raise ValueError(
                    "effective randomness resolver must return every "
                    "declared parameter exactly once"
                )
        effective_randomness = {}
        for parameter_name in declared_randomness:
            resolved_value = freeze_i_json(
                resolved_randomness[parameter_name],
                path=f"effective_randomness.{parameter_name}",
            )
            effective_randomness[parameter_name] = resolved_value
            if (
                parameter_name in node_parameters
                and parameter_name not in binding_parameters
            ):
                node_parameters[parameter_name] = resolved_value
            elif (
                parameter_name in binding_parameters
                and parameter_name not in node_parameters
            ):
                binding_parameters[parameter_name] = resolved_value
    else:
        effective_randomness = {}
    return _EffectiveRandomnessSnapshot(
        effective_randomness=MappingProxyType(effective_randomness),
        node_parameters=MappingProxyType(node_parameters),
        binding_parameters=MappingProxyType(binding_parameters),
    )


def _result_identity_descriptor(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Build the closed scientific identity of one resolved Node result."""
    plan_facts = node.result_identity_plan_facts
    resolved_node_parameters = thaw_i_json(
        effective_randomness_snapshot.node_parameters
    )
    resolved_binding_parameters = thaw_i_json(
        effective_randomness_snapshot.binding_parameters
    )
    for parameter_name in plan_facts.node_parameter_indirections:
        resolved_node_parameters.pop(parameter_name, None)
    for parameter_name in node._runtime.project_input_parameters:
        resolved_node_parameters.pop(parameter_name, None)
    declared_randomness = node._runtime.effective_randomness_parameters
    effective_randomness = thaw_i_json(
        effective_randomness_snapshot.effective_randomness
    )
    if declared_randomness:
        for parameter_name in declared_randomness:
            resolved_node_parameters.pop(parameter_name, None)
            resolved_binding_parameters.pop(parameter_name, None)
    return plan_facts.result_identity_projection(
        input_value_content_digests={
            port_name: admitted.value_content_digests
            for port_name, admitted in inputs.items()
        },
        node_parameters=resolved_node_parameters,
        binding_parameters=resolved_binding_parameters,
        deterministic=node._runtime.deterministic,
        effective_randomness=effective_randomness,
        resolved_resource_inputs=resolved_resource_inputs,
    )


def _exact_reference(reference: Any) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=reference.contract_kind,
        contract_id=reference.contract_id,
        contract_version=reference.contract_version,
        contract_digest=reference.contract_digest,
    )


def _node_output_plan(
    node: ExecutionPlanNode,
    candidate_data_port_types: Mapping[str, Any],
) -> NodeOutputPlan:
    """Project compiler-owned typed facts into Output Admission."""
    return NodeOutputPlan(
        node_id=node.node_id,
        producing_method=_exact_reference(node.method),
        output_ports={
            output_port: OutputPortPlan(
                required=declaration.required,
                multiplicity=declaration.multiplicity,
                port_type=declaration.port_type,
            )
            for output_port, declaration in node._runtime.output_ports.items()
        },
        candidate_data_port_types=candidate_data_port_types,
        produced_observations=node._runtime.produced_observation_plan,
        artifact_outputs=tuple(
            ArtifactOutputDeclaration(
                output_port=declaration.output_port,
                artifact_kind=declaration.artifact_kind,
                artifact_media_type=declaration.artifact_media_type,
                accepted_media_types=declaration.accepted_media_types,
            )
            for declaration in node._runtime.artifact_outputs
        ),
    )


def _result_identity(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...],
) -> str:
    return canonical_sha256(
        _result_identity_descriptor(
            node,
            inputs,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    )


def _result_contract_metadata(
    node: ExecutionPlanNode,
) -> dict[str, Any]:
    return node.result_identity_plan_facts.cache_contract_metadata()
