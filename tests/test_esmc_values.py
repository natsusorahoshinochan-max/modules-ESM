"""ESMC output choice and durable numeric values through public Run / SDK boundaries."""
import base64
import json
from pathlib import Path
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class ESMCValues(unittest.TestCase):
    def test_logits_only_retains_residue_rows_after_reopen(self):
        self.run_representation('logits')

    def test_embedding_only_requests_no_logits(self):
        self.run_representation('embedding')

    def test_both_outputs_remain_available_after_reopen(self):
        self.run_representation('both')

    def run_representation(self, outputs: str) -> None:
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}), patch('esm.sdk.esmc_client') as sdk:
            from dataclasses import asdict
            from protein_workbench_public.module_registry import DEFAULT_MODULES
            Path(root, 'modules.json').write_text(json.dumps({'packages': [
                *[asdict(module) for module in DEFAULT_MODULES],
                {'package_id': 'esmc_consumer', 'package_module': 'esmc_consumer', 'enabled': True, 'source_root': str(Path(__file__).parent.resolve())},
            ]}))
            sdk.return_value.logits.return_value = SimpleNamespace(
                logits=SimpleNamespace(sequence=None if outputs == 'embedding' else torch.tensor([[99.] * 64, [1.25] * 64, [-2.5] * 64, [88.] * 64])),
                mean_embedding=None if outputs == 'logits' else torch.full((1, 1, 1152), 0.25),
            )
            with TestClient(create_application(load_example_results=False)) as client:
                client.patch('/api/v2/module-settings/esm3.represent_sequence.biohub_esmc_600m_2024_12', json={'values': {'credential_handle': 'test-token'}})
                project = client.post('/api/v2/projects', json={'name': 'ESMC values'}).json()['id']
                base = '/api/v2/projects/' + project
                source = client.post(base + '/inputs', json={'filename': 'seq.fasta', 'content_base64': base64.b64encode(b'>seq\nAC\n').decode()}).json()['project_input_ref']
                commit = client.post(base + '/workflow:commit', json={'workflow': {
                    'schema_version': '2.1.0', 'workflow_id': project,
                    'nodes': [
                        {'node_id': 'source', 'node_type_id': 'protein_io.import_sequence', 'binding_id': 'protein_io.import_sequence.direct', 'node_parameters': {'project_input_ref': source}, 'binding_parameters': {}},
                        {'node_id': 'represent', 'node_type_id': 'esm3.represent_sequence', 'binding_id': 'esm3.represent_sequence.biohub_esmc_600m_2024_12', 'node_parameters': {'outputs': outputs}, 'binding_parameters': {}},
                        {'node_id': 'consumer', 'node_type_id': 'esmc_consumer.receive', 'binding_id': 'esmc_consumer.receive.direct', 'node_parameters': {}, 'binding_parameters': {}},
                    ], 'edges': [{'source_node_id': 'source', 'source_port': 'sequence', 'target_node_id': 'represent', 'target_port': 'sequence'}, {'source_node_id': 'represent', 'source_port': 'representation', 'target_node_id': 'consumer', 'target_port': 'representation'}],
                }})
                self.assertEqual(commit.status_code, 200, commit.text)
                receipt = client.post(base + '/runs', json={'workflow_commit_id': commit.json()['workflow_commit_id'], 'client_request_id': 'esmc-values'})
                self.assertEqual(receipt.status_code, 202, receipt.text)
                run = base + '/runs/' + receipt.json()['run_id']
                for _ in range(500):
                    projection = client.get(run).json()
                    if projection['status'] not in ('running', 'admitted'):
                        break
                    time.sleep(.01)
                self.assertEqual(projection['status'], 'succeeded', projection)
                config = sdk.return_value.logits.call_args.args[1]
                self.assertEqual(config.sequence, outputs != 'embedding')
                self.assertEqual(config.return_mean_embedding, outputs != 'logits')
                self.assertEqual(sdk.return_value.encode.call_args.args[0].sequence, 'AC')
            with TestClient(create_application(load_example_results=False)) as client:
                raw = client.get(run + '/outputs/represent/representation/values/0')
                self.assertEqual(raw.status_code, 200, raw.text)
                value = raw.json()['value']
                self.assertEqual(client.get(run + '/outputs/consumer/received/values/0').json()['value'], value)
                self.assertEqual(value['mean_embedding'], None if outputs == 'logits' else [0.25] * 1152)
                self.assertEqual(value['sequence_logits'], None if outputs == 'embedding' else [[1.25] * 64, [-2.5] * 64])
                self.assertEqual(value['sequence'], 'AC')
                reading = client.post(run + '/results:value', json={'node_id': 'represent', 'output_port': 'representation', 'value_index': 0})
                self.assertEqual(reading.status_code, 200, reading.text)
                self.assertEqual(reading.json(), {'kind': 'esmc_representation', 'value': value})
                manifest = client.get('/api/v2/module-ui').json()
                self.assertTrue(any(viewer['viewer_id'] == 'esm3.esmc.values' for extension in manifest['extensions'] for viewer in extension['viewers']))
