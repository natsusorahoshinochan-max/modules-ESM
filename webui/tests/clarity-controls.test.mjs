import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { build } from 'esbuild'
import { JSDOM } from 'jsdom'
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'

const temporary = await mkdtemp(fileURLToPath(new URL('../node_modules/.clarity-', import.meta.url)))
await build({entryPoints:[fileURLToPath(new URL('../src/ParameterFields.tsx',import.meta.url))],bundle:true,format:'esm',jsx:'automatic',external:['react','react/jsx-runtime'],outfile:temporary+'/fields.mjs'})
const {ParameterFields,parameterFields}=await import(pathToFileURL(temporary+'/fields.mjs'))
const dom=new JSDOM('<div id="app"></div>',{url:'http://localhost/'})
globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.HTMLElement=dom.window.HTMLElement;globalThis.IS_REACT_ACT_ENVIRONMENT=true
const root=createRoot(document.getElementById('app'))
test.after(async()=>{await act(()=>root.unmount());dom.window.close();await rm(temporary,{recursive:true,force:true})})

test('provider optional fields remain editable and declared types retain numeric values',async()=>{
 const fields=parameterFields({defaults:{seed:null,sampling_temp:[0.1]},seed:{type:'integer',title:'种子'},msa:{type:'object',properties:{sequences:{type:'array',items:{type:'string'}}}}})
 assert.ok(fields.msa)
 let changed
 await act(()=>root.render(React.createElement(ParameterFields,{schema:fields,value:{},disabled:false,onChange:next=>{changed=next}})))
 assert.equal(document.querySelector('input[type=number]').value,'')
 const group=[...document.querySelectorAll('details')].find(el=>el.querySelector('summary')?.textContent.includes('sampling temp'))
 await act(()=>[...group.querySelectorAll('button')].find(el=>el.textContent==='添加').click())
 assert.deepEqual(changed.sampling_temp,[0.1,0])
 assert.equal(document.querySelector('textarea'),null)
})

test('filter score selection preserves reference mode and uses measured metadata',async()=>{
 const source=await readFile(new URL('../../modules/filtering/ui.js',import.meta.url),'utf8')
 await writeFile(temporary+'/filter.mjs',source)
 const {register}=await import(pathToFileURL(temporary+'/filter.mjs'))
 const Editor=register({React}).editors[0].component
 let parameters={sort:{evaluation:{metric:'tm_reference',method:{name:'TM-align'},region:null,reference_mode:'provided_evaluations'},direction:'descending'},limit:2}
 const method={name:'TM-align'}
 const choice={evaluation:{input:0,evaluation:0},metric:'rmsd',method,region:null,reference:{id:'reference'},reference_display:{label:'1PGA'}}
 const host={preview:async()=>({id:'preview',data:{candidates:[{input:0,item:0,label:'candidate',choices:[choice]}]}}),cancelPreview:async()=>{}}
 const props={context:{host,inputs:{candidates:{packages:[{id:'candidate'}]},evaluations:{packages:[{id:'score'}]}}},parameters,readOnly:false,onChange:next=>{parameters=next}}
 await act(()=>root.render(React.createElement(Editor,props)))
 await act(async()=>[...document.querySelectorAll('button')].find(el=>el.textContent==='读取分数').click())
 const select=document.querySelector('select[aria-label="Sort 分数"]')
 await act(()=>{select.value='0';select.dispatchEvent(new window.Event('change',{bubbles:true}))})
 assert.equal(parameters.sort.evaluation.metric,'rmsd')
 assert.deepEqual(parameters.sort.evaluation.method,method)
 assert.equal(parameters.sort.evaluation.reference_mode,'provided_evaluations')
 assert.equal(Object.hasOwn(parameters.sort.evaluation,'reference'),false)
 assert.equal(parameters.limit,2)
 assert.equal(document.querySelector('textarea'),null)
})

test('operation editor exposes coordinates and object names without internal object ids',async()=>{
 const source=await readFile(new URL('../../modules/structure_io/ui.js',import.meta.url),'utf8')
 await writeFile(temporary+'/structure.mjs',source)
 const {register}=await import(pathToFileURL(temporary+'/structure.mjs'))
 const Editor=register({React}).editors.find(item=>item.node==='workbench.transform_structure').component
 await act(()=>root.render(React.createElement(Editor,{context:{inputs:{structures:{packages:[]}},host:{}},parameters:{object:'internal-object-id'},onChange:()=>{},readOnly:false})))
 assert.equal(document.querySelectorAll('input[aria-label^="旋转矩阵"]').length,9)
 assert.equal(document.body.textContent.includes('internal-object-id'),false)
 assert.equal(document.querySelector('textarea'),null)
})
