"""Public HTTP fixture for the registered filtering UI; JSON-lines transport only."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.test_filtering import interaction
from tests.run_helpers import wait_response
from tests.test_comparison import pdb

with TemporaryDirectory() as directory:
    app = create_application(data_root=Path(directory))
    with TestClient(app) as client:
        project = client.post('/api/projects',json={'name':'Anonymous references'}).json()['id']
        candidate = upload(client,project,'workbench.structure_set',{'manifest.json':json.dumps({'objects':[{'id':'private-subject','label':'Actual candidate','structure':{'file':'subject.pdb','format':'pdb'}}]}).encode(),'subject.pdb':pdb()})
        evaluations = []
        for index, value in enumerate((.2,.8)):
            document = {'subject':{'id':'private-subject','structure':{'file':'subject.pdb','format':'pdb'}},
                'reference':{'id':f'private-reference-{index}','structure':{'file':'reference.pdb','format':'pdb'}},
                'region':{'subject':None,'reference':{'chain':'X'}},
                'method':{'name':'TM-align','tmtools':'0.3.0','algorithm':'20210224','parameters':{'normalization':'reference'}},
                'metrics':{'tm_reference':{'value':value,'unit':'dimensionless','normalization':'reference length'}}}
            evaluations.append(upload(client,project,'workbench.comparison',{'manifest.json':json.dumps(document).encode(),'subject.pdb':pdb(),'reference.pdb':f'REMARK actual reference {index+1}\n'.encode()+pdb()}))
        direct = {'candidates':[candidate['id']],'evaluations':[pkg['id'] for pkg in evaluations]}
        def run(nodes, edges=()):
            client.put(f'/api/projects/{project}',json={'flow':{'nodes':nodes,'edges':list(edges)},'layout':{}}).raise_for_status()
            result = wait_response(client,client.post(f'/api/projects/{project}/runs')).json()
            assert result['status']=='succeeded', result
            return result
        first = run([{'id':'archive','type':'workbench.filter','inputs':direct,'parameters':{}}])
        archive = first['nodes']['archive']['outputs']['collection'][0]
        analysis = run([{'id':'analysis','type':'workbench.analyze_metrics','inputs':{'metrics':[evaluations[1]['id']]},'parameters':{'selections':[{'input':0,'object':'private-subject','origin':'comparison','metric':'tm_reference'}]}}])
        analyzed = analysis['nodes']['analysis']['outputs']['analysis'][0]
        second = run([{'id':'archive','type':'workbench.filter','inputs':{'candidates':[candidate['id']],'evaluations':[analyzed]},'parameters':{}}])
        analyzed_archive = second['nodes']['archive']['outputs']['collection'][0]
        print(json.dumps({'project':project,'direct':direct,'archive':archive,'analyzed':analyzed,'analyzed_archive':analyzed_archive}),flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            try:
                if request['action']=='preview':
                    response=interaction(client,project,request['name'],request['inputs'],request['parameters'])
                    if response.status_code != 200:
                        raise ValueError(response.text)
                    data=response.json()
                elif request['action']=='file':
                    response=client.get('/api/packages/'+request['package']+'/file',params={'key':request['key']})
                    response.raise_for_status()
                    data=response.text
                elif request['action']=='run':
                    result=run([{'id':'filter','type':'workbench.filter','inputs':request['inputs'],'parameters':request['parameters']}])
                    output=result['nodes']['filter']['outputs']['collection'][0]
                    package=app.state.workbench.package(output)
                    with package.open(package.entry) as reader:
                        manifest=json.load(reader)
                    contents={key:client.get('/api/packages/'+output+'/file',params={'key':key}).text for key in package.files}
                    data={'manifest':manifest,'files':contents}
                elif request['action']=='new_candidate':
                    # A later invocation can change its object and explicitly supplied reference.
                    next_document = json.loads(json.dumps(document))
                    next_document['subject']['id'] = 'next-round-subject'
                    if 'reference_id' in request:
                        next_document['reference']['id'] = request['reference_id']
                    next_candidate = upload(client, project, 'workbench.structure_set', {
                        'manifest.json': json.dumps({'objects': [next_document['subject']]}).encode(),
                        'subject.pdb': pdb(),
                    })
                    next_evaluation = upload(client, project, 'workbench.comparison', {
                        'manifest.json': json.dumps(next_document).encode(),
                        'subject.pdb': pdb(), 'reference.pdb': b'REMARK actual reference 2\n' + pdb(),
                    })
                    data = {'candidates': [next_candidate['id']], 'evaluations': [next_evaluation['id']]}
                else:
                    raise ValueError('Unknown fixture command')
                print(json.dumps({'id':request['id'],'data':data}),flush=True)
            except Exception as error:
                print(json.dumps({'id':request['id'],'error':str(error)}),flush=True)
