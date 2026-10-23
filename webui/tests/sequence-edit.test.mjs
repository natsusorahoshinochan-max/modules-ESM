import assert from 'node:assert/strict'
import {after,test} from 'node:test'
import {JSDOM} from 'jsdom'
import * as React from 'react'
import {execFileSync} from 'node:child_process'
const source = execFileSync(process.env.WORKBENCH_PYTHON || 'python3', ['-c', `
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_application(data_root=Path(directory))) as client:
        record = next(item for item in client.get('/api/modules').json() if item['id'] == 'workbench.sequence_edit')
        response = client.get(record['ui_url'])
        response.raise_for_status()
        print(response.text, end='')
`], {cwd:new URL('../../',import.meta.url),encoding:'utf8'})
const {register} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const dom = new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/'})
Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true})
Object.defineProperty(globalThis,'navigator',{configurable:true,value:dom.window.navigator})
const {createRoot}=await import('react-dom/client')
const Editor=register({React}).editors[0].component
after(()=>dom.window.close())
const base={id:'edited-object',sequence:'AC',positions:[{id:'a',residue:'A',prompt:'A',fixed:true,coordinates:null},{id:'c',residue:'C',prompt:'_',fixed:false,coordinates:null}],random_operations:[]}
const random={...base,sequence:'A_C',positions:[base.positions[0],{id:'inserted',residue:'_',prompt:'_',fixed:false,coordinates:null},base.positions[1]],random_operations:[{seed:0,count:1,start:0,end:0,actual:[{position:'inserted',residue:'_',index:1,gap:1}]}]}

test('real module UI confirms actual preview once, cancels fully and undoes through public target update',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const calls=[],updates=[],cancelled=[]
 const context={projectId:'project',nodeId:'edit',parameters:{sequence:'AC'},bindings:{},edges:[{source:'upstream',source_port:'result',target:'edit',target_port:'source'}],inputs:{source:{packages:[],unavailable:'Select a delivered input explicitly'}},
   host:{async preview(id,inputs,parameters){calls.push({id,inputs,parameters});return {id:`preview-${calls.length}`,data:{document:parameters.operation?random:base},outputs:['edited']}},async cancelPreview(id){cancelled.push(id)}},async update(value){updates.push(value)}}
 const click=async text=>{const button=[...container.querySelectorAll('button')].find(button=>button.textContent===text);assert.ok(button,text);await React.act(async()=>button.click())}
 try {
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await click('Load current sequence')
  assert.deepEqual(cancelled,['preview-1']);assert.equal(updates.length,0)
  await click('Preview random insertion')
  assert.equal(calls.at(-1).parameters.operation.seed,0)
  assert.equal(calls.at(-1).parameters.document.sequence,'AC')
  assert.match(container.textContent,/A_C/)
  await click('Cancel preview')
  assert.equal(updates.length,0);assert.match(container.textContent,/Sequence: AC/)
  await click('Preview random insertion');const callCount=calls.length
  await click('Confirm edit and replace source input')
  assert.equal(calls.length,callCount)
  assert.deepEqual(updates[0],{parameters:{},delivery:{interaction:'preview-3',output:'edited',port:'source'},replaceConnections:['source']})
  assert.match(container.textContent,/Sequence: A_C/)
  assert.match(container.textContent,/Accepted random operations \(read only\)/)
  await click('Undo accepted edit')
  assert.deepEqual(updates[1],{parameters:context.parameters,inputs:{source:[]},replaceConnections:['source'],connections:context.edges})
  assert.equal(calls.length,callCount);assert.match(container.textContent,/Sequence: AC/)
 } finally {await React.act(async()=>root.unmount());container.remove()}
})

