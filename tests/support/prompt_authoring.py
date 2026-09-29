"""Public Prompt authoring helpers for acceptance workflows.

Prompt Studio edits one ordinary ``prompt_authoring.author`` Node Instance in
the project's Workflow Draft (spec 2026-09-02 §9.1/§12.3): ``open`` reads the
node's ``document`` parameter, ``preview`` applies the document through the
single recipe implementation, and confirmed documents are submitted as complete Workspace edits.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def install_prompt_authoring_workflow(
    client: Any,
    project_id: str,
    workflow: Mapping[str, Any],
) -> None:
    """Place the complete workflow (author Nodes included) into the draft."""
    response = client.put(
        f"/api/v2/projects/{project_id}/workspace",
        json={"workflow": workflow},
    )
    response.raise_for_status()


def open_pdb_prompt_document(
    client: Any,
    project_id: str,
    node_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:open",
        json={"node_id": node_id},
    )
    response.raise_for_status()
    return response.json()


def open_blank_prompt_document(
    client: Any,
    project_id: str,
    node_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:open",
        json={"node_id": node_id},
    )
    response.raise_for_status()
    return response.json()


def preview_prompt_document(
    client: Any,
    project_id: str,
    node_id: str,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:preview",
        json={"node_id": node_id, "document": document},
    )
    response.raise_for_status()
    return response.json()


def workflow_with_prompt_document(
    workflow: Mapping[str, Any],
    node_id: str,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare a complete prospective Workflow without writing any state."""
    return {
        **workflow,
        "nodes": [
            {**node, "node_parameters": {**node["node_parameters"], "document": dict(document)}}
            if node["node_id"] == node_id else node
            for node in workflow["nodes"]
        ],
    }
