"""Private graph, Port, and selection-consumer compilation."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import math
from typing import Any

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
    _thaw_json,
)


def _port_map(contract: Any, direction: str) -> dict[str, Mapping[str, Any]]:
    return {
        port["name"]: port
        for port in contract.descriptor.get(direction, ())
    }

def _validate_static_semantics(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
    admitted_node_parameters: Mapping[str, AdmittedParameterValues],
) -> tuple[str, ...]:
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

    incoming: dict[tuple[str, str], int] = {}
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
        source_contract = catalog.require_contract(
            "node_type",
            source.node_type_id,
            source.node_type_version,
        )
        target_contract = catalog.require_contract(
            "node_type",
            target.node_type_id,
            target.node_type_version,
        )
        source_port = _port_map(source_contract, "outputs").get(
            edge.source_port
        )
        target_port = _port_map(target_contract, "inputs").get(
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
        if source_port["port_type"] != target_port["port_type"]:
            raise WorkflowCompileError(
                "port_type_mismatch",
                "Connected Ports do not share one exact nominal Port Type",
                node_id=target.node_id,
                field_path=("edges", index),
            )
        if (
            source_port["multiplicity"] == "many"
            and target_port["multiplicity"] == "one"
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
        incoming_key = (target.node_id, edge.target_port)
        incoming[incoming_key] = incoming.get(incoming_key, 0) + 1
        if (
            incoming[incoming_key] > 1
            and target_port.get("multiplicity") != "many"
        ):
            raise WorkflowCompileError(
                "duplicate_input_connection",
                f"Input Port {edge.target_port!r} accepts one connection",
                node_id=target.node_id,
                field_path=("edges", index, "target_port"),
            )
        adjacency[source.node_id].append(target.node_id)
        indegree[target.node_id] += 1

    plan_nodes: dict[str, tuple[Any, Any]] = {}
    for index, node in enumerate(workflow.nodes):
        node_contract = catalog.require_contract(
            "node_type",
            node.node_type_id,
            node.node_type_version,
        )
        binding = catalog.require_contract(
            "binding",
            node.binding_id,
            node.binding_version,
        )
        if binding.descriptor.get("node_type") != node_contract.reference():
            raise WorkflowCompileError(
                "binding_ownership_mismatch",
                "Selected Binding does not belong to the selected Node Type",
                node_id=node.node_id,
                field_path=("nodes", index, "binding_id"),
            )
        for port in node_contract.descriptor.get("inputs", ()):
            if (
                port.get("required") is True
                and incoming.get((node.node_id, port["name"]), 0) == 0
            ):
                raise WorkflowCompileError(
                    "required_input_missing",
                    f"Required input Port {port['name']!r} is not connected",
                    node_id=node.node_id,
                    field_path=("nodes", index),
                )
        for constraint in node_contract.descriptor.get(
            "input_constraints",
            (),
        ):
            if constraint.get("kind") != "exactly_one":
                raise WorkflowCompileError(
                    "invalid_input_constraint",
                    "Node Type contains an unsupported input constraint",
                    node_id=node.node_id,
                    field_path=("nodes", index),
                )
            connected = sum(
                incoming.get((node.node_id, port_name), 0)
                for port_name in constraint["ports"]
            )
            if connected != 1:
                raise WorkflowCompileError(
                    "input_constraint_unsatisfied",
                    "Exactly one constrained input Port must be connected",
                    node_id=node.node_id,
                    field_path=("nodes", index),
                )
        plan_nodes[node.node_id] = (node_contract, binding)

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

    _validate_selection_objectives(
        workflow,
        nodes_by_id=nodes_by_id,
        plan_nodes=plan_nodes,
        node_order=tuple(order),
    )
    _validate_observation_selectors(
        workflow,
        nodes_by_id=nodes_by_id,
        plan_nodes=plan_nodes,
        node_order=tuple(order),
    )
    _validate_selection_objective_consumers(
        workflow,
        plan_nodes=plan_nodes,
        admitted_node_parameters=admitted_node_parameters,
    )

    return tuple(order)

def _validate_selection_objectives(
    workflow: WorkflowDocument,
    *,
    nodes_by_id: Mapping[str, WorkflowNodeInstance],
    plan_nodes: Mapping[str, tuple[Any, Any]],
    node_order: tuple[str, ...],
) -> None:
    objectives = workflow.selection_objectives
    objective_ids = [objective.objective_id for objective in objectives]
    if len(objective_ids) != len(set(objective_ids)):
        raise WorkflowCompileError(
            "duplicate_selection_objective",
            "Selection Objective IDs must be unique",
            field_path=("selection_objectives",),
        )
    try:
        objective_weight_total = math.fsum(
            float(objective.weight) for objective in objectives
        )
    except (OverflowError, ValueError):
        objective_weight_total = math.inf
    if objectives and (
        not math.isfinite(objective_weight_total)
        or objective_weight_total <= 0
    ):
        raise WorkflowCompileError(
            "invalid_selection_objective",
            "Selection Objectives require a finite positive total weight",
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
    capabilities = _derive_observation_capabilities(
        workflow,
        plan_nodes=plan_nodes,
        node_order=node_order,
    )
    for index, objective in enumerate(objectives):
        objective_path = ("selection_objectives", index)
        input_contracts: dict[str, Any] = {}
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
            node = nodes_by_id.get(input_reference.node_id)
            if node is None:
                raise WorkflowCompileError(
                    "invalid_selection_objective",
                    f"{field_name} references a Node outside the Workflow",
                    field_path=(*objective_path, field_name, "node_id"),
                )
            node_contract, binding = plan_nodes[node.node_id]
            output = _port_map(node_contract, "outputs").get(
                input_reference.output_port
            )
            if (
                output is None
                or output.get("port_type", {}).get("contract_id")
                != expected_type
                or output.get("multiplicity") != "one"
            ):
                raise WorkflowCompileError(
                    "invalid_selection_objective",
                    f"{field_name} must reference one exact {expected_type} "
                    "output value",
                    node_id=node.node_id,
                    field_path=(*objective_path, field_name, "output_port"),
                )
            input_contracts[field_name] = (node_contract, binding, output)

        requested_method = {
            "contract_kind": "method",
            "contract_id": objective.method.contract_id,
            "contract_version": objective.method.contract_version,
            "contract_digest": objective.method.contract_digest,
        }
        requested_metric = {
            "contract_kind": "metric",
            "contract_id": objective.metric.contract_id,
            "contract_version": objective.metric.contract_version,
            "contract_digest": objective.metric.contract_digest,
        }
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
            if capability.get("source_partition")
            == objective.source_partition
            and capability.get("metric") == requested_metric
            and capability.get("method") == requested_method
            and capability.get("context_profile")
            == context_selector_canonical(
                objective.context_selector
            )
            and capability.get("subject_grain") == "candidate"
            and capability.get("source_role") == "subject"
            and capability.get("guaranteed_multiplicity") == "one"
            and capability.get("subject_source")
            == selection_input_canonical(objective.candidate_input)
            and (
                context_selector_canonical(
                    objective.context_selector
                ).get("kind")
                != "pairwise"
                or capability.get("reference_source") is not None
            )
            and (
                context_selector_canonical(
                    objective.context_selector
                ).get("pairing_mode")
                != "per_subject_counterpart"
                or capability.get("pairing_source") is not None
            )
        ]
        if len(produced) != 1:
            if any(
                capability.get("source_partition")
                == objective.source_partition
                and capability.get("metric") == requested_metric
                and capability.get("context_profile")
                == context_selector_canonical(
                    objective.context_selector
                )
                and capability.get("subject_source")
                == selection_input_canonical(objective.candidate_input)
                and capability.get("method") != requested_method
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
    nodes_by_id: Mapping[str, WorkflowNodeInstance],
    plan_nodes: Mapping[str, tuple[Any, Any]],
    node_order: tuple[str, ...],
) -> None:
    selectors = workflow.observation_selectors
    selector_ids = [selector.selector_id for selector in selectors]
    if len(selector_ids) != len(set(selector_ids)):
        raise WorkflowCompileError(
            "duplicate_observation_selector",
            "Observation Selector IDs must be unique",
            field_path=("observation_selectors",),
        )
    capabilities = _derive_observation_capabilities(
        workflow,
        plan_nodes=plan_nodes,
        node_order=node_order,
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
            node = nodes_by_id.get(input_reference.node_id)
            if node is None:
                raise WorkflowCompileError(
                    "invalid_observation_selector",
                    f"{field_name} references a Node outside the Workflow",
                    field_path=(*selector_path, field_name, "node_id"),
                )
            node_contract, _ = plan_nodes[node.node_id]
            output = _port_map(node_contract, "outputs").get(
                input_reference.output_port
            )
            if (
                output is None
                or output.get("port_type", {}).get("contract_id")
                != expected_type
                or output.get("multiplicity") != "one"
            ):
                raise WorkflowCompileError(
                    "invalid_observation_selector",
                    f"{field_name} must reference one exact {expected_type} "
                    "output value",
                    node_id=node.node_id,
                    field_path=(*selector_path, field_name, "output_port"),
                )
        requested_method = {
            "contract_kind": "method",
            "contract_id": selector.method.contract_id,
            "contract_version": selector.method.contract_version,
            "contract_digest": selector.method.contract_digest,
        }
        requested_metric = {
            "contract_kind": "metric",
            "contract_id": selector.metric.contract_id,
            "contract_version": selector.metric.contract_version,
            "contract_digest": selector.metric.contract_digest,
        }
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
            if capability.get("source_partition")
            == selector.source_partition
            and capability.get("metric") == requested_metric
            and capability.get("method") == requested_method
            and capability.get("context_profile")
            == context_selector_canonical(
                selector.context_selector
            )
            and capability.get("subject_grain") == "candidate"
            and capability.get("source_role") == "subject"
            and capability.get("guaranteed_multiplicity") == "one"
            and capability.get("subject_source")
            == selection_input_canonical(selector.candidate_input)
        ]
        if len(produced) != 1:
            if any(
                capability.get("source_partition")
                == selector.source_partition
                and capability.get("metric") == requested_metric
                and capability.get("context_profile")
                == context_selector_canonical(
                    selector.context_selector
                )
                and capability.get("subject_grain") == "candidate"
                and capability.get("source_role") == "subject"
                and capability.get("guaranteed_multiplicity") == "one"
                and capability.get("subject_source")
                == selection_input_canonical(selector.candidate_input)
                and capability.get("method") != requested_method
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
    workflow: WorkflowDocument,
    *,
    node_id: str,
    input_port: str,
) -> SelectionInput | None:
    sources = [
        SelectionInput(edge.source_node_id, edge.source_port)
        for edge in workflow.edges
        if edge.target_node_id == node_id
        and edge.target_port == input_port
    ]
    return sources[0] if len(sources) == 1 else None

def _connected_source_field_path(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    input_port: str,
    expected_node_id: str,
) -> tuple[str | int, ...]:
    edge_index, edge = next(
        (index, edge)
        for index, edge in enumerate(workflow.edges)
        if edge.target_node_id == node_id and edge.target_port == input_port
    )
    field_name = (
        "source_node_id"
        if edge.source_node_id != expected_node_id
        else "source_port"
    )
    return ("edges", edge_index, field_name)

def _validate_selection_objective_consumers(
    workflow: WorkflowDocument,
    *,
    plan_nodes: Mapping[str, tuple[Any, Any]],
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
        selector_consumption = binding.descriptor.get(
            "observation_selector_consumption"
        )
        if isinstance(selector_consumption, Mapping):
            parameters = admitted_node_parameters[node_id]
            parameter_name = selector_consumption.get(
                "selector_id_parameter"
            )
            selector_id = (
                parameters.get(parameter_name)
                if isinstance(parameter_name, str)
                else None
            )
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
                    selector_consumption.get("candidate_input_port"),
                    selector.candidate_input,
                ),
                (
                    "Score Collection",
                    selector_consumption.get(
                        "score_collection_input_port"
                    ),
                    selector.score_collection_input,
                ),
            ):
                connected = (
                    _connected_source(
                        workflow,
                        node_id=node_id,
                        input_port=port_name,
                    )
                    if isinstance(port_name, str)
                    else None
                )
                if connected != reference:
                    raise WorkflowCompileError(
                        "unsatisfied_selector",
                        f"Selection {label} input does not match the exact "
                        "Workflow Observation Selector source",
                        node_id=node_id,
                        field_path=_connected_source_field_path(
                            workflow,
                            node_id=node_id,
                            input_port=port_name,
                            expected_node_id=reference.node_id,
                        ),
                    )
            selector_consumers[selector.selector_id].append(node_id)
            continue
        consumption = binding.descriptor.get(
            "selection_objective_consumption"
        )
        if not isinstance(consumption, Mapping):
            continue
        parameters = admitted_node_parameters[node_id]
        scalar_parameter = consumption.get("objective_id_parameter")
        ordered_parameter = consumption.get("objective_ids_parameter")
        if isinstance(scalar_parameter, str):
            parameter_name = scalar_parameter
            raw_objective_ids = (parameters.get(parameter_name),)
        elif isinstance(ordered_parameter, str):
            parameter_name = ordered_parameter
            selected = parameters.get(parameter_name)
            raw_objective_ids = (
                tuple(selected)
                if isinstance(selected, (list, tuple))
                else ()
            )
        else:
            parameter_name = "objective_id"
            raw_objective_ids = ()
        selected_objectives = tuple(
            objectives[objective_id]
            for objective_id in raw_objective_ids
            if isinstance(objective_id, str)
            and objective_id in objectives
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
            ("Candidate", consumption.get("candidate_input_port"), "candidate_input"),
            (
                "Score Collection",
                consumption.get("score_collection_input_port"),
                "score_collection_input",
            ),
        ):
            connected = (
                _connected_source(
                    workflow,
                    node_id=node_id,
                    input_port=port_name,
                )
                if isinstance(port_name, str)
                else None
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
                        workflow,
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
    workflow: WorkflowDocument,
    *,
    node_id: str,
    direction: object,
    port: object,
) -> dict[str, str] | None:
    if not isinstance(port, str):
        return None
    if direction == "output":
        return {"node_id": node_id, "output_port": port}
    if direction == "input":
        source = _connected_source(
            workflow,
            node_id=node_id,
            input_port=port,
        )
        return None if source is None else selection_input_canonical(source)
    return None

def _capability_matches_filter(
    capability: Mapping[str, Any],
    filter_descriptor: Mapping[str, Any],
) -> bool:
    for name in (
        "source_partition",
        "metric",
        "method",
        "context_profile",
    ):
        expected = filter_descriptor.get(name)
        if expected is not None and capability.get(name) != expected:
            return False
    return True

def _produced_observation_method(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    declaration: Mapping[str, Any],
    binding_method: object,
    plan_nodes: Mapping[str, tuple[Any, Any]],
) -> object:
    direction = declaration.get("method_direction")
    port = declaration.get("method_port")
    if direction != "input" or not isinstance(port, str):
        return binding_method
    source = _connected_source(
        workflow,
        node_id=node_id,
        input_port=port,
    )
    if source is None:
        return None
    source_plan = plan_nodes.get(source.node_id)
    if source_plan is None:
        return None
    _, source_binding = source_plan
    return source_binding.descriptor.get("method")

def _derive_observation_capabilities(
    workflow: WorkflowDocument,
    *,
    plan_nodes: Mapping[str, tuple[Any, Any]],
    node_order: tuple[str, ...],
) -> dict[tuple[str, str], tuple[Mapping[str, Any], ...]]:
    """Derive exact output capabilities from closed fixed/propagation contracts."""
    capabilities: dict[
        tuple[str, str],
        tuple[Mapping[str, Any], ...],
    ] = {}
    for node_id in node_order:
        _, binding = plan_nodes[node_id]
        method = binding.descriptor.get("method")
        for declaration in binding.descriptor.get(
            "produced_observations",
            (),
        ):
            output_port = declaration.get("output_port")
            if not isinstance(output_port, str):
                continue
            observation_method = _produced_observation_method(
                workflow,
                node_id=node_id,
                declaration=declaration,
                binding_method=method,
                plan_nodes=plan_nodes,
            )
            capability = {
                "source_partition": declaration["output_partition"],
                "metric": declaration.get("metric"),
                "method": observation_method,
                "context_profile": declaration.get("context_profile"),
                "subject_grain": declaration.get("subject_grain"),
                "source_role": declaration.get("source_role"),
                "guaranteed_multiplicity": declaration.get(
                    "guaranteed_multiplicity"
                ),
                "subject_source": _capability_source(
                    workflow,
                    node_id=node_id,
                    direction=declaration.get("subject_direction"),
                    port=declaration.get("subject_port"),
                ),
                "reference_source": _capability_source(
                    workflow,
                    node_id=node_id,
                    direction=declaration.get("reference_direction"),
                    port=declaration.get("reference_port"),
                ),
                "pairing_source": _capability_source(
                    workflow,
                    node_id=node_id,
                    direction=declaration.get("pairing_direction"),
                    port=declaration.get("pairing_port"),
                ),
            }
            key = (node_id, output_port)
            capabilities[key] = (*capabilities.get(key, ()), capability)

        propagation = binding.descriptor.get("observation_propagation")
        if not isinstance(propagation, Mapping):
            continue
        output_port = propagation.get("output_port")
        input_ports = propagation.get("input_ports")
        mode = propagation.get("mode")
        if (
            not isinstance(output_port, str)
            or not isinstance(input_ports, (list, tuple))
            or propagation.get("schema_version") != "2.1.0"
            or mode not in {"pass_through", "union", "filter"}
        ):
            continue
        propagated: list[Mapping[str, Any]] = []
        for input_port in input_ports:
            if not isinstance(input_port, str):
                continue
            sources = [
                edge
                for edge in workflow.edges
                if edge.target_node_id == node_id
                and edge.target_port == input_port
            ]
            for edge in sources:
                propagated.extend(
                    capabilities.get(
                        (edge.source_node_id, edge.source_port),
                        (),
                    )
                )
        if mode == "filter":
            filter_descriptor = propagation.get("filter")
            if not isinstance(filter_descriptor, Mapping):
                propagated = []
            else:
                propagated = [
                    capability
                    for capability in propagated
                    if _capability_matches_filter(
                        capability,
                        filter_descriptor,
                    )
                ]
        unique: dict[bytes, Mapping[str, Any]] = {}
        for capability in propagated:
            unique[canonical_json_bytes(_thaw_json(capability))] = capability
        capabilities[(node_id, output_port)] = tuple(unique.values())
    return capabilities
