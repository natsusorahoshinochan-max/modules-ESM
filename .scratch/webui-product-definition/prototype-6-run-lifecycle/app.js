// PROTOTYPE 6 (throwaway): three variants of Workflow run scope and lifecycle,
// switchable via ?variant= on an isolated prototype route.

const VARIANTS = {
  A: {
    label: "A · 空间范围叠层",
    short: "直接在 Workflow 画布上选择范围、观察状态和打开节点详情。",
  },
  B: {
    label: "B · 运行账本",
    short: "把计划、依赖、执行状态与结果归属放进逐节点账本。",
  },
  C: {
    label: "C · 分支泳道",
    short: "用共享上游与独立分支泳道强调失败和整次取消的差别。",
  },
};

const STATUS = {
  idle: { label: "未参与", short: "—" },
  waiting: { label: "等待", short: "等待" },
  running: { label: "运行中", short: "运行" },
  success: { label: "成功", short: "成功" },
  failed: { label: "失败", short: "失败" },
  cancelled: { label: "已取消", short: "取消" },
  unexecuted: { label: "未执行 · 上游失败", short: "未执行" },
};

const NODES = [
  {
    id: "pdb",
    index: "01",
    label: "导入 PDB",
    kind: "输入",
    model: null,
    parameters: "链 A · 1CRN（示意样本）",
    dependencies: [],
    lane: "shared",
  },
  {
    id: "prompt",
    index: "02",
    label: "编写 ProteinPrompt",
    kind: "Prompt",
    model: null,
    parameters: "47 residues · coordinates 45/47（示意）",
    dependencies: ["pdb"],
    lane: "shared",
  },
  {
    id: "esm",
    index: "03",
    label: "ESM-3 生成",
    kind: "生成",
    model: "ESM-3（示意）",
    parameters: "80 steps · 16 Candidates · seed 1701（示意）",
    dependencies: ["prompt"],
    lane: "shared",
  },
  {
    id: "sol",
    index: "04A",
    label: "评分溶解度",
    kind: "评分",
    model: "ProteinSol（示意）",
    parameters: "Candidate-level score（示意）",
    dependencies: ["esm"],
    lane: "sequence",
  },
  {
    id: "filter",
    index: "05A",
    label: "筛选候选",
    kind: "筛选",
    model: null,
    parameters: "阈值 0.62（示意；Metric 定义未裁决）",
    dependencies: ["sol"],
    lane: "sequence",
  },
  {
    id: "fold",
    index: "04B",
    label: "预测蛋白质结构",
    kind: "折叠",
    model: "SimpleFold（示意）",
    parameters: "16 Candidates（示意）",
    dependencies: ["esm"],
    lane: "structure",
  },
  {
    id: "structure-score",
    index: "05B",
    label: "结构一致性评分",
    kind: "评分",
    model: "TM-score Method（示意）",
    parameters: "固定参考结构（示意）",
    dependencies: ["fold"],
    lane: "structure",
  },
];

const EDGES = NODES.flatMap((node) =>
  node.dependencies.map((source) => ({ source, target: node.id })),
);

const nodeById = (id) => NODES.find((node) => node.id === id);

const initialStatuses = () =>
  Object.fromEntries(NODES.map((node) => [node.id, "idle"]));

const initialVariant = new URLSearchParams(location.search).get("variant");
const SHOW_PROTOTYPE_CONTROLS =
  location.protocol === "file:" ||
  ["127.0.0.1", "localhost"].includes(location.hostname);

const state = {
  variant: VARIANTS[initialVariant] ? initialVariant : "A",
  view: "workflow",
  selectedNode: "fold",
  detailNode: "fold",
  scopeMode: "full",
  summaryOpen: false,
  failureEnabled: true,
  failureCorrected: false,
  workflowRevision: 1,
  latestRunRevision: null,
  latestRunSerial: 0,
  statuses: initialStatuses(),
  run: {
    active: false,
    outcome: "idle",
    scope: [],
    stage: 0,
    failureConsumed: false,
  },
  results: {
    candidates: 0,
    solubilityScores: 0,
    selectedCandidates: 0,
    structures: 0,
    structureScores: 0,
  },
  eventLog: [
    "尚未开始运行。先选择范围，再核对运行摘要。",
  ],
  lastAction: "原型已载入",
  toasts: [],
};

function ancestorsOf(nodeId, collected = new Set()) {
  const node = nodeById(nodeId);
  if (!node) return collected;
  node.dependencies.forEach((dependency) => {
    if (!collected.has(dependency)) {
      collected.add(dependency);
      ancestorsOf(dependency, collected);
    }
  });
  return collected;
}

function descendantsOf(nodeId, collected = new Set()) {
  NODES.filter((node) => node.dependencies.includes(nodeId)).forEach((child) => {
    if (!collected.has(child.id)) {
      collected.add(child.id);
      descendantsOf(child.id, collected);
    }
  });
  return collected;
}

