"""Result identity and Output Admission plan facts for Node Attempt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any

from core.catalog.port_contract import canonical_json_bytes, canonical_sha256
from core.execution.output_admission import NodeOutputPlan, OutputPortPlan
from core.execution.output_admission.artifacts import (
    ArtifactOutputDeclaration,
)
from core.operation import AdmittedPort
from core.workflow.plan import ExecutionPlanNode
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.exact_reference import ExactContractReference


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, list):
        return [_plain_json(item) for item in value]
    return value


def _freeze_runtime_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze_runtime_json(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_runtime_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class _EffectiveRandomnessSnapshot:
    effective_randomness: Mapping[str, Any]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]


def _resolve_effective_randomness(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
) -> _EffectiveRandomnessSnapshot:
    node_parameters = _plain_json(node.node_parameters)
    binding_parameters = _plain_json(node.binding_parameters)
    declared_randomness = node._runtime.effective_randomness_parameters
    if declared_randomness:
        resolver = node._runtime.effective_randomness_resolver
        if resolver is None:
            resolved_randomness: Mapping[str, Any] = {
                parameter_name: (
                    node_parameters[parameter_name]
                    if parameter_name in node_parameters
                    and parameter_name not in binding_parameters
                    else (
                        binding_parameters[parameter_name]
                        if parameter_name in binding_parameters
                        and parameter_name not in node_parameters
                        else {"resolution": "unresolved"}
                    )
                )
                for parameter_name in declared_randomness
            }
        else:
            resolved_randomness = resolver.resolve(
                inputs=inputs,
                node_parameters=node_parameters,
                binding_parameters=binding_parameters,
            )
            if (
                not isinstance(resolved_randomness, Mapping)
                or set(resolved_randomness) != set(declared_randomness)
            ):
                raise ValueError(
                    "effective randomness resolver must return every "
                    "declared parameter exactly once"
                )
        effective_randomness = {}
        for parameter_name in declared_randomness:
            resolved_value = _plain_json(
                resolved_randomness[parameter_name]
            )
            effective_randomness[parameter_name] = (
                {"resolution": "unresolved"}
                if resolved_value is None
                else resolved_value
            )
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
    canonical_json_bytes(
        {
            "effective_randomness": effective_randomness,
            "node_parameters": node_parameters,
            "binding_parameters": binding_parameters,
        }
    )
    return _EffectiveRandomnessSnapshot(
        effective_randomness=_freeze_runtime_json(effective_randomness),
        node_parameters=_freeze_runtime_json(node_parameters),
        binding_parameters=_freeze_runtime_json(binding_parameters),
    )


def result_identity_descriptor(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> dict[str, Any]:
    """Build the closed scientific identity of one resolved Node result."""
    plan_facts = node.result_identity_plan_facts
    randomness_snapshot = (
        effective_randomness_snapshot
        if effective_randomness_snapshot is not None
        else _resolve_effective_randomness(node, inputs)
    )
    resolved_node_parameters = _plain_json(
        randomness_snapshot.node_parameters
    )
    resolved_binding_parameters = _plain_json(
        randomness_snapshot.binding_parameters
    )
    for parameter_name in plan_facts.node_parameter_indirections:
        resolved_node_parameters.pop(parameter_name, None)
    for parameter_name in node._runtime.project_input_parameters:
        resolved_node_parameters.pop(parameter_name, None)
    declared_randomness = node._runtime.effective_randomness_parameters
    effective_randomness = _plain_json(
        randomness_snapshot.effective_randomness
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
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> str:
    return canonical_sha256(
        result_identity_descriptor(
            node,
            inputs,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    )


def _contains_unresolved_identity(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("identity_complete") is False:
            return True
        return any(
            _contains_unresolved_identity(item)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unresolved_identity(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return any(
            _contains_unresolved_identity(getattr(value, item.name))
            for item in fields(value)
        )
    return (
        isinstance(value, str)
        and value.strip().lower()
        in {"unknown", "unresolved", "latest", "unspecified"}
    )


def _candidate_values(value: Any) -> tuple[Candidate, ...]:
    if type(value) is Candidate:
        return (value,)
    if type(value) is CandidateCollection:
        return value.items
    if isinstance(value, (list, tuple)):
        return tuple(
            candidate
            for item in value
            for candidate in _candidate_values(item)
        )
    return ()


def _result_identity_is_cache_safe(
    node: ExecutionPlanNode,
    inputs: Mapping[str, AdmittedPort],
    *,
    resolved_resource_inputs: tuple[Mapping[str, Any], ...] = (),
    effective_randomness_snapshot: _EffectiveRandomnessSnapshot | None = None,
) -> bool:
    if _contains_unresolved_identity(
        node.result_identity_plan_facts.canonical_projection()
    ):
        return False
    if any(
        _contains_unresolved_identity(admitted.value)
        for admitted in inputs.values()
    ):
        return False
    if _contains_unresolved_identity(
        result_identity_descriptor(
            node,
            inputs,
            resolved_resource_inputs=resolved_resource_inputs,
            effective_randomness_snapshot=effective_randomness_snapshot,
        )
    ):
        return False
    return all(
        not _contains_unresolved_identity(candidate.candidate_id)
        for admitted in inputs.values()
        for candidate in _candidate_values(admitted.value)
    )


def result_contract_metadata(
    node: ExecutionPlanNode,
) -> dict[str, Any]:
    return node.result_identity_plan_facts.cache_contract_metadata()
