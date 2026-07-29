"""Exact contract-locked Workflow authoring and compilation for backend v2."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
import re
from types import MappingProxyType
from typing import Any

from core.parameter_contract import is_environment_parameter_name
from core.port_types import CatalogBuildError, FrozenCatalog, canonical_sha256
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

    def to_public(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "nodes": [node.to_public() for node in self.nodes],
            "edges": [edge.to_public() for edge in self.edges],
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
    )


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
    supplied_forbidden_path = _find_forbidden_environment_field(values)
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
    forbidden_path = _find_forbidden_environment_field(resolved)
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
        value_contract = declaration.get("value_contract", declaration)
        if not isinstance(value_contract, Mapping):
            raise WorkflowCompileError(
                "invalid_parameter",
                f"{field_name}.{name} has an invalid value contract",
                node_id=node_id,
                field_path=("nodes", node_id, field_name, name),
            )
        violation = _parameter_contract_violation(
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


def _find_forbidden_environment_field(
    value: Any,
    *,
    path: tuple[str | int, ...] = (),
) -> tuple[str | int, ...] | None:
    if isinstance(value, Mapping):
        for name, item in value.items():
            item_path = (*path, name)
            if is_environment_parameter_name(name):
                return item_path
            nested = _find_forbidden_environment_field(
                item,
                path=item_path,
            )
            if nested is not None:
                return nested
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            nested = _find_forbidden_environment_field(
                item,
                path=(*path, index),
            )
            if nested is not None:
                return nested
    return None


def _parameter_contract_violation(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: tuple[str | int, ...],
) -> tuple[tuple[str | int, ...], str] | None:
    """Return the first violation of one closed parameter value contract."""
    if "const" in schema and value != schema["const"]:
        return path, f"must equal {schema['const']!r}"
    if "enum" in schema and value not in schema["enum"]:
        return path, f"must be one of {_thaw_json(schema['enum'])!r}"

    for keyword in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if alternatives is None:
            continue
        results = [
            _parameter_contract_violation(value, item, path=path)
            for item in alternatives
            if isinstance(item, Mapping)
        ]
        matches = sum(result is None for result in results)
        if keyword == "allOf" and any(result is not None for result in results):
            return next(result for result in results if result is not None)
        if keyword == "anyOf" and matches == 0:
            return path, "must match at least one value-contract alternative"
        if keyword == "oneOf" and matches != 1:
            return path, "must match exactly one value-contract alternative"

    expected_type = schema.get("type")
    if isinstance(expected_type, (list, tuple)):
        valid_type = any(
            _parameter_type_matches(value, candidate)
            for candidate in expected_type
        )
    else:
        valid_type = (
            True
            if expected_type is None
            else _parameter_type_matches(value, expected_type)
        )
    if not valid_type:
        return path, f"must be {expected_type}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if minimum is not None and value < minimum:
            return path, f"must be at least {minimum}"
        if maximum is not None and value > maximum:
            return path, f"must be at most {maximum}"
        if exclusive_minimum is not None and value <= exclusive_minimum:
            return path, f"must be greater than {exclusive_minimum}"
        if exclusive_maximum is not None and value >= exclusive_maximum:
            return path, f"must be less than {exclusive_maximum}"

    if isinstance(value, str):
        if (
            schema.get("minLength") is not None
            and len(value) < schema["minLength"]
        ):
            return path, f"must contain at least {schema['minLength']} characters"
        if (
            schema.get("maxLength") is not None
            and len(value) > schema["maxLength"]
        ):
            return path, f"must contain at most {schema['maxLength']} characters"
        pattern = schema.get("pattern")
        if pattern is not None:
            try:
                matches = re.search(pattern, value) is not None
            except re.error:
                return path, "uses an invalid pattern in its value contract"
            if not matches:
                return path, f"must match {pattern!r}"

    if isinstance(value, (list, tuple)):
        if (
            schema.get("minItems") is not None
            and len(value) < schema["minItems"]
        ):
            return path, f"must contain at least {schema['minItems']} items"
        if (
            schema.get("maxItems") is not None
            and len(value) > schema["maxItems"]
        ):
            return path, f"must contain at most {schema['maxItems']} items"
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if item in value[:index]:
                    return (*path, index), "must be unique"
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                violation = _parameter_contract_violation(
                    item,
                    item_schema,
                    path=(*path, index),
                )
                if violation is not None:
                    return violation

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        if isinstance(required, (list, tuple)):
            missing = [name for name in required if name not in value]
            if missing:
                return path, f"must contain required fields {missing!r}"
        if (
            schema.get("minProperties") is not None
            and len(value) < schema["minProperties"]
        ):
            return path, f"must contain at least {schema['minProperties']} fields"
        if (
            schema.get("maxProperties") is not None
            and len(value) > schema["maxProperties"]
        ):
            return path, f"must contain at most {schema['maxProperties']} fields"
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            item_schema = (
                properties.get(name)
                if isinstance(properties, Mapping)
                else None
            )
            if item_schema is None:
                if additional is False:
                    return (*path, name), "is not an allowed field"
                item_schema = additional if isinstance(additional, Mapping) else None
            if isinstance(item_schema, Mapping):
                violation = _parameter_contract_violation(
                    item,
                    item_schema,
                    path=(*path, name),
                )
                if violation is not None:
                    return violation
    return None


def _parameter_type_matches(value: Any, expected_type: Any) -> bool:
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": type(value) is str,
        "array": isinstance(value, (list, tuple)),
        "object": isinstance(value, Mapping),
    }.get(expected_type, False)


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
