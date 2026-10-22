// Throwaway verification of the exact pure module embedded in index.html.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const source = html.match(/<script id="prototype-logic">([\s\S]*?)<\/script>/)[1];
assert(!/\bdocument\b|\bwindow\b/.test(source), 'Pure logic must not access the DOM');
const context = vm.createContext({});
vm.runInContext(source, context);
const P = context.IterationPrototype;
const plain = value => JSON.parse(JSON.stringify(value));
const action = (state, type) => P.dispatch(state, { type });
const values = (state, packets) => plain(P.view(state, packets).map(item => item.value));
const stage = (state, count) => Array.from({ length: count }).reduce(current => action(current, 'advance'), state);
const progress = state => state.calls.filter(call => call.node === 'generate').flatMap(call => call.previous?.requests ?? []);
let passed = 0;
const test = (name, check) => { check(); passed++; console.log(`PASS ${name}`); };

test('确定性演算：初始六项及独立得分预期', () => {
  let state = stage(P.create(), 2);
  assert.deepEqual(values(state, state.generated), [1, 2, 3, 7, 8, 9]);
  assert.deepEqual(plain(P.view(state, state.scored).map(item => item.score)), [5, 6, 7, 9, 8, 7]);
  state = action(state, 'advance');
  assert.deepEqual(values(state, state.selected), [7, 8]);
});

test('整批与逐包：相同结果，实际调用边界不同', () => {
  const batch = action(P.create(), 'finish');
  const mapped = action(P.create({ mode: 'host-map' }), 'finish');
  assert.deepEqual(values(batch, batch.history[0].selected), [7, 8]);
  assert.deepEqual(values(batch, batch.selected), [6, 7]);
  assert.deepEqual(values(mapped, mapped.selected), [6, 7]);
  assert.equal(batch.calls.filter(call => call.node === 'generate').length, 2);
  assert.equal(mapped.calls.filter(call => call.node === 'generate').length, 4);
  assert.equal(progress(batch).length, 12);
  assert.equal(progress(mapped).length, 12);
  assert.equal(new Set(mapped.calls.map(call => call.id)).size, mapped.calls.length);
});

test('筛选作用域由模块表达：每模板第一名改变后续输入', () => {
  const state = action(P.create({ selection: 'per-template' }), 'finish');
  assert.deepEqual(values(state, state.history[0].selected), [3, 7]);
  assert.deepEqual(values(state, state.selected), [4, 6]);
});

test('实际列表基数：每模板两项共四项，全局两项共两项', () => {
  const perTemplate = stage(P.create({ selection: 'per-template', threshold: 6, perTemplateLimit: 2, mode: 'host-map' }), 3);
  const global = stage(P.create({ threshold: 6 }), 3);
  assert.deepEqual(values(perTemplate, perTemplate.selected), [3, 2, 7, 8]);
  assert.deepEqual(values(global, global.selected), [7, 8]);
  const continued = action(perTemplate, 'finish');
  assert.equal(continued.calls.filter(call => call.iteration === 2 && call.node === 'generate').length, 4);
  assert.equal(continued.history[1].generated.length, 12);
});

test('固定参考与显式携带参考产生不同的第二轮排名', () => {
  const fixed = action(P.create(), 'finish');
  const carried = action(P.create({ reference: 'carried' }), 'finish');
  assert.deepEqual(plain(carried.history.map(round => values(carried, round.reference))), [[6], [7]]);
  assert.deepEqual(plain(fixed.history.map(round => values(fixed, round.reference))), [[6], [6]]);
  assert.deepEqual(values(carried, carried.selected), [7, 7]);
  assert.deepEqual(values(fixed, fixed.selected), [6, 7]);
});

test('并列保留输入顺序，相同数值的新对象各自存在', () => {
  const state = action(P.create({ reference: 'carried' }), 'finish');
  const selected = P.view(state, state.selected);
  assert.deepEqual(plain(selected.map(item => item.label)), ['B.1.2', 'B.2.1']);
  assert.notEqual(selected[0].packageId, selected[1].packageId);
});

for (const mode of ['task-batch', 'host-map']) {
  test(`${mode}：失败保留四项但禁止交给下游，续算跳过成功项`, () => {
    let state = action(action(P.create({ mode }), 'fail'), 'finish');
    assert.equal(state.phase, 'failed');
    assert.equal(state.generated.length, 4);
    assert.equal(state.released, false);
    assert.equal(state.calls.filter(call => call.node === 'evaluate').length, 0);
    assert.deepEqual(plain(progress(state).map(request => request.status)), ['succeeded', 'succeeded', 'succeeded', 'succeeded', 'failed', 'pending']);
    const successfulPackages = plain(state.generated.map(packet => packet.packageId));
    state = action(state, 'draft');
    assert.equal(state.config.children, 3);
    assert.equal(state.draft.children, 5);
    state = action(state, 'resume');
    assert.equal(state.generated.length, 6);
    assert.deepEqual(plain(state.generated.slice(0, 4).map(packet => packet.packageId)), successfulPackages);
    assert.deepEqual(plain(progress(state).map(request => request.attempts)), [1, 1, 1, 1, 2, 1]);
    assert.equal(state.released, true);
    if(mode === 'host-map') assert.deepEqual(plain(state.calls.map(call => call.attempts)), [1, 2]);
    state = action(state, 'finish');
    assert.deepEqual(values(state, state.selected), [6, 7]);
    assert(state.calls.filter(call => call.node === 'generate').every(call => call.parameters.children === 3));
  });
  test(`${mode}：空选择原样传入第二轮，无补足候选`, () => {
    const state = action(P.create({ mode, threshold: 99 }), 'finish');
    assert.equal(state.status, 'succeeded');
    assert.deepEqual(plain(state.history.map(round => round.selected.length)), [0, 0]);
    assert.equal(state.history[1].generated.length, 0);
    assert.equal(progress(state).length, 6);
  });
  test(`${mode}：取消在请求边界停止，继续仅执行未完成项`, () => {
    let state = action(action(P.create({ mode }), 'cancel'), 'finish');
    assert.equal(state.status, 'cancelled');
    assert.equal(state.generated.length, 4);
    assert.equal(state.released, false);
    assert.deepEqual(plain(progress(state).map(request => request.attempts)), [1, 1, 1, 1, 0, 0]);
    state = action(state, 'resume');
    assert.deepEqual(plain(progress(state).map(request => request.attempts)), [1, 1, 1, 1, 1, 1]);
    assert.equal(state.generated.length, 6);
  });
}

