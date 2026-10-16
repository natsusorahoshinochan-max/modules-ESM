"""Public codec for the module authoring capability hierarchy."""

from __future__ import annotations

from typing import Any

from core.catalog.authoring import AuthoringCapabilityProjection
from datatypes.exact_reference import ExactContractReference


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
                "role": "ordinary_node",
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
