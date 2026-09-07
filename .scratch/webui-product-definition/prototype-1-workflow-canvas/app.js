// THROWAWAY UI PROTOTYPE — not production code.
// Three variants of the default Workflow and Blender-style node canvas,
// switchable via ?variant= on this prototype-only page. Each variant distinguishes
// ordinary Nodes, the ProteinPrompt specialized composition, and read-only members.

const VARIANTS = {
  A: { name: "Graph cards", note: "A · 传统空间画布 / 卡片边缘端口" },
  B: { name: "Signal spine", note: "B · 数据类型主轴 / 端口优先" },
  C: { name: "Lab bench", note: "C · 实验仪器面板 / 操作优先" },
};

const SHOW_PROTOTYPE_CONTROLS = ["127.0.0.1", "localhost"].includes(location.hostname);

const CATALOG = {
  pdb: {
    authoringRole: "ordinary_node",
    code: "PDB",
    name: "读取 PDB 结构",
    purpose: "输入",
    provider: "Protein I/O",
    inputs: [],
    outputs: [{ id: "structure", name: "结构", type: "ProteinStructure" }],
    models: [],
    groups: [
      {
        id: "source",
        name: "结构来源",
        fields: [{ id: "pdb", label: "PDB ID（示意）", value: "1CRN" }],
      },
    ],
  },
  prompt: {
    authoringRole: "specialized_composition",
    code: "PP",
    name: "编写 ProteinPrompt",
    purpose: "Prompt",
    provider: "Prompt Authoring",
    inputs: [
      {
        id: "sequence_source",
        name: "Sequence source（可选）",
        type: "protein.sequence",
      },
      {
        id: "structure_source",
        name: "Structure source（可选）",
        type: "structure_transform.resolved_residue_axis",
      },
      {
        id: "prompt_source",
        name: "Prompt source（可选）",
        type: "protein.prompt",
      },
    ],
    outputs: [
      { id: "protein_prompt", name: "ProteinPrompt", type: "protein.prompt" },
      {
        id: "residue_layout",
        name: "Residue layout（只读角色）",
        type: "residue.layout",
      },
    ],
    models: [],
    groups: [],
    sourceKinds: ["blank", "fasta", "pdb", "protein_prompt"],
  },
  generate: {
    authoringRole: "ordinary_node",
    code: "GEN",
    name: "生成候选蛋白质",
    purpose: "生成",
    provider: "ESM",
    inputs: [{ id: "protein_prompt", name: "ProteinPrompt", type: "protein.prompt" }],
    outputs: [{ id: "candidates", name: "候选", type: "CandidateCollection" }],
    models: ["ESM-3 Small（示意）", "ESM-3 Medium（示意）"],
    recommended: true,
    groups: [
      {
        id: "sampling",
        name: "生成与随机性",
        fields: [
          { id: "count", label: "生成数量", value: "16" },
          { id: "seed", label: "随机种子", value: "42" },
        ],
      },
      {
        id: "modelSpecific",
        name: "当前模型专属参数（示意）",
        fields: [{ id: "steps", label: "步骤", value: "48" }],
      },
    ],
  },
  score: {
    authoringRole: "ordinary_node",
    code: "SCR",
    name: "评分候选",
    purpose: "评分",
    provider: "Structure Comparison",
    inputs: [{ id: "candidates", name: "候选", type: "CandidateCollection" }],
    outputs: [{ id: "scored", name: "带评分候选", type: "ScoredCandidates" }],
    models: ["评分方法组合（示意）"],
    groups: [
      {
        id: "metrics",
        name: "Metric 与 Method（示意）",
        fields: [{ id: "metric", label: "选择", value: "结构一致性（示意）" }],
      },
    ],
  },
  filter: {
    authoringRole: "ordinary_node",
    code: "FLT",
    name: "筛选候选",
    purpose: "筛选",
    provider: "Selection",
    inputs: [{ id: "scored", name: "带评分候选", type: "ScoredCandidates" }],
    outputs: [{ id: "selected", name: "筛选结果", type: "CandidateCollection" }],
    models: [],
    groups: [
      {
        id: "rules",
        name: "筛选规则（示意）",
        fields: [{ id: "keep", label: "保留数量", value: "8" }],
      },
    ],
  },
  fasta: {
    authoringRole: "ordinary_node",
    code: "FA",
    name: "读取 FASTA 序列",
    purpose: "输入",
    provider: "Protein I/O",
    inputs: [],
    outputs: [{ id: "sequence", name: "ProteinSequence", type: "protein.sequence" }],
    models: [],
    groups: [
      {
        id: "source",
        name: "序列来源",
        fields: [{ id: "count", label: "序列数（示意）", value: "24" }],
      },
    ],
  },
  fold: {
    authoringRole: "ordinary_node",
    code: "3D",
    name: "预测蛋白质结构",
    purpose: "折叠",
    provider: "Structure Prediction",
    inputs: [{ id: "candidates", name: "候选", type: "CandidateCollection" }],
    outputs: [{ id: "structures", name: "结构候选", type: "CandidateCollection" }],
    models: ["SimpleFold", "ESMFold2"],
    recommended: true,
    groups: [
      {
        id: "shared",
        name: "共有参数",
        fields: [{ id: "batch", label: "批量大小（示意）", value: "4" }],
      },
      {
        id: "modelSpecific",
        name: "当前模型专属参数（示意）",
        fields: [{ id: "recycles", label: "Recycles（示意）", value: "3" }],
      },
    ],
  },
  export: {
    authoringRole: "ordinary_node",
    code: "ZIP",
    name: "导出候选",
    purpose: "导出",
    provider: "Protein I/O",
    inputs: [{ id: "selected", name: "候选", type: "CandidateCollection" }],
    outputs: [],
    models: [],
    groups: [
      {
        id: "contents",
        name: "导出内容",
        fields: [{ id: "format", label: "固定包", value: "ZIP" }],
      },
    ],
  },
};

const START_POSITIONS = {
  prompt: [120, 160],
  generate: [430, 250],
  score: [740, 250],
  filter: [1050, 250],
};

