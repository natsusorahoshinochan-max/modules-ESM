"""Typed Workflow document and exact Contract Lock values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from core.catalog.port_contract import CatalogBuildError, canonical_sha256
from core.scoring.selection import (
    ContextSelector,
    ObservationSelector,
    PairwiseContextSelector,
    SelectionInput,
    SelectionObjective,
    SelectionError,
    observation_selector_canonical,
    selection_objective_canonical,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
)


WORKFLOW_SCHEMA_VERSION = "2.1.0"
WORKFLOW_DIGEST_NAMESPACE = "protein-workbench-workflow/v2"
CONTRACT_LOCK_NAMESPACE = "protein-workbench-contract-lock/v2"


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

def _exact_reference_from_admitted(
    value: Mapping[str, Any],
    name: str,
) -> ExactContractReference:
    reference = value[name]
    return ExactContractReference(
        contract_kind=reference["contract_kind"],
        contract_id=reference["contract_id"],
        contract_version=reference["contract_version"],
        contract_digest=reference["contract_digest"],
    )

def _selection_input_from_admitted(
    value: Mapping[str, Any],
) -> SelectionInput:
    return SelectionInput(value["node_id"], value["output_port"])

def _context_selector_from_admitted(
    value: Mapping[str, Any],
) -> ContextSelector:
    if value["kind"] == "intrinsic":
        return IntrinsicObservationContext(value["kind"])
    if value["kind"] == "calibration":
        return CalibrationObservationContext(
            calibration_metric=value["calibration_metric"],
            calibration_value=value["calibration_value"],
            calibration_unit=value["calibration_unit"],
            population_id=value["population_id"],
            kind=value["kind"],
        )
    return PairwiseContextSelector(
        pairing_mode=value["pairing_mode"],
        normalization=value["normalization"],
        subject_role=value["subject_role"],
        reference_role=value["reference_role"],
        kind=value["kind"],
    )

def _observation_selector_from_admitted(
    value: Mapping[str, Any],
) -> ObservationSelector:
    return ObservationSelector(
        selector_id=value["selector_id"],
        candidate_input=_selection_input_from_admitted(value["candidate_input"]),
        score_collection_input=_selection_input_from_admitted(
            value["score_collection_input"]
        ),
        metric=_exact_reference_from_admitted(value, "metric"),
        method=_exact_reference_from_admitted(value, "method"),
        context_selector=_context_selector_from_admitted(
            value["context_selector"]
        ),
        source_partition=value["source_partition"],
        match_cardinality=value["match_cardinality"],
        missing_policy=value["missing_policy"],
    )

def _selection_objective_from_admitted(
    value: Mapping[str, Any],
) -> SelectionObjective:
    return SelectionObjective(
        objective_id=value["objective_id"],
        candidate_input=_selection_input_from_admitted(value["candidate_input"]),
        score_collection_input=_selection_input_from_admitted(
            value["score_collection_input"]
        ),
        metric=_exact_reference_from_admitted(value, "metric"),
        method=_exact_reference_from_admitted(value, "method"),
        context_selector=_context_selector_from_admitted(
            value["context_selector"]
        ),
        utility_transform=_exact_reference_from_admitted(
            value,
            "utility_transform",
        ),
        utility_parameters=value["utility_parameters"],
        weight=value["weight"],
        source_partition=value["source_partition"],
        match_cardinality=value["match_cardinality"],
        missing_policy=value["missing_policy"],
    )

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
                observation_selector_canonical(selector)
                for selector in self.observation_selectors
            ],
            "selection_objectives": [
                selection_objective_canonical(objective)
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

class WorkflowDocumentError(ValueError):
    """A Workflow projection cannot hydrate the typed document."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)

def workflow_document_from_projection(
    payload: Mapping[str, Any],
) -> WorkflowDocument:
    """Hydrate a typed Workflow from an already-admitted projection."""
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
                _observation_selector_from_admitted(selector)
                for selector in payload.get("observation_selectors", ())
            ),
            selection_objectives=tuple(
                _selection_objective_from_admitted(objective)
                for objective in payload.get("selection_objectives", ())
            ),
        )
    except (CatalogBuildError, SelectionError, TypeError, ValueError) as error:
        raise WorkflowDocumentError(
            "malformed_request",
            f"Workflow document is invalid: {error}",
        ) from error
