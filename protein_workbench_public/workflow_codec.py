"""Current public Workflow request and response wire codec."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.port_contract import CatalogBuildError
from core.scoring.selection import SelectionError
from core.workflow.authoring import WorkflowCommit, WorkflowDraft
from core.workflow.document import (
    WORKFLOW_SCHEMA_VERSION,
    ContractLockEntry,
    WorkflowDocument,
    WorkflowDocumentError,
    WorkflowEdge,
    WorkflowNodeInstance,
)
from datatypes.i_json import thaw_i_json
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    validate_schema,
)
from protein_workbench_public.selection_codec import (
    observation_selector_from_public,
    observation_selector_to_public,
    selection_objective_from_public,
    selection_objective_to_public,
)


def _contract_lock_entry_from_public(
    payload: Mapping[str, Any],
) -> ContractLockEntry:
    return ContractLockEntry(
        contract_kind=payload["contract_kind"],
        contract_id=payload["contract_id"],
        contract_version=payload["contract_version"],
        contract_digest=payload["contract_digest"],
    )


def _workflow_node_from_public(
    payload: Mapping[str, Any],
) -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id=payload["node_id"],
        node_type_id=payload["node_type_id"],
        node_type_version=payload["node_type_version"],
        binding_id=payload["binding_id"],
        binding_version=payload["binding_version"],
        node_parameters=payload["node_parameters"],
        binding_parameters=payload["binding_parameters"],
    )


def _workflow_edge_from_public(
    payload: Mapping[str, Any],
) -> WorkflowEdge:
    return WorkflowEdge(
        source_node_id=payload["source_node_id"],
        source_port=payload["source_port"],
        target_node_id=payload["target_node_id"],
        target_port=payload["target_port"],
    )


def decode_admitted_workflow_document(
    payload: Mapping[str, Any],
) -> WorkflowDocument:
    """Hydrate a request already admitted by the enclosing REST schema."""
    try:
        return WorkflowDocument(
            schema_version=payload["schema_version"],
            workflow_id=payload["workflow_id"],
            nodes=tuple(
                _workflow_node_from_public(node)
                for node in payload["nodes"]
            ),
            edges=tuple(
                _workflow_edge_from_public(edge)
                for edge in payload["edges"]
            ),
            contract_lock=tuple(
                _contract_lock_entry_from_public(entry)
                for entry in payload["contract_lock"]
            ),
            observation_selectors=tuple(
                observation_selector_from_public(selector)
                for selector in payload.get("observation_selectors", ())
            ),
            selection_objectives=tuple(
                selection_objective_from_public(objective)
                for objective in payload.get("selection_objectives", ())
            ),
        )
    except (CatalogBuildError, SelectionError, TypeError, ValueError) as error:
        raise WorkflowDocumentError(
            "malformed_request",
            f"Workflow document is invalid: {error}",
        ) from error


def decode_workflow_document(payload: Mapping[str, Any]) -> WorkflowDocument:
    """Validate and decode one closed current public Workflow document."""
    try:
        validate_schema("#/$defs/WorkflowDocument", payload)
    except ProtocolValidationError as error:
        if payload.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
            code = "unsupported_schema_version"
        elif error.path.startswith("$.contract_lock"):
            code = "contract_digest_mismatch"
        else:
            code = "malformed_request"
        raise WorkflowDocumentError(
            code,
            f"Workflow document is invalid: {error.reason}",
        ) from error
    return decode_admitted_workflow_document(payload)


def _contract_lock_entry_to_public(
    entry: ContractLockEntry,
) -> dict[str, str]:
    return {
        "contract_kind": entry.contract_kind,
        "contract_id": entry.contract_id,
        "contract_version": entry.contract_version,
        "contract_digest": entry.contract_digest,
    }


def _workflow_node_to_public(
    node: WorkflowNodeInstance,
) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "node_type_id": node.node_type_id,
        "node_type_version": node.node_type_version,
        "binding_id": node.binding_id,
        "binding_version": node.binding_version,
        "node_parameters": thaw_i_json(node.node_parameters),
        "binding_parameters": thaw_i_json(node.binding_parameters),
    }


def _workflow_edge_to_public(edge: WorkflowEdge) -> dict[str, str]:
    return {
        "source_node_id": edge.source_node_id,
        "source_port": edge.source_port,
        "target_node_id": edge.target_node_id,
        "target_port": edge.target_port,
    }


def encode_workflow_document(workflow: WorkflowDocument) -> dict[str, Any]:
    """Encode one typed Workflow as the current public wire document."""
    return {
        "schema_version": workflow.schema_version,
        "workflow_id": workflow.workflow_id,
        "nodes": [_workflow_node_to_public(node) for node in workflow.nodes],
        "edges": [_workflow_edge_to_public(edge) for edge in workflow.edges],
        "observation_selectors": [
            observation_selector_to_public(selector)
            for selector in workflow.observation_selectors
        ],
        "selection_objectives": [
            selection_objective_to_public(objective)
            for objective in workflow.selection_objectives
        ],
        "contract_lock": [
            _contract_lock_entry_to_public(entry)
            for entry in workflow.contract_lock
        ],
    }


def encode_workflow_draft(draft: WorkflowDraft) -> dict[str, Any]:
    """Encode one typed Draft response in the current public schema."""
    return {
        "project_id": draft.project_id,
        "draft_revision": draft.draft_revision,
        "draft_digest": draft.draft_digest,
        "workflow": encode_workflow_document(draft.workflow),
    }


def encode_workflow_commit_receipt(
    commit: WorkflowCommit,
) -> dict[str, Any]:
    """Encode one typed Commit as the compact current public receipt."""
    return {
        "accepted": True,
        "workflow_commit_id": commit.workflow_commit_id,
        "workflow_commit_revision": commit.workflow_commit_revision,
        "source_draft_revision": commit.source_draft_revision,
        "source_draft_digest": commit.source_draft_digest,
        "workflow_digest": commit.workflow_digest,
        "catalog_contract_digest": commit.catalog_contract_digest,
        "contract_lock_digest": commit.contract_lock_digest,
        "execution_plan_digest": commit.execution_plan_digest,
        "issues": [],
    }
