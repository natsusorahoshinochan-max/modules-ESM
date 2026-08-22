"""Catalog scientific projection and public wire ownership tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core.catalog.declarations import AvailabilityResult, CatalogContract
from core.catalog.model import (
    CatalogAvailabilityProjection,
    CatalogContractProjection,
    FrozenCatalog,
)
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from tests.support.catalog import binding_availability, resolved_dependencies
from protein_workbench_public.catalog_codec import encode_catalog_projection


OBSERVED_AT = datetime(2026, 8, 22, 1, 2, 3, tzinfo=timezone.utc)
PROTOCOL_DIGEST = "sha256:" + "0" * 64
BINDING_DIGEST = (
    "sha256:44ac963ee466024270bc2afae912acf65e8434eceecad31f6b87bef1bd7e0e43"
)
PORT_TYPE_DIGEST = (
    "sha256:27efe011e3966d6e6011efb4e5323df6cfef65b9e0b5a20b35335f3345ccacef"
)
CATALOG_DIGEST = (
    "sha256:ae9ff74663ad394f3ce43fd1ba787b5706889d7e2bca7f8995c13d58b3f033e0"
)


def _catalog() -> FrozenCatalog:
    port_type = PortTypeDefinition(
        type_id="fixture.catalog.text",
        version="1.0.0",
        validator=BehaviorReference(
            "fixture.catalog/validate",
            "1.0.0",
            {"accepted_value_kind": "text"},
        ),
        codec=BehaviorReference(
            "fixture.catalog/codec",
            "1.0.0",
            {"canonicalization": "RFC 8785"},
        ),
        content_identity=BehaviorReference(
            "fixture.catalog/content",
            "1.0.0",
            {"digest": "SHA-256"},
        ),
        runtime_validator=lambda value: None,
        runtime_to_wire=lambda value: value,
        runtime_from_wire=lambda value: value,
    )
    binding_descriptor = {
        "schema_namespace": "protein-workbench-contract/v2",
        "contract_kind": "binding",
        "contract_id": "fixture.catalog.direct",
        "contract_version": "1.0.0",
        "node_type": {
            "contract_kind": "node_type",
            "contract_id": "fixture.catalog",
            "contract_version": "1.0.0",
            "contract_digest": "sha256:" + "1" * 64,
        },
    }
    binding = CatalogContract(
        contract_kind="binding",
        contract_id="fixture.catalog.direct",
        contract_version="1.0.0",
        descriptor=binding_descriptor,
        dependencies=resolved_dependencies(binding_descriptor),
    )
    return FrozenCatalog(
        (port_type,),
        contracts=(binding,),
        availability=(binding_availability(binding, OBSERVED_AT),),
        availability_observed_at=OBSERVED_AT,
    )


def test_catalog_projection_exposes_typed_canonical_facts_only() -> None:
    catalog = _catalog()

    projection = catalog.projection()

    assert all(
        type(contract) is CatalogContractProjection
        for contract in projection.contracts
    )
    assert [
        (
            contract.reference.contract_kind,
            contract.reference.contract_id,
            contract.reference.contract_version,
        )
        for contract in projection.contracts
    ] == [
        ("binding", "fixture.catalog.direct", "1.0.0"),
        ("port_type", "fixture.catalog.text", "1.0.0"),
    ]
    assert not hasattr(catalog, "catalog_descriptor")
    assert not hasattr(catalog.contracts[0], "public_contract")
    assert not hasattr(catalog.port_types[0], "public_contract")
    with pytest.raises(TypeError):
        projection.contracts[0].descriptor["contract_id"] = "mutated"


def test_catalog_resolves_exact_typed_binding_availability() -> None:
    catalog = _catalog()
    binding = next(
        contract.reference
        for contract in catalog.projection().contracts
        if contract.reference.contract_kind == "binding"
    )

    observation = catalog.require_availability(binding)

    assert type(observation) is CatalogAvailabilityProjection
    assert observation.binding == binding
    assert observation.observed_at == OBSERVED_AT
    assert observation.result.is_available is True


def test_public_codec_assembles_the_exact_catalog_wire() -> None:
    catalog = _catalog()

    payload = encode_catalog_projection(
        catalog.projection(),
        protocol_digest=PROTOCOL_DIGEST,
    )

    assert catalog.contract_digest == CATALOG_DIGEST
    assert payload == {
        "schema_namespace": "protein-workbench-public/v2",
        "protocol_digest": PROTOCOL_DIGEST,
        "catalog_contract_digest": CATALOG_DIGEST,
        "contracts": [
            {
                "reference": {
                    "contract_kind": "binding",
                    "contract_id": "fixture.catalog.direct",
                    "contract_version": "1.0.0",
                    "contract_digest": BINDING_DIGEST,
                },
                "descriptor": {
                    "schema_namespace": "protein-workbench-contract/v2",
                    "contract_kind": "binding",
                    "contract_id": "fixture.catalog.direct",
                    "contract_version": "1.0.0",
                    "node_type": {
                        "contract_kind": "node_type",
                        "contract_id": "fixture.catalog",
                        "contract_version": "1.0.0",
                        "contract_digest": "sha256:" + "1" * 64,
                    },
                },
            },
            {
                "reference": {
                    "contract_kind": "port_type",
                    "contract_id": "fixture.catalog.text",
                    "contract_version": "1.0.0",
                    "contract_digest": PORT_TYPE_DIGEST,
                },
                "descriptor": {
                    "schema_namespace": "protein-workbench-contract/v2",
                    "contract_kind": "port_type",
                    "contract_id": "fixture.catalog.text",
                    "contract_version": "1.0.0",
                    "validator": {
                        "behavior_id": "fixture.catalog/validate",
                        "behavior_version": "1.0.0",
                        "parameters": {"accepted_value_kind": "text"},
                    },
                    "codec": {
                        "behavior_id": "fixture.catalog/codec",
                        "behavior_version": "1.0.0",
                        "parameters": {"canonicalization": "RFC 8785"},
                    },
                    "content_identity": {
                        "behavior_id": "fixture.catalog/content",
                        "behavior_version": "1.0.0",
                        "parameters": {"digest": "SHA-256"},
                    },
                },
            },
        ],
        "availability_observed_at": "2026-08-22T01:02:03Z",
        "availability": [
            {
                "binding": {
                    "contract_kind": "binding",
                    "contract_id": "fixture.catalog.direct",
                    "contract_version": "1.0.0",
                    "contract_digest": BINDING_DIGEST,
                },
                "observed_at": "2026-08-22T01:02:03Z",
                "available": True,
            }
        ],
    }


def test_public_codec_assembles_unavailable_reason_fields() -> None:
    catalog = _catalog()
    unavailable = replace(
        catalog,
        availability=(
            binding_availability(
                catalog.contracts[0],
                OBSERVED_AT,
                AvailabilityResult.unavailable(
                    "provider_offline",
                    "Provider is offline",
                    retryable=True,
                ),
            ),
        ),
    )

    payload = encode_catalog_projection(
        unavailable.projection(),
        protocol_digest=PROTOCOL_DIGEST,
    )

    assert payload["availability"] == [
        {
            "binding": {
                "contract_kind": "binding",
                "contract_id": "fixture.catalog.direct",
                "contract_version": "1.0.0",
                "contract_digest": BINDING_DIGEST,
            },
            "observed_at": "2026-08-22T01:02:03Z",
            "available": False,
            "reason": {
                "code": "provider_offline",
                "message": "Provider is offline",
                "retryable": True,
            },
        }
    ]
