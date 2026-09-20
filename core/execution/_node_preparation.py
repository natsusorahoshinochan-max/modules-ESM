"""Scientific input resolution shared by execution and scope admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.execution._node_attempt_identity import (
    _exact_reference,
    _resolve_effective_randomness,
    _result_identity,
)
from core.execution._node_attempt_models import _PreparedNodeExecution
from core.execution.output_admission.port_values import combine_admitted_port
from core.operation import AdmittedPort
from core.project.manager import ProjectManager
from core.workflow.plan import ExecutionPlanNode


def prepare_node(
    projects: ProjectManager,
    project_id: str,
    node: ExecutionPlanNode,
    committed_values: Mapping[tuple[str, str], AdmittedPort],
) -> _PreparedNodeExecution:
    admitted_inputs: dict[str, list[Any]] = {}
    for port_name, sources in node._runtime.input_sources.items():
        for source_reference in sources:
            source = committed_values.get(
                (source_reference.node_id, source_reference.output_port)
            )
            if source is not None and source.values:
                admitted_inputs.setdefault(port_name, []).extend(source.values)
    inputs = {
        port_name: combine_admitted_port(
            port_type=_exact_reference(node._runtime.input_ports[port_name].reference),
            multiplicity=node._runtime.input_ports[port_name].multiplicity,
            values=tuple(values),
        )
        for port_name, values in admitted_inputs.items()
    }
    project_inputs = {}
    identities: list[Mapping[str, Any]] = []
    for parameter_name in node._runtime.project_input_parameters:
        reference = node.node_parameters[parameter_name]
        descriptor, payload = projects.read_input(project_id, reference)
        project_inputs[reference] = (descriptor, payload)
        identities.append({
            "resource_kind": "project_input",
            "parameter_name": parameter_name,
            "content_digest": descriptor.content_digest,
            "size": descriptor.size,
        })
    resource_identities = tuple(identities)
    randomness = _resolve_effective_randomness(node, inputs)
    cache_eligible = node._runtime.cacheable and node._runtime.deterministic
    return _PreparedNodeExecution(
        inputs=inputs,
        project_inputs=project_inputs,
        resource_identities=resource_identities,
        effective_randomness=randomness,
        cache_eligible=cache_eligible,
        result_identity=(
            _result_identity(
                node,
                inputs,
                resolved_resource_inputs=resource_identities,
                effective_randomness_snapshot=randomness,
            )
            if cache_eligible else None
        ),
    )
