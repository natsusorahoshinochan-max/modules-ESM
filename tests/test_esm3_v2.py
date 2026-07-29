"""Public v2 contracts for the cohesive remote ESM-3 package."""

from __future__ import annotations

import math

import pytest

from core import build_discovered_frozen_catalog, discover_module_packages
from datatypes import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueTrack,
)


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


def test_adapter_preserves_every_representable_prompt_track_and_symbol() -> None:
    from modules.esm3.adapter import protein_prompt_to_provider

    layout = ResidueLayout(
        chain_id="A",
        length=8,
        residue_ids=[f"A:{index}" for index in range(1, 9)],
    )
    prompt = ProteinPrompt(
        target_layout=layout,
        sequence_track=ResidueTrack(
            ["A", "B", "Z", "U", "O", "X", None, "G"],
            None,
        ),
        structure_track=ResidueTrack(
            [
                {
                    "N": (1.0, 2.0, 3.0),
                    "CA": (4.0, 5.0, 6.0),
                    "C": (7.0, 8.0, 9.0),
                    "O": (10.0, 11.0, 12.0),
                },
                *([None] * 7),
            ],
            None,
        ),
        structure_visibility_track=ResidueTrack(
            [True, False, True, True, True, True, True, True],
            None,
        ),
        secondary_structure_track=ResidueTrack(
            ["G", "H", "I", "T", "E", "B", "S", "-"],
            None,
        ),
        sasa_track=ResidueTrack(
            [0.0, 0.8, 4.0, None, 16.4, 32.9, 70.9, 151.4],
            None,
        ),
        function_annotations=FunctionAnnotations(
            [
                FunctionAnnotation(
                    label="binding site",
                    start=2,
                    end=5,
                    chain_id="A",
                    start_residue_id="A:2",
                    end_residue_id="A:5",
                    overlap_policy="reject",
                )
            ]
        ),
    )

    provider = protein_prompt_to_provider(prompt)

    assert provider.sequence == "ABZUOX_G"
    assert provider.secondary_structure == "GHITEBSC"
    assert provider.sasa == [0.0, 0.8, 4.0, None, 16.4, 32.9, 70.9, 151.4]
    assert provider.function_annotations[0].label == "binding site"
    assert provider.function_annotations[0].start == 2
    assert provider.function_annotations[0].end == 5
    assert tuple(provider.coordinates.shape) == (8, 37, 3)
    assert provider.coordinates[0, 0].tolist() == [1.0, 2.0, 3.0]
    assert provider.coordinates[0, 1].tolist() == [4.0, 5.0, 6.0]
    assert math.isnan(float(provider.coordinates[1, 1, 0]))

    prompt.sequence_track.values[0] = "J"
    with pytest.raises(ValueError, match="cannot represent sequence symbol 'J'"):
        protein_prompt_to_provider(prompt)
