"""Regional operations through persisted public Runs, using small real structures."""
import base64
import os
import json
from dataclasses import asdict
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


def mmcif(residues):
    headers = ('group_PDB id type_symbol label_atom_id label_alt_id label_comp_id '
               'label_asym_id label_entity_id label_seq_id pdbx_PDB_ins_code '
               'Cartn_x Cartn_y Cartn_z occupancy B_iso_or_equiv auth_seq_id '
               'auth_comp_id auth_asym_id auth_atom_id pdbx_PDB_model_num').split()
    rows = []
    for index, (chain, number, insertion, x, y, z) in enumerate(residues, 1):
        rows.append(f'ATOM {index} C CA . ALA {chain} 1 {index} {insertion or "?"} '
                    f'{x} {y} {z} 1 80 {number} ALA {chain} CA 1')
    return 'data_region\nloop_\n' + '\n'.join('_atom_site.' + h for h in headers) + '\n' + '\n'.join(rows) + '\n#\n'


def node(identity, kind, parameters=None, binding=None):
    return dict(node_id=identity, node_type_id=kind, binding_id=binding or kind + '.direct',
                node_parameters=parameters or {}, binding_parameters={})


def edge(source, source_port, target, target_port):
    return dict(source_node_id=source, source_port=source_port,
                target_node_id=target, target_port=target_port)


