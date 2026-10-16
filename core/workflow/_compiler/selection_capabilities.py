from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.catalog.observation import ObservationPropagationFilter
from datatypes.observation import ObservationContextProfile
from core.catalog.result_adoption import AdoptedObservation
from datatypes.observation import PairwiseContextProfile
from datatypes.i_json import canonical_json_bytes
from core.catalog.model import FrozenCatalog

from core.scoring.selection import (
    SelectionInput,
    context_selector_canonical,
    selection_input_canonical,
)
from core.workflow._compiler.graph import (
    _AdmittedWorkflowGraph,
    _connected_source,
)
from core.workflow.document import WorkflowDocument
from core.workflow.errors import WorkflowCompileError
from datatypes.exact_reference import ExactContractReference


@dataclass(frozen=True, slots=True)
class _ObservationCapability:
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference | None
    context_profile: ObservationContextProfile
    subject_grain: str
    source_role: str
    guaranteed_multiplicity: str
    subject_source: SelectionInput | None
    reference_source: SelectionInput | None
    pairing_source: SelectionInput | None


def _same_contract(
    resolved: ExactContractReference | None,
    reference: ExactContractReference | None,
) -> bool:
    return resolved == reference


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


def selectable_observation(capability: _ObservationCapability, *, ranking: bool) -> bool:
    """Selection eligibility shared by compilation and editor projection."""
    return (
        capability.subject_grain == "candidate"
        and capability.source_role == "subject"
        and (not ranking or capability.context_profile.kind != "pairwise"
             or capability.reference_source is not None)
        and (not ranking or not isinstance(capability.context_profile, PairwiseContextProfile)
             or capability.context_profile.pairing_mode != "explicit_relation"
             or capability.pairing_source is not None)
    )


def _validate_selection_capabilities(
    workflow: WorkflowDocument,
    *,
    graph: _AdmittedWorkflowGraph,
    catalog: FrozenCatalog,
    adopted_observations: Mapping[str, tuple[AdoptedObservation, ...]] | None = None,
) -> None:
    capabilities = _derive_observation_capabilities(
        graph,
        catalog=catalog,
        adopted_observations=adopted_observations,
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
            and _same_contract(capability.metric, objective.metric)
            and _same_contract(capability.method, objective.method)
            and context_selector_canonical(capability.context_profile) == requested_context
            and selectable_observation(capability, ranking=True)
        ]
        if not produced:
            if any(
                capability.source_partition == objective.source_partition
                and _same_contract(capability.metric, objective.metric)
                and context_selector_canonical(capability.context_profile) == requested_context
                and not _same_contract(
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
            and _same_contract(capability.metric, selector.metric)
            and _same_contract(capability.method, selector.method)
            and context_selector_canonical(capability.context_profile) == requested_context
            and selectable_observation(capability, ranking=False)
        ]
        if not produced:
            if any(
                capability.source_partition == selector.source_partition
                and _same_contract(capability.metric, selector.metric)
                and context_selector_canonical(capability.context_profile) == requested_context
                and capability.subject_grain == "candidate"
                and capability.source_role == "subject"
                        and not _same_contract(
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
    filter: ObservationPropagationFilter,
) -> bool:
    return (
        (filter.source_partition is None or capability.source_partition == filter.source_partition)
        and (filter.metric is None or capability.metric == filter.metric)
        and (filter.method is None or capability.method == filter.method)
        and (filter.context_profile is None or capability.context_profile == filter.context_profile)
    )


def _capability_canonical(
    capability: _ObservationCapability,
) -> dict[str, Any]:
    def reference(value: ExactContractReference | None) -> Any:
        return (
            None
            if value is None
            else {
                "contract_kind": value.contract_kind,
                "contract_id": value.contract_id,
            }
        )

    def source(value: SelectionInput | None) -> Any:
        return None if value is None else selection_input_canonical(value)

    return {
        "source_partition": capability.source_partition,
        "metric": reference(capability.metric),
        "method": reference(capability.method),
        "context_profile": context_selector_canonical(capability.context_profile),
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
    adopted_observations: Mapping[str, tuple[AdoptedObservation, ...]] | None = None,
) -> dict[tuple[str, str], tuple[_ObservationCapability, ...]]:
    """Derive exact output capabilities from closed fixed/propagation contracts."""
    capabilities: dict[
        tuple[str, str],
        tuple[_ObservationCapability, ...],
    ] = {}
    for node_id in graph.node_order:
        for observation in (adopted_observations or {}).get(node_id, ()):
            key = (node_id, observation.output_port)
            capabilities[key] = (*capabilities.get(key, ()), _ObservationCapability(
                source_partition=observation.source_partition, metric=observation.metric,
                method=observation.method, context_profile=observation.context_profile,
                subject_grain='candidate', source_role='subject',
                guaranteed_multiplicity=observation.guaranteed_multiplicity,
                subject_source=SelectionInput(node_id, observation.subject_output_port) if observation.subject_output_port else None,
                reference_source=SelectionInput(node_id, observation.reference_output_port) if observation.reference_output_port else None,
                pairing_source=SelectionInput(node_id, observation.pairing_output_port) if observation.pairing_output_port else None))
        plan = catalog.produced_observation_plan(graph.nodes_by_id[node_id].binding_id)
        for declaration in plan.observations:
            method_source = (
                _connected_source(
                    graph,
                    node_id=node_id,
                    input_port=declaration.method_source.port,
                )
                if declaration.method_source is not None and declaration.method_source.direction == "input"
                else None
            )
            observation_method = (
                catalog.produced_observation_plan(
                    graph.nodes_by_id[method_source.node_id].binding_id
                ).binding_method
                if method_source is not None
                else plan.binding_method
                if declaration.method_source is None or declaration.method_source.direction != "input"
                else None
            )
            capability = _ObservationCapability(
                source_partition=declaration.output_partition,
                metric=declaration.metric,
                method=observation_method,
                context_profile=declaration.context_profile,
                subject_grain="candidate",
                source_role="subject",
                guaranteed_multiplicity=declaration.guaranteed_multiplicity,
                subject_source=_capability_source(
                    graph,
                    node_id=node_id,
                    direction="input",
                    port=declaration.subject_input,
                ),
                reference_source=_capability_source(
                    graph,
                    node_id=node_id,
                    direction=declaration.reference_source.direction if declaration.reference_source is not None else None,
                    port=declaration.reference_source.port if declaration.reference_source is not None else None,
                ),
                pairing_source=_capability_source(
                    graph,
                    node_id=node_id,
                    direction=declaration.pairing_source.direction if declaration.pairing_source is not None else None,
                    port=declaration.pairing_source.port if declaration.pairing_source is not None else None,
                ),
            )
            key = (node_id, declaration.output_port)
            capabilities[key] = (*capabilities.get(key, ()), capability)

        propagation = plan.propagation
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