function scopeFor(mode = state.scopeMode, selected = state.selectedNode) {
  let ids;
  if (mode === "full") ids = new Set(NODES.map((node) => node.id));
  else if (mode === "to") ids = new Set([...ancestorsOf(selected), selected]);
  else ids = new Set([selected, ...descendantsOf(selected)]);
  return NODES.filter((node) => ids.has(node.id)).map((node) => node.id);
}

function scopeLabel(mode = state.scopeMode) {
  if (mode === "full") return "完整运行";
  if (mode === "to") return `运行到 · ${nodeById(state.selectedNode).label}`;
  return `从节点继续 · ${nodeById(state.selectedNode).label}`;
}

function oldResults() {
  return (
    state.latestRunRevision !== null &&
    state.workflowRevision !== state.latestRunRevision
  );
}

function blockingIssues() {
  const issues = [];
  if (state.scopeMode === "from") {
    const selectedAncestors = [...ancestorsOf(state.selectedNode)];
    const missing = selectedAncestors.filter(
      (id) => !scopeFor().includes(id) && state.statuses[id] !== "success",
    );
    if (missing.length) {
      issues.push({
        nodeId: missing[missing.length - 1],
        text: `缺少可复用的上游成功结果：${missing
          .map((id) => nodeById(id).label)
          .join("、")}`,
      });
    }
  }
  return issues;
}

function addToast(text, tone = "") {
  const id = `${Date.now()}-${Math.random()}`;
  state.toasts.push({ id, text, tone });
  setTimeout(() => {
    state.toasts = state.toasts.filter((toast) => toast.id !== id);
    renderToasts();
  }, 3600);
}

function renderToasts() {
  const root = document.querySelector(".toasts");
  if (!root) return;
  root.innerHTML = state.toasts
    .map((toast) => `<div class="toast ${toast.tone}">${toast.text}</div>`)
    .join("");
}

function recordEvent(text) {
  state.eventLog.unshift(text);
  state.eventLog = state.eventLog.slice(0, 8);
  state.lastAction = text;
}

function selectNode(nodeId) {
  if (!nodeById(nodeId)) return;
  state.selectedNode = nodeId;
  state.detailNode = nodeId;
  recordEvent(`已选择 Node Instance：${nodeById(nodeId).label}`);
  render();
}

function setScopeMode(mode) {
  if (!['full', 'to', 'from'].includes(mode) || state.run.active) return;
  state.scopeMode = mode;
  state.summaryOpen = false;
  recordEvent(`已选择运行范围：${scopeLabel(mode)}`);
  render();
}

function resultSummaryFor(nodeId) {
  if (nodeId === "pdb") return "已读取示意结构输入";
  if (nodeId === "prompt") return "ProteinPrompt · 47 residues（示意）";
  if (nodeId === "esm") return `${state.results.candidates} Candidates 已保留`;
  if (nodeId === "sol") return `${state.results.solubilityScores} 个 score observations`;
  if (nodeId === "filter") return `${state.results.selectedCandidates} 个 Candidates 通过（示意）`;
  if (nodeId === "fold") return `${state.results.structures} 个结构 Candidates`;
  return `${state.results.structureScores} 个结构 score observations`;
}

function setResultsForSuccess(nodeId) {
  if (nodeId === "esm") state.results.candidates = 16;
  if (nodeId === "sol") state.results.solubilityScores = state.results.candidates || 16;
  if (nodeId === "filter") state.results.selectedCandidates = 6;
  if (nodeId === "fold") state.results.structures = state.results.candidates || 16;
  if (nodeId === "structure-score")
    state.results.structureScores = state.results.structures || 16;
}

function scheduleAvailableNodes() {
  const scope = new Set(state.run.scope);
  let changed = true;
  while (changed) {
    changed = false;
    state.run.scope.forEach((nodeId) => {
      if (state.statuses[nodeId] !== "waiting") return;
      const node = nodeById(nodeId);
      const dependencies = node.dependencies.filter((id) => scope.has(id));
      if (
        dependencies.some((id) =>
          ["failed", "unexecuted"].includes(state.statuses[id]),
        )
      ) {
        state.statuses[nodeId] = "unexecuted";
        recordEvent(`${node.label} 未执行：依赖的上游节点失败`);
        changed = true;
      }
    });
  }

  state.run.scope.forEach((nodeId) => {
    if (state.statuses[nodeId] !== "waiting") return;
    const node = nodeById(nodeId);
    const scopedDependencies = node.dependencies.filter((id) => scope.has(id));
    const dependenciesReady = scopedDependencies.every(
      (id) => state.statuses[id] === "success",
    );
    if (dependenciesReady) state.statuses[nodeId] = "running";
  });
}

