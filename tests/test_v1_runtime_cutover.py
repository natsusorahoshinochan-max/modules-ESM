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
    workflow_project = manager.create("legacy-workflow")
    workflow_project_dir = manager.project_dir(workflow_project.id)
    (workflow_project_dir / "workflow-v2.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "workflow_revision": 1,
                "workflow": {"nodes": [], "edges": []},
            }
        ),
        encoding="utf-8",
    )
    project_id = "legacy-project"
    project_dir = manager.project_dir(project_id)
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "id": project_id,
                "name": "legacy-rejection",
            }
        ),
        encoding="utf-8",
    )
    legacy_run = manager.run_dir(project_id, "legacy-run")
    legacy_run.mkdir(parents=True)
    (legacy_run / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "status": "completed"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))

    with TestClient(server.create_app()) as client:
        workflow = client.get(
            f"/api/v2/projects/{workflow_project.id}/workflow"
        )
        assert workflow.status_code == 400
        assert workflow.json()["error"]["code"] == "unsupported_schema_version"
        assert workflow.json()["error"]["details"] == {
            "artifact_kind": "workflow",
            "expected_schema_version": "2.1.0",
            "received_schema_version": "unknown",
        }

        run = client.get(f"/api/v2/projects/{project_id}/runs/legacy-run")
        assert run.status_code == 400
        assert run.json()["error"]["code"] == "unsupported_schema_version"
        assert run.json()["error"]["details"] == {
            "artifact_kind": "run_evidence",
            "expected_schema_version": "2.1.0",
            "received_schema_version": "1",
        }

        uploaded = client.post(
            f"/api/projects/{project_id}/inputs",
            files={"file": ("legacy.pdb", b"legacy", "chemical/x-pdb")},
        )
        assert uploaded.status_code == 400
        assert uploaded.json()["error"]["code"] == (
            "unsupported_schema_version"
        )
        assert uploaded.json()["error"]["details"]["artifact_kind"] == (
            "project"
        )


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


def test_seed_install_does_not_adopt_or_rewrite_existing_local_data(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects"
    existing = project_root / "canonical-3gb1"
    existing.mkdir(parents=True)
    sentinel = existing / "local-data"
    sentinel.write_bytes(b"must-remain-unchanged")
    manager = ProjectManager(project_root)

    result = manager.ensure_seed_project_v2(
        Path("examples/v2/canonical-3gb1.workflow.json"),
        input_sources={"3GB1.pdb": Path("pdbs/3GB1.pdb")},
    )

    assert result is None
    assert sentinel.read_bytes() == b"must-remain-unchanged"
    assert sorted(path.name for path in existing.iterdir()) == ["local-data"]
