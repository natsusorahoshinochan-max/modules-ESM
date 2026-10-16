"""ESM3 continuation through public Runs and controlled official SDK responses."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
import torch
from unittest.mock import patch

from fastapi.testclient import TestClient
from esm.sdk.api import ESMProtein, ESMProteinError
from protein_workbench_public.bootstrap import create_application


class ControlledGeneration:
    def __init__(self, failures=(2,), reconstruction=False):
        self.failures = failures
        self.reconstruction = reconstruction
        self.requests = []

    def generate(self, protein, config):
        self.requests.append((protein.sequence, config.track, config.num_steps))
        if len(self.requests) in self.failures:
            return ESMProteinError(500, "Controlled exhausted request")
        if config.track == "structure" or self.reconstruction:
            return ESMProtein(sequence="AC", coordinates=torch.zeros((2, 37, 3)),
                              plddt=torch.tensor([.8, .9]), ptm=torch.tensor(.7))
        return ESMProtein(sequence="AC")

    def close(self):
        pass


class ESM3Continuation(unittest.TestCase):
    def request(self, client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def wait(self, client, base, receipt):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = self.request(client, "GET", f'{base}/runs/{receipt["run_id"]}')
            if run["status"] not in {"admitted", "running"}:
                return run
            time.sleep(.01)
        self.fail("Run did not terminate")

    def batch(self, client, operation="generate_sequence"):
        binding = f"esm3.{operation}.biohub_open"
        self.request(client, "PATCH", f"/api/v2/module-settings/{binding}", json={
            "values": {"credential_handle": "controlled-sdk-only"}})
        project = self.request(client, "POST", "/api/v2/projects", json={"name": "ESM3 continuation"})
        base = f'/api/v2/projects/{project["id"]}'
        document = {"chains": [{"chain_id": "A", "length": 2}]}
        if operation == "generate_structure":
            document["track_edits"] = [
                {"track": "sequence", "action": "replace", "residue_id": f"A:{i}", "value": residue}
                for i, residue in enumerate("AC", 1)]
        workflow = {"schema_version": "2.1.0", "workflow_id": project["id"], "nodes": [
            {"node_id": "prompt", "node_type_id": "prompt_authoring.author", "binding_id": "prompt_authoring.author.direct",
             "node_parameters": {"document": document}, "binding_parameters": {}},
            {"node_id": "generate", "node_type_id": f"esm3.{operation}", "binding_id": binding,
             "node_parameters": {"num_samples": 3}, "binding_parameters": {}},
        ], "edges": [{"source_node_id": "prompt", "source_port": "protein_prompt",
                      "target_node_id": "generate", "target_port": "protein_prompt"}]}
        if operation != "generate_sequence":
            workflow["nodes"].append({
                "node_id": "confidence", "node_type_id": "structure_prediction.materialize_confidence",
                "binding_id": "structure_prediction.materialize_confidence.direct",
                "node_parameters": {}, "binding_parameters": {}})
            workflow["edges"].extend([
                {"source_node_id": "generate", "source_port": port,
                 "target_node_id": "confidence", "target_port": port}
                for port in ("structure_candidates", "confidence_facts")])
        workflow["nodes"].append({
            "node_id": "independent", "node_type_id": "prompt_authoring.author", "binding_id": "prompt_authoring.author.direct",
            "node_parameters": {"document": {"chains": [{"chain_id": "B", "length": 1}]}}, "binding_parameters": {}})
        commit = self.request(client, "POST", f"{base}/workflow:commit", json={"workflow": workflow})
        return base, commit

    def output(self, client, base, run, port="sequence_candidates"):
        return self.request(client, "GET", f'{base}/runs/{run["run_id"]}/outputs/generate/{port}/values/0')

    def resume(self, client, base, run):
        return self.wait(client, base, self.request(client, "POST", f"{base}/runs:derive", json={
            "source_run_id": run["run_id"], "policy": "continue_batch", "node_ids": ["generate"],
            "client_request_id": f'continue-{run["run_id"]}'}))

    def test_sequence_success_is_retained_after_reopen_and_not_requested_again(self):
        sdk = ControlledGeneration()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client)
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                self.assertEqual(failed["status"], "failed")
                first = self.output(client, base, failed)
                self.assertEqual(len(sdk.requests), 2)
                self.assertEqual(failed["continuable_node_ids"], ["generate"])
            with TestClient(create_application(load_example_results=False)) as client:
                done = self.resume(client, base, failed)
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual(done["workflow_commit_id"], commit["workflow_commit_id"])
                self.assertEqual(len(sdk.requests), 4)
                items = self.output(client, base, done)["value"]["fields"]["items"]
                self.assertEqual(len(items), 3)
                self.assertEqual(items[0], first["value"]["fields"]["items"][0])
                self.assertEqual(self.output(client, base, failed), first)

    def test_structure_continuation_keeps_structure_and_confidence(self):
        sdk = ControlledGeneration()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client, "generate_structure")
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                self.assertEqual(failed["status"], "failed")
                self.assertEqual({n["node_id"]: n["outcome"] for n in failed["node_dispositions"]},
                                 {"prompt": "succeeded", "independent": "succeeded", "generate": "failed", "confidence": "blocked"})
                first = self.output(client, base, failed, "structure_candidates")
                confidence = self.output(client, base, failed, "confidence_facts")
                self.assertEqual(failed["continuable_node_ids"], ["generate"])
                done = self.resume(client, base, failed)
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual(len(sdk.requests), 4)
                items = self.output(client, base, done, "structure_candidates")["value"]["fields"]["items"]
                self.assertEqual(len(items), 3)
                self.assertEqual(items[0], first["value"]["fields"]["items"][0])
                self.assertIn(confidence["value"]["entries"][0],
                              self.output(client, base, done, "confidence_facts")["value"]["entries"])

    def test_paired_continuation_only_retries_structure_after_sequence_success(self):
        sdk = ControlledGeneration(failures=(2, 3))
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client, "generate_paired")
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                self.assertEqual(failed["status"], "failed")
                first = self.output(client, base, failed)
                self.assertEqual(failed["continuable_node_ids"], ["generate"])
                again = self.resume(client, base, failed)
                self.assertEqual(again["status"], "failed")
                self.assertEqual(self.output(client, base, again), first)
                done = self.resume(client, base, again)
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual([r[1] for r in sdk.requests],
                                 ["sequence", "structure", "structure", "structure", "sequence", "structure", "sequence", "structure"])
                self.assertEqual([r[0] for r in sdk.requests[1:4]], ["AC", "AC", "AC"])
                sequences = self.output(client, base, done)["value"]["fields"]["items"]
                structures = self.output(client, base, done, "structure_candidates")["value"]["fields"]["items"]
                self.assertEqual(len(sequences), 3)
                self.assertEqual(len(structures), 3)
                self.assertEqual(sequences[0], first["value"]["fields"]["items"][0])

    def test_first_request_failure_remains_continuable_without_fabricated_results(self):
        sdk = ControlledGeneration(failures=(1,))
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client)
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                self.assertEqual(failed["continuable_node_ids"], ["generate"])
                self.assertFalse(any(output["node_id"] == "generate" for output in failed["outputs"]))
                done = self.resume(client, base, failed)
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual(len(sdk.requests), 4)

    def test_sequence_reconstruction_and_confidence_are_preserved(self):
        sdk = ControlledGeneration(reconstruction=True)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client)
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                retained = self.output(client, base, failed, "sequence_reconstruction_candidates")["value"]["fields"]["items"][0]
                confidence = self.output(client, base, failed, "confidence_facts")["value"]["entries"][0]
                done = self.resume(client, base, failed)
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual(len(sdk.requests), 4)
                self.assertEqual(self.output(client, base, done, "sequence_reconstruction_candidates")["value"]["fields"]["items"][0], retained)
                self.assertIn(confidence, self.output(client, base, done, "confidence_facts")["value"]["entries"])

    def test_changed_parameters_start_all_samples_as_a_new_calculation(self):
        sdk = ControlledGeneration()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client)
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                self.assertEqual(failed["status"], "failed")
                workflow = self.request(client, "GET", f'{base}/workflow/commits/{commit["workflow_commit_id"]}')["workflow"]
                node = next(n for n in workflow["nodes"] if n["node_id"] == "generate")
                node["binding_parameters"]["num_steps"] = 2
                changed = self.request(client, "POST", f"{base}/workflow:commit", json={"workflow": workflow})
                done = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": changed["workflow_commit_id"], "client_request_id": "changed"}))
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual(len(sdk.requests), 5)
                self.assertEqual([r[2] for r in sdk.requests[2:]], [2, 2, 2])

    def test_paired_continuation_preserves_complete_pairs_and_sequence_reconstructions(self):
        sdk = ControlledGeneration(failures=(4,), reconstruction=True)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": root}), patch("esm.sdk.client", return_value=sdk):
            with TestClient(create_application(load_example_results=False)) as client:
                base, commit = self.batch(client, "generate_paired")
                failed = self.wait(client, base, self.request(client, "POST", f"{base}/runs", json={
                    "workflow_commit_id": commit["workflow_commit_id"], "client_request_id": "start"}))
                self.assertEqual(failed["status"], "failed")
                ports = ("sequence_candidates", "structure_candidates", "sequence_reconstruction_candidates")
                retained = {port: self.output(client, base, failed, port)["value"]["fields"]["items"] for port in ports}
                old_confidence = self.output(client, base, failed, "sequence_reconstruction_confidence_facts")["value"]["entries"]
                done = self.resume(client, base, failed)
                self.assertEqual(done["status"], "succeeded", done)
                self.assertEqual([r[1] for r in sdk.requests],
                                 ["sequence", "structure", "sequence", "structure", "structure", "sequence", "structure"])
                for port in ports:
                    items = self.output(client, base, done, port)["value"]["fields"]["items"]
                    self.assertEqual(items[:len(retained[port])], retained[port])
                    self.assertEqual(len(items), 3)
                final_confidence = self.output(client, base, done, "sequence_reconstruction_confidence_facts")["value"]["entries"]
                for fact in old_confidence:
                    self.assertIn(fact, final_confidence)
