"""Public collection boundaries, real files and independently consumed results."""
import json
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application
from tests.run_helpers import wait_response
from tests.test_sequence_io import upload
from tests.test_filtering import source
from tests.test_filtering import interaction


def execute(client, project, nodes, edges=()):
    client.put(f'/api/projects/{project}', json={'flow': {'nodes': nodes, 'edges': list(edges)}, 'layout': {}}).raise_for_status()
    return wait_response(client, client.post(f'/api/projects/{project}/runs')).json()


def entry(client, package):
    return client.get(f'/api/packages/{package}/file', params={'key': 'manifest.json'}).json()


def test_split_merge_preserves_order_and_independent_sequence_consumption(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Collections'}).json()['id']
        sequences = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [
            {'id': 'a', 'label': 'A', 'sequence': 'ACDE'},
            {'id': 'b', 'label': 'B', 'sequence': 'FGHI'},
        ]}).encode()})
        result = execute(client, project, [
            {'id': 'merge', 'type': 'workbench.collection.merge', 'inputs': {'packages': [sequences['id']]}, 'parameters': {}},
            {'id': 'split', 'type': 'workbench.collection.split', 'inputs': {}, 'parameters': {}},
            {'id': 'join', 'type': 'workbench.collection.merge', 'inputs': {}, 'parameters': {}},
            {'id': 'extract', 'type': 'workbench.collection.extract_sequences', 'inputs': {}, 'parameters': {}},
        ], [
            {'source': 'merge', 'source_port': 'collection', 'target': 'split', 'target_port': 'collection'},
            {'source': 'split', 'source_port': 'items', 'target': 'join', 'target_port': 'packages'},
            {'source': 'join', 'source_port': 'collection', 'target': 'extract', 'target_port': 'collection'},
        ])
        assert result['status'] == 'succeeded', result
        split = result['nodes']['split']['outputs']['items']
        assert len(split) == 2
        assert [[item['object']['id'] for item in entry(client, p)['items']] for p in split] == [['a'], ['b']]
        output = result['nodes']['extract']['outputs']['sequences'][0]
        target = client.post('/api/projects', json={'name': 'Independent consumer'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': output}).json()['id']
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.delete('/api/modules/workbench.collection').raise_for_status()
        # Read only its published file shape after source deletion and module uninstall.
        objects = entry(client, adopted)['objects']
        assert [(o['id'], o['sequence']) for o in objects] == [('a', 'ACDE'), ('b', 'FGHI')]


def test_selected_objects_extract_and_empty_split_use_declared_packages(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Selected collection'}).json()['id']
        candidates = source(client, project, ['a', 'b'], [.8, .3])
        first = execute(client, project, [
            {'id': 'merge', 'type': 'workbench.collection.merge', 'inputs': {'packages': [candidates['id']]}, 'parameters': {}},
            {'id': 'take', 'type': 'workbench.collection.select', 'inputs': {}, 'parameters': {'items': [1]}},
            {'id': 'extract', 'type': 'workbench.collection.extract_structures', 'inputs': {}, 'parameters': {}},
        ], [
            {'source': 'merge', 'source_port': 'collection', 'target': 'take', 'target_port': 'collection'},
            {'source': 'take', 'source_port': 'collection', 'target': 'extract', 'target_port': 'collection'},
        ])
        assert first['status'] == 'succeeded', first
        objects = entry(client, first['nodes']['extract']['outputs']['structures'][0])['objects']
        assert [obj['id'] for obj in objects] == ['b']
        empty = execute(client, project, [
            {'id': 'merge', 'type': 'workbench.collection.merge', 'inputs': {'packages': []}, 'parameters': {}},
            {'id': 'split', 'type': 'workbench.collection.split', 'inputs': {}, 'parameters': {}},
        ], [{'source': 'merge', 'source_port': 'collection', 'target': 'split', 'target_port': 'collection'}])
        assert empty['status'] == 'succeeded', empty
        assert empty['nodes']['split']['outputs']['items'] == []


def recorded(client, project):
    root = Path(__file__).with_name('fixtures')/'real_comparisons'
    return [upload(client, project, 'workbench.comparison', {
        file.name: file.read_bytes() for file in folder.iterdir() if file.is_file()
    }) for folder in sorted(root.iterdir()) if folder.is_dir()]


def test_real_recorded_scores_conditions_sort_limit_and_split_rejoin(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Recorded scientific scores'}).json()['id']
        packages = recorded(client, project)
        inputs = {'candidates': [p['id'] for p in packages], 'evaluations': [p['id'] for p in packages]}
        first = entry(client, packages[0]['id'])
        evaluation = {'metric': 'tm_reference', 'method': first['method'], 'reference': first['reference'], 'region': first['region']}
        rmsd = dict(evaluation, metric='rmsd')
        # Three pass TM >= .6; sorting raw TM values and limit 2 keeps candidates 1 and 4.
        params = {'conditions': [{'evaluation': evaluation, 'operator': 'ge', 'value': .6}],
                  'sort': {'evaluation': evaluation, 'direction': 'descending'}, 'limit': 2}
        assert interaction(client, project, 'workbench.filter', inputs, params).json()['data']['selected'] == [
            {'input': 0, 'item': 0}, {'input': 3, 'item': 0}]
        # Add an independent actual RMSD condition: candidate 4 fails, candidate 3 survives.
        params['conditions'].append({'evaluation': rmsd, 'operator': 'lt', 'value': 2.32})
        expected = [{'input': 0, 'item': 0}, {'input': 2, 'item': 0}]
        assert interaction(client, project, 'workbench.filter', inputs, params).json()['data']['selected'] == expected
        result = execute(client, project, [
            {'id': 'filter', 'type': 'workbench.filter', 'inputs': inputs, 'parameters': params},
            {'id': 'split', 'type': 'workbench.collection.split', 'inputs': {}, 'parameters': {}},
            {'id': 'merge', 'type': 'workbench.collection.merge', 'inputs': {}, 'parameters': {}},
        ], [
            {'source': 'filter', 'source_port': 'collection', 'target': 'split', 'target_port': 'collection'},
            {'source': 'split', 'source_port': 'items', 'target': 'merge', 'target_port': 'packages'},
        ])
        assert result['status'] == 'succeeded', result
        output = result['nodes']['merge']['outputs']['collection'][0]
        saved = entry(client, output)
        assert [i['object']['id'] for i in saved['items']] == ['feedback-candidate-1', 'feedback-round2-candidate-1']
        assert len(saved['sources']) == 4  # Explicit source identities survive split/rejoin.
        # Same saved evaluation contexts are still unambiguous after splitting and merging.
        repeated = interaction(client, project, 'workbench.filter', {'candidates': [output], 'evaluations': [output]}, params)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()['data']['selected'] == [{'input': 0, 'item': 0}, {'input': 0, 'item': 1}]


def test_real_batch_comparison_then_adoption_and_source_deletion(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Real scientific batch'}).json()['id']
        packages = recorded(client, project)
        reference = entry(client, packages[0]['id'])['reference']
        reference_bytes = client.get(f"/api/packages/{packages[0]['id']}/file", params={'key': 'reference.pdb'}).content
        ref = upload(client, project, 'workbench.reference', {'manifest.json': json.dumps({'objects': [reference]}).encode(), 'reference.pdb': reference_bytes})
        result = execute(client, project, [
            {'id': 'merge', 'type': 'workbench.collection.merge', 'inputs': {'packages': [p['id'] for p in packages]}, 'parameters': {}},
            {'id': 'extract', 'type': 'workbench.collection.extract_structures', 'inputs': {}, 'parameters': {}},
            {'id': 'compare', 'type': 'workbench.compare', 'inputs': {'reference': [ref['id']]},
             'parameters': {'subject_selection': {'chains': ['A']}, 'reference_selection': {'chains': ['A']}}},
        ], [
            {'source': 'merge', 'source_port': 'collection', 'target': 'extract', 'target_port': 'collection'},
            {'source': 'extract', 'source_port': 'structures', 'target': 'compare', 'target_port': 'subject'},
        ])
        assert result['status'] == 'succeeded', result
        comparisons = result['nodes']['compare']['outputs']['comparison']
        assert len(comparisons) == 4
        for new, old in zip(comparisons, packages, strict=True):
            a, b = entry(client, new), entry(client, old['id'])
            assert a['subject']['id'] == b['subject']['id']
            assert a['region'] == b['region']
            assert a['metrics']['tm_reference']['value'] == pytest.approx(b['metrics']['tm_reference']['value'], abs=1e-12)
            assert a['metrics']['tm_reference']['normalization_length'] == 56
        output = result['nodes']['extract']['outputs']['structures'][0]
        target = client.post('/api/projects', json={'name': 'Adopted real structures'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': output}).json()['id']
        ref_adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': ref['id']}).json()['id']
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.delete('/api/modules/workbench.collection').raise_for_status()
        client.delete('/api/modules/workbench.generation').raise_for_status()
        independent = execute(client, target, [{'id': 'compare', 'type': 'workbench.compare',
            'inputs': {'subject': [adopted], 'reference': [ref_adopted]},
            'parameters': {'subject_selection': {'chains': ['A']}, 'reference_selection': {'chains': ['A']}}}])
        assert independent['status'] == 'succeeded', independent
        assert len(independent['nodes']['compare']['outputs']['comparison']) == 4
