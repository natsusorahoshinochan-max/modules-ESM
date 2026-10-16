"""Mixed structural components through the published-result API."""
import base64
import json
import os
import tempfile
import time
import unittest
import gemmi
from unittest.mock import patch
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from modules.protein_io.structure_components import EXPORT_COMPONENTS_ACTION

# Protein, ligand, metal, water and DNA have distinct authored residue identities.
MIXED_PDB = (
    'HEADER    MIXED STRUCTURE\n'
    'ATOM      1  CA  ALA A  12A      1.000   2.000   3.000  1.00 80.00           C  \n'
    'HETATM    2  C1  LIG B 201       4.000   2.000   3.000  1.00 20.00           C  \n'
    'HETATM    3  O1  LIG B 201       5.000   2.000   3.000  1.00 20.00           O  \n'
    'HETATM    4 ZN    ZN C 301       8.000   2.000   3.000  1.00 20.00          ZN  \n'
    'HETATM    5  O   HOH D 401      11.000   2.000   3.000  1.00 20.00           O  \n'
    'ATOM      6  P    DA E 501      14.000   2.000   3.000  1.00 20.00           P  \n'
    'CONECT    2    3\nCONECT    3    2\nEND\n'
)

MIXED_CIF = """data_mixed
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
ATOM 1 C CA . ALA A 1 1 A 1.0 2.0 3.0 1.0 80.0 12 ALA A CA 1
HETATM 2 C C1 . LIG B 2 . ? 4.0 2.0 3.0 1.0 20.0 201 LIG B C1 1
HETATM 3 O O1 . LIG B 2 . ? 5.0 2.0 3.0 1.0 20.0 201 LIG B O1 1
HETATM 4 Zn ZN . ZN C 3 . ? 8.0 2.0 3.0 1.0 20.0 301 ZN C ZN 1
HETATM 5 O O . HOH D 4 . ? 11.0 2.0 3.0 1.0 20.0 401 HOH D O 1
ATOM 6 P P . DA E 5 1 ? 14.0 2.0 3.0 1.0 20.0 501 DA E P 1
#
"""

