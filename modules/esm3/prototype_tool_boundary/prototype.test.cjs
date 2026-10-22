// Explicit user-requested verification for the throwaway prototype.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const script=html.match(/<script id="prototype-core">([\s\S]*?)<\/script>/)[1];
const context={structuredClone};
vm.runInNewContext(script,context);
const P=context.ToolBoundary;
const plain=x=>JSON.parse(JSON.stringify(x));
const deepFreeze=x=>{if(x&&typeof x==='object'){Object.freeze(x);Object.values(x).forEach(deepFreeze);}return x;};

test('portable core has no DOM, network, process, or production module dependency',()=>{
  assert.doesNotMatch(script,/\b(document|window|fetch|process|require|localStorage)\b/);
  const task={task:'complete_sequence',frame:null,positions:[{key:'external-row',source:null,condition:{sequence:'K',atoms:{},secondary:null,sasa:null}}]};
  let received;
  const external=req=>{received=req;return {result:{task:req.task,positions:[{key:req.positions[0].key,sequence:'K'}],simulated:true}};};
  assert.equal(P.runTaskShaped(task,external).result.positions[0].key,'external-row');
  assert.deepEqual(plain(received),task);
  assert.notEqual(received,task);
});

test('both responsibility assignments execute equivalent native semantics',()=>{
  const req=P.request(P.initial());
  const a=P.runModelShaped(req,P.compileESM);
  const b=P.runTaskShaped(req,P.makeTaskTool(P.compileESM));
  assert.deepEqual(plain(a.result),plain(b.result));
  assert.equal(a.publicInput.protein.sequence,'K___T');
  assert.equal(b.publicInput.task,'complete_sequence');
  assert.equal(b.publicInput.positions.length,5);
  assert.equal(b.publicInput.protein,undefined);
});

test('insert and delete preserve independent track contents at the same position key',()=>{
  const original=P.initial();
  const inserted=P.edit(original,'insert');
  const edited=P.edit(inserted,'delete');
  assert.equal(original.positions.length,5);
  assert.equal(inserted.positions.length,6);
  assert.deepEqual(plain(edited.positions.map(p=>p.key)),['p1','added1','p3','p4','p5']);
  const n=P.compileESM(P.request(edited));
  assert.equal(n.payload.protein.secondary_structure,'__E__');
  assert.deepEqual(plain(n.payload.protein.sasa),[null,null,12,null,null]);
  assert.ok(n.payload.protein.coordinates[1].every(row=>row.every(Number.isNaN)));
  assert.deepEqual(plain(n.payload.protein.coordinates[4][P.ATOM37.indexOf('CA')]),[17,1,0]);
  assert.equal(n.payload.protein.sequence,'K___T');
});

test('ESM native coordinates use atom name mapping with missing values, not flattened observations',()=>{
  const data=P.initial();
  data.positions[0].condition.atoms={C:[9,8,7],N:[1,2,3]};
  const p=P.compileESM(P.request(data)).payload.protein;
  assert.equal(p.coordinates.length,5);
  assert.ok(p.coordinates.every(row=>row.length===37));
  assert.deepEqual(plain(p.coordinates[0][0]),[1,2,3]);
  assert.ok(p.coordinates[0][1].every(Number.isNaN));
  assert.deepEqual(plain(p.coordinates[0][2]),[9,8,7]);
  assert.ok(p.coordinates[2].every(row=>row.every(Number.isNaN)));
});

test('each boundary leaves frozen input and independent observations untouched',()=>{
  const data=deepFreeze(P.initial());
  const before=plain(data);
  const req=deepFreeze(P.request(data));
  P.runModelShaped(req,P.compileESM);
  P.runTaskShaped(req,P.makeTaskTool(P.compileESM));
  assert.deepEqual(plain(data),before);
  const seq=P.edit(data,'sequence_only');
  assert.deepEqual(plain(seq.positions[0].observed),before.positions[0].observed);
  assert.deepEqual(plain(seq.positions[0].condition.atoms),{});
});

test('transport sees native fields only, without task position keys or module state',()=>{
  const req=P.request(P.initial());
  for(const run of [t=>P.runModelShaped(req,P.compileESM,t),t=>P.runTaskShaped(req,P.makeTaskTool(P.compileESM,t))]){
    let seen;
    run((payload,codec)=>{seen=payload;return P.simulate(payload,codec);});
    assert.equal(seen.positions,undefined);
    assert.equal(seen.binding,undefined);
    assert.equal(seen.protein.sequence,'K___T');
  }
});