function beginRun() {
  const issues = blockingIssues();
  if (issues.length || state.run.active) return;

  const scope = scopeFor();
  if (state.scopeMode !== "from") state.statuses = initialStatuses();
  scope.forEach((nodeId) => {
    state.statuses[nodeId] = "waiting";
  });

  state.latestRunSerial += 1;
  state.latestRunRevision = state.workflowRevision;
  state.run = {
    active: true,
    outcome: "running",
    scope,
    stage: 1,
    failureConsumed: false,
  };
  state.summaryOpen = false;
  scheduleAvailableNodes();
  recordEvent(
    `最近一次 Run 已开始 · Workflow v${state.workflowRevision} · ${scopeLabel()}`,
  );
  addToast("Run 已开始；收起节点保持收起", "success");
  render();
}

function finishRunIfTerminal() {
  const live = state.run.scope.some((nodeId) =>
    ["waiting", "running"].includes(state.statuses[nodeId]),
  );
  if (live) return false;
  state.run.active = false;
  state.run.outcome = state.run.scope.some(
    (nodeId) => state.statuses[nodeId] === "failed",
  )
    ? "failed"
    : "completed";
  recordEvent(
    state.run.outcome === "failed"
      ? "最近一次 Run 已结束：一条分支失败；独立分支已完成"
      : "最近一次 Run 已成功完成",
  );
  addToast(
    state.run.outcome === "failed"
      ? "Run 已结束：存在失败分支"
      : "Run 已完成",
    state.run.outcome === "failed" ? "danger" : "success",
  );
  return true;
}

function advanceRun() {
  if (!state.run.active) return;
  const running = state.run.scope.filter(
    (nodeId) => state.statuses[nodeId] === "running",
  );
  if (!running.length) {
    scheduleAvailableNodes();
    if (!finishRunIfTerminal()) recordEvent("调度器正在等待可执行节点");
    render();
    return;
  }

  running.forEach((nodeId) => {
    const node = nodeById(nodeId);
    if (
      nodeId === "sol" &&
      state.failureEnabled &&
      !state.failureCorrected &&
      !state.run.failureConsumed
    ) {
      state.statuses[nodeId] = "failed";
      state.run.failureConsumed = true;
      state.detailNode = nodeId;
      recordEvent(`${node.label} 失败（示意）：独立结构分支不受影响`);
    } else {
      state.statuses[nodeId] = "success";
      setResultsForSuccess(nodeId);
      recordEvent(`${node.label} 成功 · ${resultSummaryFor(nodeId)}`);
    }
  });

  state.run.stage += 1;
  scheduleAvailableNodes();
  finishRunIfTerminal();
  render();
}

function cancelRun() {
  if (!state.run.active) return;
  state.run.scope.forEach((nodeId) => {
    if (["running", "waiting"].includes(state.statuses[nodeId])) {
      state.statuses[nodeId] = "cancelled";
    }
  });
  state.run.active = false;
  state.run.outcome = "cancelled";
  recordEvent("已取消整次 Run：运行中与等待节点均停止；成功结果继续保留");
  addToast("整次 Run 已取消；已完成结果未删除", "warn");
  render();
}

function correctFailure() {
  if (state.statuses.sol !== "failed") return;
  state.failureCorrected = true;
  state.selectedNode = "sol";
  state.detailNode = "sol";
  state.scopeMode = "from";
  state.summaryOpen = true;
  recordEvent("失败问题已在原型中标记为修正；准备从评分溶解度节点继续");
  addToast("已修正示意问题；不会重跑已完成且未受影响的分支", "success");
  render();
}

function modifyWorkflow() {
  if (state.run.active || state.latestRunRevision === null) return;
  state.workflowRevision += 1;
  state.view = "results";
  recordEvent(
    `当前 Workflow 已修改为 v${state.workflowRevision}；Results 仍来自 Workflow v${state.latestRunRevision}`,
  );
  addToast("Results 已标记“来自修改前的流程”", "warn");
  render();
}

function resetPrototype() {
  state.view = "workflow";
  state.selectedNode = "fold";
  state.detailNode = "fold";
  state.scopeMode = "full";
  state.summaryOpen = false;
  state.failureEnabled = true;
  state.failureCorrected = false;
  state.workflowRevision = 1;
  state.latestRunRevision = null;
  state.latestRunSerial = 0;
  state.statuses = initialStatuses();
  state.run = {
    active: false,
    outcome: "idle",
    scope: [],
    stage: 0,
    failureConsumed: false,
  };
  state.results = {
    candidates: 0,
    solubilityScores: 0,
    selectedCandidates: 0,
    structures: 0,
    structureScores: 0,
  };
  state.eventLog = ["原型已重置。先选择范围，再核对运行摘要。"];
  state.lastAction = "原型已重置";
  addToast("原型状态已重置");
  render();
}

