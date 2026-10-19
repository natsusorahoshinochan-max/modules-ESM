"""Structure conditions through public temporary interaction files and packages."""
import json
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload

PDB = b'ATOM      1  CA  ALA X  12A      1.000   2.000   3.000  1.00 80.00           C  \nHETATM    2 ZN    ZN M  -2       7.000   8.000   9.000  1.00 20.00          ZN  \nEND\n'


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


def test_local_structure_adoption_preserves_files_real_positions_and_only_selected_tracks(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects',json={'name':'Structure conditions'}).json()['id']
        package = upload(client, project, 'workbench.structure_set', {
            'manifest.json':json.dumps({'objects':[{'id':'structure','structure':{'file':'original.pdb','format':'pdb'}}]}).encode(), 'original.pdb':PDB})
        document = {'id':'edit','sequence':'GC','positions':[
            {'id':'g','residue':'G','prompt':'_','fixed':False,'coordinates':None},
            {'id':'c','residue':'C','prompt':'C','fixed':True,'coordinates':{'CA':[9,9,9]}}], 'random_operations':[]}
        parameters = {'document':document,'object':'structure','operation':{'kind':'adopt_structure','tracks':['coordinates'],
            'mapping':[{'edit_position':'g','position':{'chain':'X','author_number':12,'insertion_code':'A'}}]}}
        token, adopted, data = invoke(client,project,parameters,{'structures':[package['id']]})
        assert adopted['sequence'] == 'GC' and adopted['positions'][0]['prompt'] == '_'
        assert adopted['positions'][0]['coordinates'] == {'CA':[1,2,3]}
        assert adopted['positions'][1] == document['positions'][1]
        assert adopted['positions'][0]['structure_position']['position']['insertion_code'] == 'A'
        assert data['position_count'] == 2
        accepted = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        source_key = adopted['structures'][0]['files']['original.pdb']
        assert client.get(f"/api/packages/{accepted['id']}/file",params={'key':source_key}).content == PDB
        assert client.get(f'/api/projects/{project}/runs').json() == []
        inspected, reopened, _ = invoke(client,project,{'document':adopted,'object':'structure'},{'source':[accepted['id']]})
        assert reopened == adopted
        client.delete(f'/api/interactions/{inspected}').raise_for_status()
        token, moved, _ = invoke(client,project,{'document':adopted,'operation':{'kind':'transform_coordinates','positions':['g'],
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
        _, moved, _ = invoke(client,project,{'document':document,'operation':{'kind':'transform_coordinates','positions':['a'],
            'rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation':[10,0,0]}})
        token, cleared = preview(client,project,{'document':moved,'operation':{'kind':'update','positions':['a'],'changes':{'coordinates':None}}})
        assert cleared['positions'][0]['coordinates'] is None
        client.delete(f'/api/interactions/{token}').raise_for_status()
        token, reset = preview(client,project,{'document':cleared,'operation':{'kind':'update','positions':['a'],'changes':{'coordinates':{'CA':[2,4,6]}}}})
        assert reset['positions'][0]['coordinates'] == {'CA':[2,4,6]}
        assert reset['positions'][1] == document['positions'][1]
        accepted = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        assert client.get(f"/api/packages/{accepted['id']}/file",params={'key':'edited.json'}).json() == reset
        _, restored = preview(client,project,{'document':moved})
        assert restored['positions'][0]['coordinates'] == {'CA':[11,2,3]}
