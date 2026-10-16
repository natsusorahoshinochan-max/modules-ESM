from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

from core.parameters.model import AdmittedParameterValues

from core.parameters.contract import matching_value_contract_alternatives, resolve_value_contract_reference
from core.catalog.declarations import (
    ExecutionBindingDefinition,
    NodeTypeDefinition,
)
from core.workflow.graph import NodeOutputReference, WorkflowGraphDescription
from core.workflow.document import WorkflowDocument, WorkflowNodeInstance
from core.workflow.errors import WorkflowCompileError


type _PlanNodes = Mapping[
    str,
    tuple[NodeTypeDefinition, ExecutionBindingDefinition],
]
type _AdmittedInputSource = tuple[int, NodeOutputReference]


def _admit_workflow_graph(
    workflow: WorkflowDocument,
    plan_nodes: _PlanNodes,
    *, require_complete: bool = True,
) -> WorkflowGraphDescription:
    nodes_by_id: dict[str, WorkflowNodeInstance] = {}
    for index, node in enumerate(workflow.nodes):
        if node.node_id in nodes_by_id:
            raise WorkflowCompileError(
                "duplicate_node_id",
                f"Node ID {node.node_id!r} appears more than once",
                node_id=node.node_id,
                field_path=("nodes", index, "node_id"),
            )
        nodes_by_id[node.node_id] = node

    input_ports_by_node = {
        node_id: {port.name: port for port in plan_nodes[node_id][0].inputs}
        for node_id in plan_nodes
    }
    output_ports_by_node = {
        node_id: {port.name: port for port in plan_nodes[node_id][0].outputs}
        for node_id in plan_nodes
    }
    input_sources: dict[str, dict[str, tuple[_AdmittedInputSource, ...]]] = {
        node_id: {} for node_id in plan_nodes
    }
    adjacency = {node_id: [] for node_id in nodes_by_id}
    indegree = {node_id: 0 for node_id in nodes_by_id}
    for index, edge in enumerate(workflow.edges):
        source = nodes_by_id.get(edge.source_node_id)
        target = nodes_by_id.get(edge.target_node_id)
        if source is None or target is None:
            raise WorkflowCompileError(
                "edge_node_not_found",
                "Workflow Edge references a Node outside the Workflow",
                field_path=("edges", index),
            )
        if not require_complete and (source.node_id not in plan_nodes or target.node_id not in plan_nodes):
            continue
        source_port = output_ports_by_node[source.node_id].get(edge.source_port)
        target_port = input_ports_by_node[target.node_id].get(edge.target_port)
        if source_port is None:
            raise WorkflowCompileError(
                "source_port_not_found",
                f"Source Port {edge.source_port!r} is not declared",
                node_id=source.node_id,
                field_path=("edges", index, "source_port"),
            )
        if target_port is None:
            raise WorkflowCompileError(
                "target_port_not_found",
                f"Target Port {edge.target_port!r} is not declared",
                node_id=target.node_id,
                field_path=("edges", index, "target_port"),
            )
        if source_port.port_type.key != target_port.port_type.key:
            raise WorkflowCompileError(
                "port_type_mismatch",
                "Connected Ports do not share one exact nominal Port Type",
                node_id=target.node_id,
                field_path=("edges", index),
            )
        if (
            source_port.multiplicity == "many"
            and target_port.multiplicity == "one"
        ):
            raise WorkflowCompileError(
                "port_multiplicity_mismatch",
                (
                    "A many-valued output Port cannot connect to a one-valued "
                    "input Port because that would discard admitted values"
                ),
                node_id=target.node_id,
                field_path=("edges", index),
            )
        source_fact = (index, NodeOutputReference(source.node_id, edge.source_port))
        existing_sources = input_sources[target.node_id].get(edge.target_port, ())
        if edge.target_slot is not None and any(
            workflow.edges[existing_index].target_slot == edge.target_slot
            for existing_index, _ in existing_sources
        ):
            raise WorkflowCompileError('duplicate_input_slot',
                f'Input slot {edge.target_slot!r} has multiple connections',
                node_id=target.node_id, field_path=('edges', index, 'target_slot'))
        target_sources = (*existing_sources, source_fact)
        input_sources[target.node_id][edge.target_port] = target_sources
        if len(target_sources) > 1 and target_port.multiplicity != "many":
            raise WorkflowCompileError(
                "duplicate_input_connection",
                f"Input Port {edge.target_port!r} accepts one connection",
                node_id=target.node_id,
                field_path=("edges", index, "target_port"),
            )
        adjacency[source.node_id].append(target.node_id)
        indegree[target.node_id] += 1

    for index, node in enumerate(workflow.nodes):
        if node.node_id not in plan_nodes and not require_complete:
            continue
        node_definition, binding = plan_nodes[node.node_id]
        if binding.node_type.key != node_definition.identity.key:
            raise WorkflowCompileError(
                "binding_ownership_mismatch",
                "Selected Binding does not belong to the selected Node Type",
                node_id=node.node_id,
                field_path=("nodes", index, "binding_id"),
            )
        if not require_complete:
            continue
        for port in node_definition.inputs:
            if port.required and not input_sources[node.node_id].get(port.name):
                raise WorkflowCompileError(
                    "required_input_missing",
                    f"Required input Port {port.name!r} is not connected",
                    node_id=node.node_id,
                    field_path=("nodes", index),
                )
        for constraint in node_definition.input_constraints:
            connected = sum(
                len(input_sources[node.node_id].get(port_name, ()))
                for port_name in constraint
            )
            if connected != 1:
                raise WorkflowCompileError(
                    "input_constraint_unsatisfied",
                    "Exactly one constrained input Port must be connected",
                    node_id=node.node_id,
                    field_path=("nodes", index),
                )
    queue = deque(
        node.node_id for node in workflow.nodes if indegree[node.node_id] == 0
    )
    order: list[str] = []
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for downstream in adjacency[node_id]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    if len(order) != len(workflow.nodes):
        raise WorkflowCompileError(
            "workflow_cycle",
            "Workflow graph must be acyclic",
            field_path=("edges",),
        )
    return WorkflowGraphDescription(
        nodes_by_id=nodes_by_id,
        input_sources=input_sources,
        output_ports_by_node=output_ports_by_node,
        node_order=tuple(order),
    )