function statusChip(nodeId, compact = false) {
  const status = state.statuses[nodeId];
  if (compact) {
    return `<span class="status-chip ${status}" title="${STATUS[status].label}"><i></i>${STATUS[status].short}</span>`;
  }
  return `<button class="status-chip ${status}" data-detail-node="${nodeId}" title="打开运行详情"><i></i>${STATUS[status].label}</button>`;
}

function scopeClasses(nodeId) {
  const planned = state.run.active ? state.run.scope : scopeFor();
  return [
    planned.includes(nodeId) ? "in-scope" : "out-scope",
    state.selectedNode === nodeId ? "selected" : "",
    `status-${state.statuses[nodeId]}`,
  ].join(" ");
}

function renderTopbar() {
  const recent = state.latestRunRevision === null
    ? "尚无 Run"
    : `最近一次 Run · Workflow v${state.latestRunRevision}`;
  return `<header class="topbar">
    <div class="brand"><span class="brand-mark">PW</span><div><b>Protein Workbench</b><small>运行生命周期原型 6</small></div></div>
    <div class="project-title"><strong>环区重设计实验（示意）</strong><span>Workflow v${state.workflowRevision}</span><span class="recent ${oldResults() ? "stale" : ""}">${oldResults() ? "结果来自修改前流程" : recent}</span></div>
    <div class="top-actions">
      <label class="failure-toggle prototype-only"><input type="checkbox" data-field="failure-enabled" ${state.failureEnabled ? "checked" : ""} ${state.run.active ? "disabled" : ""} /> 本轮模拟溶解度评分失败</label>
      <button class="button" data-action="reset">重置演示</button>
      <button class="button ${state.view === "results" ? "active" : ""}" data-view="results" ${state.latestRunRevision === null ? "disabled" : ""}>Results</button>
      <button class="button primary" data-action="open-summary" ${state.run.active || state.view !== "workflow" ? "disabled" : ""}>核对运行摘要</button>
    </div>
  </header>`;
}

function renderQuestionBar() {
  return `<section class="question-bar"><span>唯一产品问题</span><strong>用户能否在开始前预测会运行什么，并在任意状态下正确判断结果对应哪一版 Workflow？</strong><small>对应功能规格第 4 节与第 5.1 节 · 一次性原型</small></section>`;
}

function renderScopeControls() {
  return `<div class="scope-control">
    <span class="section-label">运行范围</span>
    <button class="${state.scopeMode === "full" ? "active" : ""}" data-scope="full" ${state.run.active ? "disabled" : ""}>完整运行<small>全部 7 个节点</small></button>
    <button class="${state.scopeMode === "to" ? "active" : ""}" data-scope="to" ${state.run.active ? "disabled" : ""}>运行到节点<small>${nodeById(state.selectedNode).label}</small></button>
    <button class="${state.scopeMode === "from" ? "active" : ""}" data-scope="from" ${state.run.active ? "disabled" : ""}>从节点继续<small>${nodeById(state.selectedNode).label}</small></button>
  </div>`;
}

function renderLiveControls() {
  if (state.run.active) {
    const running = state.run.scope
      .filter((id) => state.statuses[id] === "running")
      .map((id) => nodeById(id).label)
      .join("、");
    return `<div class="live-controls"><div><span>长时间运行状态 · 阶段 ${state.run.stage}</span><strong>${running ? `正在运行：${running}` : "正在收束本次 Run"}</strong><small>“推进一次”用于人工观察中间状态，不是生产交互。</small></div><button class="button primary" data-action="advance">推进一次</button><button class="button danger" data-action="cancel-run">取消整次 Run</button></div>`;
  }
  const failed = Object.values(state.statuses).includes("failed");
  return `<div class="live-controls idle"><div><span>${state.latestRunRevision === null ? "尚未运行" : "最近一次 Run"}</span><strong>${state.run.outcome === "failed" ? "存在失败分支；独立分支已完成" : state.run.outcome === "cancelled" ? "整次 Run 已取消" : state.run.outcome === "completed" ? "运行成功完成" : "先核对范围和摘要"}</strong><small>${failed ? "修正失败节点后可从该节点继续。" : "画布高亮显示当前计划范围。"}</small></div>${failed && !state.failureCorrected ? '<button class="button warn" data-action="correct-failure">模拟修正失败问题</button>' : ""}${state.latestRunRevision !== null ? '<button class="button" data-action="modify-workflow">修改当前参数（示意）</button>' : ""}<button class="button" data-action="open-summary">核对运行摘要</button></div>`;
}