test('capability mismatch rejects in both paths without changing conditions',()=>{
  const req=P.request(P.initial());
  const before=plain(req);
  assert.throws(()=>P.runModelShaped(req,P.compileSparse),/不支持坐标/);
  assert.throws(()=>P.runTaskShaped(req,P.makeTaskTool(P.compileSparse)),/不支持坐标/);
  assert.deepEqual(plain(req),before);
});

test('unselected observed coordinates do not become unsupported conditions',()=>{
  const seq=P.edit(P.initial(),'sequence_only');
  assert.ok(Object.keys(seq.positions[0].observed.atoms).length>0);
  const req=P.request(seq);
  assert.doesNotThrow(()=>P.runTaskShaped(req,P.makeTaskTool(P.compileSparse)));
  const esm=P.runTaskShaped(req,P.makeTaskTool(P.compileESM));
  const sparse=P.runTaskShaped(req,P.makeTaskTool(P.compileSparse));
  assert.deepEqual(plain(esm.result),plain(sparse.result));
});

test('one ESM implementation supports two task contracts through one compiler',()=>{
  const tool=P.makeTaskTool(P.compileESM);
  const data=P.initial();
  const seq=P.runTaskShaped(P.request(data,'complete_sequence'),tool);
  const structure=P.runTaskShaped(P.request(data,'generate_structure'),tool);
  assert.equal(seq.compiled.payload.generation.track,'sequence');
  assert.equal(structure.compiled.payload.generation.track,'structure');
  assert.equal(seq.result.positions[0].sequence,'K');
  assert.deepEqual(plain(structure.result.positions[0].atoms.N),[0,0,0]);
  assert.throws(()=>P.runTaskShaped(P.request(data,'generate_structure'),P.makeTaskTool(P.compileSparse)),/只实现序列补全/);
});

test('unexpected output length, changed fixed residue and wrong compilation map fail',()=>{
  const req=P.request(P.initial());
  const c=P.compileESM(req);
  assert.throws(()=>P.decode(c,{sequence:'KGAT'},req),/长度改变/);
  assert.throws(()=>P.decode(c,{sequence:'AGAVT'},req),/改变固定/);
  const other=P.request(P.edit(P.initial(),'insert'));
  assert.throws(()=>P.decode(c,{sequence:'KGAVT'},other),/编译时的位置/);
});

test('explicit native indices map reversed rows; duplicated, missing, and foreign indices fail',()=>{
  const req=P.request(P.edit(P.initial(),'sequence_only'));
  const c=P.compileSparse(req),native=P.simulate(c.payload,c.codec);
  assert.equal(native.residues[0].index,4);
  assert.deepEqual(plain(P.decode(c,native,req).positions.map(p=>p.key)),['p1','p2','p3','p4','p5']);
  const duplicate=structuredClone(native);duplicate.residues[0].index=3;
  assert.throws(()=>P.decode(c,duplicate,req),/唯一性错误/);
  const foreign=structuredClone(native);foreign.residues[0].index=8;
  assert.throws(()=>P.decode(c,foreign,req),/缺少显式/);
  assert.throws(()=>P.decode(c,{residues:native.residues.slice(1)},req),/数量/);
});

test('undeclared condition, unsupported atom, malformed coordinate and duplicate key are rejected',()=>{
  const extra=P.request(P.initial());extra.positions[0].condition.contacts=[];
  assert.throws(()=>P.compileESM(extra),/未声明的条件/);
  const atom=P.request(P.initial());atom.positions[0].condition.atoms.FE=[1,2,3];
  assert.throws(()=>P.compileESM(atom),/不支持原子 FE/);
  const bad=P.request(P.initial());bad.positions[0].condition.atoms.N=[1,2];
  assert.throws(()=>P.compileESM(bad),/有限 XYZ/);
  const repeated=P.request(P.initial());repeated.positions[1].key='p1';
  assert.throws(()=>P.compileESM(repeated),/标识必须唯一/);
});

test('structure output must have full mapping and promised backbone atoms',()=>{
  const req=P.request(P.initial(),'generate_structure');
  const c=P.compileESM(req),native=P.simulate(c.payload,c.codec);
  assert.throws(()=>P.decode(c,{coordinates:native.coordinates.slice(1)},req),/长度改变/);
  const broken=structuredClone(native);broken.coordinates[0][1]=[NaN,NaN,NaN];
  assert.throws(()=>P.decode(c,broken,req),/缺少本任务要求/);
});