class StructureComponents(unittest.TestCase):
    def request(self, client, method, url, **kwargs):
        response = client.request(method, url, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def create_run(self, client, source=MIXED_PDB, format='pdb'):
        project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Mixed structure'})
        base = '/api/v2/projects/' + project['id']
        uploaded = self.request(client, 'POST', base + '/inputs', json={
            'filename': 'mixed.' + format, 'content_base64': base64.b64encode(source.encode()).decode()})
        workflow = {'schema_version': '2.1.0', 'workflow_id': project['id'], 'nodes': [{
            'node_id': 'input', 'node_type_id': 'protein_io.import_structure',
            'binding_id': 'protein_io.import_structure.direct',
            'node_parameters': {'project_input_ref': uploaded['project_input_ref']}, 'binding_parameters': {},
        }], 'edges': []}
        commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
        receipt = self.request(client, 'POST', base + '/runs', json={
            'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': 'mixed'})
        run = base + '/runs/' + receipt['run_id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.request(client, 'GET', run)
            if status['status'] not in ('admitted', 'running'):
                break
            time.sleep(.01)
        self.assertEqual(status['status'], 'succeeded', status)
        return run

    def action(self, client, run, name, parameters):
        return self.request(client, 'POST', run + '/results:action', json={
            'node_id': 'input', 'output_port': 'structure_candidates', 'value_index': 0,
            'action_id': 'protein_io.' + name, 'parameters': {'item_index': 0, **parameters}})

    def test_components_are_addressed_without_protein_residue_axis_filtering(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                run = self.create_run(client)
                result = self.action(client, run, 'structure_components', {})
                self.assertEqual([(item['kind'], item['residue_name'], item['chain_id'], item['residue_number'], item['insertion_code'], item['atom_count']) for item in result['components']], [
                    ('protein', 'ALA', 'A', '12', 'A', 1), ('other', 'LIG', 'B', '201', '', 2),
                    ('metal', 'ZN', 'C', '301', '', 1), ('water', 'HOH', 'D', '401', '', 1),
                    ('nucleic_acid', 'DA', 'E', '501', '', 1)])
                self.assertEqual(result['atoms'][3], {'component_index': 3, 'name': 'ZN', 'element': 'Zn', 'x': 8.0, 'y': 2.0, 'z': 3.0})

    def test_each_nonprotein_component_exports_in_both_formats_without_changing_source(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                for source, source_format in [(MIXED_PDB, 'pdb'), (MIXED_CIF, 'mmcif')]:
                    run = self.create_run(client, source, source_format)
                    url = run + '/outputs/input/structure_candidates/values/0'
                    original = self.request(client, 'GET', url)
                    for index, name, chain, number in [(2, 'LIG', 'B', 201), (3, 'ZN', 'C', 301), (4, 'HOH', 'D', 401), (5, 'DA', 'E', 501)]:
                        for target in ['pdb', 'mmcif']:
                            result = self.action(client, run, 'export_structure_components', {'component_indices': [index], 'format': target})
                            parsed = gemmi.read_pdb_string(result['text']) if target == 'pdb' else gemmi.make_structure_from_block(gemmi.cif.read_string(result['text']).sole_block())
                            self.assertEqual([(c.name, r.name, r.seqid.num) for model in parsed for c in model for r in c], [(chain, name, number)])
                            self.assertEqual(result['component_indices'], [index])
                    self.assertEqual(self.request(client, 'GET', url), original)
            with TestClient(create_application(load_example_results=False)) as client:
                self.assertEqual(self.request(client, 'GET', url), original)

    def test_selected_ligand_keeps_its_bonds_and_chain_termination(self):
        source = MIXED_PDB.replace('HETATM    4', 'TER       7      LIG B 201\nHETATM    4')
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                run = self.create_run(client, source)
                result = self.action(client, run, 'export_structure_components', {'component_indices': [2], 'format': 'pdb'})
                self.assertIn('TER       7      LIG B 201', result['text'])
                self.assertIn('CONECT    2    3', result['text'])
                self.assertIn('HEADER    MIXED STRUCTURE', result['text'])

    def test_selected_components_retain_only_connections_with_both_endpoints(self):
        link = list(' ' * 80)
        link[:6] = 'LINK  '
        link[12:16], link[17:20], link[21], link[22:26] = ' O1 ', 'LIG', 'B', ' 201'
        link[42:46], link[47:50], link[51], link[52:56] = ' O  ', 'HOH', 'D', ' 401'
        record = ''.join(link)
        source = MIXED_PDB.replace('END\n', record + '\nEND\n')
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                run = self.create_run(client, source)
                together = self.action(client, run, 'export_structure_components', {'component_indices': [2, 4], 'format': 'pdb'})
                self.assertIn(record, together['text'])
                separate = self.action(client, run, 'export_structure_components', {'component_indices': [2], 'format': 'pdb'})
                self.assertNotIn('LINK', separate['text'])

    def test_mmcif_connection_does_not_switch_to_another_insertion_code(self):
        source = MIXED_CIF.replace('LIG B 2 . ? 4.0', 'LIG B 2 . A 4.0').replace('O O1 . LIG B 2 . ? 5.0', 'C C1 . LIG B 2 . B 5.0').replace('201 LIG B O1', '201 LIG B C1')
        source += """loop_
_struct_conn.id
_struct_conn.ptnr1_auth_asym_id
_struct_conn.ptnr1_auth_seq_id
_struct_conn.ptnr1_label_atom_id
_struct_conn.pdbx_ptnr1_PDB_ins_code
_struct_conn.ptnr2_auth_asym_id
_struct_conn.ptnr2_auth_seq_id
_struct_conn.ptnr2_label_atom_id
_struct_conn.pdbx_ptnr2_PDB_ins_code
link1 B 201 C1 A D 401 O ?
#
"""
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                run = self.create_run(client, source, 'mmcif')
                selected_b = self.action(client, run, 'export_structure_components', {'component_indices': [3, 5], 'format': 'mmcif'})
                self.assertNotIn('_struct_conn.', selected_b['text'])
                selected_a = self.action(client, run, 'export_structure_components', {'component_indices': [2, 5], 'format': 'mmcif'})
                self.assertIn('_struct_conn.id', selected_a['text'])
                self.assertIn('link1', selected_a['text'])

    def test_export_action_keeps_atom_records_in_their_own_model(self):
        atoms = MIXED_PDB.splitlines()[1:3]
        blocks = []
        records = {}
        for model in [1, 2]:
            lines = [f'MODEL     {model:4d}']
            for serial, atom in enumerate(atoms, start=1):
                lines.append(atom)
                attached = [
                    record + atom[6:28] + ''.join(f'{model * 1000 + serial:7d}' for _ in range(6)) + atom[70:]
                    for record in ['ANISOU', 'SIGUIJ']
                ]
                attached.append('SIGATM' + atom[6:30] + f'{model / 10:8.3f}' + atom[38:])
                records[model, serial] = attached
                lines.extend(attached)
            blocks.extend([*lines, 'ENDMDL'])
        source = '\n'.join([*blocks, 'END']) + '\n'
        # A module action accepts the published Candidate wire contract, including
        # ensembles published by modules other than the single-model importer.
        encoded = json.dumps({'value': {'$dataclass': 'candidate_collection', 'fields': {
            'collection_id': 'ensemble', 'item_type': 'protein.structure', 'items': [
                {'$dataclass': 'candidate', 'fields': {'candidate_id': 'ensemble-candidate',
                 'data': {'$dataclass': 'protein_structure', 'fields': {'pdb_string': source}},
                 'parent_ids': [], 'metadata': {'$map': []}}},
            ],
        }}}).encode()
        original = bytes(encoded)
        result = EXPORT_COMPONENTS_ACTION.apply(encoded, {
            'item_index': 0, 'component_indices': [1, 4], 'format': 'pdb',
        }, ())
        for identity in [(1, 1), (2, 2)]:
            for record in records[identity]:
                self.assertIn(record, result['text'])
        for identity in [(1, 2), (2, 1)]:
            for record in records[identity]:
                self.assertNotIn(record, result['text'])
        self.assertEqual(encoded, original)

if __name__ == '__main__':
    unittest.main()
