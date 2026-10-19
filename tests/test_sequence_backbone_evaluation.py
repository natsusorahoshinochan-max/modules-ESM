"""Independent scoring through public HTTP and the public ProteinMPNN adapter."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.test_proteinmpnn import backbone
from tests.run_helpers import wait_response

POSITIONS = [{'chain': 'B', 'author_number': 42, 'insertion_code': '', 'sequence_index': 1}, {'chain': 'B', 'author_number': 42, 'insertion_code': 'A', 'sequence_index': 2}]
BINDINGS = [{'reference_chain': 'B', 'object': 'independent', 'positions': POSITIONS}, {'reference_chain': 'A', 'object': 'context', 'positions': [{'chain': 'A', 'author_number': 9, 'insertion_code': '', 'sequence_index': 1}]}]

def test_independent_reference_complete_mapping_masks_and_adoption(tmp_path, monkeypatch):
    calls = []
    def worker(command, **kwargs):
        payload = json.loads(Path(command[-1]).read_text()); calls.append(payload)
        assert payload['sequences'] == {'B': 'WY', 'A': 'G'}
        assert payload['parameters']['seed'] == 0
        assert payload['parameters']['fixed_positions'] == {'B': [2]}
        Path(payload['output']).write_text(json.dumps({'actual_seed': 0, 'samples': [{'chains': payload['sequences'], 'score': 1., 'global_score': 7/3, 'residue_nll': {'B': [1., 2.], 'A': [4.]}, 'design_mask': {'B': [1., 0.], 'A': [0.]}, 'coordinate_mask': {'B': [1., 1.], 'A': [1.]}, 'tool_chain_order': ['B', 'A']}]}))
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', worker)
    path = tmp_path / 'original.pdb'; backbone(path)
    original = path.read_bytes()
    objects = [{'id': 'independent', 'sequence': 'WY', 'positions': [{'sequence_index': 1}, {'sequence_index': 2}], 'label': 'Independent sequence', 'source_generation': {'reference': 'different-backbone'}}, {'id': 'context', 'sequence': 'G'}]
    with TestClient(create_application(data_root=tmp_path / 'data')) as client:
        project = client.post('/api/projects', json={'name': 'Evaluation'}).json()['id']
        seq = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': objects}).encode(), 'original.fa': b'>research\nWY\n'})
        ref = upload(client, project, 'workbench.structure_set', {'manifest.json': json.dumps({'objects': [{'id': 'arbitrary', 'structure': {'file': 'original.pdb', 'format': 'pdb'}}]}).encode(), 'original.pdb': original})
        node = {'id': 'e', 'type': 'workbench.evaluate_sequence_backbone', 'inputs': {'sequences': [seq['id']], 'reference': [ref['id']]}, 'parameters': {'reference': 'arbitrary', 'bindings': BINDINGS, 'region': [POSITIONS[1] | {'sequence_index': 2}]}, 'tools': {'mpnn': 'workbench.proteinmpnn.local'}, 'tool_parameters': {'mpnn': {'seed': 0, 'designed_chains': ['B'], 'fixed_positions': {'B': [2]}}}}
        # Region uses true structure positions, independent of sequence index.
        node['parameters']['region'] = [{k: v for k, v in POSITIONS[1].items() if k != 'sequence_index'}]
        client.put(f'/api/projects/{project}', json={'flow': {'nodes': [node], 'edges': []}, 'layout': {}}).raise_for_status()
        result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        assert result['status'] == 'succeeded', result
        output = result['nodes']['e']['outputs']['evaluation'][0]
        doc = client.get(f'/api/packages/{output}/file', params={'key': client.get(f'/api/packages/{output}').json()['entry']}).json()
        assert doc['objects'] == objects
        e = doc['evaluations'][0]
        assert e['object_ids'] == ['independent', 'context']
        assert e['reference']['id'] == 'arbitrary'
        assert e['bindings'] == BINDINGS
        assert e['samples'][0]['score'] == 1. and e['samples'][0]['global_score'] == 7/3
        assert e['samples'][0]['region_nll'] == 2.
        assert e['samples'][0]['region_mask'] == {'B': [0., 1.], 'A': [0.]}
        assert e['actual_seed'] == 0 and e['method'] == 'ProteinMPNN score_only'
        assert len(calls) == 1
        target = client.post('/api/projects', json={'name': 'Independent'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': output}).json()
        assert 'id' in adopted, adopted
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.delete('/api/modules/workbench.sequence_backbone_evaluation').raise_for_status()
        client.delete('/api/modules/workbench.proteinmpnn').raise_for_status()
        retained = client.get(f"/api/packages/{adopted['id']}/file", params={'key': client.get(f"/api/packages/{adopted['id']}").json()['entry']}).json()
        assert retained == doc
        file_key = e['reference']['structure']['file']
        assert client.get(f"/api/packages/{adopted['id']}/file", params={'key': file_key}).content == original


def test_bad_source_and_reference_mapping_stop_before_tool_without_input_changes(tmp_path, monkeypatch):
    from copy import deepcopy
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Bad mapping reached native worker')))
    path = tmp_path / 'input.pdb'; backbone(path)
    with TestClient(create_application(data_root=tmp_path / 'data')) as client:
        project = client.post('/api/projects', json={'name': 'Bad correspondence'}).json()['id']
        ref = upload(client, project, 'workbench.structure_set', {'manifest.json': json.dumps({'objects': [{'id': 'arbitrary', 'structure': {'file': 'input.pdb', 'format': 'pdb'}}]}).encode(), 'input.pdb': path.read_bytes()})
        baseline = [{'id': 'independent', 'sequence': 'WY'}, {'id': 'context', 'sequence': 'G'}]
        cases = []
        incomplete = deepcopy(baseline); incomplete[0]['positions'] = [{'sequence_index': 1, 'chain': 'S', 'author_number': 6, 'insertion_code': ''}]
        cases.append((incomplete, BINDINGS, 'source'))
        prefix = deepcopy(baseline); prefix[0]['sequence'] = 'W'; cases.append((prefix, BINDINGS, 'complete'))
        cases.append((baseline, BINDINGS[:1], 'every reference chain'))
        wrong = deepcopy(BINDINGS); wrong[0]['positions'][1]['insertion_code'] = ''; cases.append((baseline, wrong, 'insertion'))
        wrong = deepcopy(BINDINGS); wrong[0]['positions'][1]['sequence_index'] = 1; cases.append((baseline, wrong, 'order'))
        wrong = deepcopy(BINDINGS); wrong[1]['reference_chain'] = 'B'; cases.append((baseline, wrong, 'ambiguous'))
        rich = [{'id': 'independent', 'chains': {'S': 'WY'}, 'positions': [{'chain': 'S', 'author_number': 7, 'insertion_code': '', 'tool_position': 1}]}, baseline[1]]
        rich_bindings = deepcopy(BINDINGS); rich_bindings[0]['source_chain'] = 'S'; cases.append((rich, rich_bindings, 'source'))
        for objects, bindings, diagnostic in cases:
            content = json.dumps({'objects': objects}).encode()
            seq = upload(client, project, 'workbench.sequence', {'manifest.json': content})
            node = {'id': 'e', 'type': 'workbench.evaluate_sequence_backbone', 'inputs': {'sequences': [seq['id']], 'reference': [ref['id']]}, 'parameters': {'reference': 'arbitrary', 'bindings': bindings}, 'tools': {'mpnn': 'workbench.proteinmpnn.local'}}
            client.put(f'/api/projects/{project}', json={'flow': {'nodes': [node], 'edges': []}, 'layout': {}}).raise_for_status()
            result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()['nodes']['e']
            assert result['status'] == 'failed' and not result['outputs'], result
            assert diagnostic in str(result['diagnostics']), result
            assert client.get(f"/api/packages/{seq['id']}/file", params={'key': 'manifest.json'}).content == content


def test_public_reader_rejects_missing_reference_files_and_incomplete_values(tmp_path):
    from modules.sequence_backbone_evaluation.formats import read_evaluations
    from types import SimpleNamespace
    document = {'objects': [{'id': 's', 'sequence': 'W'}], 'evaluations': [{
        'origin': 'independent_sequence_backbone', 'object_ids': ['s'], 'reference': {'id': 'r', 'structure': {'file': 'reference.pdb', 'format': 'pdb'}},
        'reference_manifest': {'file': 'reference.json', 'files': {'manifest.json': 'reference.json', 'model.pdb': 'reference.pdb'}},
        'positions': [{'chain': 'B', 'author_number': 42, 'insertion_code': 'A', 'tool_position': 1}],
        'bindings': [{'reference_chain': 'B', 'object': 's', 'positions': [{'chain': 'B', 'author_number': 42, 'insertion_code': 'A', 'sequence_index': 1}]}],
        'region': None, 'method': 'ProteinMPNN score_only', 'unit': 'negative log likelihood (natural logarithm)', 'parameters': {'seed': 0}, 'actual_seed': 17,
        'samples': [{'chains': {'B': 'W'}, 'score': 2., 'global_score': 2., 'region_nll': 2., 'residue_nll': {'B': [2.]}, 'design_mask': {'B': [1.]}, 'coordinate_mask': {'B': [1.]}, 'region_mask': {'B': [1.]}}]}]}
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(document))
    package = SimpleNamespace(entry='manifest.json', files=('manifest.json', 'reference.pdb', 'reference.json'), open=lambda key: (tmp_path / key).open('rb'))
    (tmp_path / 'reference.pdb').write_bytes(b'original coordinates')
    (tmp_path / 'reference.json').write_text('{}')
    assert read_evaluations(package) == document
    import pytest
    package.files = ('manifest.json', 'reference.json')
    with pytest.raises(ValueError, match='file'):
        read_evaluations(package)
    package.files = ('manifest.json', 'reference.pdb', 'reference.json')
    document['evaluations'][0]['samples'][0]['design_mask']['B'] = []
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='mask'):
        read_evaluations(package)


def test_rich_design_scores_stay_source_and_independent_masks_change_actual_score(tmp_path, monkeypatch):
    from modules.sequence_backbone_evaluation.formats import read_evaluations
    from core.host import Workbench
    from protein_workbench_public.module_api import Delivery
    from tests.run_helpers import wait_run
    calls = []
    def worker(command, **kwargs):
        payload = json.loads(Path(command[-1]).read_text()); calls.append(payload)
        assert payload['parameters']['seed'] == 17 and payload['actual_seed'] == 17
        assert payload['sequences'] == {'B': 'WY', 'A': 'G'}
        masked = payload['parameters']['fixed_positions'] == {'B': [2]}
        Path(payload['output']).write_text(json.dumps({'actual_seed': 17, 'samples': [{'chains': payload['sequences'], 'score': 1. if masked else 1.5, 'global_score': 7/3, 'residue_nll': {'B': [1., 2.], 'A': [4.]}, 'design_mask': {'B': [1., 0. if masked else 1.], 'A': [0.]}, 'coordinate_mask': {'B': [1., 1.], 'A': [1.]}}]}))
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', worker)
    app = Workbench(tmp_path / 'data')
    app.install('modules.proteinmpnn:module'); app.install('modules.sequence_backbone_evaluation:module')
    project = app.create_project('Natural and independent scores')
    work = app.new_workdir(); backbone(work / 'input.pdb')
    (work / 'ref.json').write_text(json.dumps({'objects': [{'id': 'other-reference', 'structure': {'file': 'input.pdb', 'format': 'pdb'}}]}))
    ref = app.create_input(project['id'], Delivery('workbench.structure_set', 'ref.json', {'ref.json': 'ref.json', 'input.pdb': 'input.pdb'}), work)
    objects = [{'id': 'design', 'chains': {'S': 'WY', 'T': 'G'}, 'positions': [{'chain': 'S', 'author_number': 1, 'insertion_code': '', 'tool_position': 1}, {'chain': 'S', 'author_number': 2, 'insertion_code': '', 'tool_position': 2}, {'chain': 'T', 'author_number': 3, 'insertion_code': '', 'tool_position': 1}], 'backbone': {'id': 'generation-reference'}, 'design': {'score': .7, 'global_score': .9}}]
    work = app.new_workdir()
    (work / 'source.json').write_text(json.dumps({'objects': objects}))
    source = app.create_input(project['id'], Delivery('workbench.proteinmpnn_design', 'source.json', {'source.json': 'source.json'}), work)
    bindings = [{**BINDINGS[0], 'object': 'design', 'source_chain': 'S'}, {**BINDINGS[1], 'object': 'design', 'source_chain': 'T'}]
    scores = []
    for fixed in ({'B': [2]}, {}):
        app.save_project(project['id'], {'nodes': [{'id': 'e', 'type': 'workbench.evaluate_sequence_backbone', 'inputs': {'sequences': [source['id']], 'reference': [ref['id']]}, 'parameters': {'reference': 'other-reference', 'bindings': bindings, 'region': [ {'chain': 'B', 'author_number': 42, 'insertion_code': ''}, {'chain': 'A', 'author_number': 9, 'insertion_code': ''}]}, 'tools': {'mpnn': 'workbench.proteinmpnn.local'}, 'tool_parameters': {'mpnn': {'seed': 17, 'designed_chains': ['B'], 'fixed_positions': fixed}}}], 'edges': []}, {})
        run = wait_run(app, app.start(project['id']))
        assert run['status'] == 'succeeded', run
        result = read_evaluations(app.package(run['nodes']['e']['outputs']['evaluation'][0]))
        assert result['objects'] == objects
        e = result['evaluations'][0]
        assert e['reference']['id'] == 'other-reference'
        assert e['samples'][0]['region_nll'] == 2.5
        scores.append(e['samples'][0]['score'])
    assert scores == [1., 1.5] and len(calls) == 2


def test_public_inspect_interaction_displays_explicit_objects_chains_and_real_positions(tmp_path):
    path = tmp_path / 'reference.pdb'; backbone(path)
    with TestClient(create_application(data_root=tmp_path / 'data')) as client:
        project = client.post('/api/projects', json={'name': 'Explicit inspect'}).json()['id']
        seq = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [{'id': 's', 'label': 'Research sequence', 'sequence': 'WY'}]}).encode()})
        ref = upload(client, project, 'workbench.structure_set', {'manifest.json': json.dumps({'objects': [{'id': 'r', 'label': 'Chosen reference', 'structure': {'file': 'reference.pdb', 'format': 'pdb'}}]}).encode(), 'reference.pdb': path.read_bytes()})
        response = client.post(f'/api/projects/{project}/interactions', json={'interaction': 'workbench.sequence_backbone.inspect', 'inputs': {'sequences': [seq['id']], 'reference': [ref['id']]}, 'parameters': {}})
        assert response.status_code == 200, response.text
        interaction = response.json()['id']
        preview = client.post(f'/api/interactions/{interaction}/execute')
        assert preview.status_code == 200, preview.text
        result = preview.json()
        assert result['outputs'] == []
        assert result['data']['sequences'] == [{'object': 's', 'label': 'Research sequence', 'sequence': 'WY'}]
        assert result['data']['references'][0]['positions'] == [{'chain': 'B', 'author_number': 42, 'insertion_code': '', 'tool_position': 1}, {'chain': 'B', 'author_number': 42, 'insertion_code': 'A', 'tool_position': 2}, {'chain': 'A', 'author_number': 9, 'insertion_code': '', 'tool_position': 1}]
        client.delete(f'/api/interactions/{interaction}').raise_for_status()
