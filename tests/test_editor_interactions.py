"""Temporary editing through the public HTTP interaction and delivery entry."""
from fastapi.testclient import TestClient
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
        assert document == preview['data']['document']
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
    return token, response.json()['data']['document']


def test_position_edits_keep_conditions_and_source_mapping_and_never_replay_randomness(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Conditions'}).json()['id']
        token, first = preview(client, project, {'sequence': 'ACD'})
        ids = [row['id'] for row in first['positions']]
        client.delete(f'/api/interactions/{token}').raise_for_status()
        token, conditioned = preview(client, project, {'document': first, 'operation': {
            'kind': 'update', 'positions': [ids[1]], 'changes': {
                'prompt': '_', 'fixed': False, 'coordinates': {'CA': [1, 2, 3]}}}})
        token, random = preview(client, project, {'document': conditioned, 'operation': {
            'kind': 'random_insert', 'seed': 0, 'count': 2, 'start': 0, 'end': 3}})
        assert random['sequence'] == 'A_CD_'
        token, reordered = preview(client, project, {'document': random, 'operation': {
            'kind': 'reorder', 'positions': [row['id'] for row in reversed(random['positions'])]}})
        c = next(row for row in reordered['positions'] if row['id'] == ids[1])
        assert c['coordinates'] == {'CA': [1, 2, 3]} and c['prompt'] == '_' and c['fixed'] is False
        random_ids = [item['position'] for item in random['random_operations'][0]['actual']]
        token, deleted = preview(client, project, {'document': reordered, 'operation': {'kind': 'delete', 'positions': random_ids}})
        assert deleted['sequence'] == 'DCA'
        assert deleted['random_operations'] == random['random_operations']
        token, again = preview(client, project, {'document': deleted, 'operation': {
            'kind': 'random_insert', 'seed': 0, 'count': 1, 'start': 0, 'end': 0}})
        assert again['sequence'] == '_DCA'
        assert len(again['random_operations']) == 2
        client.delete(f'/api/interactions/{token}').raise_for_status()
        assert client.get(f'/api/projects/{project}/packages').json() == []


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
        assert actual == document


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
