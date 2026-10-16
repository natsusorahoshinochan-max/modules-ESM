"""Reuse published Prompt values through the public project boundary."""
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
import test_result_adoption


class TypedResultAdoption(unittest.TestCase):
    run_workflow = test_result_adoption.ResultAdoption.run_workflow
    def test_prompt_can_be_connected_after_source_project_deletion(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'Prompt source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'Prompt consumer'}).json()['id']
                source_run = self.run_workflow(client, source, [{
                    'node_id': 'prompt', 'node_type_id': 'prompt_authoring.author',
                    'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
                    'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 3}]}}}])
                original = client.get(source_run + '/outputs/prompt/protein_prompt/values/0').content
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': source_run.rsplit('/', 1)[1],
                    'node_id': 'prompt', 'output_port': 'protein_prompt', 'value_index': 0})
                self.assertEqual(adopted.status_code, 201, adopted.text)
                node = adopted.json()['source_node'] | {'node_id': 'saved'}
                self.assertEqual(client.post(f'/api/v2/projects/{source}:trash').status_code, 200)
                self.assertEqual(client.delete(f'/api/v2/projects/{source}').status_code, 200)
            with TestClient(create_application(load_example_results=False)) as client:
                nodes = [node, {
                    'node_id': 'continue', 'node_type_id': 'prompt_authoring.author',
                    'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
                    'node_parameters': {'document': {}}}]
                edges = [{'source_node_id': 'saved', 'source_port': 'value',
                          'target_node_id': 'continue', 'target_port': 'prompt_source'}]
                opened = client.post(f'/api/v2/projects/{target}/authoring-actions/prompt_authoring.open',
                    json={'parameters': {'node_id': 'continue', 'workflow': {
                        'schema_version': '2.1.0', 'workflow_id': target, 'nodes': nodes, 'edges': edges}}})
                self.assertEqual(opened.status_code, 200, opened.text)
                self.assertEqual(len(opened.json()['residues']), 3)
                target_run = self.run_workflow(client, target, nodes, edges)
                restored = client.get(target_run + '/outputs/saved/value/values/0')
                self.assertEqual(restored.content, original)
                self.assertEqual(client.get(target_run + '/outputs/continue/protein_prompt/values/0').content, original)

    def test_modules_offer_existing_connectable_result_types(self):
        expected = {
            'protein.sequence', 'protein.structure', 'candidate.relation',
            'structure_comparison.region_statistics',
            'structure_comparison.inserted_loop_evaluation', 'structure_comparison.three_way_consistency',
            'proteinmpnn.constraints', 'esm3.esmc_sequence_representation',
            'residue.condition.sequence', 'residue.condition.coordinates',
            'residue.condition.secondary_structure', 'residue.condition.sasa',
            'residue.condition.function_annotations',
            'structure_annotation.sasa.observed', 'structure_annotation.secondary_structure.observed',
            'structure_comparison.alignment_evidence', 'structure_prediction.confidence_facts',
            'structure_transform.backbone_structure',
            'structure_transform.candidate_modified_residue_normalization_associations',
            'structure_transform.candidate_normalization_facts',
            'structure_transform.candidate_resolved_residue_axis_associations',
            'structure_transform.modified_residue_normalizations',
            'structure_transform.resolved_residue_axis',
        }
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                response = client.get('/api/v2/result-sources')
                self.assertEqual(response.status_code, 200, response.text)
                actual = {item['port_type_id'] for item in response.json()['sources']}
                self.assertFalse(expected - actual, expected - actual)

    def test_external_module_value_uses_the_same_adoption_contract(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            Path(root, 'modules.json').write_text(json.dumps({'packages': [{
                'package_id': 'reader_demo', 'package_module': 'reader_module', 'enabled': True,
                'source_root': str(Path(__file__).parent.resolve())}]}))
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'External source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'External reuse'}).json()['id']
                run = self.run_workflow(client, source, [{
                    'node_id': 'observe', 'node_type_id': 'reader_demo.observe',
                    'binding_id': 'reader_demo.observe.direct', 'binding_parameters': {}, 'node_parameters': {}}])
                original = client.get(run + '/outputs/observe/observation/values/0').content
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': run.rsplit('/', 1)[1],
                    'node_id': 'observe', 'output_port': 'observation', 'value_index': 0})
                self.assertEqual(adopted.status_code, 201, adopted.text)
                node = adopted.json()['source_node'] | {'node_id': 'saved'}
                self.assertEqual(client.post(f'/api/v2/projects/{source}:trash').status_code, 200)
                self.assertEqual(client.delete(f'/api/v2/projects/{source}').status_code, 200)
            with TestClient(create_application(load_example_results=False)) as client:
                target_run = self.run_workflow(client, target, [node])
                self.assertEqual(client.get(target_run + '/outputs/saved/value/values/0').content, original)
