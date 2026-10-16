"""Whole-batch and explicit backbone scopes through the public Workflow API."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


def node(name, kind, parameters=None):
    return {'node_id': name, 'node_type_id': kind, 'binding_id': kind + '.direct',
            'node_parameters': parameters or {}, 'binding_parameters': {}}


def edge(source, output, target, input_port):
    return {'source_node_id': source, 'source_port': output,
            'target_node_id': target, 'target_port': input_port}


class TopKScopes(unittest.TestCase):
    def scenario(self, client, missing_scores=False):
        project = client.post('/api/v2/projects', json={'name': 'Composable top-k'}).json()['id']
        base = '/api/v2/projects/' + project
        nodes, edges = [], []
        for group, sequences in [('a', '>a1\nACDE\n>a2\nCDEF\n'), ('b', '>b1\nDEFG\n>b2\nEFGH\n')]:
            upload = client.post(base + '/inputs', json={'filename': group + '.fasta',
                'content_base64': base64.b64encode(sequences.encode()).decode()}).json()
            nodes.append(node(group, 'protein_io.import_sequences', {'project_input_ref': upload['project_input_ref']}))
            # Distinct independently imported structures are evaluation references, not parents.
            pdb = f'ATOM      1  CA  GLY A   1    {0 if group == "a" else 10:8.3f}   0.000   0.000  1.00 20.00           C  \nEND\n'
            uploaded = client.post(base + '/inputs', json={'filename': group + '.pdb',
                'content_base64': base64.b64encode(pdb.encode()).decode()}).json()
            nodes.append(node('backbone_' + group, 'protein_io.import_structure', {'project_input_ref': uploaded['project_input_ref']}))
            nodes.append(node('relation_' + group, 'collection_ops.relate_to_single_reference'))
            edges += [edge(group, 'sequence_candidates', 'relation_' + group, 'subjects'),
                      edge('backbone_' + group, 'structure_candidates', 'relation_' + group, 'references')]
        nodes += [node('all_candidates', 'collection_ops.concat_candidates'),
                  node('all_backbones', 'collection_ops.concat_candidates'),
                  node('all_relations', 'collection_ops.concat_relations'), node('evaluate', 'topk_demo.observe')]
        for group in ['a', 'b']:
            edges += [edge(group, 'sequence_candidates', 'all_candidates', 'candidates_' + group),
                      edge('backbone_' + group, 'structure_candidates', 'all_backbones', 'candidates_' + group),
                      edge('relation_' + group, 'relation', 'all_relations', 'relation_' + group)]
        edges += [edge('a' if missing_scores else 'all_candidates', 'sequence_candidates' if missing_scores else 'candidates', 'evaluate', 'subjects'),
                  edge('backbone_a' if missing_scores else 'all_backbones', 'structure_candidates' if missing_scores else 'candidates', 'evaluate', 'references'),
                  edge('relation_a' if missing_scores else 'all_relations', 'relation', 'evaluate', 'relation')]
        objectives = []
        for name, source, k in [('global', 'all_candidates', 2), ('per_a', 'scope_a', 1), ('per_b', 'scope_b', 1)]:
            if name != 'global':
                group = name[-1]
                nodes.append(node(source, 'collection_ops.select_related_subjects'))
                edges += [edge('all_candidates', 'candidates', source, 'subjects'),
                          edge('backbone_' + group, 'structure_candidates', source, 'selected_references'),
                          edge('all_relations', 'relation', source, 'relation')]
            nodes.append(node(name, 'selection.top_k', {'k': k, 'objective_id': name, 'out_of_scope_policy': 'ignore'}))
            edges += [edge(source, 'candidates', name, 'candidates'), edge('evaluate', 'scores', name, 'scores')]
            objectives.append({'objective_id': name, 'candidate_input': {'node_id': source, 'output_port': 'candidates'},
                'score_collection_input': {'node_id': 'evaluate', 'output_port': 'scores'},
                'metric': {'contract_kind': 'metric', 'contract_id': 'topk_demo.compatibility'},
                'method': {'contract_kind': 'method', 'contract_id': 'topk_demo.method'},
                'context_selector': {'kind': 'pairwise', 'subject_role': 'subject', 'reference_role': 'reference',
                    'pairing_mode': 'explicit_relation', 'normalization': 'test_scale'},
                'utility_transform': {'contract_kind': 'utility_transform', 'contract_id': 'topk_demo.identity'},
                'utility_parameters': {}, 'weight': 1, 'source_partition': 'compatibility',
                'match_cardinality': 'exactly_one', 'missing_policy': 'error'})
        saved = client.post(base + '/workflow:commit', json={'workflow': {'schema_version': '2.1.0',
            'workflow_id': project, 'nodes': nodes, 'edges': edges, 'selection_objectives': objectives}})
        self.assertEqual(saved.status_code, 200, saved.text)
        started = client.post(base + '/runs', json={'workflow_commit_id': saved.json()['workflow_commit_id'],
            'client_request_id': 'topk'})
        self.assertEqual(started.status_code, 202, started.text)
        run = base + '/runs/' + started.json()['run_id']
        deadline = time.monotonic() + 10
        while True:
            result = client.get(run).json()
            if result['status'] not in ('admitted', 'running'):
                return run, result
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)

    def application(self, root):
        Path(root, 'modules.json').write_text(json.dumps({'packages': [
            {'package_id': name, 'package_module': 'modules.' + name + '.package', 'enabled': True, 'source_root': None}
            for name in ['protein_io', 'collection_ops', 'selection']
        ] + [{'package_id': 'topk_demo', 'package_module': 'topk_module', 'enabled': True,
              'source_root': str(Path(__file__).parent.resolve())}]}))
        return create_application(load_example_results=False)

    def test_global_and_backbone_top_k_preserve_exact_candidates_and_evaluation_relations(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(self.application(root)) as client:
                run, result = self.scenario(client)
                self.assertEqual(result['status'], 'succeeded', result)
                def items(name, port='candidates'):
                    value = client.get(run + f'/outputs/{name}/{port}/values/0')
                    self.assertEqual(value.status_code, 200, value.text)
                    return value.json()['value']['fields']['items']
                originals = items('all_candidates')
                self.assertEqual(items('global'), originals[:2])
                self.assertEqual(items('per_a'), originals[:1])
                self.assertEqual(items('per_b'), originals[2:3])
                self.assertTrue(all(item['fields']['parent_ids'] == [] for item in originals))
                relations = client.get(run + '/outputs/all_relations/relation/values/0').json()['value']['fields']['entries']
                self.assertEqual(len(relations), 4)
                scores = client.get(run + '/outputs/evaluate/scores/values/0').json()['value']['fields']['entries']
                self.assertEqual([score['fields']['value'] for score in scores], [.9, .8, .7, .6])
                self.assertEqual([score['fields']['context']['fields']['reference']['fields']['candidate'] for score in scores],
                                 [relation['fields']['reference'] for relation in relations])

    def test_missing_required_scores_stop_top_k_without_dropping_candidates(self):
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(self.application(root)) as client:
                run, result = self.scenario(client, missing_scores=True)
                self.assertEqual(result['status'], 'failed', result)
                outcomes = {item['node_id']: item['outcome'] for item in result['node_dispositions']}
                self.assertEqual(outcomes['evaluate'], 'succeeded')
                self.assertEqual(outcomes['global'], 'failed')
                self.assertEqual(outcomes['per_b'], 'failed')
                self.assertEqual(outcomes['per_a'], 'succeeded')
                self.assertNotEqual(client.get(run + '/outputs/global/candidates/values/0').status_code, 200)
                self.assertNotEqual(client.get(run + '/outputs/per_b/candidates/values/0').status_code, 200)
                scores = client.get(run + '/outputs/evaluate/scores/values/0').json()['value']['fields']['entries']
                self.assertEqual([score['fields']['value'] for score in scores], [.9, .8])
