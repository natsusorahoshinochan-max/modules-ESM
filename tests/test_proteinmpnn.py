"""ProteinMPNN user workflows through public HTTP and the official provider boundary."""
from __future__ import annotations

from contextlib import nullcontext
import base64
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class ProteinMPNNWorkflows(unittest.TestCase):
    def test_real_design_excludes_selected_position_amino_acids(self):
        omissions = [{'residue_id': 'A:1', 'amino_acids': list('ACDEFGHIKLMNPQRSTVY')}]
        stored = self.run_constraints(omissions, design=True)
        self.assertEqual(stored['fields']['items'][0]['fields']['data']['fields']['sequence'][0], 'W')

    def test_position_omissions_preserve_selected_residue_identity(self):
        stored = self.run_constraints([{'residue_id': 'A:1', 'amino_acids': ['C', 'W']}])
        self.assertEqual(stored['omit_by_residue'], {'A:1': ['C', 'W']})

    def test_real_design_uses_selected_residue_pssm(self):
        probabilities = [0.0] * 20
        probabilities[18] = 1.0  # W in ACDEFGHIKLMNPQRSTVWY
        stored = self.run_constraints([], design=True, parameters={
            'pssm_by_residue': [{'residue_id': 'A:1', 'coefficient': 1.0,
                                 'probabilities': probabilities, 'log_odds': [0.0] * 20}],
            'pssm_multi': 1.0, 'pssm_bias_flag': True,
        })
        self.assertEqual(stored['fields']['items'][0]['fields']['data']['fields']['sequence'][0], 'W')

    def test_real_design_accepts_global_bias_and_tied_weights(self):
        stored = self.run_constraints([], design=True, parameters={
            'amino_acid_bias': [{'amino_acid': 'W', 'bias': 1e6}],
            'tied_residue_groups': [['A:1', 'A:2']],
            'tied_weights': [{'residue_id': 'A:1', 'weight': .5}, {'residue_id': 'A:2', 'weight': 1.5}],
        })
        self.assertEqual(stored['fields']['items'][0]['fields']['data']['fields']['sequence'], 'W' * 56)

    def test_tied_group_does_not_silently_ignore_member_constraints(self):
        projection = self.run_constraints(
            [{'residue_id': 'A:1', 'amino_acids': ['W']}],
            parameters={'tied_residue_groups': [['A:1', 'A:2']]}, expected_status='failed',
        )
        self.assertEqual(projection['status'], 'failed')

    def test_real_independent_sequence_score_preserves_subject_and_reference(self):
        stored = self.run_constraints([], score=True)
        observation = stored['fields']['entries'][0]['fields']
        self.assertEqual(observation['context']['fields']['pairing_mode'], 'fixed_reference')
        self.assertEqual(observation['subject'], observation['context']['fields']['subject']['fields']['candidate'])
        self.assertNotEqual(observation['subject'], observation['context']['fields']['reference']['fields']['candidate'])
        self.assertIsInstance(observation['value'], float)
        self.assertGreaterEqual(observation['value'], 0)

    def test_real_designed_sequence_can_be_scored_on_another_backbone(self):
        stored = self.run_constraints([], design=True, score=True, correspondence=[
            {'sequence_position': position, 'residue_id': f'B:{position}'}
            for position in range(1, 57)
        ])
        generated = stored['sequence']['fields']['items'][0]['fields']
        source = stored['source']['fields']['items'][0]['fields']
        reference = stored['reference']['fields']['items'][0]['fields']
        observation = stored['score']['fields']['entries'][0]['fields']
        self.assertEqual(generated['parent_ids'], [source['candidate_id']])
        self.assertEqual(observation['subject']['fields']['candidate_id'], generated['candidate_id'])
        self.assertEqual(observation['context']['fields']['reference']['fields']['candidate']['fields']['candidate_id'], reference['candidate_id'])
        self.assertNotIn(reference['candidate_id'], generated['parent_ids'])
        self.assertEqual(observation['context']['fields']['sequence_correspondence'], [[position, f'B:{position}'] for position in range(1, 57)])

    def test_different_correspondences_remain_distinct_when_scores_merge(self):
        stored = self.run_constraints([], score=True, compare_correspondence=True)
        entries = stored['fields']['entries']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['fields']['subject'], entries[1]['fields']['subject'])
        self.assertNotEqual(entries[0]['fields']['context']['fields']['sequence_correspondence'], entries[1]['fields']['context']['fields']['sequence_correspondence'])

    def test_partial_evaluation_correspondence_is_rejected(self):
        self.run_constraints([], score=True, correspondence=[{'sequence_position': 1, 'residue_id': 'A:1'}], expected_status='failed')

    def run_constraints(self, omissions, *, design=False, score=False, compare_correspondence=False, correspondence=None, parameters=None, expected_status='succeeded'):
        storage = nullcontext(tempfile.mkdtemp(prefix='proteinmpnn-business-')) if design or score else tempfile.TemporaryDirectory()
        with storage as root, patch.dict(
            'os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}
        ), TestClient(create_application(load_example_results=False)) as client:
            project = client.post('/api/v2/projects', json={'name': 'Position constraints'}).json()['id']
            base = '/api/v2/projects/' + project
            uploaded = client.post(base + '/inputs', json={
                'filename': '3GB1.pdb', 'content_base64': base64.b64encode(
                    Path('examples/v2/structures/3GB1.pdb').read_bytes()).decode(),
            }).json()['project_input_ref']
            workflow = {'schema_version': '2.1.0', 'workflow_id': project, 'nodes': [
                {'node_id': 'source', 'node_type_id': 'protein_io.import_structure', 'binding_id': 'protein_io.import_structure.direct', 'node_parameters': {'project_input_ref': uploaded}, 'binding_parameters': {}},
                {'node_id': 'axis', 'node_type_id': 'structure_transform.resolve_residue_axis', 'binding_id': 'structure_transform.resolve_residue_axis.direct', 'node_parameters': {}, 'binding_parameters': {}},
                {'node_id': 'constraints', 'node_type_id': 'proteinmpnn.constraints', 'binding_id': 'proteinmpnn.constraints.local', 'node_parameters': {'omit_by_residue': omissions, **(parameters or {})}, 'binding_parameters': {}},
            ], 'edges': [
                {'source_node_id': 'source', 'source_port': 'structure', 'target_node_id': 'axis', 'target_port': 'structure'},
                {'source_node_id': 'axis', 'source_port': 'residue_axis', 'target_node_id': 'constraints', 'target_port': 'structure_residue_axis'},
            ]}
            if design or score:
                configured = client.patch('/api/v2/module-settings/proteinmpnn.' + ('design' if design else 'score') + '.local', json={'values': {'provider_root': os.environ['PROTEINMPNN_ROOT']}})
                self.assertEqual(configured.status_code, 200, configured.text)
                workflow['nodes'].extend([
                    {'node_id': 'axes', 'node_type_id': 'structure_transform.resolve_candidate_residue_axes', 'binding_id': 'structure_transform.resolve_candidate_residue_axes.direct', 'node_parameters': {}, 'binding_parameters': {}},
                    {'node_id': 'design', 'node_type_id': 'proteinmpnn.design', 'binding_id': 'proteinmpnn.design.local', 'node_parameters': {'effective_seed': 7, 'num_sequences': 1, 'temperature': .1, 'backbone_noise': .02}, 'binding_parameters': {}},
                ])
                workflow['edges'].extend([
                    {'source_node_id': 'source', 'source_port': 'structure_candidates', 'target_node_id': 'axes', 'target_port': 'structure_candidates'},
                    {'source_node_id': 'axes', 'source_port': 'residue_axes', 'target_node_id': 'design', 'target_port': 'structure_residue_axes'},
                    {'source_node_id': 'constraints', 'source_port': 'constraints', 'target_node_id': 'design', 'target_port': 'constraints'},
                ])
            if score:
                client.patch('/api/v2/module-settings/proteinmpnn.score.local', json={'values': {'provider_root': os.environ['PROTEINMPNN_ROOT']}})
                sequence_input = client.post(base + '/inputs', json={'filename': 'independent.fasta', 'content_base64': base64.b64encode(('>independent\n' + 'A' * 56 + '\n').encode()).decode()}).json()['project_input_ref']
                if not design:
                    workflow['nodes'] = [node for node in workflow['nodes'] if node['node_id'] != 'design']
                    workflow['edges'] = [edge for edge in workflow['edges'] if edge['target_node_id'] != 'design']
                workflow['nodes'].extend([
                    {'node_id': 'sequence', 'node_type_id': 'protein_io.import_sequence', 'binding_id': 'protein_io.import_sequence.direct', 'node_parameters': {'project_input_ref': sequence_input}, 'binding_parameters': {}},
                    {'node_id': 'score', 'node_type_id': 'proteinmpnn.score', 'binding_id': 'proteinmpnn.score.local', 'node_parameters': {'effective_seed': 7, 'backbone_noise': .02, **({'sequence_correspondence': correspondence} if correspondence is not None else {})}, 'binding_parameters': {}},
                ])
                workflow['edges'].extend([
                    {'source_node_id': 'design' if design else 'sequence', 'source_port': 'sequence_candidates', 'target_node_id': 'score', 'target_port': 'sequence_candidates'},
                    {'source_node_id': 'axes', 'source_port': 'residue_axes', 'target_node_id': 'score', 'target_port': 'structure_residue_axes'},
                ])
                if design:
                    other_pdb = '\n'.join(line[:21] + 'B' + line[22:] if line.startswith(('ATOM  ', 'HETATM')) else line for line in Path('examples/v2/structures/3GB1.pdb').read_text().splitlines()) + '\n'
                    other = client.post(base + '/inputs', json={'filename': 'other.pdb', 'content_base64': base64.b64encode(other_pdb.encode()).decode()}).json()['project_input_ref']
                    workflow['nodes'].extend([
                        {'node_id': 'reference', 'node_type_id': 'protein_io.import_structure', 'binding_id': 'protein_io.import_structure.direct', 'node_parameters': {'project_input_ref': other}, 'binding_parameters': {}},
                        {'node_id': 'reference_axes', 'node_type_id': 'structure_transform.resolve_candidate_residue_axes', 'binding_id': 'structure_transform.resolve_candidate_residue_axes.direct', 'node_parameters': {}, 'binding_parameters': {}},
                    ])
                    workflow['edges'] = [edge for edge in workflow['edges'] if not (edge['target_node_id'] == 'score' and edge['target_port'] == 'structure_residue_axes')]
                    workflow['edges'].extend([
                        {'source_node_id': 'reference', 'source_port': 'structure_candidates', 'target_node_id': 'reference_axes', 'target_port': 'structure_candidates'},
                        {'source_node_id': 'reference_axes', 'source_port': 'residue_axes', 'target_node_id': 'score', 'target_port': 'structure_residue_axes'},
                    ])
            if compare_correspondence:
                workflow['nodes'].extend([
                    {'node_id': 'score_reversed', 'node_type_id': 'proteinmpnn.score', 'binding_id': 'proteinmpnn.score.local', 'node_parameters': {'effective_seed': 7, 'backbone_noise': .02, 'sequence_correspondence': [{'sequence_position': 57 - position, 'residue_id': f'A:{position}'} for position in range(1, 57)]}, 'binding_parameters': {}},
                    {'node_id': 'merge', 'node_type_id': 'collection_ops.merge_scores', 'binding_id': 'collection_ops.merge_scores.direct', 'node_parameters': {}, 'binding_parameters': {}},
                ])
                workflow['edges'].extend([
                    {'source_node_id': 'sequence', 'source_port': 'sequence_candidates', 'target_node_id': 'score_reversed', 'target_port': 'sequence_candidates'},
                    {'source_node_id': 'axes', 'source_port': 'residue_axes', 'target_node_id': 'score_reversed', 'target_port': 'structure_residue_axes'},
                    {'source_node_id': 'score', 'source_port': 'scores', 'target_node_id': 'merge', 'target_port': 'scores_a'},
                    {'source_node_id': 'score_reversed', 'source_port': 'scores', 'target_node_id': 'merge', 'target_port': 'scores_b'},
                ])
            committed = client.post(base + '/workflow:commit', json={'workflow': workflow})
            self.assertEqual(committed.status_code, 200, committed.text)
            receipt = client.post(base + '/runs', json={'workflow_commit_id': committed.json()['workflow_commit_id'], 'client_request_id': 'position-omissions'})
            self.assertEqual(receipt.status_code, 202, receipt.text)
            run = base + '/runs/' + receipt.json()['run_id']
            for _ in range(500):
                projection = client.get(run).json()
                if projection['status'] not in ('running', 'admitted'):
                    break
                time.sleep(.01)
            self.assertEqual(projection['status'], expected_status, projection)
            if expected_status != 'succeeded':
                return projection
            if design or score:
                print('Retained ProteinMPNN run:', root, run)
            if compare_correspondence:
                return client.get(run + '/outputs/merge/scores/values/0').json()['value']
            if score and design:
                return {key: client.get(run + f'/outputs/{node}/{port}/values/0').json()['value'] for key, node, port in [('score', 'score', 'scores'), ('sequence', 'design', 'sequence_candidates'), ('source', 'source', 'structure_candidates'), ('reference', 'reference', 'structure_candidates')]}
            if score:
                original = client.get(run + '/outputs/sequence/sequence_candidates/values/0').json()['value']
                self.assertEqual(original['fields']['items'][0]['fields']['parent_ids'], [])
                return client.get(run + '/outputs/score/scores/values/0').json()['value']
            output = '/outputs/design/sequence_candidates/values/0' if design else '/outputs/constraints/constraints/values/0'
            return client.get(run + output).json()['value']