const DEFAULT_PROMPT_PROJECTION = {
  source: "PDB · Project input 1CRN · chain A",
  summary: "A 链 · 46 residues · sequence + coordinates",
  managedMembers: [
    {
      name: "导入 PDB 结构",
      contract: "protein_io.import_structure",
      parameters: 'project_input_ref = "1CRN"',
    },
    {
      name: "选择链 A",
      contract: "structure_transform.select_chains",
      parameters: 'chain_ids = ["A"]',
    },
    {
      name: "解析 residue axis",
      contract: "structure_transform.resolve_residue_axis",
      parameters: "{}",
    },
    {
      name: "从结构建立 ProteinPrompt",
      contract: "prompt_authoring.prompt_from_structure",
      parameters: "{}",
    },
    {
      name: "写入最终 function annotations",
      contract: "prompt_authoring.replace_protein_prompt_annotations",
      parameters: "annotations = [] · overlap_policy = allow",
    },
  ],
};

const variantFromUrl = new URLSearchParams(location.search).get("variant")?.toUpperCase();

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "A",
  taxonomy: "purpose",
  projectName: "默认示例 · ESM-3 ProteinPrompt 设计",
  projectKind: "default",
  nodes: [],
  edges: [],
  selectedNodes: new Set(),
  selectedEdge: null,
  history: [],
  clipboard: null,
  lastAction: "已打开干净的默认示例",
  search: null,
  connecting: null,
  catalogDrag: null,
  draggingNode: null,
  toast: [],
  inspectorOpen: true,
  idCounter: 10,
};

function makeNode(type, x, y, id = `${type}-${state.idCounter++}`) {
  const spec = CATALOG[type];
  const selectedModel = spec.models[0] ?? null;
  return {
    id,
    type,
    x,
    y,
    collapsed: false,
    openGroups: {},
    selectedModel,
    modelMemory: Object.fromEntries(
      spec.models.map((model, index) => [
        model,
        { modelSpecific: index === 0 ? "3" : "8" },
      ]),
    ),
    params: Object.fromEntries(
      spec.groups.flatMap((group) => group.fields.map((field) => [field.id, field.value])),
    ),
    compositionProjection:
      spec.authoringRole === "specialized_composition"
        ? {
            source: "尚未选择来源",
            summary: "尚未编写 · 打开 Prompt Studio",
            managedMembers: [],
          }
        : null,
    status: "ready",
  };
}

function loadDefault() {
  state.nodes = Object.entries(START_POSITIONS).map(([type, [x, y]], index) =>
    makeNode(type, x, y, `${type}-${index + 1}`),
  );
  nodeById("prompt-1").compositionProjection = structuredClone(DEFAULT_PROMPT_PROJECTION);
  state.edges = [
    edge("prompt-1", "protein_prompt", "generate-2", "protein_prompt"),
    edge("generate-2", "candidates", "score-3", "candidates"),
    edge("score-3", "scored", "filter-4", "scored"),
  ];
  state.selectedNodes.clear();
  state.selectedEdge = null;
  state.history = [];
  state.projectName = "默认示例 · ESM-3 ProteinPrompt 设计";
  state.projectKind = "default";
  state.lastAction = "已打开干净的默认示例";
  render();
}

function edge(fromNode, fromPort, toNode, toPort) {
  return {
    id: `edge-${state.idCounter++}`,
    fromNode,
    fromPort,
    toNode,
    toPort,
  };
}

function serializableState() {
  return {
    projectName: state.projectName,
    projectKind: state.projectKind,
    nodes: structuredClone(state.nodes),
    edges: structuredClone(state.edges),
    selectedNodes: [...state.selectedNodes],
    selectedEdge: state.selectedEdge,
    idCounter: state.idCounter,
  };
}

function restore(snapshot) {
  state.projectName = snapshot.projectName;
  state.projectKind = snapshot.projectKind;
  state.nodes = structuredClone(snapshot.nodes);
  state.edges = structuredClone(snapshot.edges);
  state.selectedNodes = new Set(snapshot.selectedNodes);
  state.selectedEdge = snapshot.selectedEdge;
  state.idCounter = snapshot.idCounter;
}

function commit(action, mutation, toastText = action) {
  state.history.push({ action, snapshot: serializableState() });
  mutation();
  if (state.projectKind === "default") {
    state.projectKind = "personal-copy";
    state.projectName = "我的实验 · 默认示例副本";
    addToast("已自动建立个人副本；默认示例保持不变");
  }
  state.lastAction = action;
  addToast(toastText);
  render();
}

function undo() {
  const previous = state.history.pop();
  if (!previous) {
    addToast("没有可撤销的画布编辑", "warn");
    renderToasts();
    return;
  }
  restore(previous.snapshot);
  state.lastAction = `撤销：${previous.action}`;
  addToast(state.lastAction);
  render();
}

function addToast(text, tone = "") {
  const id = Date.now() + Math.random();
  state.toast.push({ id, text, tone });
  setTimeout(() => {
    state.toast = state.toast.filter((toast) => toast.id !== id);
    renderToasts();
  }, 3400);
}

function newBlank() {
  state.history.push({ action: "新建空白流程", snapshot: serializableState() });
  state.nodes = [];
  state.edges = [];
  state.selectedNodes.clear();
  state.selectedEdge = null;
  state.projectKind = "personal-copy";
  state.projectName = "未命名蛋白质实验";
  state.lastAction = "已新建空白 Workflow";
  addToast("空白 Workflow 已建立；可拖入 Palette 条目或在画布搜索");
  render();
}

function addNode(type, x, y, source = "画布搜索") {
  commit(`通过${source}添加“${CATALOG[type].name}”`, () => {
    const node = makeNode(type, x, y);
    state.nodes.push(node);
    state.selectedNodes = new Set([node.id]);
    state.selectedEdge = null;
  });
}

function nodeById(id) {
  return state.nodes.find((node) => node.id === id);
}

function specForNode(id) {
  const node = nodeById(id);
  return node ? CATALOG[node.type] : null;
}

function selectionFacts(nodes) {
  const compositions = nodes.filter(
    (node) => CATALOG[node.type].authoringRole === "specialized_composition",
  );
  return {
    entries: nodes.length,
    compositions: compositions.length,
    managedMembers: compositions.reduce(
      (total, node) => total + node.compositionProjection.managedMembers.length,
      0,
    ),
  };
}

