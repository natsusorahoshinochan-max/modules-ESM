from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.catalog.canonical import canonical_json_bytes
from core.scoring.selection import (
    SelectionInput,
    context_selector_canonical,
    selection_input_canonical,
)
from core.workflow._compiler.graph import (
    _AdmittedWorkflowGraph,
    _PlanNodes,
    _connected_source,
)
from core.workflow.document import (
    ContractLockEntry,
    WorkflowDocument,
)
from core.workflow.errors import WorkflowCompileError
from datatypes.exact_reference import ExactContractReference


@dataclass(frozen=True, slots=True)
class _ObservationCapability:
    source_partition: str
    metric: ContractLockEntry
    method: ContractLockEntry | None
    context_profile: Mapping[str, Any]
    subject_grain: str
    source_role: str
    guaranteed_multiplicity: str
    subject_source: SelectionInput | None
    reference_source: SelectionInput | None
    pairing_source: SelectionInput | None


type _LockedContracts = Mapping[tuple[str, str, str], ContractLockEntry]


def _same_exact_contract(
    locked: ContractLockEntry | None,
    reference: ExactContractReference | None,
) -> bool:
    if locked is None or reference is None:
        return locked is None and reference is None
    return (
        locked.key == reference.key
        and locked.contract_digest == reference.contract_digest
    )


def _validate_selection_inputs(
    graph: _AdmittedWorkflowGraph,
    *,
    error_code: str,
    item_path: tuple[str | int, ...],
    candidate_input: SelectionInput,
    score_collection_input: SelectionInput,
) -> None:
    for field_name, input_reference, expected_type in (
        ("candidate_input", candidate_input, "candidate.collection"),
        ("score_collection_input", score_collection_input, "score.collection"),
    ):
        if input_reference.node_id not in graph.nodes_by_id:
            raise WorkflowCompileError(
                error_code,
                f"{field_name} references a Node outside the Workflow",
                field_path=(*item_path, field_name, "node_id"),
            )
        output = graph.output_ports_by_node[input_reference.node_id].get(
            input_reference.output_port
        )
        if (
            output is None
            or output.port_type.contract_id != expected_type
            or output.multiplicity != "one"
        ):
            raise WorkflowCompileError(
                error_code,
                f"{field_name} must reference one exact {expected_type} output value",
                node_id=input_reference.node_id,
                field_path=(*item_path, field_name, "output_port"),
            )


def _validate_selection_capabilities(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
    plan_nodes: _PlanNodes,
    lock_by_key: _LockedContracts,
) -> None:
    capabilities = _derive_observation_capabilities(
        graph,
        lock_by_key=lock_by_key,
        plan_nodes=plan_nodes,
    )
    _validate_selection_objectives(
        workflow,
        graph=graph,
        capabilities=capabilities,
    )
    _validate_observation_selectors(
        workflow,
        graph=graph,
        capabilities=capabilities,
    )


def _validate_selection_objectives(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
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
        _validate_selection_inputs(
            graph,
            error_code="invalid_selection_objective",
            item_path=objective_path,
            candidate_input=objective.candidate_input,
            score_collection_input=objective.score_collection_input,
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
            and _same_exact_contract(capability.metric, objective.metric)
            and _same_exact_contract(capability.method, objective.method)
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
                and _same_exact_contract(capability.metric, objective.metric)
                and capability.context_profile == requested_context
                and capability.subject_source == objective.candidate_input
                and not _same_exact_contract(
                    capability.method,
                    objective.method,
                )
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
        _validate_selection_inputs(
            graph,
            error_code="invalid_observation_selector",
            item_path=selector_path,
            candidate_input=selector.candidate_input,
            score_collection_input=selector.score_collection_input,
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
            and _same_exact_contract(capability.metric, selector.metric)
            and _same_exact_contract(capability.method, selector.method)
            and capability.context_profile == requested_context
            and capability.subject_grain == "candidate"
            and capability.source_role == "subject"
            and capability.guaranteed_multiplicity == "one"
            and capability.subject_source == selector.candidate_input
        ]
        if len(produced) != 1:
            if any(
                capability.source_partition == selector.source_partition
                and _same_exact_contract(capability.metric, selector.metric)
                and capability.context_profile == requested_context
                and capability.subject_grain == "candidate"
                and capability.source_role == "subject"
                and capability.guaranteed_multiplicity == "one"
                and capability.subject_source == selector.candidate_input
                and not _same_exact_contract(
                    capability.method,
                    selector.method,
                )
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
    lock_by_key: _LockedContracts,
) -> bool:
    source_partition = filter_descriptor.get("source_partition")
    metric = filter_descriptor.get("metric")
    method = filter_descriptor.get("method")
    context_profile = filter_descriptor.get("context_profile")
    return (
        (source_partition is None or capability.source_partition == source_partition)
        and (
            metric is None
            or capability.metric == lock_by_key[metric.key]
        )
        and (
            method is None
            or capability.method == lock_by_key[method.key]
        )
        and (
            context_profile is None
            or capability.context_profile == context_profile
        )
    )


def _capability_canonical(
    capability: _ObservationCapability,
) -> dict[str, Any]:
    def reference(value: ContractLockEntry | None) -> Any:
        return None if value is None else value.canonical_projection()

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
    lock_by_key: _LockedContracts,
    plan_nodes: _PlanNodes,
) -> dict[tuple[str, str], tuple[_ObservationCapability, ...]]:
    """Derive exact output capabilities from closed fixed/propagation contracts."""
    capabilities: dict[
        tuple[str, str],
        tuple[_ObservationCapability, ...],
    ] = {}
    for node_id in graph.node_order:
        _, binding = plan_nodes[node_id]
        for declaration in binding.produced_observations:
            method_source = (
                _connected_source(
                    graph,
                    node_id=node_id,
                    input_port=declaration.method_port,
                )
                if declaration.method_direction == "input"
                else None
            )
            observation_method = (
                plan_nodes[method_source.node_id][1].method
                if method_source is not None
                else binding.method
                if declaration.method_direction != "input"
                else None
            )
            capability = _ObservationCapability(
                source_partition=declaration.output_partition,
                metric=lock_by_key[declaration.metric.key],
                method=(
                    lock_by_key[observation_method.key]
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
                    lock_by_key,
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
