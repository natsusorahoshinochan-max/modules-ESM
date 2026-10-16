"""The bundled original research survives public reading and archive round trips."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.bootstrap import create_application
from protein_workbench_public.example_results import export_example_results, install_example_results


RESOURCE = Path(__file__).resolve().parents[1] / "examples/v2/webui-3gb1.results.zip"


class ExampleResultsPreservationTests(unittest.TestCase):
    def test_original_example_reads_and_round_trips_without_reinterpreting_its_workflow(self):
        with ZipFile(RESOURCE) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
            manifest = json.loads(original["manifest.json"])
        project_id, run_id = manifest["project_id"], manifest["run_id"]
        run_path = f"/api/v2/projects/{project_id}/runs/{run_id}"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(root / "source")}):
                app = create_application()
                self.addCleanup(app.state.run_runtime.shutdown)
                with TestClient(app) as client:
                    run = client.get(run_path)
                    self.assertEqual(run.status_code, 200, run.text)
                    recorded = run.json()
                    self.assertEqual(recorded["status"], "succeeded")
                    self.assertEqual(recorded["workflow_commit_id"], manifest["workflow_commit_id"])
                    self.assertEqual(recorded["ledger_cursor"], manifest["terminal_cursor"])
                    commit_path = f"/api/v2/projects/{project_id}/workflow/commits/{manifest['workflow_commit_id']}"
                    commit = client.get(commit_path)
                    self.assertEqual(commit.status_code, 200, commit.text)
                    original_commit = json.loads(original[next(item["file"]["path"] for item in
                        manifest["workflow_records"] if item["collection"] == "commits")])
                    self.assertEqual(commit.json()["workflow"], original_commit["workflow"])
                    values = {}
                    for output in recorded["outputs"]:
                        for index in range(output["value_count"]):
                            location = f"/outputs/{output['node_id']}/{output['output_port']}/values/{index}"
                            value = client.get(run_path + location)
                            self.assertEqual(value.status_code, 200, value.text)
                            values[location] = value.json()
                    projects = app.state.project_manager
                    destination = root / "exported.zip"
                    export_example_results(projects=projects, authoring=app.state.workflow_authoring,
                        results=ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects)),
                        run_id=run_id, destination=destination)
            with ZipFile(destination) as exported:
                for name, payload in original.items():
                    if name not in {"manifest.json", "readings.json"}:
                        self.assertEqual(exported.read(name), payload, name)
            imported_root = root / "roundtrip"
            projects = ProjectManager(imported_root / "projects", cache_root=imported_root / "cache",
                output_root=imported_root / "outputs", run_root=imported_root / "runs")
            authoring = WorkflowAuthoringService(projects, app.state.frozen_catalog)
            self.assertEqual(install_example_results(resource=destination, projects=projects,
                authoring=authoring), run_id)
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(imported_root)}):
                imported = create_application()
                self.addCleanup(imported.state.run_runtime.shutdown)
                with TestClient(imported) as client:
                    self.assertEqual(client.get(run_path).json(), recorded)
                    self.assertEqual(client.get(commit_path).json(), commit.json())
                    for location, value in values.items():
                        self.assertEqual(client.get(run_path + location).json(), value)
                    projects = imported.state.project_manager
                    roundtrip = root / "roundtrip.zip"
                    export_example_results(projects=projects, authoring=imported.state.workflow_authoring,
                        results=ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects)),
                        run_id=run_id, destination=roundtrip)
            with ZipFile(roundtrip) as exported:
                for name, payload in original.items():
                    if name not in {"manifest.json", "readings.json"}:
                        self.assertEqual(exported.read(name), payload, name)
