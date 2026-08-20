"""Focused contracts for the canonical active-Port version cascade."""

from __future__ import annotations

from contextlib import nullcontext

from core import build_discovered_frozen_catalog, build_frozen_catalog
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

_CANDIDATE_PROJECTION_NODE_GENERATIONS = {
    "collection_ops.concat_candidates": ("4.0.0", "3.0.0"),
    "collection_ops.concat_pairings": ("4.0.0", "3.0.0"),
    "collection_ops.intersect_candidates": ("4.0.0", "3.0.0"),
    "collection_ops.merge_scores": ("5.0.0", "4.0.0"),
    "collection_ops.pair_siblings_by_parent": ("4.0.0", "3.0.0"),
    "collection_ops.rebind_candidate_pairing": ("4.0.0", "3.0.0"),
    "collection_ops.select_children_by_parent": ("4.0.0", "3.0.0"),
    "collection_ops.take_candidates": ("4.0.0", "3.0.0"),
    "esm3.generate_paired": ("8.0.0", "7.0.0"),
    "esm3.generate_sequence": ("8.0.0", "7.0.0"),
    "esm3.generate_structure": ("8.0.0", "7.0.0"),
    "folding.fold": ("7.0.0", "6.0.0"),
    "folding.simplefold_confidence": ("5.0.0", "4.0.0"),
    "protein_io.export_structure": ("6.0.0", "5.0.0"),
    "protein_io.import_sequence": ("6.0.0", "5.0.0"),
    "protein_io.import_structure": ("6.0.0", "5.0.0"),
    "proteinmpnn.design": ("10.0.0", "9.0.0"),
    "proteinmpnn.score": ("7.0.0", "6.0.0"),
    "selection.diversity": ("5.0.0", "4.0.0"),
    "selection.filter": ("5.0.0", "4.0.0"),
    "selection.pareto": ("5.0.0", "4.0.0"),
    "selection.sort": ("5.0.0", "4.0.0"),
    "selection.top_k": ("5.0.0", "4.0.0"),
    "selection.weighted_rank": ("5.0.0", "4.0.0"),
    "solubility.score_sequence": ("5.0.0", "4.0.0"),
    "structure_annotation.dssp_compute": ("7.0.0", "6.0.0"),
    "structure_annotation.expected_secondary_structure_from_prompt": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_annotation.secondary_structure_agreement": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_comparison.align_counterparts": ("5.0.0", "4.0.0"),
    "structure_comparison.align_fixed_reference": ("5.0.0", "4.0.0"),
    "structure_comparison.align_single": ("5.0.0", "4.0.0"),
    "structure_comparison.classify_three_way_consistency": (
        "3.0.0",
        "2.0.0",
    ),
    "structure_comparison.evaluate_inserted_loop": ("2.0.0", "1.0.0"),
    "structure_comparison.rmsd_counterparts": ("6.0.0", "5.0.0"),
    "structure_comparison.rmsd_fixed_reference": ("6.0.0", "5.0.0"),
    "structure_comparison.tm_score_counterparts": ("6.0.0", "5.0.0"),
    "structure_comparison.tm_score_fixed_reference": ("6.0.0", "5.0.0"),
    "structure_prediction.materialize_confidence": ("2.0.0", "1.0.0"),
    "structure_transform.extract_sequence_candidates": ("4.0.0", "3.0.0"),
    "structure_transform.materialize_candidate_normalizations": (
        "2.0.0",
        "1.0.0",
    ),
    "structure_transform.normalize_csh_parent_span_candidates": (
        "2.0.0",
        "1.0.0",
    ),
    "structure_transform.project_single_residue_axis": ("2.0.0", "1.0.0"),
    "structure_transform.resolve_candidate_residue_axes": ("6.0.0", "5.0.0"),
    "structure_transform.select_candidate_chains": ("4.0.0", "3.0.0"),
}

_CANDIDATE_PROJECTION_METHOD_GENERATIONS = {
    "structure_comparison.inserted_loop.exact_evidence_gate": (
        "2.0.0",
        "1.0.0",
    ),
    "structure_comparison.rmsd.from_alignment_evidence.method": (
        "4.0.0",
        "3.0.0",
    ),
    "structure_comparison.tm_score.reference_axis_normalized.method": (
        "4.0.0",
        "3.0.0",
    ),
    "structure_prediction.materialize_confidence.exact_reference_join": (
        "2.0.0",
        "1.0.0",
    ),
}

