"""Exact contract locking and Workflow compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
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
from core.catalog.model import FrozenCatalog
from core.catalog.port_contract import (
    CatalogBuildError,
    ContractResolutionError,
    canonical_sha256,
)
from core.scoring.selection import (
    observation_selector_canonical,
    selection_objective_canonical,
)
from datatypes.exact_reference import ExactContractReference
from core.workflow.document import (
    ContractLockEntry,
    WorkflowDocument,
    _thaw_json,
)
from core.workflow.plan import (
    ArtifactOutputPlan,
    EXECUTION_PLAN_NAMESPACE,
    ExecutionPlan,
    ExecutionPlanNode,
    _ExecutionPlanNodeRuntime,
    _ExecutionPlanPort,
    _ExecutionPlanRuntime,
    _ExecutionPlanValueSource,
)
class WorkflowCompileError(ValueError):
    """A Workflow failed static v2 compilation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        field_path: tuple[str | int, ...] = (),
    ) -> None:
        self.code = code
        self.node_id = node_id
        self.field_path = field_path
        super().__init__(message)

    def issue(self) -> dict[str, Any]:
        issue: dict[str, Any] = {
            "code": self.code,
            "severity": "error",
            "message": str(self),
            "field_path": list(self.field_path),
        }
        if self.node_id is not None:
            issue["node_id"] = self.node_id
        return issue


@dataclass(frozen=True, slots=True)
class CompilationRequest:
    """One locked Workflow and Authoring-assigned Commit revision."""

    locked_workflow: WorkflowDocument
    workflow_commit_revision: int


from core.workflow._compiler.identity import (  # noqa: E402
    _result_contracts_for_node,
    _result_identity_plan_facts,
)
from core.workflow._compiler.locking import (  # noqa: E402
    _reachable_contract_lock,
    _require_matching_lock,
    _require_workflow_contract,
    _workflow_contract_references,
)
from core.workflow._compiler.observation import (  # noqa: E402
    _resolved_produced_observation_plan,
)
from core.workflow._compiler.selection import (  # noqa: E402
    _compile_observation_selector,
    _compile_selection_objectives,
)
from core.workflow._compiler.validation import (  # noqa: E402
    _validate_static_semantics,
)


def lock_workflow(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> WorkflowDocument:
    """Lock an unlocked Draft to the current reachable Catalog closure."""
    if workflow.contract_lock:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow Draft must be unlocked before Contract locking",
            field_path=("contract_lock",),
        )
    _workflow_contract_references(workflow)

    def current_reference(
        reference: ExactContractReference,
        *,
        contract_kind: str,
        collection_name: str,
        index: int,
        field_name: str,
    ) -> ExactContractReference:
        field_path = (collection_name, index, field_name)
        contract = _require_workflow_contract(
            catalog,
            contract_kind,
            reference.contract_id,
            reference.contract_version,
            identity_path=(*field_path, "contract_id"),
            version_path=(*field_path, "contract_version"),
        )
        return ExactContractReference(**contract.reference())

    try:
        workflow = replace(
            workflow,
            observation_selectors=tuple(
                replace(
                    selector,
                    metric=current_reference(
                        selector.metric,
                        contract_kind="metric",
                        collection_name="observation_selectors",
                        index=index,
                        field_name="metric",
                    ),
                    method=current_reference(
                        selector.method,
                        contract_kind="method",
                        collection_name="observation_selectors",
                        index=index,
                        field_name="method",
                    ),
                )
                for index, selector in enumerate(
                    workflow.observation_selectors
                )
            ),
            selection_objectives=tuple(
                replace(
                    objective,
                    metric=current_reference(
                        objective.metric,
                        contract_kind="metric",
                        collection_name="selection_objectives",
                        index=index,
                        field_name="metric",
                    ),
                    method=current_reference(
                        objective.method,
                        contract_kind="method",
                        collection_name="selection_objectives",
                        index=index,
                        field_name="method",
                    ),
                    utility_transform=current_reference(
                        objective.utility_transform,
                        contract_kind="utility_transform",
                        collection_name="selection_objectives",
                        index=index,
                        field_name="utility_transform",
                    ),
                )
                for index, objective in enumerate(
                    workflow.selection_objectives
                )
            ),
        )
        contract_lock = _reachable_contract_lock(workflow, catalog)
    except (CatalogBuildError, ContractResolutionError) as error:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow references a contract absent from the current Catalog",
            field_path=("contract_lock",),
        ) from error
    return replace(
        workflow,
        contract_lock=contract_lock,
    )


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
        raise WorkflowCompileError(
            error.code,
            f"{field_name}{suffix} {error.reason}",
            node_id=node_id,
            field_path=(*field_path, *error.path),
        ) from error


