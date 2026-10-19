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


def test_inspect_uses_explicit_packages_and_does_not_run_or_save_analysis(tmp_path):
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        project = client.post('/api/projects', json={'name': 'Choose actual values'}).json()['id']
        source = upload(client, project, 'workbench.structure_confidence', confidence_files())
        response = client.post(f'/api/projects/{project}/interactions', json={
            'interaction': 'workbench.inspect_metrics', 'inputs': {'metrics': [source['id']]}, 'parameters': {}})
        assert response.status_code == 200, response.text
        token = response.json()['id']
        response = client.post(f'/api/interactions/{token}/execute')
        assert response.status_code == 200, response.text
        display = response.json()
        choice = next(c for c in display['data']['choices'] if c['selector']['metric'] == 'plddt')
        assert choice['object_label'] == 'Research structure'
        assert choice['positions'] == POSITIONS
        assert choice['reference_label'] == 'No reference'
        assert 'input_values' not in choice
        assert display['outputs'] == []
        assert client.get(f'/api/projects/{project}/runs').json() == []
        assert len(client.get(f'/api/projects/{project}/packages').json()) == 1
        client.delete(f'/api/interactions/{token}').raise_for_status()


def test_backbone_metrics_keep_joint_context_and_explicit_stochastic_sample(tmp_path):
    objects = [{'id': 'one', 'label': 'Sequence one', 'sequence': 'AA'}, {'id': 'two', 'label': 'Context sequence', 'sequence': 'A'}]
    axis = [dict(p, tool_position=i) for i,p in enumerate(POSITIONS[:2],1)] + [{'chain':'B','author_number':3,'insertion_code':'','tool_position':1}]
    sample = {'chains': {'Z':'AA','B':'A'}, 'score':2., 'global_score':3., 'region_nll':3.,
        'residue_nll': {'Z':[1.,3.], 'B':[5.]}, 'design_mask': {'Z':[1.,1.], 'B':[0.]},
        'coordinate_mask': {'Z':[1.,1.], 'B':[1.]}, 'region_mask': {'Z':[1.,1.], 'B':[1.]}}
    evaluation = {'origin':'independent_sequence_backbone','object_ids':['one','two'],
        'reference': {'id':'unrelated','label':'Arbitrary backbone','structure':{'file':'backbone.pdb','format':'pdb'}},
        'positions':axis, 'region':None, 'method':'ProteinMPNN score_only',
        'bindings':[{'reference_chain':'Z','object':'one','positions':[dict(p,sequence_index=i) for i,p in enumerate(POSITIONS[:2],1)]}, {'reference_chain':'B','object':'two','positions':[{'chain':'B','author_number':3,'insertion_code':'','sequence_index':1}]}],
        'reference_manifest':{'file':'reference.json','files':{'reference.json':'reference.json','backbone.pdb':'backbone.pdb'}},
        'unit':'negative log likelihood (natural logarithm)', 'meaning':'Full-context native NLL', 'actual_seed':17, 'parameters':{'seed':0},
        'samples':[sample, {**sample,'residue_nll':{'Z':[2.,4.],'B':[6.]}}]}
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project = client.post('/api/projects',json={'name':'Explicit sample'}).json()['id']
        source = upload(client,project,'workbench.sequence_backbone_evaluation',{'manifest.json':json.dumps({'objects':objects,'evaluations':[evaluation]}).encode(),'backbone.pdb':b'complete original','reference.json':b'{}'})
        selector={'input':0,'objects':['one','two'],'origin':'sequence_backbone','evaluation':0,'sample':1,'metric':'residue_nll'}
        result = run_analysis(client,project,source,[{**selector,'region':POSITIONS[:2]}])
        assert result['status']=='succeeded',result
        output=result['nodes']['analyze']['outputs']['analysis'][0]
        analysis=client.get(f'/api/packages/{output}/file',params={'key':'manifest.json'}).json()['analyses'][0]
        assert analysis['object']['members']==objects
        assert analysis['reference']['id']=='unrelated'
        assert analysis['input_values']==[2.,4.] and analysis['statistics']['mean']==3.
        ambiguous={k:v for k,v in selector.items() if k!='sample'}
        failure=run_analysis(client,project,source,[ambiguous])
        assert failure['status']=='failed' and 'ambiguous' in str(failure),failure


def test_canvas_nodes_choose_package_groups_without_global_grouping(tmp_path):
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project=client.post('/api/projects',json={'name':'Canvas composition'}).json()['id']
        first=upload(client,project,'workbench.structure_confidence',confidence_files())
        second=upload(client,project,'workbench.structure_confidence',confidence_files([.9,.7,.5]))
        selector={'object':'original','origin':'evaluation','evaluation':0,'metric':'plddt'}
        nodes=[{'id':'together','type':'workbench.analyze_metrics','inputs':{'metrics':[first['id'],second['id']]},
                'parameters':{'selections':[dict(selector,input=0,region=[POSITIONS[0]]),dict(selector,input=1,region=[POSITIONS[2]])]}},
               {'id':'separate','type':'workbench.analyze_metrics','inputs':{'metrics':[second['id']]},
                'parameters':{'selections':[dict(selector,input=0,region=[POSITIONS[1]])]}}]
        client.put(f'/api/projects/{project}',json={'flow':{'nodes':nodes,'edges':[]},'layout':{}}).raise_for_status()
        result=wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert result['status']=='succeeded',result
        def saved(node):
            output=result['nodes'][node]['outputs']['analysis'][0]
            return client.get(f'/api/packages/{output}/file',params={'key':'manifest.json'}).json()
        assert [a['input_values'] for a in saved('together')['analyses']]==[[.2],[.5]]
        assert [a['input_values'] for a in saved('separate')['analyses']]==[[.7]]
        assert len(saved('together')['sources'])==2 and len(saved('separate')['sources'])==1


def test_scalar_selection_does_not_require_unused_per_position_correspondence(tmp_path):
    files=confidence_files([.2])
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project=client.post('/api/projects',json={'name':'Use actual scalar only'}).json()['id']
        source=upload(client,project,'workbench.structure_confidence',files)
        selector={'input':0,'object':'original','origin':'evaluation','evaluation':0,'metric':'mean_plddt'}
        result=run_analysis(client,project,source,[selector])
        assert result['status']=='succeeded',result
        output=result['nodes']['analyze']['outputs']['analysis'][0]
        saved=client.get(f'/api/packages/{output}/file',params={'key':'manifest.json'}).json()
        assert saved['analyses'][0]['input_values']==[.5]
        assert saved['analyses'][0]['region'] is None


def test_invalid_confidence_scalar_scale_stops_without_a_replacement_value(tmp_path):
    files=confidence_files()
    document=json.loads(files['manifest.json'])
    document['evaluations'][0]['values']['mean_plddt']['value']=80.
    files['manifest.json']=json.dumps(document).encode()
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project=client.post('/api/projects',json={'name':'Existing scale'}).json()['id']
        source=upload(client,project,'workbench.structure_confidence',files)
        result=run_analysis(client,project,source,[{'input':0,'object':'original','origin':'evaluation','evaluation':0,'metric':'mean_plddt'}])
        assert result['status']=='failed' and 'fraction' in str(result),result
