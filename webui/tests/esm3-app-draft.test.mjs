/** Actual App, served ESM3 editor and persisted HTTP save/run. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { registerHooks } from 'node:module';
import { createServer } from 'node:net';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import * as React from 'react';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const originalFetch = globalThis.fetch;


test('161 invalid conditions text actual App running boundary', { timeout: 60000 }, async () => {
  const dataRoot = await mkdtemp(join(tmpdir(), 'esm3-draft-store-'));
  const buildRoot = await mkdtemp(join(repo, 'webui/.esm3-draft-app-'));
  const portProbe = createServer(); await new Promise(resolve => portProbe.listen(0, '127.0.0.1', resolve));
  const port = portProbe.address().port; await new Promise(resolve => portProbe.close(resolve));
  const backend = spawn(process.env.WORKBENCH_PYTHON || 'python3', ['-u', '-c', `
import json,sys,uuid,uvicorn
from pathlib import Path
from protein_workbench_public.bootstrap import create_application
from modules.generation.contract import GenerateResult
import tests.fixtures.esm3_tool as provider
def create(settings):
 def generate(request,parameters,runtime):
  filename='external-'+uuid.uuid4().hex+'.json'
  tracks={'sequence':'A','secondary_structure':request.tracks['secondary_structure']}
  (runtime.workdir/filename).write_text(json.dumps({'tracks':tracks,'metrics':{}}))
  return GenerateResult(tracks,filename,parameters)
 return generate
provider.create=create
app=create_application(data_root=Path(sys.argv[1]))
app.state.workbench.install('tests.fixtures.esm3_tool:module')
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
`, dataRoot, String(port)], { cwd: repo, stdio: ['ignore', 'pipe', 'pipe'] });
  let diagnostics = ''; backend.stderr.on('data', value => { diagnostics += value.toString(); });
  const base = `http://127.0.0.1:${port}`;
  const json = async (path, options = {}) => { const response = await originalFetch(base + path, options); assert.ok(response.ok, await response.clone().text()); return response.json(); };
  const post = (path, body) => json(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let root, dom, hooks;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 600; attempt++) {
      try { await json('/api/projects'); ready = true; break; } catch { if (backend.exitCode !== null) break; await new Promise(resolve => setTimeout(resolve, 50)); }
    }
    assert.ok(ready, diagnostics);
    const project = await post('/api/projects', { name: '161 invalid conditions proof' });
    await post('/api/projects', {name:'161 destination'});
    async function upload(format, files) {
      const upload = await post(`/api/projects/${project.id}/uploads`, {});
      const path = `/api/projects/${project.id}/uploads/${upload.upload_id}`;
      for (const [key, content] of Object.entries(files)) {
        const response = await originalFetch(base + path + '/files?key=' + encodeURIComponent(key), { method: 'PUT', body: content });
        assert.ok(response.ok, await response.text());
      }
      return post(path + '/commit', { format, entry: 'manifest.json', files: Object.fromEntries(Object.keys(files).map(key => [key, key])) });
    }
    const sequence = await upload('workbench.sequence', {'manifest.json':JSON.stringify({objects:[{id:'s',sequence:'A'}]})});
    const originalConditions={secondary_structure:'H'};
    await json(`/api/projects/${project.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({flow:{nodes:[{id:'generate',type:'workbench.complete_sequence',inputs:{source:[sequence.id]},parameters:{conditions:originalConditions},tools:{esm3:'lab.esm3'}}],edges:[]},layout:{}})});
    const catalog = await json('/api/catalog');
    const uiFiles = new Map(await Promise.all(catalog.modules.filter(module => module.ui_url).map(async module => {
      const response = await originalFetch(base + module.ui_url); assert.ok(response.ok);
      return [module.ui_url.split('?')[0], `data:text/javascript;base64,${Buffer.from(await response.text()).toString('base64')}`];
    })));
    hooks = registerHooks({ resolve(specifier, context, nextResolve) { const path = specifier.split('?')[0]; if (uiFiles.has(path)) return { url: uiFiles.get(path), shortCircuit: true }; return nextResolve(specifier, context); } });
    dom = new JSDOM('<!doctype html><html><body></body></html>', { url: base });
    Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
    window.confirm = () => true;
    const runRequests = [], projectReads = [];
    globalThis.fetch = (url, options) => { if (String(url)===`/api/projects/${project.id}/runs` && options?.method==='POST') runRequests.push(url); if(String(url)===`/api/projects/${project.id}/runs` && (!options?.method||options.method==='GET')) projectReads.push(url); return originalFetch(new URL(String(url), base), options); };
    const output = join(buildRoot, 'App.mjs');
    await build({ entryPoints: [join(repo, 'webui/src/App.tsx')], bundle: true, packages: 'external', platform: 'node', format: 'esm', jsx: 'automatic', outfile: output });
    const { default: App } = await import(pathToFileURL(output));
    const { createRoot } = await import('react-dom/client');
    const container = document.createElement('div'); document.body.append(container); root = createRoot(container);
    async function settle(predicate) { for (let i = 0; i < 100; i++) { await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); }); if (predicate()) return; } assert.fail(container.textContent); }
    const button = text => [...container.querySelectorAll('button')].find(item => item.textContent === text);
    await React.act(async () => root.render(React.createElement(App)));
    await settle(()=>!!button('161 invalid conditions proof'));
    await React.act(async()=>button('161 invalid conditions proof').click());
    await settle(()=>[...container.querySelectorAll('label')].some(label=>label.textContent.startsWith('Additional aligned conditions')));
    const textarea=[...container.querySelectorAll('label')].find(label=>label.textContent.startsWith('Additional aligned conditions')).querySelector('textarea');
    assert.equal(container.querySelector('[aria-label="ESM3 tools: token"]').type,'password');
    const confirms=[];window.confirm=message=>{confirms.push(message);return true};
    await React.act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(textarea,'{"secondary_structure":');textarea.dispatchEvent(new window.Event('input',{bubbles:true}));});
    assert.equal(textarea.checkValidity(),false,'invalid conditions must participate in native save validity');
    assert.match(container.querySelector('.toolbar h2').textContent,/unsaved/);
    assert.match(container.textContent,/SyntaxError/);
    const unloading=new window.Event('beforeunload',{cancelable:true});window.dispatchEvent(unloading);
    assert.equal(unloading.defaultPrevented,true);
    await React.act(async()=>button('Save project').click());
    await settle(()=>container.textContent.includes('Enter valid parameter JSON before saving'));
    await React.act(async()=>(button('Save and run')??button('Run')).click());
    assert.ok(confirms.some(message=>message==='Save changes and run?'));
    assert.equal(runRequests.length,0);
    assert.equal((await json(`/api/projects/${project.id}/runs`)).length,0);
    assert.deepEqual((await json(`/api/projects/${project.id}`)).flow.nodes[0].parameters.conditions,originalConditions);
    async function edit(control,value){await React.act(async()=>{const prototype=control.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(control,value);control.dispatchEvent(new window.Event('input',{bubbles:true}));});}
    await edit(textarea,'{"secondary_structure":"');
    await edit(textarea,'{"secondary_structure": "E"');
    const invalidText=textarea.value,reads=projectReads.length;
    await settle(()=>projectReads.length>reads);
    assert.equal(textarea.value,invalidText);assert.equal(textarea.checkValidity(),false);
    const samples=[...container.querySelectorAll('label')].find(label=>label.textContent.startsWith('Samples per input')).querySelector('input');
    await edit(samples,'2');
    assert.equal(textarea.value,invalidText);assert.equal(textarea.checkValidity(),false);
    window.confirm=message=>{confirms.push(message);return false};
    await React.act(async()=>(button('Save and run')??button('Run')).click());assert.equal(runRequests.length,0);
    await React.act(async()=>button('161 destination').click());
    assert.ok(confirms.some(message=>message.includes('Discard unsaved changes')));
    assert.match(container.querySelector('.toolbar h2').textContent,/161 invalid conditions proof/);
    assert.equal(textarea.value,invalidText);
    window.confirm=message=>{confirms.push(message);return true};
    await React.act(async()=>button('161 destination').click());
    await settle(()=>container.querySelector('.toolbar h2').textContent==='161 destination');
    await React.act(async()=>button('161 invalid conditions proof').click());
    await settle(()=>[...container.querySelectorAll('label')].some(label=>label.textContent.startsWith('Additional aligned conditions')));
    const accepted=[...container.querySelectorAll('label')].find(label=>label.textContent.startsWith('Additional aligned conditions')).querySelector('textarea');
    assert.deepEqual(JSON.parse(accepted.value),originalConditions);assert.equal(accepted.checkValidity(),true);
    await edit(accepted,'{"secondary_structure":');
    await edit(accepted,'{"secondary_structure": "E"');
    await edit(accepted,'{"secondary_structure":"E"}');
    assert.equal(accepted.checkValidity(),true);assert.doesNotMatch(container.textContent,/SyntaxError/);
    await React.act(async()=>(button('Save and run')??button('Run')).click());
    await settle(()=>container.textContent.includes('Run 1 · succeeded'));
    assert.equal(runRequests.length,1);
    const saved=await json(`/api/projects/${project.id}`);
    assert.deepEqual(saved.flow.nodes[0].parameters.conditions,{secondary_structure:'E'});
    const history=await json(`/api/projects/${project.id}/runs`);
    assert.equal(history.length,1);
    const outputPackage=history[0].nodes.generate.outputs.generated[0];
    const packageInfo=await json(`/api/packages/${outputPackage}`);
    const manifest=await json(`/api/packages/${outputPackage}/file?key=`+encodeURIComponent(packageInfo.entry));
    assert.deepEqual(manifest.objects[0].generation.tracks.secondary_structure,'E');
    console.log('Actual App invalid draft blocks save/run, survives polls/unrelated edits, supports discard and executes corrected conditions');
  } finally {
    if (root) await React.act(async () => root.unmount());
    globalThis.fetch = originalFetch;
    hooks?.deregister(); dom?.window.close();
    backend.kill('SIGTERM');
    if (backend.exitCode === null) await new Promise(resolve => backend.once('exit', resolve));
    await rm(dataRoot, { recursive: true, force: true }); await rm(buildRoot, { recursive: true, force: true });
  }
});
