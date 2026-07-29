"""Public v2 contracts for ProteinPrompt authoring operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import (
    PortValueError,
    WorkflowAuthoringError,
    build_discovered_frozen_catalog,
    discover_module_packages,
)
from core.workflow_v2 import WorkflowEdge
from datatypes import (
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueTrack,
)
from tests.fixtures.prompt_authoring_v2 import decoded_output, run_operation


VERSION = "2.0.0"


def test_prompt_authoring_registers_three_prompt_nodes_once() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["prompt_authoring"]
    assert {
        resource.resource for resource in registration.node_definitions
    } >= {
        "definitions/assemble_protein_prompt.yaml",
        "definitions/add_function_annotation.yaml",
        "definitions/update_prompt_sequence.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    assert {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "prompt_authoring" in catalog.owners[
            (kind, contract_id, version)
        ]
    } >= {
        ("prompt_authoring.assemble_protein_prompt", VERSION),
        ("prompt_authoring.add_function_annotation", VERSION),
        ("prompt_authoring.update_prompt_sequence", VERSION),
    }


def test_function_annotation_keeps_chain_qualified_provenance(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="add_function_annotation",
        node_parameters={
            "annotation": {
                "label": "binding_site",
                "chain_id": "A",
                "start_residue_id": "A:1",
                "end_residue_id": "A:2",
            },
            "overlap_policy": "reject",
        },
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
        ),
    )

    assert projection["status"] == "succeeded"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    assert decoded_output(catalog, output) == FunctionAnnotations(
        [{
            "label": "binding_site",
            "start": 1,
            "end": 2,
            "chain_id": "A",
            "start_residue_id": "A:1",
            "end_residue_id": "A:2",
            "overlap_policy": "reject",
        }]
    )


def test_prompt_assembly_preserves_every_declared_aligned_track(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="assemble_protein_prompt",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "source_sequence_track",
                "author",
                "sequence_track",
            ),
            WorkflowEdge(
                "source",
                "source_structure_track",
                "author",
                "structure_track",
            ),
            WorkflowEdge(
                "source",
                "source_visibility_track",
                "author",
                "visibility_track",
            ),
            WorkflowEdge(
                "source",
                "source_secondary_structure_track",
                "author",
                "secondary_structure_track",
            ),
            WorkflowEdge(
                "source",
                "source_sasa_track",
                "author",
                "sasa_track",
            ),
            WorkflowEdge(
                "source",
                "function_annotations",
                "author",
                "function_annotations",
            ),
        ),
    )
    assert projection["status"] == "succeeded"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    assert decoded_output(catalog, output) == ProteinPrompt(
        target_layout=ResidueLayout(
            "A,B",
            3,
            ["A:1", "A:2", "B:1"],
        ),
        sequence_track=ResidueTrack(["A", "G", "S"], None),
        structure_track=ResidueTrack(
            [
                {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
                None,
                {"CA": (2.0, 0.0, 0.0)},
            ],
            None,
        ),
        structure_visibility_track=ResidueTrack([True, True, False], None),
        secondary_structure_track=ResidueTrack(["H", "E", "-"], None),
        sasa_track=ResidueTrack([12.5, None, 30.0], None),
        function_annotations=FunctionAnnotations(
            [{
                "label": "binding_site",
                "start": 1,
                "end": 2,
                "chain_id": "A",
                "start_residue_id": "A:1",
                "end_residue_id": "A:2",
                "overlap_policy": "reject",
            }]
        ),
    )


def test_generic_sequence_update_preserves_layout_and_unaffected_tracks(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="update_prompt_sequence",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
            WorkflowEdge(
                "source",
                "protein_sequence",
                "author",
                "sequence",
            ),
        ),
    )

    assert projection["status"] == "succeeded"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    updated = decoded_output(catalog, output)
    assert updated.sequence_track == ResidueTrack(["W", "F", "C"], None)
    assert updated.target_layout == ResidueLayout(
        "A,B",
        3,
        ["A:1", "A:2", "B:1"],
    )
    assert updated.structure_track == ResidueTrack(
        [
            {"N": (0.0, 0.0, 0.0), "CA": (1.0, 0.0, 0.0)},
            None,
            {"CA": (2.0, 0.0, 0.0)},
        ],
        None,
    )
    assert updated.structure_visibility_track == ResidueTrack(
        [True, True, False],
        None,
    )
    assert updated.secondary_structure_track == ResidueTrack(
        ["H", "E", "-"],
        None,
    )
    assert updated.sasa_track == ResidueTrack([12.5, None, 30.0], None)
    assert updated.function_annotations == FunctionAnnotations(
        [{
            "label": "binding_site",
            "start": 1,
            "end": 2,
            "chain_id": "A",
            "start_residue_id": "A:1",
            "end_residue_id": "A:2",
            "overlap_policy": "reject",
        }]
    )


def test_prompt_assembly_keeps_absent_optional_tracks_absent(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = run_operation(
        tmp_path,
        operation="assemble_protein_prompt",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
        ),
    )

    assert projection["status"] == "succeeded"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    prompt = decoded_output(catalog, output)
    assert prompt.sequence_track is None
    assert prompt.structure_track is None
    assert prompt.structure_visibility_track is None
    assert prompt.secondary_structure_track is None
    assert prompt.sasa_track is None
    assert prompt.function_annotations == FunctionAnnotations()


def test_prompt_assembly_rejects_track_from_another_effective_layout(
    tmp_path: Path,
) -> None:
    _, projection, _ = run_operation(
        tmp_path,
        operation="assemble_protein_prompt",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "target_structure_track",
                "author",
                "structure_track",
            ),
        ),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "author"
        for output in projection["outputs"]
    )


@pytest.mark.parametrize(
    "annotation",
    (
        {
            "label": "cross_chain",
            "chain_id": "A",
            "start_residue_id": "A:2",
            "end_residue_id": "B:1",
        },
        {
            "label": "reversed",
            "chain_id": "A",
            "start_residue_id": "A:2",
            "end_residue_id": "A:1",
        },
        {
            "label": "outside",
            "chain_id": "A",
            "start_residue_id": "A:1",
            "end_residue_id": "A:9",
        },
    ),
)
def test_function_annotation_rejects_invalid_layout_intervals(
    tmp_path: Path,
    annotation: dict[str, str],
) -> None:
    _, projection, _ = run_operation(
        tmp_path,
        operation="add_function_annotation",
        node_parameters={
            "annotation": annotation,
            "overlap_policy": "reject",
        },
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
        ),
    )

    assert projection["status"] == "failed"


@pytest.mark.parametrize(
    "source_fixture",
    (
        "annotation-overlap",
        "annotation-out-of-order",
        "annotation-cross-chain",
    ),
)
def test_prompt_assembly_rejects_noncanonical_function_annotations(
    tmp_path: Path,
    source_fixture: str,
) -> None:
    _, projection, _ = run_operation(
        tmp_path,
        operation="assemble_protein_prompt",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "function_annotations",
                "author",
                "function_annotations",
            ),
        ),
        source_fixture=source_fixture,
    )

    assert projection["status"] == "failed"


def test_function_annotation_overlap_policy_is_retained_and_enforced(
    tmp_path: Path,
) -> None:
    catalog, allowed, _ = run_operation(
        tmp_path / "allow",
        operation="add_function_annotation",
        node_parameters={
            "annotation": {
                "label": "active_site",
                "chain_id": "A",
                "start_residue_id": "A:2",
                "end_residue_id": "A:2",
            },
            "overlap_policy": "allow",
        },
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "function_annotations",
                "author",
                "existing_annotations",
            ),
        ),
        source_fixture="annotation-allow",
    )
    assert allowed["status"] == "succeeded"
    output = next(
        output
        for output in allowed["outputs"]
        if output["node_id"] == "author"
    )
    annotations = decoded_output(catalog, output)
    assert [item["label"] for item in annotations.annotations] == [
        "binding_site",
        "active_site",
    ]
    assert {
        item["overlap_policy"] for item in annotations.annotations
    } == {"allow"}

    _, rejected, _ = run_operation(
        tmp_path / "reject",
        operation="add_function_annotation",
        node_parameters={
            "annotation": {
                "label": "active_site",
                "chain_id": "A",
                "start_residue_id": "A:2",
                "end_residue_id": "A:2",
            },
            "overlap_policy": "reject",
        },
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "function_annotations",
                "author",
                "existing_annotations",
            ),
        ),
    )
    assert rejected["status"] == "failed"


def test_function_annotation_parameter_contract_rejects_blank_label(
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkflowAuthoringError) as rejected:
        run_operation(
            tmp_path,
            operation="add_function_annotation",
            node_parameters={
                "annotation": {
                    "label": "",
                    "chain_id": "A",
                    "start_residue_id": "A:1",
                    "end_residue_id": "A:1",
                },
                "overlap_policy": "reject",
            },
            source_edges=(
                WorkflowEdge("source", "source_layout", "author", "layout"),
            ),
        )

    assert rejected.value.code == "compile_rejected"


@pytest.mark.parametrize(
    "source_fixture",
    (
        "sequence-length-drift",
        "sequence-identity-drift",
        "sequence-illegal-symbol",
        "prompt-illegal-sequence",
    ),
)
def test_sequence_update_rejects_length_identity_and_symbol_drift(
    tmp_path: Path,
    source_fixture: str,
) -> None:
    _, projection, _ = run_operation(
        tmp_path,
        operation="update_prompt_sequence",
        node_parameters={},
        source_edges=(
            WorkflowEdge(
                "source",
                "protein_prompt",
                "author",
                "protein_prompt",
            ),
            WorkflowEdge(
                "source",
                "protein_sequence",
                "author",
                "sequence",
            ),
        ),
        source_fixture=source_fixture,
    )

    assert projection["status"] == "failed"


def test_prompt_nodes_expose_only_scientific_authoring_parameters() -> None:
    catalog = build_discovered_frozen_catalog()
    expected_inputs = {
        "prompt_authoring.assemble_protein_prompt": {
            "layout",
            "sequence_track",
            "structure_track",
            "visibility_track",
            "secondary_structure_track",
            "sasa_track",
            "function_annotations",
        },
        "prompt_authoring.add_function_annotation": {
            "layout",
            "existing_annotations",
        },
        "prompt_authoring.update_prompt_sequence": {
            "protein_prompt",
            "sequence",
        },
    }
    expected_parameters = {
        "prompt_authoring.assemble_protein_prompt": set(),
        "prompt_authoring.add_function_annotation": {
            "annotation",
            "overlap_policy",
        },
        "prompt_authoring.update_prompt_sequence": set(),
    }
    forbidden = {
        "credential",
        "device",
        "model",
        "endpoint",
        "path",
        "runtime",
    }
    for node_type_id, inputs in expected_inputs.items():
        contract = catalog.require_contract(
            "node_type",
            node_type_id,
            VERSION,
        )
        assert {
            port["name"] for port in contract.descriptor["inputs"]
        } == inputs
        parameters = set(contract.descriptor["node_parameters"])
        assert parameters == expected_parameters[node_type_id]
        assert not forbidden.intersection(parameters)
        binding = catalog.require_contract(
            "binding",
            f"{node_type_id}.direct",
            VERSION,
        )
        assert dict(binding.descriptor["binding_parameters"]) == {}


def test_function_annotation_port_declares_canonical_provenance_shape() -> None:
    definition = build_discovered_frozen_catalog().require_port_type(
        "function.annotations",
        VERSION,
    )

    assert definition.validator.parameters[
        "canonical_interval_contract"
    ] == {
        "fields": (
            "chain_id",
            "end",
            "end_residue_id",
            "label",
            "overlap_policy",
            "start",
            "start_residue_id",
        ),
        "indexing": "one-based-inclusive",
        "ordering": "start,end,label,chain-and-residue-provenance",
        "overlap_policy": ("allow", "reject"),
    }


@pytest.mark.parametrize(
    "annotations",
    (
        FunctionAnnotations([
            {
                "label": "later",
                "start": 2,
                "end": 2,
                "chain_id": "A",
                "start_residue_id": "A:2",
                "end_residue_id": "A:2",
                "overlap_policy": "allow",
            },
            {
                "label": "earlier",
                "start": 1,
                "end": 1,
                "chain_id": "A",
                "start_residue_id": "A:1",
                "end_residue_id": "A:1",
                "overlap_policy": "allow",
            },
        ]),
        FunctionAnnotations([
            {
                "label": "first",
                "start": 1,
                "end": 2,
                "chain_id": "A",
                "start_residue_id": "A:1",
                "end_residue_id": "A:2",
                "overlap_policy": "reject",
            },
            {
                "label": "overlap",
                "start": 2,
                "end": 2,
                "chain_id": "A",
                "start_residue_id": "A:2",
                "end_residue_id": "A:2",
                "overlap_policy": "reject",
            },
        ]),
    ),
)
def test_function_annotation_port_rejects_noncanonical_collections(
    annotations: FunctionAnnotations,
) -> None:
    definition = build_discovered_frozen_catalog().require_port_type(
        "function.annotations",
        VERSION,
    )

    with pytest.raises(PortValueError):
        definition.encode(annotations)


def test_protein_prompt_round_trip_preserves_esm3_adapter_intent(
    tmp_path: Path,
) -> None:
    import torch

    from modules.esm3_adapter import protein_prompt_to_esm_protein

    catalog, projection, _ = run_operation(
        tmp_path,
        operation="assemble_protein_prompt",
        node_parameters={},
        source_edges=(
            WorkflowEdge("source", "source_layout", "author", "layout"),
            WorkflowEdge(
                "source",
                "source_sequence_track",
                "author",
                "sequence_track",
            ),
            WorkflowEdge(
                "source",
                "source_structure_track",
                "author",
                "structure_track",
            ),
            WorkflowEdge(
                "source",
                "source_visibility_track",
                "author",
                "visibility_track",
            ),
            WorkflowEdge(
                "source",
                "source_secondary_structure_track",
                "author",
                "secondary_structure_track",
            ),
            WorkflowEdge(
                "source",
                "source_sasa_track",
                "author",
                "sasa_track",
            ),
            WorkflowEdge(
                "source",
                "function_annotations",
                "author",
                "function_annotations",
            ),
        ),
        source_fixture="adapter-boundary",
    )
    assert projection["status"] == "succeeded"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "author"
    )
    prompt = decoded_output(catalog, output)
    prompt_codec = catalog.require_port_type("protein.prompt", VERSION)
    round_tripped = prompt_codec.decode(prompt_codec.encode(prompt))

    provider_prompt = protein_prompt_to_esm_protein(round_tripped)

    assert provider_prompt.sequence == "AGS"
    assert provider_prompt.secondary_structure == "HE_"
    assert provider_prompt.sasa == [12.5, None, 30.0]
    assert provider_prompt.function_annotations is not None
    assert [
        (
            annotation.label,
            annotation.start,
            annotation.end,
        )
        for annotation in provider_prompt.function_annotations
    ] == [("binding_site", 1, 2)]
    assert provider_prompt.coordinates is not None
    assert torch.isfinite(provider_prompt.coordinates[0, 1]).all()
    assert torch.isnan(provider_prompt.coordinates[1]).all()
    assert torch.isnan(provider_prompt.coordinates[2]).all()
