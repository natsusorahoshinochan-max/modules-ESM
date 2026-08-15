"""Focused contracts for the canonical active-Port version cascade."""

from __future__ import annotations

from contextlib import nullcontext

from core import build_frozen_catalog
from modules.structure_transform.implementation import resolve_residue_axis
from tests.fixtures.scientific_operation import build_operation, operation_call
from tests.fixtures.structure_transform_sources.package import _FIXTURES
from datatypes import ProteinStructure, ResidueLayout


_PROMPT_NODE_VERSIONS = {
    "add_function_annotation": "3.0.0",
    "assemble_protein_prompt": "3.0.0",
    "build_residue_layout": "3.0.0",
    "edit_residue_layout": "3.0.0",
    "insert_masked_residues": "3.0.0",
    "map_residue_track": "3.0.0",
    "override_protein_prompt_track": "3.0.0",
    "override_residue_track": "3.0.0",
    "prompt_from_structure": "5.0.0",
    "random_insert_masked": "3.0.0",
    "random_mask": "3.0.0",
    "update_prompt_sequence": "3.0.0",
}


def _cascade_catalog():
    from modules.esm3.package import MODULE_PACKAGE as esm3_package
    from modules.folding.package import MODULE_PACKAGE as folding_package
    from modules.prompt_authoring.package import MODULE_PACKAGE as prompt_package
    from modules.proteinmpnn.package import MODULE_PACKAGE as proteinmpnn_package
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as structure_prediction_package,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as structure_transform_package,
    )

    return build_frozen_catalog(
        (
            structure_transform_package,
            structure_prediction_package,
            prompt_package,
            esm3_package,
            folding_package,
            proteinmpnn_package,
        )
    )


def test_prompt_ports_nodes_and_bindings_use_only_the_active_generation() -> None:
    catalog = _cascade_catalog()

    for type_id in (
        "prompt_authoring.track.sequence",
        "prompt_authoring.track.structure",
        "prompt_authoring.track.visibility",
        "prompt_authoring.track.secondary_structure",
        "prompt_authoring.track.sasa",
    ):
        port_type = catalog.require_port_type(type_id, "3.0.0")
        assert port_type.codec.parameters["embedded_layout_contract"] == (
            "residue.layout@3.0.0"
        )
        assert catalog.get_contract("port_type", type_id, "2.1.0") is None

    prompt = catalog.require_port_type("protein.prompt", "3.0.0")
    assert prompt.codec.parameters["embedded_contracts"] == {
        "function_annotations": "function.annotations@3.0.0",
        "target_layout": "residue.layout@3.0.0",
        "tracks": "residue.track@2.1.0",
    }
    assert catalog.get_contract("port_type", "protein.prompt", "2.1.0") is None
    assert catalog.require_port_type("function.annotations", "3.0.0")
    assert catalog.get_contract(
        "port_type", "function.annotations", "2.1.0"
    ) is None

    for operation, version in _PROMPT_NODE_VERSIONS.items():
        node_id = f"prompt_authoring.{operation}"
        binding_id = f"{node_id}.direct"
        catalog.require_contract("node_type", node_id, version)
        binding = catalog.require_contract("binding", binding_id, version)
        expected_method_version = (
            "3.0.0" if operation == "prompt_from_structure" else "2.1.0"
        )
        assert binding.descriptor["method"]["contract_version"] == (
            expected_method_version
        )
        legacy_version = "4.0.0" if version == "5.0.0" else "2.1.0"
        assert catalog.get_contract("node_type", node_id, legacy_version) is None
        assert catalog.get_contract("binding", binding_id, legacy_version) is None

    catalog.require_contract(
        "method",
        "prompt_authoring.prompt_from_structure.method",
        "3.0.0",
    )
    assert catalog.get_contract(
        "method",
        "prompt_authoring.prompt_from_structure.method",
        "2.1.0",
    ) is None


