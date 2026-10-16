"""Saved configurations survive conversion through public project operations."""

import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


class PreservedConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = create_application(load_example_results=False)
        self.addCleanup(self.app.state.run_runtime.shutdown)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.project_id = self.request("POST", "/api/v2/projects", json={"name": "Saved research"})["id"]

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def saved_configuration(self, *, node_type="protein_io.import_sequences"):
        uploaded = self.request("POST", f"/api/v2/projects/{self.project_id}/inputs", json={
            "filename": "original.fasta", "content_base64": base64.b64encode(b">original\nACD\n").decode()})
        return {"schema_version": "2.1.0", "workflow_id": self.project_id, "nodes": [{
            "node_id": "original", "node_type_id": node_type, "binding_id": node_type + ".direct",
            "node_parameters": {"project_input_ref": uploaded["project_input_ref"]}, "binding_parameters": {},
            "preserved_configuration": {"reason": "The saved operation cannot be converted equivalently.",
                "settings": {"original_options": {"objective_id": "old-ranking"}},
                "project_input_parameters": ["project_input_ref"]},
        }], "edges": [], "observation_selectors": [], "selection_objectives": []}

    def test_preserved_registered_node_saves_and_reopens_but_cannot_run_new_defaults(self):
        workflow = self.saved_configuration()
        path = f"/api/v2/projects/{self.project_id}"
        self.request("PUT", path + "/workspace", json={"workflow": workflow, "ui_state": {}})
        reopened = self.request("GET", path + "/workspace")["draft"]["workflow"]
        self.assertEqual(reopened["nodes"], workflow["nodes"])
        response = self.client.post(path + "/workflow:commit", json={"workflow": reopened})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["details"]["issues"][0]["code"], "preserved_configuration_unavailable")

    def test_duplicate_keeps_preserved_missing_module_input_after_source_deletion(self):
        workflow = self.saved_configuration(node_type="retired.input")
        path = f"/api/v2/projects/{self.project_id}"
        self.request("PUT", path + "/workspace", json={"workflow": workflow, "ui_state": {}})
        duplicated = self.request("POST", path + ":duplicate", json={"name": "Independent retained work"})["id"]
        self.request("POST", path + ":trash")
        self.request("DELETE", path)
        reopened = self.request("GET", f"/api/v2/projects/{duplicated}/workspace")["draft"]["workflow"]
        reference = reopened["nodes"][0]["node_parameters"]["project_input_ref"]
        metadata = self.request("GET", f"/api/v2/projects/{duplicated}/inputs/{reference}")
        self.assertEqual((reopened["nodes"], metadata["filename"], metadata["size"]),
                         (workflow["nodes"], "original.fasta", 14))
