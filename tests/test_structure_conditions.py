"""Structure conditions through public temporary interaction files and packages."""
import json
import pytest
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload

PDB = b'ATOM      1  CA  ALA X  12A      1.000   2.000   3.000  1.00 80.00           C  \nHETATM    2 ZN    ZN M  -2       7.000   8.000   9.000  1.00 20.00          ZN  \nEND\n'


@pytest.mark.parametrize('accepted_source', [False, True])
def test_coordinate_document_requires_one_explicit_file_backed_base(tmp_path, accepted_source):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name':'One accepted base'}).json()['id']
        document = {'id':'edit','sequence':'A','positions':[{'id':'a','residue':'A','prompt':'A','fixed':True,'coordinates':None}], 'random_operations':[]}
        inputs = {}
        if accepted_source:
            package = upload(client,project,'workbench.sequence_conditions',{'edited.json':json.dumps(document).encode()},entry='edited.json')
            inputs['source'] = [package['id']]
        else:
            document['positions'][0]['coordinates'] = {'CA':[100,20,30]}
        begun = client.post(f'/api/projects/{project}/interactions', json={'interaction':'workbench.sequence_edit','inputs':inputs,'parameters':{'document':document}})
        begun.raise_for_status()
        result = client.post(f'/api/interactions/{begun.json()["id"]}/execute')
        assert result.status_code == 400
        assert ('accepted source' if accepted_source else 'file-backed') in result.text


def invoke(client, project, parameters, inputs=None):
    response = client.post(f'/api/projects/{project}/interactions', json={
        'interaction':'workbench.sequence_structure', 'inputs':inputs or {}, 'parameters':parameters})
    assert response.status_code == 200, response.text
    token = response.json()['id']
    result = client.post(f'/api/interactions/{token}/execute')
    assert result.status_code == 200, result.text
    data = result.json()['data']
    assert 'document' not in data
    document = client.get(f'/api/interactions/{token}/file', params={'output':'edited','key':data['document_file']})
    document.raise_for_status()
    return token, document.json(), data


