"""Public REST contracts for run recovery, artifacts, and Cache operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import threading
import time

from fastapi.testclient import TestClient

import core.server as server
from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.server import create_app
from core.workflow_module import WorkflowModule
from datatypes import Candidate, CandidateCollection, ProteinStructure


class RecoveryArtifactModule(WorkflowModule):
    """Fixture Module that publishes one Candidate-bound run artifact."""

    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition.from_yaml_string(
            """
module_id: test.recovery_artifact
version: 1.0.0
display_name: Recovery artifact
category: output
output_ports:
  - name: structures
    type_id: protein.structure.collection
  - name: file_path
    type_id: file.path
"""
        )

    def run(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        del inputs, parameters
        candidate_id = f"candidate-{context.seed}"
        content = f"MODEL {context.seed}\n"
        artifact = context.output_path(f"models/{candidate_id}.pdb")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(content)
        context.record_artifact(
            artifact,
            candidate_id=candidate_id,
            output_port="structures",
        )
        return {
            "structures": CandidateCollection(
                collection_id=f"collection-{context.seed}",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id=candidate_id,
                        data=ProteinStructure(content),
                    )
                ],
            ),
            "file_path": str(artifact),
        }


class RecoverySeedModule(WorkflowModule):
    """Deterministic seeded Module for dependency-aware recovery."""

    uses_seed = True

    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition.from_yaml_string(
            """
module_id: test.recovery_seed
version: 1.0.0
display_name: Recovery seed
category: conversion
input_ports:
  - name: text
    type_id: text
    required: false
output_ports:
  - name: text
    type_id: text
parameters:
  - name: label
    type: str
    default: ""
"""
        )

    def run(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        return {
            "text": (
                f"{inputs.get('text', '')}|"
                f"{parameters.get('label', '')}|{context.seed}"
            )
        }


class BlockingRecoveryModule(WorkflowModule):
    """Controllable fixture for active-run Cache exclusion."""

    started: Path
    release: Path

    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition.from_yaml_string(
            """
module_id: test.recovery_blocking
version: 1.0.0
display_name: Recovery blocking
category: model
output_ports:
  - name: text
    type_id: text
parameters:
  - name: started_path
    type: str
  - name: release_path
    type: str