test('cancelled late preview cannot replace current content and is released',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 let resolve;const cancelled=[]
 const context={projectId:'p',nodeId:'n',parameters:{sequence:'AC'},bindings:{},edges:[],inputs:{},host:{preview:()=>new Promise(done=>{resolve=done}),async cancelPreview(id){cancelled.push(id)}},async update(){assert.fail('Cancelled preview must not update a node')}}
 const click=async text=>React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent===text).click())
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await click('Load current sequence');await click('Cancel pending preview')
  await React.act(async()=>resolve({id:'late',data:{document:random},outputs:['edited']}))
  assert.deepEqual(cancelled,['late']);assert.doesNotMatch(container.textContent,/Sequence: A_C/)
  assert.ok([...container.querySelectorAll('button')].some(button=>button.textContent==='Load current sequence'))
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('a changed host draft discards old module content and its preview',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container),cancelled=[]
 const context={projectId:'p',nodeId:'n',revision:0,parameters:{sequence:'AC'},bindings:{},edges:[],inputs:{},host:{async preview(){return{id:'preview',data:{document:base},outputs:['edited']}},async cancelPreview(id){cancelled.push(id)}},async update(){assert.fail('Stale module content must not be accepted')}}
 const click=async text=>React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent===text).click())
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await click('Load current sequence');await click('Preview current content')
  await React.act(async()=>root.render(React.createElement(Editor,{context:{...context,revision:1,parameters:{sequence:'WW'}},parameters:{sequence:'WW'},readOnly:false})))
  assert.match(container.textContent,/Node draft changed/)
  assert.equal([...container.querySelectorAll('button')].some(button=>button.textContent==='Confirm edit and replace source input'),false)
  assert.equal(cancelled.length,2)
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('StrictMode sequence editor loads its live draft and releases a late unmounted preview',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const cancelled=[];let resolve,signal
 const context={projectId:'p',nodeId:'n',revision:0,parameters:{sequence:'AC'},bindings:{},edges:[],inputs:{},host:{
   async preview(id,inputs,parameters,options){
     if(!parameters.document)return{id:'load',data:{document:base},outputs:['edited']}
     signal=options.signal
     return new Promise(done=>{resolve=done})
   },async cancelPreview(id){cancelled.push(id)}},async update(){assert.fail('Unmounted preview must not update a node')}}
 const button=text=>[...container.querySelectorAll('button')].find(button=>button.textContent===text)
 let unmounted=false
 try{
  await React.act(async()=>root.render(React.createElement(React.StrictMode,null,React.createElement(Editor,{context,parameters:context.parameters,readOnly:false}))))
  await React.act(async()=>button('Load current sequence').click())
  assert.match(container.textContent,/Sequence: AC/)
  assert.equal(button('Preview current content').disabled,false)
  await React.act(async()=>button('Preview current content').click())
  await React.act(async()=>root.unmount());unmounted=true
  assert.equal(signal.aborted,true)
  await React.act(async()=>resolve({id:'late-unmounted',data:{document:random},outputs:['edited']}))
  assert.deepEqual(cancelled,['load','late-unmounted'])
  assert.equal(container.textContent,'')
 }finally{if(!unmounted)await React.act(async()=>root.unmount());container.remove()}
})