function selectionLabel() {
  if (state.selectedEdge) return "已选连线 · Delete 断开";
  if (!state.selectedNodes.size) return "Shift 点击可多选";
  const facts = selectionFacts(
    state.nodes.filter((node) => state.selectedNodes.has(node.id)),
  );
  if (!facts.compositions) return `已选 ${facts.entries} 个 ordinary Nodes`;
  return `已选 ${facts.entries} 项 · ${facts.compositions} 个 composition 将整体操作`;
}

function selectNode(id, additive = false) {
  if (!additive) state.selectedNodes.clear();
  if (additive && state.selectedNodes.has(id)) state.selectedNodes.delete(id);
  else state.selectedNodes.add(id);
  state.selectedEdge = null;
  state.lastAction = `更新画布选区：${selectionLabel()}`;
  render();
}

function deleteSelection() {
  if (state.selectedEdge) {
    const selected = state.edges.find((item) => item.id === state.selectedEdge);
    commit("断开所选连线", () => {
      state.edges = state.edges.filter((item) => item.id !== state.selectedEdge);
      state.selectedEdge = null;
    }, selected ? "已断开连线；Cmd/Ctrl+Z 可恢复" : "已断开连线");
    return;
  }
  if (!state.selectedNodes.size) return;
  const ids = new Set(state.selectedNodes);
  const facts = selectionFacts(state.nodes.filter((node) => ids.has(node.id)));
  const removedEdges = state.edges.filter(
    (item) => ids.has(item.fromNode) || ids.has(item.toNode),
  ).length;
  const compositionNote = facts.compositions
    ? `；其中 ${facts.compositions} 个 specialized composition 连同 ${facts.managedMembers} 个 managed members 整体删除`
    : "";
  commit(`删除 ${facts.entries} 个画布条目及 ${removedEdges} 条连线${compositionNote}`, () => {
    state.nodes = state.nodes.filter((node) => !ids.has(node.id));
    state.edges = state.edges.filter(
      (item) => !ids.has(item.fromNode) && !ids.has(item.toNode),
    );
    state.selectedNodes.clear();
  }, `已立即删除 ${facts.entries} 个画布条目和 ${removedEdges} 条相关连线${compositionNote}；可撤销`);
}

function copySelection() {
  if (!state.selectedNodes.size) {
    addToast("请先选择要复制的画布条目", "warn");
    renderToasts();
    return;
  }
  const ids = new Set(state.selectedNodes);
  const selected = state.nodes.filter((node) => ids.has(node.id));
  const facts = selectionFacts(selected);
  state.clipboard = {
    nodes: structuredClone(selected),
    edges: structuredClone(
      state.edges.filter((item) => ids.has(item.fromNode) && ids.has(item.toNode)),
    ),
  };
  const compositionNote = facts.compositions
    ? `；${facts.compositions} 个 specialized composition 连同 ${facts.managedMembers} 个 managed members 整体复制`
    : "";
  state.lastAction = `复制 ${facts.entries} 个画布条目；保留 ${state.clipboard.edges.length} 条内部连线${compositionNote}`;
  addToast(state.lastAction);
  render();
}

function pasteSelection() {
  if (!state.clipboard) {
    addToast("剪贴板中没有流程片段", "warn");
    renderToasts();
    return;
  }
  const mapping = new Map();
  const facts = selectionFacts(state.clipboard.nodes);
  commit(
    `粘贴 ${facts.entries} 个画布条目及 ${state.clipboard.edges.length} 条内部连线`,
    () => {
      const copies = state.clipboard.nodes.map((source) => {
        const id = `${source.type}-${state.idCounter++}`;
        mapping.set(source.id, id);
        return { ...structuredClone(source), id, x: source.x + 74, y: source.y + 112 };
      });
      const internalEdges = state.clipboard.edges.map((source) => ({
        ...structuredClone(source),
        id: `edge-${state.idCounter++}`,
        fromNode: mapping.get(source.fromNode),
        toNode: mapping.get(source.toNode),
      }));
      state.nodes.push(...copies);
      state.edges.push(...internalEdges);
      state.selectedNodes = new Set(copies.map((node) => node.id));
    },
    facts.compositions
      ? "已粘贴独立流程片段；完整 composition 由后端分配新的 opaque identity，managed members 不可拆分"
      : "已粘贴独立流程片段；只复制两端均在选区内的连线",
  );
}

function toggleCollapsed(id) {
  const node = nodeById(id);
  commit(`${node.collapsed ? "展开" : "整体收起"}“${CATALOG[node.type].name}”`, () => {
    node.collapsed = !node.collapsed;
  });
}

function toggleGroup(nodeId, groupId) {
  const node = nodeById(nodeId);
  const spec = CATALOG[node.type];
  const group = spec.groups.find((item) => item.id === groupId);
  commit(`${node.openGroups[groupId] ? "收起" : "展开"}参数组“${group.name}”`, () => {
    node.openGroups[groupId] = !node.openGroups[groupId];
  });
}

function switchModel(nodeId, nextModel) {
  const node = nodeById(nodeId);
  const previous = node.selectedModel;
  commit(`模型从“${previous}”切换为“${nextModel}”`, () => {
    const ownValue = node.params.recycles ?? node.params.steps ?? "3";
    node.modelMemory[previous] = { modelSpecific: ownValue };
    node.selectedModel = nextModel;
    const remembered = node.modelMemory[nextModel]?.modelSpecific ?? "8";
    if (Object.hasOwn(node.params, "recycles")) node.params.recycles = remembered;
    if (Object.hasOwn(node.params, "steps")) node.params.steps = remembered;
  }, `已切换模型；共有参数保留，${nextModel} 的专属参数已恢复`);
}

function changeParameter(nodeId, fieldId, value) {
  const node = nodeById(nodeId);
  const old = node.params[fieldId];
  if (old === value) return;
  commit(`修改参数 ${fieldId}：${old} → ${value}`, () => {
    node.params[fieldId] = value;
  });
}

function openPromptStudio(nodeId) {
  const node = nodeById(nodeId);
  state.lastAction = `从“${CATALOG[node.type].name}”打开专用 Prompt Studio；未通过通用参数表单修改 managed members`;
  addToast("进入专用 Prompt Studio（本原型只验证画布入口）；保存或取消后返回此画布");
  render();
}

function typesCompatible(outputType, inputType) {
  return outputType === inputType;
}

