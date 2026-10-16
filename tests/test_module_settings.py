"""Module settings behavior through the public HTTP API."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import base64
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


class ModuleSettingsBehavior(unittest.TestCase):
    def test_partial_settings_survive_application_reopen(self):
        with TemporaryDirectory() as root, patch.dict(
            "os.environ", {"PROTEIN_WORKBENCH_DATA_ROOT": root}
        ):
            model_path = str(Path(root) / "fold-model")
            with TestClient(create_application(load_example_results=False)) as client:
                response = client.patch(
                    "/api/v2/module-settings/folding.fold.esmfold2_local",
                    json={"values": {"model_snapshot_path": model_path}},
                )
                self.assertEqual(response.status_code, 200, response.text)
            with TestClient(create_application(load_example_results=False)) as client:
                response = client.get("/api/v2/module-settings")
                self.assertEqual(response.status_code, 200, response.text)
                binding = next(item for item in response.json()["bindings"]
                               if item["binding_id"] == "folding.fold.esmfold2_local")
                self.assertEqual(binding["values"], {"model_snapshot_path": model_path})

    def test_concurrent_field_saves_preserve_both_settings(self):
        with TemporaryDirectory() as root, patch.dict(
            "os.environ", {"PROTEIN_WORKBENCH_DATA_ROOT": root}
        ), TestClient(create_application(load_example_results=False)) as client:
            fields = {"model_snapshot_path": root + "/fold",
                      "language_model_snapshot_path": root + "/language"}
            start = Barrier(2)

            def save_field(item):
                name, value = item
                start.wait()
                return client.patch("/api/v2/module-settings/folding.fold.esmfold2_local",
                                    json={"values": {name: value}})

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(save_field, fields.items()))
            for response in responses:
                self.assertEqual(response.status_code, 200, response.text)
            settings = client.get("/api/v2/module-settings").json()
            binding = next(item for item in settings["bindings"]
                           if item["binding_id"] == "folding.fold.esmfold2_local")
            self.assertEqual(binding["values"], fields)

    def test_missing_remote_credential_is_reported_before_provider_execution(self):
        with TemporaryDirectory() as root, patch.dict(
            "os.environ", {"PROTEIN_WORKBENCH_DATA_ROOT": root}
        ), TestClient(create_application(load_example_results=False)) as client:
            events = self.run_remote_fold(client)
            fold_attempt = next(event["node_attempt_id"] for event in events
                                if event["type"] == "node_attempt_started" and event["node_id"] == "fold")
            fold_terminal = next(event for event in events
                                 if event["type"] == "node_attempt_terminal"
                                 and event["node_attempt_id"] == fold_attempt)
            self.assertEqual(fold_terminal["error"]["code"], "readiness_rejected")
            self.assertEqual(fold_terminal["error"]["details"]["reason_code"],
                             "environment_configuration_incomplete")

    def run_remote_fold(self, client):
        project = client.post("/api/v2/projects", json={"name": "Unconfigured fold"})
        self.assertEqual(project.status_code, 201, project.text)
        prefix = "/api/v2/projects/" + project.json()["id"]
        source = client.post(prefix + "/inputs", json={
            "filename": "sequence.fasta",
            "content_base64": base64.b64encode(b">sequence\nACDEFGHIKLMNPQRSTVWY\n").decode(),
        })
        self.assertEqual(source.status_code, 201, source.text)
        workflow = {
            "schema_version": "2.1.0", "workflow_id": project.json()["id"],
            "nodes": [
                {"node_id": "source", "node_type_id": "protein_io.import_sequence",
                 "binding_id": "protein_io.import_sequence.direct",
                 "node_parameters": {"project_input_ref": source.json()["project_input_ref"]},
                 "binding_parameters": {}},
                {"node_id": "fold", "node_type_id": "folding.fold",
                 "binding_id": "folding.fold.esmfold2_remote",
                 "node_parameters": {}, "binding_parameters": {}},
            ],
            "edges": [{"source_node_id": "source", "source_port": "sequence_candidates",
                       "target_node_id": "fold", "target_port": "sequence_candidates"}],
        }
        commit = client.post(prefix + "/workflow:commit", json={"workflow": workflow})
        self.assertEqual(commit.status_code, 200, commit.text)
        started = client.post(prefix + "/runs", json={
            "workflow_commit_id": commit.json()["workflow_commit_id"],
            "client_request_id": "missing-credential",
        })
        self.assertEqual(started.status_code, 202, started.text)
        deadline = time.monotonic() + 10
        while True:
            result = client.get(prefix + "/runs/" + started.json()["run_id"])
            self.assertEqual(result.status_code, 200, result.text)
            projection = result.json()
            if projection["status"] not in ("pending", "running"):
                break
            self.assertLess(time.monotonic(), deadline, "Run did not finish")
            time.sleep(0.02)
        events = []
        with client.websocket_connect(prefix + "/runs/" + started.json()["run_id"] + "/events") as stream:
            while True:
                event = stream.receive_json()["event"]
                events.append(event)
                if event["type"] == "replay_complete":
                    break
        return events

    def test_saved_service_address_and_credential_reach_official_sdk_after_reopen(self):
        from esm.sdk.api import ESMProteinError

        with TemporaryDirectory() as root, patch.dict(
            "os.environ", {"PROTEIN_WORKBENCH_DATA_ROOT": root}
        ):
            with TestClient(create_application(load_example_results=False)) as client:
                saved = client.patch("/api/v2/module-settings/folding.fold.esmfold2_remote", json={
                    "values": {"service_url": "https://configured.example", "credential_handle": "sample-token"}
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertNotIn("sample-token", saved.text)
            with patch("esm.sdk.esmfold2_client") as sdk:
                sdk.return_value.fold.return_value = ESMProteinError(500, "Defined provider failure")
                with TestClient(create_application(load_example_results=False)) as client:
                    events = self.run_remote_fold(client)
                self.assertEqual(sdk.call_args.kwargs["url"], "https://configured.example")
                self.assertEqual(sdk.call_args.kwargs["token"], "sample-token")
                self.assertEqual(sdk.return_value.fold.call_args.kwargs["sequence"], "ACDEFGHIKLMNPQRSTVWY")
                self.assertTrue(any(event["type"] == "run_terminal" and event["status"] == "failed"
                                    for event in events))


if __name__ == "__main__":
    unittest.main()
