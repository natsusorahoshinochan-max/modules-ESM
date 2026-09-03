"""Public Prompt authoring helpers for acceptance workflows.

Prompt Studio edits one ordinary ``prompt_authoring.author`` Node Instance in
the project's Workflow Draft (spec 2026-09-02 §9.1/§12.3): ``open`` reads the
node's ``document`` parameter, ``preview`` applies the document through the
single recipe implementation, and ``apply`` writes the confirmed document
back onto the same node.
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
        f"/api/v2/projects/{project_id}/workflow/draft",
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


def apply_prompt_document(
    client: Any,
    project_id: str,
    node_id: str,
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:apply",
        json={
            "node_id": node_id,
            "document": preview["normalized_document"],
            "preview_digest": preview["preview_digest"],
        },
    )
    response.raise_for_status()
    return response.json()
