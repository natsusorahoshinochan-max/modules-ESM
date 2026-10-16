"""Typed Workflow document using stable Catalog IDs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.catalog.errors import CatalogBuildError
from datatypes.i_json import freeze_i_json, thaw_i_json


WORKFLOW_SCHEMA_VERSION = "2.1.0"


@dataclass(frozen=True, slots=True)
class WorkflowNodeInstance:
    """One v2 Node Instance with separated parameter scopes."""

    node_id: str
    node_type_id: str
    binding_id: str
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    preserved_configuration: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_parameters",
            freeze_i_json(self.node_parameters),
        )
        object.__setattr__(
            self,
            "binding_parameters",
            freeze_i_json(self.binding_parameters),
        )
        if self.preserved_configuration is not None:
            object.__setattr__(self, "preserved_configuration", freeze_i_json(self.preserved_configuration))

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
            preserved_configuration=payload.get("preserved_configuration"),
        )

    def canonical_projection(self) -> dict[str, Any]:
        """Project the Node Instance for durable Workflow identity."""
        return {
            "node_id": self.node_id,
            "node_type_id": self.node_type_id,
            "binding_id": self.binding_id,
            "node_parameters": thaw_i_json(self.node_parameters),
            "binding_parameters": thaw_i_json(self.binding_parameters),
            **({"preserved_configuration": thaw_i_json(self.preserved_configuration)}
               if self.preserved_configuration is not None else {}),
        }

@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    """One named exact Port connection."""

    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str
    target_slot: str | None = None

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> WorkflowEdge:
        """Hydrate one edge from a durable canonical projection."""
        return cls(
            source_node_id=payload["source_node_id"],
            source_port=payload["source_port"],
            target_node_id=payload["target_node_id"],
            target_port=payload["target_port"],
            target_slot=payload.get("target_slot"),
        )

    def canonical_projection(self) -> dict[str, Any]:
        """Project the edge for durable Workflow and Plan identity."""
        return {
            "source_node_id": self.source_node_id,
            "source_port": self.source_port,
            "target_node_id": self.target_node_id,
            "target_port": self.target_port,
            **({"target_slot": self.target_slot} if self.target_slot is not None else {}),
        }

@dataclass(frozen=True, slots=True)
class WorkflowDocument:
    """Immutable typed Workflow document."""

    schema_version: str
    workflow_id: str
    nodes: tuple[WorkflowNodeInstance, ...]
    edges: tuple[WorkflowEdge, ...]

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
        )
    except (CatalogBuildError, TypeError, ValueError) as error:
        raise WorkflowDocumentError(
            "malformed_request",
            f"Workflow document is invalid: {error}",
        ) from error
