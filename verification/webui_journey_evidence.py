"""Produce the representative real FASTA WebUI journey through public APIs."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.project.storage import write_new_file_durable
from protein_workbench_public.bootstrap import create_application
from protein_workbench_public.provider_environment import provider_environment_configuration
from verification.acceptance_campaign import ExecutionProfile


FASTA_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "modules/solubility/fixtures/protein_sol_input.fasta"
)
FOLD_SEED = 2719001
CANDIDATE_STAGES = (
    ("import-fasta", "sequence_candidates"),
    ("prefilter-solubility", "candidates"),
    ("fold", "structure_candidates"),
    ("rank-confidence", "candidates"),
    ("postfilter-confidence", "candidates"),
    ("passing-ranked-candidates", "candidates"),
)


def fasta_journey_workflow(project_id: str, project_input_ref: str) -> dict[str, Any]:
    """Declare the fixed representative workflow using production contracts."""
    def node(
        node_id: str, node_type_id: str, binding_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "node_id": node_id, "node_type_id": node_type_id,
            "binding_id": binding_id, "node_parameters": parameters,
            "binding_parameters": {},
        }

    def edge(source: str, output: str, target: str, input_port: str) -> dict[str, str]:
        return {
            "source_node_id": source, "source_port": output,
            "target_node_id": target, "target_port": input_port,
        }

    confidence = {
        "score_collection_input": {
            "node_id": "materialize-confidence", "output_port": "observations",
        },
        "source_partition": "prediction_confidence",
        "metric": {"contract_kind": "metric", "contract_id": "structure.plddt.mean_residue"},
        "method": {
            "contract_kind": "method",
            "contract_id": "folding.fold.esmfold2_fast_biohub_2026_05",
        },
        "context_selector": {"kind": "intrinsic"},
        "match_cardinality": "exactly_one", "missing_policy": "error",
    }
    return {
        "schema_version": "2.1.0", "workflow_id": project_id,
        "nodes": [
            node("import-fasta", "protein_io.import_sequences", "protein_io.import_sequences.direct", {
                "project_input_ref": project_input_ref,
            }),
            node("score-solubility", "solubility.score_sequence", "solubility.protein_sol.local", {}),
            node("prefilter-solubility", "selection.filter", "selection.filter.direct", {
                "selector_ids": ["protein-sol-scaled"],
                "expression": [{"selector_index": 0, "operator": ">=", "threshold": 0.446}],
                "out_of_scope_policy": "ignore",
            }),
            node("fold", "folding.fold", "folding.fold.esmfold2_remote", {
                "effective_seed": FOLD_SEED, "num_samples": 1,
            }),
            node("materialize-confidence", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct", {}),
            node("rank-confidence", "selection.sort", "selection.sort.direct", {
                "objective_id": "rank-mean-plddt", "out_of_scope_policy": "ignore",
                "tie_policy": "candidate_id_ascending",
            }),
            node("postfilter-confidence", "selection.filter", "selection.filter.direct", {
                "selector_ids": ["fold-mean-plddt"],
                "expression": [{"selector_index": 0, "operator": ">=", "threshold": 70}],
                "out_of_scope_policy": "ignore",
            }),
            node("passing-ranked-candidates", "collection_ops.intersect_candidates", "collection_ops.intersect_candidates.direct", {}),
        ],
        "edges": [
            edge("import-fasta", "sequence_candidates", "score-solubility", "sequence_candidates"),
            edge("import-fasta", "sequence_candidates", "prefilter-solubility", "candidates"),
            edge("score-solubility", "scores", "prefilter-solubility", "scores"),
            edge("prefilter-solubility", "candidates", "fold", "sequence_candidates"),
            edge("fold", "structure_candidates", "materialize-confidence", "structure_candidates"),
            edge("fold", "confidence_facts", "materialize-confidence", "confidence_facts"),
            edge("fold", "structure_candidates", "rank-confidence", "candidates"),
            edge("materialize-confidence", "observations", "rank-confidence", "scores"),
            edge("fold", "structure_candidates", "postfilter-confidence", "candidates"),
            edge("materialize-confidence", "observations", "postfilter-confidence", "scores"),
            edge("rank-confidence", "candidates", "passing-ranked-candidates", "candidates_a"),
            edge("postfilter-confidence", "candidates", "passing-ranked-candidates", "candidates_b"),
        ],
        "observation_selectors": [
            {
                "selector_id": "protein-sol-scaled",
                "candidate_input": {"node_id": "import-fasta", "output_port": "sequence_candidates"},
                "score_collection_input": {"node_id": "score-solubility", "output_port": "scores"},
                "source_partition": "protein_sol_scaled",
                "metric": {"contract_kind": "metric", "contract_id": "solubility.protein_sol_scaled"},
                "method": {"contract_kind": "method", "contract_id": "solubility.protein_sol.sequence_prediction_2017"},
                "context_selector": {
                    "kind": "calibration", "calibration_metric": "population_scaled_solubility",
                    "calibration_value": 0.446, "calibration_unit": "dimensionless",
                    "population_id": "niwa_non_membrane_2396",
                },
                "match_cardinality": "exactly_one", "missing_policy": "error",
            },
            {
                "selector_id": "fold-mean-plddt",
                "candidate_input": {"node_id": "fold", "output_port": "structure_candidates"},
                **confidence,
            },
        ],
        "selection_objectives": [{
            "objective_id": "rank-mean-plddt",
            "candidate_input": {"node_id": "fold", "output_port": "structure_candidates"},
            **confidence,
            "utility_transform": {
                "contract_kind": "utility_transform",
                "contract_id": "structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit",
            },
            "utility_parameters": {}, "weight": 1.0,
        }],
    }


def _json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    return response.json()


def _write(evidence_directory: Path, filename: str, value: Any) -> None:
    write_new_file_durable(
        evidence_directory, (filename,),
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def prepare_fasta_journey(client: TestClient, evidence_directory: Path) -> dict[str, Any]:
    """Upload the exact fixture and commit the full workflow without executing it."""
    project = _json(client.post("/api/v2/projects", json={"name": "Real FASTA screening journey"}))
    project_id = project["id"]
    base = f"/api/v2/projects/{project_id}"
    published = _json(client.post(f"{base}/inputs", json={
        "filename": FASTA_SOURCE.name,
        "content_base64": base64.b64encode(FASTA_SOURCE.read_bytes()).decode("ascii"),
    }))
    inspection = _json(client.post(
        f"{base}/inputs/{published['project_input_ref']}:inspect", json={"format": "fasta"},
    ))
    workflow = fasta_journey_workflow(project_id, published["project_input_ref"])
    _json(client.put(f"{base}/workflow/draft", json={"workflow": workflow}))
    committed = _json(client.post(f"{base}/workflow:commit", json={"workflow": workflow}))
    _write(evidence_directory, "workflow.json", workflow)
    _write(evidence_directory, "input.json", {"publication": published, "inspection": inspection})
    _write(evidence_directory, "commit.json", committed)
    admission = {
        "project_id": project_id, "workflow_commit_id": committed["workflow_commit_id"],
        "project_input_ref": published["project_input_ref"],
    }
    _write(evidence_directory, "admission.json", admission)
    return admission


def _fresh_application(data_root: Path, profile_path: Path, evidence_directory: Path) -> FastAPI:
    if data_root.exists():
        raise FileExistsError(f"Real journey generation requires a new data root: {data_root}")
    if evidence_directory.exists():
        raise FileExistsError(evidence_directory)
    environment = ExecutionProfile.load(profile_path).complete_environment()
    environment["PROTEIN_WORKBENCH_DATA_ROOT"] = str(data_root)
    os.environ.clear()
    os.environ.update(environment)
    return create_application(
        v2_environment_configuration=provider_environment_configuration(environment),
    )


def prepare(data_root: Path, profile_path: Path, evidence_directory: Path) -> dict[str, Any]:
    """Prepare the real Project for a browser to start its first Run."""
    app = _fresh_application(data_root, profile_path, evidence_directory)
    with TestClient(app) as client:
        return prepare_fasta_journey(client, evidence_directory)


def _report(
    client: httpx.Client, admission: dict[str, Any], run_id: str,
    evidence_directory: Path,
) -> dict[str, Any]:
    project_id = admission["project_id"]
    run_base = f"/api/v2/projects/{project_id}/runs/{run_id}"
    projection = _json(client.get(run_base))
    if projection["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        raise ValueError("Journey report requires a terminal Run; it never starts or cancels a Run")
    if projection["scope"]["mode"] != "full":
        raise ValueError("The representative journey requires a full Run")
    snapshot = _json(client.get(
        f"/api/v2/projects/{project_id}/workflow/commits/{projection['workflow_commit_id']}",
    ))
    prepared = json.loads((evidence_directory / "commit.json").read_bytes())
    if (snapshot["workflow"], snapshot["scientific_definitions"]) != (
        prepared["workflow"], prepared["scientific_definitions"],
    ):
        raise ValueError("The Run's original Workflow and science differ from the prepared journey")
    _write(evidence_directory, "run-commit.json", snapshot)
    _write(evidence_directory, "projection.json", projection)
    stages: list[dict[str, Any]] = []
    published_outputs = {
        (output["node_id"], output["output_port"])
        for output in projection["outputs"]
    }
    for node_id, output_port in CANDIDATE_STAGES:
        if (node_id, output_port) not in published_outputs:
            continue
        page = _json(client.post(f"{run_base}/results:collection", json={
            "node_id": node_id, "output_port": output_port,
            "value_index": 0, "offset": 0, "limit": 10,
        }))
        stages.append({"node_id": node_id, "output_port": output_port, **page})
    _write(evidence_directory, "stages.json", stages)
    report = {
        **admission,
        "prepared_workflow_commit_id": admission["workflow_commit_id"],
        "workflow_commit_id": projection["workflow_commit_id"],
        "run_id": run_id, "status": projection["status"],
        "effective_seed": FOLD_SEED,
        "stage_counts": {stage["node_id"]: stage["total"] for stage in stages},
        "candidate_stages": [{
            "node_id": stage["node_id"], "output_port": stage["output_port"],
            "references": [item["reference"] for item in stage["items"]],
        } for stage in stages],
    }
    _write(evidence_directory, "report.json", report)
    return report


def run(data_root: Path, profile_path: Path, evidence_directory: Path) -> dict[str, Any]:
    """Alternative script entry: prepare and execute once with real Providers."""
    app = _fresh_application(data_root, profile_path, evidence_directory)
    with TestClient(app) as client:
        admission = prepare_fasta_journey(client, evidence_directory)
        project_id = admission["project_id"]
        receipt = _json(client.post(f"/api/v2/projects/{project_id}/runs", json={
            "workflow_commit_id": admission["workflow_commit_id"],
            "client_request_id": "real-fasta-screening-journey",
            "scope": {"mode": "full", "node_ids": []},
        }))
        _write(evidence_directory, "run-receipt.json", receipt)
        print(json.dumps({"event": "journey_admitted", **admission, "run_id": receipt["run_id"]}), flush=True)
        run_base = f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}"
        events: list[dict[str, Any]] = []
        with client.websocket_connect(f"{run_base}/events") as websocket:
            while True:
                event = websocket.receive_json()
                events.append(event)
                if event["event"]["type"] == "run_terminal":
                    break
        _write(evidence_directory, "events.json", events)
        report = _report(client, admission, receipt["run_id"], evidence_directory)
    if report["status"] != "succeeded":
        raise RuntimeError(
            f"Real journey Run {report['run_id']} ended {report['status']}; "
            "original evidence remains in the data root and evidence directory"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        operation = commands.add_parser(command)
        operation.add_argument("--data-root", type=Path, required=True)
        operation.add_argument("--profile", type=Path, required=True)
        operation.add_argument("--evidence-directory", type=Path, required=True)
    reporting = commands.add_parser("report")
    reporting.add_argument("--base-url", required=True)
    reporting.add_argument("--run-id", required=True)
    reporting.add_argument("--evidence-directory", type=Path, required=True)
    args = parser.parse_args()
    evidence_directory = args.evidence_directory.resolve()
    if args.command == "report":
        admission = json.loads((evidence_directory / "admission.json").read_bytes())
        with httpx.Client(base_url=args.base_url, trust_env=False) as client:
            report = _report(client, admission, args.run_id, evidence_directory)
    else:
        operation = prepare if args.command == "prepare" else run
        report = operation(args.data_root.resolve(), args.profile.resolve(), evidence_directory)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
