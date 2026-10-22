// PROTOTYPE: execute the exact portable logic embedded in index.html; no DOM or model calls.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const logic = html.match(/<script id="prototype-logic">([\s\S]*?)<\/script>/)[1];
const sandbox = {module:{exports:{}}};
vm.runInNewContext(logic, sandbox);
const P = sandbox.module.exports;
const packageNames=(m, ids)=>P.describe(m.store,ids).map(o=>o.label);
const record=(name,model)=>{
 const result=P.run(model);
 return {scenario:name,status:result.status,error:result.error,graph:model.graph,
   rounds:result.rounds.map(r=>({round:r.round,inputs:packageNames(model,r.inputs.items||[]),references:packageNames(model,r.inputs.reference||[]),selected:packageNames(model,r.outputs.result||[]),selectedDetails:P.describe(model.store,r.outputs.result||[])})),
   final:packageNames(model,result.outputs.result||[]),finalDetails:P.describe(model.store,result.outputs.result||[]),calls:result.log};
};
const examples=[];
let m=P.createTeaching();P.placeFilter(m.graph,'item');examples.push(record('teaching-per-item-filter',m));
m=P.createTeaching();examples.push(record('teaching-global-filter',m));
m=P.createTeaching();P.toggleReference(m.graph);examples.push(record('teaching-explicit-updated-reference',m));
m=P.createTeaching();m.graph.nodes.find(n=>n.id==='imported').packages=[m.imported];examples.push(record('teaching-independent-import',m));
examples.push(record('custom-word-format',P.createText()));
m=P.createTeaching();P.findGraphs(m.graph).find(g=>g.id==='round').edges=P.findGraphs(m.graph).find(g=>g.id==='round').edges.filter(e=>e.to.node!=='filter');examples.push(record('user-disconnected-required-input',m));
const real=JSON.parse(html.match(/<script id="real-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
if(real) for(const run of real.runs) examples.push(record(`real-round-${run.round}-evaluation-replay`,P.createReal(run.collection,run.selection)));
const evidence={purpose:'Questions about explicit scopes and feedback; educational simulated protein values are separate from actual evaluation replay.',source:'index.html#prototype-logic',cases:examples};
if(process.argv.includes('--write'))fs.writeFileSync(path.join(__dirname,'evidence.json'),JSON.stringify(evidence,null,2)+'\n');
console.log(JSON.stringify(evidence,null,2));
