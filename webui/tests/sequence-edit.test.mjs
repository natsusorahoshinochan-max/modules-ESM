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
const base={id:'edited-object',sequence:'AC',positions:[{id:'a',residue:'A',prompt:'A',fixed:true,coordinates:null},{id:'c',residue:'C',prompt:'_',fixed:false,coordinates:{CA:[1,2,3]}}],random_operations:[]}
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
