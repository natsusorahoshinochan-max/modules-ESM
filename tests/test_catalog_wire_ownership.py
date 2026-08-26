"""Catalog scientific projection and public wire ownership tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core.catalog.declarations import AvailabilityResult
from core.catalog.model import (
    CatalogAvailabilityProjection,
    CatalogContract,
    CatalogContractProjection,
    FrozenCatalog,
    result_identity_contract,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.i_json import thaw_i_json
from tests.support.catalog import binding_availability, resolved_dependencies
from protein_workbench_public.catalog_codec import encode_catalog_projection


OBSERVED_AT = datetime(2026, 8, 22, 1, 2, 3, tzinfo=timezone.utc)
PROTOCOL_DIGEST = "sha256:" + "0" * 64


def _catalog() -> FrozenCatalog:
    port_type = PortTypeDefinition(
        type_id="fixture.catalog.text",
        validator=BehaviorReference(
            "fixture.catalog/validate",
            {"accepted_value_kind": "text"},
        ),
        codec=BehaviorReference(
            "fixture.catalog/codec",
            {"canonicalization": "RFC 8785"},
        ),
        content_identity=BehaviorReference(
            "fixture.catalog/content",
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
        "node_type": {
            "contract_kind": "node_type",
            "contract_id": "fixture.catalog",
        },
    }
    binding = CatalogContract(
        contract_kind="binding",
        contract_id="fixture.catalog.direct",
        descriptor=binding_descriptor,
        dependencies=resolved_dependencies(binding_descriptor),
        definition=object(),  # type: ignore[arg-type]
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
        )
        for contract in projection.contracts
    ] == [
        ("binding", "fixture.catalog.direct"),
        ("port_type", "fixture.catalog.text"),
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


def test_result_contract_projection_has_fixed_node_and_port_identities() -> None:
    node_descriptor = {
        "schema_namespace": "protein-workbench-contract/v2",
        "contract_kind": "node_type",
        "contract_id": "fixture.identity.node",
        "title": "Presentation title",
        "summary": "Presentation summary",
        "category": "presentation-category",
        "inputs": [
            {
                "name": "value",
                "port_type": {
                    "contract_kind": "port_type",
                    "contract_id": "fixture.catalog.text",
                },
                "required": True,
                "multiplicity": "one",
                "scientific_meaning": "fixture value",
            }
        ],
        "outputs": [],
        "parameter_groups": [],
        "node_parameters": {},
    }
    node = CatalogContract(
        contract_kind="node_type",
        contract_id="fixture.identity.node",
        descriptor=node_descriptor,
        dependencies=resolved_dependencies(node_descriptor),
        definition=object(),  # type: ignore[arg-type]
    )
    node_projection = thaw_i_json(result_identity_contract(node))
    port_projection = result_identity_contract(_catalog().port_types[0])

    assert not {
        "title",
        "summary",
        "category",
        "parameter_groups",
        "schema_namespace",
        "contract_kind",
        "contract_id",
    } & node_projection["descriptor"].keys()
    assert node_projection["descriptor"]["inputs"][0]["port_type"] == {
        "contract_kind": "port_type",
        "contract_id": "fixture.catalog.text",
    }
    assert port_projection["contract_kind"] == "port_type"
    assert port_projection["contract_id"] == "fixture.catalog.text"
    assert "contract_id" not in port_projection["descriptor"]


def test_public_codec_assembles_the_exact_catalog_wire() -> None:
    catalog = _catalog()

    payload = encode_catalog_projection(
        catalog.projection(),
        protocol_digest=PROTOCOL_DIGEST,
    )

    assert payload == {
        "schema_namespace": "protein-workbench-public/v2",
        "protocol_digest": PROTOCOL_DIGEST,
        "contracts": [
            {
                "reference": {
                    "contract_kind": "binding",
                    "contract_id": "fixture.catalog.direct",
                },
                "descriptor": {
                    "schema_namespace": "protein-workbench-contract/v2",
                    "contract_kind": "binding",
                    "contract_id": "fixture.catalog.direct",
                    "node_type": {
                        "contract_kind": "node_type",
                        "contract_id": "fixture.catalog",
                    },
                },
            },
            {
                "reference": {
                    "contract_kind": "port_type",
                    "contract_id": "fixture.catalog.text",
                },
                "descriptor": {
                    "schema_namespace": "protein-workbench-contract/v2",
                    "contract_kind": "port_type",
                    "contract_id": "fixture.catalog.text",
                    "validator": {
                        "behavior_id": "fixture.catalog/validate",
                        "parameters": {"accepted_value_kind": "text"},
                    },
                    "codec": {
                        "behavior_id": "fixture.catalog/codec",
                        "parameters": {"canonicalization": "RFC 8785"},
                    },
                    "content_identity": {
                        "behavior_id": "fixture.catalog/content",
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
