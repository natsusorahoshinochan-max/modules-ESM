"""Historical result adoption through the public application API."""
import base64
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class ResultAdoption(unittest.TestCase):
    def run_workflow(self, client, project_id, nodes, edges=()):
        base = '/api/v2/projects/' + project_id
        saved = client.post(base + '/workflow:commit', json={'workflow': {
            'schema_version': '2.1.0', 'workflow_id': project_id,
            'nodes': nodes, 'edges': list(edges)}})
        self.assertEqual(saved.status_code, 200, saved.text)
        start = client.post(base + '/runs', json={
            'workflow_commit_id': saved.json()['workflow_commit_id'],
            'client_request_id': 'run-' + str(time.monotonic_ns())})
        self.assertEqual(start.status_code, 202, start.text)
        run = base + '/runs/' + start.json()['run_id']
        deadline = time.monotonic() + 10
        while True:
            result = client.get(run).json()
            if result['status'] not in ('pending', 'running'):
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        self.assertEqual(result['status'], 'succeeded', result)
        return run

    def test_adopted_candidates_keep_identity_after_reopen_and_source_deletion(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'Source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'Target'}).json()['id']
                uploaded = client.post(f'/api/v2/projects/{source}/inputs', json={
                    'filename': 'original.fasta',
                    'content_base64': base64.b64encode(b'>first\nACDE\n>second\nFGHI\n').decode()}).json()
                source_run = self.run_workflow(client, source, [{
                    'node_id': 'import', 'node_type_id': 'protein_io.import_sequences',
                    'binding_id': 'protein_io.import_sequences.direct', 'binding_parameters': {},
                    'node_parameters': {'project_input_ref': uploaded['project_input_ref']}}])
                original = client.get(source_run + '/outputs/import/sequence_candidates/values/0')
                self.assertEqual(original.status_code, 200, original.text)
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': source_run.rsplit('/', 1)[1],
                    'node_id': 'import', 'output_port': 'sequence_candidates', 'value_index': 0})
                self.assertEqual(adopted.status_code, 201, adopted.text)
                node = adopted.json()['source_node'] | {'node_id': 'adopted'}
            with TestClient(create_application(load_example_results=False)) as client:
                trashed = client.post(f'/api/v2/projects/{source}:trash')
                self.assertEqual(trashed.status_code, 200, trashed.text)
                deleted = client.delete(f'/api/v2/projects/{source}')
                self.assertEqual(deleted.status_code, 200, deleted.text)
                target_run = self.run_workflow(client, target, [node])
                restored = client.get(target_run + '/outputs/adopted/value/values/0')
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.content, original.content)
