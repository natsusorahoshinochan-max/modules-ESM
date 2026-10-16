"""Historical results remain useful through the application's public operations."""

import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


class HistoryPreservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.open_application()

    def open_application(self):
        self.app = create_application(load_example_results=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.app.state.run_runtime.shutdown)
        self.addCleanup(self.client.close)

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def project(self, name):
        return self.request("POST", "/api/v2/projects", json={"name": name})["id"]

    def workflow(self, project_id, nodes, edges=()):
        return {"schema_version": "2.1.0", "workflow_id": project_id,
                "nodes": nodes, "edges": list(edges),
                "observation_selectors": [], "selection_objectives": []}

    @staticmethod
    def node(node_id, node_type, parameters):
        return {"node_id": node_id, "node_type_id": node_type,
                "binding_id": node_type + ".direct", "node_parameters": parameters,
                "binding_parameters": {}}

    def commit_and_run(self, project_id, workflow):
        self.request("PUT", f"/api/v2/projects/{project_id}/workspace", json={"workflow": workflow, "ui_state": {}})
        commit = self.request("POST", f"/api/v2/projects/{project_id}/workflow:commit", json={"workflow": workflow})
        receipt = self.app.state.run_runtime.start(project_id,
            workflow_commit_id=commit["workflow_commit_id"], client_request_id="history-test")
        return commit, receipt["run_id"]

    def source(self):
        project_id = self.project("Original research")
        uploaded = self.request("POST", f"/api/v2/projects/{project_id}/inputs", json={
            "filename": "research.fasta", "content_base64": base64.b64encode(b">first\nACD\n>second\nWVV\n").decode()})
        workflow = self.workflow(project_id, [self.node("import", "protein_io.import_sequences", {
            "project_input_ref": uploaded["project_input_ref"]})])
        commit, run_id = self.commit_and_run(project_id, workflow)
        return project_id, run_id, commit

    def value(self, project_id, run_id, node_id, port):
        return self.request("GET", f"/api/v2/projects/{project_id}/runs/{run_id}/outputs/{node_id}/{port}/values/0")

    def candidates(self, project_id, run_id, node_id, port):
        return self.request("POST", f"/api/v2/projects/{project_id}/runs/{run_id}/results:action", json={
            "inputs": {"candidates": [{"node_id": node_id, "output_port": port, "value_index": 0, "slot": "collection"}]},
            "action_id": "protein_io.candidate_page", "parameters": {"offset": 0, "limit": 10}})

    def test_historical_run_exposes_original_saved_calculation_settings(self):
        project_id, run_id, commit = self.source()
        self.app.state.run_runtime.shutdown()
        self.client.close()
        self.open_application()
        run = self.request("GET", f"/api/v2/projects/{project_id}/runs/{run_id}")
        saved = self.request("GET", f"/api/v2/projects/{project_id}/workflow/commits/{run['workflow_commit_id']}")
        self.assertEqual(saved["workflow"], commit["workflow"])
        self.assertEqual(saved["scientific_definitions"], commit["scientific_definitions"])

    def test_adopted_history_survives_source_deletion_and_reopen(self):
        source_id, source_run, commit = self.source()
        original = self.value(source_id, source_run, "import", "sequence_candidates")
        target_id = self.project("Follow-up research")
        adopted = self.request("POST", f"/api/v2/projects/{target_id}/inputs:adopt", json={
            "source_project_id": source_id, "source_run_id": source_run,
            "node_id": "import", "output_port": "sequence_candidates", "value_index": 0})
        self.request("POST", f"/api/v2/projects/{source_id}:trash")
        self.request("DELETE", f"/api/v2/projects/{source_id}")
        self.app.state.run_runtime.shutdown()
        self.client.close()
        self.open_application()
        metadata = self.request("GET", f"/api/v2/projects/{target_id}/inputs/{adopted['project_input_ref']}:adoption")
        self.assertEqual(metadata["parameters"]["status"], "recorded")
        self.assertEqual(metadata["parameters"]["records"][0]["node_parameters"],
                         commit["workflow"]["nodes"][0]["node_parameters"])
        workflow = self.workflow(target_id, [{"node_id": "adopted", **adopted["source_node"]}])
        _, target_run = self.commit_and_run(target_id, workflow)
        self.assertEqual(self.value(target_id, target_run, "adopted", "value")["value"], original["value"])

    def test_adopted_candidates_can_be_selected_after_source_deletion(self):
        source_id, source_run, _ = self.source()
        original = self.candidates(source_id, source_run, "import", "sequence_candidates")
        selected_reference = original["items"][1]["reference"]
        target_id = self.project("Selected follow-up")
        adopted = self.request("POST", f"/api/v2/projects/{target_id}/inputs:adopt", json={
            "source_project_id": source_id, "source_run_id": source_run,
            "node_id": "import", "output_port": "sequence_candidates", "value_index": 0})
        self.request("POST", f"/api/v2/projects/{source_id}:trash")
        self.request("DELETE", f"/api/v2/projects/{source_id}")
        self.app.state.run_runtime.shutdown()
        self.client.close()
        self.open_application()
        workflow = self.workflow(target_id, [
            {"node_id": "adopted", **adopted["source_node"]},
            self.node("select", "selection.manual", {"selected_candidates": [selected_reference]}),
        ], [{"source_node_id": "adopted", "source_port": "value", "target_node_id": "select", "target_port": "candidates"}])
        _, target_run = self.commit_and_run(target_id, workflow)
        selected = self.candidates(target_id, target_run, "select", "candidates")
        self.assertEqual([(item["reference"], item["sequence"], item["metadata"], item["parent_ids"]) for item in selected["items"]],
                         [(selected_reference, "WVV", original["items"][1]["metadata"], [])])