_CANDIDATE_PROJECTION_BINDING_GENERATIONS = {
    "collection_ops.concat_candidates.direct": ("4.0.0", "3.0.0"),
    "collection_ops.concat_pairings.direct": ("4.0.0", "3.0.0"),
    "collection_ops.intersect_candidates.direct": ("4.0.0", "3.0.0"),
    "collection_ops.merge_scores.direct": ("5.0.0", "4.0.0"),
    "collection_ops.pair_siblings_by_parent.direct": ("4.0.0", "3.0.0"),
    "collection_ops.rebind_candidate_pairing.direct": ("4.0.0", "3.0.0"),
    "collection_ops.select_children_by_parent.direct": ("4.0.0", "3.0.0"),
    "collection_ops.take_candidates.direct": ("4.0.0", "3.0.0"),
    "esm3.generate_paired.biohub_medium": ("8.0.0", "7.0.0"),
    "esm3.generate_paired.biohub_open": ("8.0.0", "7.0.0"),
    "esm3.generate_paired.local_open": ("8.0.0", "7.0.0"),
    "esm3.generate_sequence.biohub_medium": ("8.0.0", "7.0.0"),
    "esm3.generate_sequence.biohub_open": ("8.0.0", "7.0.0"),
    "esm3.generate_sequence.local_open": ("8.0.0", "7.0.0"),
    "esm3.generate_structure.biohub_medium": ("8.0.0", "7.0.0"),
    "esm3.generate_structure.biohub_open": ("8.0.0", "7.0.0"),
    "esm3.generate_structure.local_open": ("8.0.0", "7.0.0"),
    "folding.fold.esmfold2_local": ("9.0.0", "8.0.0"),
    "folding.fold.esmfold2_remote": ("8.0.0", "7.0.0"),
    "folding.fold.simplefold_local": ("9.0.0", "8.0.0"),
    "folding.simplefold_confidence.simplefold_local": ("6.0.0", "5.0.0"),
    "protein_io.export_structure.direct": ("6.0.0", "5.0.0"),
    "protein_io.import_sequence.direct": ("6.0.0", "5.0.0"),
    "protein_io.import_structure.direct": ("6.0.0", "5.0.0"),
    "proteinmpnn.design.local": ("11.0.0", "10.0.0"),
    "proteinmpnn.score.local": ("8.0.0", "7.0.0"),
    "selection.diversity.direct": ("5.0.0", "4.0.0"),
    "selection.filter.direct": ("5.0.0", "4.0.0"),
    "selection.pareto.direct": ("5.0.0", "4.0.0"),
    "selection.sort.direct": ("5.0.0", "4.0.0"),
    "selection.top_k.direct": ("5.0.0", "4.0.0"),
    "selection.weighted_rank.direct": ("5.0.0", "4.0.0"),
    "solubility.protein_sol.local": ("5.0.0", "4.0.0"),
    "solubility.soluprot_full.local": ("5.0.0", "4.0.0"),
    "solubility.soluprot_no_tm.local": ("5.0.0", "4.0.0"),
    "structure_annotation.dssp_compute.mkdssp_local": ("7.0.0", "6.0.0"),
    "structure_annotation.expected_secondary_structure_from_prompt.direct": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_annotation.secondary_structure_agreement.direct": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_comparison.align_counterparts.sequence_primary_affine": (
        "5.0.0",
        "4.0.0",
    ),
    "structure_comparison.align_fixed_reference.sequence_primary_affine": (
        "5.0.0",
        "4.0.0",
    ),
    "structure_comparison.align_single.sequence_primary_affine": (
        "5.0.0",
        "4.0.0",
    ),
    "structure_comparison.align_single.structure_first_tm_align": (
        "5.0.0",
        "4.0.0",
    ),
    "structure_comparison.classify_three_way_consistency.direct": (
        "3.0.0",
        "2.0.0",
    ),
    "structure_comparison.evaluate_inserted_loop.direct": ("2.0.0", "1.0.0"),
    "structure_comparison.rmsd_counterparts.from_alignment_evidence": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_comparison.rmsd_fixed_reference.from_alignment_evidence": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_comparison.tm_score_counterparts.from_alignment_evidence": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_comparison.tm_score_fixed_reference.from_alignment_evidence": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_prediction.materialize_confidence.direct": ("2.0.0", "1.0.0"),
    "structure_transform.extract_sequence_candidates.direct": (
        "4.0.0",
        "3.0.0",
    ),
    "structure_transform.materialize_candidate_normalizations.direct": (
        "2.0.0",
        "1.0.0",
    ),
    "structure_transform.normalize_csh_parent_span_candidates.direct": (
        "2.0.0",
        "1.0.0",
    ),
    "structure_transform.project_single_residue_axis.direct": (
        "2.0.0",
        "1.0.0",
    ),
    "structure_transform.resolve_candidate_residue_axes.direct": (
        "6.0.0",
        "5.0.0",
    ),
    "structure_transform.select_candidate_chains.direct": ("4.0.0", "3.0.0"),
}