function renderNodeDetail(nodeId = state.detailNode) {
  const node = nodeById(nodeId);
  const status = state.statuses[nodeId];
  const isFailed = status === "failed";
  const isCancelled = status === "cancelled";
  return `<section class="detail-card">
    <div class="detail-heading"><div><span class="section-label">Node Instance 详情</span><h3>${node.index} · ${node.label}</h3></div>${statusChip(nodeId)}</div>
    <dl><div><dt>依赖</dt><dd>${node.dependencies.length ? node.dependencies.map((id) => nodeById(id).label).join("、") : "无"}</dd></div><div><dt>模型 / Method</dt><dd>${node.model || "不适用"}</dd></div><div><dt>主要参数</dt><dd>${node.parameters}</dd></div><div><dt>最近状态</dt><dd>${STATUS[status].label}</dd></div></dl>
    ${status === "success" ? `<div class="detail-result"><b>已保留的结果</b><span>${resultSummaryFor(nodeId)}</span></div>` : ""}
    ${isFailed ? '<div class="detail-alert danger"><b>失败（示意）</b><p>输入数据仍有效，但本 Node Execution Attempt 未产生 score outputs。依赖它的筛选节点未执行；结构分支继续。</p></div>' : ""}
    ${isCancelled ? '<div class="detail-alert warn"><b>因整次 Run 取消而停止</b><p>这里没有单节点取消入口；此前成功节点的结果仍保留。</p></div>' : ""}
    ${isFailed && !state.failureCorrected ? '<button class="button warn wide" data-action="correct-failure">模拟修正，然后从此节点继续</button>' : ""}
  </section>`;
}

function renderEventLog() {
  return `<section class="event-log"><div class="section-title"><span class="section-label">最近一次 Run 事件</span><small>只显示最近一次，不提供历史列表</small></div><ol>${state.eventLog.map((event, index) => `<li class="${index === 0 ? "latest" : ""}"><i></i><span>${event}</span></li>`).join("")}</ol></section>`;
}

function renderCanvasNode(node) {
  return `<button class="canvas-node ${scopeClasses(node.id)}" data-node="${node.id}"><div class="node-title"><span>${node.index}</span><strong>${node.label}</strong>${statusChip(node.id, true)}</div><div class="node-meta"><span>${node.kind}</span><small>${node.model || "项目数据操作"}</small></div><i class="port input"></i><i class="port output"></i></button>`;
}

function renderCanvasEdges() {
  const planned = new Set(state.run.active ? state.run.scope : scopeFor());
  const paths = {
    "pdb-prompt": "M140 300 H245",
    "prompt-esm": "M385 300 H490",
    "esm-sol": "M630 300 C680 300 660 150 720 150",
    "sol-filter": "M860 150 H930",
    "esm-fold": "M630 300 C680 300 660 445 720 445",
    "fold-structure-score": "M860 445 H930",
  };
  return `<svg class="canvas-edges" viewBox="0 0 1080 600" preserveAspectRatio="none">${EDGES.map((edge) => {
    const active = planned.has(edge.source) && planned.has(edge.target);
    const failure = state.statuses[edge.source] === "failed";
    return `<path class="${active ? "active" : ""} ${failure ? "failed" : ""}" d="${paths[`${edge.source}-${edge.target}`]}" />`;
  }).join("")}</svg>`;
}

function renderVariantA() {
  return `<main class="workspace variant-a">
    <section class="canvas-surface">
      <div class="canvas-toolbar"><div><span class="section-label">Workflow 画布 · 所有节点保持收起</span><strong>${scopeLabel()}</strong></div><div class="scope-key"><span><i class="included"></i>本次执行</span><span><i></i>不执行</span></div></div>
      <div class="canvas-stage">${renderCanvasEdges()}${NODES.map(renderCanvasNode).join("")}</div>
      ${oldResults() ? renderOldResultBanner("canvas") : ""}
    </section>
    <aside class="run-sidebar">${renderScopeControls()}${renderLiveControls()}${renderNodeDetail()}${renderEventLog()}</aside>
  </main>`;
}

function renderLedgerRow(node) {
  const scope = new Set(state.run.active ? state.run.scope : scopeFor());
  const included = scope.has(node.id);
  return `<tr class="${scopeClasses(node.id)}" data-node="${node.id}"><td><button class="row-node" data-node="${node.id}"><span>${node.index}</span><b>${node.label}</b><small>${node.kind}</small></button></td><td>${node.dependencies.length ? node.dependencies.map((id) => nodeById(id).index).join(" + ") : "输入"}</td><td><span class="scope-mark ${included ? "included" : ""}">${included ? "执行" : "不执行"}</span></td><td>${statusChip(node.id)}</td><td><small>${node.model || "—"}</small><span>${node.parameters}</span></td><td>${state.statuses[node.id] === "success" ? resultSummaryFor(node.id) : state.statuses[node.id] === "unexecuted" ? "无结果 · 上游失败" : "—"}</td></tr>`;
}

