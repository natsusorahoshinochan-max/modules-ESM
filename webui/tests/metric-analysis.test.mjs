import assert from 'node:assert/strict'
import {test, after} from 'node:test'
import {execFileSync} from 'node:child_process'
import * as React from 'react'
import {JSDOM} from 'jsdom'
const actual = JSON.parse(execFileSync(process.env.WORKBENCH_PYTHON || 'python3',['-c',`
import json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_metric_analysis import confidence_files
from tests.test_sequence_io import upload
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_application(data_root=Path(directory))) as client:
        record = next(m for m in client.get('/api/modules').json() if m['id']=='workbench.metric_analysis')
        source = client.get(record['ui_url']); source.raise_for_status()
        project = client.post('/api/projects',json={'name':'Actual metric input'}).json()['id']
        files = confidence_files()
        document = json.loads(files['manifest.json'])
        document['objects'][0]['id']='hidden-object-identity'
        document['evaluations'][0]['object_id']='hidden-object-identity'
        files['manifest.json']=json.dumps(document).encode()
        package = upload(client,project,'workbench.structure_confidence',files)
        response=client.post(f'/api/projects/{project}/interactions',json={'interaction':'workbench.inspect_metrics','inputs':{'metrics':[package['id']]},'parameters':{}})
        response.raise_for_status(); token=response.json()['id']
        response=client.post(f'/api/interactions/{token}/execute');response.raise_for_status()
        preview=response.json()
        files['scores.json']=json.dumps({'positions': __import__('tests.test_metric_analysis',fromlist=['POSITIONS']).POSITIONS,'plddt':[.2]}).encode()
        package=upload(client,project,'workbench.structure_confidence',files)
        started=client.post(f'/api/projects/{project}/interactions',json={'interaction':'workbench.inspect_metrics','inputs':{'metrics':[package['id']]},'parameters':{}})
        started.raise_for_status()
        bad=client.post('/api/interactions/'+started.json()['id']+'/execute');bad.raise_for_status()
        old_selector=preview['data']['choices'][0]['selector']
        flow={'nodes':[{'id':'analysis','type':'workbench.analyze_metrics','inputs':{'metrics':[package['id']]},'parameters':{'selections':[old_selector]}}],'edges':[]}
        client.put(f'/api/projects/{project}',json={'flow':flow,'layout':{}}).raise_for_status()
        document['objects'][0]['id']='replacement-object-private-id'
        document['evaluations'][0]['object_id']='replacement-object-private-id'
        files['manifest.json']=json.dumps(document).encode()
        replacement=upload(client,project,'workbench.structure_confidence',files)
        saved=client.get(f'/api/projects/{project}').json()
        saved['flow']['nodes'][0]['inputs']['metrics']=[replacement['id']]
        client.put(f'/api/projects/{project}',json={'flow':saved['flow'],'layout':saved['layout']}).raise_for_status()
        reopened=client.get(f'/api/projects/{project}').json()['flow']['nodes'][0]
        started=client.post(f'/api/projects/{project}/interactions',json={'interaction':'workbench.inspect_metrics','inputs':{'metrics':[replacement['id']]},'parameters':{}})
        started.raise_for_status()
        replaced=client.post('/api/interactions/'+started.json()['id']+'/execute');replaced.raise_for_status()
        print(json.dumps({'source':source.text,'preview':preview,'bad_preview':bad.json(),'replaced_preview':replaced.json(),'reopened':reopened}))
`],{cwd:new URL('../../',import.meta.url),encoding:'utf8'}))
const source = actual.source
const {register} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const dom = new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'})
Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true})
Object.defineProperty(globalThis,'navigator',{configurable:true,value:dom.window.navigator})
const {createRoot} = await import('react-dom/client')
after(()=>dom.window.close())
const extensions=register({React})
const positions=[{chain:'Z',author_number:12,insertion_code:''},{chain:'Z',author_number:12,insertion_code:'A'},{chain:'Z',author_number:19,insertion_code:''}]

