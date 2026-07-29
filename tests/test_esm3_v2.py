"""Public v2 contracts for the cohesive remote ESM-3 package."""

from __future__ import annotations

from core import build_discovered_frozen_catalog, discover_module_packages


def test_remote_esm3_is_one_package_with_three_fixed_generation_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["esm3"]
    assert registration.package_module == "modules.esm3"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/generate_sequence.yaml",
        "definitions/generate_structure.yaml",
        "definitions/generate_paired.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "esm3" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("esm3.generate_sequence", "2.0.0"),
        ("esm3.generate_structure", "2.0.0"),
        ("esm3.generate_paired", "2.0.0"),
    }

    for operation in ("generate_sequence", "generate_structure", "generate_paired"):
        node = catalog.require_contract(
            "node_type",
            f"esm3.{operation}",
            "2.0.0",
        )
        binding = catalog.require_contract(
            "binding",
            f"esm3.{operation}.biohub_medium",
            "2.0.0",
        )
        assert "model_name" not in node.descriptor["node_parameters"]
        assert "model_name" not in binding.descriptor["binding_parameters"]
        assert binding.descriptor["execution_route"] == "adapter"
        assert binding.descriptor["method"]["contract_id"] == (
            f"esm3.{operation}.esm3_medium_2024_08"
        )
        assert binding.descriptor["implementation_identity"]["model"] == (
            "esm3-medium-2024-08"
        )
        assert binding.descriptor["availability_declaration"][
            "prerequisites"
        ]["provider_sdk"]["source_revision"] == (
            "917af90b624535eed1e072d343c717e3ec11fef4"
        )
        assert binding.descriptor["readiness_declaration"][
            "prerequisites"
        ] == {
            "credential": {
                "source": "trusted_environment_configuration",
            },
            "endpoint": {
                "endpoint_id": "biohub",
                "source": "trusted_environment_configuration",
            },
            "provider_sdk": {
                "name": "esm",
                "source_revision": (
                    "917af90b624535eed1e072d343c717e3ec11fef4"
                ),
            },
        }