function renderVariantB() {
  const scope = scopeFor();
  return `<main class="workspace variant-b">
    <aside class="ledger-sidebar">${renderScopeControls()}<section class="plan-facts"><span class="section-label">当前计划</span><strong>${scopeLabel()}</strong><dl><div><dt>执行</dt><dd>${scope.length} / ${NODES.length} 节点</dd></div><div><dt>Workflow</dt><dd>v${state.workflowRevision}</dd></div><div><dt>最近结果</dt><dd>${state.latestRunRevision === null ? "无" : `v${state.latestRunRevision}`}</dd></div></dl></section>${renderLiveControls()}${renderEventLog()}</aside>
    <section class="ledger-surface">
      <div class="ledger-heading"><div><span class="section-label">逐节点运行账本</span><h2>${scopeLabel()}</h2></div><span>点击任一行选择节点；状态按钮打开详情</span></div>
      ${oldResults() ? renderOldResultBanner("ledger") : ""}
      <div class="table-scroll"><table><thead><tr><th>Node Instance</th><th>依赖</th><th>本次范围</th><th>状态</th><th>模型与主要参数（示意）</th><th>已保留结果</th></tr></thead><tbody>${NODES.map(renderLedgerRow).join("")}</tbody></table></div>
    </section>
    <aside class="detail-sidebar">${renderNodeDetail()}<section class="run-meaning"><span class="section-label">状态语义</span><div><b>失败分支</b><p>依赖失败节点的下游标记“未执行”；独立分支继续。</p></div><div><b>取消整次 Run</b><p>所有运行中与等待节点停止；已成功结果继续保留。</p></div></section></aside>
  </main>`;
}

function renderLaneNode(nodeId) {
  const node = nodeById(nodeId);
  return `<button class="lane-node ${scopeClasses(node.id)}" data-node="${node.id}"><span>${node.index}</span><strong>${node.label}</strong>${statusChip(node.id, true)}<small>${node.model || node.kind}</small></button>`;
}

function renderVariantC() {
  return `<main class="workspace variant-c">
    <section class="lane-surface">
      <div class="lane-header"><div><span class="section-label">执行分支地图</span><h2>${scopeLabel()}</h2></div><p>共享上游完成后，两个分支独立推进。收起节点只显示名称与状态。</p></div>
      ${oldResults() ? renderOldResultBanner("lanes") : ""}
      <div class="lane shared-lane"><div class="lane-label"><b>共享上游</b><small>任一失败会影响依赖它的分支</small></div><div class="lane-flow">${["pdb", "prompt", "esm"].map((id, index) => `${index ? '<i class="flow-arrow">→</i>' : ""}${renderLaneNode(id)}`).join("")}</div></div>
      <div class="branch-split"><span></span><b>并行分支</b><span></span></div>
      <div class="lane sequence-lane"><div class="lane-label"><b>序列评估分支</b><small>本轮可模拟评分失败</small></div><div class="lane-flow">${renderLaneNode("sol")}<i class="flow-arrow">→</i>${renderLaneNode("filter")}</div><div class="lane-outcome ${state.statuses.sol === "failed" ? "danger" : ""}">${state.statuses.sol === "failed" ? "失败：下游未执行" : "独立运行"}</div></div>
      <div class="lane structure-lane"><div class="lane-label"><b>结构评估分支</b><small>不依赖溶解度评分</small></div><div class="lane-flow">${renderLaneNode("fold")}<i class="flow-arrow">→</i>${renderLaneNode("structure-score")}</div><div class="lane-outcome ${state.statuses["structure-score"] === "success" ? "success" : ""}">${state.statuses["structure-score"] === "success" ? "独立完成" : "独立运行"}</div></div>
    </section>
    <aside class="lane-sidebar">${renderScopeControls()}${renderLiveControls()}${renderNodeDetail()}</aside>
    <section class="timeline-surface">${renderEventLog()}<div class="cancel-meaning"><span class="section-label">整次取消的作用域</span><div class="cancel-bracket"><span>共享上游</span><span>序列分支</span><span>结构分支</span></div><p>“取消整次 Run”同时覆盖三条泳道；不存在单节点取消。</p></div></section>
  </main>`;
}

function renderOldResultBanner(context) {
  return `<div class="old-result-banner ${context}"><div><b>来自修改前的流程</b><span>当前 Workflow v${state.workflowRevision} · 最近一次 Run 使用 Workflow v${state.latestRunRevision}</span></div><button data-view="results">查看仍可用的旧结果</button></div>`;
}