def test_candidate_reference_projection_ports_publish_new_exact_generations(
) -> None:
    catalog = build_discovered_frozen_catalog()

    expected_versions = {
        "candidate.collection": "4.0.0",
        "candidate.pairing": "4.0.0",
        "score.collection": "5.0.0",
        "structure_comparison.alignment_evidence": "5.0.0",
        "structure_comparison.inserted_loop_evaluation": "2.0.0",
        "structure_comparison.three_way_consistency": "3.0.0",
        "structure_prediction.confidence_facts": "2.0.0",
        "structure_prediction.prediction_residue_axis": "2.0.0",
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations"
        ): "6.0.0",
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations"
        ): "6.0.0",
    }
    replaced_versions = {
        "candidate.collection": "3.0.0",
        "candidate.pairing": "3.0.0",
        "score.collection": "4.0.0",
        "structure_comparison.alignment_evidence": "4.0.0",
        "structure_comparison.inserted_loop_evaluation": "1.0.0",
        "structure_comparison.three_way_consistency": "2.0.0",
        "structure_prediction.confidence_facts": "1.0.0",
        "structure_prediction.prediction_residue_axis": "1.0.0",
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations"
        ): "5.0.0",
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations"
        ): "5.0.0",
    }

    for type_id, version in expected_versions.items():
        port_type = catalog.require_port_type(type_id, version)
        if type_id != "structure_prediction.confidence_facts":
            assert port_type.candidate_data_projection is not None
        assert catalog.get_port_type(type_id, replaced_versions[type_id]) is None


def test_candidate_reference_projection_cascades_every_dependent_contract(
) -> None:
    catalog = build_discovered_frozen_catalog()

    for node_id, (active, replaced) in (
        _CANDIDATE_PROJECTION_NODE_GENERATIONS.items()
    ):
        catalog.require_contract("node_type", node_id, active)
        assert catalog.get_contract("node_type", node_id, replaced) is None

    for binding_id, (active, replaced) in (
        _CANDIDATE_PROJECTION_BINDING_GENERATIONS.items()
    ):
        binding = catalog.require_contract("binding", binding_id, active)
        assert binding.descriptor["node_type"]["contract_version"] == (
            _CANDIDATE_PROJECTION_NODE_GENERATIONS[
                binding.descriptor["node_type"]["contract_id"]
            ][0]
        )
        assert catalog.get_contract("binding", binding_id, replaced) is None

    for method_id, (active, replaced) in (
        _CANDIDATE_PROJECTION_METHOD_GENERATIONS.items()
    ):
        catalog.require_contract("method", method_id, active)
        assert catalog.get_contract("method", method_id, replaced) is None


