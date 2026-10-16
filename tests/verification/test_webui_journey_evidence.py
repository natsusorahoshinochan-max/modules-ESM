"""Contract preparation for the separately executed real-Provider journey."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from core.catalog.builder import build_frozen_catalog
from core.workflow.compiler import CompilationRequest, compile
from core.workflow.errors import WorkflowCompileError
from protein_workbench_public.bootstrap import create_application, module_registrations
from protein_workbench_public.workflow_codec import decode_workflow_document
from tests.support.public_runs import PublicRunClient
from verification.webui_journey_evidence import (
    FOLD_SEED, _report, fasta_journey_workflow, prepare_fasta_journey,
)


def test_real_fasta_journey_compiles_with_exact_production_science() -> None:
    workflow = decode_workflow_document(fasta_journey_workflow("fasta-journey", "source.fasta"))
    plan = compile(CompilationRequest(workflow), build_frozen_catalog(module_registrations()))
    nodes = {node.node_id: node for node in plan.nodes}
    assert nodes["fold"].method.contract_id == "folding.fold.esmfold2_fast_biohub_2026_05"
    assert nodes["fold"].node_parameters["effective_seed"] == FOLD_SEED
    assert nodes["prefilter-solubility"].node_parameters["expression"] == (
        {"selector_index": 0, "operator": ">=", "threshold": 0.446},
    )
    assert nodes["postfilter-confidence"].node_parameters["expression"] == (
        {"selector_index": 0, "operator": ">=", "threshold": 70},
    )
    assert len(plan.observation_selectors) == 2
    assert len(plan.selection_objectives) == 1
    assert plan.observation_selectors[1].candidate_input.node_id == "fold"
    assert plan.observation_selectors[1].candidate_input.output_port == "structure_candidates"
    assert {
        (edge.source_node_id, edge.source_port, edge.target_port)
        for edge in plan.edges if edge.target_node_id == "passing-ranked-candidates"
    } == {
        ("rank-confidence", "candidates", "candidates_a"),
        ("postfilter-confidence", "candidates", "candidates_b"),
    }


def test_ranked_stage_directly_consumes_original_confidence_observations() -> None:
    payload = fasta_journey_workflow("fasta-journey", "source.fasta")
    payload["observation_selectors"][1]["candidate_input"] = {
        "node_id": "rank-confidence", "output_port": "candidates",
    }
    for edge in payload["edges"]:
        if edge["target_node_id"] == "postfilter-confidence" and edge["target_port"] == "candidates":
            edge.update(source_node_id="rank-confidence", source_port="candidates")
    plan = compile(
        CompilationRequest(decode_workflow_document(payload)),
        build_frozen_catalog(module_registrations()),
    )
    assert plan.observation_selectors[1].candidate_input.node_id == "rank-confidence"


def test_public_preparation_imports_two_real_records_without_provider_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    evidence = tmp_path / "evidence"
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(data_root))
    with TestClient(create_application(v2_environment_configuration={}, load_example_results=False)) as client:
        admission = prepare_fasta_journey(client, evidence)
        project_id = admission["project_id"]
        projects = client.get("/api/v2/projects").json()["projects"]
        assert next(project for project in projects if project["id"] == project_id)["latest_run_id"] is None
        inspected = json.loads((evidence / "input.json").read_bytes())["inspection"]
        assert [record["display_name"] for record in inspected["records"]] == ["116415", "ubiquitin"]
        public = PublicRunClient(client)
        receipt = public.request("start_run", {
            "project_id": project_id,
            "workflow_commit_id": admission["workflow_commit_id"],
            "client_request_id": "import-real-journey-records-only",
            "scope": {"mode": "to_node", "node_ids": ["import-fasta"]},
        }, expected_status=202)
        projection = public.wait_terminal(project_id, receipt["run_id"])
        assert projection["status"] == "succeeded"
        assert projection["scope"]["execution_node_ids"] == ["import-fasta"]
        page = public.request("result_collection", {
            "project_id": project_id, "run_id": receipt["run_id"],
            "node_id": "import-fasta", "output_port": "sequence_candidates",
            "value_index": 0, "offset": 0, "limit": 10,
        }, expected_status=200)
        assert page["total"] == 2
        assert [item["sequence"][:8] for item in page["items"]] == ["MTTSIQRR", "MQIFVKTL"]
        assert len({item["reference"]["candidate_id"] for item in page["items"]}) == 2
        assert all(item["parent_ids"] == [] for item in page["items"])
        with pytest.raises(ValueError, match="requires a full Run"):
            _report(client, admission, receipt["run_id"], evidence)
        assert not (evidence / "report.json").exists()
