"""Run-bound artifact acceptance for the protein I/O Module Package."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

from protein_workbench_public.bootstrap import module_registrations

import hashlib
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import (
    V2RunError,
    V2RunService,
)
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from tests.support.application import create_application
from core.project.objects import ProjectObjectStore
from core.workflow.document import WorkflowEdge
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from protein_workbench_public.protocol import artifact_content_disposition
from tests.fixtures.protein_io_sources.package import (
    MODULE_PACKAGE as STRUCTURE_SOURCE_PACKAGE,
)


def _run_import_export(
    tmp_path: Path,
    *,
    value_kind: str,
    payload: bytes,
) -> tuple[V2RunService, str, dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog(module_registrations())
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"protein I/O {value_kind} round trip")
    projects.publish_input(
        project.id,
        f"{value_kind}-input",
        payload,
        filename=f"{value_kind}-input",
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    nodes = tuple(
        WorkflowNodeInstance(
            node_id=role,
            node_type_id=f"protein_io.{role}_{value_kind}",
            binding_id=f"protein_io.{role}_{value_kind}.direct",
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
        ))
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    compiled = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(catalog, {}),
            result_store(projects),
        ),
        result_store(projects),
    )
    receipt = service.start_background(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id=f"protein-io-{value_kind}-round-trip",
    )
    service.shutdown()
    return (
        service,
        project.id,
        public_run_projection(service, project.id, receipt["run_id"]),
        public_run_events(service, project.id, receipt["run_id"]),
    )


def _artifact_object_path(
    output_root: Path,
    project_id: str,
    artifact: dict[str, Any],
) -> Path:
    return (
        output_root
        / project_id
        / "objects"
        / Path(*ProjectObjectStore._relative_parts(artifact["content_digest"]))
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
    assert all(
        "artifact_kind" not in output for output in projection["outputs"]
    )
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


@pytest.mark.parametrize(
    "filename",
    (
        '来源结构 "alpha".pdb',
        "蛋" * 512,
    ),
)
def test_artifact_route_returns_exact_utf8_filename_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    body = b"MODEL        1\nEND\n"
    descriptor = {
        "artifact_reference": "artifact_1",
        "artifact_kind": "standalone",
        "node_id": "export",
        "output_port": "structure",
        "media_type": "chemical/x-pdb",
        "filename": filename,
        "size": len(body),
        "content_digest": f"sha256:{hashlib.sha256(body).hexdigest()}",
    }
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(
        create_application(
            frozen_catalog_override=builtin_frozen_catalog(),
        )
    ) as client:
        service = client.app.state.run_runtime
        monkeypatch.setattr(
            service,
            "artifact",
            lambda project_id, run_id, artifact_reference: (
                descriptor,
                body,
            ),
        )
        response = client.get(
            "/api/v2/projects/project-1/runs/run-1/artifacts/artifact_1"
        )

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-disposition"] == (
        artifact_content_disposition(filename)
    )


def test_structure_export_preserves_the_validated_native_pdb_serialization(
    tmp_path: Path,
) -> None:
    native = (
        b"REMARK provider-native serialization\n"
        b"MODEL        7\n"
        b"ATOM      1  CA  GLY A   1       "
        b"1.000   2.000   3.000  1.00 20.00           C  \n"
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
                binding_id="contract_test.structure_candidates.direct",
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="export",
                node_type_id="protein_io.export_structure",
                binding_id="protein_io.export_structure.direct",
                node_parameters={},
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge("source", "structures", "export", "structures"),
        ))
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    compiled = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(catalog, {}),
            result_store(projects),
        ),
        result_store(projects),
    )

    projections = []
    event_sets = []
    for suffix in ("first", "replay"):
        receipt = service.start(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"fifteen-pdb-{suffix}",
        )
        projections.append(
            public_run_projection(service, project.id, receipt["run_id"])
        )
        event_sets.append(
            public_run_events(service, project.id, receipt["run_id"])
        )
    service.shutdown()

    from tests.fixtures.public_v2 import decode_service_typed_output_value

    first_candidates_output = next(
        output
        for output in projections[0]["outputs"]
        if output["output_port"] == "structures"
    )
    candidates = decode_service_typed_output_value(
        service,
        catalog,
        projections[0],
        first_candidates_output,
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
        assert [artifact["filename"] for artifact in artifacts] == [
            f"structure-{index:04d}.pdb" for index in range(15)
        ]
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
    assert [
        artifact["content_digest"]
        for artifact in projections[0]["artifact_index"]
    ] == [
        artifact["content_digest"]
        for artifact in projections[1]["artifact_index"]
    ]
    assert not list((tmp_path / "outputs").rglob("published/*"))
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
