"""Public codecs for authoring hierarchy and Prompt Studio projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.authoring import AuthoringCapabilityProjection
from core.workflow.authoring import ManagedRoleEndpoint
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import thaw_i_json
from modules.prompt_authoring.authoring import (
    PromptApplyResult,
    PromptAuthoringPreview,
    PromptAuthoringSnapshot,
    PromptCompositionProjection,
)
from protein_workbench_public.workflow_codec import encode_workflow_draft


def _reference(reference: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
    }


def encode_authoring_capability_projection(
    projection: AuthoringCapabilityProjection,
    *,
    protocol_digest: str,
) -> dict[str, Any]:
    """Encode the startup-frozen non-scientific authoring projection."""
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "protocol_digest": protocol_digest,
        "capabilities": [
            {
                "capability_id": capability.capability_id,
                "role": "specialized_composition",
                "title": capability.title,
                "summary": capability.summary,
                "category": capability.category,
                "editor_kind": capability.editor_kind,
                "source_kinds": [
                    {
                        "source_kind": source.source_kind,
                        "title": source.title,
                        "accepted_port_types": [
                            _reference(reference)
                            for reference in source.accepted_port_types
                        ],
                    }
                    for source in capability.source_kinds
                ],
                "exposed_inputs": [
                    {
                        "role": endpoint.role,
                        "port_type": _reference(endpoint.port_type),
                    }
                    for endpoint in capability.exposed_inputs
                ],
                "exposed_outputs": [
                    {
                        "role": endpoint.role,
                        "port_type": _reference(endpoint.port_type),
                    }
                    for endpoint in capability.exposed_outputs
                ],
                "managed_node_types": [
                    _reference(reference)
                    for reference in capability.managed_node_types
                ],
            }
            for capability in projection.capabilities
        ],
        "node_roles": [
            {
                "node_type": _reference(role.node_type),
                "role": role.role,
                **(
                    {}
                    if role.capability_id is None
                    else {"capability_id": role.capability_id}
                ),
            }
            for role in projection.node_roles
        ],
    }


def _endpoint(endpoint: ManagedRoleEndpoint) -> dict[str, str]:
    return endpoint.canonical_projection()


def encode_composition_projection(
    composition: PromptCompositionProjection,
) -> dict[str, Any]:
    return {
        "composition_id": composition.composition_id,
        "capability_id": composition.capability_id,
        "managed_node_ids": list(composition.managed_node_ids),
        "exposed_inputs": [
            _endpoint(endpoint) for endpoint in composition.exposed_inputs
        ],
        "exposed_outputs": [
            _endpoint(endpoint) for endpoint in composition.exposed_outputs
        ],
    }


def encode_prompt_snapshot(
    snapshot: PromptAuthoringSnapshot,
) -> dict[str, Any]:
    return {
        "document": thaw_i_json(snapshot.document),
        "residues": [thaw_i_json(item) for item in snapshot.residues],
        "tracks": {
            name: [thaw_i_json(item) for item in values]
            for name, values in snapshot.tracks.items()
        },
        "function_annotations": [
            thaw_i_json(item) for item in snapshot.function_annotations
        ],
        "source": thaw_i_json(snapshot.source),
    }


def encode_prompt_preview(
    preview: PromptAuthoringPreview,
) -> dict[str, Any]:
    return {
        "normalized_document": thaw_i_json(preview.normalized_document),
        "preview_digest": preview.preview_digest,
        "residues": [thaw_i_json(item) for item in preview.residues],
        "tracks": {
            name: [thaw_i_json(item) for item in values]
            for name, values in preview.tracks.items()
        },
        "function_annotations": [
            thaw_i_json(item) for item in preview.function_annotations
        ],
        "changes": [thaw_i_json(item) for item in preview.changes],
        "random_selections": [
            thaw_i_json(item) for item in preview.random_selections
        ],
        "source_merges": [
            thaw_i_json(item) for item in preview.source_merges
        ],
        "diagnostics": [
            diagnostic.projection() for diagnostic in preview.diagnostics
        ],
        "summary": thaw_i_json(preview.summary),
    }


def encode_prompt_apply_result(result: PromptApplyResult) -> dict[str, Any]:
    return {
        "draft": encode_workflow_draft(result.draft),
        "composition": (
            None
            if result.composition is None
            else encode_composition_projection(result.composition)
        ),
    }
