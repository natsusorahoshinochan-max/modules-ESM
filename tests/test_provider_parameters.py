"""User parameters reach official Provider call boundaries without loading models."""
from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import time
from types import ModuleType
from typing import Any
import unittest
from unittest.mock import Mock, patch

from esm.sdk.api import ESMProtein, ESMProteinError
from fastapi.testclient import TestClient
import torch

from protein_workbench_public.bootstrap import create_application


class ProviderParameters(unittest.TestCase):
    def request(self, client: TestClient, method: str, url: str, **kwargs: Any) -> Any:
        response = client.request(method, url, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def run_workflow(self, client: TestClient, project: dict, nodes: list, edges: list) -> dict:
        base = '/api/v2/projects/' + project['id']
        commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': {
            'schema_version': '2.1.0', 'workflow_id': project['id'], 'nodes': nodes, 'edges': edges}})
        started = self.request(client, 'POST', base + '/runs', json={
            'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': 'parameters'})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = self.request(client, 'GET', base + '/runs/' + started['run_id'])
            if run['status'] not in {'admitted', 'running'}:
                return run
            time.sleep(.01)
        self.fail('Parameter Run did not terminate')

    def test_paired_esm3_passes_each_stages_distinct_settings(self) -> None:
        configs = []

        class Provider:
            def generate(self, protein: ESMProtein, config: Any) -> ESMProtein:
                configs.append(config)
                if config.track == 'sequence':
                    return ESMProtein(sequence='AC')
                return ESMProtein(sequence='AC', coordinates=torch.zeros((2, 37, 3)),
                                  plddt=torch.tensor([.8, .9]), ptm=torch.tensor(.7))

            def close(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}), patch('esm.sdk.client', return_value=Provider()), TestClient(create_application(load_example_results=False)) as client:
            binding = 'esm3.generate_paired.biohub_open'
            self.request(client, 'PATCH', '/api/v2/module-settings/' + binding,
                         json={'values': {'credential_handle': 'controlled-only'}})
            project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Paired parameters'})
            run = self.run_workflow(client, project, [
                {'node_id': 'prompt', 'node_type_id': 'prompt_authoring.author', 'binding_id': 'prompt_authoring.author.direct',
                 'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 2}]}}, 'binding_parameters': {}},
                {'node_id': 'generate', 'node_type_id': 'esm3.generate_paired', 'binding_id': binding,
                 'node_parameters': {'num_samples': 1}, 'binding_parameters': {
                     'sequence_num_steps': 2, 'sequence_temperature': .7, 'sequence_top_p': .8,
                     'sequence_invalid_ids': [4], 'sequence_condition_on_coordinates_only': False,
                     'structure_num_steps': 3, 'structure_temperature': 1.3, 'structure_top_p': .9,
                     'structure_invalid_ids': [5, 6], 'structure_condition_on_coordinates_only': True}},
            ], [{'source_node_id': 'prompt', 'source_port': 'protein_prompt', 'target_node_id': 'generate', 'target_port': 'protein_prompt'}])
            self.assertEqual(run['status'], 'succeeded', run)
        observed = [(c.track, c.num_steps, c.temperature, c.top_p, list(c.invalid_ids), c.condition_on_coordinates_only) for c in configs]
        self.assertEqual(observed, [('sequence', 2, .7, .8, [4], False), ('structure', 3, 1.3, .9, [5, 6], True)])

    def test_remote_esmfold2_passes_nondefault_inference_settings(self) -> None:
        parameters = {'num_sampling_steps': 13, 'num_loops': 2, 'lm_dropout': .2,
                      'lm_mask_pct': .3, 'msa_max_depth': 64, 'msa_column_mask_rate': .4}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}), patch('esm.sdk.esmfold2_client') as sdk, TestClient(create_application(load_example_results=False)) as client:
            sdk.return_value.fold.return_value = ESMProteinError(500, 'Controlled provider outcome')
            self.request(client, 'PATCH', '/api/v2/module-settings/folding.fold.esmfold2_remote',
                         json={'values': {'credential_handle': 'controlled-only'}})
            project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Folding parameters'})
            source = self.request(client, 'POST', '/api/v2/projects/' + project['id'] + '/inputs', json={
                'filename': 'input.fasta', 'content_base64': base64.b64encode(b'>one\nAC\n').decode()})
            run = self.run_workflow(client, project, [
                {'node_id': 'source', 'node_type_id': 'protein_io.import_sequence', 'binding_id': 'protein_io.import_sequence.direct',
                 'node_parameters': {'project_input_ref': source['project_input_ref']}, 'binding_parameters': {}},
                {'node_id': 'fold', 'node_type_id': 'folding.fold', 'binding_id': 'folding.fold.esmfold2_remote',
                 'node_parameters': {'num_samples': 1}, 'binding_parameters': parameters},
            ], [{'source_node_id': 'source', 'source_port': 'sequence_candidates', 'target_node_id': 'fold', 'target_port': 'sequence_candidates'}])
            self.assertEqual(run['status'], 'failed')
            request = sdk.return_value.fold.call_args.kwargs
            self.assertEqual(request['sequence'], 'AC')
            config = request['config']
            self.assertEqual((config.num_sampling_steps, config.num_loops, config.lm_dropout,
                              config.lm_mask_pct, config.msa_max_depth, config.msa_column_mask_rate),
                             (13, 2, .2, .3, 64, .4))
            self.assertTrue(config.include_pae)

    def test_local_esmfold2_builder_receives_local_values_without_loading_weights(self) -> None:
        from modules.folding.esmfold2_local import LocalESMFold2Runtime, load_local_engine

        parameters = {'num_sampling_steps': 201, 'num_loops': 21, 'lm_dropout': None,
                      'lm_mask_pct': None, 'msa_max_depth': None, 'msa_column_mask_rate': .2,
                      'effective_seed': 17}
        with tempfile.TemporaryDirectory() as root, \
             patch('esm.models.esmfold2.conformers.load_ccd'), \
             patch('transformers.models.esmfold2.configuration_esmfold2.ESMFold2Config.from_pretrained'), \
             patch('transformers.models.esmfold2.modeling_esmfold2.ESMFold2Model.from_pretrained') as model_loader, \
             patch('esm.models.esmfold2.ESMFold2InputBuilder') as builder:
            engine = load_local_engine(LocalESMFold2Runtime(Path(root), Path(root) / 'language', 'cpu'))
            engine.fold(sequence='AC', parameters=parameters, effective_seed=37)
            request = builder.return_value.fold.call_args
            self.assertIs(request.args[0], model_loader.return_value.to.return_value.eval.return_value)
            self.assertEqual(request.args[1].sequences[0].sequence, 'AC')
            self.assertEqual(request.kwargs, {
                'num_diffusion_samples': 1, 'seed': 37, 'complex_id': 'protein-workbench-fold',
                'num_sampling_steps': 201, 'num_loops': 21, 'lm_dropout': None,
                'lm_mask_pct': None, 'msa_max_depth': None, 'msa_column_mask_rate': .2})

    def test_simplefold_passes_tau_and_more_than_fifty_steps_to_official_wrapper(self) -> None:
        from datatypes.sequence import ProteinSequence
        from modules.folding.simplefold_runtime import activate_fold_sequence

        class StopBeforeModelLoading(Exception):
            pass

        wrapper = ModuleType('simplefold.wrapper')
        wrapper.esm_registry = {}
        wrapper.InferenceWrapper = Mock(side_effect=StopBeforeModelLoading)
        boltz = ModuleType('simplefold.utils.boltz_utils')
        boltz.process_structure = Mock()
        boltz.to_pdb = Mock()
        fasta = ModuleType('simplefold.utils.fasta_utils')
        fasta.process_fastas = Mock()
        datamodule = ModuleType('simplefold.utils.datamodule_utils')
        datamodule.process_one_inference_structure = Mock()
        with tempfile.TemporaryDirectory() as root, patch.dict('sys.modules', {
            module.__name__: module for module in (wrapper, boltz, fasta, datamodule)
        }), self.assertRaises(StopBeforeModelLoading):
            activate_fold_sequence(ProteinSequence('AC'), num_steps=501, tau=.25, num_samples=1,
                                   staging_directory=Path(root), effective_seed=23,
                                   staged_model_root=Path(root) / 'model',
                                   staged_esm2_source_root=Path(root) / 'esm2',
                                   staged_esm2_model_root=Path(root) / 'esm2-model', device='cpu')
        args = wrapper.InferenceWrapper.call_args.kwargs
        self.assertEqual((args['num_steps'], args['tau'], args['nsample_per_protein']), (501, .25, 1))
        fasta.process_fastas.assert_not_called()

    def test_simplefold_confidence_does_not_offer_sampling_controls(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}), TestClient(create_application(load_example_results=False)) as client:
            catalog = self.request(client, 'GET', '/api/v2/catalog')
        binding = next(item['descriptor'] for item in catalog['contracts']
                       if item['reference']['contract_id'] == 'folding.simplefold_confidence.simplefold_local')
        self.assertNotIn('tau', binding['binding_parameters'])
        self.assertNotIn('num_steps', binding['binding_parameters'])


if __name__ == '__main__':
    unittest.main()