test('a project switch during temporary file reading cannot display the prior project draft',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 let resolve;const cancelled=[]
 const context={projectId:'old',nodeId:'n',revision:0,parameters:{sequence:'AC'},bindings:{},edges:[],inputs:{},host:{
  async preview(){return{id:'file-preview',data:{document_file:'edited.json'},outputs:['edited']}},
  readPreviewFile(){return new Promise(done=>{resolve=done})},async cancelPreview(id){cancelled.push(id)}},async update(){assert.fail('Stale project update')}}
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Load current sequence').click())
  await React.act(async()=>root.render(React.createElement(Editor,{context:{...context,projectId:'new'},parameters:context.parameters,readOnly:false})))
  await React.act(async()=>resolve(new Blob([JSON.stringify(base)])))
  assert.doesNotMatch(container.textContent,/Sequence: AC/)
  assert.ok(cancelled.includes('file-preview'))
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('cancel owns the preview token and aborts its file phase before download completion',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 let finish,signal;const cancelled=[]
 const context={projectId:'p',nodeId:'n',revision:0,parameters:{sequence:'A'},bindings:{},edges:[],inputs:{},host:{
  async preview(){return{id:'file-token',data:{document_file:'edited.json'},outputs:['edited']}},
  readPreviewFile(id,output,key,options){signal=options?.signal;return new Promise(resolve=>{finish=resolve})},
  async cancelPreview(id){cancelled.push(id)}},async update(){assert.fail('Cancelled files cannot be accepted')}}
 const click=async name=>React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent===name).click())
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await click('Load current sequence');await click('Cancel pending preview')
  assert.deepEqual(cancelled,['file-token'])
  assert.equal(signal.aborted,true)
  await React.act(async()=>finish(new Blob([JSON.stringify(base)])))
  assert.deepEqual(cancelled,['file-token'])
  assert.doesNotMatch(container.textContent,/Sequence: AC/)
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('global coordinate frame fits full geometry and CSS-scaled dragging keeps a fixed inverse',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const documentValue={...base,positions:[{...base.positions[0],coordinates:{CA:[100,20,30]}},{...base.positions[1],coordinates:{CA:[110,23,33]}}]}
 const geometry=[{index:0,model:1,chain:'Z',author_number:1,insertion_code:'',residue_name:'ZN',position:[95,18,28]}]
 const calls=[];let finish
 const context={projectId:'p',nodeId:'n',revision:0,parameters:{},bindings:{source:['accepted']},edges:[],inputs:{source:{packages:[{id:'accepted',format:'workbench.sequence_conditions'}]}},host:{
  async preview(id,inputs,parameters){calls.push({id,inputs,parameters});if(parameters.operation)return new Promise(resolve=>{finish=resolve});return{id:'load',data:{document_file:'edited.json',view_file:'view.json'},outputs:['edited']}},
  async readPreviewFile(id,output,key){return new Blob([JSON.stringify(key==='view.json'?geometry:documentValue)])},async cancelPreview(){}},async update(){}}
 const click=async text=>React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent===text).click())
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await click('Load current sequence')
  let svg=container.querySelector('svg')
  for(const circle of svg.querySelectorAll('circle')){
   const x=Number(circle.getAttribute('cx')),y=Number(circle.getAttribute('cy'))
   assert.ok(x>=0&&x<=420&&y>=0&&y<=300,`visible geometry: ${x},${y}`)
  }
  // The supplied matrix is the public SVG layout boundary; a real-browser check
  // additionally verifies its native CSS/viewBox matrix rather than this fixture.
  await React.act(async()=>container.querySelector('[aria-label="Select position 1"]').click())
  svg=container.querySelector('svg')
  svg.getScreenCTM=()=>({inverse:()=>({a:.5,b:0,c:0,d:.5,e:-10,f:-20})})
  const atom=()=>svg.querySelector('[data-condition-atom="a:CA"]')
  const before=Number(atom().getAttribute('cx')),sourceBefore=svg.querySelector('circle').getAttribute('cx')
  const pointer=async(type,x,y)=>React.act(async()=>{const event=new window.Event(type,{bubbles:true});Object.assign(event,{clientX:x,clientY:y,pointerId:1});svg.dispatchEvent(event)})
  await pointer('pointerdown',100,100)
  assert.equal(container.querySelector('[role=alert]'),null,container.textContent)
  await pointer('pointermove',180,100)
  assert.equal(Number(atom().getAttribute('cx')),before+40)
  assert.equal(svg.querySelector('circle').getAttribute('cx'),sourceBefore)
  await pointer('pointerup',180,100)
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1].parameters)),{operation:{kind:'transform_coordinates',positions:['a'],rotation:[[1,0,0],[0,1,0],[0,0,1]],translation:[4,0,0]}})
  await click('Cancel pending preview')
  assert.equal(Number(atom().getAttribute('cx')),before)
  await React.act(async()=>finish({id:'stale-drag',data:{document:documentValue},outputs:['edited']}))
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('a selected structure establishes and previews a template without per-position mapping',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const calls=[],updates=[]
 const current={...base,structures:[{id:'retained',object:'structure'}]}
 const context={projectId:'p',nodeId:'edit',revision:0,parameters:{selection:{chains:['X']},regions:'12A,30'},bindings:{source:['structure-input']},edges:[],inputs:{source:{packages:[{id:'structure-input',format:'workbench.structure_set'}]}},host:{
  async preview(id,inputs,parameters){calls.push({id,inputs,parameters});return{id:'structure-preview',data:{document:current},outputs:['edited']}},async cancelPreview(){}},async update(change){updates.push(change)}}
 const click=async text=>React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent===text).click())
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters:context.parameters,readOnly:false})))
  await click('Preview template from structure')
  assert.deepEqual(calls[0],{id:'workbench.sequence_edit',inputs:{source:['structure-input']},parameters:{selection:{chains:['X']},regions:'12A,30',tracks:['fixed','coordinates']}})
  assert.match(container.textContent,/Sequence: AC/)
  assert.equal(container.querySelectorAll('tbody tr').length,2)
  assert.equal(updates.length,0)
  await click('Confirm edit and replace source input')
  assert.deepEqual(updates[0].delivery,{interaction:'structure-preview',output:'edited',port:'source'})
  assert.equal(container.querySelector('[role=alert]'),null)
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('reusable template configuration preserves the incoming connection and stores current-position rules',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container),updates=[]
 const parameters={selection:{chains:['X']},regions:'12A,30',operations:[{kind:'insert',index:1,sequence:'__'},{kind:'delete',indices:[3]}],template_conditions:{fixed_positions:[1],coordinate_positions:[1],atoms:['CA']}}
 const context={projectId:'p',nodeId:'edit',revision:0,parameters,bindings:{},edges:[{source:'upstream',source_port:'structures',target:'edit',target_port:'source'}],inputs:{source:{packages:[],unavailable:'Input will be delivered by the connected node'}},host:{async cancelPreview(){}},async update(change){updates.push(change)}}
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters,readOnly:false})))
  await React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Save reusable template configuration').click())
  assert.deepEqual(updates,[{parameters:{...parameters,tracks:[]}}])
  assert.equal(container.querySelector('[role=alert]'),null)
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('recipe object selection initializes from the node and follows external draft changes',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container),updates=[]
 const parameters={object:'chosen-first',selection:{chains:['X']},regions:'12A',operations:[],template_conditions:{fixed_positions:[1],coordinate_positions:[]}}
 const context={projectId:'p',nodeId:'edit',revision:0,parameters,bindings:{source:['batch']},edges:[],inputs:{source:{packages:[{id:'batch',format:'workbench.structure_set'}]}},host:{async cancelPreview(){}},async update(change){updates.push(change)}}
 const save=async()=>React.act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Save reusable template configuration').click())
 try{
  await React.act(async()=>root.render(React.createElement(Editor,{context,parameters,readOnly:false})))
  await save()
  assert.equal(updates[0].parameters.object,'chosen-first')
  const changed={...parameters,object:'chosen-second',selection:{chains:['Y']},regions:'30',operations:[{kind:'insert',index:1,sequence:'_'}],template_conditions:{fixed_positions:[2],coordinate_positions:[2],atoms:['CA']}}
  await React.act(async()=>root.render(React.createElement(Editor,{context:{...context,revision:1,parameters:changed},parameters:changed,readOnly:false})))
  await save()
  assert.deepEqual(updates[1],{parameters:{...changed,tracks:[]}})
 }finally{await React.act(async()=>root.unmount());container.remove()}
})
