"""Scientific behavior acceptance for structure transforms."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowAuthoringError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
)
from core.workflow_v2 import WorkflowEdge
from datatypes import CandidateCollection, ProteinSequence, ProteinStructure
from modules.structure_transform import CandidateResolvedResidueAxisAssociations
from modules.structure_transform.package import MODULE_PACKAGE
from tests.fixtures.proteinmpnn_model_sources.package import (
    MODULE_PACKAGE as CANDIDATE_SOURCE_PACKAGE,
)
from tests.fixtures.structure_transform_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.1.0"
CANDIDATE_SOURCE_VERSION = "3.0.0"
CANDIDATE_NODE_VERSION = "3.0.0"
STRUCTURE_VERSION = "4.0.0"
CANDIDATE_AXIS_VERSION = "5.0.0"
SOURCE_VERSION = "5.0.0"
BACKBONE_PORT_VERSION = "4.0.0"


def _run_transform(
    tmp_path: Path,
    *,
    operation: str,
    fixture: str = "canonical",
    node_parameters: dict[str, Any] | None = None,
    environment_label: str = "one",
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"structure transform {operation}")
    operation_version = STRUCTURE_VERSION
    authoring = WorkflowAuthoringService(projects, catalog)
    needs_resolved_axis = operation in {"extract_backbone", "extract_sequence"}
    nodes = [
        WorkflowNodeInstance(
            node_id="source",
            node_type_id="contract_test.structure_transform_source",
            node_type_version=SOURCE_VERSION,
            binding_id="contract_test.structure_transform_source.direct",
            binding_version=SOURCE_VERSION,
            node_parameters={"fixture": fixture},
            binding_parameters={},
        )
    ]
    edges: list[WorkflowEdge] = []
    if needs_resolved_axis:
        nodes.append(
            WorkflowNodeInstance(
                node_id="resolve-axis",
                node_type_id="structure_transform.resolve_residue_axis",
                node_type_version=STRUCTURE_VERSION,
                binding_id=(
                    "structure_transform.resolve_residue_axis.direct"
                ),
                binding_version=STRUCTURE_VERSION,
                node_parameters={},
                binding_parameters={},
            )
        )
        edges.extend(
            (
                WorkflowEdge(
                    "source",
                    "structure",
                    "resolve-axis",
                    "structure",
                ),
                WorkflowEdge(
                    "resolve-axis",
                    "residue_axis",
                    "transform",
                    "residue_axis",
                ),
            )
        )
    else:
        edges.append(
            WorkflowEdge("source", "structure", "transform", "structure")
        )
    nodes.append(
        WorkflowNodeInstance(
            node_id="transform",
            node_type_id=f"structure_transform.{operation}",
            node_type_version=operation_version,
            binding_id=f"structure_transform.{operation}.direct",
            binding_version=operation_version,
            node_parameters=node_parameters or {},
            binding_parameters={},
        )
    )
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id=project.id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (
                    f"structure_transform.{operation}.direct",
                    operation_version,
                ): {
                    "values": {
                        "irrelevant_runtime_label": (
                            f"not-result-affecting-{environment_label}"
                        )
                    },
                }
            }
        ),
    )
    receipt = service.start(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id=f"structure-transform-{operation}-{environment_label}",
    )
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    service.shutdown()
    return catalog, service, projection, events


def _transform_output(projection: dict[str, Any]) -> dict[str, Any]:
    return next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "transform"
    )


def _decode(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _run_candidate_transform(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any] | None = None,
) -> tuple[Any, V2RunService, dict[str, Any]]:
    catalog = build_frozen_catalog((MODULE_PACKAGE, CANDIDATE_SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"candidate transform {operation}")
    authoring = WorkflowAuthoringService(projects, catalog)
    operation_version = (
        CANDIDATE_AXIS_VERSION
        if operation == "resolve_candidate_residue_axes"
        else CANDIDATE_NODE_VERSION
    )
    needs_resolved_axes = operation == "extract_sequence_candidates"
    nodes = [
        WorkflowNodeInstance(
            node_id="source",
            node_type_id=("contract_test.proteinmpnn_3gb1_structure"),
            node_type_version=CANDIDATE_SOURCE_VERSION,
            binding_id=(
                "contract_test.proteinmpnn_3gb1_structure.direct"
            ),
            binding_version=CANDIDATE_SOURCE_VERSION,
            node_parameters={},
            binding_parameters={},
        )
    ]
    edges = [
        WorkflowEdge(
            "source",
            "structure_candidates",
            "transform",
            "structure_candidates",
        )
    ]
    if needs_resolved_axes:
        nodes.append(
            WorkflowNodeInstance(
                node_id="resolve-axes",
                node_type_id=(
                    "structure_transform.resolve_candidate_residue_axes"
                ),
                node_type_version=CANDIDATE_AXIS_VERSION,
                binding_id=(
                    "structure_transform.resolve_candidate_residue_axes.direct"
                ),
                binding_version=CANDIDATE_AXIS_VERSION,
                node_parameters={},
                binding_parameters={},
            )
        )
        edges.extend(
            (
                WorkflowEdge(
                    "source",
                    "structure_candidates",
                    "resolve-axes",
                    "structure_candidates",
                ),
                WorkflowEdge(
                    "resolve-axes",
                    "residue_axes",
                    "transform",
                    "residue_axes",
                ),
            )
        )
    nodes.append(
        WorkflowNodeInstance(
            node_id="transform",
            node_type_id=f"structure_transform.{operation}",
            node_type_version=operation_version,
            binding_id=f"structure_transform.{operation}.direct",
            binding_version=operation_version,
            node_parameters=node_parameters or {},
            binding_parameters={},
        )
    )
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version=VERSION,
            workflow_id=project.id,
            nodes=tuple(nodes),
            edges=tuple(edges),
            contract_lock=(),
        ),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration({}),
    )
    receipt = service.start(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id=f"candidate-transform-{operation}",
    )
    projection = service.projection(project.id, receipt["run_id"])
    service.shutdown()
    return catalog, service, projection


def test_chain_selection_obeys_requested_order_and_excludes_other_chains(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_transform(
        tmp_path,
        operation="select_chains",
        node_parameters={"chain_ids": ["B", "A"]},
    )

    assert projection["status"] == "succeeded"
    structure = _decode(catalog, service, projection, _transform_output(projection))
    atom_chains = [
        line[21]
        for line in structure.pdb_string.splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    atom_serials = [
        int(line[6:11])
        for line in structure.pdb_string.splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    assert atom_chains[:6] == ["B"] * 6
    assert atom_chains[6:] == ["A"] * 5
    assert atom_serials == list(range(1, 12))
    assert structure.pdb_string.endswith("TER\nEND\n")
    assert "private-source-label" not in structure.pdb_string


@pytest.mark.parametrize(
    ("chain_ids", "error_code"),
    (
        ([], "invalid_parameter"),
        (["A", "A"], "invalid_parameter"),
    ),
)
def test_chain_selection_rejects_empty_and_duplicate_requests(
    tmp_path: Path,
    chain_ids: list[str],
    error_code: str,
) -> None:
    with pytest.raises(WorkflowAuthoringError) as rejected:
        _run_transform(
            tmp_path,
            operation="select_chains",
            node_parameters={"chain_ids": chain_ids},
        )

    assert rejected.value.code == "compile_rejected"
    assert rejected.value.details["issues"][0]["code"] == error_code


def test_chain_selection_rejects_missing_chain_without_output(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = _run_transform(
        tmp_path,
        operation="select_chains",
        node_parameters={"chain_ids": ["Z"]},
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_chain_selection_preserves_distinct_alternate_locations(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_transform(
        tmp_path,
        operation="select_chains",
        fixture="alternate_locations",
        node_parameters={"chain_ids": ["A"]},
    )

    structure = _decode(catalog, service, projection, _transform_output(projection))
    ca_lines = [
        line
        for line in structure.pdb_string.splitlines()
        if line.startswith("ATOM  ") and line[12:16].strip() == "CA"
    ]
    assert [line[16] for line in ca_lines] == ["B", "A"]
    assert [int(line[6:11]) for line in ca_lines] == [2, 3]


@pytest.mark.parametrize(
    "operation",
    ("select_chains", "extract_backbone", "extract_sequence"),
)
def test_all_transforms_reject_multi_model_inputs(
    tmp_path: Path,
    operation: str,
) -> None:
    _, _, projection, _ = _run_transform(
        tmp_path,
        operation=operation,
        fixture="multi_model",
        node_parameters=(
            {"chain_ids": ["A"]}
            if operation == "select_chains"
            else {}
        ),
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_backbone_retains_exact_atoms_chain_breaks_and_canonical_digest(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
    )

    output = _transform_output(projection)
    backbone = _decode(catalog, service, projection, output)
    lines = backbone.pdb_string.splitlines()
    atom_lines = [line for line in lines if line.startswith("ATOM  ")]
    assert [line[12:16].strip() for line in atom_lines] == [
        "N",
        "CA",
        "C",
        "O",
        "N",
        "CA",
        "C",
        "O",
    ]
    assert [line[21] for line in atom_lines] == ["A"] * 4 + ["B"] * 4
    assert lines.count("TER") == 2
    assert not any(line.startswith("HETATM") for line in lines)
    assert backbone == ProteinStructure(backbone.pdb_string)
    port_type = catalog.require_port_type(
        "structure_transform.backbone_structure",
        BACKBONE_PORT_VERSION,
    )
    assert output["content_digest"] == port_type.content_digest(backbone)
    assert output["result_identity"].startswith("sha256:")
    assert output["output_port"] == "backbone"


def test_backbone_resolves_alternate_locations_to_a_and_normalizes_marker(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
        fixture="alternate_locations",
    )

    backbone = _decode(catalog, service, projection, _transform_output(projection))
    ca = next(
        line
        for line in backbone.pdb_string.splitlines()
        if line.startswith("ATOM  ") and line[12:16].strip() == "CA"
    )
    assert float(ca[30:38]) == 10.0
    assert ca[16] == " "


def test_backbone_rejects_a_residue_with_missing_atoms(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
        fixture="missing_backbone",
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_backbone_rejects_conflicting_names_within_one_residue(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
        fixture="residue_name_conflict",
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_sequence_excludes_non_protein_and_keeps_authored_correspondence(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_transform(
        tmp_path,
        operation="extract_sequence",
        fixture="sequence_edge_cases",
    )

    sequence = _decode(catalog, service, projection, _transform_output(projection))
    assert sequence == ProteinSequence(
        sequence="AVG",
        residue_ids=["A:1", "A:2", "B:5"],
    )


def test_resolved_axis_normalizes_mse_and_excludes_ligand_and_water(
    tmp_path: Path,
) -> None:
    catalog, service, projection, _ = _run_transform(
        tmp_path,
        operation="resolve_residue_axis",
        fixture="mse_ligand_water",
    )

    assert projection["status"] == "succeeded"
    source = _decode(
        catalog,
        service,
        projection,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "source"
            and output["output_port"] == "structure"
        ),
    )
    axis = _decode(catalog, service, projection, _transform_output(projection))
    assert axis.structure == source
    assert axis.layout.chain_id == "A"
    assert axis.layout.residue_ids == ("A:1", "A:2", "A:3")
    assert axis.sequence == "AMG"
    assert axis.residue_names == ("ALA", "MET", "GLY")
    assert [
        (segment.segment_index, segment.chain_id, segment.residue_ids)
        for segment in axis.segments
    ] == [(0, "A", ("A:1", "A:2", "A:3"))]
    assert axis.ca_coordinate_mask == (True, True, True)
    assert axis.complete_backbone_mask == (True, True, True)
    assert axis.coordinate_for("A:2", "CA") == (6.0, 2.0, 3.0)
    assert axis.backbone_coordinates_for("A:2") == {
        "N": (5.0, 2.0, 3.0),
        "CA": (6.0, 2.0, 3.0),
        "C": (7.0, 2.0, 3.0),
        "O": (8.0, 2.0, 3.0),
    }
    with pytest.raises(KeyError, match="Z:900"):
        axis.coordinate_for("Z:900", "C1")
    assert [
        (
            item.component_id,
            item.observed_residue_id,
            item.component_role,
            item.disposition,
            item.parent_residue_ids,
            item.parent_sequence,
            item.normalization_source,
        )
        for item in axis.component_dispositions
    ] == [
        ("ALA", "A:1", "polymer", "included", ("A:1",), "A", None),
        (
            "MSE",
            "A:2",
            "modified_polymer",
            "normalized",
            ("A:2",),
            "M",
            "pdb_modres",
        ),
        ("GLY", "A:3", "polymer", "included", ("A:3",), "G", None),
        ("LIG", "Z:900", "ligand", "excluded", (), "", None),
        ("HOH", "Z:901", "water", "excluded", (), "", None),
    ]
    normalization = axis.modified_residue_normalizations.entries
    assert len(normalization) == 1
    assert normalization[0].component_id == "MSE"
    assert normalization[0].observed_residue_id == "A:2"
    assert normalization[0].parent_residue_ids == ("A:2",)
    assert normalization[0].parent_sequence == "M"
    assert any(
        mapping.source_atom_name == "SE"
        and mapping.parent_atom_name == "SD"
        for mapping in normalization[0].atom_mappings
    )
    assert "HETATM" in axis.structure.pdb_string
    assert all(
        component in axis.structure.pdb_string
        for component in ("MSE", "LIG", "HOH")
    )


def test_resolved_axis_rejects_unknown_modified_polymer(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = _run_transform(
        tmp_path,
        operation="resolve_residue_axis",
        fixture="unknown_modified_polymer",
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_resolved_axis_rejects_unknown_atom_polymer(
    tmp_path: Path,
) -> None:
    _, _, projection, _ = _run_transform(
        tmp_path,
        operation="resolve_residue_axis",
        fixture="unknown_atom_polymer",
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_candidate_sequence_extraction_preserves_parent_lineage(
    tmp_path: Path,
) -> None:
    catalog, service, projection = _run_candidate_transform(
        tmp_path,
        operation="extract_sequence_candidates",
    )

    assert projection["status"] == "succeeded"
    source = _decode(
        catalog,
        service,
        projection,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "source"
        ),
    )
    transformed = _decode(catalog, service, projection, _transform_output(projection))
    assert type(source) is CandidateCollection
    assert type(transformed) is CandidateCollection
    assert transformed.item_type == "protein.sequence"
    assert len(transformed.items) == 1
    child = transformed.items[0]
    assert child.data == ProteinSequence(
        sequence="MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE",
        residue_ids=[f"A:{position}" for position in range(1, 57)],
    )
    assert child.parent_ids == (source.items[0].candidate_id,)


def test_candidate_chain_selection_preserves_parent_lineage(
    tmp_path: Path,
) -> None:
    catalog, service, projection = _run_candidate_transform(
        tmp_path,
        operation="select_candidate_chains",
        node_parameters={"chain_ids": ["A"]},
    )

    assert projection["status"] == "succeeded"
    source = _decode(
        catalog,
        service,
        projection,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "source"
        ),
    )
    transformed = _decode(catalog, service, projection, _transform_output(projection))
    assert type(source) is CandidateCollection
    assert type(transformed) is CandidateCollection
    assert transformed.item_type == "protein.structure"
    assert len(transformed.items) == 1
    child = transformed.items[0]
    assert {
        line[21]
        for line in child.data.pdb_string.splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    } == {"A"}
    assert child.parent_ids == (source.items[0].candidate_id,)


def test_candidate_residue_axes_bind_exact_structure_candidate_reference(
    tmp_path: Path,
) -> None:
    catalog, service, projection = _run_candidate_transform(
        tmp_path,
        operation="resolve_candidate_residue_axes",
    )

    assert projection["status"] == "succeeded"
    source = _decode(
        catalog,
        service,
        projection,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "source"
        ),
    )
    transformed = _decode(catalog, service, projection, _transform_output(projection))
    assert type(source) is CandidateCollection
    assert type(transformed) is CandidateResolvedResidueAxisAssociations
    assert len(transformed.entries) == 1
    association = transformed.entries[0]
    assert association.subject.candidate_id == source.items[0].candidate_id
    assert association.subject.data_type_id == "protein.structure"
    structure_type = catalog.require_port_type(
        "protein.structure",
        STRUCTURE_VERSION,
    )
    assert association.subject.content_digest == structure_type.content_digest(
        source.items[0].data
    )
    assert association.residue_axis.structure == source.items[0].data


def test_provider_free_transform_identity_is_stable_across_environments(
    tmp_path: Path,
) -> None:
    first_catalog, first_service, first, first_events = _run_transform(
        tmp_path / "first",
        operation="extract_sequence",
        environment_label="first",
    )
    second_catalog, second_service, second, second_events = _run_transform(
        tmp_path / "second",
        operation="extract_sequence",
        environment_label="second",
    )
    first_output = _transform_output(first)
    second_output = _transform_output(second)

    assert first_output["result_identity"] == second_output["result_identity"]
    assert first_output["content_digest"] == second_output["content_digest"]
    assert _decode(
        first_catalog,
        first_service,
        first,
        first_output,
    ) == _decode(
        second_catalog,
        second_service,
        second,
        second_output,
    )
    retained = str(
        {
            "first": first,
            "second": second,
            "first_events": first_events,
            "second_events": second_events,
        }
    )
    assert "not-result-affecting" not in retained
    assert "private-fixture" not in retained
