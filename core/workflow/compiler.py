"""Stable-ID Workflow compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from core.catalog.errors import UnknownContractError
from core.catalog.result_adoption import AdoptedObservation, with_adopted_definitions
from typing import Any, cast

from datatypes.i_json import thaw_i_json
from core.catalog.declarations import (
    ExecutionBindingDefinition,
    NodePortDefinition,
    NodeTypeDefinition,
    ParameterDependencies,
)

from core.parameters.contract import (
    ParameterValueAdmissionError,
    admit_values,
)
from core.parameters.model import (
    AdmittedParameterValues,
    ParameterContract,
)
from core.catalog.model import CatalogContract, FrozenCatalog, result_identity_contract
from core.workflow._compiler.identity import (
    _result_contracts_for_node,
    _result_identity_plan_facts,
)
from core.workflow._compiler.graph import _admit_workflow_graph, _validate_input_slot_references
from core.workflow import errors as _errors
from core.workflow.document import WorkflowDocument
from core.workflow.plan import (
    ArtifactOutputPlan,
    ResultIdentityPlanFacts,
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
    adopted_observations: Mapping[str, tuple[AdoptedObservation, ...]] = field(default_factory=dict)
    adopted_definitions: tuple[Mapping[str, Any], ...] = ()


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
    for index, node in enumerate(workflow.nodes):
        if node.preserved_configuration is not None:
            raise _errors.WorkflowCompileError(
                "preserved_configuration_unavailable",
                node.preserved_configuration["reason"],
                node_id=node.node_id,
                field_path=("nodes", index, "preserved_configuration"),
            )
    try:
        catalog = with_adopted_definitions(catalog, request.adopted_definitions)
    except ValueError as error:
        raise _errors.WorkflowCompileError("adopted_definition_conflict", str(error)) from error
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
    graph = _admit_workflow_graph(workflow, plan_nodes)
    _validate_input_slot_references(workflow, plan_nodes, {node_id: values[0] for node_id, values in admitted_parameters.items()})
    candidate_data_port_types = {
        definition.type_id: definition
        for definition in catalog.port_types
        if definition.type_id
        in {
            "protein.sequence",
            "protein.structure",
        }
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
        parameter_dependencies = ParameterDependencies()
        if binding_definition.parameter_dependencies is not None:
            try:
                parameter_dependencies = binding_definition.parameter_dependencies.resolve(
                    normalized_node_parameters, normalized_binding_parameters)
            except ValueError as error:
                raise _errors.WorkflowCompileError(
                    "invalid_parameter_dependencies", str(error), node_id=node_id,
                    field_path=("nodes", node_id, "node_parameters")) from error
            connected = {(edge.target_port, edge.target_slot) for edge in workflow.edges
                         if edge.target_node_id == node_id}
            for port, slot in parameter_dependencies.input_slots:
                if (port, slot) not in connected:
                    raise _errors.WorkflowCompileError(
                        "required_input_missing", f"Input slot {slot!r} on {port!r} is disconnected",
                        node_id=node_id, field_path=("nodes", node_id, "node_parameters"))
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
                    workflow.edges[edge_index].target_slot,
                )
                for edge_index, source in admitted_sources
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
        produced_observation_plan = catalog.produced_observation_plan(node.binding_id)
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
        try:
            result_contracts = _result_contracts_for_node(
                node_contract=node_type_contract,
                binding_contract=binding,
                catalog=catalog,
                parameter_dependencies=parameter_dependencies.contracts,
            )
        except UnknownContractError as error:
            raise _errors.WorkflowCompileError(
                "unknown_contract", str(error), node_id=node_id,
                field_path=("nodes", node_id, "node_parameters")) from error
        resolved_definitions = MappingProxyType({
            (facts['contract_kind'], facts['contract_id']):
                contract.definition if isinstance(contract, CatalogContract) else contract
            for contract in result_contracts
            for facts in (result_identity_contract(contract),)
        })
        for contract in result_contracts:
            identity_definition = thaw_i_json(result_identity_contract(contract))
            scientific_definitions[(identity_definition['contract_kind'], identity_definition['contract_id'])] = identity_definition
        result_identity_plan_facts = _result_identity_plan_facts(
            node_contract=node_type_contract,
            binding_contract=binding,
            method_contract=method_contract,
            result_contracts=result_contracts,
        )
        slot_bindings = {port: [source.target_slot for source in sources]
                         for port, sources in frozen_input_sources.items()
                         if any(source.target_slot is not None for source in sources)}
        if slot_bindings:
            result_identity_plan_facts = ResultIdentityPlanFacts(
                {**result_identity_plan_facts.identity_projection(), "input_slots": slot_bindings},
            )
        runtime = _ExecutionPlanNodeRuntime(
            factory=binding_definition.factory,
            resolved_definitions=resolved_definitions,
            readiness_declaration=binding_definition.readiness,
            required_environment_fields=tuple(
                field.name for field in binding_definition.environment_fields if field.required
            ),
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
    for definition in request.adopted_definitions:
        key = (definition['contract_kind'], definition['contract_id'])
        if key not in scientific_definitions:
            scientific_definitions[key] = definition
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
    )
    return plan
