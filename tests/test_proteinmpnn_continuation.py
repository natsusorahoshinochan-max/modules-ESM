"""Public Run continuation using a test package, not a real local model."""
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import torch
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from protein_workbench_public.module_registry import DEFAULT_MODULES
import proteinmpnn_controlled as provider


class ProteinMPNNContinuation(unittest.TestCase):
    def request(self, client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def wait(self, client, base, run_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = self.request(client, 'GET', f'{base}/runs/{run_id}')
            if run['status'] not in ('running', 'admitted'):
                return run
            time.sleep(.01)
        self.fail('Run did not terminate')

    def test_completed_sample_requests_survive_reopening_and_are_not_repeated(self):
        self.exercise_batch({2})

    def test_first_request_and_repeated_failure_preserve_continuation(self):
        self.exercise_batch({1, 3})

    def test_program_error_does_not_offer_continuation(self):
        self.exercise_batch({1}, failure_type=RuntimeError)

    def exercise_batch(self, failures, failure_type=torch.cuda.OutOfMemoryError):
        provider.requests.clear()
        provider.failures = failures
        provider.failure_type = failure_type
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            packages = [asdict(p) for p in DEFAULT_MODULES]
            folding = next(p for p in packages if p['package_id'] == 'proteinmpnn')
            folding.update(package_module='proteinmpnn_controlled', source_root=str(Path(__file__).parent.resolve()))
            Path(root, 'modules.json').write_text(json.dumps({'packages': packages}))
            with TestClient(create_application(load_example_results=False)) as client:
                project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'ProteinMPNN batch'})
                base = f'/api/v2/projects/{project["id"]}'
                source = self.request(client, 'POST', base + '/inputs', json={
                    'filename': 'one.pdb', 'content_base64': base64.b64encode(
                        b'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 80.00           C  \nEND\n').decode(),
                })
                def node(name, kind, params=None):
                    return {'node_id': name, 'node_type_id': kind, 'binding_id': kind + ('.local' if kind == 'proteinmpnn.design' else '.direct'),
                            'node_parameters': params or {}, 'binding_parameters': {}}
                workflow = {'schema_version': '2.1.0', 'workflow_id': project['id'], 'nodes': [
                    node('input', 'protein_io.import_structure', {'project_input_ref': source['project_input_ref']}),
                    node('axes', 'structure_transform.resolve_candidate_residue_axes'),
                    node('fold', 'proteinmpnn.design', {'num_sequences': 3, 'effective_seed': 12}),
                    node('confidence', 'collection_ops.take_candidates', {'k': 1}),
                ], 'edges': [
                    {'source_node_id': 'input', 'source_port': 'structure_candidates', 'target_node_id': 'axes', 'target_port': 'structure_candidates'},
                    {'source_node_id': 'axes', 'source_port': 'residue_axes', 'target_node_id': 'fold', 'target_port': 'structure_residue_axes'},
                    {'source_node_id': 'fold', 'source_port': 'sequence_candidates', 'target_node_id': 'confidence', 'target_port': 'candidates'},
                ]}
                commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
                receipt = self.request(client, 'POST', base + '/runs', json={'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': 'initial'})
                run = self.wait(client, base, receipt['run_id'])
                self.assertEqual(run['status'], 'failed', run)
                if failure_type is RuntimeError:
                    self.assertEqual(run['continuable_node_ids'], [])
                    return
                self.assertEqual(run['continuable_node_ids'], ['fold'])
                self.assertEqual(next(n['outcome'] for n in run['node_dispositions'] if n['node_id'] == 'confidence'), 'blocked')
                source_id = run['run_id']
                output = f'/runs/{source_id}/outputs/fold/sequence_candidates/values/0'
                retained = None
                if min(failures) > 1:
                    retained = self.request(client, 'GET', base + output)
                    self.assertEqual(len(retained['value']['fields']['items']), 1)
                else:
                    self.assertFalse(any(o['node_id'] == 'fold' for o in run['outputs']))
                self.assertEqual(len(provider.requests), min(failures))
            with TestClient(create_application(load_example_results=False)) as client:
                if retained is not None:
                    self.assertEqual(self.request(client, 'GET', base + output), retained)
                receipt = self.request(client, 'POST', base + '/runs:derive', json={
                    'source_run_id': source_id, 'policy': 'continue_batch', 'node_ids': ['fold'], 'client_request_id': 'continue',
                })
                run = self.wait(client, base, receipt['run_id'])
                if len(failures) > 1:
                    self.assertEqual(run['status'], 'failed', run)
                    self.assertEqual(run['continuable_node_ids'], ['fold'])
                    retained = self.request(client, 'GET', f'{base}/runs/{run["run_id"]}/outputs/fold/sequence_candidates/values/0')
                    self.assertEqual(len(retained['value']['fields']['items']), 1)
                    self.assertEqual(len(provider.requests), 3)
                    receipt = self.request(client, 'POST', base + '/runs:derive', json={
                        'source_run_id': run['run_id'], 'policy': 'continue_batch',
                        'node_ids': ['fold'], 'client_request_id': 'finish',
                    })
                    run = self.wait(client, base, receipt['run_id'])
                self.assertEqual(run['status'], 'succeeded', run)
                self.assertEqual(run['continuable_node_ids'], [])
                complete = self.request(client, 'GET', f'{base}/runs/{run["run_id"]}/outputs/fold/sequence_candidates/values/0')
                self.assertEqual(len(complete['value']['fields']['items']), 3)
                self.assertEqual(complete['value']['fields']['items'][:1], retained['value']['fields']['items'])
                self.assertEqual(len(provider.requests), 3 + len(failures))
                failed_index = min(failures) - 1
                self.assertEqual(provider.requests[failed_index].seed, provider.requests[failed_index + 1].seed)
                self.assertEqual([r.num_sequences for r in provider.requests], [1] * len(provider.requests))
                self.assertEqual([r.temperature for r in provider.requests], [.1] * len(provider.requests))
                workflow['nodes'][2]['node_parameters']['temperature'] = .2
                changed = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
                before_new = len(provider.requests)
                receipt = self.request(client, 'POST', base + '/runs', json={
                    'workflow_commit_id': changed['workflow_commit_id'], 'client_request_id': 'changed-parameters'})
                run = self.wait(client, base, receipt['run_id'])
                self.assertEqual(run['status'], 'succeeded', run)
                self.assertEqual(len(provider.requests) - before_new, 3)
                self.assertEqual([r.temperature for r in provider.requests[before_new:]], [.2] * 3)
