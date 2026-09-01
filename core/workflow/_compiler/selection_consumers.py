from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.parameters.model import AdmittedParameterValues
from core.scoring.selection import (
    ObservationSelector,
    SelectionObjective,
)
from core.workflow._compiler.graph import (
    _AdmittedWorkflowGraph,
    _PlanNodes,
    _connected_source,
)
from core.workflow.document import WorkflowDocument
from core.workflow.errors import WorkflowCompileError


@dataclass(frozen=True, slots=True)
class _SelectionConsumerCompilation:
    objectives_by_node: Mapping[str, tuple[SelectionObjective, ...]]
    selectors_by_node: Mapping[str, tuple[ObservationSelector, ...]]


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


def _compile_selection_consumers(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
    plan_nodes: _PlanNodes,
    admitted_node_parameters: Mapping[str, AdmittedParameterValues],
) -> _SelectionConsumerCompilation:
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
    objectives_by_node: dict[str, tuple[SelectionObjective, ...]] = {
        node_id: () for node_id in plan_nodes
    }
    selectors_by_node: dict[str, tuple[ObservationSelector, ...]] = {
        node_id: () for node_id in plan_nodes
    }
    for node_index, node in enumerate(workflow.nodes):
        node_id = node.node_id
        binding = plan_nodes[node_id][1]
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
                        parameter_name,
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
            selectors_by_node[node_id] = (selector,)
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
        if len(selected_objectives) != len(raw_objective_ids):
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
        candidate_sources = {
            objective.candidate_input for objective in selected_objectives
        }
        connected_candidate = _connected_source(
            graph,
            node_id=node_id,
            input_port=consumption.candidate_input_port,
        )
        if (
            len(candidate_sources) != 1
            or connected_candidate not in candidate_sources
        ):
            candidate_field_path = (
                (
                    "nodes",
                    node_index,
                    "node_parameters",
                    parameter_name,
                )
                if len(candidate_sources) != 1
                else _connected_source_field_path(
                    graph,
                    node_id=node_id,
                    input_port=consumption.candidate_input_port,
                    expected_node_id=next(iter(candidate_sources)).node_id,
                )
            )
            raise WorkflowCompileError(
                "unsatisfied_selector",
                "Selection Candidate input does not match the exact Workflow "
                "Selection Objective sources",
                node_id=node_id,
                field_path=candidate_field_path,
            )
        connected_scores = {
            source
            for _, source in graph.input_sources[node_id][
                consumption.score_collection_input_port
            ]
        }
        expected_scores = {
            objective.score_collection_input
            for objective in selected_objectives
        }
        if connected_scores != expected_scores:
            score_field_path = (
                _connected_source_field_path(
                    graph,
                    node_id=node_id,
                    input_port=consumption.score_collection_input_port,
                    expected_node_id=next(iter(expected_scores)).node_id,
                )
                if len(expected_scores) == 1 and len(connected_scores) == 1
                else (
                    "nodes",
                    node_index,
                    "node_parameters",
                    parameter_name,
                )
            )
            raise WorkflowCompileError(
                "unsatisfied_selector",
                "Selection Score Collection input does not match the exact "
                "Workflow Selection Objective sources",
                node_id=node_id,
                field_path=score_field_path,
            )
        objectives_by_node[node_id] = selected_objectives
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
    return _SelectionConsumerCompilation(
        objectives_by_node=objectives_by_node,
        selectors_by_node=selectors_by_node,
    )
