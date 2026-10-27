import test from 'node:test'
import {readFile} from 'node:fs/promises'
import assert from 'node:assert/strict'
import {pathToFileURL, fileURLToPath} from 'node:url'
import {JSDOM, VirtualConsole} from 'jsdom'
import React, {act} from 'react'
import {createRoot} from 'react-dom/client'
import {i18n,setLocale,text,initialLocale,loadExtensions,localizeCatalog,ParameterFields} from './helpers/language-runtime.mjs'

const dom=new JSDOM('<div id="app"></div>',{url:'http://localhost/',virtualConsole:new VirtualConsole()})
Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,localStorage:dom.window.localStorage,IS_REACT_ACT_ENVIRONMENT:true})
globalThis.ResizeObserver=class {observe(){} disconnect(){}}
window.HTMLElement.prototype.scrollIntoView=()=>{}
const root=createRoot(document.getElementById('app'))
const flush=()=>new Promise(resolve=>setImmediate(resolve))
const click=element=>act(async()=>{assert.ok(element);element.dispatchEvent(new window.MouseEvent('click',{bubbles:true}));await flush()})
const button=label=>[...document.querySelectorAll('button')].find(el=>el.textContent===label)
const cell=label=>document.querySelector(`[role="gridcell"][aria-label="${label}"]`)
async function event(element,type,options={}) { await act(async()=>{assert.ok(element);element.dispatchEvent(type.startsWith('key')?new window.KeyboardEvent(type,{bubbles:true,...options}):new window.MouseEvent(type,{bubbles:true,...options}));await flush()}) }
test.after(async()=>{await act(()=>root.unmount());dom.window.close()})

test('language follows browser initially, persists explicit choice, and resolves display text only',()=>{
 assert.equal(initialLocale({getItem:()=>null},'zh-TW'),'zh-CN')
 assert.equal(initialLocale({getItem:()=>null},'fr-FR'),'en')
 assert.equal(initialLocale({getItem:()=> 'en'},'zh-CN'),'en')
 assert.equal(initialLocale({getItem:()=>{throw Error('blocked')}},'zh-CN'),'zh-CN')
 setLocale('en');assert.equal(localStorage.getItem('workbench.language'),'en');assert.equal(document.documentElement.lang,'en')
 assert.equal(text({'zh-CN':'第 {n} 次运行',en:'Run {n}'},{n:3}),'Run 3')
 assert.equal(text('User project 中文'),'User project 中文')
 setLocale('zh-CN');assert.equal(text({en:'Third-party label'}),'Third-party label')
})

test('catalog labels change without mutating declarations, enum values or defaults',()=>{
 const raw={nodes:[{id:'predict',module_id:'folding',name:{'zh-CN':'预测结构',en:'Predict structure'},inputs:{sequence:{accepts:['workbench.sequence'],name:{'zh-CN':'序列',en:'Sequence'},cardinality:'one',required:true}},outputs:{},parameters:{mode:{enum:['fast'],enumLabels:{fast:{'zh-CN':'快速',en:'Fast'}},default:'fast'}}}],modules:[],tools:[]}
 const before=JSON.stringify(raw);setLocale('en');assert.equal(localizeCatalog(raw).nodes[0].name,'Predict structure')
 setLocale('zh-CN');assert.equal(localizeCatalog(raw).nodes[0].inputs.sequence.name,'序列')
 assert.equal(JSON.stringify(raw),before)
})

test('parameter labels translate while submitted values stay unchanged',async()=>{
 let updates=[];const schema={model:{title:{'zh-CN':'模型',en:'Model'},enum:['model_fast','model_full'],enumLabels:{model_fast:{'zh-CN':'快速',en:'Fast'},model_full:{'zh-CN':'完整',en:'Full'}}},seed:{title:{'zh-CN':'种子',en:'Seed'},type:'integer'}}
 function Fields(){i18n.useLocale();return React.createElement(ParameterFields,{schema,value:{model:'model_fast',seed:42},onChange:value=>updates.push(value),disabled:false})}
 setLocale('zh-CN');await act(()=>root.render(React.createElement(Fields)))
 const select=document.querySelector('select');assert.equal(select.value,'"model_fast"')
 await act(()=>setLocale('en'));assert.ok(document.body.textContent.includes('Model'));assert.equal(document.querySelector('select'),select);assert.equal(document.querySelector('input').value,'42');assert.deepEqual(updates,[])
 await act(()=>{select.value='"model_full"';select.dispatchEvent(new window.Event('change',{bubbles:true}))});assert.deepEqual(updates,[{model:'model_full',seed:42}])
})

test('Studio language switching retains edited rows, selection and undo without reloading the module',async()=>{
 await act(()=>setLocale('zh-CN'))
 const entry=pathToFileURL(fileURLToPath(new URL('../../modules/sequence_edit/ui.js',import.meta.url))).href
 const extensions=await loadExtensions([{id:'studio',name:'Protein Studio',enabled:true,installation_id:'one',ui_url:entry}])
 const Editor=extensions.editors[0].component;let previews=0,updates=0,closed=0
 const context={revision:1,inputs:{},document:{id:'existing'},host:{preview:async()=>{previews++;return{id:'preview',data:{document:{positions:[...'ACDE'].map((residue,i)=>({id:'r'+i,residue,coordinates:null,secondary_structure:null,sasa:null,function_annotations:[]}))}}}},cancelPreview:async()=>{}},update:async()=>{updates++}}
 await act(async()=>{root.render(React.createElement(Editor,{context,parameters:{},readOnly:false,onClose:()=>{closed++}}));await flush();await flush()})
 await event(cell('序列 2'),'pointerdown',{button:0});await event(cell('序列 2'),'pointerup',{button:0})
 await event(document.querySelector('[role="grid"]'),'keydown',{key:'-'});assert.equal(cell('序列 2').dataset.editState,'deleted')
 const row=cell('序列 2'),grid=document.querySelector('[role="grid"]');grid.scrollLeft=80
 await act(()=>setLocale('en'))
 assert.equal(cell('Sequence 2'),row);assert.equal(row.dataset.editState,'deleted');assert.equal(grid.scrollLeft,80)
 assert.ok(button('Done and return to canvas'));assert.equal(document.querySelectorAll('.language-picker').length,1)
 await event(grid,'keydown',{key:'z',ctrlKey:true});assert.equal(cell('Sequence 2').textContent,'C');assert.equal(cell('Sequence 2').dataset.editState,'normal')
 await event(grid,'keydown',{key:'g'});assert.equal(cell('Sequence 2').textContent,'G')
 await act(()=>setLocale('zh-CN'));assert.equal(cell('序列 2').textContent,'G');assert.equal(previews,1);assert.equal(updates,0)
 await click(button('取消编辑'));assert.equal(closed,1);assert.equal(updates,0)
})

test('local validation errors use authored translations and preserve original details',async()=>{
 const source=await readFile(new URL('../../modules/sequence_io/ui.js',import.meta.url),'utf8')
 const {parseSequence}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
 let error;try{parseSequence('123')}catch(value){error=value}
 await act(()=>setLocale('zh-CN'));assert.match(i18n.error(error),/氨基酸/)
 await act(()=>setLocale('en'));assert.match(i18n.error(error),/amino-acid/)
 const remote=new Error('Biohub original diagnostic');assert.equal(i18n.error(remote),'Biohub original diagnostic')
})