function connect(fromNodeId, fromPortId, toNodeId, toPortId) {
  const fromSpec = specForNode(fromNodeId);
  const toSpec = specForNode(toNodeId);
  const output = fromSpec.outputs.find((port) => port.id === fromPortId);
  const input = toSpec.inputs.find((port) => port.id === toPortId);
  if (!output || !input || !typesCompatible(output.type, input.type)) {
    addToast(`不能连接：${output?.type ?? "未知"} 与 ${input?.type ?? "未知"} 不兼容`, "danger");
    state.lastAction = "不兼容端口拒绝连接";
    state.connecting = null;
    render();
    return;
  }
  const occupied = state.edges.find(
    (item) => item.toNode === toNodeId && item.toPort === toPortId,
  );
  commit(
    occupied ? "自动替换单连接输入的原连线" : "连接兼容端口",
    () => {
      state.edges = state.edges.filter(
        (item) => !(item.toNode === toNodeId && item.toPort === toPortId),
      );
      state.edges.push(edge(fromNodeId, fromPortId, toNodeId, toPortId));
      state.connecting = null;
    },
    occupied ? "输入仅接受一条连线：已自动替换旧连线（可撤销）" : "已连接兼容端口",
  );
}

function disconnectInput(nodeId, portId) {
  const attached = state.edges.filter(
    (item) => item.toNode === nodeId && item.toPort === portId,
  );
  if (!attached.length) return;
  commit("从已连接输入端口拖到空白处断开", () => {
    state.edges = state.edges.filter(
      (item) => !(item.toNode === nodeId && item.toPort === portId),
    );
    state.connecting = null;
  }, "已从输入端口断开连线；可撤销");
}

function setVariant(next) {
  state.variant = next;
  const url = new URL(location.href);
  url.searchParams.set("variant", next);
  history.replaceState({}, "", url);
  state.lastAction = `切换到方案 ${next} · ${VARIANTS[next].name}`;
  render();
}

function cycleVariant(direction) {
  const keys = Object.keys(VARIANTS);
  const current = keys.indexOf(state.variant);
  setVariant(keys[(current + direction + keys.length) % keys.length]);
}

function catalogGroups() {
  const key = state.taxonomy;
  return Object.entries(CATALOG).reduce((groups, [type, spec]) => {
    const group = spec[key];
    groups[group] ??= [];
    groups[group].push({ type, spec });
    return groups;
  }, {});
}

function renderLibrary() {
  return `
    <aside class="library" aria-label="Authoring Palette">
      <div class="library-header">
        <div class="eyebrow">Authoring Palette</div>
        <h2>添加操作或专用编辑器</h2>
        <div class="segmented" role="tablist" aria-label="节点分类方式">
          <button data-taxonomy="purpose" class="${state.taxonomy === "purpose" ? "active" : ""}">研究用途</button>
          <button data-taxonomy="provider" class="${state.taxonomy === "provider" ? "active" : ""}">模块 / 提供方</button>
        </div>
        <p class="library-note">只列 ordinary Nodes 与 specialized entries。composition 的 managed members 不在 Palette 或搜索中单独出现。</p>
      </div>
      <div class="catalog">
        ${Object.entries(catalogGroups())
          .map(
            ([group, items]) => `
              <section class="catalog-group">
                <div class="catalog-group-title"><span>▾</span>${group}</div>
                ${items
                  .map(
                    ({ type, spec }) => `
                      <button class="catalog-item" data-catalog-type="${type}" title="拖入画布">
                        <span class="catalog-icon">${spec.code}</span>
                        <span class="catalog-copy">
                          <span class="catalog-name">${spec.name}</span>
                          <span class="catalog-provider">${state.taxonomy === "purpose" ? spec.provider : spec.purpose}</span>
                          ${spec.authoringRole === "specialized_composition" ? '<span class="catalog-role">Specialized entry</span>' : ""}
                        </span>
                        <span class="drag-handle">⠿</span>
                      </button>`,
                  )
                  .join("")}
              </section>`,
          )
          .join("")}
      </div>
    </aside>`;
}

function nodeStyle(node) {
  let { x, y } = node;
  const ordinary = CATALOG[node.type].authoringRole === "ordinary_node";
  if (state.variant === "B" && ordinary) {
    y += (Number(node.id.match(/(\d+)$/)?.[1] ?? 0) % 2) * 92;
  }
  if (state.variant === "C" && ordinary) {
    y += (Number(node.id.match(/(\d+)$/)?.[1] ?? 0) % 3) * 42;
  }
  return `left:${x}px;top:${y}px`;
}

function portMarkup(node, port, direction) {
  const connected = state.edges.some((item) =>
    direction === "input"
      ? item.toNode === node.id && item.toPort === port.id
      : item.fromNode === node.id && item.fromPort === port.id,
  );
  let compatibility = "";
  if (state.connecting && direction === "input") {
    const source = specForNode(state.connecting.fromNode).outputs.find(
      (item) => item.id === state.connecting.fromPort,
    );
    compatibility = typesCompatible(source.type, port.type) ? "compatible" : "incompatible";
  }
  return `
    <button class="port ${direction} ${connected ? "connected" : ""} ${compatibility}"
      data-node-id="${node.id}" data-port-id="${port.id}" data-port-direction="${direction}"
      title="${direction === "output" ? "拖到兼容输入端口" : connected ? "拖到画布空白处断开" : port.type}">
      <span class="port-dot"></span>
      <span>${port.name}<span class="port-type">${port.type}</span></span>
    </button>`;
}

function renderField(node, field) {
  const value = node.params[field.id] ?? field.value;
  const unit = field.id === "distance" ? "Å" : "";
  return `
    <label class="field">
      <span>${field.label}</span>
      <span class="${unit ? "unit-field" : ""}">
        <input data-parameter-node="${node.id}" data-parameter-field="${field.id}" value="${value}" />
        ${unit ? `<span>${unit}</span>` : ""}
      </span>
    </label>`;
}

