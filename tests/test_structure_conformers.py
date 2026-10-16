"""Conformer selection through the public input and Run APIs."""
import base64
import os
from io import StringIO
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application

PDB = ('HEADER    TWO CONFORMERS\nMODEL        7\n'
       'ATOM      1  CA  ALA A  12A      1.000   2.000   3.000  1.00 80.00           C  \n'
       'ENDMDL\nMODEL       19\n'
       'ATOM      1  CA  GLY B  23       8.000   9.000  10.000  1.00 70.00           C  \n'
       'ENDMDL\nEND\n')
CIF = '''data_conformers
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA X 1 1 A 1.0 2.0 3.0 1.0 80.0 12 ALA alpha CA 7
ATOM 2 C CA . GLY Y 2 1 ? 8.0 9.0 10.0 1.0 70.0 23 GLY beta CA 19
#
'''

class StructureConformers(unittest.TestCase):
    def request(self, client, method, url, **kwargs):
        response = client.request(method, url, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def upload(self, client, text, format):
        project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Conformers'})
        base = '/api/v2/projects/' + project['id']
        source = self.request(client, 'POST', base + '/inputs', json={
            'filename': 'ensemble.' + format, 'content_base64': base64.b64encode(text.encode()).decode(),
        })
        return base, source['project_input_ref']

    def test_inspection_lists_source_models_and_their_own_chains(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                for text, format, chains in [(PDB, 'pdb', [['A'], ['B']]), (CIF, 'mmcif', [['alpha'], ['beta']])]:
                    base, ref = self.upload(client, text, format)
                    result = self.request(client, 'POST', base + '/authoring-actions/protein_io.inspect_input', json={'parameters': {'project_input_ref': ref, 'format': format}})
                    self.assertEqual(result['models'], [
                        {'model_index': 1, 'model_id': '7', 'chain_ids': chains[0]},
                        {'model_index': 2, 'model_id': '19', 'chain_ids': chains[1]},
                    ])

    def run_import(self, client, base, ref, operation, parameters, expected_status='succeeded'):
        node_type = 'protein_io.' + operation
        workflow = {'schema_version': '2.1.0', 'workflow_id': base.rsplit('/', 1)[1], 'nodes': [
            {'node_id': 'source', 'node_type_id': node_type, 'binding_id': node_type + '.direct',
             'node_parameters': {'project_input_ref': ref, **parameters}, 'binding_parameters': {}},
            {'node_id': 'axes', 'node_type_id': 'structure_transform.resolve_candidate_residue_axes',
             'binding_id': 'structure_transform.resolve_candidate_residue_axes.direct',
             'node_parameters': {}, 'binding_parameters': {}},
        ], 'edges': [{'source_node_id': 'source', 'source_port': 'structure_candidates',
                      'target_node_id': 'axes', 'target_port': 'structure_candidates'}]}
        commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
        receipt = self.request(client, 'POST', base + '/runs', json={
            'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': 'import-' + str(time.monotonic_ns())})
        run = base + '/runs/' + receipt['run_id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.request(client, 'GET', run)
            if status['status'] not in ('admitted', 'running'):
                break
            time.sleep(.01)
        self.assertEqual(status['status'], expected_status, status)
        return run

    def test_selected_pdb_model_is_single_and_survives_reopening(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                base, ref = self.upload(client, PDB, 'pdb')
                run = self.run_import(client, base, ref, 'import_structure', {'model_index': 2})
                raw = self.request(client, 'GET', run + '/outputs/source/structure/values/0')
                self.assertIn('MODEL       19', str(raw))
                self.assertNotIn('MODEL        7', str(raw))
                self.assertIn('GLY B  23', str(raw))
                collection = self.request(client, 'GET', run + '/outputs/source/structure_candidates/values/0')
                item = collection['value']['fields']['items'][0]['fields']
                self.assertEqual(dict(item['metadata']['$map'])['source_model_id'], '19')
                self.assertEqual(dict(item['metadata']['$map'])['source_model_index'], 2)
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.request(client, 'GET', run + '/outputs/source/structure/values/0'), raw)
                self.assertEqual(self.request(client, 'GET', run + '/outputs/source/structure_candidates/values/0'), collection)

    def test_split_both_formats_preserves_models_and_candidate_identity_after_reopen(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            for text, format in [(PDB, 'pdb'), (CIF, 'mmcif')]:
                with TestClient(create_application(load_example_results=False)) as client:
                    base, ref = self.upload(client, text, format)
                    run = self.run_import(client, base, ref, 'import_structures', {'model_indices': [2, 1]})
                    url = run + '/outputs/source/structure_candidates/values/0'
                    collection = self.request(client, 'GET', url)
                    items = [item['fields'] for item in collection['value']['fields']['items']]
                    self.assertEqual(len(items), 2)
                    self.assertNotEqual(items[0]['candidate_id'], items[1]['candidate_id'])
                    self.assertEqual([dict(item['metadata']['$map'])['source_model_id'] for item in items], ['19', '7'])
                    self.assertIn('GLY', str(items[0]['data']))
                    self.assertNotIn('ALA', str(items[0]['data']))
                    self.assertIn('ALA', str(items[1]['data']))
                    self.assertNotIn('GLY', str(items[1]['data']))
                    if format == 'mmcif':
                        self.assertIn('alpha', str(items[1]['data']))
                        self.assertIn('beta', str(items[0]['data']))
                        first = MMCIF2Dict(StringIO(items[1]['data']['fields']['mmcif_string']))
                        self.assertEqual(first['_atom_site.auth_asym_id'], ['alpha'])
                        self.assertEqual(first['_atom_site.auth_seq_id'], ['12'])
                        self.assertEqual(first['_atom_site.pdbx_PDB_ins_code'], ['A'])
                        self.assertEqual(first['_atom_site.pdbx_PDB_model_num'], ['7'])
                        self.assertEqual(first['_atom_site.Cartn_x'], ['1.0'])
                    else:
                        self.assertIn(PDB.splitlines()[2], items[1]['data']['fields']['pdb_string'])
                with TestClient(create_application(load_example_results=False)) as client:
                    self.assertEqual(self.request(client, 'GET', url), collection)
                    # Single-model mmCIF selection uses the same public single-value contract.
                    if format == 'mmcif':
                        selected = self.run_import(client, base, ref, 'import_structure', {'model_index': 1})
                        value = self.request(client, 'GET', selected + '/outputs/source/structure/values/0')
                        self.assertIn('alpha', str(value))
                        self.assertNotIn('beta', str(value))

    def test_multi_model_input_requires_a_selection_and_invalid_models_fail(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                for text, format in [(PDB, 'pdb'), (CIF, 'mmcif')]:
                    base, ref = self.upload(client, text, format)
                    for operation, parameters in [('import_structure', {}), ('import_structure', {'model_index': 3}), ('import_structures', {'model_indices': [1, 3]})]:
                        run = self.run_import(client, base, ref, operation, parameters, expected_status='failed')
                        status = self.request(client, 'GET', run)
                        self.assertEqual(status['outputs'], [])
                        self.assertIn('blocked', str(status['node_dispositions']))
                    # Selection never replaces the uploaded ensemble, including after failed imports.
                    inspected = self.request(client, 'POST', base + '/authoring-actions/protein_io.inspect_input', json={'parameters': {'project_input_ref': ref, 'format': format}})
                    self.assertEqual([model['model_id'] for model in inspected['models']], ['7', '19'])

    def test_mmcif_selection_keeps_only_the_selected_atoms_anisotropic_values(self):
        source = CIF + """loop_
_atom_site_anisotrop.id
_atom_site_anisotrop.pdbx_PDB_model_num
_atom_site_anisotrop.U[1][1]
_atom_site_anisotrop.U[2][2]
_atom_site_anisotrop.U[3][3]
_atom_site_anisotrop.U[1][2]
_atom_site_anisotrop.U[1][3]
_atom_site_anisotrop.U[2][3]
1 7 0.1 0.2 0.3 0.0 0.0 0.0
2 19 0.4 0.5 0.6 0.0 0.0 0.0
#
"""
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                base, ref = self.upload(client, source, 'mmcif')
                run = self.run_import(client, base, ref, 'import_structure', {'model_index': 2})
                value = self.request(client, 'GET', run + '/outputs/source/structure/values/0')
                parsed = MMCIF2Dict(StringIO(value['value']['fields']['mmcif_string']))
                self.assertEqual(parsed['_atom_site_anisotrop.id'], ['2'])
                self.assertEqual(parsed['_atom_site_anisotrop.U[1][1]'], ['0.4'])

    def test_model_without_anisotropic_atoms_has_no_empty_anisotropic_loop(self):
        source = CIF + "loop_\n_atom_site_anisotrop.id\n_atom_site_anisotrop.U[1][1]\n1 0.1\n#\n"
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                base, ref = self.upload(client, source, 'mmcif')
                run = self.run_import(client, base, ref, 'import_structure', {'model_index': 2})
                value = self.request(client, 'GET', run + '/outputs/source/structure/values/0')
                self.assertNotIn('_atom_site_anisotrop.', value['value']['fields']['mmcif_string'])

if __name__ == '__main__':
    unittest.main()