def compile(
    request: CompilationRequest,
    catalog: FrozenCatalog,
) -> ExecutionPlan:
    """Compile one exact Lock before consulting runtime Availability."""
    workflow = request.locked_workflow
    workflow_commit_revision = request.workflow_commit_revision
    resolved_contracts = _require_matching_lock(workflow, catalog)
    lock_by_key = {entry.key: entry for entry in resolved_contracts}
    resolved_by_key = {
        entry.key: catalog.require_contract(*entry.key)
        for entry in resolved_contracts
    }
    admitted_parameters: dict[
        str,
        tuple[AdmittedParameterValues, AdmittedParameterValues],
    ] = {}
    plan_nodes: dict[
        str,
        tuple[NodeTypeDefinition, ExecutionBindingDefinition],
    ] = {}
    for index, node in enumerate(workflow.nodes):
        node_type_contract = resolved_by_key[
            ("node_type", node.node_type_id, node.node_type_version)
        ]
        binding_contract = resolved_by_key[
            ("binding", node.binding_id, node.binding_version)
        ]
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
    objective_compilation_by_id = {
        objective.objective_id: (
            index,
            _admit_parameter_values(
                objective.utility_parameters,
                cast(
                    UtilityTransformDefinition,
                    resolved_by_key[
                        objective.utility_transform.key
                    ].definition,
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
    graph, selection_consumers = _validate_static_semantics(
        workflow,
        plan_nodes=plan_nodes,
        lock_by_key=lock_by_key,
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
            resolved_by_key=resolved_by_key,
        )
        for selector in workflow.observation_selectors
    )
    resolved_selectors_by_id = {
        item.selector_id: item
        for item in resolved_workflow_selectors
    }
    nodes: list[ExecutionPlanNode] = []
    for node_id in graph.node_order:
        node = graph.nodes_by_id[node_id]
        node_type_contract = resolved_by_key[
            ("node_type", node.node_type_id, node.node_type_version)
        ]
        binding = resolved_by_key[
            ("binding", node.binding_id, node.binding_version)
        ]
        node_definition, binding_definition = plan_nodes[node_id]
        method_key = binding_definition.method.key
        method_contract = resolved_by_key[method_key]
        normalized_node_parameters, normalized_binding_parameters = (
            admitted_parameters[node.node_id]
        )
        selected_objectives = selection_consumers.objectives_by_node[node_id]
        selected_selectors = selection_consumers.selectors_by_node[node_id]
        resolved_selected_objectives = _compile_selection_objectives(
            selected_objectives,
            compilation_by_id=objective_compilation_by_id,
            resolved_by_key=resolved_by_key,
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
                port_type = resolved_by_key[key]
                ports[declaration.name] = _ExecutionPlanPort(
                    reference=lock_by_key[key],
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
            resolved_by_key=resolved_by_key,
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
            resolved_by_key=resolved_by_key,
        )
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
                node_type=lock_by_key[
                    ("node_type", node.node_type_id, node.node_type_version)
                ],
                binding=lock_by_key[
                    ("binding", node.binding_id, node.binding_version)
                ],
                method=lock_by_key[method_key],
                node_parameters=normalized_node_parameters,
                binding_parameters=normalized_binding_parameters,
                result_identity_plan_facts=result_identity_plan_facts,
                _runtime=runtime,
            )
        )
    plan_descriptor = {
        "schema_namespace": EXECUTION_PLAN_NAMESPACE,
        "workflow_id": workflow.workflow_id,
        "workflow_commit_revision": workflow_commit_revision,
        "workflow_digest": workflow.digest,
        "catalog_contract_digest": catalog.contract_digest,
        "contract_lock_digest": workflow.contract_lock_digest,
        "node_order": list(graph.node_order),
        "nodes": [
            {
                "node_id": node.node_id,
                "node_type": node.node_type.canonical_projection(),
                "binding": node.binding.canonical_projection(),
                "method": node.method.canonical_projection(),
                "node_parameters": _thaw_json(node.node_parameters),
                "binding_parameters": _thaw_json(node.binding_parameters),
                "result_identity_plan_facts_digest": (
                    node.result_identity_plan_facts.digest
                ),
            }
            for node in nodes
        ],
        "edges": [
            edge.canonical_projection() for edge in workflow.edges
        ],
        "observation_selectors": [
            observation_selector_canonical(selector)
            for selector in workflow.observation_selectors
        ],
        "selection_objectives": [
            selection_objective_canonical(objective)
            for objective in workflow.selection_objectives
        ],
        "resolved_contracts": [
            entry.canonical_projection() for entry in resolved_contracts
        ],
    }
    execution_plan_digest = canonical_sha256(plan_descriptor)
    plan = ExecutionPlan(
        workflow_id=workflow.workflow_id,
        workflow_commit_revision=workflow_commit_revision,
        workflow_digest=workflow.digest,
        catalog_contract_digest=catalog.contract_digest,
        contract_lock_digest=workflow.contract_lock_digest,
        execution_plan_digest=execution_plan_digest,
        nodes=tuple(nodes),
        edges=workflow.edges,
        node_order=graph.node_order,
        resolved_contracts=resolved_contracts,
        _runtime=_ExecutionPlanRuntime(
            candidate_data_port_types=candidate_data_port_types,
        ),
        observation_selectors=workflow.observation_selectors,
        selection_objectives=workflow.selection_objectives,
    )
    return plan
