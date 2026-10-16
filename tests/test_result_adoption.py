"""Historical result adoption through the public application API."""
import base64
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class ResultAdoption(unittest.TestCase):
    def run_workflow(self, client, project_id, nodes, edges=(), selectors=(), status="succeeded", objectives=()):
        base = '/api/v2/projects/' + project_id
        saved = client.post(base + '/workflow:commit', json={'workflow': {
            'schema_version': '2.1.0', 'workflow_id': project_id,
            'nodes': nodes, 'edges': list(edges), 'observation_selectors': list(selectors), 'selection_objectives': list(objectives)}})
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
        self.assertEqual(result['status'], status, result)
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
                copied = client.post(f'/api/v2/projects/{target}:duplicate', json={'name': 'Independent copy'})
                self.assertEqual(copied.status_code, 201, copied.text)
                copy_id = copied.json()['id']
                self.assertEqual(client.get(f'/api/v2/projects/{copy_id}/runs').json()['runs'], [])
                client.post(f'/api/v2/projects/{target}:trash')
                client.delete(f'/api/v2/projects/{target}')
                copied_run = self.run_workflow(client, copy_id, [node])
                self.assertEqual(client.get(copied_run + '/outputs/adopted/value/values/0').content, original.content)


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
                for name in ('protein_io', 'selection', 'collection_ops')
            ] + [{'package_id': 'adoption_demo', 'package_module': 'adoption_module', 'enabled': True,
                  'source_root': str(Path(__file__).parent.resolve())},
                 {'package_id': 'reader_demo', 'package_module': 'reader_module', 'enabled': True,
                  'source_root': str(Path(__file__).parent.resolve())}]}))
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'Source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'Target'}).json()['id']
                uploaded = client.post(f'/api/v2/projects/{source}/inputs', json={
                    'filename': 'sequence.fasta', 'content_base64': base64.b64encode(b'>original\nACDE\n').decode()}).json()
                source_run = self.run_workflow(client, source, [
                    {'node_id': 'a-unrelated', 'node_type_id': 'reader_demo.observe',
                     'binding_id': 'reader_demo.observe.direct', 'binding_parameters': {}, 'node_parameters': {}},
                    {'node_id': 'import', 'node_type_id': 'protein_io.import_sequences',
                     'binding_id': 'protein_io.import_sequences.direct', 'binding_parameters': {},
                     'node_parameters': {'project_input_ref': uploaded['project_input_ref']}},
                    {'node_id': 'observe', 'node_type_id': 'adoption_demo.observe',
                     'binding_id': 'adoption_demo.observe.direct', 'binding_parameters': {}, 'node_parameters': {'stop': True}},
                    {'node_id': 'blocked', 'node_type_id': 'collection_ops.merge_scores',
                     'binding_id': 'collection_ops.merge_scores.direct', 'binding_parameters': {}, 'node_parameters': {}}],
                    [{'source_node_id': 'import', 'source_port': 'sequence_candidates',
                      'target_node_id': 'observe', 'target_port': 'candidates'},
                     {'source_node_id': 'observe', 'source_port': 'scores', 'target_node_id': 'blocked', 'target_port': 'scores_a'}], status='failed')
                unrelated = client.get(source_run + '/outputs/a-unrelated/observation/values/0')
                self.assertEqual(unrelated.status_code, 200, unrelated.text)
                disabled_unrelated = client.put('/api/v2/modules', json={
                    'enabled_package_ids': ['protein_io', 'selection', 'collection_ops', 'adoption_demo']})
                self.assertEqual(disabled_unrelated.status_code, 200, disabled_unrelated.text)
                original = client.get(source_run + '/outputs/observe/scores/values/0').content
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': source_run.rsplit('/', 1)[1],
                    'node_id': 'observe', 'output_port': 'scores', 'value_index': 0})
                self.assertEqual(adopted.status_code, 201, adopted.text)
                unchanged = client.get(source_run).json()
                self.assertEqual(unchanged['status'], 'failed')
                self.assertEqual(next(item['outcome'] for item in unchanged['node_dispositions'] if item['node_id'] == 'blocked'), 'blocked')
                node = adopted.json()['source_node'] | {'node_id': 'adopted'}
                candidates = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': source_run.rsplit('/', 1)[1],
                    'node_id': 'import', 'output_port': 'sequence_candidates', 'value_index': 0})
                self.assertEqual(candidates.status_code, 201, candidates.text)
                candidates_node = candidates.json()['source_node'] | {'node_id': 'candidates'}
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

                disabled = client.put('/api/v2/modules', json={'enabled_package_ids': ['protein_io', 'selection']})
                self.assertEqual(disabled.status_code, 200, disabled.text)
                filtered_run = self.run_workflow(client, target, [node, candidates_node, {
                    'node_id': 'filter', 'node_type_id': 'selection.filter', 'binding_id': 'selection.filter.direct',
                    'binding_parameters': {}, 'node_parameters': {'selector_ids': ['value'],
                    'expression': [{'selector_index': 0, 'operator': '>', 'threshold': 0.5}], 'out_of_scope_policy': 'error'}}],
                    [{'source_node_id': 'candidates', 'source_port': 'value', 'target_node_id': 'filter', 'target_port': 'candidates'},
                     {'source_node_id': 'adopted', 'source_port': 'value', 'target_node_id': 'filter', 'target_port': 'scores'}],
                    [{'selector_id': 'value', 'candidate_input': {'node_id': 'candidates', 'output_port': 'value'},
                      'score_collection_input': {'node_id': 'adopted', 'output_port': 'value'},
                      'metric': {'contract_kind': 'metric', 'contract_id': 'adoption_demo.value'},
                      'method': {'contract_kind': 'method', 'contract_id': 'adoption_demo.method'},
                      'context_selector': {'kind': 'intrinsic'}, 'source_partition': 'value',
                      'match_cardinality': 'exactly_one', 'missing_policy': 'error'}])
                filtered = client.get(filtered_run + '/outputs/filter/candidates/values/0')
                self.assertEqual(filtered.status_code, 200, filtered.text)
                self.assertIn('ACDE', filtered.text)

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

    def test_pairwise_scores_retain_axes_evidence_and_rank_after_source_deletion(self):
        def node(identity, kind, parameters=None, binding='direct'):
            return {'node_id': identity, 'node_type_id': kind, 'binding_id': kind + '.' + binding,
                    'node_parameters': parameters or {}, 'binding_parameters': {}}
        def edge(source, port, target, input_port):
            return {'source_node_id': source, 'source_port': port, 'target_node_id': target, 'target_port': input_port}
        with TemporaryDirectory() as root, patch.dict('os.environ', {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                source = client.post('/api/v2/projects', json={'name': 'Pairwise source'}).json()['id']
                target = client.post('/api/v2/projects', json={'name': 'Saved comparison'}).json()['id']
                imports = []
                for name, translation in [('subject', 0), ('reference', 10)]:
                    lines = []
                    for residue, (x, y, z) in enumerate([(0, 0, 0), (3, 1, 0), (6, 0, 1)], 1):
                        for offset, atom in enumerate(['N', 'CA', 'C', 'O']):
                            lines.append(f"ATOM  {len(lines)+1:5d} {atom:>4} GLY A{residue:4d}    {x+offset*.2+translation:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00          {atom[0]:>2}  ")
                    uploaded = client.post(f'/api/v2/projects/{source}/inputs', json={
                        'filename': name + '.pdb', 'content_base64': base64.b64encode(('\n'.join(lines)+'\nEND\n').encode()).decode()}).json()
                    imports.append(node(name, 'protein_io.import_structure', {'project_input_ref': uploaded['project_input_ref']}))
                run = self.run_workflow(client, source, imports + [
                    node('subject_axis', 'structure_transform.resolve_candidate_residue_axes'),
                    node('reference_axis', 'structure_transform.resolve_candidate_residue_axes'),
                    node('relation', 'collection_ops.relate_to_single_reference'),
                    node('align', 'structure_comparison.align_pairs', binding='sequence_primary_affine'),
                    node('score', 'structure_comparison.tm_score_from_alignments', binding='from_alignment_evidence')], [
                    edge('subject', 'structure_candidates', 'subject_axis', 'structure_candidates'),
                    edge('reference', 'structure_candidates', 'reference_axis', 'structure_candidates'),
                    edge('subject', 'structure_candidates', 'relation', 'subjects'),
                    edge('reference', 'structure_candidates', 'relation', 'references'),
                    edge('subject_axis', 'residue_axes', 'align', 'subject_residue_axes'),
                    edge('reference_axis', 'residue_axes', 'align', 'reference_residue_axes'),
                    edge('relation', 'relation', 'align', 'relation'),
                    edge('align', 'alignments', 'score', 'alignments'),
                    edge('subject', 'structure_candidates', 'score', 'subjects'),
                    edge('reference', 'structure_candidates', 'score', 'references'),
                    edge('relation', 'relation', 'score', 'relation')])
                originals = {name: client.get(run + path).content for name, path in {
                    'score': '/outputs/score/scores/values/0',
                    'subject': '/outputs/subject/structure_candidates/values/0',
                    'reference': '/outputs/reference/structure_candidates/values/0',
                    'evidence': '/outputs/align/alignments/values/0'}.items()}
                adopted = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': source, 'source_run_id': run.rsplit('/', 1)[1],
                    'node_id': 'score', 'output_port': 'scores', 'value_index': 0})
                self.assertEqual(adopted.status_code, 201, adopted.text)
                source_node = adopted.json()['source_node'] | {'node_id': 'saved'}
                self.assertEqual(client.post(f'/api/v2/projects/{source}:trash').status_code, 200)
                self.assertEqual(client.delete(f'/api/v2/projects/{source}').status_code, 200)
            with TestClient(create_application(load_example_results=False)) as client:
                metadata = client.get(f"/api/v2/projects/{target}/inputs/{adopted.json()['project_input_ref']}:adoption").json()
                self.assertIn(originals['evidence'].decode(), [item['canonical_value'] for item in metadata['dependencies']])
                self.assertEqual(sum(item['port_type_id'] == 'structure_transform.candidate_resolved_residue_axis_associations' for item in metadata['dependencies']), 2)
                options = client.post(f'/api/v2/projects/{target}/workflow:observation-options', json={
                    'workflow': {'nodes': [source_node], 'edges': []}, 'ranking': True})
                self.assertEqual(options.status_code, 200, options.text)
                self.assertEqual(len(options.json()['options']), 1)
                option = options.json()['options'][0]
                ranked = self.run_workflow(client, target, [source_node,
                    node('rank', 'selection.sort', {'objective_id': 'comparison'})], [
                    edge('saved', 'subjects', 'rank', 'candidates'), edge('saved', 'value', 'rank', 'scores')],
                    objectives=[{'objective_id': 'comparison', 'candidate_input': {'node_id': 'saved', 'output_port': 'subjects'},
                        'score_collection_input': option['source'], 'metric': {'contract_kind': 'metric', 'contract_id': option['metric_id']},
                        'method': {'contract_kind': 'method', 'contract_id': option['method_id']}, 'context_selector': option['context'],
                        'source_partition': option['partition'], 'utility_transform': {'contract_kind': 'utility_transform',
                            'contract_id': 'structure_comparison.tm_score.explicit_relation.identity'},
                        'utility_parameters': {}, 'weight': 1, 'match_cardinality': 'exactly_one', 'missing_policy': 'error'}])
                self.assertEqual(client.get(ranked + '/outputs/saved/value/values/0').content, originals['score'])
                import json
                self.assertEqual(client.get(ranked + '/outputs/rank/candidates/values/0').json()['value']['fields']['items'],
                                 json.loads(originals['subject'])['value']['fields']['items'])
                self.assertEqual(client.get(ranked + '/outputs/saved/references/values/0').json()['value']['fields']['items'],
                                 json.loads(originals['reference'])['value']['fields']['items'])

                reused = client.post(f'/api/v2/projects/{target}/inputs:adopt', json={
                    'source_project_id': target, 'source_run_id': ranked.rsplit('/', 1)[1],
                    'node_id': 'saved', 'output_port': 'references', 'value_index': 0})
                self.assertEqual(reused.status_code, 201, reused.text)
                reference_metadata = client.get(f"/api/v2/projects/{target}/inputs/{reused.json()['project_input_ref']}:adoption").json()
                self.assertEqual(reference_metadata['parameters']['records'][0]['node_id'], 'saved')
