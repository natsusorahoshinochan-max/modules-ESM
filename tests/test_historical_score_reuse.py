"""Context display enrichment does not change the original scoring Method."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.builder import build_frozen_catalog
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from modules.collection_ops.package import MODULE_PACKAGE as COLLECTIONS
from modules.selection.package import MODULE_PACKAGE as SELECTION
from modules.structure_comparison.package import MODULE_PACKAGE as COMPARISON
from protein_workbench_public.http.app import create_http_app
from tests import test_selection_application as study


def registration(*, original):
    package = study.study_registration()
    tm = next(method for method in COMPARISON.methods if method.method_id == "structure_comparison.tm_score.reference_axis_normalized.method")
    algorithm = dict(tm.algorithm_identity)
    if original:
        algorithm.pop("observation_regions", None)
    method = replace(tm, method_id="selection_fixture.scores.method", algorithm_identity=algorithm)
    return replace(package, methods=tuple(method if item.method_id == method.method_id else item for item in package.methods))


def application(root, package):
    registrations = (SELECTION, COLLECTIONS, package)
    catalog = build_frozen_catalog(registrations)
    projects = ProjectManager(root / "projects", cache_root=root / "cache", output_root=root / "outputs", run_root=root / "runs")
    authoring = WorkflowAuthoringService(projects, catalog)
    store = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
    runtime = V2RunService(projects, catalog, authoring,
        NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), store), store)
    return create_http_app(catalog, projects, authoring, runtime,
        authoring_projection=build_authoring_capability_projection(registrations, catalog))


class HistoricalScoreReuseTests(unittest.TestCase):
    execute_workflow = study.SelectionApplicationTests.execute_workflow

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def test_original_method_scores_restore_and_raw_sort_after_source_deletion_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_app = application(root, registration(original=True))
            with TestClient(old_app) as self.client:
                self.project = self.request("POST", "/api/v2/projects", json={"name": "Original scores"})["id"]
                source_id = self.project
                workflow = study.SelectionApplicationTests.workflow(self)
                workflow["nodes"][1]["node_parameters"] = {"values": [0.3, 0.9, 0.1]}
                source_run, result = self.execute_workflow(workflow)
                self.assertEqual(result["status"], "succeeded", result)
            old_app.state.run_runtime.shutdown()
            current = application(root, registration(original=False))
            with TestClient(current) as self.client:
                self.project = self.request("POST", "/api/v2/projects", json={"name": "Reused scores"})["id"]
                target = self.project
                adopted = self.request("POST", f"/api/v2/projects/{target}/inputs:adopt", json={
                    "source_project_id": source_id, "source_run_id": source_run,
                    "node_id": "measurements", "output_port": "scores", "value_index": 0})
                source_node = {"node_id": "history", **adopted["source_node"]}
                source_only = {"schema_version": "2.1.0", "workflow_id": target, "nodes": [source_node], "edges": []}
                _, restored = self.execute_workflow(source_only)
                self.assertEqual(restored["status"], "succeeded", restored)
                self.request("POST", f"/api/v2/projects/{source_id}:trash")
                self.request("DELETE", f"/api/v2/projects/{source_id}")
            current.state.run_runtime.shutdown()
            reopened = application(root, registration(original=False))
            with TestClient(reopened) as self.client:
                selection = {"score_input": "historic", "metric_id": "selection_fixture.raw",
                    "method_id": "selection_fixture.scores.method", "source_partition": "raw", "context": {"kind": "intrinsic"}}
                sorted_workflow = {"schema_version": "2.1.0", "workflow_id": target, "nodes": [source_node, {
                    "node_id": "chosen", "node_type_id": "selection.sort", "binding_id": "selection.sort.direct",
                    "node_parameters": {"selection": selection, "direction": "descending"}, "binding_parameters": {}}],
                    "edges": [{"source_node_id": "history", "source_port": "subjects", "target_node_id": "chosen", "target_port": "candidates"},
                              {"source_node_id": "history", "source_port": "value", "target_node_id": "chosen", "target_port": "scores", "target_slot": "historic"}]}
                run_id, sorted_result = self.execute_workflow(sorted_workflow)
                self.assertEqual(sorted_result["status"], "succeeded", sorted_result)
                output = self.request("GET", f"/api/v2/projects/{target}/runs/{run_id}/outputs/chosen/candidates/values/0")
                self.assertEqual([dict(item["fields"]["metadata"]["$map"])["display_name"] for item in output["value"]["fields"]["items"]], ["alpha", "zeta", "last"])
            reopened.state.run_runtime.shutdown()
