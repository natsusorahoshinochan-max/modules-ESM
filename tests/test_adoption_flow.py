from tests.run_helpers import wait_response
"""Public HTTP acceptance shared with the isolated installed-wheel check.

Byte equality below is a test assertion, never a production save prerequisite.
"""
import io
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(client, package_id):
    metadata = checked(client.get(f'/api/packages/{package_id}'))
    files = {}
    for key in metadata['files']:
        response = client.get(f'/api/packages/{package_id}/file', params={'key': key})
        assert response.status_code == 200, response.text
        files[key] = response.content
    return metadata, files


def upload_files(client, project, metadata, files):
    base = f'/api/projects/{project}/uploads'
    base += '/' + checked(client.post(base))['upload_id']
    for key, content in files.items():
        checked(client.put(base + '/files', params={'key': key}, content=content))
    return checked(client.post(base + '/commit', json={
        'format': metadata['format'], 'entry': metadata['entry'],
        'files': {key: key for key in files},
    }))


def compute(client, project, subject, reference):
    flow = {'nodes': [
        {'id': 'direct', 'type': 'workbench.compare', 'inputs': {'subject': [subject], 'reference': [reference]}},
        {'id': 'convert', 'type': 'workbench.prediction_to_structure', 'inputs': {'prediction': [subject]}},
        {'id': 'converted', 'type': 'workbench.compare_structure', 'inputs': {'reference': [reference]}},
    ], 'edges': [{'source': 'convert', 'source_port': 'structure', 'target': 'converted', 'target_port': 'subject'}]}
    layout = {'direct': {'x': 51, 'y': 23}}
    checked(client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': layout}))
    result = checked(wait_response(client, client.post(f'/api/projects/{project}/runs')))
    assert result['status'] == 'succeeded', result
    outputs = {name: result['nodes'][name]['outputs'][port][0] for name, port in (
        ('direct', 'comparison'), ('convert', 'structure'), ('converted', 'comparison'))}
    direct = json.loads(snapshot(client, outputs['direct'])[1]['manifest.json'])
    converted = json.loads(snapshot(client, outputs['converted'])[1]['manifest.json'])
    assert direct['metrics'] == converted['metrics']
    assert direct['subject']['id'] == converted['subject']['id']
    assert direct['reference']['id'] == converted['reference']['id']
    return outputs, direct['metrics'], result['id']


def prepare(root, predictions, reference):
    """Run both paths, adopt all packages, delete source via API, unregister producers."""
    with TestClient(create_application(data_root=root)) as client:
        source = checked(client.post('/api/projects', json={'name': 'Source predictions'}))['id']
        target = checked(client.post('/api/projects', json={'name': 'Independent adopted data'}))['id']
        ref = upload_files(client, source, *reference)['id']
        cases = []
        for metadata, files in predictions:
            subject = upload_files(client, source, metadata, files)['id']
            outputs, metrics, run_id = compute(client, source, subject, ref)
            identifiers = {'prediction': subject, 'reference': ref, **outputs}
            adopted = {}
            for name, package_id in identifiers.items():
                before, expected = snapshot(client, package_id)
                copied = checked(client.post(f'/api/projects/{target}/adoptions', json={'package_id': package_id}))
                assert copied['id'] != package_id
                assert copied['project_id'] == target
                after, actual = snapshot(client, copied['id'])
                assert (after['format'], after['entry'], after['files']) == (before['format'], before['entry'], before['files'])
                assert actual == expected
                adopted[name] = copied['id']
            cases.append({'adopted': adopted, 'metrics': metrics, 'source_run_id': run_id,
                          'tool': json.loads(files[metadata['entry']])['tool']})
        checked(client.delete(f'/api/projects/{source}'))
        assert client.get(f'/api/projects/{source}').status_code == 400
        for module in ('workbench.prediction', 'workbench.simplefold'):
            checked(client.delete(f'/api/modules/{module}'))
        # Saving a flow referencing explicitly adopted inputs works after deletion.
        for case in cases:
            adopted = case['adopted']
            _, metrics, _ = compute(client, target, adopted['prediction'], adopted['reference'])
            assert metrics == case['metrics']
    return {'target': target, 'deleted_source': source, 'checks': cases}


def reopen(root, state):
    """Read, export, re-adopt and compute after producer Python code is unavailable."""
    with TestClient(create_application(data_root=root)) as client:
        target = state['target']
        project = checked(client.get(f'/api/projects/{target}'))
        assert project['layout'] == {'direct': {'x': 51, 'y': 23}}
        other = checked(client.post('/api/projects', json={'name': 'Readopted independent data'}))['id']
        for case in state['checks']:
            readopted = {}
            for name, package_id in case['adopted'].items():
                metadata, files = snapshot(client, package_id)
                exported = client.get(f'/api/packages/{package_id}/export.zip')
                assert exported.status_code == 200, exported.text
                with ZipFile(io.BytesIO(exported.content)) as archive:
                    descriptor = json.loads(archive.read('package.json'))
                    assert descriptor['format'] == metadata['format']
                    assert descriptor['entry'] == metadata['entry']
                    assert [item['key'] for item in descriptor['files']] == metadata['files']
                    assert {item['key']: archive.read(item['member']) for item in descriptor['files']} == files
                adopted = checked(client.post(f'/api/projects/{other}/adoptions', json={'package_id': package_id}))
                assert adopted['id'] != package_id
                assert snapshot(client, adopted['id'])[1] == files
                readopted[name] = adopted['id']
            _, metrics, run_id = compute(client, other, readopted['prediction'], readopted['reference'])
            assert metrics == case['metrics']
            converted_manifest = json.loads(snapshot(client, readopted['convert'])[1]['manifest.json'])
            assert 'confidence' not in converted_manifest
            assert 'confidence' not in converted_manifest['structure']
            case['readopted'] = readopted
            case['independent_run_id'] = run_id
        checked(client.delete(f'/api/projects/{target}'))
        # Second adoption survives deletion of its own source too.
        for case in state['checks']:
            for package_id in case['readopted'].values():
                snapshot(client, package_id)
        state['readopted_project'] = other
    return state


def test_full_prediction_conversion_comparison_adoption_flow(tmp_path):
    from tests.test_comparison import inputs
    with TestClient(create_application(data_root=tmp_path / 'fixtures')) as client:
        project = checked(client.post('/api/projects', json={'name': 'Fixture'}))['id']
        subject, reference, _ = inputs(client, project)
        prediction = snapshot(client, subject['id'])
        reference = snapshot(client, reference['id'])
    state = prepare(tmp_path / 'flow', [prediction], reference)
    reopen(tmp_path / 'flow', state)