function renderResults() {
  const resultCount = state.results.selectedCandidates || state.results.candidates;
  return `<main class="results-view">
    <div class="results-heading"><div><span class="section-label">Results Workbench · 原型 6 仅验证来源标记</span><h1>最近一次 Run 的结果</h1><p>项目只显示最近一次 Run；此处没有历史列表。</p></div><button class="button" data-view="workflow">返回 Workflow</button></div>
    ${oldResults() ? `<section class="results-stale-banner"><div><b>来自修改前的流程</b><strong>这些结果来自 Workflow v${state.latestRunRevision}，当前已修改为 Workflow v${state.workflowRevision}。</strong><p>结果仍可查看、比较、筛选和导出；它们不会被描述为当前 Workflow 的结果。</p></div><button class="button primary" data-action="export-old">导出这些结果（ZIP）</button></section>` : `<section class="results-current-banner"><b>结果与当前 Workflow 一致</b><span>Workflow v${state.workflowRevision}</span></section>`}
    <div class="results-grid">
      <section class="result-panel candidate-panel"><div class="panel-heading"><span class="section-label">Candidate 表格（示意）</span><b>${resultCount} Candidates</b></div>${[1,2,3,4].map((index) => `<div class="candidate-row"><input type="checkbox" ${index < 3 ? "checked" : ""}/><span>CAND-${String(index).padStart(3,"0")}</span><small>${state.results.structures ? "有结构" : "序列"}</small><b>${index === 1 ? "父 Candidate" : "生成 Candidate"}（示意）</b></div>`).join("")}</section>
      <section class="result-panel structure-panel"><div class="panel-heading"><span class="section-label">结构查看器占位</span><b>CAND-001</b></div><div class="structure-placeholder"><div class="protein-scribble">∿⌁∿<br/>⌁∿⌁</div><span>结构几何仅为示意</span></div></section>
      <section class="result-panel provenance-panel"><div class="panel-heading"><span class="section-label">结果归属</span><b>最近一次 Run</b></div><dl><div><dt>Run</dt><dd>#${state.latestRunSerial}（仅显示最近一次）</dd></div><div><dt>Workflow revision</dt><dd>v${state.latestRunRevision}</dd></div><div><dt>当前 Workflow</dt><dd>v${state.workflowRevision}</dd></div><div><dt>运行结局</dt><dd>${state.run.outcome === "failed" ? "存在失败分支" : state.run.outcome === "cancelled" ? "已取消" : "成功"}</dd></div><div><dt>保留结果</dt><dd>${state.results.candidates} Candidates · ${state.results.structures} structures</dd></div></dl></section>
    </div>
  </main>`;
}

function renderRunSummary() {
  if (!state.summaryOpen || state.view !== "workflow") return "";
  const scope = scopeFor();
  const issues = blockingIssues();
  const models = scope.map((id) => nodeById(id)).filter((node) => node.model);
  return `<div class="modal-backdrop"><section class="run-summary" role="dialog" aria-modal="true" aria-label="运行前摘要">
    <div class="summary-heading"><div><span class="section-label">运行前确认 · 尚未开始</span><h2>${scopeLabel()}</h2><p>Workflow v${state.workflowRevision} · 运行后会替代项目当前显示的最近一次 Run。</p></div><button class="icon-button" data-action="close-summary" aria-label="关闭">×</button></div>
    <div class="scope-preview"><span>将执行 ${scope.length} 个 Node Instances</span><ol>${scope.map((id) => `<li><b>${nodeById(id).index}</b>${nodeById(id).label}</li>`).join("")}</ol></div>
    <div class="summary-grid"><section><span class="section-label">模型 / Method（示意）</span>${models.length ? models.map((node) => `<div class="summary-row"><b>${node.label}</b><span>${node.model}</span></div>`).join("") : "<p>本范围不含模型节点。</p>"}</section><section><span class="section-label">主要参数（示意）</span>${scope.map((id) => nodeById(id)).filter((node) => ["esm", "filter"].includes(node.id)).map((node) => `<div class="summary-row"><b>${node.label}</b><span>${node.parameters}</span></div>`).join("") || "<p>本范围无主要生成参数。</p>"}</section><section><span class="section-label">生成数量与随机性</span><div class="summary-row"><b>生成数量</b><span>${scope.includes("esm") ? "16 Candidates（示意）" : "不在本次范围"}</span></div><div class="summary-row"><b>随机种子</b><span>${scope.includes("esm") ? "1701（示意）" : "不在本次范围"}</span></div></section><section class="blockers ${issues.length ? "has-issues" : ""}"><span class="section-label">当前阻止运行的问题</span>${issues.length ? issues.map((issue) => `<button data-node="${issue.nodeId}"><b>1 个问题</b><span>${issue.text}</span><small>点击定位相关节点</small></button>`).join("") : '<div class="no-issues"><b>0</b><span>没有阻止本次范围运行的问题</span></div>'}</section></div>
    <div class="summary-note">具体模型、Metric、阈值、默认参数与科学值均为交互示意，不是本原型的产品决定。</div>
    <div class="summary-actions"><button class="button" data-action="close-summary">返回修改范围</button><button class="button primary" data-action="begin-run" ${issues.length ? "disabled" : ""}>确认并开始 Run</button></div>
  </section></div>`;
}

