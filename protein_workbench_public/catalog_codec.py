"""Public protocol codec for the typed Catalog projection."""

from __future__ import annotations

from typing import cast

from core.catalog.model import CatalogContractProjection, CatalogProjection
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import thaw_i_json


def _encode_reference(
    reference: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


def _encode_contract(
    contract: CatalogContractProjection,
) -> dict[str, object]:
    return {
        "reference": _encode_reference(contract.reference),
        "descriptor": cast(dict[str, object], thaw_i_json(contract.descriptor)),
    }


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
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "protocol_digest": protocol_digest,
        "catalog_contract_digest": projection.catalog_contract_digest,
        "contracts": [
            _encode_contract(contract)
            for contract in projection.contracts
        ],
        "availability_observed_at": observed_at,
        "availability": [
            {
                "binding": _encode_reference(snapshot.binding),
                "observed_at": (
                    snapshot.observed_at.isoformat().replace("+00:00", "Z")
                ),
                "available": snapshot.result.is_available,
                **(
                    {}
                    if snapshot.result.is_available
                    else {
                        "reason": {
                            "code": snapshot.result.code,
                            "message": snapshot.result.message,
                            "retryable": snapshot.result.retryable,
                        }
                    }
                ),
            }
            for snapshot in projection.availability
        ],
    }
