"""Public v2 contracts for the cohesive protein I/O Module Package."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ModulePackagePortCase,
    ProjectManager,
    V2RunError,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowAuthoringError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.storage import StoragePathError
from core.workflow_v2 import WorkflowEdge
from datatypes import ArtifactPayload, ProteinSequence, ProteinStructure
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.fixtures.protein_io_sources.package import (
    MODULE_PACKAGE as STRUCTURE_SOURCE_PACKAGE,
)


_SEQUENCE_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.protein_sequence",
    node_type_version="2.0.0",
    binding_id="contract_test.protein_sequence.direct",
    binding_version="2.0.0",
    node_parameters={},
    binding_parameters={},
)
_STRUCTURE_SOURCE = WorkflowNodeInstance(
    node_id="source",
    node_type_id="contract_test.protein_structure",
    node_type_version="2.0.0",
    binding_id="contract_test.protein_structure.direct",
    binding_version="2.0.0",
    node_parameters={},
    binding_parameters={},
)
_CTK_CASES = (
    ModulePackageContractCase(
        case_id="protein-io-import-sequence",
        node_type_id="protein_io.import_sequence",
        node_type_version="2.0.0",
        binding_id="protein_io.import_sequence.direct",
        binding_version="2.0.0",
        node_parameters={"project_input_ref": "sequence-input"},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-import-sequence-v1",
        project_inputs={"sequence-input": b">ctk\nACDEFG\n"},
    ),
    ModulePackageContractCase(
        case_id="protein-io-import-structure",
        node_type_id="protein_io.import_structure",
        node_type_version="2.0.0",
        binding_id="protein_io.import_structure.direct",
        binding_version="2.0.0",
        node_parameters={"project_input_ref": "structure-input"},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-import-structure-v1",
        project_inputs={
            "structure-input": (
                b"ATOM      1  CA  GLY A   1      "
                b"1.000   2.000   3.000  1.00 20.00           C\nEND\n"
            )
        },
    ),
    ModulePackageContractCase(
        case_id="protein-io-export-sequence",
        node_type_id="protein_io.export_sequence",
        node_type_version="2.0.0",
        binding_id="protein_io.export_sequence.direct",
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-export-sequence-v1",
        workflow_nodes=(_SEQUENCE_SOURCE,),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "sequence",
                "contract-test-node",
                "sequence",
            ),
        ),
        expected_artifacts={
            "standalone_artifact": (
                b">protein-workbench-sequence\nACDEFG\n"
            )
        },
    ),
    ModulePackageContractCase(
        case_id="protein-io-export-structure",
        node_type_id="protein_io.export_structure",
        node_type_version="2.0.0",
        binding_id="protein_io.export_structure.direct",
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
        environment_values={},
        safe_environment_fingerprint="protein-io-provider-free-v1",
        invalidation_token="protein-io-export-structure-v1",
        workflow_nodes=(_STRUCTURE_SOURCE,),
        workflow_edges=(
            WorkflowEdge(
                "source",
                "structure",
                "contract-test-node",
                "structure",
            ),
        ),
        expected_artifacts={
            "standalone_artifact": (
                b"REMARK contract-test-provider-native\n"
                b"ATOM      1  CA  GLY A   1      "
                b"1.000   2.000   3.000  1.00 20.00           C\n"
                b"END\n"
            )
        },
    ),
)
_CTK_PORT_CASE = ModulePackagePortCase(
    type_id="protein_io.artifact_payload",
    version="2.0.0",
    valid_value=ArtifactPayload(
        body=b">ctk\nACD\n",
        media_type="text/x-fasta",
        filename="ctk.fasta",
    ),
    invalid_values=(7,),
)


def test_protein_io_is_one_package_with_four_independent_nodes() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }

    registration = registrations["protein_io"]
    assert registration.package_module == "modules.protein_io"
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/sequence_import.yaml",
        "definitions/structure_import.yaml",
        "definitions/sequence_export.yaml",
        "definitions/structure_export.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    owned_nodes = {
        (contract_id, version)
        for kind, contract_id, version in catalog.owners
        if kind == "node_type"
        and "protein_io" in catalog.owners[(kind, contract_id, version)]
    }
    assert owned_nodes == {
        ("protein_io.import_sequence", "2.0.0"),
        ("protein_io.import_structure", "2.0.0"),
        ("protein_io.export_sequence", "2.0.0"),
        ("protein_io.export_structure", "2.0.0"),
    }


def test_protein_io_passes_the_shared_contract_test_kit(
    tmp_path: Path,
) -> None:
    report = verify_module_package_contract(
        PROTEIN_IO_PACKAGE,
        execution_cases=_CTK_CASES,
        port_cases=(_CTK_PORT_CASE,),
        supporting_registrations=(STRUCTURE_SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert report.package_id == "protein_io"
    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert {
        port
        for case in report.case_reports
        for port in case.artifact_ports
    } == {"standalone_artifact"}


def _run_single_node(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any],
    project_inputs: dict[str, bytes] | None = None,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_discovered_frozen_catalog()
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"protein I/O {operation}")
    for reference, payload in (project_inputs or {}).items():
        projects.publish_input(project.id, reference, payload)
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.0.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="protein-io",
                node_type_id=f"protein_io.{operation}",
                node_type_version="2.0.0",
                binding_id=f"protein_io.{operation}.direct",
                binding_version="2.0.0",
                node_parameters=node_parameters,
                binding_parameters={},
            ),
        ),
        edges=(),
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
    locked = parse_workflow_document(relocked["workflow"])
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=locked,
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
        client_request_id=f"protein-io-{operation}",
    )
    service.shutdown()
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    return (catalog, projection, events)


def test_sequence_import_reads_only_one_project_scoped_reference(
    tmp_path: Path,
) -> None:
    catalog, projection, events = _run_single_node(
        tmp_path,
        operation="import_sequence",
        node_parameters={"project_input_ref": "input-sequence-1"},
        project_inputs={
            "input-sequence-1": b">protein\r\nacD e\r\n",
        },
    )

    assert projection["status"] == "succeeded"
    output = projection["outputs"][0]
    port_type = catalog.require_port_type("protein.sequence", "2.0.0")
    sequence = port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": "protein.sequence",
                "port_type_version": "2.0.0",
                "value": output["values"][0],
            }
        )
    )
    assert sequence == ProteinSequence(sequence="ACDE")
    assert output["content_digest"] == port_type.content_digest(sequence)
    assert {
        event["event"]["type"] for event in events
    } >= {
        "engine_invocation_started",
        "engine_invocation_terminal",
    }
    assert not any(
        "input-sequence-1" in str(event.get("event"))
        for event in events
    )


def test_structure_import_validates_and_canonicalizes_project_pdb(
    tmp_path: Path,
) -> None:
    catalog, projection, _ = _run_single_node(
        tmp_path,
        operation="import_structure",
        node_parameters={"project_input_ref": "input-structure-1"},
        project_inputs={
            "input-structure-1": (
                b"ATOM      1  CA  GLY A   1      "
                b"1.000   2.000   3.000  1.00 20.00           C\r\n"
                b"END\r\n"
            ),
        },
    )

    assert projection["status"] == "succeeded"
    output = projection["outputs"][0]
    port_type = catalog.require_port_type("protein.structure", "2.0.0")
    structure = port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": "protein.structure",
                "port_type_version": "2.0.0",
                "value": output["values"][0],
            }
        )
    )
    assert structure == ProteinStructure(
        pdb_string=(
            "ATOM      1  CA  GLY A   1      "
            "1.000   2.000   3.000  1.00 20.00           C\n"
            "END\n"
        ),
        source="project_input",
    )
    assert output["content_digest"] == port_type.content_digest(structure)


@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        ("import_sequence", b">empty\n"),
        ("import_sequence", b">invalid\nACD?\n"),
        ("import_structure", b"HEADER no atoms\nEND\n"),
        (
            "import_structure",
            b"ATOM      X malformed coordinate record\nEND\n",
        ),
    ),
)
def test_import_fails_closed_for_malformed_sequence_or_structure(
    tmp_path: Path,
    operation: str,
    payload: bytes,
) -> None:
    _, projection, events = _run_single_node(
        tmp_path,
        operation=operation,
        node_parameters={"project_input_ref": "malformed-input"},
        project_inputs={"malformed-input": payload},
    )

    assert projection["status"] == "failed"
    assert projection["outputs"] == []
    assert projection["artifact_index"] == []
    assert not any(
        str(tmp_path) in str(event)
        or "malformed-input" in str(event.get("event"))
        for event in events
    )


def test_import_rejects_private_paths_and_cross_project_references(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        WorkflowAuthoringError,
        match="parameter values do not match",
    ) as rejected:
        _run_single_node(
            tmp_path / "private-path",
            operation="import_sequence",
            node_parameters={
                "project_input_ref": "/private/host/sequence.fasta"
            },
        )
    assert rejected.value.code == "compile_rejected"

    _, projection, _ = _run_single_node(
        tmp_path / "cross-project",
        operation="import_sequence",
        node_parameters={"project_input_ref": "belongs-to-another-project"},
    )
    assert projection["status"] == "failed"
    assert projection["outputs"] == []


def test_project_input_snapshot_rejects_symlink_aliases(
    tmp_path: Path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("input symlink containment")
    projects.publish_input(project.id, "trusted-input", b">p\nACD\n")
    managed = projects.input_path(project.id, "trusted-input")
    managed.unlink()
    outside = tmp_path / "outside.fasta"
    outside.write_bytes(b">outside\nW\n")
    managed.symlink_to(outside)

    with pytest.raises((OSError, StoragePathError)):
        projects.read_input(project.id, "trusted-input")


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
            node_type_version="2.0.0",
            binding_id=f"protein_io.{role}_{value_kind}.direct",
            binding_version="2.0.0",
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
        schema_version="2.0.0",
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
        "sequence"
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
        schema_version="2.0.0",
        workflow_id=project.id,
        nodes=(
            WorkflowNodeInstance(
                node_id="source",
                node_type_id="contract_test.structure_candidates",
                node_type_version="2.0.0",
                binding_id="contract_test.structure_candidates.direct",
                binding_version="2.0.0",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="export",
                node_type_id="protein_io.export_structure",
                node_type_version="2.0.0",
                binding_id="protein_io.export_structure.direct",
                binding_version="2.0.0",
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
        "2.0.0",
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
                "port_type_version": "2.0.0",
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
