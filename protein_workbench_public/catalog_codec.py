"""Public protocol codec for the typed Catalog projection."""

from __future__ import annotations

from core.catalog.model import CatalogProjection


def encode_catalog_projection(
    projection: CatalogProjection,
    *,
    protocol_digest: str,
) -> dict[str, object]:
    """Encode a typed Catalog projection for the public protocol."""
    observed_at = (
        projection.availability_observed_at.isoformat()
        .replace("+00:00", "Z")
    )
    contracts = [
        definition.public_contract()
        for definition in projection.port_types
    ] + [contract.public_contract() for contract in projection.contracts]
    contracts.sort(
        key=lambda item: (
            item["reference"]["contract_kind"],
            item["reference"]["contract_id"],
            item["reference"]["contract_version"],
        )
    )
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "protocol_digest": protocol_digest,
        "catalog_contract_digest": projection.catalog_contract_digest,
        "contracts": contracts,
        "availability_observed_at": observed_at,
        "availability": [
            {
                "binding": snapshot.binding.reference(),
                "observed_at": (
                    snapshot.observed_at.isoformat().replace("+00:00", "Z")
                ),
                "available": snapshot.result.is_available,
                **(
                    {}
                    if snapshot.result.is_available
                    else {"reason": snapshot.result.reason()}
                ),
            }
            for snapshot in projection.availability
        ],
    }