function renderSpecializedComposition(node, spec) {
  const projection = node.compositionProjection;
  const sourceDisposition = projection.managedMembers.length
    ? `当前 ${projection.source} 已在 composition 内 materialize；三个 external source roles 保持可选。`
    : "blank 无需 Port；尚未 materialize，可从三个 optional exposed input roles 或 Prompt Studio 开始。";
  return `
    <div class="composition-panel">
      <div class="composition-role-row">
        <span class="composition-role">Specialized composition</span>
        <span>专用入口拥有完整 Prompt authoring</span>
      </div>
      <div class="composition-sources">
        <span>Source disposition</span>
        <small>${sourceDisposition}</small>
      </div>
      <div class="composition-summary">
        <span>${projection.source}</span>
        <strong>${projection.summary}</strong>
      </div>
      <button class="edit-composition" data-edit-composition="${node.id}">
        <span>编辑 ProteinPrompt</span>
        <small>打开 Prompt Studio →</small>
      </button>
      <section class="managed-members" aria-label="只读 managed members">
        <div class="managed-heading">
          <span>Materialized members</span>
          <strong>只读 · ${projection.managedMembers.length}</strong>
        </div>
        ${
          projection.managedMembers.length
            ? projection.managedMembers
                .map(
                  (member) => `<div class="managed-member">
                    <span class="managed-lock">⌁</span>
                    <span><strong>${member.name}</strong><small>${member.contract}</small><em>${member.parameters}</em></span>
                  </div>`,
                )
                .join("")
            : '<div class="managed-empty">尚未 materialize；先在 Prompt Studio 完成 preview 与 apply。</div>'
        }
        <p>实例投影由此 composition 整体拥有；不可单独选择、修改、复制或删除。</p>
      </section>
    </div>`;
}

function renderNode(node, index) {
  const spec = CATALOG[node.type];
  const specialized = spec.authoringRole === "specialized_composition";
  const compositionMaterialized = specialized && node.compositionProjection.managedMembers.length > 0;
  return `
    <article class="node role-${spec.authoringRole} ${node.collapsed ? "collapsed" : ""} ${state.selectedNodes.has(node.id) ? "selected" : ""}"
      style="${nodeStyle(node)}" data-node-id="${node.id}" aria-label="${spec.name}">
      <header class="node-header" data-drag-node="${node.id}">
        <span class="node-index">${String(index + 1).padStart(2, "0")}</span>
        <span class="node-title"><strong>${spec.name}</strong><span>${specialized ? "Specialized composition · 专用编辑" : `${spec.purpose} · ${spec.provider}`}</span></span>
        <span class="node-header-actions">
          <span class="status-dot ${specialized ? (compositionMaterialized ? "materialized" : "pending") : node.status}" title="${specialized ? (compositionMaterialized ? "Composition 已 materialize" : "尚未 materialize") : "可运行"}"></span>
          <button class="collapse-button" data-collapse-node="${node.id}" title="${node.collapsed ? "展开画布条目" : "整体收起：只保留名称"}">${node.collapsed ? "+" : "−"}</button>
        </span>
      </header>
      ${
        node.collapsed
          ? ""
          : `<div class="node-body">
              ${
                spec.models.length
                  ? `<div class="model-row">
                      <div class="model-label"><span>执行模型</span>${spec.recommended ? '<span class="tiny-badge">推荐 · 标准未裁决</span>' : ""}</div>
                      <select data-model-node="${node.id}" aria-label="${spec.name}的执行模型">
                        ${spec.models.map((model) => `<option ${model === node.selectedModel ? "selected" : ""}>${model}</option>`).join("")}
                      </select>
                    </div>`
                  : ""
              }
              <div class="ports-row">
                <div class="port-stack input">${spec.inputs.map((port) => portMarkup(node, port, "input")).join("") || '<span class="port-type">无输入</span>'}</div>
                <div class="port-stack output">${spec.outputs.map((port) => portMarkup(node, port, "output")).join("") || '<span class="port-type">无输出</span>'}</div>
              </div>
              ${
                specialized
                  ? renderSpecializedComposition(node, spec)
                  : `<div class="parameter-groups">
                      ${spec.groups
                        .map(
                          (group) => `<section class="parameter-group">
                            <button class="group-toggle" data-group-node="${node.id}" data-group-id="${group.id}">
                              <span>${group.name}</span><span>${node.openGroups[group.id] ? "▾" : "▸"}</span>
                            </button>
                            ${node.openGroups[group.id] ? `<div class="parameter-fields">${group.fields.map((field) => renderField(node, field)).join("")}</div>` : ""}
                          </section>`,
                        )
                        .join("")}
                    </div>`
              }
            </div>`
      }
    </article>`;
}

function renderSearch() {
  if (!state.search) return "";
  const query = state.search.query.toLowerCase();
  const results = Object.entries(CATALOG).filter(([, spec]) =>
    `${spec.name} ${spec.purpose} ${spec.provider}`.toLowerCase().includes(query),
  );
  return `
    <div class="search-popover" style="left:${state.search.screenX}px;top:${state.search.screenY}px" role="dialog" aria-label="搜索 Palette entries">
      <input id="node-search" value="${state.search.query}" placeholder="搜索 ordinary Nodes 与 specialized entries…" autocomplete="off" />
      <div class="search-results">
        ${results
          .map(
            ([type, spec]) => `<button class="search-result" data-search-add="${type}"><span>${spec.name}</span><small>${spec.authoringRole === "specialized_composition" ? "Specialized entry" : "Ordinary Node"} · ${spec.provider}</small></button>`,
          )
          .join("") || '<div class="state-callout">没有匹配的 Palette entry</div>'}
      </div>
    </div>`;
}