class RegionalOperations(unittest.TestCase):
    def request(self, client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def project(self, client):
        project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Regions'})
        return project['id'], '/api/v2/projects/' + project['id']

    def upload(self, client, base, text, filename='region.cif'):
        return self.request(client, 'POST', base + '/inputs', json={
            'filename': filename, 'content_base64': base64.b64encode(text.encode()).decode(),
        })['project_input_ref']

    def execute_workflow(self, client, base, workflow, expected_status="succeeded"):
        commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
        receipt = self.request(client, 'POST', base + '/runs', json={
            'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': uuid.uuid4().hex,
        })
        run_url = base + '/runs/' + receipt['run_id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.request(client, 'GET', run_url)
            if result['status'] not in {'running', 'admitted'}:
                break
            time.sleep(.01)
        self.assertEqual(result['status'], expected_status, result)
        return run_url

    def test_colliding_author_labels_fail_without_rewriting_original_data(self):
        text = mmcif([('A', '12A', '', 0, 0, 0), ('A', '12', 'A', 1, 0, 0)])
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                project_id, base = self.project(client)
                source = self.upload(client, base, text)
                workflow = dict(schema_version='2.1.0', workflow_id=project_id, nodes=[
                    node('input', 'protein_io.import_structure', {'project_input_ref': source}),
                    node('axis', 'structure_transform.resolve_candidate_residue_axes'),
                ], edges=[edge('input', 'structure_candidates', 'axis', 'structure_candidates')])
                run = self.execute_workflow(client, base, workflow, expected_status='failed')
                original = self.request(client, 'GET', run + '/outputs/input/structure/values/0')
                self.assertEqual(original['value']['fields']['mmcif_string'], text)
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.request(client, 'GET', run + '/outputs/input/structure/values/0'), original)

    def test_discontinuous_comparison_preserves_full_structures_and_reopens_regions(self):
        subject = mmcif([('A', '10', '', 0, 0, 0), ('A', '11', '', 100, 100, 100),
                          ('A', '12', 'A', 1, 0, 0), ('A', '15', '', 0, 1, 0)])
        reference = mmcif([('B', '20', '', 3, 2, 1), ('B', '21', '', -90, 0, 0),
                            ('B', '22', '', 4, 2, 1), ('B', '25', '', 3, 3, 1)])
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                project_id, base = self.project(client)
                sources = [self.upload(client, base, text) for text in (subject, reference)]
                parameters = {
                    'subject_region': [{'chain_id': 'A', 'residue_number': n, 'insertion_code': i}
                                       for n, i in [('10', ''), ('12', 'A'), ('15', '')]],
                    'reference_region': [{'chain_id': 'B', 'residue_number': n, 'insertion_code': ''}
                                         for n in ['20', '22', '25']],
                }
                workflow = dict(schema_version='2.1.0', workflow_id=project_id, nodes=[
                    *[node(role, 'protein_io.import_structure', {'project_input_ref': source})
                      for role, source in zip(('subject', 'reference'), sources)],
                    *[node(role + '_axis', 'structure_transform.resolve_candidate_residue_axes') for role in ('subject', 'reference')],
                    node('relation', 'collection_ops.relate_to_single_reference'),
                    node('align', 'structure_comparison.align_pairs', parameters,
                         'structure_comparison.align_pairs.sequence_primary_affine'),
                ], edges=[
                    *[edge(role, 'structure_candidates', role + '_axis', 'structure_candidates') for role in ('subject', 'reference')],
                    edge('subject', 'structure_candidates', 'relation', 'subjects'),
                    edge('reference', 'structure_candidates', 'relation', 'references'),
                    edge('relation', 'relation', 'align', 'relation'),
                    *[edge(role + '_axis', 'residue_axes', 'align', role + '_residue_axes') for role in ('subject', 'reference')],
                ])
                for metric in ['rmsd', 'tm_score']:
                    kind = 'structure_comparison.' + metric + '_from_alignments'
                    workflow['nodes'].append(node(metric, kind, binding=kind + '.from_alignment_evidence'))
                    workflow['edges'].extend([
                        edge('align', 'alignments', metric, 'alignments'),
                        edge('subject', 'structure_candidates', metric, 'subjects'),
                        edge('reference', 'structure_candidates', metric, 'references'),
                        edge('relation', 'relation', metric, 'relation'),
                    ])
                run = self.execute_workflow(client, base, workflow)
                for metric, expected in [('rmsd', 0.0), ('tm_score', 1.0)]:
                    score = self.request(client, 'GET', run + f'/outputs/{metric}/scores/values/0')['value']['fields']['entries'][0]['fields']
                    self.assertAlmostEqual(score['value'], expected)
                reading = self.request(client, 'POST', run + '/results:value', json={
                    'node_id': 'align', 'output_port': 'alignments', 'value_index': 0,
                })
                alignment = reading['value']
                self.assertLess(alignment['rmsd'], 1e-10)
                self.assertEqual(alignment['subject_region'], ['A:10', 'A:12A', 'A:15'])
                self.assertEqual(alignment['reference_region'], ['B:20', 'B:22', 'B:25'])
                self.assertEqual(alignment['normalization']['reference_axis_residue_count'], 3)
                self.assertEqual([pair['subject_residue_id'] for pair in alignment['correspondence']], ['A:10', 'A:12A', 'A:15'])
                workflow['nodes'][5]['binding_id'] = 'structure_comparison.align_pairs.structure_first_tm_align'
                tm_run = self.execute_workflow(client, base, workflow)
                tm_alignment = self.request(client, 'POST', tm_run + '/results:value', json={
                    'node_id': 'align', 'output_port': 'alignments', 'value_index': 0,
                })['value']
                self.assertEqual(tm_alignment['subject_region'], ['A:10', 'A:12A', 'A:15'])
                self.assertLess(tm_alignment['rmsd'], 1e-6)
                for role, original in [('subject', subject), ('reference', reference)]:
                    raw = self.request(client, 'GET', run + f'/outputs/{role}/structure/values/0')
                    self.assertEqual(raw['value']['fields']['mmcif_string'], original)
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.request(client, 'POST', run + '/results:value', json={
                    'node_id': 'align', 'output_port': 'alignments', 'value_index': 0,
                }), reading)

    def test_explicit_extraction_creates_child_with_original_numbering_and_preserves_parent(self):
        original = mmcif([('A', '10', '', 0, 0, 0), ('A', '11', '', 1, 0, 0),
                          ('A', 'A42', '', 2, 0, 0), ('A', '12', 'A', 3, 0, 0)])
        # Coordinate-only mmCIF does not require an entity identifier column.
        original = '\n'.join(
            ' '.join(line.split()[:7] + line.split()[8:]) if line.startswith('ATOM ') else line
            for line in original.splitlines() if line != '_atom_site.label_entity_id'
        ) + '\n'
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                project_id, base = self.project(client)
                source = self.upload(client, base, original)
                workflow = dict(schema_version='2.1.0', workflow_id=project_id, nodes=[
                    node('input', 'protein_io.import_structure', {'project_input_ref': source}),
                    node('extract', 'structure_transform.extract_region', {'region': [
                        {'chain_id': 'A', 'residue_number': '10', 'insertion_code': ''},
                        {'chain_id': 'A', 'residue_number': 'A42', 'insertion_code': ''},
                    ]}),
                    node('axis', 'structure_transform.resolve_candidate_residue_axes'),
                ], edges=[edge('input', 'structure_candidates', 'extract', 'structure_candidates'),
                          edge('extract', 'structure_candidates', 'axis', 'structure_candidates')])
                run = self.execute_workflow(client, base, workflow)
                parent = self.request(client, 'GET', run + '/outputs/input/structure_candidates/values/0')['value']['fields']['items'][0]['fields']
                child_value = self.request(client, 'GET', run + '/outputs/extract/structure_candidates/values/0')
                child = child_value['value']['fields']['items'][0]['fields']
                self.assertEqual(child['parent_ids'], [parent['candidate_id']])
                self.assertNotEqual(child['candidate_id'], parent['candidate_id'])
                self.assertEqual(parent['data']['fields']['mmcif_string'], original)
                axis = self.request(client, 'GET', run + '/outputs/axis/residue_axes/values/0')['value']['entries'][0]['residue_axis']
                self.assertEqual(axis['layout']['fields']['residue_ids'], ['A:10', 'A:A42'])
                self.assertEqual(axis['sequence'], 'AA')
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.request(client, 'GET', run + '/outputs/extract/structure_candidates/values/0'), child_value)

    def test_saved_prompt_author_labels_remain_valid_when_source_is_reopened(self):
        original = mmcif([('A', 'A42', '', 0, 0, 0)])
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                project_id, base = self.project(client)
                source = self.upload(client, base, original)
                # A saved document authored before regional operations uses this
                # exact pre-existing source ID. Do not migrate or alias it.
                workflow = dict(schema_version='2.1.0', workflow_id=project_id, nodes=[
                    node('input', 'protein_io.import_structure', {'project_input_ref': source}),
                    node('axis', 'structure_transform.resolve_residue_axis'),
                    node('prompt', 'prompt_authoring.author', {'document': {
                        'target_residues': [{'residue_id': 'A:A42', 'origin': 'source'}],
                    }}),
                ], edges=[edge('input', 'structure', 'axis', 'structure'),
                          edge('axis', 'residue_axis', 'prompt', 'structure_source')])
                self.request(client, 'PUT', base + '/workspace', json={'workflow': workflow, 'ui_state': {}})
            with TestClient(create_application(load_example_results=False)) as client:
                run = self.execute_workflow(client, base, workflow)
                prompt = self.request(client, 'POST', run + '/results:value', json={
                    'node_id': 'prompt', 'output_port': 'protein_prompt', 'value_index': 0,
                })
                self.assertEqual(prompt['value']['residue_ids'], ['A:A42'])

    def test_extracted_modified_residue_keeps_polymer_declarations_for_downstream_resolution(self):
        pdb = ('SEQRES   1 A    3  MSE GLY MSE\n'
               'MODRES 1ABC MSE A   12  MET\nMODRES 1ABC MSE A   14  MET\n'
               'HETATM    1  CA  MSE A  12       0.000   0.000   0.000  1.00 20.00           C  \n'
               'ATOM      2  CA  GLY A  13       1.000   0.000   0.000  1.00 20.00           C  \n'
               'HETATM    3  CA  MSE A  14       2.000   0.000   0.000  1.00 20.00           C  \nEND\n')
        cif = mmcif([('A', str(number), '', index, 0, 0) for index, number in enumerate([12, 13, 14])])
        for index, number, name in [(1, 12, 'MSE'), (2, 13, 'GLY'), (3, 14, 'MSE')]:
            cif = cif.replace(f'ATOM {index} C CA . ALA', f'{"HETATM" if name == "MSE" else "ATOM"} {index} C CA . {name}')
            cif = cif.replace(f'{number} ALA A CA', f'{number} {name} A CA')
        cif += ('loop_\n_entity_poly_seq.entity_id\n_entity_poly_seq.num\n_entity_poly_seq.mon_id\n1 1 MSE\n1 2 GLY\n1 3 MSE\n#\n'
                'loop_\n_pdbx_struct_mod_residue.auth_asym_id\n_pdbx_struct_mod_residue.auth_seq_id\n'
                '_pdbx_struct_mod_residue.PDB_ins_code\n_pdbx_struct_mod_residue.auth_comp_id\n'
                '_pdbx_struct_mod_residue.parent_comp_id\nA 12 ? MSE MET\nA 14 ? MSE MET\n#\n')
        for filename, original in [('region.pdb', pdb), ('region.cif', cif)]:
            with self.subTest(format=filename), tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
                with TestClient(create_application(load_example_results=False)) as client:
                    project_id, base = self.project(client)
                    source = self.upload(client, base, original, filename)
                    workflow = dict(schema_version='2.1.0', workflow_id=project_id, nodes=[
                        node('input', 'protein_io.import_structure', {'project_input_ref': source}),
                        node('extract', 'structure_transform.extract_region', {'region': [
                            {'chain_id': 'A', 'residue_number': '12', 'insertion_code': ''},
                        ]}),
                        node('axis', 'structure_transform.resolve_candidate_residue_axes'),
                    ], edges=[edge('input', 'structure_candidates', 'extract', 'structure_candidates'),
                              edge('extract', 'structure_candidates', 'axis', 'structure_candidates')])
                    run = self.execute_workflow(client, base, workflow)
                    axis = self.request(client, 'GET', run + '/outputs/axis/residue_axes/values/0')['value']['entries'][0]['residue_axis']
                    self.assertEqual(axis['sequence'], 'M')
                    self.assertEqual(axis['layout']['fields']['residue_ids'], ['A:12'])
                    parent = self.request(client, 'GET', run + '/outputs/input/structure_candidates/values/0')['value']['fields']['items'][0]['fields']
                    source_field = 'mmcif_string' if filename.endswith('.cif') else 'pdb_string'
                    self.assertEqual(parent['data']['fields'][source_field], original)

    def test_existing_residue_metrics_are_summarized_without_provider_recalculation(self):
        from protein_workbench_public.module_registry import DEFAULT_MODULES
        original = mmcif([('A', str(number), '', number, 0, 0) for number in [10, 11, 12, 15]])
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}), patch('esm.sdk.esmfold2_client') as provider:
            Path(root, 'modules.json').write_text(json.dumps({'packages': [
                *[asdict(module) for module in DEFAULT_MODULES],
                {'package_id': 'region_observations', 'package_module': 'region_observations',
                 'enabled': True, 'source_root': str(Path(__file__).parent.resolve())},
            ]}))
            with TestClient(create_application(load_example_results=False)) as client:
                project_id, base = self.project(client)
                source = self.upload(client, base, original)
                workflow = dict(schema_version='2.1.0', workflow_id=project_id, nodes=[
                    node('input', 'protein_io.import_structure', {'project_input_ref': source}),
                    node('axis', 'structure_transform.resolve_candidate_residue_axes'),
                    node('measured', 'region_observations.source'),
                    node('statistics', 'structure_comparison.region_statistics', {
                        'metric_id': 'structure.plddt.per_residue', 'missing_values': 'exclude_null',
                        'region': [{'chain_id': 'A', 'residue_number': number, 'insertion_code': ''} for number in ['10', '11', '12']],
                    }),
                    node('downstream', 'region_observations.receive'),
                ], edges=[
                    edge('input', 'structure_candidates', 'axis', 'structure_candidates'),
                    edge('input', 'structure_candidates', 'measured', 'structures'),
                    edge('axis', 'residue_axes', 'measured', 'axes'),
                    edge('measured', 'scores', 'statistics', 'scores'),
                    edge('statistics', 'statistics', 'downstream', 'statistics'),
                ])
                run = self.execute_workflow(client, base, workflow)
                reading = self.request(client, 'POST', run + '/results:value', json={
                    'node_id': 'statistics', 'output_port': 'statistics', 'value_index': 0,
                })
                entry = reading['value']['entries'][0]
                self.assertEqual(entry['region'], ['A:10', 'A:11', 'A:12'])
                self.assertEqual(entry['selected_count'], 3)
                self.assertEqual(entry['valid_count'], 2)
                self.assertEqual(entry['mean'], 50.0)
                self.assertEqual(entry['source_metric']['contract_id'], 'structure.plddt.per_residue')
                self.assertEqual(entry['source_method']['contract_id'], 'region_observations.measured')
                received = self.request(client, 'GET', run + '/outputs/downstream/statistics/values/0')
                self.assertEqual(received['value'], reading['value'])
                provider.assert_not_called()
                strict = json.loads(json.dumps(workflow))
                strict['nodes'][3]['node_parameters']['missing_values'] = 'require_all'
                strict_run = self.execute_workflow(client, base, strict, expected_status='failed')
                states = self.request(client, 'GET', strict_run)['node_dispositions']
                self.assertEqual({entry['node_id']: entry['outcome'] for entry in states}, {'input': 'succeeded', 'axis': 'succeeded', 'measured': 'succeeded', 'statistics': 'failed', 'downstream': 'blocked'})
                empty = json.loads(json.dumps(workflow))
                empty['nodes'][3]['node_parameters']['region'] = [{'chain_id': 'A', 'residue_number': '11', 'insertion_code': ''}]
                empty_run = self.execute_workflow(client, base, empty, expected_status='failed')
                states = self.request(client, 'GET', empty_run)['node_dispositions']
                self.assertEqual({entry['node_id']: entry['outcome'] for entry in states}, {'input': 'succeeded', 'axis': 'succeeded', 'measured': 'succeeded', 'statistics': 'failed', 'downstream': 'blocked'})
                provider.assert_not_called()
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.request(client, 'POST', run + '/results:value', json={
                    'node_id': 'statistics', 'output_port': 'statistics', 'value_index': 0,
                }), reading)


if __name__ == '__main__':
    unittest.main()
