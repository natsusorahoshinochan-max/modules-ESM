/** Project shapes accepted by HTTP must remain editable through the real App. */
import assert from 'node:assert/strict'
import {test} from 'node:test'
import {spawn} from 'node:child_process'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {createServer} from 'node:net'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'
import * as React from 'react'

test('actual HTTP project defaults remain editable through nested scopes, save and copy',{timeout:60000},async()=>{
 const repo=fileURLToPath(new URL('../../',import.meta.url)),originalFetch=globalThis.fetch
 const directory=await mkdtemp(join(tmpdir(),'project-defaults-')),buildDirectory=await mkdtemp(join(repo,'webui/.project-defaults-'))
 const probe=createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve))
 const backend=spawn(process.env.WORKBENCH_PYTHON||'python3',['-u','-c',`
import sys,uvicorn
from pathlib import Path
from core.host import Workbench
from protein_workbench_public.http.app import create_http_app
host=Workbench(Path(sys.argv[1]))
host.install('tests.fixtures.scope_module:source_module')
uvicorn.run(create_http_app(host),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
`,directory,String(port)],{cwd:repo,stdio:['ignore','pipe','pipe']})
 let diagnostics='',root,dom
 backend.stderr.on('data',value=>{diagnostics+=value.toString()})
 const base=`http://127.0.0.1:${port}`
 const json=async(path,body,method=body===undefined?'GET':'POST')=>{
  const response=await originalFetch(base+path,{method,headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
  assert.ok(response.ok,await response.clone().text());return response.json()
 }
 try{
  let ready=false
  for(let i=0;i<600;i++){try{await json('/api/projects');ready=true;break}catch{if(backend.exitCode!==null)break;await new Promise(resolve=>setTimeout(resolve,50))}}
  assert.ok(ready,diagnostics)
  const project=await json('/api/projects',{name:'Minimal HTTP project'})
  const preserved={explicit:{residues:[1,4,9],enabled:false}}
  const flow={nodes:[{id:'repeat',type:'host.repeat',scope:{rounds:1,body:{nodes:[{id:'leaf',type:'scope.source'}]},outputs:{result:{format:'scope.text'}},output_bindings:[{output:'result',node:'leaf',port:'result'}]}},{id:'configured',type:'scope.source',parameters:preserved}]}
  await json(`/api/projects/${project.id}`,{flow,layout:{}},'PUT')
  const raw=await json(`/api/projects/${project.id}`)
  assert.equal(Object.hasOwn(raw.flow.nodes[0],'parameters'),false)
  assert.equal(Object.hasOwn(raw.flow.nodes[0].scope.body.nodes[0],'inputs'),false)
  dom=new JSDOM('<!doctype html><html><body></body></html>',{url:base})
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true})
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:dom.window.navigator});window.confirm=()=>true
  globalThis.fetch=(url,options)=>originalFetch(new URL(String(url),base),options)
  const output=join(buildDirectory,'App.mjs')
  await build({entryPoints:[join(repo,'webui/src/App.tsx')],bundle:true,packages:'external',platform:'node',format:'esm',jsx:'automatic',outfile:output})
  const {default:App}=await import(pathToFileURL(output));const {createRoot}=await import('react-dom/client')
  const container=document.createElement('div');document.body.append(container);root=createRoot(container)
  const button=text=>[...container.querySelectorAll('button')].find(item=>item.textContent===text)
  const settle=async predicate=>{for(let i=0;i<200;i++){await React.act(async()=>new Promise(resolve=>setTimeout(resolve,15)));if(predicate())return}assert.fail(container.textContent)}
  const click=async text=>React.act(async()=>{assert.ok(button(text),text);button(text).click()})
  await React.act(async()=>root.render(React.createElement(App)))
  await settle(()=>button('Minimal HTTP project'))
  await click('Minimal HTTP project');await settle(()=>container.querySelector('.toolbar h2')?.textContent==='Minimal HTTP project')
  await click('Open subflow')
  assert.equal(container.querySelector('.canvas article textarea').value,'{}')
  assert.equal(container.querySelectorAll('.scope-navigation button').length,2)
  await click('Save project');await settle(()=>container.textContent.includes('Project and layout saved'))
  const saved=await json(`/api/projects/${project.id}`),scope=saved.flow.nodes[0].scope
  assert.deepEqual(saved.flow.edges,[]);assert.deepEqual(saved.flow.nodes[0].parameters,{})
  assert.deepEqual(scope.inputs,{});assert.deepEqual(scope.input_bindings,[]);assert.deepEqual(scope.body.edges,[])
  assert.deepEqual(scope.body.nodes[0].inputs,{});assert.deepEqual(scope.body.nodes[0].parameters,{})
  assert.equal(scope.outputs.result.cardinality,'one');assert.deepEqual(saved.flow.nodes[1].parameters,preserved)
  await click('Copy project');await settle(()=>container.querySelector('.toolbar h2')?.textContent==='Research project')
  await click('Open subflow');assert.equal(container.querySelector('.canvas article textarea').value,'{}')
 }finally{
  if(root)await React.act(async()=>root.unmount())
  globalThis.fetch=originalFetch;dom?.window.close();backend.kill('SIGTERM')
  if(backend.exitCode===null)await new Promise(resolve=>backend.once('exit',resolve))
  await rm(directory,{recursive:true,force:true});await rm(buildDirectory,{recursive:true,force:true})
 }
})
