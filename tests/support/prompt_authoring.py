"""Public Prompt authoring helpers for current source-bound acceptance workflows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def initialize_prompt_authoring_draft(
    client: Any,
    project_id: str,
) -> None:
    response = client.put(
        f"/api/v2/projects/{project_id}/workflow/draft",
        json={
            "workflow": {
                "schema_version": "2.1.0",
                "workflow_id": project_id,
                "nodes": [],
                "edges": [],
                "observation_selectors": [],
                "selection_objectives": [],
            }
        },
    )
    response.raise_for_status()


def open_pdb_prompt_document(
    client: Any,
    project_id: str,
    project_input_ref: str,
    *,
    chain_ids: list[str],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:open",
        json={
            "mode": "create",
            "source": {
                "kind": "pdb",
                "project_input_ref": project_input_ref,
                "chain_ids": chain_ids,
            },
        },
    )
    response.raise_for_status()
    return response.json()


def open_blank_prompt_document(
    client: Any,
    project_id: str,
    *,
    chains: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:open",
        json={
            "mode": "create",
            "source": {"kind": "blank", "chains": chains},
        },
    )
    response.raise_for_status()
    return response.json()


def preview_prompt_document(
    client: Any,
    project_id: str,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:preview",
        json={"document": document},
    )
    response.raise_for_status()
    return response.json()


def apply_prompt_document(
    client: Any,
    project_id: str,
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/prompt-authoring:apply",
        json={
            "intent": "create",
            "normalized_document": preview["normalized_document"],
            "preview_digest": preview["preview_digest"],
        },
    )
    response.raise_for_status()
    return response.json()


def composition_output(
    composition: Mapping[str, Any],
    role: str,
) -> Mapping[str, str]:
    return next(
        endpoint
        for endpoint in composition["exposed_outputs"]
        if endpoint["role"] == role
    )


def replace_prompt_managed_subgraph(
    workflow: Mapping[str, Any],
    materialized_draft: Mapping[str, Any],
    superseded_managed_node_ids: set[str],
    output_replacements: Mapping[tuple[str, str], Mapping[str, str]],
) -> dict[str, Any]:
    nodes = [
        node
        for node in workflow["nodes"]
        if node["node_id"] not in superseded_managed_node_ids
    ]
    nodes.extend(materialized_draft["nodes"])
    edges: list[Mapping[str, Any]] = []
    for edge in workflow["edges"]:
        source_managed = (
            edge["source_node_id"] in superseded_managed_node_ids
        )
        target_managed = (
            edge["target_node_id"] in superseded_managed_node_ids
        )
        if source_managed and not target_managed:
            endpoint = output_replacements[
                (edge["source_node_id"], edge["source_port"])
            ]
            edges.append(
                {
                    **edge,
                    "source_node_id": endpoint["node_id"],
                    "source_port": endpoint["port_name"],
                }
            )
        elif not source_managed and not target_managed:
            edges.append(edge)
    edges.extend(materialized_draft["edges"])
    return {**workflow, "nodes": nodes, "edges": edges}
