"""Private graph, Port, and selection-consumer compilation."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from core.catalog.declarations import (
    ContractIdentity,
    ExecutionBindingDefinition,
    NodePortDefinition,
    NodeTypeDefinition,
    ProducedObservationDefinition,
)
from core.catalog.model import FrozenCatalog
from core.catalog.port_contract import canonical_json_bytes
from core.parameters.model import AdmittedParameterValues
from core.scoring.selection import (
    SelectionInput,
    context_selector_canonical,
    selection_input_canonical,
)
from core.workflow.compiler import WorkflowCompileError
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from datatypes.exact_reference import ExactContractReference


def _port_map(
    definition: NodeTypeDefinition,
    direction: str,
) -> dict[str, NodePortDefinition]:
    ports = definition.inputs if direction == "inputs" else definition.outputs
    return {port.name: port for port in ports}


@dataclass(frozen=True, slots=True)
class _ObservationCapability:
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference | None
    context_profile: Mapping[str, Any]
    subject_grain: str
    source_role: str
    guaranteed_multiplicity: str
    subject_source: SelectionInput | None
    reference_source: SelectionInput | None
    pairing_source: SelectionInput | None


type _AdmittedInputSource = tuple[int, SelectionInput]


@dataclass(frozen=True, slots=True)
class _AdmittedWorkflowGraph:
    nodes_by_id: Mapping[str, WorkflowNodeInstance]
    input_sources: dict[str, dict[str, tuple[_AdmittedInputSource, ...]]]
    node_order: tuple[str, ...]


def _validate_static_semantics(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
    admitted_node_parameters: Mapping[str, AdmittedParameterValues],
) -> _AdmittedWorkflowGraph:
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

    input_sources: dict[str, dict[str, tuple[_AdmittedInputSource, ...]]] = {
        node_id: {} for node_id in nodes_by_id
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
        source_definition = cast(
            NodeTypeDefinition,
            catalog.require_contract(
            "node_type",
            source.node_type_id,
            source.node_type_version,
            ).definition,
        )
        target_definition = cast(
            NodeTypeDefinition,
            catalog.require_contract(
            "node_type",
            target.node_type_id,
            target.node_type_version,
            ).definition,
        )
        source_port = _port_map(source_definition, "outputs").get(
            edge.source_port
        )
        target_port = _port_map(target_definition, "inputs").get(
            edge.target_port
        )
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
        source_fact = (index, SelectionInput(source.node_id, edge.source_port))
        existing_sources = input_sources[target.node_id].get(edge.target_port, ())
        target_sources = (*existing_sources, source_fact)
        input_sources[target.node_id][edge.target_port] = target_sources
        if (
            len(target_sources) > 1
            and target_port.multiplicity != "many"
        ):
            raise WorkflowCompileError(
                "duplicate_input_connection",
                f"Input Port {edge.target_port!r} accepts one connection",
                node_id=target.node_id,
                field_path=("edges", index, "target_port"),
            )
        adjacency[source.node_id].append(target.node_id)
        indegree[target.node_id] += 1

    plan_nodes: dict[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ] = {}
    for index, node in enumerate(workflow.nodes):
        node_definition = cast(
            NodeTypeDefinition,
            catalog.require_contract(
            "node_type",
            node.node_type_id,
            node.node_type_version,
            ).definition,
        )
        binding = cast(
            ExecutionBindingDefinition,
            catalog.require_contract(
            "binding",
            node.binding_id,
            node.binding_version,
            ).definition,
        )
        if binding.node_type.key != node_definition.identity.key:
            raise WorkflowCompileError(
                "binding_ownership_mismatch",
                "Selected Binding does not belong to the selected Node Type",
                node_id=node.node_id,
                field_path=("nodes", index, "binding_id"),
            )
        for port in node_definition.inputs:
            if (
                port.required
                and not input_sources[node.node_id].get(port.name)
            ):
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
        plan_nodes[node.node_id] = (node_definition, binding)

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

    graph = _AdmittedWorkflowGraph(
        nodes_by_id=nodes_by_id,
        input_sources=input_sources,
        node_order=tuple(order),
    )
    capabilities = _derive_observation_capabilities(
        graph,
        catalog=catalog,
        plan_nodes=plan_nodes,
    )
    _validate_selection_objectives(
        workflow,
        graph=graph,
        plan_nodes=plan_nodes,
        capabilities=capabilities,
    )
    _validate_observation_selectors(
        workflow,
        graph=graph,
        plan_nodes=plan_nodes,
        capabilities=capabilities,
    )
    _validate_selection_objective_consumers(
        workflow,
        graph=graph,
        plan_nodes=plan_nodes,
        admitted_node_parameters=admitted_node_parameters,
    )

    return graph

def _validate_selection_objectives(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
    plan_nodes: Mapping[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ],
    capabilities: Mapping[
        tuple[str, str],
        tuple[_ObservationCapability, ...],
    ],
) -> None:
    objectives = workflow.selection_objectives
    objective_ids = [objective.objective_id for objective in objectives]
    if len(objective_ids) != len(set(objective_ids)):
        raise WorkflowCompileError(
            "duplicate_selection_objective",
            "Selection Objective IDs must be unique",
            field_path=("selection_objectives",),
        )
    candidate_inputs = {
        objective.candidate_input for objective in objectives
    }
    if len(candidate_inputs) > 1:
        raise WorkflowCompileError(
            "invalid_selection_objective",
            "Weighted Selection Objectives must use one exact Candidate input",
            field_path=("selection_objectives",),
        )
    for index, objective in enumerate(objectives):
        objective_path = ("selection_objectives", index)
        for field_name, input_reference, expected_type in (
            (
                "candidate_input",
                objective.candidate_input,
                "candidate.collection",
            ),
            (
                "score_collection_input",
                objective.score_collection_input,
                "score.collection",
            ),
        ):
            node = graph.nodes_by_id.get(input_reference.node_id)
            if node is None:
                raise WorkflowCompileError(
                    "invalid_selection_objective",
                    f"{field_name} references a Node outside the Workflow",
                    field_path=(*objective_path, field_name, "node_id"),
                )
            node_definition, _ = plan_nodes[node.node_id]
            output = _port_map(node_definition, "outputs").get(
                input_reference.output_port
            )
            if (
                output is None
                or output.port_type.contract_id != expected_type
                or output.multiplicity != "one"
            ):
                raise WorkflowCompileError(
                    "invalid_selection_objective",
                    f"{field_name} must reference one exact {expected_type} "
                    "output value",
                    node_id=node.node_id,
                    field_path=(*objective_path, field_name, "output_port"),
                )
        requested_context = context_selector_canonical(
            objective.context_selector
        )
        output_capabilities = capabilities.get(
            (
                objective.score_collection_input.node_id,
                objective.score_collection_input.output_port,
            ),
            (),
        )
        produced = [
            capability
            for capability in output_capabilities
            if capability.source_partition == objective.source_partition
            and capability.metric == objective.metric
            and capability.method == objective.method
            and capability.context_profile == requested_context
            and capability.subject_grain == "candidate"
            and capability.source_role == "subject"
            and capability.guaranteed_multiplicity == "one"
            and capability.subject_source == objective.candidate_input
            and (
                requested_context.get("kind") != "pairwise"
                or capability.reference_source is not None
            )
            and (
                requested_context.get("pairing_mode")
                != "per_subject_counterpart"
                or capability.pairing_source is not None
            )
        ]
        if len(produced) != 1:
            if any(
                capability.source_partition == objective.source_partition
                and capability.metric == objective.metric
                and capability.context_profile == requested_context
                and capability.subject_source == objective.candidate_input
                and capability.method != objective.method
                for capability in output_capabilities
            ):
                raise WorkflowCompileError(
                    "unsatisfied_selection_objective",
                    "Exact output capability does not use requested Method",
                    node_id=objective.score_collection_input.node_id,
                    field_path=(*objective_path, "method"),
                )
            raise WorkflowCompileError(
                "unsatisfied_selection_objective",
                "Selected scoring Binding cannot guarantee the requested "
                "Observation in the exact source partition with exactly-one "
                "multiplicity",
                node_id=objective.score_collection_input.node_id,
                field_path=(*objective_path, "metric"),
            )

def _validate_observation_selectors(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
    plan_nodes: Mapping[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ],
    capabilities: Mapping[
        tuple[str, str],
        tuple[_ObservationCapability, ...],
    ],
) -> None:
    selectors = workflow.observation_selectors
    selector_ids = [selector.selector_id for selector in selectors]
    if len(selector_ids) != len(set(selector_ids)):
        raise WorkflowCompileError(
            "duplicate_observation_selector",
            "Observation Selector IDs must be unique",
            field_path=("observation_selectors",),
        )
    for index, selector in enumerate(selectors):
        selector_path = ("observation_selectors", index)
        for field_name, input_reference, expected_type in (
            (
                "candidate_input",
                selector.candidate_input,
                "candidate.collection",
            ),
            (
                "score_collection_input",
                selector.score_collection_input,
                "score.collection",
            ),
        ):
            node = graph.nodes_by_id.get(input_reference.node_id)
            if node is None:
                raise WorkflowCompileError(
                    "invalid_observation_selector",
                    f"{field_name} references a Node outside the Workflow",
                    field_path=(*selector_path, field_name, "node_id"),
                )
            node_definition, _ = plan_nodes[node.node_id]
            output = _port_map(node_definition, "outputs").get(
                input_reference.output_port
            )
            if (
                output is None
                or output.port_type.contract_id != expected_type
                or output.multiplicity != "one"
            ):
                raise WorkflowCompileError(
                    "invalid_observation_selector",
                    f"{field_name} must reference one exact {expected_type} "
                    "output value",
                    node_id=node.node_id,
                    field_path=(*selector_path, field_name, "output_port"),
                )
        requested_context = context_selector_canonical(
            selector.context_selector
        )
        output_capabilities = capabilities.get(
            (
                selector.score_collection_input.node_id,
                selector.score_collection_input.output_port,
            ),
            (),
        )
        produced = [
            capability
            for capability in output_capabilities
            if capability.source_partition == selector.source_partition
            and capability.metric == selector.metric
            and capability.method == selector.method
            and capability.context_profile == requested_context
            and capability.subject_grain == "candidate"
            and capability.source_role == "subject"
            and capability.guaranteed_multiplicity == "one"
            and capability.subject_source == selector.candidate_input
        ]
        if len(produced) != 1:
            if any(
                capability.source_partition == selector.source_partition
                and capability.metric == selector.metric
                and capability.context_profile == requested_context
                and capability.subject_grain == "candidate"
                and capability.source_role == "subject"
                and capability.guaranteed_multiplicity == "one"
                and capability.subject_source == selector.candidate_input
                and capability.method != selector.method
                for capability in output_capabilities
            ):
                raise WorkflowCompileError(
                    "unsatisfied_observation_selector",
                    "Exact output capability does not use requested Method",
                    node_id=selector.score_collection_input.node_id,
                    field_path=(*selector_path, "method"),
                )
            raise WorkflowCompileError(
                "unsatisfied_observation_selector",
                "Selected scoring Binding cannot guarantee the requested raw "
                "Observation with exactly-one multiplicity",
                node_id=selector.score_collection_input.node_id,
                field_path=(*selector_path, "metric"),
            )

def _connected_source(
    graph: _AdmittedWorkflowGraph,
    *,
    node_id: str,
    input_port: str,
) -> SelectionInput | None:
    sources = graph.input_sources[node_id].get(input_port, ())
    return sources[0][1] if len(sources) == 1 else None

def _connected_source_field_path(
    graph: _AdmittedWorkflowGraph,
    *,
    node_id: str,
    input_port: str,
    expected_node_id: str,
) -> tuple[str | int, ...]:
    edge_index, source = graph.input_sources[node_id][input_port][0]
    field_name = (
        "source_node_id"
        if source.node_id != expected_node_id
        else "source_port"
    )
    return ("edges", edge_index, field_name)

def _validate_selection_objective_consumers(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
    plan_nodes: Mapping[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ],
    admitted_node_parameters: Mapping[str, AdmittedParameterValues],
) -> None:
    """Bind generic declared selection consumers to exact Workflow sources."""
    objectives = {
        objective.objective_id: objective
        for objective in workflow.selection_objectives
    }
    objective_consumers: dict[str, list[str]] = {
        objective_id: [] for objective_id in objectives
    }
    selectors = {
        selector.selector_id: selector
        for selector in workflow.observation_selectors
    }
    selector_consumers: dict[str, list[str]] = {
        selector_id: [] for selector_id in selectors
    }
    node_indexes = {
        node.node_id: index for index, node in enumerate(workflow.nodes)
    }
    for node_id, (_, binding) in plan_nodes.items():
        node_index = node_indexes[node_id]
        selector_consumption = binding.observation_selector_consumption
        if selector_consumption is not None:
            parameters = admitted_node_parameters[node_id]
            parameter_name = selector_consumption.selector_id_parameter
            selector_id = parameters[parameter_name]
            selector = selectors.get(selector_id)
            if selector is None:
                raise WorkflowCompileError(
                    "unsatisfied_selector",
                    "Selection selector does not resolve one Workflow "
                    "Observation Selector",
                    node_id=node_id,
                    field_path=(
                        "nodes",
                        node_index,
                        "node_parameters",
                        parameter_name or "selector_id",
                    ),
                )
            for label, port_name, reference in (
                (
                    "Candidate",
                    selector_consumption.candidate_input_port,
                    selector.candidate_input,
                ),
                (
                    "Score Collection",
                    selector_consumption.score_collection_input_port,
                    selector.score_collection_input,
                ),
            ):
                connected = _connected_source(
                    graph,
                    node_id=node_id,
                    input_port=port_name,
                )
                if connected != reference:
                    raise WorkflowCompileError(
                        "unsatisfied_selector",
                        f"Selection {label} input does not match the exact "
                        "Workflow Observation Selector source",
                        node_id=node_id,
                        field_path=_connected_source_field_path(
                            graph,
                            node_id=node_id,
                            input_port=port_name,
                            expected_node_id=reference.node_id,
                        ),
                    )
            selector_consumers[selector.selector_id].append(node_id)
            continue
        consumption = binding.selection_objective_consumption
        if consumption is None:
            continue
        parameters = admitted_node_parameters[node_id]
        if consumption.objective_id_parameter is not None:
            parameter_name = consumption.objective_id_parameter
            raw_objective_ids = (parameters[parameter_name],)
        else:
            parameter_name = consumption.objective_ids_parameter
            raw_objective_ids = tuple(parameters[parameter_name])
        selected_objectives = tuple(
            objectives[objective_id]
            for objective_id in raw_objective_ids
            if objective_id in objectives
        )
        if (
            not raw_objective_ids
            or len(selected_objectives) != len(raw_objective_ids)
        ):
            raise WorkflowCompileError(
                "unsatisfied_selector",
                "Selection selector does not resolve one Workflow Selection "
                "Objective for every declared ID",
                node_id=node_id,
                field_path=(
                    "nodes",
                    node_index,
                    "node_parameters",
                    parameter_name,
                ),
            )
        for label, port_name, reference_name in (
            (
                "Candidate",
                consumption.candidate_input_port,
                "candidate_input",
            ),
            (
                "Score Collection",
                consumption.score_collection_input_port,
                "score_collection_input",
            ),
        ):
            connected = _connected_source(
                graph,
                node_id=node_id,
                input_port=port_name,
            )
            expected_sources = {
                (
                    getattr(objective, reference_name).node_id,
                    getattr(objective, reference_name).output_port,
                )
                for objective in selected_objectives
            }
            connected_source = (
                (connected.node_id, connected.output_port)
                if connected is not None
                else None
            )
            if (
                len(expected_sources) != 1
                or connected_source not in expected_sources
            ):
                field_path = (
                    (
                        "nodes",
                        node_index,
                        "node_parameters",
                        parameter_name,
                    )
                    if len(expected_sources) != 1
                    else _connected_source_field_path(
                        graph,
                        node_id=node_id,
                        input_port=port_name,
                        expected_node_id=next(iter(expected_sources))[0],
                    )
                )
                raise WorkflowCompileError(
                    "unsatisfied_selector",
                    f"Selection {label} input does not match the exact "
                    "Workflow Selection Objective sources",
                    node_id=node_id,
                    field_path=field_path,
                )
        for objective in selected_objectives:
            objective_consumers[objective.objective_id].append(node_id)

    for index, objective in enumerate(workflow.selection_objectives):
        consumers = objective_consumers[objective.objective_id]
        if not consumers:
            raise WorkflowCompileError(
                "unconsumed_selection_objective",
                "Selection Objective is not consumed by an explicit "
                "Selection Node",
                field_path=("selection_objectives", index),
            )
        if len(consumers) != 1:
            raise WorkflowCompileError(
                "multiple_selection_objective_consumers",
                "Selection Objective must be consumed by exactly one explicit "
                f"Selection Node; resolved consumers: {consumers!r}",
                field_path=("selection_objectives", index),
            )
    for index, selector in enumerate(workflow.observation_selectors):
        consumers = selector_consumers[selector.selector_id]
        if not consumers:
            raise WorkflowCompileError(
                "unconsumed_observation_selector",
                "Observation Selector is not consumed by an explicit "
                "Selection Node",
                field_path=("observation_selectors", index),
            )
        if len(consumers) != 1:
            raise WorkflowCompileError(
                "multiple_observation_selector_consumers",
                "Observation Selector must be consumed by exactly one explicit "
                f"Selection Node; resolved consumers: {consumers!r}",
                field_path=("observation_selectors", index),
            )

def _capability_source(
    graph: _AdmittedWorkflowGraph,
    *,
    node_id: str,
    direction: str | None,
    port: str | None,
) -> SelectionInput | None:
    if port is None:
        return None
    if direction == "output":
        return SelectionInput(node_id, port)
    return _connected_source(
        graph,
        node_id=node_id,
        input_port=port,
    )

def _capability_matches_filter(
    capability: _ObservationCapability,
    filter_descriptor: Mapping[str, Any],
    catalog: FrozenCatalog,
) -> bool:
    source_partition = filter_descriptor.get("source_partition")
    metric = filter_descriptor.get("metric")
    method = filter_descriptor.get("method")
    context_profile = filter_descriptor.get("context_profile")
    return (
        (source_partition is None or capability.source_partition == source_partition)
        and (
            metric is None
            or capability.metric == catalog.require_reference(*metric.key)
        )
        and (
            method is None
            or capability.method == catalog.require_reference(*method.key)
        )
        and (
            context_profile is None
            or capability.context_profile == context_profile
        )
    )

def _produced_observation_method(
    graph: _AdmittedWorkflowGraph,
    *,
    node_id: str,
    declaration: ProducedObservationDefinition,
    binding_method: ContractIdentity,
    plan_nodes: Mapping[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ],
) -> ContractIdentity | None:
    if declaration.method_direction != "input":
        return binding_method
    source = _connected_source(
        graph,
        node_id=node_id,
        input_port=declaration.method_port,
    )
    if source is None:
        return None
    source_plan = plan_nodes.get(source.node_id)
    if source_plan is None:
        return None
    return source_plan[1].method


def _capability_canonical(
    capability: _ObservationCapability,
) -> dict[str, Any]:
    def reference(value: ExactContractReference | None) -> Any:
        if value is None:
            return None
        return {
            "contract_kind": value.contract_kind,
            "contract_id": value.contract_id,
            "contract_version": value.contract_version,
            "contract_digest": value.contract_digest,
        }

    def source(value: SelectionInput | None) -> Any:
        return None if value is None else selection_input_canonical(value)

    return {
        "source_partition": capability.source_partition,
        "metric": reference(capability.metric),
        "method": reference(capability.method),
        "context_profile": capability.context_profile,
        "subject_grain": capability.subject_grain,
        "source_role": capability.source_role,
        "guaranteed_multiplicity": capability.guaranteed_multiplicity,
        "subject_source": source(capability.subject_source),
        "reference_source": source(capability.reference_source),
        "pairing_source": source(capability.pairing_source),
    }

def _derive_observation_capabilities(
    graph: _AdmittedWorkflowGraph,
    *,
    catalog: FrozenCatalog,
    plan_nodes: Mapping[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ],
) -> dict[tuple[str, str], tuple[_ObservationCapability, ...]]:
    """Derive exact output capabilities from closed fixed/propagation contracts."""
    capabilities: dict[
        tuple[str, str],
        tuple[_ObservationCapability, ...],
    ] = {}
    for node_id in graph.node_order:
        _, binding = plan_nodes[node_id]
        for declaration in binding.produced_observations:
            observation_method = _produced_observation_method(
                graph,
                node_id=node_id,
                declaration=declaration,
                binding_method=binding.method,
                plan_nodes=plan_nodes,
            )
            capability = _ObservationCapability(
                source_partition=declaration.output_partition,
                metric=catalog.require_reference(*declaration.metric.key),
                method=(
                    catalog.require_reference(*observation_method.key)
                    if observation_method is not None
                    else None
                ),
                context_profile=declaration.context_profile,
                subject_grain=declaration.subject_grain,
                source_role=declaration.source_role,
                guaranteed_multiplicity=declaration.guaranteed_multiplicity,
                subject_source=_capability_source(
                    graph,
                    node_id=node_id,
                    direction=declaration.subject_direction,
                    port=declaration.subject_port,
                ),
                reference_source=_capability_source(
                    graph,
                    node_id=node_id,
                    direction=declaration.reference_direction,
                    port=declaration.reference_port,
                ),
                pairing_source=_capability_source(
                    graph,
                    node_id=node_id,
                    direction=declaration.pairing_direction,
                    port=declaration.pairing_port,
                ),
            )
            key = (node_id, declaration.output_port)
            capabilities[key] = (*capabilities.get(key, ()), capability)

        propagation = binding.observation_propagation
        if propagation is None:
            continue
        propagated: list[_ObservationCapability] = []
        for input_port in propagation.input_ports:
            for _, source in graph.input_sources[node_id].get(input_port, ()):
                propagated.extend(
                    capabilities.get(
                        (source.node_id, source.output_port),
                        (),
                    )
                )
        if propagation.mode == "filter":
            propagated = [
                capability
                for capability in propagated
                if _capability_matches_filter(
                    capability,
                    propagation.filter,
                    catalog,
                )
            ]
        unique: dict[bytes, _ObservationCapability] = {}
        for capability in propagated:
            unique[canonical_json_bytes(_capability_canonical(capability))] = (
                capability
            )
        capabilities[(node_id, propagation.output_port)] = tuple(
            unique.values()
        )
    return capabilities
