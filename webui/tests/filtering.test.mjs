import assert from 'node:assert/strict'
import {test,after} from 'node:test'
import {readFile} from 'node:fs/promises'
import * as React from 'react'
import {JSDOM} from 'jsdom'
const source=await readFile(new URL('../../modules/filtering/ui.js',import.meta.url),'utf8')
const {register}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
const dom=new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/'})
Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true})
Object.defineProperty(globalThis,'navigator',{configurable:true,value:dom.window.navigator})
const {createRoot}=await import('react-dom/client')
after(()=>dom.window.close())
test('temporary result action explicitly selects multiple packages without flow edits',async()=>{
 const extension=register({React}),Action=extension.resultActions[0].component
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container)
 const calls=[],cancelled=[]
 const packages=[{id:'private-a',format:'workbench.structure_confidence'},{id:'private-b',format:'workbench.structure_confidence'}]
 const host={readOnly:false,preview:async(name,inputs,parameters)=>{calls.push({name,inputs,parameters});return {id:'preview',data:name.endsWith('inspect')?{candidates:[]}:{selected:[{input:1,item:0}]}}},cancelPreview:async id=>cancelled.push(id),addNode:()=>assert.fail('temporary filtering edited flow')}
 await React.act(async()=>root.render(React.createElement(Action,{host,packages})))
 for(const input of container.querySelectorAll('input[type=checkbox]'))await React.act(async()=>input.click())
 const button=[...container.querySelectorAll('button')].find(b=>b.textContent==='Apply temporary filter')
 assert.ok(button)
 await React.act(async()=>button.click())
 assert.deepEqual(calls.at(-1).inputs,{candidates:['private-a','private-b'],evaluations:['private-a','private-b']})
 assert.match(container.textContent,/Input 2 · Item 1/)
 assert.ok(!container.textContent.includes('private-a'))
 assert.deepEqual(cancelled,['preview'])
 await React.act(async()=>root.unmount());container.remove()
})
