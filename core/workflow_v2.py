"""Exact contract-locked Workflow authoring and compilation for backend v2."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from types import MappingProxyType
from typing import Any

from core.parameter_contract import (
    find_environment_parameter_field,
    parameter_contract_violation,
    parameter_value_contract,
)
from core.port_types import (
    CatalogBuildError,
    FrozenCatalog,
    canonical_json_bytes,
    canonical_sha256,
)
from core.scoring_v2 import (
    SelectionError,
    SelectionObjective,
    resolve_selection_objective,
)
from protein_workbench_public import ProtocolValidationError, validate_schema


WORKFLOW_SCHEMA_VERSION = "2.0.0"
WORKFLOW_DIGEST_NAMESPACE = "protein-workbench-workflow/v2"
CONTRACT_LOCK_NAMESPACE = "protein-workbench-contract-lock/v2"
EXECUTION_PLAN_NAMESPACE = "protein-workbench-execution-plan/v2"


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {name: _freeze_json(item) for name, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {name: _thaw_json(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, order=True)
class ContractLockEntry:
    """One exact author-approved reachable Catalog contract."""

    contract_kind: str
    contract_id: str
    contract_version: str
    contract_digest: str

    @classmethod
    def from_public(cls, payload: Mapping[str, Any]) -> ContractLockEntry:
        return cls(
            contract_kind=payload["contract_kind"],
            contract_id=payload["contract_id"],
            contract_version=payload["contract_version"],
            contract_digest=payload["contract_digest"],
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            self.contract_kind,
            self.contract_id,
            self.contract_version,
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class WorkflowNodeInstance:
    """One exact v2 Node Instance with separated parameter scopes."""

    node_id: str
    node_type_id: str
    node_type_version: str
    binding_id: str
    binding_version: str
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_parameters",
            _freeze_json(self.node_parameters),
        )
        object.__setattr__(
            self,
            "binding_parameters",
            _freeze_json(self.binding_parameters),
        )

    @classmethod
    def from_public(
        cls,
        payload: Mapping[str, Any],
    ) -> WorkflowNodeInstance:
        return cls(
            node_id=payload["node_id"],
            node_type_id=payload["node_type_id"],
            node_type_version=payload["node_type_version"],
            binding_id=payload["binding_id"],
            binding_version=payload["binding_version"],
            node_parameters=payload["node_parameters"],
            binding_parameters=payload["binding_parameters"],
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type_id": self.node_type_id,
            "node_type_version": self.node_type_version,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "node_parameters": _thaw_json(self.node_parameters),
            "binding_parameters": _thaw_json(self.binding_parameters),
        }


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    """One named exact Port connection."""

    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str

    @classmethod
    def from_public(cls, payload: Mapping[str, Any]) -> WorkflowEdge:
        return cls(
            source_node_id=payload["source_node_id"],
            source_port=payload["source_port"],
            target_node_id=payload["target_node_id"],
            target_port=payload["target_port"],
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "source_port": self.source_port,
            "target_node_id": self.target_node_id,
            "target_port": self.target_port,
        }


@dataclass(frozen=True, slots=True)
class WorkflowDocument:
    """Immutable parsed public v2 Workflow document."""

    schema_version: str
    workflow_id: str
    nodes: tuple[WorkflowNodeInstance, ...]
    edges: tuple[WorkflowEdge, ...]
    contract_lock: tuple[ContractLockEntry, ...]
    selection_objectives: tuple[SelectionObjective, ...] = ()

    def to_public(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "nodes": [node.to_public() for node in self.nodes],
            "edges": [edge.to_public() for edge in self.edges],
            "selection_objectives": [
                objective.to_public()
                for objective in self.selection_objectives
            ],
            "contract_lock": [
                entry.to_public() for entry in self.contract_lock
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_sha256(
            {
                "schema_namespace": WORKFLOW_DIGEST_NAMESPACE,
                "workflow": self.to_public(),
            }
        )

    @property
    def contract_lock_digest(self) -> str:
        return canonical_sha256(
            {
                "schema_namespace": CONTRACT_LOCK_NAMESPACE,
                "entries": [
                    entry.to_public() for entry in self.contract_lock
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class ExecutionPlanNode:
    """One fully resolved immutable private plan Node."""

    node_id: str
    node_type: ContractLockEntry
    binding: ContractLockEntry
    method: ContractLockEntry
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_parameters",
            _freeze_json(self.node_parameters),
        )
        object.__setattr__(
            self,
            "binding_parameters",
            _freeze_json(self.binding_parameters),
        )


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Private immutable result of one successful compilation."""

    workflow_id: str
    workflow_revision: int
    workflow_digest: str
    catalog_contract_digest: str
    contract_lock_digest: str
    execution_plan_digest: str
    nodes: tuple[ExecutionPlanNode, ...]
    edges: tuple[WorkflowEdge, ...]
    node_order: tuple[str, ...]
    resolved_contracts: tuple[ContractLockEntry, ...]
    selection_objectives: tuple[SelectionObjective, ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledWorkflow:
    """Private plan paired with its compact public compile receipt."""

    execution_plan: ExecutionPlan
    receipt: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt", _freeze_json(self.receipt))

    def public_receipt(self) -> dict[str, Any]:
        """Return an isolated mutable wire copy of the compact receipt."""
        return _thaw_json(self.receipt)


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


class WorkflowDocumentError(ValueError):
    """A public Workflow document violates the closed v2 schema."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def parse_workflow_document(payload: Mapping[str, Any]) -> WorkflowDocument:
    """Parse one closed public v2 Workflow without legacy inference."""
    try:
        validate_schema("#/$defs/WorkflowDocument", payload)
    except ProtocolValidationError as error:
        if (
            isinstance(payload, Mapping)
            and payload.get("schema_version") != WORKFLOW_SCHEMA_VERSION
        ):
            code = "unsupported_schema_version"
        elif error.path.startswith("$.contract_lock"):
            code = "contract_digest_mismatch"
        else:
            code = "malformed_request"
        raise WorkflowDocumentError(
            code,
            f"Workflow document is invalid: {error.reason}",
        ) from error
    try:
        return WorkflowDocument(
            schema_version=payload["schema_version"],
            workflow_id=payload["workflow_id"],
            nodes=tuple(
                WorkflowNodeInstance.from_public(node)
                for node in payload["nodes"]
            ),
            edges=tuple(
                WorkflowEdge.from_public(edge)
                for edge in payload["edges"]
            ),
            contract_lock=tuple(
                ContractLockEntry.from_public(entry)
                for entry in payload["contract_lock"]
            ),
            selection_objectives=tuple(
                SelectionObjective.from_public(objective)
                for objective in payload.get("selection_objectives", ())
            ),
        )
    except (CatalogBuildError, SelectionError, TypeError, ValueError) as error:
        raise WorkflowDocumentError(
            "malformed_request",
            f"Workflow document is invalid: {error}",
        ) from error


def _reference_from_value(value: Any) -> ContractLockEntry | None:
    if not isinstance(value, Mapping):
        return None
    required = {
        "contract_kind",
        "contract_id",
        "contract_version",
        "contract_digest",
    }
    if set(value) != required:
        return None
    return ContractLockEntry.from_public(value)


def _reachable_contract_lock(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> tuple[ContractLockEntry, ...]:
    pending: deque[ContractLockEntry] = deque()
    for node in workflow.nodes:
        for kind, contract_id, version in (
            ("node_type", node.node_type_id, node.node_type_version),
            ("binding", node.binding_id, node.binding_version),
        ):
            contract = catalog.require_contract(kind, contract_id, version)
            pending.append(ContractLockEntry.from_public(contract.reference()))
    for objective in workflow.selection_objectives:
        for kind, reference in (
            ("metric", objective.metric),
            ("method", objective.method),
            ("utility_transform", objective.utility_transform),
        ):
            contract = catalog.require_contract(
                kind,
                reference.contract_id,
                reference.contract_version,
            )
            pending.append(
                ContractLockEntry.from_public(contract.reference())
            )

    reachable: dict[tuple[str, str, str], ContractLockEntry] = {}
    while pending:
        reference = pending.popleft()
        if reference.key in reachable:
            continue
        contract = catalog.require_contract(*reference.key)
        observed = ContractLockEntry.from_public(contract.reference())
        reachable[observed.key] = observed
        descriptor = contract.descriptor
        nested: deque[Any] = deque([descriptor])
        while nested:
            value = nested.popleft()
            nested_reference = _reference_from_value(value)
            if nested_reference is not None:
                pending.append(nested_reference)
            elif isinstance(value, Mapping):
                nested.extend(value.values())
            elif isinstance(value, tuple):
                nested.extend(value)
            elif isinstance(value, list):
                nested.extend(value)
    return tuple(sorted(reachable.values()))


def relock_workflow(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> WorkflowDocument:
    """Explicitly replace the Lock with the current reachable closure."""
    try:
        contract_lock = _reachable_contract_lock(workflow, catalog)
    except CatalogBuildError as error:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow references a contract absent from the current Catalog",
            field_path=("contract_lock",),
        ) from error
    return replace(
        workflow,
        contract_lock=contract_lock,
    )


def _require_matching_lock(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> tuple[ContractLockEntry, ...]:
    try:
        expected = _reachable_contract_lock(workflow, catalog)
    except CatalogBuildError as error:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow references a contract absent from the current Catalog",
            field_path=("contract_lock",),
        ) from error
    if workflow.contract_lock != expected:
        raise WorkflowCompileError(
            "contract_digest_mismatch",
            "Workflow Contract Lock does not equal the reachable Catalog closure",
            field_path=("contract_lock",),
        )
    return expected


def _port_map(contract: Any, direction: str) -> dict[str, Mapping[str, Any]]:
    return {
        port["name"]: port
        for port in contract.descriptor.get(direction, ())
    }


def _validate_parameter_values(
    values: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    node_id: str,
    field_name: str,
) -> dict[str, Any]:
    supplied_forbidden_path = find_environment_parameter_field(values)
    if supplied_forbidden_path is not None:
        raise WorkflowCompileError(
            "environment_parameter_forbidden",
            (
                f"{field_name} contains Environment Configuration or "
                f"model identity field {supplied_forbidden_path[-1]!r}"
            ),
            node_id=node_id,
            field_path=(
                "nodes",
                node_id,
                field_name,
                *supplied_forbidden_path,
            ),
        )
    unknown = sorted(set(values) - set(contract))
    if unknown:
        raise WorkflowCompileError(
            "unknown_parameter",
            f"{field_name} contains undeclared parameters: {unknown}",
            node_id=node_id,
            field_path=("nodes", node_id, field_name),
        )
    resolved = {
        name: _thaw_json(declaration["default"])
        for name, declaration in contract.items()
        if isinstance(declaration, Mapping) and "default" in declaration
    }
    resolved.update(_thaw_json(values))
    forbidden_path = find_environment_parameter_field(resolved)
    if forbidden_path is not None:
        raise WorkflowCompileError(
            "environment_parameter_forbidden",
            (
                f"{field_name} contains Environment Configuration or "
                f"model identity field {forbidden_path[-1]!r}"
            ),
            node_id=node_id,
            field_path=(
                "nodes",
                node_id,
                field_name,
                *forbidden_path,
            ),
        )
    for name, declaration in contract.items():
        if (
            isinstance(declaration, Mapping)
            and declaration.get("required") is True
            and name not in values
            and "default" not in declaration
        ):
            raise WorkflowCompileError(
                "required_parameter_missing",
                f"{field_name}.{name} is required",
                node_id=node_id,
                field_path=("nodes", node_id, field_name, name),
            )
        if name not in resolved or not isinstance(declaration, Mapping):
            continue
        value = resolved[name]
        value_contract = parameter_value_contract(declaration)
        if not isinstance(value_contract, Mapping):
            raise WorkflowCompileError(
                "invalid_parameter",
                f"{field_name}.{name} has an invalid value contract",
                node_id=node_id,
                field_path=("nodes", node_id, field_name, name),
            )
        violation = parameter_contract_violation(
            value,
            value_contract,
            path=(name,),
        )
        if violation is not None:
            path, reason = violation
            raise WorkflowCompileError(
                "invalid_parameter",
                f"{field_name}.{'.'.join(map(str, path))} {reason}",
                node_id=node_id,
                field_path=("nodes", node_id, field_name, *path),
            )
    return resolved


def validate_workflow_parameter_values(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> None:
    """Validate exact scientific parameter paths without repairing the Lock."""
    for index, node in enumerate(workflow.nodes):
        try:
            node_contract = catalog.require_contract(
                "node_type",
                node.node_type_id,
                node.node_type_version,
            )
            binding_contract = catalog.require_contract(
                "binding",
                node.binding_id,
                node.binding_version,
            )
        except CatalogBuildError as error:
            raise WorkflowCompileError(
                "unknown_contract",
                "Workflow parameter paths require exact current contracts",
                node_id=node.node_id,
                field_path=("nodes", index),
            ) from error
        _validate_parameter_values(
            node.node_parameters,
            node_contract.descriptor.get("node_parameters", {}),
            node_id=node.node_id,
            field_name="node_parameters",
        )
        _validate_parameter_values(
            node.binding_parameters,
            binding_contract.descriptor.get("binding_parameters", {}),
            node_id=node.node_id,
            field_name="binding_parameters",
        )


def _validate_static_semantics(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
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
        _validate_parameter_values(
            node.node_parameters,
            node_contract.descriptor.get("node_parameters", {}),
            node_id=node.node_id,
            field_name="node_parameters",
        )
        _validate_parameter_values(
            node.binding_parameters,
            binding.descriptor.get("binding_parameters", {}),
            node_id=node.node_id,
            field_name="binding_parameters",
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
        catalog,
        nodes_by_id=nodes_by_id,
        plan_nodes=plan_nodes,
        node_order=tuple(order),
    )

    availability = {
        (
            snapshot["binding"]["contract_id"],
            snapshot["binding"]["contract_version"],
        ): snapshot
        for snapshot in catalog.availability
    }
    for node in workflow.nodes:
        snapshot = availability.get((node.binding_id, node.binding_version))
        if snapshot is None or snapshot.get("available") is not True:
            raise WorkflowCompileError(
                "binding_unavailable",
                "Selected Binding is unavailable in this Catalog snapshot",
                node_id=node.node_id,
                field_path=("nodes", node.node_id, "binding_id"),
            )
    return tuple(order)


def _validate_selection_objectives(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
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
            == objective.context_selector.to_public()
            and capability.get("subject_grain") == "candidate"
            and capability.get("source_role") == "subject"
            and capability.get("guaranteed_multiplicity") == "one"
            and capability.get("subject_source")
            == objective.candidate_input.to_public()
            and (
                objective.context_selector.to_public().get("kind")
                != "pairwise"
                or capability.get("reference_source") is not None
            )
            and (
                objective.context_selector.to_public().get("pairing_mode")
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
                == objective.context_selector.to_public()
                and capability.get("subject_source")
                == objective.candidate_input.to_public()
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
        try:
            resolve_selection_objective(objective, catalog)
        except SelectionError as error:
            raise WorkflowCompileError(
                "invalid_selection_objective",
                str(error),
                field_path=objective_path,
            ) from error


def _connected_source(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    input_port: str,
) -> dict[str, str] | None:
    sources = [
        {
            "node_id": edge.source_node_id,
            "output_port": edge.source_port,
        }
        for edge in workflow.edges
        if edge.target_node_id == node_id
        and edge.target_port == input_port
    ]
    return sources[0] if len(sources) == 1 else None


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
        return _connected_source(
            workflow,
            node_id=node_id,
            input_port=port,
        )
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
            capability = {
                "source_partition": declaration.get(
                    "output_partition",
                    "default",
                ),
                "metric": declaration.get("metric"),
                "method": method,
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
            or propagation.get("schema_version") != "2.0.0"
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


def compile_workflow(
    workflow: WorkflowDocument,
    *,
    workflow_revision: int,
    catalog: FrozenCatalog,
) -> CompiledWorkflow:
    """Compile one exact Lock before consulting runtime Availability."""
    resolved_contracts = _require_matching_lock(workflow, catalog)
    node_order = _validate_static_semantics(workflow, catalog)
    lock_by_key = {entry.key: entry for entry in resolved_contracts}
    nodes: list[ExecutionPlanNode] = []
    for node_id in node_order:
        node = next(item for item in workflow.nodes if item.node_id == node_id)
        node_type_contract = catalog.require_contract(
            "node_type",
            node.node_type_id,
            node.node_type_version,
        )
        binding = catalog.require_contract(
            "binding",
            node.binding_id,
            node.binding_version,
        )
        method_reference = ContractLockEntry.from_public(
            binding.descriptor["method"]
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
                method=lock_by_key[method_reference.key],
                node_parameters=_validate_parameter_values(
                    node.node_parameters,
                    node_type_contract.descriptor.get(
                        "node_parameters",
                        {},
                    ),
                    node_id=node.node_id,
                    field_name="node_parameters",
                ),
                binding_parameters=_validate_parameter_values(
                    node.binding_parameters,
                    binding.descriptor.get("binding_parameters", {}),
                    node_id=node.node_id,
                    field_name="binding_parameters",
                ),
            )
        )
    plan_descriptor = {
        "schema_namespace": EXECUTION_PLAN_NAMESPACE,
        "workflow_id": workflow.workflow_id,
        "workflow_revision": workflow_revision,
        "workflow_digest": workflow.digest,
        "catalog_contract_digest": catalog.contract_digest,
        "contract_lock_digest": workflow.contract_lock_digest,
        "node_order": list(node_order),
        "nodes": [
            {
                "node_id": node.node_id,
                "node_type": node.node_type.to_public(),
                "binding": node.binding.to_public(),
                "method": node.method.to_public(),
                "node_parameters": _thaw_json(node.node_parameters),
                "binding_parameters": _thaw_json(node.binding_parameters),
            }
            for node in nodes
        ],
        "edges": [edge.to_public() for edge in workflow.edges],
        "selection_objectives": [
            objective.to_public()
            for objective in workflow.selection_objectives
        ],
        "resolved_contracts": [
            entry.to_public() for entry in resolved_contracts
        ],
    }
    execution_plan_digest = canonical_sha256(plan_descriptor)
    plan = ExecutionPlan(
        workflow_id=workflow.workflow_id,
        workflow_revision=workflow_revision,
        workflow_digest=workflow.digest,
        catalog_contract_digest=catalog.contract_digest,
        contract_lock_digest=workflow.contract_lock_digest,
        execution_plan_digest=execution_plan_digest,
        nodes=tuple(nodes),
        edges=workflow.edges,
        node_order=node_order,
        resolved_contracts=resolved_contracts,
        selection_objectives=workflow.selection_objectives,
    )
    receipt = {
        "accepted": True,
        "compile_id": execution_plan_digest.replace("sha256:", "compile-"),
        "workflow_revision": workflow_revision,
        "workflow_digest": workflow.digest,
        "catalog_contract_digest": catalog.contract_digest,
        "contract_lock_digest": workflow.contract_lock_digest,
        "execution_plan_digest": execution_plan_digest,
        "issues": [],
    }
    return CompiledWorkflow(plan, receipt)