test('saved selection absent after input replacement stays visible until explicitly removed',async()=>{
  const container=document.createElement('div');document.body.append(container)
  const root=createRoot(container),updates=[]
  const parameters=actual.reopened.parameters
  const scalar=actual.replaced_preview.data.choices.find(choice=>choice.selector.metric==='mean_plddt')
  assert.equal(parameters.selections[0].object,'hidden-object-identity')
  assert.notEqual(parameters.selections[0].object,scalar.selector.object)
  const context={projectId:'p',nodeId:'analysis',revision:1,parameters,bindings:actual.reopened.inputs,edges:[],
    inputs:{metrics:{packages:[{id:actual.reopened.inputs.metrics[0]}]}},
    host:{preview:async()=>actual.replaced_preview,cancelPreview:async()=>{}},update:async change=>updates.push(change)}
  try{
    await React.act(async()=>root.render(React.createElement(extensions.editors[0].component,{context,parameters,readOnly:false})))
    await React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Inspect existing metrics').click())
    await React.act(async()=>container.querySelector('[aria-label="Use metric 1"]').click())
    const apply=[...container.querySelectorAll('button')].find(button=>button.textContent==='Apply metric selections')
    assert.equal(apply.disabled,true)
    assert.match(container.textContent,/Saved metric selection.*mean_plddt/)
    assert.match(container.textContent,/not available in the current inspected inputs/)
    assert.doesNotMatch(container.textContent,/hidden-object-identity|replacement-object-private-id/)
    assert.deepEqual(updates,[])
    const remove=container.querySelector('[aria-label="Remove saved metric selection 1"]')
    assert.ok(remove,'unresolved saved selection needs an explicit recovery control')
    await React.act(async()=>remove.click())
    assert.equal(apply.disabled,false)
    await React.act(async()=>apply.click())
    assert.deepEqual(updates,[{parameters:{selections:[scalar.selector]}}])
    assert.equal(container.querySelector('[aria-label="Use metric 1"]').checked,true)
  }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('unavailable metric remains visible and removable while a valid scalar completes real analysis',async()=>{
  const container=document.createElement('div');document.body.append(container)
  const root=createRoot(container),updates=[]
  const choices=actual.bad_preview.data.choices
  const unavailable=choices.find(choice=>choice.unavailable)
  const scalar=choices.find(choice=>choice.selector.metric==='mean_plddt')
  const parameters={selections:[unavailable.selector]}
  const context={projectId:'p',nodeId:'n',revision:0,parameters,bindings:{},edges:[],inputs:{metrics:{packages:[{id:'input'}]}},
    host:{preview:async()=>actual.bad_preview,cancelPreview:async()=>{}},update:async change=>updates.push(change)}
  try{
    await React.act(async()=>root.render(React.createElement(extensions.editors[0].component,{context,parameters,readOnly:false})))
    await React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Inspect existing metrics').click())
    assert.match(container.textContent,/Unavailable:.*correspondence/)
    const bad=container.querySelector(`[aria-label="Use metric ${choices.indexOf(unavailable)+1}"]`)
    assert.equal(bad.checked,true);assert.equal(bad.disabled,false)
    const apply=[...container.querySelectorAll('button')].find(button=>button.textContent==='Apply metric selections')
    assert.equal(apply.disabled,true)
    await React.act(async()=>bad.click())
    assert.equal(bad.checked,false);assert.equal(bad.disabled,true)
    await React.act(async()=>container.querySelector(`[aria-label="Use metric ${choices.indexOf(scalar)+1}"]`).click())
    assert.equal(apply.disabled,false)
    await React.act(async()=>apply.click())
    assert.deepEqual(updates,[{parameters:{selections:[scalar.selector]}}])
    const saved=JSON.parse(execFileSync(process.env.WORKBENCH_PYTHON || 'python3',['-c',`
import json,sys,tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.test_metric_analysis import confidence_files,run_analysis
from modules.metric_analysis.formats import read_analysis
with tempfile.TemporaryDirectory() as directory:
 app=create_application(data_root=Path(directory))
 with TestClient(app) as client:
  project=client.post('/api/projects',json={'name':'Applied scalar'}).json()['id']
  files=confidence_files([.2]);document=json.loads(files['manifest.json'])
  document['objects'][0]['id']='hidden-object-identity';document['evaluations'][0]['object_id']='hidden-object-identity'
  files['manifest.json']=json.dumps(document).encode()
  package=upload(client,project,'workbench.structure_confidence',files)
  result=run_analysis(client,project,package,json.loads(sys.argv[1]));assert result['status']=='succeeded',result
  output=app.state.workbench.package(result['nodes']['analyze']['outputs']['analysis'][0])
  saved=read_analysis(output)
  with output.open(saved['sources'][0]['files']['scores.json']) as reader: assert reader.read()==files['scores.json']
  print(json.dumps(saved['analyses'][0]['input_values']))
`,JSON.stringify(updates[0].parameters.selections)],{cwd:new URL('../../',import.meta.url),encoding:'utf8'}))
    assert.deepEqual(saved,[.5])
  }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('actual metric editor selects existing values and discontinuous actual positions through generic inspect',async()=>{
  const container=document.createElement('div');document.body.append(container)
  const root=createRoot(container), requests=[],updates=[],cancelled=[]
  const selector={input:0,object:'hidden-object-identity',origin:'evaluation',evaluation:0,metric:'plddt'}
  const context={projectId:'p',nodeId:'n',revision:0,parameters:{},bindings:{metrics:['existing']},edges:[],
    inputs:{metrics:{packages:[{id:'existing'}]}},host:{
      preview:async(...args)=>{requests.push(args);return {...actual.preview,id:'inspect',data:{choices:actual.preview.data.choices.filter(choice=>choice.selector.metric==='plddt')}}},
      cancelPreview:async id=>cancelled.push(id)}, update:async change=>updates.push(change)}
  function Harness(){const [parameters,set]=React.useState({});return React.createElement(extensions.editors[0].component,{context,parameters,onChange:set,readOnly:false})}
  try{
    await React.act(async()=>root.render(React.createElement(Harness)))
    await React.act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Inspect existing metrics').click())
    assert.equal(requests[0][0],'workbench.inspect_metrics');assert.deepEqual(requests[0][1],{metrics:['existing']})
    assert.deepEqual(cancelled,['inspect'])
    assert.match(container.textContent,/Research structure/);assert.match(container.textContent,/No reference/)
    assert.doesNotMatch(container.textContent,/hidden-object-identity/)
    await React.act(async()=>container.querySelector('[aria-label="Use metric 1"]').click())
    await React.act(async()=>container.querySelector('[aria-label="Select individual positions 1"]').click())
    await React.act(async()=>{container.querySelector('[aria-label="Metric 1 position Z:12"]').click()})
    await React.act(async()=>{container.querySelector('[aria-label="Metric 1 position Z:19"]').click()})
    await React.act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Apply metric selections').click())
    assert.deepEqual(updates,[{parameters:{selections:[{...selector,region:[positions[0],positions[2]]}]}}])
    assert.equal(container.querySelector('textarea'),null)
  }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('metric inspection cannot display a response from a replaced node draft',async()=>{
  const container=document.createElement('div');document.body.append(container)
  const root=createRoot(container),cancelled=[]
  let release
  const gate=new Promise(resolve=>{release=resolve})
  const context={projectId:'first',nodeId:'n',revision:0,parameters:{},bindings:{},edges:[],inputs:{metrics:{packages:[{id:'first-input'}]}},
    host:{preview:async()=>{await gate;return {...actual.preview,id:'stale'}},cancelPreview:async id=>cancelled.push(id)},update:async()=>assert.fail('Stale inspection cannot modify a draft')}
  const Editor=extensions.editors[0].component
  try{
    await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:{},readOnly:false})))
    await React.act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Inspect existing metrics').click())
    await React.act(async()=>root.render(React.createElement(Editor,{context:{...context,projectId:'second',revision:1},parameters:{},readOnly:false})))
    await React.act(async()=>release())
    assert.doesNotMatch(container.textContent,/Research structure/)
    assert.deepEqual(cancelled,['stale'])
    assert.ok([...container.querySelectorAll('button')].find(b=>b.textContent==='Apply metric selections').disabled)
  }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('saved analysis viewer shows actual methods scopes values and unit without source lookup',async()=>{
  const container=document.createElement('div');document.body.append(container)
  const root=createRoot(container),reads=[]
  const savedDocument={analyses:[{object:{label:'Research structure'},reference:{label:'Independent reference'},metric:'plddt',
    source_method:'Existing independent evaluator',method:'arithmetic mean, minimum, maximum of existing values',unit:'fraction (0–1)',meaning:'Existing local confidence',
    region:[positions[1]],positions:[positions[1]],input_values:[.8],statistics:{count:1,mean:.8,minimum:.8,maximum:.8}}]}
  try{
    await React.act(async()=>root.render(React.createElement(extensions.viewers[0].component,{package:{id:'saved',format:'workbench.metric_analysis',entry:'manifest.json'},
      host:{readOnly:true,readFile:async(id,key)=>{reads.push([id,key]);return new Blob([JSON.stringify(savedDocument)])}}})))
    assert.match(container.textContent,/Independent reference/);assert.match(container.textContent,/Existing independent evaluator/)
    assert.match(container.textContent,/fraction \(0–1\)/);assert.match(container.textContent,/mean 0.8/)
    assert.match(container.textContent,/12/);assert.match(container.textContent,/insertion_code/)
    assert.deepEqual(reads,[['saved','manifest.json']])
  }finally{await React.act(async()=>root.unmount());container.remove()}
})
