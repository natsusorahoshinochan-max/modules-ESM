"""Candidate reading through module actions survives application restart."""
import base64
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class CandidateReading(unittest.TestCase):
    def test_module_page_action_preserves_order_and_references_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': directory}):
            with TestClient(create_application()) as client:
                project = client.post('/api/v2/projects', json={'name': 'Candidate pages'})
                self.assertEqual(project.status_code, 201, project.text)
                base = '/api/v2/projects/' + project.json()['id']
                uploaded = client.post(base + '/inputs', json={'filename': 'two.fasta', 'content_base64': base64.b64encode(b'>one\nACD\n>two\nGEF\n').decode()})
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                committed = client.post(base + '/workflow:commit', json={'workflow': {
                    'schema_version': '2.1.0', 'workflow_id': project.json()['id'],
                    'nodes': [{'node_id': 'import', 'node_type_id': 'protein_io.import_sequences', 'binding_id': 'protein_io.import_sequences.direct', 'node_parameters': {'project_input_ref': uploaded.json()['project_input_ref']}, 'binding_parameters': {}}], 'edges': [],
                }})
                self.assertEqual(committed.status_code, 200, committed.text)
                receipt = client.post(base + '/runs', json={'workflow_commit_id': committed.json()['workflow_commit_id'], 'client_request_id': 'page-reading'})
                self.assertEqual(receipt.status_code, 202, receipt.text)
                run = base + '/runs/' + receipt.json()['run_id']
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    projection = client.get(run).json()
                    if projection['status'] not in ('running', 'admitted'):
                        break
                    time.sleep(.01)
                self.assertEqual(projection['status'], 'succeeded', projection)
                location = {'node_id': 'import', 'output_port': 'sequence_candidates', 'value_index': 0}
                page = client.post(run + '/results:action', json={**location, 'action_id': 'protein_io.candidate_page', 'parameters': {'offset': 0, 'limit': 1}})
                self.assertEqual(page.status_code, 200, page.text)
                first = page.json()
                self.assertEqual(first['total'], 2)
                self.assertEqual([item['sequence'] for item in first['items']], ['ACD'])
                self.assertEqual(first['items'][0]['item_index'], 0)
                self.assertEqual(first['items'][0]['parent_ids'], [])
                self.assertEqual(first['items'][0]['reference']['data_type_id'], 'protein.sequence')
            with TestClient(create_application()) as client:
                reopened = client.post(run + '/results:action', json={**location, 'action_id': 'protein_io.candidate_page', 'parameters': {'offset': 0, 'limit': 1}})
                self.assertEqual(reopened.json(), first)
                second = client.post(run + '/results:action', json={**location, 'action_id': 'protein_io.candidate_page', 'parameters': {'offset': 1, 'limit': 1}})
                self.assertEqual(second.status_code, 200, second.text)
                self.assertEqual(second.json()['items'][0]['sequence'], 'GEF')
                self.assertEqual(second.json()['items'][0]['item_index'], 1)
                self.assertNotEqual(second.json()['items'][0]['reference'], first['items'][0]['reference'])

    def test_module_structure_action_reads_original_coordinates(self) -> None:
        pdb = 'ATOM      1  CA  GLY A   1       1.000   2.000   3.000  1.00 20.00           C  \nEND\n'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': directory}):
            with TestClient(create_application()) as client:
                project = client.post('/api/v2/projects', json={'name': 'Structure reading'})
                base = '/api/v2/projects/' + project.json()['id']
                uploaded = client.post(base + '/inputs', json={'filename': 'gly.pdb', 'content_base64': base64.b64encode(pdb.encode()).decode()})
                committed = client.post(base + '/workflow:commit', json={'workflow': {
                    'schema_version': '2.1.0', 'workflow_id': project.json()['id'],
                    'nodes': [{'node_id': 'import', 'node_type_id': 'protein_io.import_structure', 'binding_id': 'protein_io.import_structure.direct', 'node_parameters': {'project_input_ref': uploaded.json()['project_input_ref']}, 'binding_parameters': {}}], 'edges': [],
                }})
                self.assertEqual(committed.status_code, 200, committed.text)
                receipt = client.post(base + '/runs', json={'workflow_commit_id': committed.json()['workflow_commit_id'], 'client_request_id': 'structure-reading'})
                run = base + '/runs/' + receipt.json()['run_id']
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    projection = client.get(run).json()
                    if projection['status'] not in ('running', 'admitted'):
                        break
                    time.sleep(.01)
                self.assertEqual(projection['status'], 'succeeded', projection)
            with TestClient(create_application()) as client:
                reading = client.post(run + '/results:action', json={'node_id': 'import', 'output_port': 'structure_candidates', 'value_index': 0, 'action_id': 'protein_io.candidate_structure', 'parameters': {'item_index': 0}})
                self.assertEqual(reading.status_code, 200, reading.text)
                self.assertEqual(reading.json(), {'text': pdb, 'format': 'pdb'})


if __name__ == '__main__':
    unittest.main()
