"""Public backend checks for production workflow-scoped readiness."""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.server import create_app


def test_production_backend_fails_closed_before_accepting_unready_workflow(
    monkeypatch,
    isolated_project_dir,
) -> None:
    del isolated_project_dir
    monkeypatch.delenv(
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        raising=False,
    )
    workflow = {
        "nodes": [{
            "node_id": "import",
            "module_id": "import.sequence",
            "module_version": "1.0.0",
            "parameters": {
                "file_path": "inputs/input.fasta",
            },
        }, {
            "node_id": "fold",
            "module_id": "esmfold2.fold",
            "module_version": "1.0.0",
            "parameters": {
                "model_name": "esmfold2-fast-2026-05",
            },
        }],
        "edges": [{
            "source_node_id": "import",
            "source_port": "sequence",
            "target_node_id": "fold",
            "target_port": "sequence",
        }],
    }

    with TestClient(create_app()) as client:
        response = client.post("/api/execute", json={
            **workflow,
            "provider_readiness": {
                "biohub": {
                    "ready": True,
                    "credential": "client-secret-must-not-authorize",
                },
            },
        })

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["kind"] == "required_provider_unavailable"
    assert error["readiness"] == [{
        "provider": "biohub",
        "status": "unavailable",
        "ready": False,
        "provider_identity": {
            "sdk": "esm",
            "sdk_source_revision": (
                "917af90b624535eed1e072d343c717e3ec11fef4"
            ),
            "service": "Biohub",
        },
        "source": {
            "kind": "workflow_required_boundary",
            "node_ids": ["fold"],
            "module_ids": ["esmfold2.fold"],
        },
        "details": {"access_configured": False},
    }]
    assert "run_id" not in response.json()
    assert "client-secret-must-not-authorize" not in response.text
