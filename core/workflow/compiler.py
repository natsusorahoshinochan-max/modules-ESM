"""Stable-ID Workflow compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from core.catalog.declarations import (
    ExecutionBindingDefinition,
    NodePortDefinition,
    NodeTypeDefinition,
    UtilityTransformDefinition,
)

from core.parameters.contract import (
    ParameterValueAdmissionError,
    admit_values,
)
from core.parameters.model import (
    AdmittedParameterValues,
    ParameterContract,
)
from core.catalog.model import FrozenCatalog, result_identity_contract
from core.workflow._compiler.identity import (
    _result_contracts_for_node,
    _result_identity_plan_facts,
)
from core.workflow._compiler.graph import _admit_workflow_graph
from core.workflow._compiler.observation import (
    _resolved_produced_observation_plan,
)
from core.workflow._compiler.selection import (
    _compile_observation_selector,
    _compile_selection_objectives,
)
from core.workflow._compiler.selection_capabilities import (
    _validate_selection_capabilities,
)
from core.workflow._compiler.selection_consumers import (
    _compile_selection_consumers,
)
from core.workflow import errors as _errors
from core.workflow.document import WorkflowDocument, _thaw_json
from core.workflow.plan import (
    ArtifactOutputPlan,
    ExecutionPlan,
    ExecutionPlanNode,
    _ExecutionPlanNodeRuntime,
    _ExecutionPlanPort,
    _ExecutionPlanRuntime,
    _ExecutionPlanValueSource,
)


@dataclass(frozen=True, slots=True)
class CompilationRequest:
    """One admitted Workflow."""

    workflow: WorkflowDocument


def _admit_parameter_values(
    values: Mapping[str, Any],
    contract: ParameterContract,
    *,
    field_name: str,
    field_path: tuple[str | int, ...],
    node_id: str | None = None,
) -> AdmittedParameterValues:
    try:
        return admit_values(contract, values)
    except ParameterValueAdmissionError as error:
        suffix = (
            "" if not error.path else f".{'.'.join(map(str, error.path))}"
        )
        raise _errors.WorkflowCompileError(
            error.code,
            f"{field_name}{suffix} {error.reason}",
            node_id=node_id,
            field_path=(*field_path, *error.path),
        ) from error


def compile(
    request: CompilationRequest,
    catalog: FrozenCatalog,
) -> ExecutionPlan:
    """Compile one stable-ID Workflow before consulting runtime state."""
    workflow = request.workflow
    def resolved_contract(
        contract_kind: str,
        contract_id: str,
        *,
        node_id: str | None = None,
        field_path: tuple[str | int, ...],
    ) -> Any:
        contract = catalog.get_contract(contract_kind, contract_id)
        if contract is None:
            raise _errors.WorkflowCompileError(
                "unknown_contract",
                f"Unknown {contract_kind} {contract_id}",
                node_id=node_id,
                field_path=field_path,
            )
        return contract
    admitted_parameters: dict[
        str,
        tuple[AdmittedParameterValues, AdmittedParameterValues],
    ] = {}
    plan_nodes: dict[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ] = {}
    for index, node in enumerate(workflow.nodes):
        node_type_contract = resolved_contract(
            "node_type",
            node.node_type_id,
            node_id=node.node_id,
            field_path=("nodes", index, "node_type_id"),
        )
        binding_contract = resolved_contract(
            "binding",
            node.binding_id,
            node_id=node.node_id,
            field_path=("nodes", index, "binding_id"),
        )
        node_definition = cast(
            NodeTypeDefinition,
            node_type_contract.definition,
        )
        binding_definition = cast(
            ExecutionBindingDefinition,
            binding_contract.definition,
        )
        plan_nodes[node.node_id] = (node_definition, binding_definition)
        admitted_parameters[node.node_id] = (
            _admit_parameter_values(
                node.node_parameters,
                node_definition.parameter_contract,
                node_id=node.node_id,
                field_name="node_parameters",
                field_path=("nodes", index, "node_parameters"),
            ),
            _admit_parameter_values(
                node.binding_parameters,
                binding_definition.parameter_contract,
                node_id=node.node_id,
                field_name="binding_parameters",
                field_path=("nodes", index, "binding_parameters"),
            ),
        )
    for index, selector in enumerate(workflow.observation_selectors):
        for field_name, reference, expected_kind in (
            ("metric", selector.metric, "metric"),
            ("method", selector.method, "method"),
        ):
            if reference.contract_kind != expected_kind:
                raise _errors.WorkflowCompileError(
                    "contract_kind_mismatch",
                    f"{field_name} must reference a {expected_kind}",
                    field_path=(
                        "observation_selectors",
                        index,
                        field_name,
                        "contract_kind",
                    ),
                )
            resolved_contract(
                expected_kind,
                reference.contract_id,
                field_path=(
                    "observation_selectors",
                    index,
                    field_name,
                    "contract_id",
                ),
            )
    for index, objective in enumerate(workflow.selection_objectives):
        for field_name, reference, expected_kind in (
            ("metric", objective.metric, "metric"),
            ("method", objective.method, "method"),
            (
                "utility_transform",
                objective.utility_transform,
                "utility_transform",
            ),
        ):
            if reference.contract_kind != expected_kind:
                raise _errors.WorkflowCompileError(
                    "contract_kind_mismatch",
                    f"{field_name} must reference a {expected_kind}",
                    field_path=(
                        "selection_objectives",
                        index,
                        field_name,
                        "contract_kind",
                    ),
                )
            resolved_contract(
                expected_kind,
                reference.contract_id,
                field_path=(
                    "selection_objectives",
                    index,
                    field_name,
                    "contract_id",
                ),
            )
    objective_compilation_by_id = {
        objective.objective_id: (
            index,
            _admit_parameter_values(
                objective.utility_parameters,
                cast(
                    UtilityTransformDefinition,
                    catalog.require_contract(
                        *objective.utility_transform.key
                    ).definition,
                ).parameter_contract,
                field_name="utility_parameters",
                field_path=(
                    "selection_objectives",
                    index,
                    "utility_parameters",
                ),
            ),
        )
        for index, objective in enumerate(workflow.selection_objectives)
    }
    graph = _admit_workflow_graph(workflow, plan_nodes)
    _validate_selection_capabilities(
        workflow,
        graph=graph,
        plan_nodes=plan_nodes,
        catalog=catalog,
    )
    selection_consumers = _compile_selection_consumers(
        workflow,
        graph=graph,
        plan_nodes=plan_nodes,
        admitted_node_parameters={
            node_id: values[0]
            for node_id, values in admitted_parameters.items()
        },
    )
    candidate_data_port_types = {
        definition.type_id: definition
        for definition in catalog.port_types
        if definition.type_id
        in {
            "protein.sequence",
            "protein.structure",
        }
    }
    resolved_workflow_selectors = tuple(
        _compile_observation_selector(
            selector,
            catalog=catalog,
        )
        for selector in workflow.observation_selectors
    )
    resolved_selectors_by_id = {
        item.selector_id: item
        for item in resolved_workflow_selectors
    }
    nodes: list[ExecutionPlanNode] = []
    scientific_definitions: dict[tuple[str, str], Mapping[str, Any]] = {}
    for node_id in graph.node_order:
        node = graph.nodes_by_id[node_id]
        node_type_contract = catalog.require_contract(
            "node_type", node.node_type_id
        )
        binding = catalog.require_contract("binding", node.binding_id)
        node_definition, binding_definition = plan_nodes[node_id]
        method_key = binding_definition.method.key
        method_contract = catalog.require_contract(*method_key)
        normalized_node_parameters, normalized_binding_parameters = (
            admitted_parameters[node.node_id]
        )
        selected_objectives = selection_consumers.objectives_by_node[node_id]
        selected_selectors = selection_consumers.selectors_by_node[node_id]
        resolved_selected_objectives = _compile_selection_objectives(
            selected_objectives,
            compilation_by_id=objective_compilation_by_id,
            catalog=catalog,
        )
        resolved_selected_selectors = tuple(
            resolved_selectors_by_id[item.selector_id]
            for item in selected_selectors
        )

        def resolved_ports(
            declarations: tuple[NodePortDefinition, ...],
        ) -> dict[str, _ExecutionPlanPort]:
            ports: dict[str, _ExecutionPlanPort] = {}
            for declaration in declarations:
                key = declaration.port_type.key
                port_type = catalog.require_port_type(key[1])
                ports[declaration.name] = _ExecutionPlanPort(
                    reference=catalog.require_reference(*key),
                    multiplicity=declaration.multiplicity,
                    required=declaration.required,
                    artifact_kind=declaration.artifact_kind,
                    artifact_media_type=declaration.artifact_media_type,
                    port_type=port_type,
                )
            return ports

        input_ports = resolved_ports(node_definition.inputs)
        output_ports = resolved_ports(node_definition.outputs)
        frozen_input_sources = {
            port_name: tuple(
                _ExecutionPlanValueSource(
                    source.node_id,
                    source.output_port,
                )
                for _, source in admitted_sources
            )
            for port_name, admitted_sources in graph.input_sources[node_id].items()
        }
        required_port_names = {
            name
            for name, port in input_ports.items()
            if port.required
        }
        for constraint in node_definition.input_constraints:
            required_port_names.update(
                port_name
                for port_name in constraint
                if port_name in frozen_input_sources
            )
        required_input_sources = {
            port_name: frozen_input_sources[port_name]
            for port_name in sorted(required_port_names)
            if port_name in frozen_input_sources
        }
        produced_observation_plan = _resolved_produced_observation_plan(
            binding,
            catalog=catalog,
        )
        artifact_outputs: list[ArtifactOutputPlan] = []
        for port_name, port in output_ports.items():
            artifact_kind = port.artifact_kind
            if artifact_kind is None:
                continue
            artifact_outputs.append(
                ArtifactOutputPlan(
                    output_port=port_name,
                    artifact_kind=artifact_kind,
                    artifact_media_type=port.artifact_media_type,
                    port_type=port.reference,
                    accepted_media_types=tuple(
                        cast(tuple[str, ...], port.port_type.artifact_media_types)
                    ),
                )
            )
        objective_consumption = binding_definition.selection_objective_consumption
        selector_consumption = binding_definition.observation_selector_consumption
        selection_consumption = (
            selector_consumption
            if selector_consumption is not None
            else objective_consumption
            if objective_consumption is not None
            else None
        )
        result_contracts = _result_contracts_for_node(
            node_contract=node_type_contract,
            binding_contract=binding,
            selected_objectives=selected_objectives,
            selected_selectors=selected_selectors,
            catalog=catalog,
        )
        for contract in result_contracts:
            scientific_definitions[
                (contract.contract_kind, contract.contract_id)
            ] = _thaw_json(result_identity_contract(contract))
        result_identity_plan_facts = _result_identity_plan_facts(
            node_contract=node_type_contract,
            binding_contract=binding,
            method_contract=method_contract,
            result_contracts=result_contracts,
            selected_objectives=resolved_selected_objectives,
            selected_selectors=resolved_selected_selectors,
        )
        runtime = _ExecutionPlanNodeRuntime(
            factory=binding_definition.factory,
            readiness_declaration=binding_definition.readiness,
            effective_randomness_resolver=(
                binding_definition.effective_randomness_resolver
            ),
            execution_route=binding_definition.execution_route,
            cacheable=binding_definition.cacheable,
            deterministic=binding_definition.deterministic,
            effective_randomness_parameters=(
                binding_definition.effective_randomness_parameters
            ),
            input_ports=input_ports,
            output_ports=output_ports,
            input_sources=frozen_input_sources,
            required_input_sources=required_input_sources,
            dependencies=tuple(
                sorted(
                    {
                        source.node_id
                        for sources in frozen_input_sources.values()
                        for source in sources
                    }
                )
            ),
            project_input_parameters=tuple(
                declaration.name
                for declaration in node_definition.parameter_contract.entries
                if declaration.resource_kind == "project_input"
            ),
            produced_observation_plan=produced_observation_plan,
            selection_objectives=resolved_selected_objectives,
            observation_selectors=resolved_selected_selectors,
            selection_candidate_output_port=(
                selection_consumption.candidate_output_port
                if selection_consumption is not None
                else None
            ),
            artifact_outputs=tuple(artifact_outputs),
        )
        nodes.append(
            ExecutionPlanNode(
                node_id=node.node_id,
                node_type=catalog.require_reference(
                    "node_type", node.node_type_id
                ),
                binding=catalog.require_reference("binding", node.binding_id),
                method=catalog.require_reference(*method_key),
                node_parameters=normalized_node_parameters,
                binding_parameters=normalized_binding_parameters,
                result_identity_plan_facts=result_identity_plan_facts,
                _runtime=runtime,
            )
        )
    plan = ExecutionPlan(
        workflow_id=workflow.workflow_id,
        nodes=tuple(nodes),
        edges=workflow.edges,
        node_order=graph.node_order,
        scientific_definitions=tuple(
            scientific_definitions[key]
            for key in sorted(scientific_definitions)
        ),
        _runtime=_ExecutionPlanRuntime(
            candidate_data_port_types=candidate_data_port_types,
        ),
        observation_selectors=workflow.observation_selectors,
        selection_objectives=workflow.selection_objectives,
    )
    return plan
