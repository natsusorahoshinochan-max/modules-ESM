"""Ordinary scientific publication through the public application boundary."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
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
from modules.selection.package import MODULE_PACKAGE as SELECTION
from protein_workbench_public.http.app import create_http_app
from tests.scoring_fixture import registration


class ScientificPublicationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        registrations = (registration(), SELECTION)
        catalog = build_frozen_catalog(registrations)
        projects = ProjectManager(root / "projects", cache_root=root / "cache",
                                  output_root=root / "outputs", run_root=root / "runs")
        authoring = WorkflowAuthoringService(projects, catalog)
        store = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
        runtime = V2RunService(projects, catalog, authoring,
            NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), store), store)
        self.client = TestClient(create_http_app(catalog, projects, authoring, runtime,
            authoring_projection=build_authoring_capability_projection(registrations, catalog)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        response = self.client.post("/api/v2/projects", json={"name": "Trial measurements"})
        self.assertEqual(response.status_code, 201, response.text)
        self.project = response.json()["id"]

    def workflow(self):
        return {
            "schema_version": "2.1.0", "workflow_id": self.project,
            "nodes": [
                {"node_id": "population", "node_type_id": "scoring_fixture.population",
                 "binding_id": "scoring_fixture.population.direct", "node_parameters": {}, "binding_parameters": {}},
                {"node_id": "measurements", "node_type_id": "scoring_fixture.measurements",
                 "binding_id": "scoring_fixture.measurements.direct", "node_parameters": {"values": [0.8, 0.4, 0.6]}, "binding_parameters": {}},
            ],
            "edges": [{"source_node_id": "population", "source_port": "candidates",
                       "target_node_id": "measurements", "target_port": "candidates"}],
        }

    def execute(self, workflow):
        committed = self.client.post(f"/api/v2/projects/{self.project}/workflow:commit", json={"workflow": workflow})
        self.assertEqual(committed.status_code, 200, committed.text)
        started = self.client.post(f"/api/v2/projects/{self.project}/runs", json={
            "workflow_commit_id": committed.json()["workflow_commit_id"], "client_request_id": "publish-trials"})
        self.assertEqual(started.status_code, 202, started.text)
        run_path = f"/api/v2/projects/{self.project}/runs/{started.json()['run_id']}"
        for _ in range(200):
            response = self.client.get(run_path)
            self.assertEqual(response.status_code, 200, response.text)
            projection = response.json()
            if projection["status"] not in ("admitted", "running"):
                return run_path, projection
            time.sleep(0.01)
        self.fail("Trial publication did not finish")

    def read_events(self, run_path):
        events = []
        with self.client.websocket_connect(run_path + "/events") as stream:
            while True:
                message = stream.receive_json()
                if message["event"]["type"] == "replay_complete":
                    return events
                if message["event"]["type"] != "replay_started":
                    events.append(message["event"])

    def test_scientific_measurements_publish_readable_scores_and_replay_from_cache(self):
        workflow = self.workflow()
        first_path, first = self.execute(workflow)
        self.assertEqual(first["status"], "succeeded", first)
        value = self.client.get(first_path + "/outputs/measurements/scores/values/0")
        self.assertEqual(value.status_code, 200, value.text)
        observations = value.json()["value"]["fields"]["entries"]
        self.assertEqual([item["fields"]["value"] for item in observations], [0.8, 0.4, 0.6])
        second_path, second = self.execute(workflow)
        self.assertEqual(second["status"], "succeeded", second)
        self.assertEqual({item["resolution"] for item in second["node_dispositions"]}, {"cache_replayed"})
        self.assertEqual(self.client.get(second_path + "/outputs/measurements/scores/values/0").json(), value.json())
        events = self.read_events(second_path)
        self.assertEqual(events[-1], {"type": "run_terminal", "status": "succeeded"})
        self.assertFalse(any(event["type"] == "operation_attempt_started" for event in events))

    def test_run_scope_describes_only_ordinary_node_execution(self):
        _, projection = self.execute(self.workflow())
        self.assertEqual(projection["scope"], {
            "mode": "full", "selected_node_ids": [],
            "execution_node_ids": ["population", "measurements"],
            "forced_node_ids": [], "reused_node_ids": [], "out_of_scope_node_ids": [],
        })

    def test_module_result_reading_exposes_the_exact_published_value_digest(self):
        run_path, projection = self.execute(self.workflow())
        self.assertEqual(projection["status"], "succeeded", projection)
        canonical = self.client.get(run_path + "/outputs/measurements/scores/values/0")
        self.assertEqual(canonical.status_code, 200, canonical.text)
        reading = self.client.post(run_path + "/results:value", json={
            "node_id": "measurements", "output_port": "scores", "value_index": 0,
        })
        self.assertEqual(reading.status_code, 200, reading.text)
        self.assertEqual(reading.json()["value_content_digest"], canonical.headers["Digest"])

    def test_failed_measurement_keeps_an_independent_scientific_publication_readable(self):
        workflow = self.workflow()
        workflow["nodes"][1]["node_parameters"] = {"values": [0.8, 0.4]}
        workflow["nodes"].append({
            **workflow["nodes"][1], "node_id": "independent",
            "node_parameters": {"values": [0.7, 0.3, 0.5]},
        })
        workflow["edges"].append({**workflow["edges"][0], "target_node_id": "independent"})
        run_path, projection = self.execute(workflow)
        self.assertEqual(projection["status"], "failed", projection)
        self.assertEqual({item["node_id"]: item["outcome"] for item in projection["node_dispositions"]}, {
            "population": "succeeded", "measurements": "failed", "independent": "succeeded",
        })
        value = self.client.get(run_path + "/outputs/independent/scores/values/0")
        self.assertEqual(value.status_code, 200, value.text)
        self.assertEqual([item["fields"]["value"] for item in value.json()["value"]["fields"]["entries"]], [0.7, 0.3, 0.5])
        events = self.read_events(run_path)
        self.assertTrue(any(event["type"] == "node_attempt_terminal" and event["status"] == "failed"
                            and event["failure_origin"] == "operation" for event in events))
        self.assertEqual(events[-1], {"type": "run_terminal", "status": "failed"})


if __name__ == "__main__":
    unittest.main()
