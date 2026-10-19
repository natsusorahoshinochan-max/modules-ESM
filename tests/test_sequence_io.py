"""Sequence import handoff through real HTTP, persistence and ZIP bytes."""
import io
import json
import zipfile

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.run_helpers import wait_response


def upload(client, project, format, files, entry='manifest.json'):
    base = f'/api/projects/{project}/uploads'
    base += '/' + client.post(base).json()['upload_id']
    for key, content in files.items():
        response = client.put(base + '/files', params={'key': key}, content=content)
        assert response.status_code == 200, response.text
    response = client.post(base + '/commit', json={'format': format, 'entry': entry, 'files': {key: key for key in files}})
    assert response.status_code == 200, response.text
    return response.json()


def test_explicit_sequence_correspondence_survives_prediction_and_reopening(tmp_path):
    sequence = {'id': 'research-sequence', 'sequence': 'ACD', 'label': 'Original fragment',
                'source': {'name': 'original.fa', 'record': 'fragment chain Z'},
                'positions': [{'sequence_index': 1, 'chain': 'Z', 'author_number': 12, 'insertion_code': ''},
                              {'sequence_index': 2, 'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'},
                              {'sequence_index': 3, 'chain': 'Z', 'author_number': 19, 'insertion_code': ''}]}
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.post('/api/modules', json={'entry_point': 'tests.fixtures.prediction_tool:module'})
        client.put('/api/modules/lab.predictor/settings', json={'settings': {'prefix': 'actual'}})
        project = client.post('/api/projects', json={'name': 'Imported sequence'}).json()['id']
        package = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [sequence]}).encode()})
        flow = {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]},
                           'tools': {'predictor': 'lab.external'}, 'tool_parameters': {'predictor': {'seed': 0}}}], 'edges': []}
        assert client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {'x': 2}}).status_code == 200
        result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        assert result['status'] == 'succeeded', result
        output = result['nodes']['predict']['outputs']['structure'][0]
    with TestClient(create_application(data_root=tmp_path)) as client:
        assert client.get(f'/api/projects/{project}').json()['flow'] == flow
        document = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
        assert document['objects'][0]['input'] == sequence
        assert document['tool'] == {'id': 'lab.external', 'parameters': {'seed': 0}}
        archive = client.get(f'/api/packages/{output}/export.zip')
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            index = json.loads(bundle.read('package.json'))
            files = {item['key']: bundle.read(item['member']) for item in index['files']}
            assert json.loads(files[index['entry']]) == document
            assert files['structure.pdb'] == b'actual seed=0 sequence=ACD'
            assert json.loads(files['confidence.json']) == {'plddt': [0.8, 0.9, 0.7]}


def test_incomplete_supplied_positions_fail_without_guessing_or_tool_calls(tmp_path, monkeypatch):
    def forbid(_settings):
        def predict(*_args):
            raise AssertionError('Tool must not be called for incomplete correspondence')
        return predict
    monkeypatch.setattr('tests.fixtures.prediction_tool.create', forbid)
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.post('/api/modules', json={'entry_point': 'tests.fixtures.prediction_tool:module'})
        project = client.post('/api/projects', json={'name': 'Incomplete positions'}).json()['id']
        document = {'objects': [{'id': 'incomplete', 'sequence': 'ACD', 'positions': [{'sequence_index': 1, 'chain': 'X'}]}]}
        content = json.dumps(document).encode()
        package = upload(client, project, 'workbench.sequence', {'manifest.json': content})
        flow = {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': 'lab.external'}}], 'edges': []}
        assert client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {}}).status_code == 200
        result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        assert result['status'] == 'failed'
        assert 'positions must cover every sequence residue' in str(result['nodes']['predict']['diagnostics'])
        assert result['nodes']['predict']['outputs'] == {}
        assert client.get(f"/api/packages/{package['id']}/file", params={'key': 'manifest.json'}).content == content


def test_external_module_zip_preserves_its_data_format_and_existing_parameter_description(tmp_path):
    files = {'external.bin': b'\x00\xff\x11\x80', 'parameters.txt': b'Existing calculation: seed=0; count=2\n'}
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'External data'}).json()['id']
        package = upload(client, project, 'independent.custom-format', files, entry='external.bin')
        for module in client.get('/api/modules').json():
            client.put(f"/api/modules/{module['id']}/enabled", json={'enabled': False}).raise_for_status()
    with TestClient(create_application(data_root=tmp_path)) as client:
        response = client.get(f"/api/packages/{package['id']}/export.zip")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            index = json.loads(bundle.read('package.json'))
            assert index['format'] == 'independent.custom-format'
            assert index['entry'] == 'external.bin'
            assert {item['key']: bundle.read(item['member']) for item in index['files']} == files