def test_repeated_adoptions_address_exact_retained_records_after_source_deletion(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name':'Repeated adoption'}).json()['id']
        package = upload(client, project, 'workbench.structure_set', {
            'manifest.json':json.dumps({'objects':[{'id':'structure','label':'Original structure','structure':{'file':'original.pdb','format':'pdb'}}]}).encode(),
            'original.pdb':PDB, 'research.txt':b'original research bytes'})
        document = {'id':'edit','sequence':'AA','positions':[{'id':key,'residue':'A','prompt':'A','fixed':True,'coordinates':None} for key in ('a','b')], 'random_operations':[]}
        accepted = None
        for identity in ('a','b'):
            parameters = {'structure':{'input':'structures','object':'structure'}, 'operation':{'kind':'adopt_structure','tracks':['coordinates'],
                'mapping':[{'edit_position':identity,'position':{'chain':'X','author_number':12,'insertion_code':'A'}}]}}
            inputs = {'structures':[package['id']]}
            if accepted:
                inputs['source'] = [accepted['id']]
            else:
                parameters['document'] = document
            token, document, _ = invoke(client, project, parameters, inputs)
            response = client.post(f'/api/interactions/{token}/accept', json={'output':'edited'})
            response.raise_for_status(); accepted = response.json()
        records = document['structures']
        assert len(records) == 2 and records[0]['id'] != records[1]['id']
        assert [row['structure_position']['structure'] for row in document['positions']] == [record['id'] for record in records]
        target = client.post('/api/projects', json={'name':'Independent retained input'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id':accepted['id']})
        adopted.raise_for_status(); independent = adopted.json()['id']
        client.delete(f'/api/projects/{project}').raise_for_status()
        for record in records:
            token, inspected, data = invoke(client, target, {'structure':{'retained':record['id']}}, {'source':[independent]})
            assert inspected == document
            geometry = client.get(f'/api/interactions/{token}/file', params={'output':'edited','key':data['view_file']}).json()
            assert len(geometry) == 2 and any(atom['residue_name'] == 'ZN' for atom in geometry)
            client.delete(f'/api/interactions/{token}').raise_for_status()
            for original, retained in record['files'].items():
                response = client.get(f'/api/packages/{independent}/file', params={'key':retained})
                response.raise_for_status()
                if original == 'original.pdb': assert response.content == PDB
                if original == 'research.txt': assert response.content == b'original research bytes'
        token, reused, _ = invoke(client, target, {'structure':{'retained':records[0]['id']}, 'operation':{'kind':'adopt_structure','tracks':['coordinates'],
            'mapping':[{'edit_position':'b','position':{'chain':'X','author_number':12,'insertion_code':'A'}}]}}, {'source':[independent]})
        assert reused['structures'] == records
        assert reused['positions'][1]['structure_position']['structure'] == records[0]['id']
        received = client.post(f'/api/interactions/{token}/accept', json={'output':'edited'}).json()
        token, reread, _ = invoke(client, target, {'structure':{'retained':records[0]['id']}}, {'source':[received['id']]})
        assert reread == reused
        client.delete(f'/api/interactions/{token}').raise_for_status()


def test_local_structure_adoption_preserves_files_real_positions_and_only_selected_tracks(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects',json={'name':'Structure conditions'}).json()['id']
        package = upload(client, project, 'workbench.structure_set', {
            'manifest.json':json.dumps({'objects':[{'id':'structure','structure':{'file':'original.pdb','format':'pdb'}}]}).encode(), 'original.pdb':PDB})
        document = {'id':'edit','sequence':'GC','positions':[
            {'id':'g','residue':'G','prompt':'_','fixed':False,'coordinates':None},
            {'id':'c','residue':'C','prompt':'C','fixed':True,'coordinates':{'CA':[9,9,9]}}], 'random_operations':[]}
        base = upload(client,project,'workbench.sequence_conditions',{'edited.json':json.dumps(document).encode()},entry='edited.json')
        parameters = {'structure':{'input':'structures','object':'structure'},'operation':{'kind':'adopt_structure','tracks':['coordinates'],
            'mapping':[{'edit_position':'g','position':{'chain':'X','author_number':12,'insertion_code':'A'}}]}}
        token, adopted, data = invoke(client,project,parameters,{'structures':[package['id']],'source':[base['id']]})
        assert adopted['sequence'] == 'GC' and adopted['positions'][0]['prompt'] == '_'
        assert adopted['positions'][0]['coordinates'] == {'CA':[1,2,3]}
        assert adopted['positions'][1] == document['positions'][1]
        assert adopted['positions'][0]['structure_position']['position']['insertion_code'] == 'A'
        assert data['position_count'] == 2
        accepted = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        source_key = adopted['structures'][0]['files']['original.pdb']
        assert client.get(f"/api/packages/{accepted['id']}/file",params={'key':source_key}).content == PDB
        assert client.get(f'/api/projects/{project}/runs').json() == []
        inspected, reopened, _ = invoke(client,project,{'structure':{'retained':adopted['structures'][0]['id']}},{'source':[accepted['id']]})
        assert reopened == adopted
        client.delete(f'/api/interactions/{inspected}').raise_for_status()
        token, moved, _ = invoke(client,project,{'operation':{'kind':'transform_coordinates','positions':['g'],
            'rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation':[10,0,0]}},{'source':[accepted['id']]})
        assert moved['positions'][0]['coordinates'] == {'CA':[11,2,3]}
        assert moved['positions'][1] == document['positions'][1]
        client.delete(f'/api/interactions/{token}').raise_for_status()
        assert client.get(f"/api/packages/{accepted['id']}/file",params={'key':source_key}).content == PDB


def test_clear_then_set_coordinates_never_replays_a_previous_transform(tmp_path):
    from tests.test_editor_interactions import preview
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects',json={'name':'Materialized coordinates'}).json()['id']
        document = {'id':'edit','sequence':'AC','positions':[
            {'id':'a','residue':'A','prompt':'A','fixed':True,'coordinates':{'CA':[1,2,3]}},
            {'id':'c','residue':'C','prompt':'C','fixed':True,'coordinates':{'CA':[8,8,8]}}], 'random_operations':[]}
        base = upload(client,project,'workbench.sequence_conditions',{'edited.json':json.dumps(document).encode()},entry='edited.json')
        token, moved, _ = invoke(client,project,{'operation':{'kind':'transform_coordinates','positions':['a'],
            'rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation':[10,0,0]}},{'source':[base['id']]})
        moved_package = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        token, cleared = preview(client,project,{'operation':{'kind':'update','positions':['a'],'changes':{'coordinates':None}}},{'source':[moved_package['id']]})
        assert cleared['positions'][0]['coordinates'] is None
        cleared_package = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        token, reset = preview(client,project,{'operation':{'kind':'update','positions':['a'],'changes':{'coordinates':{'CA':[2,4,6]}}}},{'source':[cleared_package['id']]})
        assert reset['positions'][0]['coordinates'] == {'CA':[2,4,6]}
        assert reset['positions'][1] == document['positions'][1]
        accepted = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        assert client.get(f"/api/packages/{accepted['id']}/file",params={'key':'edited.json'}).json() == reset
        _, restored = preview(client,project,{}, {'source':[moved_package['id']]})
        assert restored['positions'][0]['coordinates'] == {'CA':[11,2,3]}
