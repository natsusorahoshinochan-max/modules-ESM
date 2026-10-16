"""Completed research remains readable after its execution machinery retires."""

import base64
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


class RecordedRunReadingTests(unittest.TestCase):
    def test_completed_run_reopens_from_preserved_reading_without_original_ledger(self):
        self.assert_completed_run_readable(prepare_history=True)

    def test_new_completed_run_already_has_reading_independent_of_execution_ledger(self):
        self.assert_completed_run_readable(prepare_history=False)

    def assert_completed_run_readable(self, *, prepare_history):
        with tempfile.TemporaryDirectory() as directory:
            original_root = Path(directory) / "original"
            copy_root = Path(directory) / "preserved"
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(original_root)}):
                app = create_application(load_example_results=False)
                with TestClient(app) as client:
                    def request(method, path, **kwargs):
                        response = client.request(method, path, **kwargs)
                        self.assertLess(response.status_code, 300, response.text)
                        return response.json()

                    project_id = request("POST", "/api/v2/projects", json={"name": "Research"})["id"]
                    uploaded = request("POST", f"/api/v2/projects/{project_id}/inputs", json={
                        "filename": "sequences.fasta",
                        "content_base64": base64.b64encode(b">sample\nACD\n").decode(),
                    })
                    workflow = {
                        "schema_version": "2.1.0", "workflow_id": project_id,
                        "nodes": [{"node_id": "import", "node_type_id": "protein_io.import_sequences",
                                   "binding_id": "protein_io.import_sequences.direct",
                                   "node_parameters": {"project_input_ref": uploaded["project_input_ref"]},
                                   "binding_parameters": {}}],
                        "edges": [], "observation_selectors": [], "selection_objectives": [],
                    }
                    request("PUT", f"/api/v2/projects/{project_id}/workspace", json={"workflow": workflow, "ui_state": {}})
                    commit = request("POST", f"/api/v2/projects/{project_id}/workflow:commit", json={"workflow": workflow})
                    receipt = request("POST", f"/api/v2/projects/{project_id}/runs", json={
                        "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "record-history",
                    })
                    run_id = receipt["run_id"]
                    app.state.run_runtime.shutdown()
                    run_path = f"/api/v2/projects/{project_id}/runs/{run_id}"
                    original = request("GET", run_path)
                    original_value = request("GET", run_path + "/outputs/import/sequence_candidates/values/0")
                    original_events = self.read_events(client, run_path)
                app.state.run_runtime.shutdown()

            shutil.copytree(original_root, copy_root)
            if prepare_history:
                from core.execution.history_preservation import prepare_historical_reading
                (copy_root / "runs" / project_id / run_id / "reading.json").unlink()
                prepare_historical_reading(copy_root)
            shutil.rmtree(copy_root / "runs" / project_id / run_id / "ledger")

            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(copy_root)}):
                reopened = create_application(load_example_results=False)
                try:
                    with TestClient(reopened) as client:
                        response = client.get(run_path)
                        self.assertEqual(response.status_code, 200, response.text)
                        reading = response.json()
                        self.assertEqual(reading, original)
                        value = client.get(run_path + "/outputs/import/sequence_candidates/values/0")
                        self.assertEqual(value.status_code, 200, value.text)
                        self.assertEqual(value.json(), original_value)
                        self.assertEqual(self.read_events(client, run_path), original_events)
                        runs = client.get(f"/api/v2/projects/{project_id}/runs").json()["runs"]
                        self.assertEqual(next(run for run in runs if run["run_id"] == run_id)["status"], "succeeded")
                finally:
                    reopened.state.run_runtime.shutdown()

    def read_events(self, client, run_path):
        events = []
        with client.websocket_connect(run_path + "/events") as stream:
            while True:
                message = stream.receive_json()
                self.assertIn("event", message)
                event_type = message["event"]["type"]
                if event_type == "replay_complete":
                    return events
                if event_type != "replay_started":
                    events.append(message)
