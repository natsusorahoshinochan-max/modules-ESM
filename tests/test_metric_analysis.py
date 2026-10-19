"""Existing numbers analyzed through installed HTTP modules and independent files."""
import json
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.run_helpers import wait_response

POSITIONS = [
    {'chain': 'Z', 'author_number': 12, 'insertion_code': ''},
    {'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'},
    {'chain': 'Z', 'author_number': 19, 'insertion_code': ''},
]


def confidence_files(values=None):
    evaluation = {'object_id': 'original', 'reference': None, 'region': None,
        'origin': 'independent_existing_geometry', 'method': 'Original geometry evaluator',
        'values': {'mean_plddt': {'value': .5, 'unit': 'fraction (0–1)', 'meaning': 'Original full mean'}},
        'per_position': {'file': 'scores.json', 'unit': 'fraction (0–1)', 'meaning': 'Existing local confidence'}}
    document = {'objects': [{'id': 'original', 'label': 'Research structure',
        'structure': {'file': 'original.pdb', 'format': 'pdb'}}], 'evaluations': [evaluation]}
    return {'manifest.json': json.dumps(document).encode(), 'original.pdb': b'full original research structure',
        'scores.json': json.dumps({'positions': POSITIONS, 'plddt': values if values is not None else [.2, .8, .4]}).encode(),
        'research.txt': b'original observations'}


def run_analysis(client, project, package, selections):
    flow = {'nodes': [{'id': 'analyze', 'type': 'workbench.analyze_metrics',
        'inputs': {'metrics': [package['id']]}, 'parameters': {'selections': selections}}], 'edges': []}
    client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {}}).raise_for_status()
    return wait_response(client, client.post(f'/api/projects/{project}/runs')).json()


