"""Scientific scope and pinned-result continuation through the public seam."""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient
import pytest

from tests.fixtures.run_scenarios import commit_pipeline, pipeline_catalog
from tests.support.application import create_application
from tests.support.public_runs import PublicRunClient


def _request(client, project_id, committed, scope, *, start=False):
    return PublicRunClient(client).request(
        "start_run" if start else "preview_run_scope",
        {
            "project_id": project_id,
            "workflow_commit_id": committed["workflow_commit_id"],
            "scope": scope,
            **({"client_request_id": "scope-test"} if start else {}),
        },
        expected_status=202 if start else 200,
    )


def _run(client, project_id, committed, scope):
    receipt = _request(client, project_id, committed, scope, start=True)
    return PublicRunClient(client).wait_terminal(project_id, receipt["run_id"])


def _branch(client, project_id):
    workflow = copy.deepcopy(client.get(
        f"/api/v2/projects/{project_id}/workflow/draft"
    ).json()["workflow"])
    workflow["nodes"].append({**workflow["nodes"][0], "node_id": "independent"})
    return PublicRunClient(client).commit_workflow(project_id, workflow)


@pytest.mark.deterministic_acceptance
def test_to_node_executes_ancestors_and_has_no_unrelated_dispositions(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    calls = []
    with TestClient(create_application(frozen_catalog_override=pipeline_catalog(calls))) as client:
        project_id, _ = commit_pipeline(client)
        committed = _branch(client, project_id)
        scope = {"mode": "to_node", "node_ids": ["sink"]}
        preview = _request(client, project_id, committed, scope)
        projection = _run(client, project_id, committed, scope)
        assert preview["scope"] == projection["scope"]
        assert projection["status"] == "succeeded"
        assert set(preview["scope"]["execution_node_ids"]) == {"source", "sink"}
        assert preview["scope"]["out_of_scope_node_ids"] == ["independent"]
        assert {d["node_id"] for d in projection["node_dispositions"]} == {"source", "sink"}
        assert "execute:independent" not in calls


@pytest.mark.parametrize("cacheable", [False, True])
def test_continue_pins_upstream_and_forces_execution_despite_matching_cache(tmp_path, monkeypatch, cacheable):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    calls = []
    app = create_application(frozen_catalog_override=pipeline_catalog(calls, cacheable=cacheable))
    with TestClient(app) as client:
        project_id, committed = commit_pipeline(client)
        source = _run(client, project_id, committed, {"mode": "full", "node_ids": []})
        committed = _branch(client, project_id)
        calls.clear()
        scope = {"mode": "from_node", "node_ids": ["sink"], "source_run_id": source["run_id"]}
        preview = _request(client, project_id, committed, scope)
        assert preview["blockers"] == []
        projection = _run(client, project_id, committed, scope)
        assert projection["scope"] == preview["scope"]
        assert projection["workflow_commit_id"] != source["workflow_commit_id"]
        assert projection["scope"]["reused_node_ids"] == ["source"]
        assert projection["scope"]["forced_node_ids"] == ["sink"]
        assert {d["node_id"]: d["resolution"] for d in projection["node_dispositions"]} == {
            "source": "cache_replayed", "sink": "executed",
        }
        assert "execute:source" not in calls
        assert "execute:independent" not in calls
        assert calls.count("sink-input:ready") == 1
        source_after = PublicRunClient(client).request("run_projection", {
            "project_id": project_id, "run_id": source["run_id"],
        })
        assert source_after == source


def test_continue_missing_upstream_rejects_before_creating_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    calls = []
    with TestClient(create_application(frozen_catalog_override=pipeline_catalog(calls))) as client:
        project_id, _ = commit_pipeline(client)
        committed = _branch(client, project_id)
        source = _run(client, project_id, committed, {"mode": "to_node", "node_ids": ["independent"]})
        calls.clear()
        scope = {"mode": "from_node", "node_ids": ["sink"], "source_run_id": source["run_id"]}
        preview = _request(client, project_id, committed, scope)
        assert preview["blockers"][0]["code"] == "upstream_result_missing"
        response = client.post(f"/api/v2/projects/{project_id}/runs", json={
            "workflow_commit_id": committed["workflow_commit_id"],
            "client_request_id": "missing-source", "scope": scope,
        })
        assert response.status_code == 422
        assert not any(call.startswith("execute:") or call.startswith("sink-input:") for call in calls)


def test_continue_changed_upstream_identity_is_a_blocker(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    calls = []
    with TestClient(create_application(frozen_catalog_override=pipeline_catalog(
        calls, cacheable=True, configurable_source=True,
    ))) as client:
        project_id, committed = commit_pipeline(client)
        source = _run(client, project_id, committed, {"mode": "full", "node_ids": []})
        workflow = client.get(f"/api/v2/projects/{project_id}/workflow/draft").json()["workflow"]
        workflow["nodes"][0]["node_parameters"]["value"] = "changed"
        revised = PublicRunClient(client).commit_workflow(project_id, workflow)
        calls.clear()
        scope = {"mode": "from_node", "node_ids": ["sink"], "source_run_id": source["run_id"]}
        preview = _request(client, project_id, revised, scope)
        assert preview["blockers"] == []
        response = client.post(f"/api/v2/projects/{project_id}/runs", json={
            "workflow_commit_id": revised["workflow_commit_id"], "scope": scope,
            "client_request_id": "reject-changed-upstream",
        })
        assert response.status_code == 422, response.text
        assert "upstream_result_identity_mismatch" in response.text
        assert not any(call.startswith("execute:") for call in calls)


def test_continue_restores_published_upstream_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(create_application(frozen_catalog_override=pipeline_catalog([]))) as client:
        project_id, committed = commit_pipeline(client)
        source = _run(client, project_id, committed, {"mode": "to_node", "node_ids": ["source"]})
    calls = []
    with TestClient(create_application(frozen_catalog_override=pipeline_catalog(calls))) as client:
        projection = _run(client, project_id, committed, {
            "mode": "from_node", "node_ids": ["sink"], "source_run_id": source["run_id"],
        })
        assert projection["status"] == "succeeded"
        assert projection["run_id"] != source["run_id"]
        assert "execute:source" not in calls
        assert calls.count("sink-input:ready") == 1
        assert PublicRunClient(client).request("run_projection", {
            "project_id": project_id, "run_id": source["run_id"],
        }) == source


def test_continue_forced_failure_never_replays_old_success(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    terminations = {}
    calls = []
    app = create_application(frozen_catalog_override=pipeline_catalog(
        calls, cacheable=True, terminating_source_nodes=terminations,
    ))
    with TestClient(app) as client:
        project_id, committed = commit_pipeline(client)
        source = _run(client, project_id, committed, {"mode": "full", "node_ids": []})
        terminations["source"] = "interrupted"
        calls.clear()
        projection = _run(client, project_id, committed, {
            "mode": "from_node", "node_ids": ["source"], "source_run_id": source["run_id"],
        })
        assert projection["status"] == "interrupted"
        assert projection["outputs"] == []
        assert {item["node_id"]: item["outcome"] for item in projection["node_dispositions"]} == {
            "source": "interrupted", "sink": "blocked",
        }
        assert calls.count("execute:source") == 1
        assert "sink-input:ready" not in calls


def test_interrupted_source_remains_interrupted_when_continued_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    catalog = pipeline_catalog([], terminating_source_nodes={"z-interrupted": "interrupted"})
    with TestClient(create_application(frozen_catalog_override=catalog)) as client:
        project_id, _ = commit_pipeline(client)
        workflow = client.get(f"/api/v2/projects/{project_id}/workflow/draft").json()["workflow"]
        workflow["nodes"].append({**workflow["nodes"][0], "node_id": "z-interrupted"})
        committed = PublicRunClient(client).commit_workflow(project_id, workflow)
        source = _run(client, project_id, committed, {"mode": "full", "node_ids": []})
        assert source["status"] == "interrupted"
    calls = []
    with TestClient(create_application(frozen_catalog_override=pipeline_catalog(calls))) as client:
        projection = _run(client, project_id, committed, {
            "mode": "from_node", "node_ids": ["sink"], "source_run_id": source["run_id"],
        })
        assert projection["status"] == "succeeded"
        assert calls.count("sink-input:ready") == 1
        assert "execute:source" not in calls
        assert "execute:z-interrupted" not in calls
        assert PublicRunClient(client).request("run_projection", {
            "project_id": project_id, "run_id": source["run_id"],
        }) == source
