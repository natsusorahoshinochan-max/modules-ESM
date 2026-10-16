"""Public catalog and workspace boundaries for module-owned scoring choices."""

from pathlib import Path
from tempfile import TemporaryDirectory
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
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.http.app import create_http_app
from protein_workbench_public.protocol import validate_schema
from tests.scoring_fixture import registration


class ScoringChoiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        registrations = (*module_registrations(), registration())
        catalog = build_frozen_catalog(registrations)
        projects = ProjectManager(root / "projects", cache_root=root / "cache", output_root=root / "outputs", run_root=root / "runs")
        authoring = WorkflowAuthoringService(projects, catalog)
        store = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
        runtime = V2RunService(projects, catalog, authoring,
            NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), store), store)
        self.client = TestClient(create_http_app(catalog, projects, authoring, runtime,
            authoring_projection=build_authoring_capability_projection(registrations, catalog)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_official_and_external_modules_publish_scoring_meaning_and_conditions(self):
        response = self.client.get("/api/v2/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        choices = {item["reference"]["contract_id"]: item["descriptor"]
                   for item in response.json()["contracts"]
                   if item["reference"]["contract_kind"] == "utility_transform"}
        external = choices["scoring_fixture.success_fraction.native"]
        self.assertEqual(external["title"], "成功试验比例（原始尺度）")
        self.assertIn("本组试验全部成功", external["meaning"])
        self.assertIn("intrinsic", external["applicability"])
        self.assertIn("不能视为已经校准", external["limitations"][0])
        official = choices["structure_comparison.tm_score.explicit_relation.identity"]
        self.assertIn("TM-score", official["title"])
        self.assertIn("reference", official["applicability"])
        self.assertTrue(official["meaning"])
        self.assertTrue(official["limitations"])

    def test_unjustified_plddt_representation_conversions_are_not_weighted_choices(self):
        response = self.client.get("/api/v2/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        transforms = {item["reference"]["contract_id"] for item in response.json()["contracts"]
                      if item["reference"]["contract_kind"] == "utility_transform"}
        self.assertEqual(transforms, {"structure_comparison.tm_score.explicit_relation.identity",
                                     "scoring_fixture.success_fraction.native"})

    def test_weighted_choice_is_manually_saved_and_reopened_without_formula_endpoints(self):
        project = self.client.post("/api/v2/projects", json={"name": "Trial scoring"}).json()["id"]
        parameters = {"objectives": [{"selection": {
            "score_input": "trials", "metric_id": "scoring_fixture.success_fraction",
            "method_id": "scoring_fixture.trials", "source_partition": "trials", "context": {"kind": "intrinsic"}},
            "transform_id": "scoring_fixture.success_fraction.native", "weight": 2}]}
        workflow = {"schema_version": "2.1.0", "workflow_id": project, "nodes": [{
            "node_id": "rank", "node_type_id": "selection.weighted_rank", "binding_id": "selection.weighted_rank.direct",
            "node_parameters": parameters, "binding_parameters": {}}], "edges": [],
            "selection_objectives": [], "observation_selectors": []}
        saved = self.client.put(f"/api/v2/projects/{project}/workspace", json={"workflow": workflow, "ui_state": {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f"/api/v2/projects/{project}/workspace")
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(reopened.json()["draft"]["workflow"]["nodes"][0]["node_parameters"], parameters)
        self.assertEqual(reopened.json()["draft"]["workflow"]["selection_objectives"], [])

    def test_weighted_calculation_is_available_for_module_owned_choices(self):
        response = self.client.get("/api/v2/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        availability = next(item for item in response.json()["availability"]
                            if item["binding"]["contract_id"] == "selection.weighted_rank.direct")
        self.assertTrue(availability["available"])

    def test_binding_scientific_behaviors_are_valid_public_contract_descriptors(self):
        response = self.client.get("/api/v2/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        for contract in response.json()['contracts']:
            if contract['reference']['contract_kind'] == 'binding':
                validate_schema('#/$defs/BindingContractDescriptor', contract['descriptor'])


if __name__ == "__main__":
    unittest.main()
