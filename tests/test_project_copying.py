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


def test_upload_commit_after_another_instance_deletes_project_releases_its_workdir(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as first:
        project = first.post('/api/projects', json={'name': 'Concurrent deletion'}).json()['id']
        base = f'/api/projects/{project}/uploads'
        token = first.post(base).json()['upload_id']
        base += '/' + token
        assert first.put(base + '/files', params={'key': 'data'}, content=b'real uploaded research input').status_code == 200
        staged = tuple((tmp_path / 'work').glob('execution-*'))
        assert len(staged) == 1
        with TestClient(create_application(data_root=tmp_path)) as second:
            assert second.delete(f'/api/projects/{project}').status_code == 200
        response = first.post(base + '/commit', json={'format': 'custom.data', 'entry': 'data', 'files': {'data': 'data'}})
        assert response.status_code == 400
        assert 'Unknown project' in response.json()['detail']
        assert not staged[0].exists()
        assert first.delete(base).status_code == 400
    assert not tuple((tmp_path / 'work').glob('execution-*'))


@pytest.mark.parametrize('project_kind', ['user', 'tutorial'])
def test_upload_receiver_failure_releases_workdir_without_persisting_input(tmp_path, project_kind):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.get('/api/tutorial').json()['id'] if project_kind == 'tutorial' else client.post('/api/projects', json={'name': 'Failed reception'}).json()['id']
        original = client.get(f'/api/projects/{project}/packages').json()
        base = f'/api/projects/{project}/uploads'
        token = client.post(base).json()['upload_id']
        base += '/' + token
        assert client.put(base + '/files', params={'key': 'data'}, content=b'failed received bytes').status_code == 200
        response = client.post(base + '/commit', json={'format': 'custom.data', 'entry': 'missing', 'files': {'data': 'data'}})
        assert response.status_code == 400
        assert 'entry' in response.json()['detail']
        assert not tuple((tmp_path / 'work').glob('execution-*'))
        assert client.get(f'/api/projects/{project}/packages').json() == original


def test_first_save_keeps_explicit_unbound_teaching_imports_and_deduplicates_bindings(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.get('/api/tutorial')
        bound = _input(client, 'tutorial', b'bound input')
        unbound = _input(client, 'tutorial', b'unbound research')
        flow = {'nodes': [{'id': 'later', 'type': 'missing.consumer', 'inputs': {'source': [bound]}}], 'edges': []}
        response = client.post('/api/projects/tutorial/copies', json={
            'name': 'Research imports', 'flow': flow, 'layout': {},
            'input_packages': [bound, unbound, unbound],
        })
        assert response.status_code == 200, response.text
        copied = response.json()
        packages = client.get(f"/api/projects/{copied['id']}/packages").json()
        assert len(packages) == 2
        assert copied['flow']['nodes'][0]['inputs']['source'][0] in {item['id'] for item in packages}
        assert all(item['id'] not in (bound, unbound) for item in packages)
        for key in (bound, unbound):
            assert client.delete(f'/api/draft-inputs/{key}').status_code == 200
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        saved = reopened.get(f"/api/projects/{copied['id']}/packages").json()
        assert sorted(reopened.get(f"/api/packages/{item['id']}/file", params={'key': 'request'}).content for item in saved) == [b'bound input', b'unbound research']
        assert reopened.get(f"/api/projects/{copied['id']}/runs").json() == []


def test_first_save_unbound_only_import_survives_transaction_failure_then_retry(tmp_path, monkeypatch):
    with TestClient(create_application(data_root=tmp_path)) as client:
        original = client.get('/api/tutorial').json()
        temporary = _input(client, 'tutorial', b'independent research input')
        before = sorted(path.name for path in (tmp_path / 'packages').iterdir())
        body = {'name': 'Imported only', 'flow': {'nodes': [], 'edges': []}, 'layout': {}, 'input_packages': [temporary]}
        connect = sqlite3.connect

        class RefuseCommit(sqlite3.Connection):
            def commit(self):
                if self.in_transaction:
                    raise sqlite3.OperationalError('import copy commit refused')
                return super().commit()

        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=RefuseCommit))
            failed = client.post('/api/projects/tutorial/copies', json=body)
        assert failed.status_code == 400
        assert client.get('/api/projects').json() == []
        assert client.get('/api/tutorial').json() == original
        assert client.get(f'/api/packages/{temporary}/file', params={'key': 'request'}).content == b'independent research input'
        assert sorted(path.name for path in (tmp_path / 'packages').iterdir()) == before
        copied = client.post('/api/projects/tutorial/copies', json=body)
        assert copied.status_code == 200, copied.text
        assert copied.json()['flow'] == {'nodes': [], 'edges': []}
        assert len(client.get(f"/api/projects/{copied.json()['id']}/packages").json()) == 1