test('相同输入分别启动两次，两个运行都实际执行', () => {
  const first = stage(P.create({}, 'run-first'), 1);
  const second = stage(P.create({}, 'run-second'), 1);
  assert.equal(progress(first).filter(request => request.attempts === 1).length, 6);
  assert.equal(progress(second).filter(request => request.attempts === 1).length, 6);
  assert.notEqual(first.calls[0].id, second.calls[0].id);
  assert.deepEqual(values(first, first.generated), values(second, second.generated));
});

test('状态转换不修改前态或来源模板', () => {
  const initial = P.create();
  const before = JSON.stringify(initial);
  const after = action(initial, 'finish');
  assert.equal(JSON.stringify(initial), before);
  assert.deepEqual(values(after, initial.templates), [2, 8]);
});

test('运行中拒绝修改画布，停止后允许修改而不改变旧调用', () => {
  for(const phaseSteps of [0, 1, 2, 3]) {
    const active = stage(P.create(), phaseSteps);
    const rejected = action(active, 'draft');
    assert.equal(rejected.draft.children, 3);
    assert.equal(rejected.config.children, 3);
    assert.match(rejected.message, /锁定/);
  }
  for(const stop of ['fail', 'cancel']) {
    const stopped = action(action(P.create(), stop), 'finish');
    const changed = action(stopped, 'draft');
    assert.equal(changed.draft.children, 5);
    assert.equal(changed.config.children, 3);
  }
  const ended = action(action(P.create(), 'finish'), 'draft');
  assert.equal(ended.draft.children, 5);
  assert.equal(ended.config.children, 3);
});

test('载体只传递不透明包与私有续算内容', () => {
  const packet = new Proxy({}, { get() { throw new Error('Host read packet content'); } });
  const privateCheckpoint = new Proxy({}, { get() { throw new Error('Host read private checkpoint'); } });
  const calls = P.Host.calls('opaque', 3, 'external-operation', [{ any: [packet] }], { rate: 4 });
  const stopped = P.Host.drive(calls, call => {
    assert.equal(call.inputs.any[0], packet);
    return { status: 'failed', outputs: [packet], continuation: privateCheckpoint };
  });
  assert.equal(P.Host.release(stopped), null);
  const resumed = P.Host.drive(stopped, call => {
    assert.equal(call.previous, privateCheckpoint);
    return { status: 'succeeded', outputs: [packet] };
  });
  const outputs = P.Host.release(resumed);
  const carry = P.Host.carry({ result: outputs }, { next: 'result' });
  assert.equal(carry.next[0], packet);
});

test('载体串行汇合暂停尚未开始项；续算不重跑成功调用', () => {
  let executed = [];
  const calls = P.Host.calls('generic', 1, 'external', [1, 2, 3].map(n => ({ entry: [{ packageId: `p-${n}`, format: 'external.any' }] })), { factor: 2 });
  let stopped = P.Host.drive(calls, call => {
    executed.push(call.item);
    return { status: call.item === 1 ? 'failed' : 'succeeded', outputs: [] };
  });
  assert.deepEqual(executed, [0, 1]);
  assert.deepEqual(plain(stopped.map(call => call.status)), ['succeeded', 'failed', 'pending']);
  stopped = P.Host.drive(stopped, call => { executed.push(call.item); return { status: 'succeeded', outputs: [] }; });
  assert.deepEqual(executed, [0, 1, 1, 2]);
  assert.deepEqual(plain(P.Host.release(stopped)), []);
});

test('标量变体复用同一载体；不会覆盖失败运行的续算位置', () => {
  let state = action(action(P.create({ mode: 'host-map' }), 'fail'), 'finish');
  const resumable = plain(state.currentCalls.map(call => call.id));
  state = action(state, 'scalar');
  assert.deepEqual(plain(P.view(state, state.scalarResult).map(item => item.number)), [11, 17]);
  assert.deepEqual(plain(state.currentCalls.map(call => call.id)), resumable);
  state = action(state, 'scalar');
  assert.equal(new Set(state.calls.map(call => call.id)).size, state.calls.length);
  state = action(state, 'resume');
  assert.equal(state.generated.length, 6);
  assert.equal(state.phase, 'generated');
});

console.log(`\n${passed} prototype checks passed; scientific generation remains simulated.`);
