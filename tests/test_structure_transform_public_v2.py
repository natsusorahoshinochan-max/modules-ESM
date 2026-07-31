"""Installed public-protocol import-transform-export acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from core.server import create_app
from protein_workbench_public import (
    prepare_rest_request,
    validate_artifact_response,
    validate_response,
)
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal


VERSION = "2.1.0"
_MULTI_CHAIN_PDB = (
    b"REMARK uploaded-label\n"
    b"ATOM      1  N   ALA A   1       1.000   2.000   3.000"
    b"  1.00 20.00           N\n"
    b"ATOM      2  CA  ALA A   1       2.000   2.000   3.000"
    b"  1.00 20.00           C\n"
    b"ATOM      3  C   ALA A   1       3.000   2.000   3.000"
    b"  1.00 20.00           C\n"
    b"ATOM      4  O   ALA A   1       4.000   2.000   3.000"
    b"  1.00 20.00           O\n"
    b"ATOM      5  CB  ALA A   1       5.000   2.000   3.000"
    b"  1.00 20.00           C\n"
    b"TER\n"
    b"ATOM      6  N   GLY B   2       6.000   2.000   3.000"
    b"  1.00 20.00           N\n"
    b"ATOM      7  CA  GLY B   2       7.000   2.000   3.000"
    b"  1.00 20.00           C\n"
    b"ATOM      8  C   GLY B   2       8.000   2.000   3.000"
    b"  1.00 20.00           C\n"
    b"ATOM      9  O   GLY B   2       9.000   2.000   3.000"
    b"  1.00 20.00           O\n"
    b"TER\nEND\n"
)


def test_public_import_transform_export_keeps_artifacts_run_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))

    with TestClient(create_app()) as client:
        def public_request(
            operation_id: str,
            request: dict[str, Any],
            expected_status: int,
        ):
            prepared = prepare_rest_request(operation_id, request)
            response = client.request(
                prepared.method,
                prepared.route,
                json=prepared.json_body,
            )
            assert response.status_code == expected_status
            validate_response(operation_id, expected_status, response.json())
            return response

        catalog = public_request("catalog_snapshot", {}, 200).json()
        assert {
            contract["reference"]["contract_id"]
            for contract in catalog["contracts"]
            if contract["reference"]["contract_kind"] == "node_type"
        } >= {
            "structure_transform.select_chains",
            "structure_transform.extract_backbone",
            "structure_transform.extract_sequence",
            "structure_transform.backbone_to_structure",
        }
        project_id = client.post(
            "/api/projects",
            json={"name": "structure transform public journey"},
        ).json()["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/inputs",
            files={
                "file": (
                    "source.pdb",
                    _MULTI_CHAIN_PDB,
                    "chemical/x-pdb",
                )
            },
        )
        assert uploaded.status_code == 200
        project_input_ref = uploaded.json()["project_input_ref"]
        assert "/" not in project_input_ref
        assert "path" not in uploaded.json()

        nodes = [
            {
                "node_id": "import",
                "node_type_id": "protein_io.import_structure",
                "node_type_version": VERSION,
                "binding_id": "protein_io.import_structure.direct",
                "binding_version": VERSION,
                "node_parameters": {
                    "project_input_ref": project_input_ref,
                },
                "binding_parameters": {},
            },
            {
                "node_id": "select",
                "node_type_id": "structure_transform.select_chains",
                "node_type_version": VERSION,
                "binding_id": "structure_transform.select_chains.direct",
                "binding_version": VERSION,
                "node_parameters": {"chain_ids": ["A"]},
                "binding_parameters": {},
            },
            {
                "node_id": "extract-backbone",
                "node_type_id": "structure_transform.extract_backbone",
                "node_type_version": VERSION,
                "binding_id": "structure_transform.extract_backbone.direct",
                "binding_version": VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "backbone-to-structure",
                "node_type_id": (
                    "structure_transform.backbone_to_structure"
                ),
                "node_type_version": VERSION,
                "binding_id": (
                    "structure_transform.backbone_to_structure.direct"
                ),
                "binding_version": VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "extract-sequence",
                "node_type_id": "structure_transform.extract_sequence",
                "node_type_version": VERSION,
                "binding_id": "structure_transform.extract_sequence.direct",
                "binding_version": VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "export-backbone",
                "node_type_id": "protein_io.export_structure",
                "node_type_version": VERSION,
                "binding_id": "protein_io.export_structure.direct",
                "binding_version": VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "export-structure",
                "node_type_id": "protein_io.export_structure",
                "node_type_version": VERSION,
                "binding_id": "protein_io.export_structure.direct",
                "binding_version": VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "export-sequence",
                "node_type_id": "protein_io.export_sequence",
                "node_type_version": VERSION,
                "binding_id": "protein_io.export_sequence.direct",
                "binding_version": VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
        ]
        edges = [
            {
                "source_node_id": "import",
                "source_port": "structure",
                "target_node_id": "select",
                "target_port": "structure",
            },
            {
                "source_node_id": "select",
                "source_port": "structure",
                "target_node_id": "extract-backbone",
                "target_port": "structure",
            },
            {
                "source_node_id": "select",
                "source_port": "structure",
                "target_node_id": "extract-sequence",
                "target_port": "structure",
            },
            {
                "source_node_id": "extract-backbone",
                "source_port": "backbone",
                "target_node_id": "backbone-to-structure",
                "target_port": "backbone",
            },
            {
                "source_node_id": "backbone-to-structure",
                "source_port": "structure",
                "target_node_id": "export-backbone",
                "target_port": "structure",
            },
            {
                "source_node_id": "select",
                "source_port": "structure",
                "target_node_id": "export-structure",
                "target_port": "structure",
            },
            {
                "source_node_id": "extract-sequence",
                "source_port": "sequence",
                "target_node_id": "export-sequence",
                "target_port": "sequence",
            },
        ]
        workflow = {
            "schema_version": VERSION,
            "workflow_id": project_id,
            "nodes": nodes,
            "edges": edges,
            "contract_lock": [],
        }
        saved = public_request(
            "save_project_workflow",
            {
                "project_id": project_id,
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
            200,
        ).json()
        relocked = public_request(
            "relock_project_workflow",
            {
                "project_id": project_id,
                "workflow_revision": saved["workflow_revision"],
            },
            200,
        ).json()
        compiled = public_request(
            "workflow_compile",
            {
                "project_id": project_id,
                "workflow_revision": relocked["workflow_revision"],
                "workflow": relocked["workflow"],
            },
            200,
        ).json()
        started = public_request(
            "start_run",
            {
                "project_id": project_id,
                "workflow_revision": relocked["workflow_revision"],
                "compile_id": compiled["compile_id"],
                "client_request_id": "structure-transform-public",
            },
            202,
        ).json()
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started["run_id"],
        )

        assert projection["status"] == "succeeded"
        artifacts = projection["artifact_index"]
        assert len(artifacts) == 3
        bodies: dict[str, bytes] = {}
        for artifact in artifacts:
            assert artifact["artifact_kind"] == "standalone"
            assert "/" not in artifact["artifact_reference"]
            prepared = prepare_rest_request(
                "artifact_retrieval",
                {
                    "project_id": project_id,
                    "run_id": started["run_id"],
                    "artifact_reference": artifact["artifact_reference"],
                },
            )
            retrieved = client.request(prepared.method, prepared.route)
            assert retrieved.status_code == 200
            validate_artifact_response(
                {
                    "artifact": artifact,
                    "content_disposition": retrieved.headers[
                        "content-disposition"
                    ],
                },
                retrieved.headers,
                retrieved.content,
            )
            bodies[artifact["node_id"]] = retrieved.content

    assert bodies["export-sequence"] == (
        b">protein-workbench-sequence\nA\n"
    )
    assert bodies["export-structure"].startswith(
        b"ATOM      1  N   ALA A   1"
    )
    assert bodies["export-structure"].endswith(b"TER\nEND\n")
    backbone_lines = bodies["export-backbone"].decode("ascii").splitlines()
    assert [
        line[12:16].strip()
        for line in backbone_lines
        if line.startswith("ATOM  ")
    ] == ["N", "CA", "C", "O"]
    assert backbone_lines[-2:] == ["TER", "END"]
    retained = str(projection)
    assert str(tmp_path) not in retained
    assert "private_path" not in retained
    assert all(
        output["result_identity"].startswith("sha256:")
        and output["content_digest"].startswith("sha256:")
        for output in projection["outputs"]
    )
