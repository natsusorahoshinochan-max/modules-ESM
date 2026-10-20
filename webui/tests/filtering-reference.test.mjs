import assert from 'node:assert/strict'
import {test,after} from 'node:test'
import {spawn} from 'node:child_process'
import {createInterface} from 'node:readline'
import {readFile} from 'node:fs/promises'
import * as React from 'react'
import {JSDOM} from 'jsdom'
const process=spawn('python3',['-m','tests.fixtures.filtering_reference'],{cwd:new URL('../../',import.meta.url),stdio:['pipe','pipe','inherit']})
const waiters=new Map();let counter=0,ready
const initial=new Promise(resolve=>ready=resolve)
createInterface({input:process.stdout}).on('line',line=>{const result=JSON.parse(line);if(!('id' in result))ready(result);else{const {resolve,reject}=waiters.get(result.id);waiters.delete(result.id);result.error?reject(new Error(result.error)):resolve(result.data)}})
const call=request=>new Promise((resolve,reject)=>{const id=counter++;waiters.set(id,{resolve,reject});process.stdin.write(JSON.stringify({...request,id})+'\n')})
const actual=await initial
const source=await readFile(new URL('../../modules/filtering/ui.js',import.meta.url),'utf8')
const {register}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
const dom=new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/'})
Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true})
Object.defineProperty(globalThis,'navigator',{configurable:true,value:dom.window.navigator})
const {createRoot}=await import('react-dom/client')
after(()=>{process.stdin.end();dom.window.close()})
let latest
const host={preview:(name,inputs,parameters)=>(latest=call({action:'preview',name,inputs,parameters})),cancelPreview:async()=>{},readFile:(packageId,key)=>(latest=call({action:'file',package:packageId,key}).then(text=>new Blob([text])))}
const button=(container,text)=>[...container.querySelectorAll('button')].find(button=>button.textContent===text)

test('actual inspection lets the registered editor identify and view the second anonymous reference before filtering',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const Editor=register({React}).editors[0].component
 let parameters={conditions:[{evaluation:{bindings:[]},operator:'ge',value:.5}]}
 const context={host,inputs:Object.fromEntries(Object.entries(actual.direct).map(([port,ids])=>[port,{packages:ids.map(id=>({id}))}]))}
 const render=()=>root.render(React.createElement(Editor,{context,parameters,onChange:next=>{parameters=next;render()},readOnly:false}))
 try{
  await React.act(async()=>render())
  await React.act(async()=>{button(container,'Inspect selected inputs').click();await latest})
  const select=container.querySelector('select')
  assert.match(select.options[1].textContent,/Evaluation input 1.*reference.pdb/)
  assert.match(select.options[2].textContent,/Evaluation input 2.*reference.pdb/)
  assert.ok(!container.textContent.includes('private-reference-'))
  await React.act(async()=>{select.value='1';select.dispatchEvent(new window.Event('change',{bubbles:true}))})
  assert.match(container.textContent,/normalization.*reference/)
  await React.act(async()=>{button(container,'View reference file').click();await latest})
  assert.match(container.textContent,/REMARK actual reference 2/)
  assert.equal(parameters.conditions[0].evaluation.bindings[0].evaluation.input,1)
  const result=await call({action:'run',inputs:actual.direct,parameters})
  assert.equal(result.manifest.items.length,1)
  assert.equal(result.manifest.items[0].object.id,'private-subject')
  assert.ok(Object.values(result.files).some(value=>value.startsWith('REMARK actual reference 2')))
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('mapped collection and saved analysis reference access follows exact maps in temporary Controls',async()=>{
 const extension=register({React}),Action=extension.resultActions[0].component
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 try{
  const archive={id:actual.archive,format:'workbench.filtered_collection'}
  await React.act(async()=>root.render(React.createElement(Action,{host,packages:[archive]})))
  for(const checkbox of [...container.querySelectorAll('input[type=checkbox]')].slice(0,2))await React.act(async()=>checkbox.click())
  await React.act(async()=>button(container,'Add condition').click())
  await React.act(async()=>{button(container,'Inspect selected inputs').click();await latest})
  const select=container.querySelector('select')
  assert.match(select.options[2].textContent,/source 3.*reference.pdb/)
  await React.act(async()=>{select.value='1';select.dispatchEvent(new window.Event('change',{bubbles:true}))})
  await React.act(async()=>{button(container,'View reference file').click();await latest})
  assert.match(container.textContent,/REMARK actual reference 2/)
  const threshold=container.querySelector('input[type=number]')
  await React.act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(threshold,'.5');threshold.dispatchEvent(new window.Event('input',{bubbles:true}));threshold.dispatchEvent(new window.Event('change',{bubbles:true}))})
  await React.act(async()=>{button(container,'Apply temporary filter').click();await latest})
  assert.match(container.textContent,/Input 1 · Item 1/)
  for(const id of [actual.analyzed,actual.analyzed_archive]){
   const inspected=await host.preview('workbench.filter.inspect',{candidates:actual.direct.candidates,evaluations:[id]}, {})
   const choice=inspected.data.candidates[0].choices.find(choice=>choice.metric==='tm_reference.mean')
   assert.ok(choice.reference_access.key)
   const blob=await host.readFile(id,choice.reference_access.key)
   assert.match(await blob.text(),/^REMARK actual reference 2/)
   assert.equal(choice.method.statistic,'mean')
   assert.equal(choice.method.source_method.name,'TM-align')
  }
 }finally{await React.act(async()=>root.unmount());container.remove()}
})

test('reference viewing stays read-only and discards completion after a different selected input or unmount',async()=>{
 const inspected=await host.preview('workbench.filter.inspect',actual.direct,{})
 const choices=inspected.data.candidates[0].choices
 const Editor=register({React}).editors[0].component,container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 let finish
 const controlled={...host,preview:async()=>inspected,readFile:()=>new Promise(resolve=>finish=resolve)}
 const context={host:controlled,inputs:Object.fromEntries(Object.entries(actual.direct).map(([port,ids])=>[port,{packages:ids.map(id=>({id}))}]))}
 const parameters=index=>({conditions:[{operator:'ge',value:.5,evaluation:{bindings:[{candidate:{input:0,item:0},evaluation:choices[index].evaluation}]}}]})
 const render=index=>root.render(React.createElement(Editor,{context,parameters:parameters(index),onChange:()=>assert.fail('view changed parameters'),readOnly:true}))
 await React.act(async()=>render(0))
 await React.act(async()=>button(container,'Inspect selected inputs').click())
 assert.equal(button(container,'View reference file').matches(':disabled'),false)
 assert.equal(container.querySelector('select').disabled,true)
 await React.act(async()=>button(container,'View reference file').click())
 await React.act(async()=>render(1))
 await React.act(async()=>finish(new Blob(['STALE FIRST REFERENCE'])))
 assert.ok(!container.textContent.includes('STALE FIRST'))
 await React.act(async()=>button(container,'View reference file').click())
 await React.act(async()=>root.unmount())
 await React.act(async()=>finish(new Blob(['STALE UNMOUNTED REFERENCE'])))
 assert.equal(container.textContent,'');container.remove()
})
