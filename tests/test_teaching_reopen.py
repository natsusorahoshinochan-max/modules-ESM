"""An installed teaching example survives module upgrades at the application boundary."""
import base64
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from modules.structure_comparison import package as comparison
from protein_workbench_public.bootstrap import create_application


class TeachingReopen(unittest.TestCase):
    def test_corrupt_teaching_commit_is_not_silently_replaced(self):
        with TemporaryDirectory() as root, patch.dict(
            'os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}
        ):
            with TestClient(create_application(load_example_results=False)):
                pass
            records = Path(root) / 'projects/webui-3gb1-example/workflow-v2/commits'
            record = next(records.glob('*.json'))
            record.write_text('{broken', encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                create_application(load_example_results=False)

    def test_module_upgrade_keeps_teaching_and_personal_work(self):
        upgraded = replace(comparison.MODULE_PACKAGE, bindings=tuple(
            replace(binding, binding_parameters={**binding.binding_parameters,
                'region_enabled': {
                    'parameter_scope': 'scientific',
                    'scientific_meaning': 'Enable the explicitly selected comparison region.',
                    'value_contract': {'type': 'boolean'}, 'default': False,
                }}) if binding.node_type.contract_id == 'structure_comparison.align_pairs'
            else binding for binding in comparison.MODULE_PACKAGE.bindings
        ))
        for bundled_results in (False, True):
            with self.subTest(bundled_results=bundled_results), TemporaryDirectory() as root, patch.dict(
                'os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}
            ):
                with TestClient(create_application(load_example_results=bundled_results)) as client:
                    project = client.post('/api/v2/projects', json={'name': 'Retained research'})
                    self.assertEqual(project.status_code, 201, project.text)
                    project_id = project.json()['id']
                    prefix = '/api/v2/projects/' + project_id
                    source = client.post(prefix + '/inputs', json={
                        'filename': 'sequence.fasta',
                        'content_base64': base64.b64encode(b'>sequence\nACDE\n').decode(),
                    })
                    self.assertEqual(source.status_code, 201, source.text)
                    commit = client.post(prefix + '/workflow:commit', json={'workflow': {
                        'schema_version': '2.1.0', 'workflow_id': project_id,
                        'nodes': [{'node_id': 'source', 'node_type_id': 'protein_io.import_sequence',
                            'binding_id': 'protein_io.import_sequence.direct', 'binding_parameters': {},
                            'node_parameters': {'project_input_ref': source.json()['project_input_ref']}}],
                        'edges': [],
                    }})
                    self.assertEqual(commit.status_code, 200, commit.text)
                    started = client.post(prefix + '/runs', json={
                        'workflow_commit_id': commit.json()['workflow_commit_id'],
                        'client_request_id': 'preserve-research',
                    })
                    self.assertEqual(started.status_code, 202, started.text)
                    run_path = prefix + '/runs/' + started.json()['run_id']
                    deadline = time.monotonic() + 10
                    while client.get(run_path).json()['status'] in ('admitted', 'running'):
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.01)
                    paths = [prefix + '/workspace', run_path,
                        prefix + '/workflow/commits/' + commit.json()['workflow_commit_id'],
                        run_path + '/outputs/source/sequence_candidates/values/0',
                        '/api/v2/projects/webui-3gb1-example/workspace',
                        '/api/v2/projects/webui-3gb1-example/runs',
                    ]
                    before = {}
                    for path in paths:
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200, response.text)
                        before[path] = response.json()
                    for run in before[paths[-1]]['runs']:
                        path = '/api/v2/projects/webui-3gb1-example/workflow/commits/' + run['workflow_commit_id']
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200, response.text)
                        before[path] = response.json()
                # The installed package publishes an additional optional scientific parameter.
                with patch.object(comparison, 'MODULE_PACKAGE', upgraded), TestClient(
                    create_application(load_example_results=bundled_results)
                ) as client:
                    for path, retained in before.items():
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json(), retained)


if __name__ == '__main__':
    unittest.main()
