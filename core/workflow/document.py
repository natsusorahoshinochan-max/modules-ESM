"""Typed Workflow document using stable Catalog IDs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from core.catalog.errors import CatalogBuildError
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
    if isinstance(value, (list, tuple)):
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

@dataclass(frozen=True, slots=True)
class WorkflowNodeInstance:
    """One v2 Node Instance with separated parameter scopes."""

    node_id: str
    node_type_id: str
    binding_id: str
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
    def from_canonical(
        cls,
        payload: Mapping[str, Any],
    ) -> WorkflowNodeInstance:
        """Hydrate one Node Instance from a durable canonical projection."""
        return cls(
            node_id=payload["node_id"],
            node_type_id=payload["node_type_id"],
            binding_id=payload["binding_id"],
            node_parameters=payload["node_parameters"],
            binding_parameters=payload["binding_parameters"],
        )

    def canonical_projection(self) -> dict[str, Any]:
        """Project the Node Instance for durable Workflow identity."""
        return {
            "node_id": self.node_id,
            "node_type_id": self.node_type_id,
            "binding_id": self.binding_id,
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
    def from_canonical(cls, payload: Mapping[str, Any]) -> WorkflowEdge:
        """Hydrate one edge from a durable canonical projection."""
        return cls(
            source_node_id=payload["source_node_id"],
            source_port=payload["source_port"],
            target_node_id=payload["target_node_id"],
            target_port=payload["target_port"],
        )

    def canonical_projection(self) -> dict[str, Any]:
        """Project the edge for durable Workflow and Plan identity."""
        return {
            "source_node_id": self.source_node_id,
            "source_port": self.source_port,
            "target_node_id": self.target_node_id,
            "target_port": self.target_port,
        }

@dataclass(frozen=True, slots=True)
class WorkflowDocument:
    """Immutable typed Workflow document."""

    schema_version: str
    workflow_id: str
    nodes: tuple[WorkflowNodeInstance, ...]
    edges: tuple[WorkflowEdge, ...]
    observation_selectors: tuple[ObservationSelector, ...] = ()
    selection_objectives: tuple[SelectionObjective, ...] = ()

    def canonical_projection(self) -> dict[str, Any]:
        """Project the durable canonical Workflow identity document."""
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "nodes": [
                node.canonical_projection() for node in self.nodes
            ],
            "edges": [
                edge.canonical_projection() for edge in self.edges
            ],
            "observation_selectors": [
                observation_selector_canonical(selector)
                for selector in self.observation_selectors
            ],
            "selection_objectives": [
                selection_objective_canonical(objective)
                for objective in self.selection_objectives
            ],
        }

class WorkflowDocumentError(ValueError):
    """A Workflow projection cannot hydrate the typed document."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)

def workflow_document_from_canonical(
    payload: Mapping[str, Any],
) -> WorkflowDocument:
    """Hydrate a typed Workflow from a durable canonical projection."""
    try:
        return WorkflowDocument(
            schema_version=payload["schema_version"],
            workflow_id=payload["workflow_id"],
            nodes=tuple(
                WorkflowNodeInstance.from_canonical(node)
                for node in payload["nodes"]
            ),
            edges=tuple(
                WorkflowEdge.from_canonical(edge)
                for edge in payload["edges"]
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
