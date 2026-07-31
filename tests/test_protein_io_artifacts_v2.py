"""Run-bound artifact acceptance for the protein I/O Module Package."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    builtin_frozen_catalog,
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.fixtures.protein_io_sources.package import (
    MODULE_PACKAGE as STRUCTURE_SOURCE_PACKAGE,
)


def _run_import_export(
    tmp_path: Path,
    *,
    value_kind: str,
    payload: bytes,
) -> tuple[V2RunService, str, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_discovered_frozen_catalog()
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"protein I/O {value_kind} round trip")
    projects.publish_input(project.id, f"{value_kind}-input", payload)
    authoring = WorkflowAuthoringService(projects, catalog)
    nodes = tuple(
        WorkflowNodeInstance(
            node_id=role,
            node_type_id=f"protein_io.{role}_{value_kind}",
            node_type_version="2.1.0",
            binding_id=f"protein_io.{role}_{value_kind}.direct",
            binding_version="2.1.0",
            node_parameters=(
                {"project_input_ref": f"{value_kind}-input"}
                if role == "import"
                else {}
            ),
            binding_parameters={},
        )
        for role in ("import", "export")
    )
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=nodes,
        edges=(
            WorkflowEdge("import", value_kind, "export", value_kind),
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
        EnvironmentConfiguration({}),
    )
    receipt = service.start_background(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id=f"protein-io-{value_kind}-round-trip",
    )
    service.shutdown()
    return (
        service,
        project.id,
        service.projection(project.id, receipt["run_id"]),
        service.public_events(project.id, receipt["run_id"]),
    )


def test_sequence_export_publishes_only_an_opaque_run_bound_fasta(
    tmp_path: Path,
) -> None:
    service, project_id, projection, _ = _run_import_export(
        tmp_path,
        value_kind="sequence",
        payload=b">source\nACDEFG\n",
    )

    assert projection["status"] == "succeeded"
    assert [output["output_port"] for output in projection["outputs"]] == [
        "sequence",
        "sequence_candidates",
    ]
    assert len(projection["artifact_index"]) == 1
    artifact = projection["artifact_index"][0]
    assert artifact["artifact_kind"] == "standalone"
    assert artifact["node_id"] == "export"
    assert artifact["output_port"] == "standalone_artifact"
    assert artifact["media_type"] == "text/x-fasta"
    assert "/" not in artifact["artifact_reference"]
    assert "path" not in str(projection).lower()
    descriptor, body = service.artifact(
        project_id,
        projection["run_id"],
        artifact["artifact_reference"],
    )
    assert descriptor == artifact
    assert body == b">protein-workbench-sequence\nACDEFG\n"


def test_artifact_retrieval_rejects_tampering_symlinks_and_traversal(
    tmp_path: Path,
) -> None:
    service, project_id, projection, _ = _run_import_export(
        tmp_path,
        value_kind="sequence",
        payload=b">source\nACDEFG\n",
    )
    artifact = projection["artifact_index"][0]
    reference = artifact["artifact_reference"]
    managed = (
        tmp_path
        / "outputs"
        / project_id
        / projection["run_id"]
        / "published"
        / reference
    )
    managed.write_bytes(b"TAMPERED")
    managed.chmod(0o600)
    with pytest.raises(V2RunError) as tampered:
        service.artifact(project_id, projection["run_id"], reference)
    assert tampered.value.code == "artifact_integrity_mismatch"

    managed.unlink()
    outside = tmp_path / "outside.fasta"
    outside.write_bytes(b">outside\nW\n")
    managed.symlink_to(outside)
    with pytest.raises(V2RunError) as symlinked:
        service.artifact(project_id, projection["run_id"], reference)
    assert symlinked.value.code == "artifact_integrity_mismatch"

    with pytest.raises(V2RunError) as traversed:
        service.artifact(
            project_id,
            projection["run_id"],
            "../outside.fasta",
        )
    assert traversed.value.code == "artifact_not_found"


def test_artifact_retrieval_uses_durable_binding_after_package_removal(
    tmp_path: Path,
) -> None:
    service, project_id, projection, _ = _run_import_export(
        tmp_path,
        value_kind="sequence",
        payload=b">source\nACDEFG\n",
    )
    service.shutdown()
    catalog = builtin_frozen_catalog()
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    restarted = V2RunService(
        projects,
        catalog,
        WorkflowAuthoringService(projects, catalog),
        EnvironmentConfiguration({}),
    )
    artifact = projection["artifact_index"][0]

    descriptor, body = restarted.artifact(
        project_id,
        projection["run_id"],
        artifact["artifact_reference"],
    )
    restarted.shutdown()

    assert descriptor["media_type"] == "text/x-fasta"
    assert body == b">protein-workbench-sequence\nACDEFG\n"


def test_artifact_retrieval_rejects_media_outside_the_exact_output_port(
    tmp_path: Path,
) -> None:
    service, project_id, projection, _ = _run_import_export(
        tmp_path,
        value_kind="sequence",
        payload=b">source\nACDEFG\n",
    )
    record = service._runs[(project_id, projection["run_id"])]
    for fact in record.ledger._facts:
        if fact["fact_type"] != "outputs_published":
            continue
        for artifact in fact["payload"]["artifacts"]:
            artifact["media_type"] = "chemical/x-pdb"
    reference = projection["artifact_index"][0]["artifact_reference"]

    with pytest.raises(V2RunError) as rejected:
        service.artifact(project_id, projection["run_id"], reference)

    assert rejected.value.code == "artifact_integrity_mismatch"


def test_structure_export_preserves_the_validated_native_pdb_serialization(
    tmp_path: Path,
) -> None:
    native = (
        b"REMARK provider-native serialization\n"
        b"MODEL        7\n"
        b"ATOM      1  CA  GLY A   1      "
        b"1.000   2.000   3.000  1.00 20.00           C\n"
        b"ENDMDL\n"
        b"END\n"
    )
    service, project_id, projection, _ = _run_import_export(
        tmp_path,
        value_kind="structure",
        payload=native,
    )

    assert projection["status"] == "succeeded"
    artifact = projection["artifact_index"][0]
    assert artifact["artifact_kind"] == "standalone"
    assert artifact["output_port"] == "standalone_artifact"
    assert artifact["media_type"] == "chemical/x-pdb"
    _, body = service.artifact(
        project_id,
        projection["run_id"],
        artifact["artifact_reference"],
    )
    assert body == native


def test_fifteen_candidate_pdbs_keep_identity_slots_and_cache_rematerialize(
    tmp_path: Path,
) -> None:
    catalog = build_frozen_catalog(
        (PROTEIN_IO_PACKAGE, STRUCTURE_SOURCE_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("fifteen PDB artifact acceptance")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_candidates",
                node_type_version="2.1.0",
                binding_id="contract_test.structure_candidates.direct",
                binding_version="2.1.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="export",
                node_type_id="protein_io.export_structure",
                node_type_version="2.1.0",
                binding_id="protein_io.export_structure.direct",
                binding_version="2.1.0",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "structures", "export", "structures"),
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
        EnvironmentConfiguration({}),
    )

    projections = []
    event_sets = []
    for suffix in ("first", "replay"):
        receipt = service.start(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"fifteen-pdb-{suffix}",
        )
        projections.append(service.projection(project.id, receipt["run_id"]))
        event_sets.append(
            service.public_events(project.id, receipt["run_id"])
        )
    service.shutdown()

    candidate_port = catalog.require_port_type(
        "candidate.collection",
        "2.1.0",
    )
    first_candidates_output = next(
        output
        for output in projections[0]["outputs"]
        if output["output_port"] == "structures"
    )
    candidates = candidate_port.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": "candidate.collection",
                "port_type_version": "2.1.0",
                "value": first_candidates_output["values"][0],
            }
        )
    )
    expected_ids = [candidate.candidate_id for candidate in candidates.items]
    assert len(expected_ids) == len(set(expected_ids)) == 15
    for projection in projections:
        artifacts = projection["artifact_index"]
        assert len(artifacts) == 15
        assert [artifact["candidate_id"] for artifact in artifacts] == (
            expected_ids
        )
        assert all(
            artifact["artifact_kind"] == "candidate"
            and artifact["output_port"] == "candidate_artifacts"
            and artifact["media_type"] == "chemical/x-pdb"
            for artifact in artifacts
        )
        bodies = [
            service.artifact(
                project.id,
                projection["run_id"],
                artifact["artifact_reference"],
            )[1]
            for artifact in artifacts
        ]
        assert len(set(bodies)) == 15
        assert all(
            body.startswith(
                f"REMARK provider-native-{index:02d}\n".encode()
            )
            for index, body in enumerate(bodies)
        )
    assert {
        artifact["artifact_reference"]
        for artifact in projections[0]["artifact_index"]
    }.isdisjoint(
        {
            artifact["artifact_reference"]
            for artifact in projections[1]["artifact_index"]
        }
    )
    with pytest.raises(V2RunError) as cross_run:
        service.artifact(
            project.id,
            projections[1]["run_id"],
            projections[0]["artifact_index"][0]["artifact_reference"],
        )
    assert cross_run.value.code == "artifact_not_found"
    replay_types = {
        event["event"]["type"] for event in event_sets[1]
    }
    assert "engine_invocation_started" not in replay_types
    assert all(
        disposition["resolution"] == "cache_replayed"
        for disposition in projections[1]["node_dispositions"]
    )