function renderStateInspector() {
  const compactNodes = state.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    authoringRole: CATALOG[node.type].authoringRole,
    capabilityProjection:
      CATALOG[node.type].authoringRole === "specialized_composition"
        ? {
            sourceKinds: CATALOG[node.type].sourceKinds,
            exposedInputs: CATALOG[node.type].inputs.map((port) => ({
              role: port.id,
              portType: port.type,
            })),
            exposedOutputs: CATALOG[node.type].outputs.map((port) => ({
              role: port.id,
              portType: port.type,
            })),
          }
        : undefined,
    compositionSource: node.compositionProjection?.source,
    compositionSummary: node.compositionProjection?.summary,
    managedMembers:
      CATALOG[node.type].authoringRole === "specialized_composition"
        ? node.compositionProjection.managedMembers.map((member) => ({
            contract: member.contract,
            parameters: member.parameters,
          }))
        : undefined,
    model: node.selectedModel,
    collapsed: node.collapsed,
    openGroups: Object.keys(node.openGroups).filter((key) => node.openGroups[key]),
  }));
  const compactEdges = state.edges.map((item) =>
    `${item.fromNode}.${item.fromPort} → ${item.toNode}.${item.toPort}`,
  );
  const clipboardFacts = state.clipboard ? selectionFacts(state.clipboard.nodes) : null;
  return `
    <details class="state-inspector" ${state.inspectorOpen ? "open" : ""}>
      <summary><span>原型状态 · 每步可核对</span><span>${state.nodes.length} entries / ${state.edges.length}E</span></summary>
      <div class="state-body">
        <div class="state-callout">${state.lastAction}</div>
        <div class="state-grid">
          <span>方案</span><strong>${state.variant} · ${VARIANTS[state.variant].name}</strong>
          <span>分类</span><strong>${state.taxonomy === "purpose" ? "研究用途" : "模块 / 提供方"}</strong>
          <span>选区</span><strong>${state.selectedEdge ?? ([...state.selectedNodes].join(", ") || "无")}</strong>
          <span>撤销深度</span><strong>${state.history.length} 步</strong>
          <span>剪贴板</span><strong>${clipboardFacts ? `${clipboardFacts.entries} entries${clipboardFacts.compositions ? ` / ${clipboardFacts.compositions} composition` : ""} / ${state.clipboard.edges.length}E` : "空"}</strong>
        </div>
        <pre class="state-json">${escapeHtml(JSON.stringify({ nodes: compactNodes, edges: compactEdges }, null, 2))}</pre>
      </div>
    </details>`;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function render() {
  document.body.className = `variant-${state.variant}`;
  document.querySelector("#app").innerHTML = `
    <div class="app-shell">
      <header class="topbar">
        <div class="brand"><span class="brand-mark">PW</span>Protein Workbench</div>
        <div class="project-title">
          <button class="button" id="project-menu">项目 ▾</button>
          <strong>${state.projectName}</strong>
          <span class="badge">${state.projectKind === "default" ? "只读默认示例" : "自动保存 · 内存示意"}</span>
        </div>
        <div class="top-actions">
          <button class="button" id="load-default">打开默认示例</button>
          <button class="button" id="new-blank">新建空白</button>
          <button class="button primary">运行摘要（非本原型）</button>
        </div>
      </header>
      <main class="main-grid">
        ${renderLibrary()}
        <section class="canvas-shell" aria-label="Workflow authoring 画布">
          <div class="canvas-toolbar">
            <div class="canvas-actions">
              <button class="icon-button" id="undo" title="撤销（Cmd/Ctrl+Z）" ${state.history.length ? "" : "disabled"}>↶</button>
              <button class="icon-button" id="copy" title="复制所选画布条目；composition 始终整体复制（Cmd/Ctrl+C）" ${state.selectedNodes.size ? "" : "disabled"}>⧉</button>
              <button class="icon-button" id="paste" title="粘贴流程片段（Cmd/Ctrl+V）" ${state.clipboard ? "" : "disabled"}>▣</button>
              <button class="icon-button" id="delete" title="立即删除；composition 始终整体删除（Delete/Backspace）" ${state.selectedNodes.size || state.selectedEdge ? "" : "disabled"}>⌫</button>
            </div>
            <span class="toolbar-divider"></span>
            <button class="button" id="open-search">⌕ 搜索 Palette</button>
            <span class="selection-copy">${selectionLabel()}</span>
          </div>
          <div class="canvas" id="canvas">
            <div class="canvas-world" id="canvas-world" data-variant-note="${VARIANTS[state.variant].note}">
              <svg class="edges" id="edges"></svg>
              ${state.nodes.map(renderNode).join("")}
              ${
                state.nodes.length
                  ? ""
                  : `<div class="empty-state"><h3>空白 Workflow</h3><p>从左侧拖入 ordinary Node 或 specialized entry，或在画布空白处双击搜索。managed members 只由 composition 建立。</p><button class="button primary" id="empty-search">搜索并添加第一个条目</button></div>`
              }
            </div>
          </div>
        </section>
      </main>
    </div>
    ${SHOW_PROTOTYPE_CONTROLS ? '<div class="throwaway-flag">Throwaway prototype · not production</div>' : ""}
    <div class="toast-stack" id="toast-stack"></div>
    ${SHOW_PROTOTYPE_CONTROLS ? renderStateInspector() : ""}
    ${
      SHOW_PROTOTYPE_CONTROLS
        ? `<nav class="switcher" aria-label="原型方案切换器">
            <button id="variant-prev" aria-label="上一个方案">←</button>
            <div class="switcher-label">${state.variant} · ${VARIANTS[state.variant].name}</div>
            <button id="variant-next" aria-label="下一个方案">→</button>
          </nav>`
        : ""
    }
    ${renderSearch()}`;
  bindEvents();
  renderToasts();
  requestAnimationFrame(drawEdges);
}

function renderToasts() {
  const container = document.querySelector("#toast-stack");
  if (!container) return;
  container.innerHTML = state.toast
    .map((toast) => `<div class="toast ${toast.tone}">${toast.text}</div>`)
    .join("");
}

function openSearch(screenX, screenY, worldX, worldY) {
  state.search = {
    screenX: Math.min(screenX, innerWidth - 314),
    screenY: Math.min(screenY, innerHeight - 360),
    worldX,
    worldY,
    query: "",
  };
  state.lastAction = "打开 Palette 搜索；结果仅含 ordinary Nodes 与 specialized entries";
  render();
  document.querySelector("#node-search")?.focus();
}

