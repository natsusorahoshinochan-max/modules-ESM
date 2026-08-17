"""Exact contract-locked Workflow authoring and compilation for backend v2."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
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
    ContractResolutionError,
    FrozenCatalog,
    InactiveContractGenerationError,
    UnknownContractError,
    canonical_json_bytes,
    canonical_sha256,
)
from core.operation import ResolvedProducedObservation
from core.scoring_v2 import (
    ObservationSelector,
    ResolvedMetricFacts,
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    SelectionError,
    SelectionObjective,
    observation_selector_identity_facts_from_facts,
    resolve_selection_objective,
    resolve_observation_selector,
    resolve_observation_selector_facts,
    resolve_metric_facts,
    resolve_selection_objective_facts,
    selection_objective_identity_facts_from_facts,
)
from datatypes import ExactContractReference
from protein_workbench_public import ProtocolValidationError, validate_schema


WORKFLOW_SCHEMA_VERSION = "2.1.0"
WORKFLOW_DIGEST_NAMESPACE = "protein-workbench-workflow/v2"
CONTRACT_LOCK_NAMESPACE = "protein-workbench-contract-lock/v2"
EXECUTION_PLAN_NAMESPACE = "protein-workbench-execution-plan/v3"
RESULT_IDENTITY_PLAN_FACTS_NAMESPACE = (
    "protein-workbench-result-identity-plan-facts/v1"
)

_PRESENTATION_CONTRACT_FIELDS = {
    "node_type": frozenset({"title", "summary", "category"}),
    "metric": frozenset({"title", "description"}),
}


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
    observation_selectors: tuple[ObservationSelector, ...] = ()
    selection_objectives: tuple[SelectionObjective, ...] = ()

    def to_public(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "nodes": [node.to_public() for node in self.nodes],
            "edges": [edge.to_public() for edge in self.edges],
            "observation_selectors": [
                selector.to_public()
                for selector in self.observation_selectors
            ],
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
class _ExecutionPlanPort:
    """One exact Port declaration paired with its admitted-value runtime."""

    declaration: Mapping[str, Any]
    port_type: Any = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declaration",
            _freeze_json(self.declaration),
        )


@dataclass(frozen=True, slots=True)
class _ExecutionPlanValueSource:
    """One compile-resolved upstream value source."""

    node_id: str
    output_port: str


@dataclass(frozen=True, slots=True)
class ResultIdentityPlanFacts:
    """Immutable compile-resolved static facts for one Result Identity."""

    identity_facts: Mapping[str, Any]
    node_parameter_indirections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identity_facts",
            _freeze_json(self.identity_facts),
        )
        object.__setattr__(
            self,
            "node_parameter_indirections",
            tuple(sorted(set(self.node_parameter_indirections))),
        )

    def identity_projection(self) -> dict[str, Any]:
        """Return one isolated canonical projection shared by runtime users."""
        return _thaw_json(self.identity_facts)

    def canonical_projection(self) -> dict[str, Any]:
        """Return the complete compiler-owned plan facts contract."""
        return {
            "schema_namespace": RESULT_IDENTITY_PLAN_FACTS_NAMESPACE,
            "identity_facts": self.identity_projection(),
            "node_parameter_indirections": list(
                self.node_parameter_indirections
            ),
        }

    def cache_contract_metadata(self) -> dict[str, Any]:
        """Project the exact static identity facts stored beside Cache data."""
        return {
            "result_identity_plan_facts": self.canonical_projection()
        }

    @property
    def digest(self) -> str:
        """Identify the exact compiler-owned facts recorded in Run evidence."""
        return canonical_sha256(self.canonical_projection())


@dataclass(frozen=True, slots=True)
class _ExecutionPlanNodeRuntime:
    """Private executable facts excluded from the public Plan digest."""

    node_contract: Any = field(repr=False, compare=False)
    binding_contract: Any = field(repr=False, compare=False)
    method_contract: Any = field(repr=False, compare=False)
    factory: Any = field(repr=False, compare=False)
    readiness_declaration: Any = field(repr=False, compare=False)
    effective_randomness_resolver: Any | None = field(
        repr=False,
        compare=False,
    )
    input_ports: Mapping[str, _ExecutionPlanPort] = field(
        repr=False,
        compare=False,
    )
    output_ports: Mapping[str, _ExecutionPlanPort] = field(
        repr=False,
        compare=False,
    )
    input_sources: Mapping[
        str,
        tuple[_ExecutionPlanValueSource, ...],
    ] = field(repr=False, compare=False)
    required_input_sources: Mapping[
        str,
        tuple[_ExecutionPlanValueSource, ...],
    ] = field(repr=False, compare=False)
    dependencies: tuple[str, ...]
    required_dependencies: tuple[str, ...]
    project_input_parameters: tuple[str, ...]
    produced_observations: tuple[ResolvedProducedObservation, ...] = field(
        repr=False,
        compare=False,
    )
    selection_objectives: tuple[ResolvedSelectionObjective, ...] = field(
        repr=False,
        compare=False,
    )
    observation_selectors: tuple[ResolvedObservationSelector, ...] = field(
        repr=False,
        compare=False,
    )
    selection_candidate_output_port: str | None
    produced_metric_facts: Mapping[
        tuple[str, str, str, str],
        ResolvedMetricFacts,
    ] = field(repr=False, compare=False)
    artifact_outputs: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        for name in ("input_ports", "output_ports", "produced_metric_facts"):
            object.__setattr__(
                self,
                name,
                MappingProxyType(dict(getattr(self, name))),
            )
        for name in ("input_sources", "required_input_sources"):
            object.__setattr__(
                self,
                name,
                MappingProxyType(
                    {
                        port_name: tuple(sources)
                        for port_name, sources in getattr(self, name).items()
                    }
                ),
            )
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(
            self,
            "required_dependencies",
            tuple(self.required_dependencies),
        )
        object.__setattr__(
            self,
            "project_input_parameters",
            tuple(self.project_input_parameters),
        )
        object.__setattr__(
            self,
            "produced_observations",
            tuple(self.produced_observations),
        )
        object.__setattr__(
            self,
            "selection_objectives",
            tuple(self.selection_objectives),
        )
        object.__setattr__(
            self,
            "observation_selectors",
            tuple(self.observation_selectors),
        )
        object.__setattr__(
            self,
            "artifact_outputs",
            tuple(_freeze_json(item) for item in self.artifact_outputs),
        )


@dataclass(frozen=True, slots=True)
class _ExecutionPlanRuntime:
    """Private Workflow-wide facts resolved atomically during compilation."""

    candidate_data_port_types: Mapping[str, Any] = field(
        repr=False,
        compare=False,
    )
    selection_objectives: tuple[ResolvedSelectionObjective, ...] = field(
        repr=False,
        compare=False,
    )
    observation_selectors: tuple[ResolvedObservationSelector, ...] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_data_port_types",
            MappingProxyType(dict(self.candidate_data_port_types)),
        )
        object.__setattr__(
            self,
            "selection_objectives",
            tuple(self.selection_objectives),
        )
        object.__setattr__(
            self,
            "observation_selectors",
            tuple(self.observation_selectors),
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
    result_identity_plan_facts: ResultIdentityPlanFacts
    _runtime: _ExecutionPlanNodeRuntime = field(repr=False, compare=False)

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
    workflow_commit_revision: int
    workflow_digest: str
    catalog_contract_digest: str
    contract_lock_digest: str
    execution_plan_digest: str
    nodes: tuple[ExecutionPlanNode, ...]
    edges: tuple[WorkflowEdge, ...]
    node_order: tuple[str, ...]
    resolved_contracts: tuple[ContractLockEntry, ...]
    _runtime: _ExecutionPlanRuntime = field(repr=False, compare=False)
    observation_selectors: tuple[ObservationSelector, ...] = ()
    selection_objectives: tuple[SelectionObjective, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "nodes",
            "edges",
            "node_order",
            "resolved_contracts",
            "observation_selectors",
            "selection_objectives",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class CompiledWorkflow:
    """One private, exact compiler-resolved Execution Plan."""

    execution_plan: ExecutionPlan


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


def _require_workflow_contract(
    catalog: FrozenCatalog,
    contract_kind: str,
    contract_id: str,
    contract_version: str,
    *,
    identity_path: tuple[str | int, ...],
    version_path: tuple[str | int, ...],
    node_id: str | None = None,
) -> Any:
    try:
        return catalog.require_contract(
            contract_kind,
            contract_id,
            contract_version,
        )
    except InactiveContractGenerationError as error:
        raise WorkflowCompileError(
            "inactive_generation",
            (
                "Workflow requested exact contract version "
                f"{contract_kind}:{contract_id}@{contract_version}, which is "
                "not active; "
                f"the active Catalog generation publishes {error.active_version}"
            ),
            node_id=node_id,
            field_path=version_path,
        ) from error
    except UnknownContractError as error:
        raise WorkflowCompileError(
            "unknown_contract",
            (
                "Workflow references unknown contract "
                f"{contract_kind}:{contract_id}@{contract_version}"
            ),
            node_id=node_id,
            field_path=identity_path,
        ) from error


def _workflow_contract_references(
    workflow: WorkflowDocument,
) -> tuple[
    tuple[
        str,
        ExactContractReference,
        tuple[str | int, ...],
        tuple[str | int, ...],
    ],
    ...,
]:
    references: list[
        tuple[
            str,
            ExactContractReference,
            tuple[str | int, ...],
            tuple[str | int, ...],
        ]
    ] = []
    for collection_name, selectors in (
        ("observation_selectors", workflow.observation_selectors),
        ("selection_objectives", workflow.selection_objectives),
    ):
        for index, selector in enumerate(selectors):
            fields = [
                ("metric", "metric", selector.metric),
                ("method", "method", selector.method),
            ]
            if isinstance(selector, SelectionObjective):
                fields.append(
                    (
                        "utility_transform",
                        "utility_transform",
                        selector.utility_transform,
                    )
                )
            for field_name, contract_kind, reference in fields:
                field_path = (collection_name, index, field_name)
                if reference.contract_kind != contract_kind:
                    raise WorkflowCompileError(
                        "contract_kind_mismatch",
                        (
                            f"Workflow {field_name} requires an exact "
                            f"{contract_kind} contract reference, received "
                            f"{reference.contract_kind}"
                        ),
                        field_path=(*field_path, "contract_kind"),
                    )
                references.append(
                    (
                        contract_kind,
                        reference,
                        (*field_path, "contract_id"),
                        (*field_path, "contract_version"),
                    )
                )
    return tuple(references)


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
    return workflow_document_from_admitted_public(payload)


def workflow_document_from_admitted_public(
    payload: Mapping[str, Any],
) -> WorkflowDocument:
    """Construct a typed Workflow after exact bundle admission.

    This is not a public wire-admission interface. Callers must first admit
    ``payload`` against the exact current ``WorkflowDocument`` bundle schema.
    """
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
            observation_selectors=tuple(
                ObservationSelector.from_public(selector)
                for selector in payload.get("observation_selectors", ())
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
    for index, node in enumerate(workflow.nodes):
        for kind, contract_id, version, field_prefix in (
            (
                "node_type",
                node.node_type_id,
                node.node_type_version,
                "node_type",
            ),
            (
                "binding",
                node.binding_id,
                node.binding_version,
                "binding",
            ),
        ):
            contract = _require_workflow_contract(
                catalog,
                kind,
                contract_id,
                version,
                identity_path=("nodes", index, f"{field_prefix}_id"),
                version_path=("nodes", index, f"{field_prefix}_version"),
                node_id=node.node_id,
            )
            pending.append(ContractLockEntry.from_public(contract.reference()))
    for kind, reference, identity_path, version_path in (
        _workflow_contract_references(workflow)
    ):
        contract = _require_workflow_contract(
            catalog,
            kind,
            reference.contract_id,
            reference.contract_version,
            identity_path=identity_path,
            version_path=version_path,
        )
        if reference.contract_digest != contract.contract_digest:
            raise WorkflowCompileError(
                "contract_digest_mismatch",
                (
                    "Workflow exact contract reference digest does not match "
                    "the active Catalog contract"
                ),
                field_path=(*version_path[:-1], "contract_digest"),
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


def _require_matching_lock(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> tuple[ContractLockEntry, ...]:
    try:
        expected = _reachable_contract_lock(workflow, catalog)
    except (CatalogBuildError, ContractResolutionError) as error:
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
        node_contract = _require_workflow_contract(
            catalog,
            "node_type",
            node.node_type_id,
            node.node_type_version,
            identity_path=("nodes", index, "node_type_id"),
            version_path=("nodes", index, "node_type_version"),
            node_id=node.node_id,
        )
        binding_contract = _require_workflow_contract(
            catalog,
            "binding",
            node.binding_id,
            node.binding_version,
            identity_path=("nodes", index, "binding_id"),
            version_path=("nodes", index, "binding_version"),
            node_id=node.node_id,
        )
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
    for kind, reference, identity_path, version_path in (
        _workflow_contract_references(workflow)
    ):
        _require_workflow_contract(
            catalog,
            kind,
            reference.contract_id,
            reference.contract_version,
            identity_path=identity_path,
            version_path=version_path,
        )


def validate_workflow_generation(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
) -> None:
    """Require active exact references and any present Lock to be current."""
    validate_workflow_parameter_values(workflow, catalog)
    if workflow.contract_lock:
        _require_matching_lock(workflow, catalog)
    else:
        _reachable_contract_lock(workflow, catalog)


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
        catalog,
        nodes_by_id=nodes_by_id,
        plan_nodes=plan_nodes,
        node_order=tuple(order),
    )
    _validate_observation_selectors(
        workflow,
        catalog,
        nodes_by_id=nodes_by_id,
        plan_nodes=plan_nodes,
        node_order=tuple(order),
    )
    _validate_selection_objective_consumers(
        workflow,
        plan_nodes=plan_nodes,
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


def _validate_observation_selectors(
    workflow: WorkflowDocument,
    catalog: FrozenCatalog,
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
            == selector.context_selector.to_public()
            and capability.get("subject_grain") == "candidate"
            and capability.get("source_role") == "subject"
            and capability.get("guaranteed_multiplicity") == "one"
            and capability.get("subject_source")
            == selector.candidate_input.to_public()
        ]
        if len(produced) != 1:
            if any(
                capability.get("source_partition")
                == selector.source_partition
                and capability.get("metric") == requested_metric
                and capability.get("context_profile")
                == selector.context_selector.to_public()
                and capability.get("subject_grain") == "candidate"
                and capability.get("source_role") == "subject"
                and capability.get("guaranteed_multiplicity") == "one"
                and capability.get("subject_source")
                == selector.candidate_input.to_public()
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
        try:
            resolve_observation_selector(selector, catalog)
        except SelectionError as error:
            raise WorkflowCompileError(
                "invalid_observation_selector",
                str(error),
                field_path=selector_path,
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


def _validate_selection_objective_consumers(
    workflow: WorkflowDocument,
    *,
    plan_nodes: Mapping[str, tuple[Any, Any]],
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
    nodes = {node.node_id: node for node in workflow.nodes}
    for node_id, (node_contract, binding) in plan_nodes.items():
        selector_consumption = binding.descriptor.get(
            "observation_selector_consumption"
        )
        if isinstance(selector_consumption, Mapping):
            node = nodes[node_id]
            parameters = _validate_parameter_values(
                node.node_parameters,
                node_contract.descriptor.get("node_parameters", {}),
                node_id=node_id,
                field_name="node_parameters",
            )
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
                        node_id,
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
                if connected != reference.to_public():
                    raise WorkflowCompileError(
                        "unsatisfied_selector",
                        f"Selection {label} input does not match the exact "
                        "Workflow Observation Selector source",
                        node_id=node_id,
                        field_path=(
                            "nodes",
                            node_id,
                            "inputs",
                            port_name or "",
                        ),
                    )
            selector_consumers[selector.selector_id].append(node_id)
            continue
        consumption = binding.descriptor.get(
            "selection_objective_consumption"
        )
        if not isinstance(consumption, Mapping):
            continue
        node = nodes[node_id]
        parameters = _validate_parameter_values(
            node.node_parameters,
            node_contract.descriptor.get("node_parameters", {}),
            node_id=node_id,
            field_name="node_parameters",
        )
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
                    node_id,
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
                (connected["node_id"], connected["output_port"])
                if connected is not None
                else None
            )
            if (
                len(expected_sources) != 1
                or connected_source not in expected_sources
            ):
                raise WorkflowCompileError(
                    "unsatisfied_selector",
                    f"Selection {label} input does not match the exact "
                    "Workflow Selection Objective sources",
                    node_id=node_id,
                    field_path=("nodes", node_id, "inputs", port_name or ""),
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
    source_plan = plan_nodes.get(source["node_id"])
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
                "source_partition": declaration.get(
                    "output_partition",
                    "default",
                ),
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


def _contract_descriptor(contract: Any) -> Mapping[str, Any]:
    descriptor = contract.descriptor
    return descriptor() if callable(descriptor) else descriptor


def _resolved_produced_observations(
    binding_contract: Any,
) -> tuple[ResolvedProducedObservation, ...]:
    return tuple(
        ResolvedProducedObservation(
            output_port=declaration["output_port"],
            output_partition=declaration.get(
                "output_partition",
                "default",
            ),
            metric=ExactContractReference(**declaration["metric"]),
            context_profile=declaration["context_profile"],
            subject_grain=declaration["subject_grain"],
            source_role=declaration["source_role"],
            subject_direction=declaration["subject_direction"],
            subject_port=declaration["subject_port"],
            guaranteed_multiplicity=declaration[
                "guaranteed_multiplicity"
            ],
            reference_direction=declaration.get("reference_direction"),
            reference_port=declaration.get("reference_port"),
            pairing_direction=declaration.get("pairing_direction"),
            pairing_port=declaration.get("pairing_port"),
            axis_direction=declaration.get("axis_direction"),
            axis_port=declaration.get("axis_port"),
            method_direction=declaration.get("method_direction"),
            method_port=declaration.get("method_port"),
        )
        for declaration in binding_contract.descriptor.get(
            "produced_observations",
            (),
        )
    )


def _selected_objectives(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    node_parameters: Mapping[str, Any],
    binding_contract: Any,
) -> tuple[SelectionObjective, ...]:
    consumption = binding_contract.descriptor.get(
        "selection_objective_consumption"
    )
    if not isinstance(consumption, Mapping):
        return ()
    scalar_parameter = consumption.get("objective_id_parameter")
    ordered_parameter = consumption.get("objective_ids_parameter")
    if isinstance(scalar_parameter, str):
        objective_ids = (node_parameters.get(scalar_parameter),)
    elif isinstance(ordered_parameter, str):
        raw_ids = node_parameters.get(ordered_parameter)
        objective_ids = (
            tuple(raw_ids) if isinstance(raw_ids, (list, tuple)) else ()
        )
    else:
        objective_ids = ()
    objectives = {
        objective.objective_id: objective
        for objective in workflow.selection_objectives
    }
    if (
        not objective_ids
        or any(not isinstance(item, str) for item in objective_ids)
        or any(item not in objectives for item in objective_ids)
    ):
        raise WorkflowCompileError(
            "invalid_selection_objective_consumer",
            "Selection Objective consumption did not resolve during compilation",
            node_id=node_id,
        )
    return tuple(objectives[item] for item in objective_ids)


def _selected_observation_selectors(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    node_parameters: Mapping[str, Any],
    binding_contract: Any,
) -> tuple[ObservationSelector, ...]:
    consumption = binding_contract.descriptor.get(
        "observation_selector_consumption"
    )
    if not isinstance(consumption, Mapping):
        return ()
    parameter = consumption.get("selector_id_parameter")
    selector_id = (
        node_parameters.get(parameter)
        if isinstance(parameter, str)
        else None
    )
    selectors = {
        selector.selector_id: selector
        for selector in workflow.observation_selectors
    }
    if not isinstance(selector_id, str) or selector_id not in selectors:
        raise WorkflowCompileError(
            "invalid_observation_selector_consumer",
            "Observation Selector consumption did not resolve during compilation",
            node_id=node_id,
        )
    return (selectors[selector_id],)


def _nested_contract_keys(value: Any) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        reference = _reference_from_value(current)
        if reference is not None:
            keys.add(reference.key)
        elif isinstance(current, Mapping):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return keys


def _identity_without_digest(reference: Mapping[str, Any]) -> dict[str, str]:
    return {
        "contract_kind": reference["contract_kind"],
        "contract_id": reference["contract_id"],
        "contract_version": reference["contract_version"],
    }


def _normalize_nested_contract_references(value: Any) -> Any:
    if isinstance(value, Mapping):
        fields = set(value)
        is_contract_reference = fields == {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        }
        return {
            str(key): _normalize_nested_contract_references(item)
            for key, item in value.items()
            if not (is_contract_reference and key == "contract_digest")
        }
    if isinstance(value, (list, tuple)):
        return [
            _normalize_nested_contract_references(item)
            for item in value
        ]
    return value


def _result_affecting_contract(contract: Any) -> dict[str, Any]:
    descriptor = _contract_descriptor(contract)
    contract_kind = descriptor["contract_kind"]
    presentation_fields = _PRESENTATION_CONTRACT_FIELDS.get(
        contract_kind,
        (),
    )
    return {
        "contract_kind": contract_kind,
        "contract_id": descriptor["contract_id"],
        "contract_version": descriptor["contract_version"],
        "descriptor": _normalize_nested_contract_references(
            {
                key: value
                for key, value in descriptor.items()
                if key not in presentation_fields
            }
        ),
    }


def _result_contracts_for_node(
    *,
    node_contract: Any,
    binding_contract: Any,
    selected_objectives: tuple[SelectionObjective, ...],
    selected_selectors: tuple[ObservationSelector, ...],
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> tuple[Any, ...]:
    keys = {
        (
            node_contract.contract_kind,
            node_contract.contract_id,
            node_contract.contract_version,
        ),
        (
            binding_contract.contract_kind,
            binding_contract.contract_id,
            binding_contract.contract_version,
        ),
        (
            binding_contract.descriptor["method"]["contract_kind"],
            binding_contract.descriptor["method"]["contract_id"],
            binding_contract.descriptor["method"]["contract_version"],
        ),
        *{
            (
                port["port_type"]["contract_kind"],
                port["port_type"]["contract_id"],
                port["port_type"]["contract_version"],
            )
            for direction in ("inputs", "outputs")
            for port in node_contract.descriptor.get(direction, ())
        },
        *{
            (
                observation["metric"]["contract_kind"],
                observation["metric"]["contract_id"],
                observation["metric"]["contract_version"],
            )
            for observation in binding_contract.descriptor.get(
                "produced_observations",
                (),
            )
        },
    }
    for objective in selected_objectives:
        keys.update(
            (
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            )
            for reference in (
                objective.metric,
                objective.method,
                objective.utility_transform,
            )
        )
    for selector in selected_selectors:
        keys.update(
            (
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            )
            for reference in (selector.metric, selector.method)
        )
    pending = list(keys)
    while pending:
        key = pending.pop()
        try:
            contract = resolved_by_key[key]
        except KeyError as error:
            raise WorkflowCompileError(
                "contract_lock_mismatch",
                "Execution Plan result contract is outside the exact Lock",
            ) from error
        for nested_key in _nested_contract_keys(
            _contract_descriptor(contract)
        ):
            if nested_key not in keys:
                if nested_key not in resolved_by_key:
                    raise WorkflowCompileError(
                        "contract_lock_mismatch",
                        "Execution Plan nested contract is outside the exact Lock",
                    )
                keys.add(nested_key)
                pending.append(nested_key)
    return tuple(resolved_by_key[key] for key in sorted(keys))


def _result_identity_plan_facts(
    *,
    node_contract: Any,
    binding_contract: Any,
    method_contract: Any,
    result_contracts: tuple[Any, ...],
    selected_objectives: tuple[ResolvedSelectionObjective, ...],
    selected_selectors: tuple[ResolvedObservationSelector, ...],
) -> ResultIdentityPlanFacts:
    objective_consumption = binding_contract.descriptor.get(
        "selection_objective_consumption"
    )
    selector_consumption = binding_contract.descriptor.get(
        "observation_selector_consumption"
    )
    facts: dict[str, Any] = {
        "node_type": _identity_without_digest(node_contract.reference()),
        "binding": _identity_without_digest(binding_contract.reference()),
        "method": _identity_without_digest(method_contract.reference()),
        "resolved_result_contracts": [
            _result_affecting_contract(contract)
            for contract in result_contracts
        ],
        "input_contracts": [
            {
                "input_port": port["name"],
                "port_type": _identity_without_digest(port["port_type"]),
                "required": port["required"],
                "multiplicity": port["multiplicity"],
                "scientific_meaning": port["scientific_meaning"],
            }
            for port in node_contract.descriptor.get("inputs", ())
        ],
        "output_contracts": [
            {
                "output_port": port["name"],
                "port_type": _identity_without_digest(port["port_type"]),
                "required": port["required"],
                "multiplicity": port["multiplicity"],
                "scientific_meaning": port["scientific_meaning"],
            }
            for port in node_contract.descriptor.get("outputs", ())
        ],
        "produced_observations": _normalize_nested_contract_references(
            binding_contract.descriptor.get("produced_observations", ())
        ),
    }
    node_parameter_indirections: list[str] = []
    if selected_objectives:
        if not isinstance(objective_consumption, Mapping):
            raise WorkflowCompileError(
                "invalid_selection_objective_consumer",
                "Selection Objective facts lack exact local input roles",
            )
        candidate_input_port = objective_consumption.get(
            "candidate_input_port"
        )
        score_collection_input_port = objective_consumption.get(
            "score_collection_input_port"
        )
        if not isinstance(candidate_input_port, str) or not isinstance(
            score_collection_input_port,
            str,
        ):
            raise WorkflowCompileError(
                "invalid_selection_objective_consumer",
                "Selection Objective facts lack exact local input roles",
            )
        facts["selection_objectives"] = list(
            selection_objective_identity_facts_from_facts(
                selected_objectives,
                candidate_input_port=candidate_input_port,
                score_collection_input_port=score_collection_input_port,
            )
        )
        node_parameter_indirections.extend(
            parameter
            for parameter in (
                objective_consumption.get("objective_id_parameter"),
                objective_consumption.get("objective_ids_parameter"),
            )
            if isinstance(parameter, str)
        )
    if selected_selectors:
        if not isinstance(selector_consumption, Mapping):
            raise WorkflowCompileError(
                "invalid_observation_selector_consumer",
                "Observation Selector facts lack exact local input roles",
            )
        candidate_input_port = selector_consumption.get(
            "candidate_input_port"
        )
        score_collection_input_port = selector_consumption.get(
            "score_collection_input_port"
        )
        if not isinstance(candidate_input_port, str) or not isinstance(
            score_collection_input_port,
            str,
        ):
            raise WorkflowCompileError(
                "invalid_observation_selector_consumer",
                "Observation Selector facts lack exact local input roles",
            )
        facts["observation_selectors"] = list(
            observation_selector_identity_facts_from_facts(
                selected_selectors,
                candidate_input_port=candidate_input_port,
                score_collection_input_port=score_collection_input_port,
            )
        )
        parameter = selector_consumption.get("selector_id_parameter")
        if isinstance(parameter, str):
            node_parameter_indirections.append(parameter)
    return ResultIdentityPlanFacts(
        identity_facts=facts,
        node_parameter_indirections=tuple(node_parameter_indirections),
    )


def compile_workflow(
    workflow: WorkflowDocument,
    *,
    workflow_commit_revision: int,
    catalog: FrozenCatalog,
) -> CompiledWorkflow:
    """Compile one exact Lock before consulting runtime Availability."""
    resolved_contracts = _require_matching_lock(workflow, catalog)
    node_order = _validate_static_semantics(workflow, catalog)
    lock_by_key = {entry.key: entry for entry in resolved_contracts}
    resolved_by_key = {
        entry.key: catalog.require_contract(*entry.key)
        for entry in resolved_contracts
    }
    candidate_data_port_types = {
        definition.type_id: definition
        for definition in catalog.port_types
        if definition.type_id
        in {
            "protein.sequence",
            "protein.structure",
        }
    }
    resolved_workflow_objectives = tuple(
        resolve_selection_objective_facts(objective, catalog)
        for objective in workflow.selection_objectives
    )
    resolved_objectives_by_id = {
        item.objective.objective_id: item
        for item in resolved_workflow_objectives
    }
    resolved_workflow_selectors = tuple(
        resolve_observation_selector_facts(selector, catalog)
        for selector in workflow.observation_selectors
    )
    resolved_selectors_by_id = {
        item.selector.selector_id: item
        for item in resolved_workflow_selectors
    }
    nodes: list[ExecutionPlanNode] = []
    for node_id in node_order:
        node = next(item for item in workflow.nodes if item.node_id == node_id)
        node_type_contract = resolved_by_key[
            ("node_type", node.node_type_id, node.node_type_version)
        ]
        binding = resolved_by_key[
            ("binding", node.binding_id, node.binding_version)
        ]
        method_reference = ContractLockEntry.from_public(
            binding.descriptor["method"]
        )
        method_contract = resolved_by_key[method_reference.key]
        normalized_node_parameters = _validate_parameter_values(
            node.node_parameters,
            node_type_contract.descriptor.get("node_parameters", {}),
            node_id=node.node_id,
            field_name="node_parameters",
        )
        normalized_binding_parameters = _validate_parameter_values(
            node.binding_parameters,
            binding.descriptor.get("binding_parameters", {}),
            node_id=node.node_id,
            field_name="binding_parameters",
        )
        selected_objectives = _selected_objectives(
            workflow,
            node_id=node.node_id,
            node_parameters=normalized_node_parameters,
            binding_contract=binding,
        )
        selected_selectors = _selected_observation_selectors(
            workflow,
            node_id=node.node_id,
            node_parameters=normalized_node_parameters,
            binding_contract=binding,
        )
        resolved_selected_objectives = tuple(
            resolved_objectives_by_id[item.objective_id]
            for item in selected_objectives
        )
        resolved_selected_selectors = tuple(
            resolved_selectors_by_id[item.selector_id]
            for item in selected_selectors
        )

        def resolved_ports(direction: str) -> dict[str, _ExecutionPlanPort]:
            ports: dict[str, _ExecutionPlanPort] = {}
            for declaration in node_type_contract.descriptor.get(
                direction,
                (),
            ):
                reference = declaration["port_type"]
                key = (
                    reference["contract_kind"],
                    reference["contract_id"],
                    reference["contract_version"],
                )
                port_type = resolved_by_key[key]
                if port_type.contract_digest != reference["contract_digest"]:
                    raise WorkflowCompileError(
                        "contract_digest_mismatch",
                        "Port Type runtime does not match its exact declaration",
                        node_id=node.node_id,
                    )
                ports[declaration["name"]] = _ExecutionPlanPort(
                    declaration,
                    port_type,
                )
            return ports

        input_ports = resolved_ports("inputs")
        output_ports = resolved_ports("outputs")
        input_sources: dict[
            str,
            list[_ExecutionPlanValueSource],
        ] = {}
        for edge in workflow.edges:
            if edge.target_node_id != node.node_id:
                continue
            input_sources.setdefault(edge.target_port, []).append(
                _ExecutionPlanValueSource(
                    edge.source_node_id,
                    edge.source_port,
                )
            )
        frozen_input_sources = {
            port_name: tuple(sources)
            for port_name, sources in input_sources.items()
        }
        required_port_names = {
            name
            for name, port in input_ports.items()
            if port.declaration.get("required") is True
        }
        for constraint in node_type_contract.descriptor.get(
            "input_constraints",
            (),
        ):
            if constraint.get("kind") == "exactly_one":
                required_port_names.update(
                    port_name
                    for port_name in constraint["ports"]
                    if port_name in frozen_input_sources
                )
        required_input_sources = {
            port_name: frozen_input_sources[port_name]
            for port_name in sorted(required_port_names)
            if port_name in frozen_input_sources
        }
        produced_observations = _resolved_produced_observations(binding)
        produced_metric_facts = {
            (
                observation.metric.contract_kind,
                observation.metric.contract_id,
                observation.metric.contract_version,
                observation.metric.contract_digest,
            ): resolve_metric_facts(observation.metric, catalog)
            for observation in produced_observations
        }
        artifact_outputs: list[Mapping[str, Any]] = []
        for port_name, port in output_ports.items():
            artifact_kind = port.declaration.get("artifact_kind")
            if artifact_kind is None:
                continue
            accepted_media_types = port.port_type.artifact_media_types
            if accepted_media_types is None:
                raise WorkflowCompileError(
                    "invalid_artifact_contract",
                    "Artifact Port lacks a publication media contract",
                    node_id=node.node_id,
                )
            artifact_outputs.append(
                {
                    "output_port": port_name,
                    "artifact_kind": artifact_kind,
                    "artifact_media_type": port.declaration.get(
                        "artifact_media_type"
                    ),
                    "port_type": dict(port.declaration["port_type"]),
                    "accepted_media_types": tuple(accepted_media_types),
                }
            )
        objective_consumption = binding.descriptor.get(
            "selection_objective_consumption"
        )
        selector_consumption = binding.descriptor.get(
            "observation_selector_consumption"
        )
        selection_consumption = (
            selector_consumption
            if isinstance(selector_consumption, Mapping)
            else objective_consumption
            if isinstance(objective_consumption, Mapping)
            else None
        )
        result_contracts = _result_contracts_for_node(
            node_contract=node_type_contract,
            binding_contract=binding,
            selected_objectives=selected_objectives,
            selected_selectors=selected_selectors,
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
            node_contract=node_type_contract,
            binding_contract=binding,
            method_contract=method_contract,
            factory=catalog.require_factory(
                node.binding_id,
                node.binding_version,
            ),
            readiness_declaration=catalog.require_readiness_declaration(
                node.binding_id,
                node.binding_version,
            ),
            effective_randomness_resolver=(
                catalog.get_effective_randomness_resolver(
                    node.binding_id,
                    node.binding_version,
                )
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
            required_dependencies=tuple(
                sorted(
                    {
                        source.node_id
                        for sources in required_input_sources.values()
                        for source in sources
                    }
                )
            ),
            project_input_parameters=tuple(
                parameter_name
                for parameter_name, declaration in sorted(
                    node_type_contract.descriptor.get(
                        "node_parameters",
                        {},
                    ).items()
                )
                if declaration.get("resource_kind") == "project_input"
            ),
            produced_observations=produced_observations,
            selection_objectives=resolved_selected_objectives,
            observation_selectors=resolved_selected_selectors,
            selection_candidate_output_port=(
                selection_consumption.get("candidate_output_port")
                if isinstance(selection_consumption, Mapping)
                else None
            ),
            produced_metric_facts=produced_metric_facts,
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
                method=lock_by_key[method_reference.key],
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
        "node_order": list(node_order),
        "nodes": [
            {
                "node_id": node.node_id,
                "node_type": node.node_type.to_public(),
                "binding": node.binding.to_public(),
                "method": node.method.to_public(),
                "node_parameters": _thaw_json(node.node_parameters),
                "binding_parameters": _thaw_json(node.binding_parameters),
                "result_identity_plan_facts_digest": (
                    node.result_identity_plan_facts.digest
                ),
            }
            for node in nodes
        ],
        "edges": [edge.to_public() for edge in workflow.edges],
        "observation_selectors": [
            selector.to_public()
            for selector in workflow.observation_selectors
        ],
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
        workflow_commit_revision=workflow_commit_revision,
        workflow_digest=workflow.digest,
        catalog_contract_digest=catalog.contract_digest,
        contract_lock_digest=workflow.contract_lock_digest,
        execution_plan_digest=execution_plan_digest,
        nodes=tuple(nodes),
        edges=workflow.edges,
        node_order=node_order,
        resolved_contracts=resolved_contracts,
        _runtime=_ExecutionPlanRuntime(
            candidate_data_port_types=candidate_data_port_types,
            selection_objectives=resolved_workflow_objectives,
            observation_selectors=resolved_workflow_selectors,
        ),
        observation_selectors=workflow.observation_selectors,
        selection_objectives=workflow.selection_objectives,
    )
    return CompiledWorkflow(plan)
