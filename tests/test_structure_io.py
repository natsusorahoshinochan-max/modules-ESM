import io
import json
import zipfile

import gemmi
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.run_helpers import wait_response


def research():
    lines = ['ATOM      1  CA  ALA X  12A      1.000   2.000   3.000  1.00 80.00           C  ',
             'HETATM    2  C1  LIG L  91       4.000   5.000   6.000  0.50 20.00           C  ',
             'HETATM    3 ZN    ZN M  -2       7.000   8.000   9.000  1.00 20.00          ZN  ',
             'HETATM    4  O   HOH W   3      10.000  11.000  12.000  1.00 20.00           O  ',
             'ATOM      5  P    DA N  40      13.000  14.000  15.000  1.00 20.00           P  ']
    return ('MODEL        7\n'+'\n'.join(lines)+'\nENDMDL\nMODEL        9\n'+'\n'.join(lines).replace('1.000   2.000', '2.000   2.000')+'\nENDMDL\nEND\n').encode()


def run(client, project, kind, inputs, parameters):
    response = client.put(f'/api/projects/{project}', json={'flow': {'nodes': [{'id': 'operation', 'type': kind, 'inputs': inputs, 'parameters': parameters}], 'edges': []}, 'layout': {}})
    assert response.status_code == 200, response.text
    return wait_response(client, client.post(f'/api/projects/{project}/runs')).json()['nodes']['operation']


def test_multimodel_import_keeps_all_components_and_reopens_real_numbering(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Research'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {'manifest.json': json.dumps({'name': 'research.pdb', 'file': 'original.pdb', 'format': 'pdb'}).encode(), 'original.pdb': research()})
        result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 'all'})
        assert result['status'] == 'succeeded', result
        package = result['outputs']['structures'][0]
    with TestClient(create_application(data_root=tmp_path)) as client:
        def read(key):
            return client.get(f'/api/packages/{package}/file', params={'key': key}).content
        manifest = json.loads(read('manifest.json'))
        assert [o['source']['model'] for o in manifest['objects']] == [7, 9]
        assert read('original.pdb') == research()
        assert 'tool' not in manifest
        for obj in manifest['objects']:
            atoms = json.loads(read(obj['atoms']))
            assert [a['residue_name'] for a in atoms] == ['ALA', 'LIG', 'ZN', 'HOH', 'DA']
            assert atoms[0]['chain'] == 'X' and atoms[0]['author_number'] == 12 and atoms[0]['insertion_code'] == 'A'
            assert atoms[2]['author_number'] == -2
            actual = gemmi.read_pdb_string(read(obj['structure']['file']))
            assert actual[0].num == obj['source']['model']
            assert actual[0]['X'][0].seqid.icode == 'A'


def test_selected_component_exports_mmcif_then_pdb_zip_with_source_parameters(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Export'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {'manifest.json': json.dumps({'name': 'research.pdb', 'file': 'raw', 'format': 'pdb'}).encode(), 'raw': research()})
        imported = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 9})['outputs']['structures'][0]
        manifest = client.get(f'/api/packages/{imported}/file', params={'key': 'manifest.json'}).json()
        obj = manifest['objects'][0]
        result = run(client, project, 'workbench.export_structure', {'structures': [imported]}, {'object': obj['id'], 'format': 'mmcif', 'atoms': [1, 2, 3, 4]})
        assert result['status'] == 'succeeded', result
        output = result['outputs']['structures'][0]
        response = client.get(f'/api/packages/{output}/export.zip')
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            index = json.loads(bundle.read('package.json'))
            files = {f['key']: bundle.read(f['member']) for f in index['files']}
        exported = json.loads(files['manifest.json'])['objects'][0]
        actual = gemmi.make_structure_from_block(gemmi.cif.read_string(files[exported['structure']['file']].decode()).sole_block())
        assert actual[0].num == 9 and actual[0].count_atom_sites() == 4
        assert [r.name for c in actual[0] for r in c] == ['LIG', 'ZN', 'HOH', 'DA']
        assert exported['selection'] == {'source_object': obj['id'], 'atoms': [1, 2, 3, 4]}
        assert files['original.pdb'] == research()
        assert 'not recalculated' in files['export-notes.txt'].decode()
        again = run(client, project, 'workbench.export_structure', {'structures': [output]}, {'object': exported['id'], 'format': 'pdb'})
        assert again['status'] == 'succeeded', again


