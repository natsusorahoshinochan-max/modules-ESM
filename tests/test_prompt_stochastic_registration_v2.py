"""Registration contracts for reproducible stochastic prompt authoring."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core import (
    CatalogBuildError,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
)
from modules.prompt_authoring.package import MODULE_PACKAGE
from tests.fixtures.prompt_authoring_v2 import VERSION


def test_stochastic_prompt_authoring_registers_two_exact_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }
    registration = registrations["prompt_authoring"]
    assert {
        resource.resource for resource in registration.node_definitions
    } >= {
        "definitions/random_mask.yaml",
        "definitions/random_insert_masked.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    for operation in ("random_mask", "random_insert_masked"):
        node = catalog.require_contract(
            "node_type",
            f"prompt_authoring.{operation}",
            VERSION,
        )
        binding = catalog.require_contract(
            "binding",
            f"prompt_authoring.{operation}.direct",
            VERSION,
        )
        assert node.descriptor["category"] == "prompt_authoring"
        assert binding.descriptor["deterministic"] is True
        assert binding.descriptor["cacheable"] is True
        assert tuple(
            binding.descriptor["effective_randomness_parameters"]
        )


def test_randomness_declaration_cannot_name_an_undeclared_parameter() -> None:
    broken_bindings = tuple(
        (
            replace(
                binding,
                effective_randomness_parameters=("missing_randomness",),
            )
            if binding.binding_id == "prompt_authoring.random_mask.direct"
            else binding
        )
        for binding in MODULE_PACKAGE.bindings
    )

    with pytest.raises(CatalogBuildError, match="undeclared parameters"):
        build_frozen_catalog(
            (replace(MODULE_PACKAGE, bindings=broken_bindings),)
        )


def test_randomness_declaration_has_one_unambiguous_parameter_scope() -> None:
    broken_bindings = tuple(
        (
            replace(
                binding,
                binding_parameters={
                    "effective_seed": {
                        "parameter_scope": "scientific",
                        "scientific_meaning": "Ambiguous duplicate seed.",
                        "required": True,
                        "value_contract": {"type": "integer"},
                    },
                },
            )
            if binding.binding_id == "prompt_authoring.random_mask.direct"
            else binding
        )
        for binding in MODULE_PACKAGE.bindings
    )

    with pytest.raises(CatalogBuildError, match="exactly one parameter scope"):
        build_frozen_catalog(
            (replace(MODULE_PACKAGE, bindings=broken_bindings),)
        )


def test_randomness_declaration_is_bounded_like_the_public_contract() -> None:
    binding = next(
        binding
        for binding in MODULE_PACKAGE.bindings
        if binding.binding_id == "prompt_authoring.random_mask.direct"
    )

    with pytest.raises(CatalogBuildError, match="at most 256"):
        replace(
            binding,
            effective_randomness_parameters=tuple(
                f"randomness_{index}" for index in range(257)
            ),
        )
