"""Manual flow saving and delivered files have separate public lifecycles."""
from tests.run_helpers import wait_response
import sqlite3

import pytest
from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def test_incomplete_flow_and_layout_reopen_together_without_run_eligibility(tmp_path):
    flow = {
        'nodes': [{'id': 'draft', 'type': 'missing.operation', 'parameters': {'seed': 0}, 'inputs': {}}],
        'edges': [{'source': 'draft', 'source_port': 'output', 'target': 'unfinished', 'target_port': 'input'}],
    }
    layout = {'draft': {'x': 42, 'y': 73}, 'viewport': {'zoom': 0.8}}
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Unfinished research'}).json()['id']
        saved = client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': layout})
        assert saved.status_code == 200, saved.text
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        project = reopened.get(f'/api/projects/{project}').json()
        assert project['flow'] == flow
        assert project['layout'] == layout
        assert project['missing_modules'] == ['missing.operation']


@pytest.mark.parametrize('failure', ['write', 'commit'])
def test_failed_edit_save_preserves_both_previous_flow_and_layout(tmp_path, monkeypatch, failure):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Atomic editing'}).json()['id']
        original = {'flow': {'nodes': [], 'edges': [], 'note': 'saved'}, 'layout': {'viewport': {'zoom': 0.5}}}
        assert client.put(f'/api/projects/{project}', json=original).status_code == 200
        connect = sqlite3.connect

        class RefusedSave(sqlite3.Connection):
            def execute(self, statement, parameters=()):
                if failure == 'write' and statement.startswith('INSERT INTO records') and parameters[0] == 'project':
                    raise sqlite3.OperationalError('project write refused')
                return super().execute(statement, parameters)

            def commit(self):
                if failure == 'commit' and self.in_transaction:
                    raise sqlite3.OperationalError('project commit refused')
                return super().commit()

        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=RefusedSave))
            response = client.put(f'/api/projects/{project}', json={
                'flow': {'nodes': [], 'edges': [], 'note': 'new draft'}, 'layout': {'viewport': {'zoom': 2}},
            })
            assert response.status_code == 400
            assert f'project {failure} refused' in response.json()['detail']
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        saved = reopened.get(f'/api/projects/{project}').json()
        assert saved['flow'] == original['flow']
        assert saved['layout'] == original['layout']


def test_input_file_reception_does_not_save_flow_edits(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Separate actions'}).json()['id']
        original = {'flow': {'nodes': [], 'edges': []}, 'layout': {}}
        base = f'/api/projects/{project}/uploads'
        upload = client.post(base).json()['upload_id']
        base += f'/{upload}'
        assert client.put(base + '/files', params={'key': 'data'}, content=b'complete input').status_code == 200
        received = client.post(base + '/commit', json={'format': 'custom.data', 'entry': 'data', 'files': {'data': 'data'}})
        assert received.status_code == 200
        package = received.json()['id']
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        saved = reopened.get(f'/api/projects/{project}').json()
        assert saved['flow'] == original['flow']
        assert saved['layout'] == original['layout']
        assert reopened.get(f'/api/packages/{package}/file', params={'key': 'data'}).content == b'complete input'


def test_run_result_reception_preserves_the_explicitly_saved_flow_and_layout(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        assert client.post('/api/modules', json={'entry_point': 'tests.fixtures.host_module:module'}).status_code == 200
        project = client.post('/api/projects', json={'name': 'Saved calculation'}).json()['id']
        base = f'/api/projects/{project}/uploads'
        upload = client.post(base).json()['upload_id']
        base += f'/{upload}'
        client.put(base + '/files', params={'key': 'request'}, content=b'input')
        source = client.post(base + '/commit', json={
            'format': 'independent.request', 'entry': 'request', 'files': {'request': 'request'},
        }).json()['id']
        saved = {
            'flow': {'nodes': [{'id': 'encode', 'type': 'independent.encode', 'parameters': {'suffix': '!'}, 'inputs': {'source': [source]}}], 'edges': []},
            'layout': {'encode': {'x': 24, 'y': 63}},
        }
        assert client.put(f'/api/projects/{project}', json=saved).status_code == 200
        run = wait_response(client, client.post(f'/api/projects/{project}/runs', json={})).json()
        assert run['status'] == 'succeeded'
        output = run['nodes']['encode']['outputs']['result'][0]
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        project = reopened.get(f'/api/projects/{project}').json()
        assert project['flow'] == saved['flow']
        assert project['layout'] == saved['layout']
        assert reopened.get(f'/api/packages/{output}/file', params={'key': 'entry.bin'}).content == b'input!'
