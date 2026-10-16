"""One-time Run conversion uses saved facts without reexecuting old rules."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.project.manager import ProjectManager


class HistoryConversionTests(unittest.TestCase):
    def test_failed_retired_selection_preserves_status_diagnostic_and_sparse_event_cursors(self):
        from core.execution.history_preservation import prepare_historical_reading
        from protein_workbench_public.bootstrap import create_application

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projects = ProjectManager(root / "projects", run_root=root / "runs")
            project = projects.create("Saved failed selection")
            run_id = "run-saved-selection"
            ledger = root / "runs" / project.id / run_id / "ledger"
            ledger.mkdir(parents=True)
            error = {"code": "selection_failed", "message": "Recorded required score was absent",
                     "retryable": False, "correlation_id": "recorded-error", "details": {"reason": "One required score was absent"}}
            timestamp = "2026-10-17T00:00:00+00:00"
            facts = [
                {"fact_type": "run_scope_bound", "payload": {"workflow_commit_id": "commit-original", "plan_nodes": [], "execution_scope": None}},
                {"fact_type": "run_admitted", "payload": {"workflow_commit_id": "commit-original"}},
                {"fact_type": "run_started", "payload": {"started_at": timestamp}},
                {"fact_type": "selection_terminal", "payload": {"status": "failed", "result": None, "error": error}},
                {"fact_type": "run_terminal", "payload": {"status": "failed"}},
            ]
            for sequence, fact in enumerate(facts, 1):
                fact.update(sequence=sequence, recorded_at=timestamp)
            transaction = {"project_id": project.id, "run_id": run_id, "transaction_sequence": 1,
                "first_fact_sequence": 1, "last_fact_sequence": 5, "committed_at": timestamp, "facts": facts}
            original = json.dumps(transaction).encode()
            path = ledger / "00000000000000000001.json"
            path.write_bytes(original)

            self.assertEqual(prepare_historical_reading(root), ((project.id, run_id),))
            with patch.dict(os.environ, {"PROTEIN_WORKBENCH_DATA_ROOT": str(root)}):
                app = create_application(load_example_results=False)
                try:
                    with TestClient(app) as client:
                        base = f"/api/v2/projects/{project.id}/runs/{run_id}"
                        response = client.get(base)
                        self.assertEqual(response.status_code, 200, response.text)
                        projection = response.json()
                        self.assertEqual((projection["status"], projection["terminal_sequence"], projection["diagnostic"]["message"]),
                                         ("failed", 5, "Recorded required score was absent"))
                        sequences = []
                        with client.websocket_connect(base + "/events") as stream:
                            while True:
                                event = stream.receive_json()
                                if event["event"]["type"] == "replay_complete":
                                    break
                                if event["event"]["type"] != "replay_started":
                                    sequences.append(event["sequence"])
                        self.assertEqual(sequences, [2, 3, 5])
                finally:
                    app.state.run_runtime.shutdown()
            self.assertEqual(path.read_bytes(), original)
