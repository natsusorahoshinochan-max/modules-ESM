from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def test_empty_host_creates_saves_and_reopens_project(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        for module in client.get('/api/modules').json():
            client.put(f"/api/modules/{module['id']}/enabled", json={'enabled': False})
        assert client.get('/api/catalog').json()['nodes'] == []
        project = client.post('/api/projects', json={'name': 'Empty research'}).json()
        response = client.put(f"/api/projects/{project['id']}", json={
            'flow': {'nodes': [], 'edges': []}, 'layout': {'zoom': 0.75},
        })
        assert response.status_code == 200
        assert client.get(f"/api/projects/{project['id']}").json()['layout'] == {'zoom': 0.75}


def upload(client, project, content, *, format='example.note', key='text'):
    base = f"/api/projects/{project}/uploads"
    token = client.post(base).json()['upload_id']
    path = f'{base}/{token}'
    assert client.put(path + '/files', params={'key': key}, content=content).status_code == 200
    response = client.post(path + '/commit', json={'format': format, 'entry': key, 'files': {key: key}})
    assert response.status_code == 200, response.text
    return response.json()


def test_streamed_binary_entry_and_logical_key_survive_without_viewer(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Binary data'}).json()['id']
        content = b'\x00\xff\x01\xfe' * (1024 * 512)
        package = upload(client, project, iter([content[:4096], content[4096:]]), format='external.binary', key='logical/../binary ? #')
        assert package['entry'] == 'logical/../binary ? #'
        response = client.get(f"/api/packages/{package['id']}/file", params={'key': package['entry']})
        assert response.status_code == 200
        assert response.content == content
        assert client.get(f"/api/packages/{package['id']}/file", params={'key': 'not-declared'}).status_code == 400


def test_incomplete_stream_cannot_be_committed_or_overwritten(tmp_path):
    import asyncio
    import httpx

    async def exercise():
        transport = httpx.ASGITransport(app=create_application(data_root=tmp_path))
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            project = (await client.post('/api/projects', json={'name': 'Streaming input'})).json()['id']
            base = f'/api/projects/{project}/uploads'
            token = (await client.post(base)).json()['upload_id']
            base += '/' + token
            started, finish = asyncio.Event(), asyncio.Event()

            async def chunks():
                yield b'first'
                started.set()
                await finish.wait()
                yield b'second'

            uploading = asyncio.create_task(client.put(base + '/files', params={'key': 'text'}, content=chunks()))
            await started.wait()
            try:
                duplicate = await client.put(base + '/files', params={'key': 'text'}, content=b'wrong')
                premature = await client.post(base + '/commit', json={'format': 'external.binary', 'entry': 'text', 'files': {'text': 'text'}})
            finally:
                finish.set()
                await uploading
            assert duplicate.status_code == 400
            assert premature.status_code == 400
            package = (await client.post(base + '/commit', json={'format': 'external.binary', 'entry': 'text', 'files': {'text': 'text'}})).json()
            response = await client.get(f"/api/packages/{package['id']}/file", params={'key': 'text'})
            assert response.content == b'firstsecond'
    asyncio.run(exercise())


def test_missing_entry_and_unreadable_stored_file_report_failure(tmp_path, monkeypatch):
    from pathlib import Path
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Read failures'}).json()['id']
        token = client.post(f'/api/projects/{project}/uploads').json()['upload_id']
        base = f'/api/projects/{project}/uploads/{token}'
        client.put(base + '/files', params={'key': 'text'}, content=b'complete')
        failed = client.post(base + '/commit', json={'format': 'example.note', 'entry': 'missing', 'files': {'text': 'text'}})
        assert failed.status_code == 400
        assert 'entry' in failed.json()['detail']
        assert client.get(f'/api/projects/{project}/packages').json() == []
        package = upload(client, project, b'complete')
        original_open = Path.open

        def deny_package_read(path, *args, **kwargs):
            if path.is_relative_to(tmp_path / 'packages') and args and args[0] == 'rb':
                raise PermissionError('storage temporarily unreadable')
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, 'open', deny_package_read)
        response = client.get(f"/api/packages/{package['id']}/file", params={'key': 'text'})
        assert response.status_code == 400
        assert 'storage temporarily unreadable' in response.json()['detail']


def test_invalid_unicode_project_name_cannot_poison_project_list(tmp_path):
    with TestClient(create_application(data_root=tmp_path), raise_server_exceptions=False) as client:
        rejected = client.post('/api/projects', content=b'{"name":"\\ud800"}', headers={'Content-Type': 'application/json'})
        assert rejected.status_code == 400
        assert 'UTF-8' in rejected.json()['detail']
        assert client.get('/api/projects').json() == []
        valid = client.post('/api/projects', json={'name': 'Research 🧪'}).json()
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        assert [project['name'] for project in reopened.get('/api/projects').json()] == ['Research 🧪']
        assert reopened.get(f"/api/projects/{valid['id']}").status_code == 200


def test_invalid_nested_flow_and_settings_leave_previous_records_readable(tmp_path):
    import json
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Safe project'}).json()['id']
        module = client.post('/api/modules', json={'entry_point': 'tests.fixtures.host_module:module'}).json()['id']
        for path, data in [
            (f'/api/projects/{project}', {'flow': {'nodes': [], 'edges': [], 'draft': [{'title': '\ud800'}]}, 'layout': {}}),
            (f'/api/projects/{project}', {'flow': {'nodes': [], 'edges': []}, 'layout': {'\udfff': {'x': 1}}}),
            (f'/api/modules/{module}/settings', {'settings': {'nested': [{'label': '\udfff'}]}}),
        ]:
            response = client.put(path, content=json.dumps(data).encode('ascii'), headers={'Content-Type': 'application/json'})
            assert response.status_code == 400
            assert 'UTF-8' in response.json()['detail']
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        assert reopened.get(f'/api/projects/{project}').json()['flow'] == {'nodes': [], 'edges': []}
        assert reopened.get(f'/api/projects/{project}').json()['layout'] == {}
        assert reopened.get('/api/modules').json()[0]['settings'] == {}
        assert reopened.get('/api/catalog').status_code == 200
