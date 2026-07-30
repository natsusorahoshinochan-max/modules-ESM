"""Cutover contract: production exposes one v2 runtime and no v1 bridge."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import core
import core.server as server
from core import build_discovered_frozen_catalog, discover_module_packages
from core.project import ProjectManager


ACCEPTED_MODULE_PACKAGES = {
    "collection_ops",
    "esm3",
    "folding",
    "prompt_authoring",
    "protein_io",
    "proteinmpnn",
    "selection",
    "solubility",
    "structure_annotation",
    "structure_comparison",
    "structure_transform",
}


def test_production_discovery_is_exactly_the_accepted_package_surface() -> None:
    registrations = discover_module_packages()
    assert {registration.package_id for registration in registrations} == (
        ACCEPTED_MODULE_PACKAGES
    )
    assert len(registrations) == 11

    catalog = build_discovered_frozen_catalog()
    node_ids = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
    }
    assert "stub.echo" not in node_ids
    assert "scoring.aggregate_confidence" not in node_ids
    assert "file.path" not in {
        definition.type_id for definition in catalog.port_types
    }


def test_server_publishes_only_the_frozen_catalog_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    with TestClient(server.create_app()) as client:
        assert client.get("/api/v2/catalog").status_code == 200
        for method, path in (
            ("get", "/api/modules"),
            ("get", "/api/types"),
            ("post", "/api/execute"),
            ("get", "/api/projects/canonical-3gb1/workflow"),
            ("post", "/api/projects/canonical-3gb1/run"),
            ("get", "/api/projects/canonical-3gb1/cache"),
        ):
            response = (
                client.post(path, json={})
                if method == "post"
                else client.get(path)
            )
            assert response.status_code == 404
        assert hasattr(client.app.state, "frozen_catalog")
        assert not hasattr(client.app.state, "module_registry")
        assert not hasattr(server, "module_registry")
        assert not hasattr(server, "type_registry")
        assert not hasattr(server, "_module_factories")


def test_legacy_persisted_workflow_and_run_are_stably_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    manager = ProjectManager(project_root, run_root=run_root)
    project = manager.create("legacy-rejection")
    project_dir = manager.project_dir(project.id)
    (project_dir / "workflow-v2.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "workflow_revision": 1,
                "workflow": {"nodes": [], "edges": []},
            }
        ),
        encoding="utf-8",
    )
    legacy_run = manager.run_dir(project.id, "legacy-run")
    legacy_run.mkdir(parents=True)
    (legacy_run / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "status": "completed"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))

    with TestClient(server.create_app()) as client:
        workflow = client.get(f"/api/v2/projects/{project.id}/workflow")
        assert workflow.status_code == 400
        assert workflow.json()["error"]["code"] == "unsupported_schema_version"
        assert workflow.json()["error"]["details"] == {
            "artifact_kind": "workflow",
            "expected_schema_version": "2.0.0",
            "received_schema_version": "unknown",
        }

        run = client.get(f"/api/v2/projects/{project.id}/runs/legacy-run")
        assert run.status_code == 400
        assert run.json()["error"]["code"] == "unsupported_schema_version"
        assert run.json()["error"]["details"] == {
            "artifact_kind": "run_evidence",
            "expected_schema_version": "2.0.0",
            "received_schema_version": "1",
        }


def test_legacy_runtime_symbols_are_not_public_or_importable() -> None:
    for name in (
        "Executor",
        "ModuleRegistry",
        "TypeRegistry",
        "Workflow",
        "WorkflowModule",
        "RunManifest",
    ):
        assert not hasattr(core, name)

    import datatypes

    assert not hasattr(datatypes, "Score")