def test_existing_discontinuous_values_survive_adoption_without_producer(tmp_path):
    storage = tmp_path / 'store'
    files = confidence_files()
    selector = {'input': 0, 'object': 'original', 'origin': 'evaluation', 'evaluation': 0, 'metric': 'plddt'}
    with TestClient(create_application(data_root=storage)) as client:
        project = client.post('/api/projects', json={'name': 'Original numbers'}).json()['id']
        package = upload(client, project, 'workbench.structure_confidence', files)
        result = run_analysis(client, project, package, [{**selector, 'region': [POSITIONS[0], POSITIONS[2]]}])
        assert result['status'] == 'succeeded', result
        output = result['nodes']['analyze']['outputs']['analysis'][0]
        saved = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
        analysis, = saved['analyses']
        assert analysis['object']['id'] == 'original' and analysis['reference'] is None
        assert analysis['region'] == [POSITIONS[0], POSITIONS[2]]
        assert analysis['input_values'] == [.2, .4]
        assert analysis['statistics'] == {'count': 2, 'mean': .30000000000000004, 'minimum': .2, 'maximum': .4}
        assert analysis['unit'] == 'fraction (0–1)'
        assert analysis['source_method'] == 'Original geometry evaluator'
        assert analysis['method'] == 'arithmetic mean, minimum, maximum of existing values'
        source = saved['sources'][0]
        assert source['format'] == 'workbench.structure_confidence'
        for key, content in files.items():
            assert client.get(f'/api/packages/{output}/file', params={'key': source['files'][key]}).content == content
        target = client.post('/api/projects', json={'name': 'Independent'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': output}).json()
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.delete('/api/modules/workbench.structure_confidence').raise_for_status()
        client.delete('/api/modules/workbench.metric_analysis').raise_for_status()
    from core.host import Workbench
    from modules.metric_analysis.formats import read_analysis
    document = read_analysis(Workbench(storage).package(adopted['id']))
    assert document['analyses'][0]['input_values'] == [.2, .4]


def test_missing_ambiguous_and_incomplete_values_fail_whole_analysis(tmp_path):
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        project = client.post('/api/projects', json={'name': 'Strict correspondence'}).json()['id']
        base = {'input': 0, 'object': 'original', 'origin': 'evaluation', 'evaluation': 0, 'metric': 'plddt'}
        cases = [
            (confidence_files([.2]), base, 'correspondence'),
            (confidence_files([.2, None, .4]), base, 'finite'),
            (confidence_files(), {**base, 'region': [{'chain': 'Z', 'author_number': 99, 'insertion_code': ''}]}, 'lacks'),
            (confidence_files(), {**base, 'region': [POSITIONS[0], POSITIONS[0]]}, 'repeated'),
            (confidence_files(), {**base, 'region': [{**POSITIONS[0], 'author_number': 12.0}]}, 'integer'),
            (confidence_files(), {'input': 0, 'object': 'original'}, 'ambiguous'),
            (confidence_files(), {**base, 'metric': 'mean_plddt', 'region': [POSITIONS[0]]}, 'Scalar'),
        ]
        for files, selection, reason in cases:
            source = upload(client, project, 'workbench.structure_confidence', files)
            result = run_analysis(client, project, source, [base, selection])
            node = result['nodes']['analyze']
            assert result['status'] == 'failed' and not node['outputs'], result
            assert reason in str(node['diagnostics']), result
            assert client.get(f'/api/packages/{source["id"]}/file', params={'key': 'original.pdb'}).content == files['original.pdb']
        files = confidence_files()
        del files['scores.json']
        source = upload(client, project, 'workbench.structure_confidence', files)
        result = run_analysis(client, project, source, [base])
        assert result['status'] == 'failed' and 'not declared' in str(result), result


def test_comparison_and_solubility_keep_scalar_scope_and_arbitrary_reference(tmp_path):
    from pathlib import Path
    sample = Path(__file__).parents[1] / 'modules/structure_comparison/sample'
    files = {p.name: p.read_bytes() for p in sample.iterdir() if p.is_file()}
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        project = client.post('/api/projects', json={'name': 'Independent reference'}).json()['id']
        source = upload(client, project, 'workbench.comparison', files)
        selector = {'input': 0, 'object': 'predicted-object', 'origin': 'comparison', 'metric': 'tm_reference'}
        result = run_analysis(client, project, source, [selector])
        assert result['status'] == 'succeeded', result
        output = result['nodes']['analyze']['outputs']['analysis'][0]
        saved = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
        analysis = saved['analyses'][0]
        assert analysis['reference']['id'] == 'independent-reference'
        assert analysis['object']['generation']['tool']['id'] == 'other.producer'
        assert analysis['input_values'] == [1.0]
        assert analysis['region'] == {'subject': None, 'reference': None}
        assert analysis['meaning'] == 'selected reference protein residue count'
        failure = run_analysis(client, project, source, [{**selector, 'region': [POSITIONS[0]]}])
        assert failure['status'] == 'failed' and 'Scalar' in str(failure), failure
        solubility = {'objects': [{'id': 'sequence', 'label': 'Imported sequence', 'sequence': 'ACD'}],
            'evaluations': [{'object_id': 'sequence', 'reference': None, 'region': None, 'method': 'Protein-Sol October 2017',
                'values': {'scaled_solubility': {'value': .252, 'unit': 'dimensionless', 'meaning': 'Training-group scaled solubility'}}}],
            'tool': {'id': 'workbench.protein_sol', 'parameters': {}, 'output': 'tool.txt'}}
        source = upload(client, project, 'workbench.solubility', {'manifest.json': json.dumps(solubility).encode(), 'tool.txt': b'raw existing output'})
        result = run_analysis(client, project, source, [{'input': 0, 'object': 'sequence', 'origin': 'evaluation', 'evaluation': 0, 'metric': 'scaled_solubility'}])
        assert result['status'] == 'succeeded', result
        output = result['nodes']['analyze']['outputs']['analysis'][0]
        saved = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
        assert saved['analyses'][0]['statistics']['mean'] == .252


def test_prediction_confidence_maps_existing_values_to_actual_insertion_positions(tmp_path):
    structure = b''.join(f'ATOM  {i:5d}  CA  ALA Z{number:4d}{code:1s}   {i:8.3f}{0:8.3f}{0:8.3f}  1.00 10.00           C\n'.encode()
        for i, (number, code) in enumerate(((12, ''), (12, 'A'), (19, '')), 1)) + b'END\n'
    document = {'objects': [{'id': 'prediction', 'label': 'Natural confidence', 'sequence': 'AAA',
        'structure': {'file': 'prediction.pdb', 'format': 'pdb'},
        'confidence': {'plddt': {'file': 'confidence.json', 'scale': '0-1'}, 'ptm': .75}}],
        'tool': {'id': 'given.predictor', 'parameters': {'seed': 1}}}
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        project = client.post('/api/projects', json={'name': 'Existing natural confidence'}).json()['id']
        source = upload(client, project, 'workbench.prediction', {'manifest.json': json.dumps(document).encode(),
            'prediction.pdb': structure, 'confidence.json': b'{"plddt":[0.1,0.9,0.3]}'})
        selector = {'input': 0, 'object': 'prediction', 'origin': 'generation', 'metric': 'plddt', 'region': [POSITIONS[1], POSITIONS[2]]}
        result = run_analysis(client, project, source, [selector])
        assert result['status'] == 'succeeded', result
        output = result['nodes']['analyze']['outputs']['analysis'][0]
        analysis = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()['analyses'][0]
        assert analysis['input_values'] == [.9, .3] and analysis['statistics']['mean'] == .6
        assert analysis['positions'] == [POSITIONS[1], POSITIONS[2]]
        assert analysis['source_method'] == document['tool']
        assert analysis['reference'] is None
        document['objects'][0]['sequence'] = 'AAC'
        source = upload(client, project, 'workbench.prediction', {'manifest.json': json.dumps(document).encode(),
            'prediction.pdb': structure, 'confidence.json': b'{"plddt":[0.1,0.9,0.3]}'})
        failure = run_analysis(client, project, source, [selector])
        assert failure['status'] == 'failed' and 'sequence' in str(failure), failure
