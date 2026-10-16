"""Public Run behavior with controlled official SDK outcomes; no model is run."""
from __future__ import annotations

import base64
import os
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import torch
from esm.sdk.api import ESMProteinError

from protein_workbench_public.bootstrap import create_application


PDB = (
    "ATOM      1  N   ALA A   1      -1.000   0.000   0.000  1.00 80.00           N  \n"
    "ATOM      2  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C  \n"
    "ATOM      3  C   ALA A   1       1.000   0.000   0.000  1.00 80.00           C  \n"
    "ATOM      4  O   ALA A   1       2.000   0.000   0.000  1.00 80.00           O  \nEND\n"
)


class ControlledBiohub:
    """The SDK boundary returns one success, one defined failure, then success."""

    def __init__(self, failures: tuple[int, ...] = (2,)) -> None:
        self.failures = failures
        self.requests: list[tuple[str, str, object]] = []

    def fold(self, *, sequence: str, model_name: str, config: object) -> object:
        self.requests.append((sequence, model_name, config))
        if len(self.requests) in self.failures:
            return ESMProteinError(500, "Controlled exhausted Provider request")
        return SimpleNamespace(
            plddt=torch.tensor([0.8]), ptm=torch.tensor(0.7), pae=torch.tensor([[0.0]]),
            to_protein_chain=lambda: SimpleNamespace(to_pdb_string=lambda: PDB),
        )

    def close(self) -> None:
        pass


