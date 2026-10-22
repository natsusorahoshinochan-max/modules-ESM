const {readFileSync,mkdtempSync,writeFileSync,rmSync,existsSync} = require('node:fs');
const {join} = require('node:path');
const {tmpdir} = require('node:os');
const {spawnSync} = require('node:child_process');
const {runInNewContext} = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const html = readFileSync(join(__dirname, 'index.html'), 'utf8');
const source = html.match(/<script id="prototype-logic">([\s\S]*?)<\/script>/)[1];
const context = {};
runInNewContext(source, context);
const P = context.ConditionsPrototype;
const plain = value => JSON.parse(JSON.stringify(value));
const after = (kind, keys) => keys.reduce((state, key) => P.apply(state, P.actions[key].action), P.initial(kind));
const exported = (kind, keys = []) => plain(P.exportRequest(after(kind, keys)));

test('两种正确实现的初始交付内容完全一致', () => {
  assert.deepEqual(exported('rows'), exported('tracks'));
});
for (const kind of ['rows', 'tracks']) {
  test(`${kind}: 插入、突变、重排保留内容身份、原编号及轨道`, () => {
    const value = exported(kind, ['insert', 'mutate', 'reverse']);
    assert.deepEqual(value.positions.map(p => p.id), ['p4','p3','p5','p2','p1']);
    const p2 = value.positions[3];
    assert.deepEqual(p2.source, {objectId:'source-structure',chain:'A',authorNumber:11,insertionCode:'A'});
    assert.equal(p2.residue, 'W');
    assert.equal(p2.observed.residue, 'A');
    assert.equal(p2.condition.sequence, 'W');
    assert.equal(p2.condition.secondary, 'E');
    assert.equal(p2.condition.sasa, 0.2);
    assert.deepEqual(p2.observed.coordinates.atoms.CA, [13,4,5]);
    assert.deepEqual(value.regions[0].members, ['p1','p2','p4']);
    assert.deepEqual(value.pairs[0].members, ['p2','p4']);
    const inserted = value.positions[2];
    assert.equal(inserted.source, null);
    assert.equal(inserted.observed, null);
    assert.deepEqual(inserted.condition, {sequence:null,coordinates:null,secondary:null,sasa:null});
    assert.deepEqual(value.positions[0].condition.coordinates, {frame:'source-frame',atoms:{CA:[33,4,5]}});
  });
  test(`${kind}: 删除被引用位置须明确清理，不留下悬空引用`, () => {
    const initial = P.initial(kind), snapshot = plain(initial);
    assert.throws(() => P.apply(initial, P.actions.delete.action), /删除并清理引用/);
    assert.deepEqual(plain(initial), snapshot);
    const state = P.apply(initial, P.actions.prune.action);
    const value = plain(P.exportRequest(state));
    assert.deepEqual(value.positions.map(p=>p.id), ['p1','p3','p4']);
    assert.deepEqual(value.regions[0].members, ['p1','p4']);
    assert.deepEqual(value.pairs, []);
    assert.equal(P.validate(state), state);
    assert.equal(value.positions[1].condition.secondary, 'C');
    assert.equal(value.positions[1].condition.sasa, 0.3);
    assert.deepEqual(value.positions[1].observed.coordinates.atoms.CA, [23,4,5]);
    const corrupt = plain(state); corrupt.regions[0].members.push('p2');
    assert.throws(() => P.exportRequest(corrupt), /引用缺失位置 p2/);
  });
  test(`${kind}: 清除条件和突变不改写来源观察或移植原分数`, () => {
    const initial = P.initial(kind), state = after(kind, ['clear','mutate','variable']);
    const value = plain(P.exportRequest(state));
    assert.equal(value.positions[0].condition.coordinates, null);
    assert.deepEqual(value.positions[0].observed.coordinates, {frame:'source-frame',atoms:{N:[0,1,2],CA:[3,4,5]}});
    assert.deepEqual(plain(state.original), plain(initial.original));
    assert.equal(state.original.evaluations[0].subjectId, 'source-structure');
    assert.equal('evaluations' in value, false);
    assert.equal(value.positions[1].residue, 'W');
    assert.equal(value.positions[1].condition.sequence, null);
    assert.equal(value.positions[1].observed.residue, 'A');
  });
  test(`${kind}: 独立等长输入没有映射仍拒绝；显式映射按内容交接`, () => {
    const initial = P.initial(kind);
    assert.throws(() => P.apply(initial, P.actions.unmapped.action), /缺少明确位置映射/);
    const value = exported(kind, ['mapped','reverse']);
    assert.deepEqual(value.positions.map(p=>[p.id,p.condition.coordinates.atoms.CA[0]]), [['p4',100],['p3',200],['p2',300],['p1',400]]);
    assert.equal(value.positions[0].condition.coordinates.frame, 'independent-frame');
    assert.equal(value.positions[0].observed.coordinates.frame, 'source-frame');
    assert.deepEqual(value.positions[0].observed.coordinates.atoms.CA, [33,4,5]);
    assert.throws(() => P.apply(initial, {...P.actions.mapped.action,mapping:[{source:'q1',target:'p1'}]}), /映射不完整/);
    assert.throws(() => P.apply(initial, {...P.actions.mapped.action,mapping:[{source:'q1',target:'p1'},{source:'q2',target:'p1'}]}), /一对一映射/);
    assert.throws(() => P.apply(initial, {...P.actions.mapped.action,mapping:[{source:'q1',target:'missing'}]}), /不存在的位置/);
  });
  test(`${kind}: 新位置可以继续编辑删除，ID 不重用`, () => {
    let state = after(kind, ['insert']);
    state=P.apply(state,{type:'mutateAndFixSequence',id:'p5',residue:'S'});
    state=P.apply(state,{type:'delete',id:'p5'});
    state=P.apply(state,P.actions.insert.action);
    assert.deepEqual(plain(P.ids(state)), ['p1','p2','p6','p3','p4']);
    assert.equal(P.rowAt(state,'p6').condition.coordinates,null);
    assert.throws(()=>P.apply(state,{type:'makeVariable',id:'p5'}),/已不存在/);
  });
}
test('组合动作搜索：可执行和拒绝的结果均保持两种表示等价', () => {
  const keys = Object.keys(P.actions);
  let visits = 0;
  function walk(rows, tracks, depth) {
    assert.deepEqual(plain(P.exportRequest(rows)), plain(P.exportRequest(tracks)));
    if (!depth) return;
    for (const key of keys) {
      let a,b,ae,be;
      try { a=P.apply(rows,P.actions[key].action); } catch(error) { ae=error.message; }
      try { b=P.apply(tracks,P.actions[key].action); } catch(error) { be=error.message; }
      visits++;
      assert.equal(ae,be,`动作 ${key} 的拒绝原因不同`);
      if (!ae) walk(a,b,depth-1);
    }
  }
  walk(P.initial('rows'),P.initial('tracks'),3);
  assert.ok(visits > 300);
});
test('独立轨道表示明确检测缺失轨道，不按位置补默认值', () => {
  const state=P.initial('tracks');delete state.tracks.sasa.p2;
  assert.throws(()=>P.exportRequest(state),/轨道 sasa 与位置不一致/);
});
test('显式输入夹具经同一编辑核心导出，保留实际来源和选择的原子', () => {
  const request=exported('rows');
  const seed={objectId:'external',positions:request.positions.map(({index,...row})=>row),regions:request.regions,pairs:request.pairs};
  seed.positions[1].source={objectId:'external',chain:'B',authorNumber:-3,insertionCode:'Z'};
  seed.positions[1].observed.coordinates.atoms.CA=[1.25,-2.5,3.75];
  seed.positions[1].condition.coordinates={frame:'external-frame',atoms:{N:[9,8,7]}};
  const run=kind=>P.exportRequest(P.apply(P.fromSeed(kind,seed),P.actions.reverse.action));
  const a=plain(run('rows')),b=plain(run('tracks'));
  assert.deepEqual(a,b);
  assert.deepEqual(a.positions[2].source,seed.positions[1].source);
  assert.deepEqual(a.positions[2].observed.coordinates.atoms.CA,[1.25,-2.5,3.75]);
  assert.deepEqual(a.positions[2].condition.coordinates,{frame:'external-frame',atoms:{N:[9,8,7]}});
});
test('命令行桥接实际执行HTML核心并只在成功时写出完整交付', () => {
  const directory=mkdtempSync(join(tmpdir(),'conditions-prototype-'));
  try {
    const input=join(directory,'input.json'),output=join(directory,'output.json');
    const request=exported('rows');
    const seed={objectId:'fixture',positions:request.positions.map(({index,...row})=>row),regions:request.regions,pairs:request.pairs};
    writeFileSync(input,JSON.stringify({seed,actions:[P.actions.insert.action,P.actions.reverse.action]}));
    const success=spawnSync(process.execPath,[join(__dirname,'export.cjs'),input,output],{encoding:'utf8'});
    assert.equal(success.status,0,success.stderr);
    const value=JSON.parse(readFileSync(output,'utf8'));
    assert.equal(value.representationsEqual,true);
    assert.deepEqual(value.request.positions.map(p=>p.id),['p4','p3','p5','p2','p1']);
    assert.equal(value.request.positions[3].source.insertionCode,'A');
    rmSync(output);
    writeFileSync(input,JSON.stringify({seed,actions:[P.actions.delete.action]}));
    const failure=spawnSync(process.execPath,[join(__dirname,'export.cjs'),input,output],{encoding:'utf8'});
    assert.notEqual(failure.status,0);
    assert.equal(existsSync(output),false);
  } finally { rmSync(directory,{recursive:true,force:true}); }
});
