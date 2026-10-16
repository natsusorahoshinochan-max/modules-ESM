"""Actual structure export nodes, read back using the declared file formats."""
import base64
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import gemmi
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application

PDB = ('HEADER    EXPORT IDENTITY\n'
       'ATOM      1  CA  ALA A  12A      1.000   2.000   3.000  1.00 80.00           C  \n'
       'HETATM    2  O   HOH B  23       4.000   5.000   6.000  1.00 20.00           O  \nEND\n')
CIF = '''data_export
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
ATOM 1 C CA . ALA A 1 1 A 1 2 3 1 80 12 ALA A CA 1
HETATM 2 O O . HOH B 2 . ? 4 5 6 1 20 23 HOH B O 1
#
'''


class StructureExport(unittest.TestCase):
    def request(self, client, method, url, **kwargs):
        response = client.request(method, url, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def test_export_node_converts_both_sources_to_each_declared_target(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}), TestClient(create_application(load_example_results=False)) as client:
            for source_format, text in [('pdb', PDB), ('mmcif', CIF)]:
                project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Export ' + source_format})
                base = '/api/v2/projects/' + project['id']
                uploaded = self.request(client, 'POST', base + '/inputs', json={'filename': 'source.' + source_format, 'content_base64': base64.b64encode(text.encode()).decode()})
                for target in ('pdb', 'mmcif'):
                    with self.subTest(source=source_format, target=target):
                        nodes = [{'node_id': 'source', 'node_type_id': 'protein_io.import_structure', 'binding_id': 'protein_io.import_structure.direct', 'node_parameters': {'project_input_ref': uploaded['project_input_ref']}, 'binding_parameters': {}}]
                        edges = []
                        for node, source_port, target_port in [('single', 'structure', 'structure'), ('candidates', 'structure_candidates', 'structures')]:
                            nodes.append({'node_id': node, 'node_type_id': 'protein_io.export_structure', 'binding_id': 'protein_io.export_structure.direct', 'node_parameters': {'format': target}, 'binding_parameters': {}})
                            edges.append({'source_node_id': 'source', 'source_port': source_port, 'target_node_id': node, 'target_port': target_port})
                        workflow = {'schema_version': '2.1.0', 'workflow_id': project['id'], 'nodes': nodes, 'edges': edges}
                        commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
                        receipt = self.request(client, 'POST', base + '/runs', json={'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': target})
                        run_url = base + '/runs/' + receipt['run_id']
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            run = self.request(client, 'GET', run_url)
                            if run['status'] not in ('running', 'admitted'):
                                break
                            time.sleep(.01)
                        self.assertEqual(run['status'], 'succeeded', run)
                        artifacts = run['artifact_index']
                        self.assertEqual(len(artifacts), 2)
                        for artifact in artifacts:
                            response = client.get(run_url + '/artifacts/' + artifact['artifact_reference'])
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(response.headers['content-type'], 'chemical/x-pdb' if target == 'pdb' else 'chemical/x-mmcif')
                            result = gemmi.read_pdb_string(response.text) if target == 'pdb' else gemmi.make_structure_from_block(gemmi.cif.read_string(response.text).sole_block())
                            atoms = [(chain.name, residue.name, residue.seqid.num, residue.seqid.icode.strip(), atom.name, tuple(atom.pos)) for chain in result[0] for residue in chain for atom in residue]
                            self.assertEqual(atoms, [('A', 'ALA', 12, 'A', 'CA', (1., 2., 3.)), ('B', 'HOH', 23, '', 'O', (4., 5., 6.))])
                            if target == source_format:
                                self.assertEqual(response.text, text)
                        raw = self.request(client, 'GET', run_url + '/outputs/source/structure/values/0')
                        self.assertEqual(raw['value']['fields'][source_format + '_string'], text)


if __name__ == '__main__':
    unittest.main()
