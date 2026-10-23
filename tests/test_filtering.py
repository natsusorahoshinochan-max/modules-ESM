"""Filtering through public installed HTTP execution and temporary interaction."""
import json
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.run_helpers import wait_response
from tests.test_comparison import pdb


def source(client, project, identities, values):
    objects = [{'id': key, 'label': 'Structure '+key, 'structure': {'file': key+'.pdb', 'format':'pdb'}} for key in identities]
    evaluations = [{'object_id': key, 'reference':None, 'region':None, 'method':'Recorded evaluator','origin':'independent_existing_geometry',
        'values': {'quality': {'value':value, 'unit':'fraction (0–1)', 'meaning':'Recorded quality'}}} for key,value in zip(identities,values)]
    files = {'manifest.json':json.dumps({'objects':objects,'evaluations':evaluations}).encode()}
    files.update({key+'.pdb':pdb() for key in identities})
    return upload(client, project, 'workbench.structure_confidence', files)


def interaction(client, project, name, inputs, parameters):
    response = client.post(f'/api/projects/{project}/interactions', json={'interaction':name,'inputs':inputs,'parameters':parameters})
    response.raise_for_status()
    token = response.json()['id']
    response = client.post(f'/api/interactions/{token}/execute')
    client.delete(f'/api/interactions/{token}')
    return response


