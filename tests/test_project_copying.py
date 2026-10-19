"""Tutorial drafts and copied projects own independent inputs through public HTTP."""
from copy import deepcopy
import sqlite3

import pytest

from tests.run_helpers import wait_response

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def test_tutorial_first_save_creates_editable_user_project_without_changing_original(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        response = client.get('/api/tutorial')
        assert response.status_code == 200, response.text
        tutorial = response.json()
        assert tutorial['tutorial'] is True
        assert tutorial['flow']['nodes']
        assert client.get('/api/projects').json() == []
        draft = deepcopy(tutorial)
        draft['flow']['nodes'][0]['parameters'] = {'seed': 0}
        draft['layout'] = {'predict': {'x': 77, 'y': 34}}
        saved = client.post(f"/api/projects/{tutorial['id']}/copies", json={
            'name': 'My research', 'flow': draft['flow'], 'layout': draft['layout'],
        })
        assert saved.status_code == 200, saved.text
        own = saved.json()
        assert own['id'] != tutorial['id']
        assert own.get('tutorial', False) is False
        assert own['flow']['nodes'][0]['parameters'] == {'seed': 0}
        assert own['layout'] == draft['layout']
        original_id = tutorial['flow']['nodes'][0]['inputs']['sequence'][0]
        copied_id = own['flow']['nodes'][0]['inputs']['sequence'][0]
        assert copied_id != original_id
        assert client.get(f'/api/packages/{copied_id}/file', params={'key': 'sequence.json'}).json()['objects'][0]['sequence'] == 'ACDEFGHIK'
        assert client.get('/api/tutorial').json() == tutorial
        assert client.put(f"/api/projects/{tutorial['id']}", json={'flow': draft['flow'], 'layout': draft['layout']}).status_code == 400
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        assert reopened.get(f"/api/projects/{own['id']}").json() == own
        assert reopened.get(f"/api/projects/{own['id']}/runs").json() == []


def test_tutorial_new_input_stays_temporary_until_first_save(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        tutorial = client.get('/api/tutorial').json()
        base = '/api/projects/tutorial/uploads'
        token = client.post(base).json()['upload_id']
        base += '/' + token
        client.put(base + '/files', params={'key': 'data'}, content=b'draft input')
        response = client.post(base + '/commit', json={'format': 'custom.input', 'entry': 'data', 'files': {'data': 'data'}})
        assert response.status_code == 200, response.text
        package = response.json()['id']
        assert client.get('/api/projects').json() == []
        assert len(client.get('/api/projects/tutorial/packages').json()) == 1
        assert client.get(f'/api/packages/{package}/file', params={'key': 'data'}).content == b'draft input'
        tutorial['flow']['nodes'][0]['inputs'] = {'sequence': [package]}
        response = client.post('/api/projects/tutorial/copies', json={'name': 'My imported input', 'flow': tutorial['flow'], 'layout': tutorial['layout']})
        assert response.status_code == 200, response.text
        copied = response.json()['flow']['nodes'][0]['inputs']['sequence'][0]
        assert client.delete(f'/api/draft-inputs/{package}').status_code == 200
        assert client.get(f'/api/packages/{package}').status_code == 400
        assert client.get(f'/api/packages/{copied}/file', params={'key': 'data'}).content == b'draft input'


def _input(client, project, content):
    base = f'/api/projects/{project}/uploads'
    upload = client.post(base).json()['upload_id']
    base += '/' + upload
    client.put(base + '/files', params={'key': 'request'}, content=content)
    return client.post(base + '/commit', json={'format': 'independent.request', 'entry': 'request', 'files': {'request': 'request'}}).json()['id']


def test_copy_reopens_with_adopted_and_selected_result_inputs_after_sources_deleted(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.post('/api/modules', json={'entry_point': 'tests.fixtures.host_module:module'})
        origin = client.post('/api/projects', json={'name': 'Origin'}).json()['id']
        imported = _input(client, origin, b'research input')
        source = client.post('/api/projects', json={'name': 'Source'}).json()['id']
        adopted = client.post(f'/api/projects/{source}/adoptions', json={'package_id': imported}).json()['id']
        node = {'id': 'encode', 'type': 'independent.encode', 'parameters': {'suffix': '!'}, 'inputs': {'source': [adopted]}}
        flow = {'nodes': [node], 'edges': []}
        layout = {'encode': {'x': 12, 'y': 87}}
        client.put(f'/api/projects/{source}', json={'flow': flow, 'layout': layout})
        result = wait_response(client, client.post(f'/api/projects/{source}/runs', json={})).json()
        selected = result['nodes']['encode']['outputs']['result'][0]
        wait_response(client, client.post(f'/api/projects/{source}/runs', json={}))
        assert len(client.get(f'/api/projects/{source}/packages').json()) == 3
        node.update(tools={'slot': 'chosen.tool'}, tool_parameters={'slot': {'seed': 0}})
        # The selected historical result is now an explicit input; other output is excluded.
        flow['nodes'].append({'id': 'later', 'type': 'missing.consumer', 'parameters': {}, 'inputs': {'items': [selected, adopted]}})
        flow['edges'] = [{'source': 'encode', 'source_port': 'result', 'target': 'later', 'target_port': 'items'}]
        client.put(f'/api/projects/{source}', json={'flow': flow, 'layout': layout})
        response = client.post(f'/api/projects/{source}/copies', json={'name': 'Independent copy'})
        assert response.status_code == 200, response.text
        copied = response.json()
        assert copied['layout'] == layout
        assert copied['flow']['edges'] == flow['edges']
        assert copied['flow']['nodes'][0]['parameters'] == {'suffix': '!'}
        assert copied['flow']['nodes'][0]['tools'] == {'slot': 'chosen.tool'}
        assert copied['flow']['nodes'][0]['tool_parameters'] == {'slot': {'seed': 0}}
        assert client.delete(f'/api/projects/{origin}').status_code == 200
        assert client.delete(f'/api/projects/{source}').status_code == 200
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        project = reopened.get(f"/api/projects/{copied['id']}").json()
        assert project == copied
        assert reopened.get(f"/api/projects/{copied['id']}/runs").json() == []
        bound = project['flow']['nodes']
        assert bound[0]['inputs']['source'][0] == bound[1]['inputs']['items'][1]
        assert len(reopened.get(f"/api/projects/{copied['id']}/packages").json()) == 2
        assert reopened.get(f"/api/packages/{bound[0]['inputs']['source'][0]}/file", params={'key': 'request'}).content == b'research input'
        assert reopened.get(f"/api/packages/{bound[1]['inputs']['items'][0]}/file", params={'key': 'entry.bin'}).content == b'research input!'


@pytest.mark.parametrize('failure', ['write', 'commit', 'file'])
def test_failed_first_save_leaves_no_project_or_copied_files(tmp_path, monkeypatch, failure):
    with TestClient(create_application(data_root=tmp_path)) as client:
        tutorial = client.get('/api/tutorial').json()
        before = sorted(path.name for path in (tmp_path / 'packages').iterdir())
        connect = sqlite3.connect

        class RefusedCopy(sqlite3.Connection):
            def execute(self, statement, parameters=()):
                if failure == 'write' and statement.startswith('INSERT INTO records'):
                    raise sqlite3.OperationalError('copy write refused')
                return super().execute(statement, parameters)

            def commit(self):
                if failure == 'commit' and self.in_transaction:
                    raise sqlite3.OperationalError('copy commit refused')
                return super().commit()

        if failure == 'file':
            # A filesystem failure at the real byte boundary, with all public calls real.
            package = tutorial['flow']['nodes'][0]['inputs']['sequence'][0]
            (tmp_path / 'packages' / package / '0').unlink()
        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=RefusedCopy))
            response = client.post('/api/projects/tutorial/copies', json={'name': 'Failed copy'})
            assert response.status_code == 400, response.text
            assert 'copy' in response.json()['detail'].lower() or 'read' in response.json()['detail'].lower()
        assert client.get('/api/projects').json() == []
        assert client.get('/api/tutorial').json() == tutorial
        assert sorted(path.name for path in (tmp_path / 'packages').iterdir()) == before


def test_tutorial_original_rejects_mutation_and_retains_template_without_modules(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        original = client.get('/api/tutorial').json()
        for module in client.get('/api/modules').json():
            assert client.delete('/api/modules/' + module['id']).status_code == 200
        tutorial = client.get('/api/tutorial').json()
        assert tutorial['flow'] == original['flow']
        assert tutorial['missing_modules'] == ['workbench.predict']
        assert client.delete('/api/projects/tutorial').status_code == 400
        assert client.post('/api/projects/tutorial/runs', json={}).status_code == 400
        source = tutorial['flow']['nodes'][0]['inputs']['sequence'][0]
        assert client.post('/api/projects/tutorial/adoptions', json={'package_id': source}).status_code == 400
        copied = client.post('/api/projects/tutorial/copies', json={'name': 'Continue offline'})
        assert copied.status_code == 200
        assert copied.json()['missing_modules'] == ['workbench.predict']


def test_temporary_teaching_input_can_be_viewed_exported_and_adopted_before_save(tmp_path):
    import io
    import json
    import zipfile

    with TestClient(create_application(data_root=tmp_path)) as client:
        client.get('/api/tutorial')
        temporary = _input(client, 'tutorial', b'temporary research')
        archive = client.get(f'/api/packages/{temporary}/export.zip')
        assert archive.status_code == 200, archive.text
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            manifest = json.loads(zipped.read('package.json'))
            assert manifest['format'] == 'independent.request'
            assert zipped.read(manifest['files'][0]['member']) == b'temporary research'
        target = client.post('/api/projects', json={'name': 'Explicit adoption'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': temporary})
        assert adopted.status_code == 200, adopted.text
        client.delete(f'/api/draft-inputs/{temporary}')
        assert client.get(f"/api/packages/{adopted.json()['id']}/file", params={'key': 'request'}).content == b'temporary research'
