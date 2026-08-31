"""Public Prompt authoring helpers for acceptance workflows."""

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


def save_ordinary_graph_on_prompt_draft(
    client: Any,
    project_id: str,
    applied_compositions: tuple[Mapping[str, Any], ...],
    fixture_workflow: Mapping[str, Any],
    *,
    fixture_composition_ids: tuple[str, ...],
    output_connections: tuple[
        tuple[Mapping[str, Any], str, str, str], ...
    ],
) -> dict[str, Any]:
    draft = applied_compositions[-1]["draft"]
    materialized = draft["workflow"]
    fixture_managed_node_ids = {
        node["node_id"]
        for node in fixture_workflow["nodes"]
        if any(
            node["node_id"].startswith(f"{composition_id}.")
            for composition_id in fixture_composition_ids
        )
    }
    external_edges = []
    for composition, role, target_node_id, target_port in output_connections:
        endpoint = next(
            endpoint
            for endpoint in composition["exposed_outputs"]
            if endpoint["role"] == role
        )
        external_edges.append(
            {
                "source_node_id": endpoint["node_id"],
                "source_port": endpoint["port_name"],
                "target_node_id": target_node_id,
                "target_port": target_port,
            }
        )
    workflow = {
        "schema_version": materialized["schema_version"],
        "workflow_id": project_id,
        "nodes": [
            *materialized["nodes"],
            *(
                node
                for node in fixture_workflow["nodes"]
                if node["node_id"] not in fixture_managed_node_ids
            ),
        ],
        "edges": [
            *materialized["edges"],
            *(
                edge
                for edge in fixture_workflow["edges"]
                if edge["source_node_id"] not in fixture_managed_node_ids
                and edge["target_node_id"] not in fixture_managed_node_ids
            ),
            *external_edges,
        ],
        "observation_selectors": fixture_workflow[
            "observation_selectors"
        ],
        "selection_objectives": fixture_workflow[
            "selection_objectives"
        ],
    }
    response = client.put(
        f"/api/v2/projects/{project_id}/workflow/draft",
        json={"workflow": workflow},
    )
    response.raise_for_status()
    return workflow