def test_shared_multi_package_filter_and_real_persistent_files(tmp_path):
    app = create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project = client.post('/api/projects',json={'name':'Filtering'}).json()['id']
        a = source(client,project,['a','b'],[.8,.8])
        b = source(client,project,['c'],[.3])
        inputs = {'candidates':[a['id'],b['id']], 'evaluations':[a['id'],b['id']]}
        params = {'sort': {'evaluation': {'metric':'quality','method':'Recorded evaluator','reference':None,'region':None}, 'direction':'descending'}, 'limit':2}
        temporary = interaction(client,project,'workbench.filter',inputs,params)
        assert temporary.status_code == 200, temporary.text
        assert temporary.json()['data']['selected'] == [{'input':0,'item':0},{'input':0,'item':1}]
        assert client.get(f'/api/projects/{project}/runs').json() == []
        flow = {'nodes':[{'id':'filter','type':'workbench.filter','inputs':inputs,'parameters':params}], 'edges':[]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run = wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert run['status'] == 'succeeded', run
        output = app.state.workbench.package(run['nodes']['filter']['outputs']['collection'][0])
        from modules.collection.formats import read_collection
        saved = read_collection(output)
        assert saved['selected'] == temporary.json()['data']['selected']
        assert [item['object']['id'] for item in saved['items']] == ['a','b']
        with output.open(saved['sources'][0]['files']['a.pdb']) as stream:
            assert stream.read() == pdb()


def test_missing_ambiguous_and_quantity_boundaries_stop_whole_operation(tmp_path):
    app = create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project = client.post('/api/projects',json={'name':'Boundaries'}).json()['id']
        a = source(client,project,['a','b'],[.8,.3])
        inputs = {'candidates':[a['id']],'evaluations':[a['id']]}
        evaluation = {'metric':'quality','method':'Recorded evaluator','reference':None,'region':None}
        for limit,expected in [(0,[]),(9,[{'input':0,'item':0},{'input':0,'item':1}])]:
            result = interaction(client,project,'workbench.filter',inputs,{'limit':limit})
            assert result.json()['data']['selected'] == expected
        assert interaction(client,project,'workbench.filter',{}, {'limit':3}).json()['data']['selected'] == []
        missing = source(client,project,['a'],[.9])
        for values in ([missing['id']], [a['id'],a['id']]):
            result = interaction(client,project,'workbench.filter',dict(inputs,evaluations=values),{
                'conditions':[{'evaluation':evaluation,'operator':'gt','value':.99}],
                'sort':{'evaluation':evaluation,'direction':'ascending'}})
            assert result.status_code == 400 and 'missing or ambiguous' in result.text
        result = interaction(client,project,'workbench.filter',inputs,{'limit':-1})
        assert result.status_code == 400


def test_explicit_connected_evaluations_follow_changed_references_and_require_one_match(tmp_path):
    app = create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name': 'Changing references'}).json()['id']

        def comparison(subject_id, reference_id):
            document = {
                'subject': {'id': subject_id, 'structure': {'file': 'subject.pdb', 'format': 'pdb'}},
                'reference': {'id': reference_id, 'structure': {'file': 'reference.pdb', 'format': 'pdb'}},
                'region': None, 'method': {'name': 'TM-align'},
                'metrics': {'tm_reference': {'value': .8, 'unit': 'dimensionless', 'normalization': 'reference length'}},
            }
            return upload(client, project, 'workbench.comparison', {
                'manifest.json': json.dumps(document).encode(), 'subject.pdb': pdb(), 'reference.pdb': pdb(),
            })

        first = comparison('round-one', 'fixed-reference')
        second = comparison('round-two', 'updated-reference')
        alternate = comparison('round-two', 'another-explicit-reference')
        rule = {'metric': 'tm_reference', 'method': {'name': 'TM-align'}, 'region': None,
                'reference_mode': 'provided_evaluations'}
        for parameters in ({'conditions': [{'evaluation': rule, 'operator': 'ge', 'value': .5}]},
                           {'sort': {'evaluation': rule, 'direction': 'descending'}}):
            for package in (first, second):
                result = interaction(client, project, 'workbench.filter',
                                     {'candidates': [package['id']], 'evaluations': [package['id']]}, parameters)
                assert result.status_code == 200, result.text
                assert result.json()['data']['selected'] == [{'input': 0, 'item': 0}]
            for evaluations in ([], [second['id'], alternate['id']]):
                result = interaction(client, project, 'workbench.filter',
                                     {'candidates': [second['id']], 'evaluations': evaluations}, parameters)
                assert result.status_code == 400 and 'missing or ambiguous' in result.text

        for invalid in (dict(rule, reference=None), dict(rule, reference_mode='latest')):
            result = interaction(client, project, 'workbench.filter',
                                 {'candidates': [second['id']], 'evaluations': [second['id']]},
                                 {'sort': {'evaluation': invalid, 'direction': 'ascending'}})
            assert result.status_code == 400 and 'reference' in result.text
        fixed = {key: value for key, value in rule.items() if key != 'reference_mode'}
        fixed['reference'] = {'id': 'fixed-reference', 'structure': {'file': 'reference.pdb', 'format': 'pdb'}}
        result = interaction(client, project, 'workbench.filter',
                             {'candidates': [second['id']], 'evaluations': [second['id']]},
                             {'sort': {'evaluation': fixed, 'direction': 'ascending'}})
        assert result.status_code == 400 and 'missing or ambiguous' in result.text


def test_collection_adoption_and_explicit_structure_conversion(tmp_path):
    app = create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project = client.post('/api/projects',json={'name':'Original'}).json()['id']
        package = source(client,project,['a','b'],[.8,.3])
        flow={'nodes':[{'id':'filter','type':'workbench.filter','inputs':{'candidates':[package['id']]},'parameters':{'limit':1}}], 'edges':[]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run=wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        output=run['nodes']['filter']['outputs']['collection'][0]
        target=client.post('/api/projects',json={'name':'Adopted'}).json()['id']
        response=client.post(f'/api/projects/{target}/adoptions',json={'package_id':output})
        response.raise_for_status()
        adopted=response.json()['id']
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.delete('/api/modules/workbench.structure_confidence').raise_for_status()
        client.delete('/api/modules/workbench.filtering').raise_for_status()
        from modules.collection.formats import read_collection
        assert read_collection(app.state.workbench.package(adopted))['items'][0]['object']['id']=='a'
        flow={'nodes':[{'id':'extract','type':'workbench.collection.extract_structures','inputs':{'collection':[adopted]},'parameters':{}}], 'edges':[]}
        client.put(f'/api/projects/{target}',json={'flow':flow,'layout':{}}).raise_for_status()
        run=wait_response(client,client.post(f'/api/projects/{target}/runs')).json()
        assert run['status']=='succeeded', run
        structures=app.state.workbench.package(run['nodes']['extract']['outputs']['structures'][0])
        with structures.open(structures.entry) as stream:
            document=json.load(stream)
        obj,=document['objects']
        assert obj['id']=='a'
        with structures.open(obj['atoms']) as stream:
            actual_atoms=json.load(stream)
        assert len(actual_atoms)==6 and actual_atoms[-1]['residue_name']=='HOH'
        with structures.open(obj['structure']['file']) as stream:
            assert stream.read()==pdb()


def test_native_esm3_ptm_keeps_whole_generation_context_and_rejects_array(tmp_path):
    app=create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'name':'Native metrics'}).json()['id']
        def native(metric):
            return upload(client,project,'workbench.esm3_generation',{'manifest.json':json.dumps({'objects':[{'id':'joint-native','label':'Two-chain generation','sequence':'AC|DE','native':{'file':'native.json'},'tool':{'parameters':{},'actual_seed':7}}], 'tool':{'id':'workbench.esm3','parameters':{}}}).encode(), 'native.json':json.dumps({'tracks':{'sequence':'AC|DE'},'metrics':{'ptm':metric}}).encode()})
        package=native(.7)
        inputs={'candidates':[package['id']],'evaluations':[package['id']]}
        inspected=interaction(client,project,'workbench.filter.inspect',inputs,{})
        assert inspected.status_code==200, inspected.text
        row,=inspected.json()['data']['candidates']
        choice,=row['choices']
        evaluation={'bindings':[{'candidate':{'input':0,'item':0},'evaluation':choice['evaluation']}]}
        result=interaction(client,project,'workbench.filter',inputs,{'sort':{'evaluation':evaluation,'direction':'descending'}})
        assert result.status_code==200 and result.json()['data']['selected']==[{'input':0,'item':0}], result.text
        package=native([.7])
        inputs={'candidates':[package['id']],'evaluations':[package['id']]}
        inspected=interaction(client,project,'workbench.filter.inspect',inputs,{})
        choice,=inspected.json()['data']['candidates'][0]['choices']
        assert 'scalar' in choice['unavailable']
        evaluation={'bindings':[{'candidate':{'input':0,'item':0},'evaluation':choice['evaluation']}]}
        assert interaction(client,project,'workbench.filter',inputs,{'sort':{'evaluation':evaluation,'direction':'ascending'}}).status_code==400