def test_prompt_from_structure_consumes_the_resolved_axis_without_reparsing() -> None:
    from modules.prompt_authoring.package import MODULE_PACKAGE as prompt_package
    from modules.structure_transform.package import (
        MODULE_PACKAGE as structure_transform_package,
    )

    axis = resolve_residue_axis(
        ProteinStructure(_FIXTURES["mse_ligand_water"]())
    )
    catalog = build_frozen_catalog(
        (structure_transform_package, prompt_package)
    )

    class Resources:
        @staticmethod
        def engine_invocation(**kwargs):
            del kwargs
            return nullcontext()

    outputs = build_operation(
        catalog,
        "prompt_authoring.prompt_from_structure.direct",
        Resources(),
        binding_version="5.0.0",
    ).execute(
        operation_call(
            catalog=catalog,
            binding_id="prompt_authoring.prompt_from_structure.direct",
            binding_version="5.0.0",
            inputs={"residue_axis": axis},
        )
    )

    assert outputs["layout"] == ResidueLayout(
        "A", 3, ("A:1", "A:2", "A:3")
    )
    prompt = outputs["protein_prompt"]
    assert prompt.sequence_track.values == ("A", "M", "G")
    assert prompt.structure_track.values[1]["SD"] == (11.0, 2.0, 3.0)
    assert prompt.structure_visibility_track.values == (True, True, True)
    assert all(
        disposition.component_id not in {"LIG", "HOH"}
        or disposition.disposition == "excluded"
        for disposition in axis.component_dispositions
    )


def test_esm3_nodes_bindings_cascade_without_method_or_port_aliases() -> None:
    catalog = _cascade_catalog()

    representation = catalog.require_contract(
        "node_type", "esm3.represent_sequence", "5.0.0"
    )
    assert representation.descriptor["inputs"][0]["port_type"][
        "contract_version"
    ] == "3.0.0"
    assert representation.descriptor["outputs"][0]["port_type"][
        "contract_version"
    ] == "4.0.0"
    representation_binding = catalog.require_contract(
        "binding",
        "esm3.represent_sequence.biohub_esmc_600m_2024_12",
        "5.0.0",
    )
    assert representation_binding.descriptor["method"][
        "contract_version"
    ] == "3.0.0"
    assert catalog.require_port_type(
        "esm3.esmc_sequence_representation", "4.0.0"
    )

    routes = ("biohub_medium", "biohub_open", "local_open")
    for operation in (
        "generate_sequence",
        "generate_structure",
        "generate_paired",
    ):
        node_id = f"esm3.{operation}"
        node = catalog.require_contract("node_type", node_id, "7.0.0")
        assert node.descriptor["inputs"][0]["port_type"] == {
            "contract_kind": "port_type",
            "contract_id": "protein.prompt",
            "contract_version": "3.0.0",
            "contract_digest": node.descriptor["inputs"][0]["port_type"][
                "contract_digest"
            ],
        }
        for output in node.descriptor["outputs"]:
            output_port = output["port_type"]
            if output_port["contract_id"] in {
                "candidate.collection",
                "candidate.pairing",
            }:
                assert output_port["contract_version"] == "3.0.0"
            if output_port["contract_id"] == (
                "structure_prediction.confidence_facts"
            ):
                assert output_port["contract_version"] == "1.0.0"
            assert output_port["contract_id"] != "score.collection"
        for route in routes:
            binding = catalog.require_contract(
                "binding", f"{node_id}.{route}", "7.0.0"
            )
            assert binding.descriptor["method"]["contract_version"] == "5.0.0"
            assert binding.descriptor["produced_observations"] == ()
        assert catalog.get_contract("node_type", node_id, "5.0.0") is None


