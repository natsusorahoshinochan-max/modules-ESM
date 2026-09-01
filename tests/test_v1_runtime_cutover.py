"""Cutover contract: production exposes one v2 runtime and no v1 bridge."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from core.project.manager import ProjectManager
from tests.support.public_request import encode_project_input_content
import protein_workbench_public.bootstrap as bootstrap


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
    "structure_prediction",
    "structure_transform",
}


def test_production_discovery_is_exactly_the_accepted_package_surface() -> None:
    registrations = module_registrations()
    assert {registration.package_id for registration in registrations} == (
        ACCEPTED_MODULE_PACKAGES
    )
    assert len(registrations) == 12

    catalog = build_frozen_catalog(module_registrations())
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
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(bootstrap.create_application()) as client:
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
        assert not hasattr(bootstrap, "module_registry")
        assert not hasattr(bootstrap, "type_registry")
        assert not hasattr(bootstrap, "_module_factories")


def test_legacy_persisted_run_and_project_are_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    project_id = "legacy-project"
    project_dir = project_root / project_id
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
    legacy_run = run_root / project_id / "legacy-run"
    legacy_run.mkdir(parents=True)
    (legacy_run / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "status": "completed"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))

    with TestClient(bootstrap.create_application()) as client:
        run = client.get(f"/api/v2/projects/{project_id}/runs/legacy-run")
        assert run.status_code == 404
        assert run.json()["error"]["code"] == "run_not_found"

        uploaded = client.post(
            f"/api/v2/projects/{project_id}/inputs",
            json={
                "filename": "legacy.pdb",
                "content_base64": encode_project_input_content(b"legacy"),
            },
        )
        assert uploaded.status_code == 500
        assert uploaded.json()["error"]["code"] == "internal_error"


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
        input_sources={
            "3GB1.pdb": Path("examples/v2/structures/3GB1.pdb")
        },
    )

    assert result is None
    assert sentinel.read_bytes() == b"must-remain-unchanged"
    assert sorted(path.name for path in existing.iterdir()) == ["local-data"]
