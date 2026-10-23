"""Temporary editing through the public HTTP interaction and delivery entry."""
from fastapi.testclient import TestClient
from tests.fixtures.sequence_conditions import assert_manifest
from protein_workbench_public.bootstrap import create_application


def test_edit_preview_is_temporary_and_confirm_receives_exact_preview(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Editing'}).json()['id']
        response = client.post(f'/api/projects/{project}/interactions', json={
            'interaction': 'workbench.sequence_edit', 'inputs': {},
            'parameters': {'sequence': 'ACD', 'operation': {'kind': 'random_insert', 'seed': 0, 'count': 2, 'start': 0, 'end': 3}},
        })
        assert response.status_code == 200, response.text
        token = response.json()['id']
        preview = client.post(f'/api/interactions/{token}/execute').json()
        assert preview['data']['document']['sequence'] == 'A_CD_'
        assert client.get(f'/api/projects/{project}/packages').json() == []
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output': 'edited'}).json()
        document = client.get(f"/api/packages/{accepted['id']}/file", params={'key': accepted['entry']}).json()
        assert_manifest(preview['data']['document'], document)
        assert client.get(f'/api/projects/{project}/runs').json() == []
        assert client.get(f'/api/projects/{project}').json()['flow'] == {'nodes': [], 'edges': []}
        assert client.post(f'/api/interactions/{token}/execute').status_code == 400


def preview(client, project, parameters, inputs=None):
    response = client.post(f'/api/projects/{project}/interactions', json={
        'interaction': 'workbench.sequence_edit', 'inputs': inputs or {}, 'parameters': parameters})
    assert response.status_code == 200, response.text
    token = response.json()['id']
    response = client.post(f'/api/interactions/{token}/execute')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    if 'document_file' in data:
        response = client.get(f'/api/interactions/{token}/file', params={'output':'edited','key':data['document_file']})
        response.raise_for_status()
        return token, response.json()
    return token, data['document']


def test_position_edits_keep_conditions_and_source_mapping_and_never_replay_randomness(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Conditions'}).json()['id']
        token, first = preview(client, project, {'sequence': 'ACD'})
        ids = [row['id'] for row in first['positions']]
        client.delete(f'/api/interactions/{token}').raise_for_status()
        token, conditioned = preview(client, project, {'document': first, 'operation': {
            'kind': 'update', 'positions': [ids[1]], 'changes': {
                'prompt': '_', 'fixed': False, 'coordinates': {'CA': [1, 2, 3]}}}})
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output':'edited'}).json()
        token, random = preview(client, project, {'operation': {
            'kind': 'random_insert', 'seed': 0, 'count': 2, 'start': 0, 'end': 3}}, {'source':[accepted['id']]})
        assert random['sequence'] == 'A_CD_'
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output':'edited'}).json()
        token, reordered = preview(client, project, {'operation': {
            'kind': 'reorder', 'positions': [row['id'] for row in reversed(random['positions'])]}}, {'source':[accepted['id']]})
        c = next(row for row in reordered['positions'] if row['id'] == ids[1])
        assert c['coordinates'] == {'CA': [1, 2, 3]} and c['prompt'] == '_' and c['fixed'] is False
        random_ids = [item['position'] for item in random['random_operations'][0]['actual']]
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output':'edited'}).json()
        token, deleted = preview(client, project, {'operation': {'kind': 'delete', 'positions': random_ids}}, {'source':[accepted['id']]})
        assert deleted['sequence'] == 'DCA'
        assert deleted['random_operations'] == random['random_operations']
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output':'edited'}).json()
        token, again = preview(client, project, {'operation': {
            'kind': 'random_insert', 'seed': 0, 'count': 1, 'start': 0, 'end': 0}}, {'source':[accepted['id']]})
        assert again['sequence'] == '_DCA'
        assert len(again['random_operations']) == 2
        client.delete(f'/api/interactions/{token}').raise_for_status()
        assert len(client.get(f'/api/projects/{project}/packages').json()) == 4


def test_edited_input_survives_source_removal_and_runs_without_reapplying_random(tmp_path):
    from tests.test_sequence_io import upload
    from tests.test_structure_io import run
    import json
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Source'}).json()['id']
        target = client.post('/api/projects', json={'name': 'Edited'}).json()['id']
        source = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [{
            'id': 'original-object', 'sequence': 'AC', 'positions': [
                {'sequence_index': 1, 'chain': 'Z', 'author_number': 12, 'insertion_code': ''},
                {'sequence_index': 2, 'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}]}]}).encode()})
        token, document = preview(client, project, {'operation': {'kind': 'insert', 'index': 1, 'sequence': '_'}}, {'source': [source['id']]})
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output': 'edited'}).json()
        assert document['id'] != 'original-object'
        assert document['positions'][2]['source']['position']['insertion_code'] == 'A'
        assert 'source' not in document['positions'][1]
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': accepted['id']}).json()
        client.delete(f'/api/projects/{project}').raise_for_status()
        result = run(client, target, 'workbench.edit_sequence', {'source': [adopted['id']]}, {})
        assert result['status'] == 'succeeded', result
        package = result['outputs']['edited'][0]
        actual = client.get(f'/api/packages/{package}/file', params={'key': 'edited.json'}).json()
        assert_manifest(document, actual)


def test_independent_interaction_inputs_settings_missing_files_and_cancel_cleanup(tmp_path):
    from tests.test_sequence_io import upload
    from concurrent.futures import ThreadPoolExecutor
    from tests.fixtures import editor_interactions as fixture
    fixture.started.clear(); fixture.cancelled.clear(); fixture.finish.clear()
    with TestClient(create_application(data_root=tmp_path)) as client:
        client.post('/api/modules', json={'entry_point': 'tests.fixtures.editor_interactions:module'}).raise_for_status()
        client.put('/api/modules/external.editor/settings', json={'settings': {'suffix': '!'}}).raise_for_status()
        project = client.post('/api/projects', json={'name': 'Independent editor'}).json()['id']
        source = upload(client, project, 'external.data', {'data': b'explicit'}, entry='data')
        def begin(parameters, inputs=None):
            return client.post(f'/api/projects/{project}/interactions', json={
                'interaction': 'external.inspect', 'inputs': inputs if inputs is not None else {'data': [source['id']]}, 'parameters': parameters})
        assert 'select delivered packages' in begin({}, {}).json()['detail']
        token = begin({'missing': True}).json()['id']
        result = client.post(f'/api/interactions/{token}/execute').json()
        assert result['data'] == {'content': 'explicit', 'settings': {'suffix': '!'}}
        failed = client.post(f'/api/interactions/{token}/accept', json={'output': 'result'})
        assert failed.status_code == 400 and 'Could not receive declared file' in failed.json()['detail']
        assert [item['id'] for item in client.get(f'/api/projects/{project}/packages').json()] == [source['id']]
        assert list((tmp_path / 'work').iterdir()) == []
        token = begin({'wait': True}).json()['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            executing = pool.submit(client.post, f'/api/interactions/{token}/execute')
            assert fixture.started.wait(5)
            cancelling = pool.submit(client.delete, f'/api/interactions/{token}')
            assert fixture.cancelled.wait(5)
            fixture.finish.set()
            result = executing.result(timeout=5)
            assert result.status_code == 400 and result.json()['detail'] == 'Interaction failed: Interaction cancelled'
            assert cancelling.result(timeout=5).status_code == 200
        assert client.post(f'/api/interactions/{token}/accept', json={'output': 'result'}).status_code == 400
        assert list((tmp_path / 'work').iterdir()) == []
        assert client.get(f'/api/projects/{project}/runs').json() == []


def test_residue_and_fixed_variable_changes_update_the_actual_prompt_together(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Prompt consistency'}).json()['id']
        _, first = preview(client, project, {'sequence': 'AC'})
        selected = first['positions'][1]['id']
        _, changed = preview(client, project, {'document': first, 'operation': {
            'kind': 'update', 'positions': [selected], 'changes': {'residue': 'G'}}})
        assert changed['sequence'] == 'AG'
        assert changed['positions'][1]['prompt'] == 'G'
        _, variable = preview(client, project, {'document': changed, 'operation': {
            'kind': 'update', 'positions': [selected], 'changes': {'fixed': False}}})
        assert variable['positions'][1]['prompt'] == '_'
        _, fixed = preview(client, project, {'document': variable, 'operation': {
            'kind': 'update', 'positions': [selected], 'changes': {'prompt': 'W'}}})
        assert fixed['sequence'] == 'AW'
        assert fixed['positions'][1]['fixed'] is True


def test_preview_files_are_readable_until_cancel_or_accept(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Temporary files'}).json()['id']
        token, expected = preview(client, project, {'sequence': 'AC'})
        path = f'/api/interactions/{token}/file'
        response = client.get(path, params={'output': 'edited', 'key': 'edited.json'})
        assert response.status_code == 200, response.text
        assert_manifest(expected, response.json())
        assert client.get(path, params={'output': 'edited', 'key': '../edited.json'}).status_code == 400
        client.delete(f'/api/interactions/{token}').raise_for_status()
        assert client.get(path, params={'output': 'edited', 'key': 'edited.json'}).status_code == 400
        assert list((tmp_path / 'work').iterdir()) == []
        token, expected = preview(client, project, {'sequence': 'AC'})
        accepted = client.post(f'/api/interactions/{token}/accept', json={'output': 'edited'})
        accepted.raise_for_status()
        assert_manifest(expected, client.get(f"/api/packages/{accepted.json()['id']}/file", params={'key': 'edited.json'}).json())
        assert list((tmp_path / 'work').iterdir()) == []


def test_live_http_disconnect_releases_reader_before_cancel_cleans_files(tmp_path):
    import socket
    import time
    from threading import Thread
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    import httpx
    import uvicorn
    from tests.test_sequence_io import upload
    application = create_application(data_root=tmp_path)
    with TestClient(application) as client:
        client.post('/api/modules', json={'entry_point':'tests.fixtures.editor_interactions:module'}).raise_for_status()
        project = client.post('/api/projects',json={'name':'Streaming cancellation'}).json()['id']
        package = upload(client,project,'external.data',{'data':b'x'},entry='data')
    listener = socket.socket()
    listener.bind(('127.0.0.1',0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application,log_level='error'))
    thread = Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=5) as client:
            token = client.post(f'/api/projects/{project}/interactions',json={'interaction':'external.inspect',
                'inputs':{'data':[package['id']]},'parameters':{'repeat':64*1024*1024}}).json()['id']
            client.post(f'/api/interactions/{token}/execute').raise_for_status()
            stream = socket.create_connection(('127.0.0.1',port),timeout=5)
            stream.sendall(f'GET /api/interactions/{token}/file?output=result&key=data HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
            assert b'200 OK' in stream.recv(4096)
            with ThreadPoolExecutor(max_workers=1) as pool:
                cancelling = pool.submit(client.delete,f'/api/interactions/{token}')
                try:
                    cancelling.result(timeout=.1)
                    raise AssertionError('Cancellation released an active HTTP reader')
                except TimeoutError:
                    pass
                finally:
                    stream.close()
                cancelling.result(timeout=5).raise_for_status()
            assert client.get(f'/api/interactions/{token}/file',params={'output':'result','key':'data'}).status_code == 400
            assert list((tmp_path/'work').iterdir()) == []
    finally:
        server.should_exit=True
        thread.join(timeout=5)
        listener.close()