def test_proteinmpnn_cascade_uses_exact_axis_and_score_generations() -> None:
    catalog = _cascade_catalog()

    constraints = catalog.require_port_type("proteinmpnn.constraints", "4.0.0")
    assert constraints.codec.parameters["embedded_layout_contract"] == (
        "residue.layout@3.0.0"
    )
    assert catalog.get_contract(
        "port_type", "proteinmpnn.constraints", "3.0.0"
    ) is None

    expected = {
        "constraints": ("4.0.0", "3.0.0", "3.0.0"),
        "random_fixed_positions": ("4.0.0", "3.0.0", "3.0.0"),
        "design": ("9.0.0", "5.0.0", "8.0.0"),
        "score": ("6.0.0", "5.0.0", "5.0.0"),
    }
    for operation, (
        contract_version,
        method_version,
        legacy_version,
    ) in expected.items():
        node_id = f"proteinmpnn.{operation}"
        catalog.require_contract("node_type", node_id, contract_version)
        binding = catalog.require_contract(
            "binding", f"{node_id}.local", contract_version
        )
        assert binding.descriptor["method"][
            "contract_version"
        ] == method_version
        assert catalog.get_contract("node_type", node_id, legacy_version) is None
        assert catalog.get_contract(
            "binding", f"{node_id}.local", legacy_version
        ) is None

    for operation in ("constraints", "random_fixed_positions"):
        node = catalog.require_contract(
            "node_type", f"proteinmpnn.{operation}", "4.0.0"
        )
        assert all(
            port["port_type"]["contract_id"] != "candidate.collection"
            for port in (*node.descriptor["inputs"], *node.descriptor["outputs"])
        )

    design = catalog.require_contract(
        "node_type", "proteinmpnn.design", "9.0.0"
    )
    assert {
        port["name"]: (
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in design.descriptor["inputs"]
    }["structure_residue_axes"] == (
        "structure_transform.candidate_resolved_residue_axis_associations",
        "5.0.0",
    )
    score = catalog.require_contract(
        "node_type", "proteinmpnn.score", "6.0.0"
    )
    assert score.descriptor["outputs"][0]["port_type"]["contract_id"] == (
        "score.collection"
    )
    assert score.descriptor["outputs"][0]["port_type"]["contract_version"] == (
        "4.0.0"
    )


def test_folding_and_confidence_materialization_use_fact_then_score_generations(
) -> None:
    catalog = _cascade_catalog()

    fold = catalog.require_contract("node_type", "folding.fold", "6.0.0")
    assert {
        output["name"]: (
            output["port_type"]["contract_id"],
            output["port_type"]["contract_version"],
        )
        for output in fold.descriptor["outputs"]
    } == {
        "structure_candidates": ("candidate.collection", "3.0.0"),
        "confidence_facts": (
            "structure_prediction.confidence_facts",
            "1.0.0",
        ),
    }
    for binding_id, binding_version in (
        ("folding.fold.esmfold2_remote", "7.0.0"),
        ("folding.fold.esmfold2_local", "8.0.0"),
        ("folding.fold.simplefold_local", "6.0.0"),
    ):
        binding = catalog.require_contract(
            "binding",
            binding_id,
            binding_version,
        )
        assert binding.descriptor["method"]["contract_version"] == (
            "6.0.0"
            if binding_id == "folding.fold.esmfold2_local"
            else "4.0.0"
        )
        assert binding.descriptor["produced_observations"] == ()

    confidence = catalog.require_contract(
        "node_type", "folding.simplefold_confidence", "4.0.0"
    )
    assert confidence.descriptor["outputs"][0]["port_type"][
        "contract_version"
    ] == "4.0.0"

    materializer = catalog.require_contract(
        "node_type",
        "structure_prediction.materialize_confidence",
        "1.0.0",
    )
    assert {
        port["name"]: (
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in materializer.descriptor["inputs"]
    } == {
        "structure_candidates": ("candidate.collection", "3.0.0"),
        "confidence_facts": (
            "structure_prediction.confidence_facts",
            "1.0.0",
        ),
    }
    assert materializer.descriptor["outputs"][0]["port_type"] == {
        "contract_kind": "port_type",
        "contract_id": "score.collection",
        "contract_version": "4.0.0",
        "contract_digest": materializer.descriptor["outputs"][0]["port_type"][
            "contract_digest"
        ],
    }
    binding = catalog.require_contract(
        "binding",
        "structure_prediction.materialize_confidence.direct",
        "1.0.0",
    )
    assert binding.descriptor["method"]["contract_version"] == "1.0.0"
    assert {
        observation["method_port"]
        for observation in binding.descriptor["produced_observations"]
    } == {"confidence_facts"}
