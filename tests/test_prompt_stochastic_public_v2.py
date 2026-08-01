"""Public REST journey for stochastic prompt authoring."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import build_frozen_catalog
from core.server import create_app
from modules.prompt_authoring.package import MODULE_PACKAGE
from protein_workbench_public import validate_response
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)
from tests.fixtures.prompt_authoring_v2 import VERSION


STRUCTURE_SOURCE_VERSION = "3.0.0"


def test_stochastic_prompt_authoring_executes_through_public_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))

    with TestClient(create_app(frozen_catalog_override=catalog)) as client:
        project_id = client.post(
            "/api/projects",
            json={"name": "stochastic prompt public journey"},
        ).json()["id"]
        workflow = {
            "schema_version": VERSION,
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "source",
                    "node_type_id": "contract_test.prompt_authoring_values",
                    "node_type_version": STRUCTURE_SOURCE_VERSION,
                    "binding_id": (
                        "contract_test.prompt_authoring_values.direct"
                    ),
                    "binding_version": STRUCTURE_SOURCE_VERSION,
                    "node_parameters": {"fixture": "canonical"},
                    "binding_parameters": {},
                },
                {
                    "node_id": "mask",
                    "node_type_id": "prompt_authoring.random_mask",
                    "node_type_version": VERSION,
                    "binding_id": "prompt_authoring.random_mask.direct",
                    "binding_version": VERSION,
                    "node_parameters": {
                        "effective_seed": 73,
                        "count": 1,
                        "track": "sequence",
                        "eligible_residue_ids": [],
                    },
                    "binding_parameters": {},
                },
            ],
            "edges": [
                {
                    "source_node_id": "source",
                    "source_port": "protein_prompt",
                    "target_node_id": "mask",
                    "target_port": "protein_prompt",
                },
            ],
            "contract_lock": [],
        }
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": saved.json()["workflow_revision"]},
        )
        assert relocked.status_code == 200
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": relocked.json()["workflow_revision"],
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": relocked.json()["workflow_revision"],
                "compile_id": compiled.json()["compile_id"],
                "client_request_id": "stochastic-public-run",
            },
        )
        assert started.status_code == 202
        validate_response("start_run", 202, started.json())
        projection = wait_for_testclient_run_terminal(
            client,
            project_id=project_id,
            run_id=started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert any(
        output["node_id"] == "mask"
        and output["output_port"] == "protein_prompt"
        for output in projection["outputs"]
    )
