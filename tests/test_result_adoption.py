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

    def test_missing_target_reports_project_not_found_without_adopting(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                response = client.post('/api/v2/projects/missing/inputs:adopt', json={
                    'source_project_id': 'source', 'source_run_id': 'run',
                    'node_id': 'import', 'output_port': 'sequence_candidates', 'value_index': 0})
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()['error']['code'], 'project_not_found')

    def test_original_parameters_remain_readable_after_source_deletion(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'Source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'Target'}).json()['id']
                uploaded = client.post(f'/api/v2/projects/{source}/inputs', json={
                    'filename': 'sequence.fasta', 'content_base64': base64.b64encode(b'>original\nACDE\n').decode()}).json()
                source_run = self.run_workflow(client, source, [{
                    'node_id': 'import', 'node_type_id': 'protein_io.import_sequences',
                    'binding_id': 'protein_io.import_sequences.direct', 'binding_parameters': {},
                    'node_parameters': {'project_input_ref': uploaded['project_input_ref']}}])
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': source_run.rsplit('/', 1)[1],
                    'node_id': 'import', 'output_port': 'sequence_candidates', 'value_index': 0}).json()
                client.post(f'/api/v2/projects/{source}:trash')
                client.delete(f'/api/v2/projects/{source}')
            with TestClient(create_application(load_example_results=False)) as client:
                metadata = client.get(f"/api/v2/projects/{target}/inputs/{adopted['project_input_ref']}:adoption")
                self.assertEqual(metadata.status_code, 200, metadata.text)
                provenance = metadata.json()
                self.assertEqual(provenance['source']['source_project_id'], source)
                self.assertEqual(provenance['parameters']['status'], 'recorded')
                record = provenance['parameters']['records'][0]
                self.assertEqual(record['node_type_id'], 'protein_io.import_sequences')
                self.assertEqual(record['node_parameters'], {'project_input_ref': uploaded['project_input_ref']})

    def test_scores_keep_subject_method_and_values_after_source_deletion(self):
        import json
        from pathlib import Path
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            Path(root, 'modules.json').write_text(json.dumps({'packages': [
                {'package_id': name, 'package_module': 'modules.' + name + '.package', 'enabled': True, 'source_root': None}
                for name in ('protein_io', 'selection')
            ] + [{'package_id': 'adoption_demo', 'package_module': 'adoption_module', 'enabled': True,
                  'source_root': str(Path(__file__).parent.resolve())}]}))
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'Source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'Target'}).json()['id']
                uploaded = client.post(f'/api/v2/projects/{source}/inputs', json={
                    'filename': 'sequence.fasta', 'content_base64': base64.b64encode(b'>original\nACDE\n').decode()}).json()
                source_run = self.run_workflow(client, source, [
                    {'node_id': 'import', 'node_type_id': 'protein_io.import_sequences',
                     'binding_id': 'protein_io.import_sequences.direct', 'binding_parameters': {},
                     'node_parameters': {'project_input_ref': uploaded['project_input_ref']}},
                    {'node_id': 'observe', 'node_type_id': 'adoption_demo.observe',
                     'binding_id': 'adoption_demo.observe.direct', 'binding_parameters': {}, 'node_parameters': {}}],
                    [{'source_node_id': 'import', 'source_port': 'sequence_candidates',
                      'target_node_id': 'observe', 'target_port': 'candidates'}])
                original = client.get(source_run + '/outputs/observe/scores/values/0').content
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': source_run.rsplit('/', 1)[1],
                    'node_id': 'observe', 'output_port': 'scores', 'value_index': 0})
                self.assertEqual(adopted.status_code, 201, adopted.text)
                node = adopted.json()['source_node'] | {'node_id': 'adopted'}
                client.post(f'/api/v2/projects/{source}:trash')
                client.delete(f'/api/v2/projects/{source}')
            with TestClient(create_application(load_example_results=False)) as client:
                target_run = self.run_workflow(client, target, [node])
                restored = client.get(target_run + '/outputs/adopted/value/values/0')
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.content, original)

                metadata = client.get(f"/api/v2/projects/{target}/inputs/{adopted.json()['project_input_ref']}:adoption").json()
                self.assertEqual(len(metadata['dependencies']), 1)
                self.assertEqual(metadata['dependencies'][0]['port_type_id'], 'candidate.collection')
                self.assertIn('ACDE', metadata['dependencies'][0]['canonical_value'])
                options = client.post(f'/api/v2/projects/{target}/workflow:observation-options', json={
                    'workflow': {'nodes': [node], 'edges': []}, 'ranking': False})
                self.assertEqual(options.status_code, 200, options.text)
                self.assertEqual([(item['metric_id'], item['method_id']) for item in options.json()['options']],
                                 [('adoption_demo.value', 'adoption_demo.method')])

    def test_unfinished_adopted_score_node_has_no_observation_options(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                project = client.post('/api/v2/projects', json={'name': 'Unfinished'}).json()['id']
                response = client.post(f'/api/v2/projects/{project}/workflow:observation-options', json={
                    'workflow': {'nodes': [{'node_id': 'source', 'node_type_id': 'selection.adopt_scores',
                        'binding_id': 'selection.adopt_scores.direct', 'binding_parameters': {},
                        'node_parameters': {'project_input_ref': ''}}], 'edges': []}, 'ranking': False})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['options'], [])