function renderPrototypeSwitcher() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  const keys = Object.keys(VARIANTS);
  const index = keys.indexOf(state.variant);
  const previous = keys[(index - 1 + keys.length) % keys.length];
  const next = keys[(index + 1) % keys.length];
  return `<div class="prototype-switcher"><button data-variant="${previous}" aria-label="上一个方案">←</button><div><span>PROTOTYPE VARIANT</span><strong>${VARIANTS[state.variant].label}</strong><small>${VARIANTS[state.variant].short}</small></div><button data-variant="${next}" aria-label="下一个方案">→</button></div>`;
}

function renderStateInspector() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  return `<details class="state-inspector"><summary>原型完整状态</summary><pre>${JSON.stringify({
    variant: state.variant,
    view: state.view,
    selectedNode: state.selectedNode,
    plannedScope: scopeLabel(),
    plannedNodes: scopeFor(),
    workflowRevision: state.workflowRevision,
    latestRunRevision: state.latestRunRevision,
    resultsFromModifiedWorkflow: oldResults(),
    run: state.run,
    statuses: state.statuses,
    results: state.results,
    lastAction: state.lastAction,
  }, null, 2)}</pre></details>`;
}

function render() {
  const root = document.querySelector("#app");
  const body = state.view === "results"
    ? renderResults()
    : state.variant === "A"
      ? renderVariantA()
      : state.variant === "B"
        ? renderVariantB()
        : renderVariantC();
  root.innerHTML = `<div class="app-shell">${renderTopbar()}${renderQuestionBar()}${body}</div>${renderRunSummary()}${renderPrototypeSwitcher()}${renderStateInspector()}<div class="toasts"></div>`;
  renderToasts();
}

function setVariant(key) {
  if (!VARIANTS[key]) return;
  state.variant = key;
  const params = new URLSearchParams(location.search);
  params.set("variant", key);
  history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
  state.lastAction = `切换到 ${VARIANTS[key].label}；Run、范围与结果状态保持不变`;
  render();
}

document.addEventListener("click", (event) => {
  const variantButton = event.target.closest("[data-variant]");
  if (variantButton) return setVariant(variantButton.dataset.variant);

  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    state.view = viewButton.dataset.view;
    state.summaryOpen = false;
    state.lastAction = state.view === "results" ? "打开最近一次 Run 的 Results" : "返回 Workflow";
    return render();
  }

  const scopeButton = event.target.closest("[data-scope]");
  if (scopeButton) return setScopeMode(scopeButton.dataset.scope);

  const detailButton = event.target.closest("[data-detail-node]");
  if (detailButton) {
    event.stopPropagation();
    state.detailNode = detailButton.dataset.detailNode;
    state.lastAction = `打开 ${nodeById(state.detailNode).label} 的运行详情`;
    return render();
  }

  const nodeButton = event.target.closest("[data-node]");
  if (nodeButton) {
    state.summaryOpen = false;
    return selectNode(nodeButton.dataset.node);
  }

  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action) return;
  if (action === "reset") return resetPrototype();
  if (action === "open-summary") { state.summaryOpen = true; return render(); }
  if (action === "close-summary") { state.summaryOpen = false; return render(); }
  if (action === "begin-run") return beginRun();
  if (action === "advance") return advanceRun();
  if (action === "cancel-run") return cancelRun();
  if (action === "correct-failure") return correctFailure();
  if (action === "modify-workflow") return modifyWorkflow();
  if (action === "export-old") {
    recordEvent(`模拟导出：Results 仍明确归属于 Workflow v${state.latestRunRevision}`);
    addToast("已模拟导出固定 ZIP；来源标记随导出保留", "success");
    return render();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches('[data-field="failure-enabled"]')) {
    state.failureEnabled = event.target.checked;
    state.failureCorrected = !state.failureEnabled;
    recordEvent(`本轮失败情境：${state.failureEnabled ? "开启" : "关闭"}`);
    render();
  }
});

document.addEventListener("keydown", (event) => {
  if (!SHOW_PROTOTYPE_CONTROLS || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  if (event.target.matches("input, textarea, select, [contenteditable='true']")) return;
  const keys = Object.keys(VARIANTS);
  const current = keys.indexOf(state.variant);
  setVariant(
    keys[(current + (event.key === "ArrowRight" ? 1 : -1) + keys.length) % keys.length],
  );
});

// Prototype-only action exposed in completed/cancelled views without adding a
// production feature: it simulates a parameter edit so stale-result wording can be tested.
document.addEventListener("dblclick", (event) => {
  if (event.target.closest(".project-title") && state.latestRunRevision !== null && !state.run.active) {
    modifyWorkflow();
  }
});

render();