function bindEvents() {
  document.querySelector("#load-default")?.addEventListener("click", loadDefault);
  document.querySelector("#new-blank")?.addEventListener("click", newBlank);
  document.querySelector("#undo")?.addEventListener("click", undo);
  document.querySelector("#copy")?.addEventListener("click", copySelection);
  document.querySelector("#paste")?.addEventListener("click", pasteSelection);
  document.querySelector("#delete")?.addEventListener("click", deleteSelection);
  document.querySelector("#variant-prev")?.addEventListener("click", () => cycleVariant(-1));
  document.querySelector("#variant-next")?.addEventListener("click", () => cycleVariant(1));
  document.querySelector(".state-inspector")?.addEventListener("toggle", (event) => {
    state.inspectorOpen = event.currentTarget.open;
  });

  document.querySelectorAll("[data-taxonomy]").forEach((button) => {
    button.addEventListener("click", () => {
      state.taxonomy = button.dataset.taxonomy;
      state.lastAction = `Palette 切换为${state.taxonomy === "purpose" ? "研究用途" : "模块 / 提供方"}分类`;
      render();
    });
  });

  document.querySelectorAll("[data-catalog-type]").forEach((button) => {
    button.addEventListener("pointerdown", startCatalogDrag);
    button.addEventListener("dblclick", () => addNode(button.dataset.catalogType, 330, 520, "左侧列表双击"));
  });

  const canvas = document.querySelector("#canvas");
  const world = document.querySelector("#canvas-world");
  canvas?.addEventListener("dblclick", (event) => {
    if (event.target.closest(".node") || event.target.closest(".canvas-toolbar")) return;
    const rect = world.getBoundingClientRect();
    openSearch(event.clientX, event.clientY, event.clientX - rect.left, event.clientY - rect.top);
  });
  canvas?.addEventListener("click", (event) => {
    if (event.target.closest(".node") || event.target.closest(".edge-hit")) return;
    state.selectedNodes.clear();
    state.selectedEdge = null;
    state.lastAction = "清除画布选区";
    render();
  });

  const openSearchFromButton = () => {
    const rect = world.getBoundingClientRect();
    openSearch(280, 118, 360 - rect.left, 220 - rect.top);
  };
  document.querySelector("#open-search")?.addEventListener("click", openSearchFromButton);
  document.querySelector("#empty-search")?.addEventListener("click", openSearchFromButton);

  document.querySelectorAll(".node").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (event.target.closest("button, select, input")) return;
      selectNode(element.dataset.nodeId, event.shiftKey);
    });
  });

  document.querySelectorAll("[data-collapse-node]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleCollapsed(button.dataset.collapseNode);
    });
  });

  document.querySelectorAll("[data-edit-composition]").forEach((button) => {
    button.addEventListener("click", () => openPromptStudio(button.dataset.editComposition));
  });

  document.querySelectorAll("[data-group-node]").forEach((button) => {
    button.addEventListener("click", () => toggleGroup(button.dataset.groupNode, button.dataset.groupId));
  });

  document.querySelectorAll("[data-model-node]").forEach((select) => {
    select.addEventListener("change", () => switchModel(select.dataset.modelNode, select.value));
  });

  document.querySelectorAll("[data-parameter-node]").forEach((input) => {
    input.addEventListener("change", () => changeParameter(input.dataset.parameterNode, input.dataset.parameterField, input.value));
  });

  document.querySelectorAll("[data-port-direction]").forEach((port) => {
    port.addEventListener("pointerdown", startConnection);
  });

  document.querySelectorAll("[data-drag-node]").forEach((header) => {
    header.addEventListener("pointerdown", startNodeDrag);
  });

  document.querySelector("#node-search")?.addEventListener("input", (event) => {
    state.search.query = event.target.value;
    render();
    const input = document.querySelector("#node-search");
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });
  document.querySelectorAll("[data-search-add]").forEach((button) => {
    button.addEventListener("click", () => {
      const { worldX, worldY } = state.search;
      const type = button.dataset.searchAdd;
      state.search = null;
      addNode(type, worldX - 125, worldY - 22, "画布搜索");
    });
  });
}

function startCatalogDrag(event) {
  state.catalogDrag = {
    type: event.currentTarget.dataset.catalogType,
    startX: event.clientX,
    startY: event.clientY,
    moved: false,
  };
  document.addEventListener("pointermove", moveCatalogDrag);
  document.addEventListener("pointerup", endCatalogDrag, { once: true });
}

function moveCatalogDrag(event) {
  if (!state.catalogDrag) return;
  state.catalogDrag.moved =
    state.catalogDrag.moved ||
    Math.hypot(event.clientX - state.catalogDrag.startX, event.clientY - state.catalogDrag.startY) > 8;
}

function endCatalogDrag(event) {
  document.removeEventListener("pointermove", moveCatalogDrag);
  const drag = state.catalogDrag;
  state.catalogDrag = null;
  if (!drag?.moved) return;
  const canvas = document.querySelector("#canvas");
  const world = document.querySelector("#canvas-world");
  const canvasRect = canvas.getBoundingClientRect();
  if (
    event.clientX < canvasRect.left ||
    event.clientX > canvasRect.right ||
    event.clientY < canvasRect.top ||
    event.clientY > canvasRect.bottom
  ) {
    addToast("拖拽取消：请放到画布区域", "warn");
    renderToasts();
    return;
  }
  const worldRect = world.getBoundingClientRect();
  addNode(
    drag.type,
    event.clientX - worldRect.left - 125,
    event.clientY - worldRect.top - 22,
    "左侧列表拖入",
  );
}

function startNodeDrag(event) {
  if (event.target.closest("button, input, select")) return;
  const id = event.currentTarget.dataset.dragNode;
  const node = nodeById(id);
  const startSnapshot = serializableState();
  state.draggingNode = {
    id,
    startX: event.clientX,
    startY: event.clientY,
    nodeX: node.x,
    nodeY: node.y,
    snapshot: startSnapshot,
    moved: false,
  };
  document.addEventListener("pointermove", moveNode);
  document.addEventListener("pointerup", endNodeDrag, { once: true });
}

function moveNode(event) {
  if (!state.draggingNode) return;
  const node = nodeById(state.draggingNode.id);
  node.x = Math.max(20, state.draggingNode.nodeX + event.clientX - state.draggingNode.startX);
  node.y = Math.max(90, state.draggingNode.nodeY + event.clientY - state.draggingNode.startY);
  state.draggingNode.moved = true;
  const element = document.querySelector(`[data-node-id="${node.id}"]`);
  if (element) element.style.cssText = nodeStyle(node);
  drawEdges();
}

function endNodeDrag(event) {
  document.removeEventListener("pointermove", moveNode);
  if (state.draggingNode?.moved) {
    state.history.push({ action: "移动画布条目", snapshot: state.draggingNode.snapshot });
    if (state.projectKind === "default") {
      state.projectKind = "personal-copy";
      state.projectName = "我的实验 · 默认示例副本";
      addToast("已自动建立个人副本；默认示例保持不变");
    }
    state.lastAction = `移动“${CATALOG[nodeById(state.draggingNode.id).type].name}”`;
    addToast("画布条目位置已更新；可撤销");
    state.draggingNode = null;
    render();
    return;
  }
  state.draggingNode = null;
}