"""
        )

    def run(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        del inputs, context
        started = Path(str(parameters["started_path"]))
        release = Path(str(parameters["release_path"]))
        started.touch()
        deadline = time.monotonic() + 5
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        return {"text": "released"}


def _isolated_app(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_CACHE_ROOT",
        str(tmp_path / "cache"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_RUN_ROOT",
        str(tmp_path / "runs"),
    )
    return create_app()


def _saved_echo_project(client: TestClient, name: str = "Recovery") -> str:
    project_id = client.post(
        "/api/projects",
        json={"name": name},
    ).json()["id"]
    response = client.put(
        f"/api/projects/{project_id}/workflow",
        json={
            "nodes": [
                {
                    "node_id": "echo",
                    "module_id": "stub.echo",
                    "module_version": "1.0.0",
                    "parameters": {"prefix": name},
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 200
    return project_id


def _finish_run(
    client: TestClient,
    project_id: str,
    *,
    seed: int,
) -> str:
    response = client.post(
        f"/api/projects/{project_id}/run",
        json={"seed": seed},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    _await_run(client, project_id, run_id)
    return run_id


def _await_run(
    client: TestClient,
    project_id: str,
    run_id: str,
) -> None:
    with client.websocket_connect(
        f"/api/projects/{project_id}/run/{run_id}/ws"
    ) as websocket:
        while True:
            event = websocket.receive_json()
            if event["type"] in {
                "run_completed",
                "run_failed",
                "run_cancelled",
            }:
                assert event["type"] == "run_completed"
                break


def test_status_and_manifest_are_retrieved_by_explicit_project_and_run(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client)
        first_run = _finish_run(client, project_id, seed=17)
        second_run = _finish_run(client, project_id, seed=29)

        first_status = client.get(
            f"/api/projects/{project_id}/run/{first_run}/status"
        )
        first_manifest = client.get(
            f"/api/projects/{project_id}/run/{first_run}/manifest"
        )

    assert first_run != second_run
    assert first_status.status_code == 200
    assert first_status.json()["project_id"] == project_id
    assert first_status.json()["run_id"] == first_run
    assert first_status.json()["status"] == "completed"
    assert first_manifest.status_code == 200
    assert first_manifest.json()["project_id"] == project_id
    assert first_manifest.json()["run_id"] == first_run
    assert first_manifest.json()["status"] == "completed"


def test_outputs_preserve_candidate_artifact_mapping_and_verified_reference(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        module = RecoveryArtifactModule()
        server.module_registry.register(module.definition)
        server.register_module_factory(
            module.definition.module_id,
            RecoveryArtifactModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "Artifact retrieval"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [
                    {
                        "node_id": "export",
                        "module_id": module.definition.module_id,
                        "module_version": module.definition.version,
                    }
                ],
                "edges": [],
            },
        ).status_code == 200
        first_run = _finish_run(client, project_id, seed=17)
        second_run = _finish_run(client, project_id, seed=29)

        response = client.get(
            f"/api/projects/{project_id}/run/{first_run}/outputs"
        )
        artifact = client.get(
            f"/api/projects/{project_id}/run/{first_run}"
            "/artifacts/models/candidate-17.pdb"
        )
        unscoped_node_output = client.get(
            f"/api/projects/{project_id}/nodes/export/output"
        )
        scoped_node_output = client.get(
            f"/api/projects/{project_id}/nodes/export/output",
            params={"run_id": first_run},
        )
        compatibility_download = client.get(
            f"/api/projects/{project_id}/outputs/{first_run}"
            "/models/candidate-17.pdb"
        )

    assert first_run != second_run
    assert response.status_code == 200
    assert response.json() == {
        "project_id": project_id,
        "run_id": first_run,
        "status": "completed",
        "artifacts": [
            {
                "node_id": "export",
                "output_port": "structures",
                "candidate_id": "candidate-17",
                "reference": "models/candidate-17.pdb",
                "size": 9,
                "sha256": (
                    "fc82576c00f39202a4be25640ee55236"
                    "f1a663606583db31d9d58b8cc427b6fa"
                ),
            }
        ],
    }
    assert artifact.status_code == 200
    assert artifact.content == b"MODEL 17\n"
    assert unscoped_node_output.status_code == 422
    assert unscoped_node_output.json()["error"]["kind"] == (
        "run_scope_required"
    )
    assert scoped_node_output.status_code == 200
    assert scoped_node_output.json()["run_id"] == first_run
    assert scoped_node_output.json()["artifacts"] == (
        response.json()["artifacts"]
    )
    assert compatibility_download.status_code == 200
    assert compatibility_download.content == b"MODEL 17\n"


def test_outputs_reject_manifest_artifacts_without_candidate_port_mapping(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Incomplete artifact")
        run_id = _finish_run(client, project_id, seed=17)
        output_dir = server.project_manager.output_dir(project_id, run_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / "unbound.pdb"
        artifact.write_bytes(b"MODEL\n")
        manifest_path = (
            server.project_manager.run_dir(project_id, run_id)
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text())
        manifest["artifacts"] = [{
            "node_id": "echo",
            "reference": "unbound.pdb",
            "size": 6,
            "sha256": hashlib.sha256(b"MODEL\n").hexdigest(),
        }]
        manifest_path.write_text(json.dumps(manifest))

        response = client.get(
            f"/api/projects/{project_id}/run/{run_id}/outputs"
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "invalid_run_manifest"


def test_outputs_reject_oversized_artifacts_before_opening_them(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Oversized artifact")
        run_id = _finish_run(client, project_id, seed=17)
        manifest_path = (
            server.project_manager.run_dir(project_id, run_id)
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text())
        manifest["artifacts"] = [{
            "node_id": "echo",
            "output_port": "structures",
            "candidate_id": "candidate-17",
            "reference": "missing-large.pdb",
            "size": 64 * 1024 * 1024 + 1,
            "sha256": "0" * 64,
        }]
        manifest_path.write_text(json.dumps(manifest))

        response = client.get(
            f"/api/projects/{project_id}/run/{run_id}/outputs"
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "artifact_limit_exceeded"


def test_retry_and_force_rerun_use_documented_dependency_cache_semantics(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        module = RecoverySeedModule()
        server.module_registry.register(module.definition)
        server.register_module_factory(
            module.definition.module_id,
            RecoverySeedModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "Dependency recovery"},
        ).json()["id"]
        nodes = [
            {
                "node_id": node_id,
                "module_id": module.definition.module_id,
                "module_version": module.definition.version,
                "parameters": {"label": node_id},
            }
            for node_id in ("source", "selected", "downstream", "unrelated")
        ]
        edges = [
            {
                "source_node_id": "source",
                "source_port": "text",
                "target_node_id": "selected",
                "target_port": "text",
            },
            {
                "source_node_id": "selected",
                "source_port": "text",
                "target_node_id": "downstream",
                "target_port": "text",
            },
        ]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={"nodes": nodes, "edges": edges},
        ).status_code == 200
        source_run = _finish_run(client, project_id, seed=73)

        retry = client.post(
            f"/api/projects/{project_id}/run/{source_run}"
            "/nodes/selected/retry"
        )
        assert retry.status_code == 200
        retry_run = retry.json()["run_id"]
        _await_run(client, project_id, retry_run)
        retry_manifest = client.get(
            f"/api/projects/{project_id}/run/{retry_run}/manifest"
        ).json()

        forced = client.post(
            f"/api/projects/{project_id}/run/{retry_run}"
            "/nodes/selected/force-rerun"
        )
        assert forced.status_code == 200
        forced_run = forced.json()["run_id"]
        _await_run(client, project_id, forced_run)
        forced_manifest = client.get(
            f"/api/projects/{project_id}/run/{forced_run}/manifest"
        ).json()

    assert retry_manifest["recovery"] == {
        "source_run_id": source_run,
        "action": "retry",
        "selected_node_id": "selected",
        "forced_node_ids": ["selected"],
        "dependency_semantics": {
            "ancestors": "cache_eligible",
            "selected": "cache_bypassed",
            "descendants": "cache_eligible",
            "unrelated": "cache_eligible",
        },
    }
    assert {
        event["node_id"]: event["outcome"]
        for event in retry_manifest["cache"]
    } == {
        "source": "hit",
        "selected": "bypass",
        "downstream": "hit",
        "unrelated": "hit",
    }
    assert retry_manifest["effective_seeds"] == {
        "downstream": 73,
        "selected": 73,
        "source": 73,
        "unrelated": 73,
    }
    assert forced_manifest["recovery"] == {
        "source_run_id": retry_run,
        "action": "force_rerun",
        "selected_node_id": "selected",
        "forced_node_ids": ["selected", "downstream"],
        "dependency_semantics": {
            "ancestors": "cache_eligible",
            "selected": "cache_bypassed",
            "descendants": "cache_bypassed",
            "unrelated": "cache_eligible",
        },
    }
    assert {
        event["node_id"]: event["outcome"]
        for event in forced_manifest["cache"]
    } == {
        "source": "hit",
        "selected": "bypass",
        "downstream": "bypass",
        "unrelated": "hit",
    }
    assert {
        event["node_id"]: event["state"]
        for event in forced_manifest["node_states"]
        if event["state"] in {
            "completed",
            "failed",
            "blocked",
            "cancelled",
        }
    } == {
        "source": "completed",
        "selected": "completed",
        "downstream": "completed",
        "unrelated": "completed",
    }


def test_cache_entries_are_listed_and_cleared_at_node_or_project_scope(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Cache API")
        other_project = _saved_echo_project(client, "Other Cache")
        _finish_run(client, project_id, seed=41)
        _finish_run(client, other_project, seed=41)

        project_cache = client.get(
            f"/api/projects/{project_id}/cache"
        )
        node_cache = client.get(
            f"/api/projects/{project_id}/cache/echo"
        )

        node_clear = client.delete(
            f"/api/projects/{project_id}/cache/echo"
        )
        empty_node_cache = client.get(
            f"/api/projects/{project_id}/cache/echo"
        )

        _finish_run(client, project_id, seed=41)
        project_clear = client.delete(
            f"/api/projects/{project_id}/cache"
        )
        empty_project_cache = client.get(
            f"/api/projects/{project_id}/cache"
        )
        other_project_cache = client.get(
            f"/api/projects/{other_project}/cache"
        )

    assert project_cache.status_code == 200
    assert node_cache.status_code == 200
    assert len(project_cache.json()["entries"]) == 1
    entry = project_cache.json()["entries"][0]
    assert entry["node_id"] == "echo"
    assert len(entry["cache_key"]) == 32
    assert entry["module_id"] == "stub.echo"
    assert entry["module_version"] == "1.0.0"
    assert entry["output_ports"] == [{"name": "text", "type_id": "text"}]
    assert entry["size"] > 0
    assert node_cache.json() == {
        "project_id": project_id,
        "node_id": "echo",
        "entries": [entry],
    }
    assert node_clear.json() == {
        "project_id": project_id,
        "node_id": "echo",
        "status": "cleared",
        "removed": 1,
    }
    assert empty_node_cache.json()["entries"] == []
    assert project_clear.json() == {
        "project_id": project_id,
        "status": "cleared",
        "removed": 1,
    }
    assert empty_project_cache.json()["entries"] == []
    assert len(other_project_cache.json()["entries"]) == 1
    assert other_project_cache.json()["project_id"] == other_project


def test_project_cache_operations_preserve_unrelated_root_files(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Unrelated Cache file")
        _finish_run(client, project_id, seed=41)
        cache_root = server.project_manager.cache_dir(project_id)
        unrelated = cache_root / "notes"
        unrelated.write_text("preserve me")

        listed = client.get(f"/api/projects/{project_id}/cache")
        cleared = client.delete(f"/api/projects/{project_id}/cache")

    assert listed.status_code == 200
    assert len(listed.json()["entries"]) == 1
    assert cleared.status_code == 200
    assert cleared.json()["removed"] == 1
    assert unrelated.read_text() == "preserve me"


def test_cache_listing_ignores_authenticated_non_object_headers(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Malformed Cache header")
        cache_root = server.project_manager.cache_dir(project_id)
        poison_dir = cache_root / "poison"
        poison_dir.mkdir(mode=0o700, parents=True)
        cache_root.chmod(0o700)
        key_path = cache_root / ".integrity-key"
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = b"k" * 32
            key_path.write_bytes(key)
            key_path.chmod(0o600)
        header = b"[]"
        payload = b""
        encoded = (
            b"PWB-CACHE-1\n"
            + len(header).to_bytes(8, "big")
            + header
            + hmac.digest(key, header + payload, "sha256")
            + payload
        )
        poison = poison_dir / "poison.pkl"
        poison.write_bytes(encoded)
        poison.chmod(0o600)

        response = client.get(f"/api/projects/{project_id}/cache")

    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_cache_listing_ignores_authenticated_recursive_headers(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Recursive Cache header")
        cache_root = server.project_manager.cache_dir(project_id)
        poison_dir = cache_root / "poison"
        poison_dir.mkdir(mode=0o700, parents=True)
        cache_root.chmod(0o700)
        key_path = cache_root / ".integrity-key"
        key = b"k" * 32
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        header = b"[" * 10000 + b"0" + b"]" * 10000
        encoded = (
            b"PWB-CACHE-1\n"
            + len(header).to_bytes(8, "big")
            + header
            + hmac.digest(key, header, "sha256")
        )
        poison = poison_dir / "poison.pkl"
        poison.write_bytes(encoded)
        poison.chmod(0o600)

        response = client.get(f"/api/projects/{project_id}/cache")

    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_recovery_apis_reject_unknown_cross_scoped_and_traversal_requests(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Scoped")
        other_project = _saved_echo_project(client, "Other")
        run_id = _finish_run(client, project_id, seed=43)

        unknown_project = client.get(
            f"/api/projects/unknown-project/run/{run_id}/status"
        )
        unknown_run = client.get(
            f"/api/projects/{project_id}/run/unknown-run/status"
        )
        cross_scoped = client.get(
            f"/api/projects/{other_project}/run/{run_id}/manifest"
        )
        unknown_node = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/unknown-node/retry"
        )
        unknown_cache_node = client.get(
            f"/api/projects/{project_id}/cache/unknown-node"
        )
        undeclared_artifact = client.get(
            f"/api/projects/{project_id}/run/{run_id}"
            "/artifacts/not-declared.pdb"
        )
        traversal_artifact = client.get(
            f"/api/projects/{project_id}/run/{run_id}"
            "/artifacts/%2E%2E%2Foutside.pdb"
        )

        workflow = client.get(
            f"/api/projects/{project_id}/workflow"
        ).json()
        workflow["nodes"][0]["parameters"]["prefix"] = "changed"
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json=workflow,
        ).status_code == 200
        mismatched_workflow = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/echo/retry"
        )

    assert unknown_project.status_code == 404
    assert unknown_project.json()["error"]["kind"] == "project_not_found"
    assert unknown_run.status_code == 404
    assert unknown_run.json()["error"]["kind"] == "run_not_found"
    assert cross_scoped.status_code == 404
    assert cross_scoped.json()["error"]["kind"] == "run_not_found"
    assert unknown_node.status_code == 404
    assert unknown_node.json()["error"]["kind"] == "node_not_found"
    assert unknown_cache_node.status_code == 404
    assert unknown_cache_node.json()["error"]["kind"] == "node_not_found"
    assert undeclared_artifact.status_code == 404
    assert undeclared_artifact.json()["error"]["kind"] == (
        "artifact_not_found"
    )
    assert traversal_artifact.status_code == 422
    assert traversal_artifact.json()["error"] == {
        "kind": "invalid_storage_path",
        "field": "artifact_reference",
        "message": "Invalid artifact_reference",
    }
    assert mismatched_workflow.status_code == 409
    assert mismatched_workflow.json()["error"]["kind"] == (
        "workflow_mismatch"
    )


def test_recovery_rejects_stale_workflow_before_current_validation(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Invalid stale Workflow")
        run_id = _finish_run(client, project_id, seed=43)
        workflow = client.get(
            f"/api/projects/{project_id}/workflow"
        ).json()
        workflow["nodes"][0]["parameters"]["prefix"] = "changed"
        workflow["edges"] = [{
            "source_node_id": "echo",
            "source_port": "missing",
            "target_node_id": "echo",
            "target_port": "missing",
        }]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json=workflow,
        ).status_code == 200

        response = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/echo/retry"
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "workflow_mismatch"


def test_recovery_rejects_invalid_bodies_without_echoing_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Safe recovery body")
        run_id = _finish_run(client, project_id, seed=43)
        malformed = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/echo/retry",
            json=[{"password": "TOPSECRET"}],
        )
        null_seed = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/echo/retry",
            json={"seed": None},
        )

    assert malformed.status_code == 422
    assert malformed.json()["error"]["kind"] == "invalid_recovery_request"
    assert "TOPSECRET" not in malformed.text
    assert null_seed.status_code == 422
    assert null_seed.json()["error"]["kind"] == "invalid_recovery_seed"


def test_recovery_uses_structured_errors_for_invalid_json_and_workflow(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Malformed recovery")
        run_id = _finish_run(client, project_id, seed=43)
        invalid_json = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/echo/retry",
            content=b'{"seed":',
            headers={"content-type": "application/json"},
        )
        workflow_path = (
            server.project_manager.project_dir(project_id)
            / "workflow.json"
        )
        workflow_path.write_text("[]")
        invalid_workflow = client.post(
            f"/api/projects/{project_id}/run/{run_id}"
            "/nodes/echo/retry"
        )

    assert invalid_json.status_code == 422
    assert invalid_json.json() == {
        "error": {
            "kind": "invalid_request_body",
            "message": "Request body is invalid",
        }
    }
    assert invalid_workflow.status_code == 409
    assert invalid_workflow.json()["error"]["kind"] == "invalid_workflow"


def test_artifact_api_refuses_content_that_no_longer_matches_the_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        module = RecoveryArtifactModule()
        server.module_registry.register(module.definition)
        server.register_module_factory(
            module.definition.module_id,
            RecoveryArtifactModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "Tampered artifact"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [
                    {
                        "node_id": "export",
                        "module_id": module.definition.module_id,
                        "module_version": module.definition.version,
                    }
                ],
                "edges": [],
            },
        ).status_code == 200
        run_id = _finish_run(client, project_id, seed=17)
        server.project_manager.output_path(
            project_id,
            run_id,
            "models/candidate-17.pdb",
        ).write_text("TAMPERED\n")

        response = client.get(
            f"/api/projects/{project_id}/run/{run_id}/outputs"
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "kind": "artifact_integrity_mismatch",
            "message": "Artifact does not match its run manifest",
            "reference": "models/candidate-17.pdb",
        }
    }


def test_artifact_api_refuses_hardlinked_files(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        module = RecoveryArtifactModule()
        server.module_registry.register(module.definition)
        server.register_module_factory(
            module.definition.module_id,
            RecoveryArtifactModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "Hardlinked artifact"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [{
                    "node_id": "export",
                    "module_id": module.definition.module_id,
                    "module_version": module.definition.version,
                }],
                "edges": [],
            },
        ).status_code == 200
        run_id = _finish_run(client, project_id, seed=17)
        artifact = server.project_manager.output_path(
            project_id,
            run_id,
            "models/candidate-17.pdb",
        )
        outside = tmp_path / "outside-secret"
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        os.link(outside, artifact)

        response = client.get(
            f"/api/projects/{project_id}/run/{run_id}"
            "/artifacts/models/candidate-17.pdb"
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "invalid_artifact"


def test_artifact_api_refuses_symlinked_parent_directories(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        module = RecoveryArtifactModule()
        server.module_registry.register(module.definition)
        server.register_module_factory(
            module.definition.module_id,
            RecoveryArtifactModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "Aliased artifact parent"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [{
                    "node_id": "export",
                    "module_id": module.definition.module_id,
                    "module_version": module.definition.version,
                }],
                "edges": [],
            },
        ).status_code == 200
        run_id = _finish_run(client, project_id, seed=17)
        output_dir = server.project_manager.output_dir(project_id, run_id)
        models = output_dir / "models"
        content = (models / "candidate-17.pdb").read_bytes()
        shutil.rmtree(models)
        outside = tmp_path / "outside-models"
        outside.mkdir()
        (outside / "candidate-17.pdb").write_bytes(content)
        models.symlink_to(outside, target_is_directory=True)

        response = client.get(
            f"/api/projects/{project_id}/run/{run_id}"
            "/artifacts/models/candidate-17.pdb"
        )

    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "invalid_artifact"


def test_cache_clear_refuses_symlink_entries_without_partial_deletion(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Poisoned Cache")
        _finish_run(client, project_id, seed=47)
        before = client.get(
            f"/api/projects/{project_id}/cache/echo"
        ).json()["entries"]
        outside = tmp_path / "outside-cache-target"
        outside.write_text("do not delete")
        poison = (
            server.project_manager.cache_node_dir(project_id, "echo")
            / "poison.pkl"
        )
        poison.symlink_to(outside)

        response = client.delete(
            f"/api/projects/{project_id}/cache/echo"
        )
        after = client.get(
            f"/api/projects/{project_id}/cache/echo"
        ).json()["entries"]

    assert len(before) == 1
    assert response.status_code == 422
    assert response.json()["error"] == {
        "kind": "invalid_storage_path",
        "field": "cache_entry",
        "message": "Invalid Cache entry",
    }
    assert after == before
    assert outside.read_text() == "do not delete"


def test_cache_clear_is_rejected_while_the_project_has_an_active_run(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        module = BlockingRecoveryModule()
        server.module_registry.register(module.definition)
        server.register_module_factory(
            module.definition.module_id,
            BlockingRecoveryModule,
        )
        started = tmp_path / "blocking-started"
        release = tmp_path / "blocking-release"
        project_id = client.post(
            "/api/projects",
            json={"name": "Active Cache"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [
                    {
                        "node_id": "blocking",
                        "module_id": module.definition.module_id,
                        "module_version": module.definition.version,
                        "parameters": {
                            "started_path": str(started),
                            "release_path": str(release),
                        },
                    }
                ],
                "edges": [],
            },
        ).status_code == 200
        execution = client.post(f"/api/projects/{project_id}/run")
        run_id = execution.json()["run_id"]
        deadline = time.monotonic() + 2
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

        response = client.delete(
            f"/api/projects/{project_id}/cache"
        )
        release.touch()
        _await_run(client, project_id, run_id)

    assert started.exists()
    assert response.status_code == 409
    assert response.json()["error"]["kind"] == "active_run_conflict"
    assert response.json()["error"]["active_run_id"] == run_id


def test_run_start_is_rejected_while_cache_clear_is_reserved(
    tmp_path,
    monkeypatch,
) -> None:
    app = _isolated_app(tmp_path, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    original_clear = server.CacheService.clear

    def blocking_clear(service, project_id, node_id=None):
        entered.set()
        assert release.wait(timeout=5)
        return original_clear(service, project_id, node_id)

    monkeypatch.setattr(server.CacheService, "clear", blocking_clear)
    with TestClient(app) as client:
        project_id = _saved_echo_project(client, "Cache reservation")
        result: dict[str, object] = {}

        def request_clear() -> None:
            result["response"] = client.delete(
                f"/api/projects/{project_id}/cache"
            )

        thread = threading.Thread(target=request_clear)
        thread.start()
        assert entered.wait(timeout=5)
        run = client.post(f"/api/projects/{project_id}/run")
        release.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert run.status_code == 409
    assert run.json()["error"]["kind"] == "cache_mutation_conflict"
    clear_response = result["response"]
    assert clear_response.status_code == 200