class FailedBatchContinuation(unittest.TestCase):
    def json_request(self, client: TestClient, method: str, url: str, **kwargs):
        response = client.request(method, url, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def wait_for_run(self, client: TestClient, base: str, run_id: str):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            value = self.json_request(client, "GET", f"{base}/runs/{run_id}")
            if value["status"] not in {"admitted", "running"}:
                return value
            time.sleep(0.01)
        self.fail("Run did not finish within 15 seconds")

    def read_output(self, client: TestClient, base: str, run_id: str, port: str):
        return self.json_request(
            client, "GET", f"{base}/runs/{run_id}/outputs/fold/{port}/values/0",
        )

    def create_batch(self, client: TestClient):
        self.json_request(client, "PATCH", "/api/v2/module-settings/folding.fold.esmfold2_remote", json={
            "values": {"credential_handle": "controlled-sdk-only", "service_url": "https://biohub.ai"},
        })
        project = self.json_request(client, "POST", "/api/v2/projects", json={"name": "Continue folding"})
        base = f'/api/v2/projects/{project["id"]}'
        source = self.json_request(client, "POST", f"{base}/inputs", json={
            "filename": "one.fasta", "content_base64": base64.b64encode(b">one\nA\n").decode(),
        })
        def node(node_id, node_type, binding, params=None):
            return {"node_id": node_id, "node_type_id": node_type,
                    "binding_id": binding, "node_parameters": params or {}, "binding_parameters": {}}
        workflow = {"schema_version": "2.1.0", "workflow_id": project["id"], "nodes": [
            node("input", "protein_io.import_sequences", "protein_io.import_sequences.direct",
                 {"project_input_ref": source["project_input_ref"]}),
            node("fold", "folding.fold", "folding.fold.esmfold2_remote", {"num_samples": 3}),
            node("confidence", "structure_prediction.materialize_confidence", "structure_prediction.materialize_confidence.direct"),
            node("independent", "protein_io.import_sequences", "protein_io.import_sequences.direct",
                 {"project_input_ref": source["project_input_ref"]}),
        ], "edges": [
            {"source_node_id": "input", "source_port": "sequence_candidates", "target_node_id": "fold", "target_port": "sequence_candidates"},
            *[{"source_node_id": "fold", "source_port": port, "target_node_id": "confidence", "target_port": port}
              for port in ("structure_candidates", "confidence_facts")],
        ]}
        commit = self.json_request(client, "POST", f"{base}/workflow:commit", json={"workflow": workflow})
        return base, commit

    def test_user_continues_original_batch_after_reopening_without_repeating_success(self):
        provider = ControlledBiohub()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "PROTEIN_WORKBENCH_DATA_ROOT": root,
        }), patch("esm.sdk.esmfold2_client", return_value=provider):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.create_batch(client)
                receipt = self.json_request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "original",
                })
                source_id = receipt["run_id"]
                failed = self.wait_for_run(client, base, source_id)
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["continuable_node_ids"], ["fold"])
                outcomes = {n["node_id"]: n["outcome"] for n in failed["node_dispositions"]}
                self.assertEqual(outcomes, {"input": "succeeded", "fold": "failed", "confidence": "blocked", "independent": "succeeded"})
                first = self.read_output(client, base, source_id, "structure_candidates")
                first_confidence = self.read_output(client, base, source_id, "confidence_facts")
                self.assertEqual(len(provider.requests), 2, "Stop unstarted requests after failure")
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.read_output(client, base, source_id, "structure_candidates"), first)
                resumed = self.json_request(client, "POST", f"{base}/runs:derive", json={
                    "source_run_id": source_id, "policy": "continue_batch", "node_ids": ["fold"], "client_request_id": "continue",
                })
                complete = self.wait_for_run(client, base, resumed["run_id"])
                self.assertEqual(complete["status"], "succeeded", complete)
                self.assertEqual(complete["continuable_node_ids"], [])
                self.assertEqual(complete["workflow_commit_id"], commit["workflow_commit_id"])
                self.assertEqual(len(provider.requests), 4, "Only failed and unstarted samples are retried")
                structures = self.read_output(client, base, resumed["run_id"], "structure_candidates")
                confidence = self.read_output(client, base, resumed["run_id"], "confidence_facts")
                self.assertEqual(structures["value"]["fields"]["items"][0], first["value"]["fields"]["items"][0])
                self.assertEqual(len(structures["value"]["fields"]["items"]), 3)
                self.assertEqual(confidence["value"]["entries"][0], first_confidence["value"]["entries"][0])
                self.assertEqual(self.read_output(client, base, source_id, "structure_candidates"), first)

    def test_empty_failure_and_repeated_failure_keep_the_remaining_batch(self):
        provider = ControlledBiohub(failures=(1, 3))
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "PROTEIN_WORKBENCH_DATA_ROOT": root,
        }), patch("esm.sdk.esmfold2_client", return_value=provider):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.create_batch(client)
                receipt = self.json_request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "empty",
                })
                empty = self.wait_for_run(client, base, receipt["run_id"])
                self.assertEqual(empty["status"], "failed")
                self.assertEqual(empty["continuable_node_ids"], ["fold"])
                self.assertFalse(any(output["node_id"] == "fold" for output in empty["outputs"]))
                self.assertEqual(len(provider.requests), 1)
                receipt = self.json_request(client, "POST", f"{base}/runs:derive", json={
                    "source_run_id": empty["run_id"], "policy": "continue_batch", "node_ids": ["fold"], "client_request_id": "again",
                })
                partial = self.wait_for_run(client, base, receipt["run_id"])
                self.assertEqual(partial["status"], "failed")
                self.assertEqual(partial["continuable_node_ids"], ["fold"])
                self.assertEqual(len(provider.requests), 3)
                retained = self.read_output(client, base, partial["run_id"], "structure_candidates")
                self.assertEqual(len(retained["value"]["fields"]["items"]), 1)
                receipt = self.json_request(client, "POST", f"{base}/runs:derive", json={
                    "source_run_id": partial["run_id"], "policy": "continue_batch", "node_ids": ["fold"], "client_request_id": "finish",
                })
                complete = self.wait_for_run(client, base, receipt["run_id"])
                self.assertEqual(complete["status"], "succeeded", complete)
                self.assertEqual(complete["continuable_node_ids"], [])
                self.assertEqual(len(provider.requests), 5)
                final = self.read_output(client, base, complete["run_id"], "structure_candidates")
                self.assertEqual(len(final["value"]["fields"]["items"]), 3)
                self.assertEqual(final["value"]["fields"]["items"][0], retained["value"]["fields"]["items"][0])

    def test_changed_calculation_parameters_start_a_new_batch(self):
        provider = ControlledBiohub()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "PROTEIN_WORKBENCH_DATA_ROOT": root,
        }), patch("esm.sdk.esmfold2_client", return_value=provider):
            with TestClient(create_application(load_example_results=False)) as client:
                base, original = self.create_batch(client)
                started = self.json_request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": original["workflow_commit_id"], "client_request_id": "original",
                })
                failed = self.wait_for_run(client, base, started["run_id"])
                self.assertEqual(failed["status"], "failed")
                snapshot = self.json_request(client, "GET", f'{base}/workflow/commits/{original["workflow_commit_id"]}')
                workflow = snapshot["workflow"]
                fold = next(node for node in workflow["nodes"] if node["node_id"] == "fold")
                fold["node_parameters"]["num_samples"] = 2
                fold["binding_parameters"]["num_loops"] = 7
                changed = self.json_request(client, "POST", f"{base}/workflow:commit", json={"workflow": workflow})
                started = self.json_request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": changed["workflow_commit_id"], "client_request_id": "new-calculation",
                })
                complete = self.wait_for_run(client, base, started["run_id"])
                self.assertEqual(complete["status"], "succeeded", complete)
                self.assertEqual(len(provider.requests), 4, "Changed parameters execute both samples anew")
                self.assertEqual([request[2].num_loops for request in provider.requests[2:]], [7, 7])
                structures = self.read_output(client, base, started["run_id"], "structure_candidates")
                self.assertEqual(len(structures["value"]["fields"]["items"]), 2)


if __name__ == "__main__":
    unittest.main()
