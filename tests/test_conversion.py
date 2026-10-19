"""Explicit format conversion through the production HTTP/application boundary."""
import json

import pytest
from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application
from tests.test_comparison import inputs, pdb


def save_run(client, project, nodes, edges=()):
    response = client.put(f'/api/projects/{project}', json={'flow': {'nodes': nodes, 'edges': list(edges)}, 'layout': {}})
    assert response.status_code == 200, response.text
    return client.post(f'/api/projects/{project}/runs')


def test_only_explicit_converter_connects_prediction_to_structure_consumer(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Explicit conversion'}).json()['id']
        subject, reference, _ = inputs(client, project)
        rejected = save_run(client, project, [{'id': 'compare', 'type': 'workbench.compare_structure', 'inputs': {'subject': [subject['id']], 'reference': [reference['id']]}}])
        assert rejected.status_code == 400
        assert 'format is not accepted' in rejected.text.lower(), rejected.text
        result = save_run(client, project, [
            {'id': 'convert', 'type': 'workbench.prediction_to_structure', 'inputs': {'prediction': [subject['id']]}},
            {'id': 'compare', 'type': 'workbench.compare_structure', 'inputs': {'reference': [reference['id']]}},
            {'id': 'direct', 'type': 'workbench.compare', 'inputs': {'subject': [subject['id']], 'reference': [reference['id']]}},
        ], [{'source': 'convert', 'source_port': 'structure', 'target': 'compare', 'target_port': 'subject'}])
        assert result.status_code == 200, result.text
        run = result.json()
        assert run['status'] == 'succeeded', run
        converted_id = run['nodes']['convert']['outputs']['structure'][0]
        converted = client.get(f'/api/packages/{converted_id}').json()
        assert converted['format'] == 'workbench.structure'
        manifest = client.get(f'/api/packages/{converted_id}/file', params={'key': converted['entry']}).json()
        assert manifest['structure']['id'] == 'predicted-object'
        assert manifest['structure']['sequence'] == 'AAAAA'
        assert 'confidence' not in manifest
        assert 'confidence' not in manifest['structure']
        assert manifest['generation'] == {'tool': {'id': 'other.producer', 'parameters': {'seed': 0}}}
        assert client.get(f'/api/packages/{converted_id}/file', params={'key': manifest['structure']['file']}).content == pdb()
        converted_comparison = run['nodes']['compare']['outputs']['comparison'][0]
        direct_comparison = run['nodes']['direct']['outputs']['comparison'][0]
        read = lambda identifier: client.get(f'/api/packages/{identifier}/file', params={'key': 'manifest.json'}).json()
        final = read(converted_comparison)
        assert final['metrics'] == read(direct_comparison)['metrics']
        assert final['metrics']['tm_subject']['value'] == pytest.approx(1)
        assert final['subject']['id'] == 'predicted-object'
        assert final['alignment']['subject_positions'][1] == {'chain': 'X', 'author_number': 12, 'insertion_code': 'A'}
        assert client.get(f"/api/packages/{subject['id']}/file", params={'key': 'subject.pdb'}).content == pdb()
    with TestClient(create_application(data_root=tmp_path)) as client:
        assert client.get(f'/api/packages/{converted_comparison}/file', params={'key': 'overlay.json'}).status_code == 200


def test_declared_prediction_edge_into_structure_only_consumer_is_rejected(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Incompatible edge'}).json()['id']
        catalog = client.get('/api/catalog').json()
        predictor = next(tool['id'] for tool in catalog['tools'] if tool['slot'] == 'workbench.predict.structure')
        response = save_run(client, project, [
            {'id': 'predict', 'type': 'workbench.predict', 'tools': {'predictor': predictor}},
            {'id': 'compare', 'type': 'workbench.compare_structure'},
        ], [{'source': 'predict', 'source_port': 'structure', 'target': 'compare', 'target_port': 'subject'}])
        assert response.status_code == 400
        assert 'select an explicit conversion node' in response.text
        saved = client.get(f'/api/projects/{project}').json()
        assert len(saved['flow']['nodes']) == 2


@pytest.mark.parametrize(('alter', 'diagnostic'), [
    ('sequence', 'Structure sequence is required'),
    ('file', 'Structure file is required'),
    ('empty', 'structure file is empty'),
])
def test_required_conversion_content_fails_without_mutating_source(tmp_path, alter, diagnostic):
    from tests.test_comparison import upload
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Failed conversion'}).json()['id']
        obj = {'id': 'unchanged-object', 'sequence': 'AAAAA', 'structure': {'file': 'subject.pdb', 'format': 'pdb'}}
        if alter == 'sequence':
            obj.pop('sequence')
        elif alter == 'file':
            obj['structure']['file'] = ''
        manifest = {'objects': [obj], 'tool': {'id': 'source.tool', 'parameters': {}}}
        content = b'' if alter == 'empty' else pdb()
        source = upload(client, project, 'workbench.prediction', manifest, content, 'subject.pdb')
        original = client.get(f"/api/packages/{source['id']}/file", params={'key': 'manifest.json'}).content
        result = save_run(client, project, [{'id': 'convert', 'type': 'workbench.prediction_to_structure', 'inputs': {'prediction': [source['id']]}}]).json()
        assert result['status'] == 'failed', result
        assert diagnostic in ' '.join(result['nodes']['convert']['diagnostics'])
        assert not result['nodes']['convert']['outputs']
        assert client.get(f"/api/packages/{source['id']}/file", params={'key': 'manifest.json'}).content == original
        assert client.get(f"/api/packages/{source['id']}/file", params={'key': 'subject.pdb'}).content == content


def test_converter_and_structure_consumer_work_without_producer_import_and_keep_original_confidence(tmp_path, monkeypatch):
    import builtins
    import gemmi
    from core.host import Workbench
    from protein_workbench_public.http.app import create_http_app
    from tests.test_comparison import upload

    original_import = builtins.__import__
    def independent_import(name, *args, **kwargs):
        if name.startswith(('modules.folding', 'datatypes', 'core.catalog', 'core.execution')):
            raise ImportError('Prediction producer and legacy scientific code unavailable')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', independent_import)
    host = Workbench(tmp_path)
    host.install('modules.structure_conversion:module')
    with TestClient(create_http_app(host)) as client:
        project = client.post('/api/projects', json={'name': 'Independent conversion'}).json()['id']
        content = gemmi.read_pdb_string(pdb()).make_mmcif_document().as_string().encode()
        manifest = {'objects': [{'id': 'original-object', 'sequence': 'AAAAA', 'label': 'Original prediction', 'structure': {'file': 'original.cif', 'format': 'mmcif'}, 'confidence': {'ptm': 0.8}}], 'tool': {'id': 'removed.producer', 'parameters': {'seed': 0}}}
        source = upload(client, project, 'workbench.prediction', manifest, content, 'original.cif')
        original = client.get(f"/api/packages/{source['id']}/file", params={'key': 'manifest.json'}).content
        reference = upload(client, project, 'workbench.reference', {'objects': [{'id': 'unrelated', 'structure': {'file': 'reference.pdb', 'format': 'pdb'}}]}, pdb(), 'reference.pdb')
        result = save_run(client, project, [
            {'id': 'convert', 'type': 'workbench.prediction_to_structure', 'inputs': {'prediction': [source['id']]}},
            {'id': 'compare', 'type': 'workbench.compare_structure', 'inputs': {'reference': [reference['id']]}},
        ], [{'source': 'convert', 'source_port': 'structure', 'target': 'compare', 'target_port': 'subject'}]).json()
        assert result['status'] == 'succeeded', result
        converted_id = result['nodes']['convert']['outputs']['structure'][0]
        target = client.get(f'/api/packages/{converted_id}/file', params={'key': 'manifest.json'}).json()
        assert target['structure'] == {'id': 'original-object', 'sequence': 'AAAAA', 'label': 'Original prediction', 'file': 'structure.cif', 'format': 'mmcif'}
        assert 'confidence' not in target
        assert 'confidence' not in target['structure']
        assert client.get(f'/api/packages/{converted_id}/file', params={'key': 'structure.cif'}).content == content
        assert client.get(f"/api/packages/{source['id']}/file", params={'key': 'manifest.json'}).content == original
