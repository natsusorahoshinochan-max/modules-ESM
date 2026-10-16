"""Offline conversion preserves whole saved projects and retained workspaces."""

import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def files_in(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


class DataRootMigrationTests(unittest.TestCase):
    def test_interrupted_copy_does_not_publish_destination_or_switch_active_root(self):
        from modules.selection.migrate import convert_data_root

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "saved"
            destination = Path(directory) / "converted"
            source.mkdir()
            (source / "original-input").write_bytes(b"original research input")
            original = files_in(source)
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(source)}):
                with patch("shutil.copytree", side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        convert_data_root(source, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(files_in(source), original)
                self.assertEqual(os.environ["PROTEIN_WORKBENCH_DATA_ROOT"], str(source))
                self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["saved"])

    def test_original_non_equivalent_commit_is_readable_but_direct_execution_is_blocked(self):
        from modules.selection.migrate import convert_data_root

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "saved"
            destination = Path(directory) / "converted"
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(source)}):
                app = create_application(load_example_results=False)
                with TestClient(app) as client:
                    project = client.post("/api/v2/projects", json={"name": "Original saved calculation"}).json()["id"]
                app.state.run_runtime.shutdown()
            original_workflow = {"schema_version": "2.1.0", "workflow_id": project, "nodes": [{
                "node_id": "old", "node_type_id": "selection.top_k", "binding_id": "selection.top_k.direct",
                "node_parameters": {"objective_id": "old-objective", "k": 3}, "binding_parameters": {}}],
                "edges": [], "observation_selectors": [], "selection_objectives": []}
            record = {"workflow": original_workflow, "commit": {"workflow_commit_id": "workflow-commit-11111111111111111111111111111111",
                "source_draft_revision": 1, "scientific_definitions": [], "scientific_identity": {"nodes": []}}}
            commits = source / "projects" / project / "workflow-v2" / "commits"
            commits.mkdir(parents=True)
            (commits / "00000000000000000001.json").write_text(json.dumps(record))

            convert_data_root(source, destination)

            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(destination)}):
                reopened = create_application(load_example_results=False)
                try:
                    with TestClient(reopened) as client:
                        base = f"/api/v2/projects/{project}"
                        snapshot = client.get(base + "/workflow/commits/workflow-commit-11111111111111111111111111111111")
                        self.assertEqual(snapshot.status_code, 200, snapshot.text)
                        self.assertEqual(snapshot.json()["workflow"], original_workflow)
                        started = client.post(base + "/runs", json={"workflow_commit_id": "workflow-commit-11111111111111111111111111111111", "client_request_id": "original-run"})
                        self.assertEqual(started.status_code, 422, started.text)
                        self.assertEqual(started.json()["error"]["details"]["issues"][0]["code"], "preserved_configuration_unavailable")
                finally:
                    reopened.state.run_runtime.shutdown()

    def test_unreadable_saved_input_aborts_copy_without_changing_source_or_active_setting(self):
        from modules.selection.migrate import convert_data_root

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "saved"
            destination = Path(directory) / "converted"
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(source)}):
                app = create_application(load_example_results=False)
                with TestClient(app) as client:
                    project = client.post("/api/v2/projects", json={"name": "Damaged input study"}).json()["id"]
                    uploaded = client.post(f"/api/v2/projects/{project}/inputs", json={
                        "filename": "original.fasta", "content_base64": base64.b64encode(b">sample\nACD\n").decode()}).json()
                app.state.run_runtime.shutdown()
                payload = source / "projects" / project / "inputs" / uploaded["project_input_ref"] / "payload"
                payload.write_bytes(b"interrupted stored bytes")
                original = files_in(source)
                with self.assertRaisesRegex(ValueError, "Input.*integrity"):
                    convert_data_root(source, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(files_in(source), original)
                self.assertEqual(os.environ["PROTEIN_WORKBENCH_DATA_ROOT"], str(source))

    def test_every_saved_version_and_return_point_remains_readable_in_new_copy(self):
        from modules.selection.migrate import convert_data_root

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "saved"
            destination = Path(directory) / "converted"
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(source)}):
                app = create_application(load_example_results=False)
                with TestClient(app) as client:
                    def request(method, path, **kwargs):
                        response = client.request(method, path, **kwargs)
                        self.assertLess(response.status_code, 300, response.text)
                        return response.json()
                    project = request("POST", "/api/v2/projects", json={"name": "Archived study"})["id"]
                    uploaded = request("POST", f"/api/v2/projects/{project}/inputs", json={
                        "filename": "sequences.fasta", "content_base64": base64.b64encode(b">sample\nACD\n").decode()})
                    workflow = {"schema_version": "2.1.0", "workflow_id": project, "nodes": [{
                        "node_id": "rank", "node_type_id": "selection.top_k", "binding_id": "selection.top_k.direct",
                        "node_parameters": {"objective_id": "saved-objective", "k": 2}, "binding_parameters": {},
                    }, {"node_id": "input", "node_type_id": "protein_io.import_sequences", "binding_id": "protein_io.import_sequences.direct",
                        "node_parameters": {"project_input_ref": uploaded["project_input_ref"]}, "binding_parameters": {}}],
                        "edges": [{"source_node_id": "input", "source_port": "sequence_candidates", "target_node_id": "rank", "target_port": "candidates"}],
                        "observation_selectors": [], "selection_objectives": []}
                    base = f"/api/v2/projects/{project}"
                    first = request("PUT", base + "/workspace", json={"workflow": workflow, "ui_state": {"position": "first"}})
                    version = request("POST", base + "/versions", json={"name": "Original preference"})
                    workflow["nodes"][0]["node_parameters"]["k"] = 5
                    second = request("PUT", base + "/workspace", json={"workflow": workflow, "ui_state": {"position": "second"}})
                app.state.run_runtime.shutdown()
            # Model an original stored data format at the filesystem boundary;
            # all values above came from current public save operations.
            for current in source.glob("projects/*/workflow-v2/draft-readings"):
                current.rename(current.with_name("drafts"))
            original = files_in(source)

            convert_data_root(source, destination)

            self.assertEqual(files_in(source), original)
            self.assertTrue(all(files_in(destination)[name] == digest for name, digest in original.items()))
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(destination)}):
                reopened = create_application(load_example_results=False)
                try:
                    with TestClient(reopened) as client:
                        saved = client.get(base + "/workspace").json()
                        self.assertEqual(saved["draft"]["workflow"]["nodes"][0]["node_parameters"]["k"], 5)
                        self.assertIn("preserved_configuration", saved["draft"]["workflow"]["nodes"][0])
                        old = client.get(base + "/versions/" + version["version_id"]).json()["workspace"]
                        self.assertEqual((old["draft"]["workflow"]["nodes"][0]["node_parameters"]["k"], old["ui_state"]), (2, {"position": "first"}))
                        returned = client.post(base + "/workspace:return", json={"workspace_revision": first["workspace_revision"]})
                        self.assertEqual(returned.status_code, 200, returned.text)
                        self.assertEqual(returned.json()["draft"]["workflow"]["nodes"][0]["node_parameters"]["k"], 2)
                        saved_again = client.put(base + "/workspace", json={"workflow": saved["draft"]["workflow"], "ui_state": {"position": "continued"}})
                        self.assertEqual(saved_again.status_code, 200, saved_again.text)
                        duplicate = client.post(base + ":duplicate", json={"name": "Converted copy"})
                        self.assertEqual(duplicate.status_code, 201, duplicate.text)
                        copied = client.get(f"/api/v2/projects/{duplicate.json()['id']}/workspace").json()
                        self.assertEqual(copied["draft"]["workflow"]["nodes"], saved["draft"]["workflow"]["nodes"])
                finally:
                    reopened.state.run_runtime.shutdown()