def test_declared_local_single_invocation_ptm_batch_axis_is_decoded_exactly(tmp_path):
    app=create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'name':'Local native axis'}).json()['id']
        for value,ok in [([.73],True),([.73,.2],False),([[.73]],False)]:
            package=upload(client,project,'workbench.esm3_generation',{'manifest.json':json.dumps({'objects':[{'id':'native','sequence':'AAA','native':{'file':'native.json'},'tool':{'parameters':{},'actual_seed':7}}],'tool':{'id':'workbench.esm3.local','parameters':{}}}).encode(),'native.json':json.dumps({'tracks':{'sequence':'AAA'},'metrics':{'ptm':value}}).encode()})
            inputs={'candidates':[package['id']],'evaluations':[package['id']]}
            params={'conditions':[{'evaluation':{'metric':'ptm','method':{'id':'workbench.esm3.local','parameters':{},'actual_seed':7},'reference':None,'region':None},'operator':'ge','value':.7}]}
            result=interaction(client,project,'workbench.filter',inputs,params)
            assert (result.status_code==200)==ok, result.text
            if ok:
                assert result.json()['data']['selected']==[{'input':0,'item':0}]


def test_saved_collection_can_filter_again_using_its_independent_evaluation_files(tmp_path):
    app=create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'name':'Repeated filtering'}).json()['id']
        package=source(client,project,['a','b'],[.8,.3])
        selection={'metric':'quality','method':'Recorded evaluator','reference':None,'region':None}
        params={'sort':{'evaluation':selection,'direction':'descending'}}
        flow={'nodes':[{'id':'first','type':'workbench.filter','inputs':{'candidates':[package['id']],'evaluations':[package['id']]},'parameters':params},
            {'id':'second','type':'workbench.filter','inputs':{},'parameters':{'conditions':[{'evaluation':selection,'operator':'lt','value':.5}]}}],
            'edges':[{'source':'first','source_port':'collection','target':'second','target_port':'candidates'}, {'source':'first','source_port':'collection','target':'second','target_port':'evaluations'}]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run=wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert run['status']=='succeeded', run
        from modules.collection.formats import read_collection
        saved=read_collection(app.state.workbench.package(run['nodes']['second']['outputs']['collection'][0]))
        assert [item['object']['id'] for item in saved['items']]==['b']


def test_joint_backbone_evaluation_is_selectable_only_as_its_complete_context(tmp_path):
    from tests.test_metric_analysis import backbone_files
    app=create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project=client.post('/api/projects',json={'name':'Joint ownership'}).json()['id']
        files,_=backbone_files(None,{'X':[1.]*5})
        package=upload(client,project,'workbench.sequence_backbone_evaluation',files)
        inputs={'candidates':[package['id']],'evaluations':[package['id']]}
        response=interaction(client,project,'workbench.filter.inspect',inputs,{})
        assert response.status_code==200,response.text
        context,=response.json()['data']['candidates']
        assert context['label'].startswith('Joint sequence context:')
        choice=next(choice for choice in context['choices'] if choice['metric']=='global_score')
        evaluation={'bindings':[{'candidate':{'input':0,'item':0},'evaluation':choice['evaluation']}]}
        params={'sort':{'evaluation':evaluation,'direction':'ascending'}}
        assert interaction(client,project,'workbench.filter',inputs,params).status_code==200
        individual=upload(client,project,'workbench.sequence',{'manifest.json':json.dumps({'objects':[{'id':'sequence','sequence':'AAAAA'}]}).encode()})
        refused=interaction(client,project,'workbench.filter',dict(inputs,candidates=[individual['id']]),params)
        assert refused.status_code==400 and 'missing or ambiguous' in refused.text


def test_missing_complete_structure_file_fails_filter_without_hiding_candidate(tmp_path):
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project=client.post('/api/projects',json={'name':'Missing structure'}).json()['id']
        package=upload(client,project,'workbench.structure_set',{'manifest.json':json.dumps({'objects':[{'id':'missing','structure':{'file':'absent.cif','format':'mmcif'}}]}).encode()})
        result=interaction(client,project,'workbench.filter',{'candidates':[package['id']]},{'limit':0})
        assert result.status_code==400 and 'structure file' in result.text


def test_native_proteinmpnn_design_score_filters_complete_multichain_sample(tmp_path):
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project=client.post('/api/projects',json={'name':'Native design score'}).json()['id']
        objects=[]
        for identity,score in [('first',2.5),('second',1.2)]:
            objects.append({'id':identity,'chains':{'A':'AA','B':'GG'},'backbone':{'id':'backbone','structure':{'file':'backbone.pdb','format':'pdb'}},
                'design':{'chains':{'A':'AA','B':'GG'},'score':score,'global_score':score+.5,'coordinate_mask':{'A':[1.,1.],'B':[1.,1.]},'design_mask':{'A':[1.,1.],'B':[0.,0.]}},
                'tool':{'parameters':{'seed':7},'actual_seed':7}})
        package=upload(client,project,'workbench.proteinmpnn_design',{'manifest.json':json.dumps({'objects':objects,'tool':{'id':'workbench.proteinmpnn.local','parameters':{}}}).encode(),'backbone.pdb':pdb()})
        inputs={'candidates':[package['id']],'evaluations':[package['id']]}
        response=interaction(client,project,'workbench.filter.inspect',inputs,{})
        assert response.status_code==200,response.text
        rows=response.json()['data']['candidates']
        bindings=[{'candidate':{'input':row['input'],'item':row['item']},'evaluation':next(c for c in row['choices'] if c['metric']=='score')['evaluation']} for row in rows]
        result=interaction(client,project,'workbench.filter',inputs,{'sort':{'evaluation':{'bindings':bindings},'direction':'ascending'},'limit':1})
        assert result.status_code==200 and result.json()['data']['selected']==[{'input':0,'item':1}],result.text


def test_explicit_positional_analysis_result_is_used_as_existing_filter_scalar(tmp_path):
    from tests.test_metric_analysis import confidence_files
    with TestClient(create_application(data_root=tmp_path/'store')) as client:
        project=client.post('/api/projects',json={'name':'Analyze then filter'}).json()['id']
        package=upload(client,project,'workbench.structure_confidence',confidence_files())
        flow={'nodes':[{'id':'analysis','type':'workbench.analyze_metrics','inputs':{'metrics':[package['id']]},'parameters':{'selections':[{'input':0,'object':'original','origin':'evaluation','evaluation':0,'metric':'plddt'}]}},
            {'id':'filter','type':'workbench.filter','inputs':{'candidates':[package['id']]},'parameters':{'conditions':[{'evaluation':{'bindings':[{'candidate':{'input':0,'item':0},'evaluation':{'input':0,'selector':{'object':'original','origin':'analysis','analysis':0,'metric':'plddt.mean'}}}]},'operator':'gt','value':.4}]}}],
            'edges':[{'source':'analysis','source_port':'analysis','target':'filter','target_port':'evaluations'}]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run=wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert run['status']=='succeeded',run
        output=client.get('/api/packages/'+run['nodes']['filter']['outputs']['collection'][0]+'/file',params={'key':'manifest.json'}).json()
        assert [item['object']['id'] for item in output['items']]==['original']


def test_native_backbone_is_required_before_limits_in_direct_and_mapped_candidates(tmp_path):
    app = create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'name':'Native resources'}).json()['id']
        obj = {'id':'sample', 'chains':{'A':'AA'}, 'backbone':{'id':'backbone', 'structure':{'file':'backbone.pdb','format':'pdb'}},
            'design':{'chains':{'A':'AA'}, 'score':1.2, 'global_score':1.3,
                'coordinate_mask':{'A':[1.,1.]}, 'design_mask':{'A':[1.,1.]}}, 'tool':{'parameters':{},'actual_seed':7}}
        manifest = json.dumps({'objects':[obj], 'tool':{'id':'workbench.proteinmpnn.local','parameters':{}}}).encode()
        # Generic storage accepts the scientifically incomplete manifest.
        bad = upload(client, project, 'workbench.proteinmpnn_design', {'manifest.json':manifest})
        inputs = {'candidates':[bad['id']]}
        refused = interaction(client, project, 'workbench.filter', inputs, {'limit':0})
        assert refused.status_code == 400 and 'backbone' in refused.text, refused.text
        flow = {'nodes':[{'id':'filter','type':'workbench.filter','inputs':inputs,'parameters':{'limit':1}}], 'edges':[]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run = wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert run['nodes']['filter']['status'] == 'failed', run
        assert not run['nodes']['filter'].get('outputs'), run
        good = upload(client, project, 'workbench.proteinmpnn_design', {'manifest.json':manifest,'backbone.pdb':pdb()})
        flow['nodes'][0]['inputs']['candidates'] = [good['id']]
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run = wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert run['status'] == 'succeeded', run
        collection = run['nodes']['filter']['outputs']['collection'][0]
        assert interaction(client,project,'workbench.filter',{'candidates':[collection]}, {'limit':0}).status_code == 200
        saved = client.get(f'/api/packages/{collection}/file',params={'key':'manifest.json'}).json()
        mapped = saved['sources'][0]['files'].pop('backbone.pdb')
        # Its source map, rather than a similarly named unrelated file, owns access.
        files = {'manifest.json':json.dumps(saved).encode()}
        for key in saved['sources'][0]['files'].values():
            files[key] = client.get(f'/api/packages/{collection}/file',params={'key':key}).content
        files['backbone.pdb'] = pdb()
        malformed = upload(client,project,'workbench.collection',files)
        refused = interaction(client,project,'workbench.filter',{'candidates':[malformed['id']]},{'limit':0})
        assert refused.status_code == 400 and 'backbone' in refused.text, (mapped,refused.text)


def test_nested_saved_analysis_reference_view_resolves_selected_records_and_file_maps(tmp_path):
    app = create_application(data_root=tmp_path/'store')
    with TestClient(app) as client:
        project = client.post('/api/projects',json={'name':'Nested reference access'}).json()['id']
        files = {'subject.pdb':pdb(), 'reference.pdb':b'REMARK selected nested reference\n'+pdb()}
        document = {'subject':{'id':'subject','structure':{'file':'subject.pdb','format':'pdb'}},
            'reference':{'id':'reference','structure':{'file':'reference.pdb','format':'pdb'}}, 'method':'TM-align', 'region':None,
            'metrics':{'tm_reference':{'value':.8,'unit':'dimensionless','normalization':'reference length'}}}
        package = upload(client,project,'workbench.comparison',dict(files, **{'manifest.json':json.dumps(document).encode()}))
        flow = {'nodes':[
            {'id':'first','type':'workbench.analyze_metrics','inputs':{'metrics':[package['id']]},'parameters':{'selections':[{'input':0,'object':'subject','origin':'comparison','metric':'tm_reference'}]}},
            {'id':'second','type':'workbench.analyze_metrics','inputs':{},'parameters':{'selections':[{'input':0,'object':'subject','origin':'analysis','analysis':0,'metric':'tm_reference.mean'}]}}],
            'edges':[{'source':'first','source_port':'analysis','target':'second','target_port':'metrics'}]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        run = wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
        assert run['status'] == 'succeeded', run
        nested = run['nodes']['second']['outputs']['analysis'][0]
        inputs = {'candidates':[package['id']], 'evaluations':[nested]}
        response = interaction(client,project,'workbench.filter.inspect',inputs,{})
        assert response.status_code == 200, response.text
        choice = next(choice for choice in response.json()['data']['candidates'][0]['choices'] if choice['metric']=='tm_reference.mean.mean')
        access = choice['reference_access']
        assert 'key' in access, access
        actual = client.get(f'/api/packages/{nested}/file',params={'key':access['key']})
        assert actual.status_code == 200 and actual.content == files['reference.pdb']
        # Invalid current-package source cycles must produce an explicit view reason.
        saved = client.get(f'/api/packages/{nested}/file',params={'key':'manifest.json'}).json()
        saved['sources'] = [{'format':'workbench.metric_analysis','entry':'manifest.json','files':{'manifest.json':'manifest.json'}}]
        saved['analyses'][0]['selection'] = {'object':'subject','origin':'analysis','analysis':0,'metric':'tm_reference.mean'}
        circular = upload(client,project,'workbench.metric_analysis',{'manifest.json':json.dumps(saved).encode()})
        response = interaction(client,project,'workbench.filter.inspect',dict(inputs,evaluations=[circular['id']]),{})
        assert response.status_code == 200, response.text
        unavailable = response.json()['data']['candidates'][0]['choices'][0]['reference_access']['unavailable']
        assert 'cycle' in unavailable.lower(), unavailable