def _cascade_catalog():
    from modules.esm3.package import MODULE_PACKAGE as esm3_package
    from modules.folding.package import MODULE_PACKAGE as folding_package
    from modules.prompt_authoring.package import MODULE_PACKAGE as prompt_package
    from modules.proteinmpnn.package import MODULE_PACKAGE as proteinmpnn_package
    from modules.structure_comparison.package import (
        MODULE_PACKAGE as structure_comparison_package,
    )
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
            structure_comparison_package,
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
        node = catalog.require_contract("node_type", node_id, "8.0.0")
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
                assert output_port["contract_version"] == "4.0.0"
            if output_port["contract_id"] == (
                "structure_prediction.confidence_facts"
            ):
                assert output_port["contract_version"] == "2.0.0"
            assert output_port["contract_id"] != "score.collection"
        for route in routes:
            binding = catalog.require_contract(
                "binding", f"{node_id}.{route}", "8.0.0"
            )
            assert binding.descriptor["method"]["contract_version"] == "5.0.0"
            assert binding.descriptor["produced_observations"] == ()
        assert catalog.get_contract("node_type", node_id, "7.0.0") is None


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
        "constraints": (
            "4.0.0",
            "4.0.0",
            "3.0.0",
            "3.0.0",
            "3.0.0",
        ),
        "random_fixed_positions": (
            "4.0.0",
            "4.0.0",
            "3.0.0",
            "3.0.0",
            "3.0.0",
        ),
        "design": (
            "10.0.0",
            "11.0.0",
            "6.0.0",
            "9.0.0",
            "10.0.0",
        ),
        "score": (
            "7.0.0",
            "8.0.0",
            "6.0.0",
            "6.0.0",
            "7.0.0",
        ),
    }
    for operation, (
        node_version,
        binding_version,
        method_version,
        legacy_node_version,
        legacy_binding_version,
    ) in expected.items():
        node_id = f"proteinmpnn.{operation}"
        catalog.require_contract("node_type", node_id, node_version)
        binding = catalog.require_contract(
            "binding", f"{node_id}.local", binding_version
        )
        assert binding.descriptor["method"][
            "contract_version"
        ] == method_version
        assert catalog.get_contract(
            "node_type", node_id, legacy_node_version
        ) is None
        assert catalog.get_contract(
            "binding", f"{node_id}.local", legacy_binding_version
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
        "node_type", "proteinmpnn.design", "10.0.0"
    )
    assert {
        port["name"]: (
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in design.descriptor["inputs"]
    }["structure_residue_axes"] == (
        "structure_transform.candidate_resolved_residue_axis_associations",
        "6.0.0",
    )
    score = catalog.require_contract(
        "node_type", "proteinmpnn.score", "7.0.0"
    )
    assert score.descriptor["outputs"][0]["port_type"]["contract_id"] == (
        "score.collection"
    )
    assert score.descriptor["outputs"][0]["port_type"]["contract_version"] == (
        "5.0.0"
    )


def test_structure_comparison_utilities_follow_the_score_contract_generation(
) -> None:
    catalog = _cascade_catalog()

    for pairing_mode in (
        "fixed_reference",
        "per_subject_counterpart",
    ):
        transform_id = (
            "structure_comparison.tm_score."
            f"{pairing_mode}.identity"
        )
        catalog.require_contract(
            "utility_transform",
            transform_id,
            "4.0.0",
        )
        assert catalog.get_contract(
            "utility_transform",
            transform_id,
            "3.0.0",
        ) is None


def test_structure_comparison_conclusion_ports_follow_embedded_methods() -> None:
    catalog = _cascade_catalog()

    expected_outputs = {
        "structure_comparison.classify_three_way_consistency": (
            "3.0.0",
            "consistency",
            "structure_comparison.three_way_consistency",
            "3.0.0",
        ),
        "structure_comparison.evaluate_inserted_loop": (
            "2.0.0",
            "quality_evidence",
            "structure_comparison.inserted_loop_evaluation",
            "2.0.0",
        ),
    }
    for node_id, (
        node_version,
        output_name,
        port_type_id,
        port_type_version,
    ) in expected_outputs.items():
        node = catalog.require_contract("node_type", node_id, node_version)
        outputs = {
            output["name"]: output["port_type"]
            for output in node.descriptor["outputs"]
        }
        assert outputs[output_name]["contract_id"] == port_type_id
        assert outputs[output_name]["contract_version"] == port_type_version


def test_folding_and_confidence_materialization_use_fact_then_score_generations(
) -> None:
    catalog = _cascade_catalog()

    fold = catalog.require_contract("node_type", "folding.fold", "7.0.0")
    assert {
        output["name"]: (
            output["port_type"]["contract_id"],
            output["port_type"]["contract_version"],
        )
        for output in fold.descriptor["outputs"]
    } == {
        "structure_candidates": ("candidate.collection", "4.0.0"),
        "confidence_facts": (
            "structure_prediction.confidence_facts",
            "2.0.0",
        ),
    }
    for binding_id, binding_version in (
        ("folding.fold.esmfold2_remote", "8.0.0"),
        ("folding.fold.esmfold2_local", "9.0.0"),
        ("folding.fold.simplefold_local", "9.0.0"),
    ):
        binding = catalog.require_contract(
            "binding",
            binding_id,
            binding_version,
        )
        assert binding.descriptor["method"]["contract_version"] == {
            "folding.fold.esmfold2_remote": "4.0.0",
            "folding.fold.esmfold2_local": "6.0.0",
            "folding.fold.simplefold_local": "5.0.0",
        }[binding_id]
        assert binding.descriptor["produced_observations"] == ()

    confidence = catalog.require_contract(
        "node_type", "folding.simplefold_confidence", "5.0.0"
    )
    assert confidence.descriptor["outputs"][0]["port_type"][
        "contract_version"
    ] == "5.0.0"

    materializer = catalog.require_contract(
        "node_type",
        "structure_prediction.materialize_confidence",
        "2.0.0",
    )
    assert {
        port["name"]: (
            port["port_type"]["contract_id"],
            port["port_type"]["contract_version"],
        )
        for port in materializer.descriptor["inputs"]
    } == {
        "structure_candidates": ("candidate.collection", "4.0.0"),
        "confidence_facts": (
            "structure_prediction.confidence_facts",
            "2.0.0",
        ),
    }
    assert materializer.descriptor["outputs"][0]["port_type"] == {
        "contract_kind": "port_type",
        "contract_id": "score.collection",
        "contract_version": "5.0.0",
        "contract_digest": materializer.descriptor["outputs"][0]["port_type"][
            "contract_digest"
        ],
    }
    binding = catalog.require_contract(
        "binding",
        "structure_prediction.materialize_confidence.direct",
        "2.0.0",
    )
    assert binding.descriptor["method"]["contract_version"] == "2.0.0"
    assert {
        observation["method_port"]
        for observation in binding.descriptor["produced_observations"]
    } == {"confidence_facts"}