def test_explicit_copy_inputs_reject_other_project_ownership(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.get('/api/tutorial')
        other = client.post('/api/projects', json={'name': 'Other research'}).json()['id']
        foreign = _input(client, other, b'foreign research')
        before = sorted(path.name for path in (tmp_path / 'packages').iterdir())
        response = client.post('/api/projects/tutorial/copies', json={
            'name': 'Invalid input ownership', 'flow': {'nodes': [], 'edges': []},
            'layout': {}, 'input_packages': [foreign],
        })
        assert response.status_code == 400, response.text
        assert 'source project' in response.json()['detail']
        assert [project['id'] for project in client.get('/api/projects').json()] == [other]
        assert sorted(path.name for path in (tmp_path / 'packages').iterdir()) == before
        assert client.get(f'/api/packages/{foreign}/file', params={'key': 'request'}).content == b'foreign research'


def test_copy_keeps_unbound_imports_and_adoptions_but_excludes_unused_run_outputs(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.post('/api/modules', json={'entry_point': 'tests.fixtures.host_module:module'})
        origin = client.post('/api/projects', json={'name': 'Origin'}).json()['id']
        original = _input(client, origin, b'adopted research')
        source = client.post('/api/projects', json={'name': 'Imported research'}).json()['id']
        imported = _input(client, source, b'imported research')
        client.post(f'/api/projects/{source}/adoptions', json={'package_id': original}).raise_for_status()
        flow = {'nodes': [{'id': 'encode', 'type': 'independent.encode', 'inputs': {'source': [imported]}, 'parameters': {'suffix': '!'}}], 'edges': []}
        client.put(f'/api/projects/{source}', json={'flow': flow, 'layout': {}}).raise_for_status()
        run = wait_response(client, client.post(f'/api/projects/{source}/runs', json={})).json()
        assert run['status'] == 'succeeded'
        assert len(client.get(f'/api/projects/{source}/packages').json()) == 3
        # The user removes the node, keeping imports and adoptions in the project.
        client.put(f'/api/projects/{source}', json={'flow': {'nodes': [], 'edges': []}, 'layout': {}}).raise_for_status()
        copied = client.post(f'/api/projects/{source}/copies', json={'name': 'Copy all inputs'})
        copied.raise_for_status()
        copy_id = copied.json()['id']
        assert len(client.get(f'/api/projects/{copy_id}/packages').json()) == 2
        for project in (origin, source):
            client.delete(f'/api/projects/{project}').raise_for_status()
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        again = reopened.post(f'/api/projects/{copy_id}/copies', json={'name': 'Copy saved inputs again'})
        again.raise_for_status()
        copy_id = again.json()['id']
        packages = reopened.get(f'/api/projects/{copy_id}/packages').json()
        assert sorted(reopened.get(f"/api/packages/{item['id']}/file", params={'key': 'request'}).content for item in packages) == [b'adopted research', b'imported research']
        assert reopened.get(f'/api/projects/{copy_id}/runs').json() == []