function startConnection(event) {
  event.stopPropagation();
  const port = event.currentTarget;
  const direction = port.dataset.portDirection;
  const nodeId = port.dataset.nodeId;
  const portId = port.dataset.portId;
  if (direction === "input") {
    const attached = state.edges.find(
      (item) => item.toNode === nodeId && item.toPort === portId,
    );
    if (!attached) return;
    state.connecting = {
      fromNode: attached.fromNode,
      fromPort: attached.fromPort,
      detachInput: { nodeId, portId },
      x: event.clientX,
      y: event.clientY,
    };
  } else {
    state.connecting = {
      fromNode: nodeId,
      fromPort: portId,
      detachInput: null,
      x: event.clientX,
      y: event.clientY,
    };
  }
  document.addEventListener("pointermove", moveConnection);
  document.addEventListener("pointerup", endConnection, { once: true });
  document.querySelectorAll('.port[data-port-direction="input"]').forEach((input) => {
    const inputSpec = specForNode(input.dataset.nodeId).inputs.find(
      (item) => item.id === input.dataset.portId,
    );
    const outputSpec = specForNode(state.connecting.fromNode).outputs.find(
      (item) => item.id === state.connecting.fromPort,
    );
    input.classList.add(typesCompatible(outputSpec.type, inputSpec.type) ? "compatible" : "incompatible");
  });
  state.lastAction = "正在拖动连线；兼容输入端口已高亮";
  drawEdges();
}

function moveConnection(event) {
  if (!state.connecting) return;
  state.connecting.x = event.clientX;
  state.connecting.y = event.clientY;
  drawEdges();
}

function endConnection(event) {
  document.removeEventListener("pointermove", moveConnection);
  if (!state.connecting) return;
  const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.port[data-port-direction="input"]');
  if (target) {
    const current = { ...state.connecting };
    state.connecting = null;
    connect(current.fromNode, current.fromPort, target.dataset.nodeId, target.dataset.portId);
    return;
  }
  if (state.connecting.detachInput) {
    const { nodeId, portId } = state.connecting.detachInput;
    state.connecting = null;
    disconnectInput(nodeId, portId);
    return;
  }
  state.connecting = null;
  state.lastAction = "连线拖动取消：未落在兼容输入端口";
  addToast("未连接：请拖到高亮的兼容输入端口", "warn");
  render();
}

function pathBetween(x1, y1, x2, y2) {
  const distance = Math.max(54, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + distance} ${y1}, ${x2 - distance} ${y2}, ${x2} ${y2}`;
}

function drawEdges() {
  const svg = document.querySelector("#edges");
  const world = document.querySelector("#canvas-world");
  if (!svg || !world) return;
  const worldRect = world.getBoundingClientRect();
  const chunks = state.edges.map((item) => {
    const from = document.querySelector(`.port.output[data-node-id="${item.fromNode}"][data-port-id="${item.fromPort}"]`);
    const to = document.querySelector(`.port.input[data-node-id="${item.toNode}"][data-port-id="${item.toPort}"]`);
    const fromNode = document.querySelector(`.node[data-node-id="${item.fromNode}"]`);
    const toNode = document.querySelector(`.node[data-node-id="${item.toNode}"]`);
    if (!fromNode || !toNode) return "";
    const a = (from?.querySelector(".port-dot") ?? fromNode).getBoundingClientRect();
    const b = (to?.querySelector(".port-dot") ?? toNode).getBoundingClientRect();
    const x1 = (from ? a.left + a.width / 2 : a.right) - worldRect.left;
    const y1 = a.top + a.height / 2 - worldRect.top;
    const x2 = (to ? b.left + b.width / 2 : b.left) - worldRect.left;
    const y2 = b.top + b.height / 2 - worldRect.top;
    const d = pathBetween(x1, y1, x2, y2);
    const output = specForNode(item.fromNode).outputs.find((port) => port.id === item.fromPort);
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    const label = output.type;
    const width = label.length * 5.5 + 12;
    return `<path class="edge-line ${state.selectedEdge === item.id ? "selected" : ""}" d="${d}" />
      <path class="edge-hit" data-edge-id="${item.id}" d="${d}" />
      <rect class="edge-label-bg" x="${mx - width / 2}" y="${my - 8}" width="${width}" height="16" rx="7" />
      <text class="edge-label" x="${mx}" y="${my + 3}" text-anchor="middle">${label}</text>`;
  });
  if (state.connecting) {
    const from = document.querySelector(`.port.output[data-node-id="${state.connecting.fromNode}"][data-port-id="${state.connecting.fromPort}"]`);
    if (from) {
      const a = from.querySelector(".port-dot").getBoundingClientRect();
      const x1 = a.left + a.width / 2 - worldRect.left;
      const y1 = a.top + a.height / 2 - worldRect.top;
      const x2 = state.connecting.x - worldRect.left;
      const y2 = state.connecting.y - worldRect.top;
      chunks.push(`<path class="connection-preview" d="${pathBetween(x1, y1, x2, y2)}" />`);
    }
  }
  svg.innerHTML = chunks.join("");
  svg.querySelectorAll("[data-edge-id]").forEach((path) => {
    path.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selectedEdge = path.dataset.edgeId;
      state.selectedNodes.clear();
      state.lastAction = "已选择连线；Delete/Backspace 可断开";
      render();
    });
  });
}

document.addEventListener("keydown", (event) => {
  const editing = event.target.closest("input, textarea, select, [contenteditable]");
  if (!editing && event.key === "ArrowLeft") {
    event.preventDefault();
    cycleVariant(-1);
  }
  if (!editing && event.key === "ArrowRight") {
    event.preventDefault();
    cycleVariant(1);
  }
  if (!editing && (event.key === "Delete" || event.key === "Backspace")) {
    event.preventDefault();
    deleteSelection();
  }
  if (!editing && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undo();
  }
  if (!editing && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "c") {
    event.preventDefault();
    copySelection();
  }
  if (!editing && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "v") {
    event.preventDefault();
    pasteSelection();
  }
  if (event.key === "Escape" && state.search) {
    state.search = null;
    render();
  }
});

addEventListener("resize", () => requestAnimationFrame(drawEdges));
loadDefault();