def test_mmcif_chain_limit_and_invalid_model_fail_without_modifying_original(tmp_path):
    cif = gemmi.read_pdb_string(research()).make_mmcif_document().as_string().replace(' X ', ' LONG ')
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Limits'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {'manifest.json': json.dumps({'name': 'wide.cif', 'file': 'raw', 'format': 'mmcif'}).encode(), 'raw': cif.encode()})
        failed = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 3})
        assert failed['status'] == 'failed' and 'available models' in str(failed['diagnostics'])
        result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 7})
        assert result['status'] == 'succeeded', result
        package = result['outputs']['structures'][0]
        document = client.get(f'/api/packages/{package}/file', params={'key': 'manifest.json'}).json()
        failed = run(client, project, 'workbench.export_structure', {'structures': [package]}, {'object': document['objects'][0]['id'], 'format': 'pdb'})
        assert failed['status'] == 'failed' and 'chain' in str(failed['diagnostics'])
        assert client.get(f"/api/packages/{raw['id']}/file", params={'key': 'raw'}).content == cif.encode()


def test_imported_structure_is_independently_compared_without_prediction_history(tmp_path):
    from tests.test_comparison import pdb
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Independent'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {'manifest.json': json.dumps({'name': 'independent.pdb', 'file': 'raw', 'format': 'pdb'}).encode(), 'raw': pdb()})
        result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 1})
        package = result['outputs']['structures'][0]
        assert client.delete('/api/modules/workbench.structure_io').status_code == 200
        result = run(client, project, 'workbench.compare', {'subject': [package], 'reference': [package]}, {})
        assert result['status'] == 'succeeded', result
        document = client.get(f"/api/packages/{result['outputs']['comparison'][0]}/file", params={'key': 'manifest.json'}).json()
        assert 'generation' not in document['subject']
        assert document['metrics']['tm_subject']['value'] == 1.0


def test_mmcif_missing_author_correspondence_is_not_repaired_from_labels(tmp_path):
    cif = gemmi.read_pdb_string(research()).make_mmcif_document().sole_block()
    column = cif.find_values('_atom_site.auth_seq_id')
    column[0] = '?'
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Missing actual numbering'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {'manifest.json': json.dumps({'name': 'missing.cif', 'file': 'raw', 'format': 'mmcif'}).encode(), 'raw': cif.as_string().encode()})
        result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 7})
        assert result['status'] == 'failed' and 'author' in str(result['diagnostics'])


def test_existing_prediction_export_preserves_parameters_and_source_bytes(tmp_path):
    from tests.test_comparison import pdb
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Existing prediction'}).json()['id']
        document = {'objects': [{'id': 'predicted', 'sequence': 'AAAAA', 'structure': {'file': 'calculated.pdb', 'format': 'pdb'}}],
                    'tool': {'id': 'actual.method', 'parameters': {'seed': 0, 'steps': 2}}}
        package = upload(client, project, 'workbench.prediction', {'manifest.json': json.dumps(document).encode(), 'calculated.pdb': pdb(), 'parameters.txt': b'Actual original parameters: seed=0; steps=2'})
        result = run(client, project, 'workbench.export_structure', {'structures': [package['id']]}, {'object': 'predicted', 'format': 'mmcif', 'atoms': [5]})
        assert result['status'] == 'succeeded', result
        response = client.get(f"/api/packages/{result['outputs']['structures'][0]}/export.zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            index = json.loads(bundle.read('package.json'))
            files = {f['key']: bundle.read(f['member']) for f in index['files']}
        exported = json.loads(files['manifest.json'])
        assert exported['tool'] == document['tool']
        assert files['parameters.txt'] == b'Actual original parameters: seed=0; steps=2'
        assert files['calculated.pdb'] == pdb()
        assert exported['objects'][0]['source_object'] == document['objects'][0]
        assert 'sequence' not in exported['objects'][0] and 'confidence' not in exported['objects'][0]
        assert 'not recalculated' in files['export-notes.txt'].decode()