def _validate_input_slot_references(
    workflow: WorkflowDocument,
    plan_nodes: _PlanNodes,
    admitted_parameters: Mapping[str, AdmittedParameterValues],
) -> None:
    """Validate declared parameter references to node-local connected slots."""
    for node_index, node in enumerate(workflow.nodes):
        connected = {(edge.target_port, edge.target_slot) for edge in workflow.edges
                     if edge.target_node_id == node.node_id and edge.target_slot is not None}
        def visit(schema: Mapping[str, Any], value: Any, path: tuple[str | int, ...], root: Mapping[str, Any]) -> None:
            if '$ref' in schema:
                visit(resolve_value_contract_reference(schema, root), value, path, root)
                return
            input_port = schema.get('input_port')
            if input_port is not None and (input_port, value) not in connected:
                raise WorkflowCompileError(
                    'required_input_missing', f'Input slot {value!r} on {input_port!r} is disconnected',
                    node_id=node.node_id, field_path=path)
            if isinstance(value, Mapping):
                for name, child in schema.get('properties', {}).items():
                    if name in value:
                        visit(child, value[name], (*path, name), root)
            if isinstance(value, (list, tuple)) and 'items' in schema:
                for index, item in enumerate(value):
                    visit(schema['items'], item, (*path, index), root)
            for alternative in matching_value_contract_alternatives(value, schema, root=root):
                visit(alternative, value, path, root)
        for declaration in plan_nodes[node.node_id][0].parameter_contract.entries:
            if declaration.name in admitted_parameters[node.node_id]:
                visit(declaration.value_contract, admitted_parameters[node.node_id][declaration.name],
                      ('nodes', node_index, 'node_parameters', declaration.name), declaration.value_contract)
