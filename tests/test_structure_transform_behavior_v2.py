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
    WorkflowCompileError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import CandidateCollection, ProteinSequence, ProteinStructure
from modules.structure_transform.package import MODULE_PACKAGE
from tests.fixtures.proteinmpnn_model_sources.package import (
    MODULE_PACKAGE as CANDIDATE_SOURCE_PACKAGE,
)
from tests.fixtures.structure_transform_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.1.0"


def _run_transform(
    tmp_path: Path,
    *,
    operation: str,
    fixture: str = "canonical",
    node_parameters: dict[str, Any] | None = None,
    environment_label: str = "one",
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"structure transform {operation}")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_transform_source",
                node_type_version=VERSION,
                binding_id="contract_test.structure_transform_source.direct",
                binding_version=VERSION,
                node_parameters={"fixture": fixture},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="transform",
                node_type_id=f"structure_transform.{operation}",
                node_type_version=VERSION,
                binding_id=f"structure_transform.{operation}.direct",
                binding_version=VERSION,
                node_parameters=node_parameters or {},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "structure", "transform", "structure"),
        ),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (
                    f"structure_transform.{operation}.direct",
                    VERSION,
                ): {
                    "values": {
                        "irrelevant_runtime_label": (
                            f"not-result-affecting-{environment_label}"
                        )
                    },
                    "safe_fingerprint": (
                        f"provider-free-{environment_label}"
                    ),
                    "invalidation_token": (
                        f"provider-free-{environment_label}"
                    ),
                }
            }
        ),
    )
    receipt = service.start(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id=f"structure-transform-{operation}-{environment_label}",
    )
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    service.shutdown()
    return catalog, projection, events


def _transform_output(projection: dict[str, Any]) -> dict[str, Any]:
    return next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "transform"
    )


def _decode(catalog: Any, output: dict[str, Any]) -> Any:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": output["values"][0],
            }
        )
    )


def _run_candidate_transform(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    catalog = build_frozen_catalog((MODULE_PACKAGE, CANDIDATE_SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"candidate transform {operation}")
    authoring = WorkflowAuthoringService(projects, catalog)
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version=VERSION,
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id=(
                        "contract_test.proteinmpnn_3gb1_structure"
                    ),
                    node_type_version=VERSION,
                    binding_id=(
                        "contract_test.proteinmpnn_3gb1_structure.direct"
                    ),
                    binding_version=VERSION,
                    node_parameters={},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="transform",
                    node_type_id=f"structure_transform.{operation}",
                    node_type_version=VERSION,
                    binding_id=f"structure_transform.{operation}.direct",
                    binding_version=VERSION,
                    node_parameters=node_parameters or {},
                    binding_parameters={},
                ),
            ),
            edges=(
                WorkflowEdge(
                    "source",
                    "structure_candidates",
                    "transform",
                    "structure_candidates",
                ),
            ),
            contract_lock=(),
        ),
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration({}),
    )
    receipt = service.start(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id=f"candidate-transform-{operation}",
    )
    projection = service.projection(project.id, receipt["run_id"])
    service.shutdown()
    return catalog, projection


def test_chain_selection_obeys_requested_order_and_excludes_other_chains(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = _run_transform(
        tmp_path,
        operation="select_chains",
        node_parameters={"chain_ids": ["B", "A"]},
    )

    assert projection["status"] == "succeeded"
    structure = _decode(catalog, _transform_output(projection))
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
    _, projection, _ = _run_transform(
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
    catalog, projection, _ = _run_transform(
        tmp_path,
        operation="select_chains",
        fixture="alternate_locations",
        node_parameters={"chain_ids": ["A"]},
    )

    structure = _decode(catalog, _transform_output(projection))
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
    _, projection, _ = _run_transform(
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
    catalog, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
    )

    output = _transform_output(projection)
    backbone = _decode(catalog, output)
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
    assert backbone.source == "structure_transform.extract_backbone"
    port_type = catalog.require_port_type(
        "structure_transform.backbone_structure",
        VERSION,
    )
    assert output["content_digest"] == port_type.content_digest(backbone)
    assert output["result_identity"].startswith("sha256:")
    assert output["output_port"] == "backbone"


def test_backbone_resolves_alternate_locations_to_a_and_normalizes_marker(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
        fixture="alternate_locations",
    )

    backbone = _decode(catalog, _transform_output(projection))
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
    _, projection, _ = _run_transform(
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
    _, projection, _ = _run_transform(
        tmp_path,
        operation="extract_backbone",
        fixture="residue_name_conflict",
    )

    assert projection["status"] == "failed"
    assert not any(
        output["node_id"] == "transform"
        for output in projection["outputs"]
    )


def test_sequence_ignores_non_protein_maps_unknown_and_keeps_correspondence(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = _run_transform(
        tmp_path,
        operation="extract_sequence",
        fixture="sequence_edge_cases",
    )

    sequence = _decode(catalog, _transform_output(projection))
    assert sequence == ProteinSequence(
        sequence="AXG",
        residue_ids=["A:1", "A:2", "B:5"],
    )


def test_candidate_sequence_extraction_preserves_parent_lineage(
    tmp_path: Path,
) -> None:
    catalog, projection = _run_candidate_transform(
        tmp_path,
        operation="extract_sequence_candidates",
    )

    assert projection["status"] == "succeeded"
    source = _decode(
        catalog,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "source"
        ),
    )
    transformed = _decode(catalog, _transform_output(projection))
    assert type(source) is CandidateCollection
    assert type(transformed) is CandidateCollection
    assert transformed.item_type == "protein.sequence"
    assert len(transformed.items) == 1
    child = transformed.items[0]
    assert child.data == ProteinSequence(
        sequence="MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE",
        residue_ids=[f"A:{position}" for position in range(1, 57)],
    )
    assert child.parent_ids == [source.items[0].candidate_id]


def test_candidate_chain_selection_preserves_parent_lineage(
    tmp_path: Path,
) -> None:
    catalog, projection = _run_candidate_transform(
        tmp_path,
        operation="select_candidate_chains",
        node_parameters={"chain_ids": ["A"]},
    )

    assert projection["status"] == "succeeded"
    source = _decode(
        catalog,
        next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "source"
        ),
    )
    transformed = _decode(catalog, _transform_output(projection))
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
    assert child.parent_ids == [source.items[0].candidate_id]


def test_provider_free_transform_identity_is_stable_across_environments(
    tmp_path: Path,
) -> None:
    first_catalog, first, first_events = _run_transform(
        tmp_path / "first",
        operation="extract_sequence",
        environment_label="first",
    )
    second_catalog, second, second_events = _run_transform(
        tmp_path / "second",
        operation="extract_sequence",
        environment_label="second",
    )
    first_output = _transform_output(first)
    second_output = _transform_output(second)

    assert first_output["result_identity"] == second_output["result_identity"]
    assert first_output["content_digest"] == second_output["content_digest"]
    assert _decode(first_catalog, first_output) == _decode(
        second_catalog,
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
