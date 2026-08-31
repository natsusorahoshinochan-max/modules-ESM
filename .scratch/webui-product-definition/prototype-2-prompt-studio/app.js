// THROWAWAY UI PROTOTYPE — not production code.
// Three Prompt Studio information-architecture variants, switchable via
// ?variant= on this prototype-only page.

const VARIANTS = {
  A: {
    name: "Tri-pane balance",
    note: "A · 均衡三域 / 同屏判断",
    question: "三处同权时，用户能否稳定跟踪选择与编辑上下文？",
  },
  B: {
    name: "Residue ledger",
    note: "B · 残基账本 / 共享轴优先",
    question: "矩阵成为主表后，三维同步是否仍然足够清楚？",
    adopted: true,
  },
  C: {
    name: "Selection lens",
    note: "C · 选择透镜 / 局部聚焦",
    question: "局部放大与全局轴并存时，用户会不会丢失整体位置？",
  },
};

const ENTRIES = {
  blank: {
    short: "空白",
    label: "空白 · A36 + B18",
    source: "新建空白 Prompt",
    detail: "双链；所有轨道初始未指定",
    defaultMode: "layout",
  },
  fasta: {
    short: "FASTA",
    label: "FASTA · ubiquitin",
    source: "从序列开始",
    detail: "Chain A · 76 residues；仅 sequence 已指定",
    defaultMode: "condition",
  },
  pdb: {
    short: "PDB",
    label: "PDB · 1CRN（示意样本）",
    source: "从结构开始",
    detail: "Chain A · 46 residues；结构几何仅作同步交互示意",
    defaultMode: "condition",
  },
  existing: {
    short: "已有 Prompt",
    label: "已有 Prompt · motif design（示意）",
    source: "打开已有 ProteinPrompt",
    detail: "双链 · 稀疏多轨道条件与 3 个 function intervals（示意）",
    defaultMode: "condition",
  },
};

const MODES = {
  layout: {
    name: "布局",
    verb: "编辑残基轴",
    detail: "插入 / 删除残基与链",
  },
  condition: {
    name: "条件",
    verb: "编辑轨道条件",
    detail: "在各轨道内直接操作",
  },
  structure: {
    name: "结构",
    verb: "编辑残基坐标",
    detail: "以残基集合进行刚体操作",
  },
};

const TRACKS = {
  sequence: { label: "Sequence", short: "SEQ", unit: "residue" },
  coordinates: { label: "Coordinates", short: "XYZ", unit: "assigned / Mask" },
  ss: { label: "Secondary structure", short: "SS8", unit: "state" },
  sasa: { label: "SASA", short: "SASA", unit: "Å²" },
  function: { label: "Function annotations", short: "FUNC", unit: "interval" },
};

const CHANGE_STATES = ["source", "current", "changed", "cleared", "inserted", "pending-delete"];

const SHOW_PROTOTYPE_CONTROLS = ["127.0.0.1", "localhost"].includes(location.hostname);
const variantFromUrl = new URLSearchParams(location.search).get("variant")?.toUpperCase();

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "B",
  entry: "pdb",
  mode: "condition",
  residues: [],
  annotations: [],
  sourceResidueHandles: new Set(),
  sourceAnnotationTuples: [],
  residueTombstones: [],
  annotationTombstones: [],
  operationDiagnostics: [],
  selected: new Set(),
  anchor: null,
  viewerHidden: new Set(),
  activeTrack: "sequence",
  hiddenTracks: new Set(),
  summaryOpen: true,
  entryMenuOpen: false,
  sequenceAction: "指定",
  sequenceValue: "G",
  insertInitial: "mask",
  insertCount: 1,
  undoStack: [],
  draftPreview: null,
  savePreview: null,
  workflowRevision: 17,
  dirty: false,
  lastAction: "从结构开始：已建立 1CRN 示例 Prompt",
  toast: [],
};

let backendHandleCounter = 1;

function backendOpaqueHandle() {
  const handle = `opaque-residue-${backendHandleCounter}`;
  backendHandleCounter += 1;
  return handle;
}

function residue({ handle = backendOpaqueHandle(), chain, number = null, sourceNumber = number, sequence = null, sourceSequence = sequence, coordinates = false, ss = null, sasa = null, state: residueState = "source", trackStates = {} }) {
  const defaultTrackState = residueState === "inserted" ? "inserted" : "source";
  return {
    id: handle,
    chain,
    sourceNumber,
    sequence,
    coordinates,
    ss,
    sasa,
    sourceValues: {
      sequence: residueState === "inserted" ? null : sourceSequence,
      coordinates: residueState === "inserted" ? false : coordinates,
      ss: residueState === "inserted" ? null : ss,
      sasa: residueState === "inserted" ? null : sasa,
    },
    state: residueState,
    trackStates: {
      sequence: trackStates.sequence ?? defaultTrackState,
      coordinates: trackStates.coordinates ?? defaultTrackState,
      ss: trackStates.ss ?? defaultTrackState,
      sasa: trackStates.sasa ?? defaultTrackState,
    },
  };
}

function buildPrompt(entry) {
  if (entry === "blank") {
    return {
      residues: [
        ...Array.from({ length: 36 }, (_, index) => residue({ chain: "A", number: index + 1, state: "inserted" })),
        ...Array.from({ length: 18 }, (_, index) => residue({ chain: "B", number: index + 1, state: "inserted" })),
      ],
      annotations: [],
    };
  }

  if (entry === "fasta") {
    const sequence = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG";
    return {
      residues: [...sequence].map((letter, index) => residue({ chain: "A", number: index + 1, sequence: letter })),
      annotations: [],
    };
  }

  if (entry === "pdb") {
    const sequence = "TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN";
    const ssPattern = "--EEE-TT--HHHHHHH-TT--EEE--TT---HHHHH--TT---";
    return {
      residues: [...sequence].map((letter, index) =>
        residue({
          chain: "A",
          number: index + 1,
          sequence: letter,
          coordinates: true,
          ss: ssPattern[index] ?? "-",
          sasa: Math.round(8 + 46 * Math.abs(Math.sin(index * 0.73))),
        }),
      ),
      annotations: [
        { chain: "A", start: 3, end: 8, label: "function label（示意）", state: "source" },
      ],
    };
  }

  const sequenceA = "MKTIIALSYIFCLVFADYKDDDDKGGHPEPTDEHALKQLAEAGVEVEVK";
  const sequenceB = "GSSGSSAPVNTKDIQLVEEA";
  const residues = [
    ...[...sequenceA].map((letter, index) => {
      const position = index + 1;
      const hasCoordinates = position >= 12 && position <= 38;
      return residue({
        chain: "A",
        number: position,
        sequence: position >= 35 && position <= 37 ? "G" : position % 11 === 0 ? null : letter,
        sourceSequence: letter,
        coordinates: hasCoordinates,
        ss: position >= 14 && position <= 31 ? (position % 6 < 4 ? "H" : "-") : null,
        sasa: position % 4 === 0 ? Math.round(18 + 55 * Math.abs(Math.sin(position))) : null,
        state: position === 12 ? "current" : "source",
        trackStates: {
          sequence: position === 22 ? "cleared" : position >= 35 && position <= 37 ? "changed" : position === 12 ? "current" : "source",
        },
      });
    }),
    ...[...sequenceB].map((letter, index) =>
      residue({
        chain: "B",
        number: index + 1,
        sequence: index % 6 === 0 ? null : letter,
        coordinates: false,
        ss: index >= 4 && index <= 12 ? "E" : null,
        sasa: null,
        state: index < 2 ? "inserted" : "source",
      }),
    ),
  ];
  return {
    residues,
    annotations: [
      { chain: "A", start: 15, end: 21, label: "binding region（示意）", state: "source" },
      { chain: "A", start: 31, end: 38, label: "motif（示意）", state: "source" },
      { chain: "B", start: 5, end: 14, label: "interaction region（示意）", state: "inserted" },
    ],
  };
}

function attachAnnotationHandles(prompt) {
  return prompt.annotations.map((annotation) => ({
    ...annotation,
    startHandle: prompt.residues.find((item) => item.chain === annotation.chain && item.sourceNumber === annotation.start)?.id,
    endHandle: prompt.residues.find((item) => item.chain === annotation.chain && item.sourceNumber === annotation.end)?.id,
  }));
}

function initializeEntry(entry, announce = false) {
  const prompt = buildPrompt(entry);
  state.entry = entry;
  state.mode = ENTRIES[entry].defaultMode;
  state.residues = prompt.residues.map((item, index) => ({ ...item, projectionOrder: index + 1 }));
  state.annotations = attachAnnotationHandles(prompt);
  state.sourceResidueHandles = new Set(state.residues.filter((item) => item.state !== "inserted").map((item) => item.id));
  state.sourceAnnotationTuples = cloneAnnotations(state.annotations.filter((annotation) => annotation.state === "source"));
  state.residueTombstones = [];
  state.annotationTombstones = [];
  state.operationDiagnostics = [];
  state.selected = new Set();
  state.anchor = null;
  state.viewerHidden = new Set();
  state.activeTrack = "sequence";
  state.hiddenTracks = new Set();
  state.sequenceAction = "指定";
  state.sequenceValue = "G";
  state.insertInitial = "mask";
  state.insertCount = 1;
  state.undoStack = [];
  state.draftPreview = null;
  state.savePreview = null;
  state.dirty = false;
  state.entryMenuOpen = false;
  state.lastAction = `${ENTRIES[entry].source}：${ENTRIES[entry].detail}`;
  if (announce) addToast(`${ENTRIES[entry].label} 已加载；默认进入${MODES[state.mode].name}模式`);
}

function hasCoordinates() {
  return state.residues.some((item) => item.coordinates);
}

function residueById(id) {
  return state.residues.find((item) => item.id === id);
}

function indexById(id) {
  return state.residues.findIndex((item) => item.id === id);
}

function residueLocator(item) {
  if (item.state === "pending-delete" && item.locator) return item.locator;
  const chainItems = state.residues.filter((candidate) => candidate.chain === item.chain);
  return `${item.chain}:${chainItems.indexOf(item) + 1}`;
}

function selectedResidues(ids = state.selected) {
  return state.residues.filter((item) => ids.has(item.id));
}

function cloneResidues(items) {
  return items.map((item) => ({ ...item, sourceValues: { ...item.sourceValues }, trackStates: { ...item.trackStates } }));
}

function cloneAnnotations(items) {
  return items.map((item) => ({ ...item }));
}

function pushUndo(label) {
  state.undoStack.push({
    label,
    residues: cloneResidues(state.residues),
    annotations: cloneAnnotations(state.annotations),
    residueTombstones: cloneResidues(state.residueTombstones),
    annotationTombstones: cloneAnnotations(state.annotationTombstones),
    operationDiagnostics: state.operationDiagnostics.map((item) => ({ ...item })),
    selected: [...state.selected],
    anchor: state.anchor,
    viewerHidden: [...state.viewerHidden],
    dirty: state.dirty,
  });
}

function undoPromptEdit() {
  const previous = state.undoStack.pop();
  if (!previous) {
    addToast("没有可撤销的原型编辑", "warn");
    renderToasts();
    return;
  }
  state.residues = cloneResidues(previous.residues);
  state.annotations = cloneAnnotations(previous.annotations);
  state.residueTombstones = cloneResidues(previous.residueTombstones);
  state.annotationTombstones = cloneAnnotations(previous.annotationTombstones);
  state.operationDiagnostics = previous.operationDiagnostics.map((item) => ({ ...item }));
  state.selected = new Set(previous.selected);
  state.anchor = previous.anchor;
  state.viewerHidden = new Set(previous.viewerHidden);
  state.draftPreview = null;
  state.savePreview = null;
  state.dirty = previous.dirty;
  state.lastAction = `撤销：${previous.label}`;
  addToast(state.lastAction);
  render();
}

function chainSummary() {
  const counts = new Map();
  state.residues.forEach((item) => counts.set(item.chain, (counts.get(item.chain) ?? 0) + 1));
  return [...counts.entries()].map(([chain, count]) => `${chain}${count}`).join(" + ");
}

function projectedResidues() {
  return [...state.residues, ...state.residueTombstones]
    .sort((left, right) => left.projectionOrder - right.projectionOrder);
}

function insertionProjectionOrders(afterId, count) {
  const after = residueById(afterId);
  const lower = after.projectionOrder;
  const upper = projectedResidues().find((item) => item.projectionOrder > lower)?.projectionOrder ?? lower + 1;
  const step = (upper - lower) / (count + 1);
  return Array.from({ length: count }, (_, index) => lower + step * (index + 1));
}

function countAssigned(track) {
  if (track === "sequence") return state.residues.filter((item) => item.sequence !== null).length;
  if (track === "coordinates") return state.residues.filter((item) => item.coordinates).length;
  if (track === "ss") return state.residues.filter((item) => item.ss !== null).length;
  if (track === "sasa") return state.residues.filter((item) => item.sasa !== null).length;
  return state.annotations.length;
}

function formatSelection(ids = state.selected) {
  if (ids.size === 0) return "未选择残基";
  const ordered = selectedResidues(ids);
  const groups = [];
  let start = ordered[0];
  let previous = ordered[0];
  for (const item of ordered.slice(1)) {
    const contiguous = item.chain === previous.chain && indexById(item.id) === indexById(previous.id) + 1;
    if (!contiguous) {
      groups.push(formatLocatorRange(start, previous));
      start = item;
    }
    previous = item;
  }
  groups.push(formatLocatorRange(start, previous));
  return `${groups.join(" + ")} · ${ordered.length} residues`;
}

function formatLocatorRange(start, end) {
  if (start.id === end.id) return residueLocator(start);
  return `${residueLocator(start)}–${residueLocator(end).split(":")[1]}`;
}

function selectionKinds() {
  if (state.selected.size === 0) return "无选择";
  const ordered = selectedResidues();
  if (ordered.length === 1) return "单残基";
  let runs = 1;
  for (let index = 1; index < ordered.length; index += 1) {
    if (ordered[index].chain !== ordered[index - 1].chain || indexById(ordered[index].id) !== indexById(ordered[index - 1].id) + 1) runs += 1;
  }
  return runs === 1 ? "连续区间" : `${runs} 个不连续区间`;
}

function setSelection(ids, source) {
  state.selected = new Set(ids.filter((id) => residueById(id)));
  state.anchor = ids.at(-1) ?? null;
  state.draftPreview = null;
  state.lastAction = `${source}：${formatSelection()}`;
  render();
}

function selectPreset(kind) {
  if (kind === "single") {
    const item = state.residues[Math.min(17, state.residues.length - 1)];
    setSelection([item.id], "选择单残基");
    return;
  }
  if (kind === "continuous") {
    const sameChain = state.residues.filter((item) => item.chain === state.residues[0].chain);
    const items = sameChain.slice(Math.min(11, sameChain.length - 1), Math.min(20, sameChain.length));
    setSelection(items.map((item) => item.id), "选择连续区间");
    return;
  }
  const firstChain = state.residues.filter((item) => item.chain === state.residues[0].chain);
  const items = [...firstChain.slice(7, 10), ...firstChain.slice(Math.min(30, firstChain.length - 3), Math.min(33, firstChain.length))];
  setSelection(items.map((item) => item.id), "选择不连续区间");
}

function handleResidueClick(id, event, source) {
  if (event.shiftKey && state.anchor) {
    const from = indexById(state.anchor);
    const to = indexById(id);
    const [start, end] = from < to ? [from, to] : [to, from];
    setSelection(state.residues.slice(start, end + 1).map((item) => item.id), `${source} Shift 区间选择`);
    return;
  }
  if (event.metaKey || event.ctrlKey) {
    const next = new Set(state.selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelection([...next], `${source}追加选择`);
    state.anchor = id;
    return;
  }
  setSelection([id], `${source}选择`);
}

function addToast(text, tone = "") {
  const id = Date.now() + Math.random();
  state.toast.push({ id, text, tone });
  setTimeout(() => {
    state.toast = state.toast.filter((toast) => toast.id !== id);
    renderToasts();
  }, 3200);
}

function renderToasts() {
  const root = document.querySelector(".toasts");
  if (!root) return;
  root.innerHTML = state.toast.map((toast) => `<div class="toast ${toast.tone}">${toast.text}</div>`).join("");
}

function switchMode(mode) {
  if (mode === "structure" && !hasCoordinates()) {
    addToast("当前 Prompt 没有坐标；结构模式不可用，但 Prompt 仍然合法", "warn");
    renderToasts();
    return;
  }
  state.mode = mode;
  state.draftPreview = null;
  state.lastAction = `切换到${MODES[mode].name}模式；轨道显示保持不变`;
  render();
}

function setVariant(key, updateUrl = true) {
  state.variant = key;
  if (updateUrl) {
    const url = new URL(location.href);
    url.searchParams.set("variant", key);
    history.replaceState({}, "", url);
  }
  state.lastAction = `切换原型方案：${VARIANTS[key].note}`;
  render();
}

function cycleVariant(direction) {
  const keys = Object.keys(VARIANTS);
  const current = keys.indexOf(state.variant);
  setVariant(keys[(current + direction + keys.length) % keys.length]);
}

function setEntry(entry) {
  initializeEntry(entry, true);
  render();
}

function setActiveTrack(track) {
  state.activeTrack = track;
  state.draftPreview = null;
  state.lastAction = `当前编辑对象：${TRACKS[track].label}`;
  render();
}

function setSequenceAction(action) {
  state.activeTrack = "sequence";
  state.sequenceAction = action;
  state.mode = ["插入", "删除"].includes(action) ? "layout" : "condition";
  state.draftPreview = null;
  state.lastAction = `Sequence 轨道直接操作：${action}`;
  render();
}

function toggleViewerSelected() {
  const coordinateIds = [...state.selected].filter((id) => residueById(id)?.coordinates);
  if (coordinateIds.length === 0) {
    addToast("请先选择具有 coordinates 的残基；viewer 显隐不改变 Prompt", "warn");
    renderToasts();
    return;
  }
  const shouldHide = coordinateIds.some((id) => !state.viewerHidden.has(id));
  coordinateIds.forEach((id) => shouldHide ? state.viewerHidden.add(id) : state.viewerHidden.delete(id));
  state.lastAction = `${shouldHide ? "临时隐藏" : "重新显示"} ${coordinateIds.length} 个 viewer residues；ProteinPrompt 未改变`;
  addToast(`${state.lastAction}`);
  render();
}

function deletionImpact(items) {
  const ids = new Set(items.map((item) => item.id));
  const affectedAnnotations = state.annotations.filter((annotation) =>
    items.some((item) => item.id === annotation.startHandle || item.id === annotation.endHandle),
  );
  return {
    sequence: items.filter((item) => item.sequence !== null).length,
    coordinates: items.filter((item) => item.coordinates).length,
    ss: items.filter((item) => item.ss !== null).length,
    sasa: items.filter((item) => item.sasa !== null).length,
    functionTuples: affectedAnnotations.map((item) => ({ ...item })),
    viewerHidden: [...state.viewerHidden].filter((id) => ids.has(id)).length,
  };
}

function locatorOnly(ids) {
  return formatSelection(new Set(ids)).replace(/ · \d+ residues$/, "");
}

function annotationLocator(annotation) {
  const [startLocator, endLocator] = annotationEndpointLocators(annotation);
  if (startLocator.split(":")[0] === endLocator.split(":")[0]) return `${startLocator}–${endLocator.split(":")[1]}`;
  return `${startLocator}–${endLocator}`;
}

function annotationEndpointLocators(annotation) {
  if (annotation.state === "pending-delete" && annotation.startLocator && annotation.endLocator) {
    return [annotation.startLocator, annotation.endLocator];
  }
  const start = residueById(annotation.startHandle);
  const end = residueById(annotation.endHandle);
  if (!start || !end) return [`${annotation.chain}:${annotation.start}`, `${annotation.chain}:${annotation.end}`];
  return [residueLocator(start), residueLocator(end)];
}

function annotationTuple(annotation) {
  const [startLocator, endLocator] = annotationEndpointLocators(annotation);
  return `(${annotation.label}, ${startLocator}, ${endLocator})`;
}

function annotationTombstone(annotation) {
  const [startLocator, endLocator] = annotationEndpointLocators(annotation);
  return { ...annotation, startLocator, endLocator, state: "pending-delete" };
}

function annotationContains(annotation, item) {
  const startIndex = indexById(annotation.startHandle);
  const endIndex = indexById(annotation.endHandle);
  const itemIndex = indexById(item.id);
  return item.chain === annotation.chain && itemIndex >= startIndex && itemIndex <= endIndex;
}

function deletionDiagnostics(items, impact) {
  const diagnostics = [];
  const lostValues = impact.sequence + impact.coordinates + impact.ss + impact.sasa;
  if (lostValues > 0) {
    diagnostics.push({
      severity: "warning",
      locator: locatorOnly(items.map((item) => item.id)),
      message: `删除将移除 ${lostValues} 个已指定 track values`,
    });
  }
  impact.functionTuples.forEach((annotation) => diagnostics.push({
      severity: "warning",
      locator: annotationLocator(annotation),
      message: `Function tuple ${annotationTuple(annotation)} 将进入 pending-delete`,
    }));
  return diagnostics;
}

// Prototype backend stub: preview owns allocation and returns opaque handles.
function backendPreviewInsertion(after, count) {
  return Array.from({ length: count }, () => ({ handle: backendOpaqueHandle(), chain: after.chain }));
}

function createSequencePreview(kind) {
  const countField = document.querySelector('[data-sequence-field="insert-count"]');
  const valueField = document.querySelector('[data-sequence-field="insert-value"], [data-sequence-field="sequence-value"]');
  if (countField) state.insertCount = Math.max(1, Math.min(12, Number(countField.value) || 1));
  if (valueField) state.sequenceValue = valueField.value;
  const items = selectedResidues();
  if (items.length === 0) {
    addToast("请先选择插入位置或要编辑的残基", "warn");
    renderToasts();
    return;
  }
  if (kind === "insert") {
    const after = items.at(-1);
    const count = Math.max(1, Math.min(12, Number(state.insertCount) || 1));
    state.insertCount = count;
    state.draftPreview = {
      kind,
      track: "sequence",
      selection: formatSelection(),
      afterId: after.id,
      afterLocator: residueLocator(after),
      chain: after.chain,
      count,
      backendResidues: backendPreviewInsertion(after, count),
      initialSequence: state.insertInitial,
      sequenceValue: state.insertInitial === "assigned" ? state.sequenceValue : null,
      beforeLength: state.residues.length,
      afterLength: state.residues.length + count,
    };
    state.lastAction = `Backend preview：在 ${residueLocator(after)} 后新增 ${count} 个残基`;
    render();
    return;
  }
  if (kind === "delete") {
    if (items.length === state.residues.length) {
      addToast("此原型不演示删除全部残基；请保留至少一个可定位残基", "warn");
      renderToasts();
      return;
    }
    const impact = deletionImpact(items);
    state.draftPreview = {
      kind,
      track: "sequence",
      ids: items.map((item) => item.id),
      selection: formatSelection(),
      beforeLength: state.residues.length,
      afterLength: state.residues.length - items.length,
      impact,
      diagnostics: deletionDiagnostics(items, impact),
    };
    state.lastAction = `预览删除：${formatSelection()}`;
    render();
    return;
  }
  state.draftPreview = {
    kind,
    track: "sequence",
    ids: items.map((item) => item.id),
    selection: formatSelection(),
    sequenceValue: kind === "specify" ? state.sequenceValue : null,
  };
  state.lastAction = `预览 Sequence ${kind === "specify" ? "指定" : "Mask"}：${formatSelection()}`;
  render();
}

function applySequencePreview() {
  const preview = state.draftPreview;
  if (!preview || !["insert", "delete", "specify", "mask"].includes(preview.kind)) return;

  if (preview.kind === "insert") {
    const insertionIndex = indexById(preview.afterId);
    pushUndo(`插入 ${preview.count} 个残基`);
    const projectionOrders = insertionProjectionOrders(preview.afterId, preview.count);
    const inserted = preview.backendResidues.map((projection, index) => ({
      ...residue({
        handle: projection.handle,
        chain: projection.chain,
        sourceNumber: null,
        sequence: preview.initialSequence === "assigned" ? preview.sequenceValue : null,
        state: "inserted",
      }),
      projectionOrder: projectionOrders[index],
    }));
    state.residues.splice(insertionIndex + 1, 0, ...inserted);
    state.selected = new Set(inserted.map((item) => item.id));
    state.anchor = inserted.at(-1)?.id ?? null;
    state.draftPreview = null;
    state.savePreview = null;
    state.dirty = true;
    state.lastAction = `已应用 backend preview：插入 ${inserted.length} 个残基 · ${formatSelection()}`;
    addToast(`${state.lastAction}；其他轨道均为 Mask`);
    render();
    return;
  }

  const targetIds = new Set(preview.ids.filter((id) => residueById(id)));
  if (targetIds.size === 0) {
    addToast("预览中的残基已不存在，请重新选择", "warn");
    state.draftPreview = null;
    state.savePreview = null;
    render();
    return;
  }

  if (preview.kind === "delete") {
    if (targetIds.size === state.residues.length) {
      addToast("此原型不演示删除全部残基", "warn");
      return;
    }
    pushUndo(`删除 ${targetIds.size} 个残基`);
    const firstDeletedIndex = Math.min(...[...targetIds].map(indexById));
    const deletedItems = state.residues.filter((item) => targetIds.has(item.id));
    deletedItems
      .filter((item) => state.sourceResidueHandles.has(item.id))
      .forEach((item) => state.residueTombstones.push({
        ...cloneResidues([item])[0],
        locator: residueLocator(item),
        state: "pending-delete",
        trackStates: { sequence: "pending-delete", coordinates: "pending-delete", ss: "pending-delete", sasa: "pending-delete" },
      }));
    preview.impact.functionTuples
      .filter(isSourceAnnotation)
      .forEach((tuple) => state.annotationTombstones.push(annotationTombstone(tuple)));
    state.residues = state.residues.filter((item) => !targetIds.has(item.id));
    targetIds.forEach((id) => state.viewerHidden.delete(id));
    state.annotations = state.annotations.filter((annotation) =>
      !preview.impact.functionTuples.some((tuple) => sameAnnotationTuple(tuple, annotation)),
    );
    state.operationDiagnostics.push(...preview.diagnostics.map((item) => ({ ...item })));
    const neighbor = state.residues[Math.min(firstDeletedIndex, state.residues.length - 1)];
    state.selected = new Set(neighbor ? [neighbor.id] : []);
    state.anchor = neighbor?.id ?? null;
    state.draftPreview = null;
    state.savePreview = null;
    state.dirty = true;
    state.lastAction = `已删除 ${targetIds.size} 个残基；各轨道已按共享轴同步`;
    addToast(`${state.lastAction}；可撤销`);
    render();
    return;
  }

  pushUndo(`${preview.kind === "specify" ? "指定" : "Mask"} ${targetIds.size} 个 Sequence 值`);
  state.residues = state.residues.map((item) => {
    if (!targetIds.has(item.id)) return item;
    return {
      ...item,
      sequence: preview.kind === "specify" ? preview.sequenceValue : null,
      trackStates: {
        ...item.trackStates,
        sequence: item.state === "inserted"
          ? "inserted"
          : preview.kind === "specify"
            ? preview.sequenceValue === item.sourceValues.sequence ? "current" : "changed"
            : item.sourceValues.sequence === null ? "current" : "cleared",
      },
    };
  });
  state.draftPreview = null;
  state.savePreview = null;
  state.dirty = true;
  state.lastAction = `已${preview.kind === "specify" ? `指定为 ${preview.sequenceValue}` : "Mask"} ${targetIds.size} 个 Sequence 值`;
  addToast(`${state.lastAction}；可撤销`);
  render();
}

function createPreview(intent) {
  if (state.selected.size === 0) {
    addToast("请先选择单残基、连续区间或不连续区间", "warn");
    renderToasts();
    return;
  }
  state.draftPreview = {
    mode: state.mode,
    intent,
    track: state.activeTrack,
    selection: formatSelection(),
  };
  state.lastAction = `建立未应用预览：${intent} · ${TRACKS[state.activeTrack].label}`;
  render();
}

function createFunctionPreview(action) {
  const items = selectedResidues();
  if (items.length === 0) {
    addToast("请先选择 Function tuple 的 residue locator", "warn");
    renderToasts();
    return;
  }
  const affected = state.annotations.filter((annotation) =>
    items.some((item) => annotationContains(annotation, item)),
  );
  const locator = locatorOnly(items.map((item) => item.id));
  const first = items[0];
  const last = items.at(-1);
  const sameChain = new Set(items.map((item) => item.chain)).size === 1 && first.chain === last.chain;
  const orderedEndpoints = sameChain && indexById(first.id) <= indexById(last.id);
  const insertedTuple = {
    label: "new function label（示意）",
    chain: first.chain,
    startHandle: first.id,
    endHandle: last.id,
    locator,
    state: "inserted",
  };
  const pendingTuples = action === "insert" ? [] : affected.filter(isSourceAnnotation);
  const diagnostics = [];
  if (!sameChain) diagnostics.push({ severity: "error", locator, message: "Function interval 的全部 residues 与 endpoints 必须属于同一 chain" });
  if (sameChain && !orderedEndpoints) diagnostics.push({ severity: "error", locator, message: "Function interval 的 start locator 必须位于 end locator 之前" });
  if (action !== "insert" && pendingTuples.length === 0) diagnostics.push({ severity: "error", locator, message: "所选范围没有可删除的 source tuple" });
  pendingTuples.forEach((annotation) => diagnostics.push({
    severity: "warning",
    locator: annotationLocator(annotation),
    message: `原 tuple ${annotationTuple(annotation)} 将进入 pending-delete`,
  }));
  state.draftPreview = {
    kind: `function-${action}`,
    track: "function",
    selection: formatSelection(),
    functionRemovedTuples: action === "insert" ? [] : pendingTuples.map((annotation) => ({ ...annotation })),
    functionPendingTuples: action === "insert" ? [] : pendingTuples.map((annotation) => ({ ...annotation })),
    functionInsertedTuples: action === "delete" ? [] : [insertedTuple],
    diagnostics,
  };
  state.lastAction = `Backend preview：Function ${action} 以完整 tuple 对应`;
  render();
}

function applyFunctionPreview() {
  const preview = state.draftPreview;
  pushUndo(`应用 ${preview.kind} tuple preview`);
  preview.functionPendingTuples.forEach((tuple) => {
    state.annotationTombstones.push(annotationTombstone(tuple));
  });
  state.annotations = state.annotations.filter((annotation) =>
    !(annotation.state === "source" && preview.functionRemovedTuples.some((tuple) => sameAnnotationTuple(tuple, annotation))),
  );
  state.annotations.push(...preview.functionInsertedTuples.map((tuple) => ({ ...tuple })));
  state.operationDiagnostics.push(...preview.diagnostics.map((item) => ({ ...item })));
  state.draftPreview = null;
  state.savePreview = null;
  state.dirty = true;
  state.lastAction = `已应用 Function tuple preview：${preview.kind.replace("function-", "")}`;
  addToast(`${state.lastAction}；可撤销`);
  render();
}

function toggleTrack(track) {
  if (state.hiddenTracks.has(track)) state.hiddenTracks.delete(track);
  else state.hiddenTracks.add(track);
  state.lastAction = `${state.hiddenTracks.has(track) ? "暂时隐藏" : "显示"}${TRACKS[track].label} 行`;
  render();
}

function projectionStateCounts() {
  const counts = Object.fromEntries(CHANGE_STATES.map((key) => [key, 0]));
  state.residues.forEach((item) => {
    counts[item.state] += 1;
    Object.values(item.trackStates).forEach((trackState) => { counts[trackState] += 1; });
  });
  state.annotations.forEach((annotation) => { counts[annotation.state] += 1; });
  state.residueTombstones.forEach((item) => {
    counts[item.state] += 1;
    Object.values(item.trackStates).forEach((trackState) => { counts[trackState] += 1; });
  });
  state.annotationTombstones.forEach((annotation) => { counts[annotation.state] += 1; });
  return counts;
}

function hasBlockingDiagnostics(preview) {
  return preview.diagnostics.some((item) => item.severity === "error");
}

function buildSavePreview() {
  const stateCounts = projectionStateCounts();
  return {
    digest: `preview-r${state.workflowRevision}-${state.entry}-${state.residues.length}-${state.undoStack.length}-${state.residueTombstones.length}-${state.annotationTombstones.length}`,
    applyIntent: "replace",
    normalizedDocument: true,
    diagnostics: state.operationDiagnostics.map((item) => ({ ...item })),
    stateCounts,
    summary: `${chainSummary()} · ${state.residues.length} current residues · ${state.annotations.length} current Function tuples`,
    tombstones: {
      residues: state.residueTombstones.map((item) => item.locator),
      functionTuples: state.annotationTombstones.map(annotationTuple),
    },
  };
}

function rebaseAfterReplace() {
  state.residues = state.residues.map((item) => ({
    ...item,
    state: "source",
    sourceValues: { sequence: item.sequence, coordinates: item.coordinates, ss: item.ss, sasa: item.sasa },
    trackStates: { sequence: "source", coordinates: "source", ss: "source", sasa: "source" },
  }));
  state.annotations = state.annotations.map((annotation) => ({ ...annotation, state: "source" }));
  state.sourceResidueHandles = new Set(state.residues.map((item) => item.id));
  state.sourceAnnotationTuples = cloneAnnotations(state.annotations);
  state.residueTombstones = [];
  state.annotationTombstones = [];
  state.operationDiagnostics = [];
  state.undoStack = [];
}

function savePrompt() {
  if (state.draftPreview) {
    state.lastAction = "请先应用或关闭局部 preview，再建立或确认保存 preview";
    addToast(state.lastAction, "warn");
    render();
    return;
  }
  if (!state.savePreview) {
    state.savePreview = buildSavePreview();
    state.lastAction = `Backend preview 已返回：${state.savePreview.digest}`;
    addToast("preview 已一次返回 normalized document、六态、summary 与全部 diagnostics");
    render();
    return;
  }
  if (hasBlockingDiagnostics(state.savePreview)) {
    state.lastAction = "apply(replace) 未发布：请先修正 error diagnostics";
    addToast(state.lastAction, "warn");
    render();
    return;
  }
  const confirmedDigest = state.savePreview.digest;
  state.workflowRevision += 1;
  state.dirty = false;
  state.savePreview = null;
  rebaseAfterReplace();
  state.lastAction = `已确认 ${confirmedDigest}；apply(replace) 写回 Workflow Draft r${state.workflowRevision}`;
  addToast(`Workflow Draft r${state.workflowRevision} 已返回；managed composition 已 replace`);
  render();
}

function renderSavePreview() {
  const preview = state.savePreview;
  if (!preview) return "";
  const localPreviewOpen = Boolean(state.draftPreview);
  const blocked = localPreviewOpen || hasBlockingDiagnostics(preview);
  const blockMessage = localPreviewOpen
    ? "存在未应用的局部 preview；当前 digest 不可确认"
    : "存在 error diagnostic；apply(replace) 不可确认";
  return `
    <section class="save-preview-panel" aria-label="Backend authoring preview">
      <header><div><span>OPEN ✓ → PREVIEW ✓ → APPLY(REPLACE)</span><strong>确认 backend preview 后写回 Workflow</strong></div><code>${preview.digest}</code></header>
      <div class="save-preview-summary"><b>normalized authoring document</b><span>${preview.summary}</span></div>
      <div class="save-state-counts">${CHANGE_STATES.map((key) => `<span><b>${key}</b> ${preview.stateCounts[key]}</span>`).join("")}</div>
      <div class="save-tombstones"><b>pending-delete tombstones</b><span>residues：${preview.tombstones.residues.length ? preview.tombstones.residues.join("、") : "0"}</span><span>Function：${preview.tombstones.functionTuples.length ? preview.tombstones.functionTuples.join("、") : "0"}</span></div>
      ${renderDiagnostics(preview.diagnostics)}
      <footer><span>${blocked ? blockMessage : "apply 接收此 normalized document + confirmed preview digest；intent = replace"}</span><div><button class="button ghost" data-action="clear-save-preview">返回编辑</button><button class="button primary" data-action="save" ${blocked ? "disabled" : ""}>确认 preview 并 replace</button></div></footer>
    </section>
  `;
}

function renderTopbar() {
  const localPreviewOpen = Boolean(state.draftPreview);
  const saveBlocked = localPreviewOpen || (state.savePreview && hasBlockingDiagnostics(state.savePreview));
  return `
    <header class="topbar">
      <div class="brand"><span class="brand-mark">PW</span><div><strong>Prompt Studio</strong><small>PROTOTYPE 2 · THROWAWAY</small></div></div>
      <div class="prompt-heading">
        <span class="crumb">Workflow / 编写 ProteinPrompt</span>
        <strong>${ENTRIES[state.entry].label}</strong>
        <span class="legal-badge">${hasCoordinates() ? "含坐标" : "无坐标 · 合法 Prompt"}</span>
        <span class="contract-flow">open ✓ → ${state.savePreview ? "preview ✓" : "preview"} → apply(replace)</span>
      </div>
      <div class="top-actions">
        <button class="button ghost" data-action="cancel">取消</button>
        <button class="button ghost" data-action="undo" ${state.undoStack.length ? "" : "disabled"}>撤销${state.undoStack.length ? ` (${state.undoStack.length})` : ""}</button>
        <button class="button" data-action="summary">整份 Prompt 摘要</button>
        <button class="button primary" data-action="save" ${saveBlocked ? "disabled" : ""}>${localPreviewOpen ? "先应用/关闭局部 preview" : state.savePreview ? "确认 replace 写回 Workflow" : "Preview 保存"}</button>
      </div>
    </header>
  `;
}

function renderEntryBar() {
  return `
    <section class="entry-mode-bar">
      <div class="entry-picker">
        <span class="bar-label">四种同等级入口</span>
        <div class="entry-options">
          ${Object.entries(ENTRIES).map(([key, entry]) => `<button class="entry-button ${state.entry === key ? "active" : ""}" data-entry="${key}"><span>${entry.short}</span><small>${entry.source}</small></button>`).join("")}
        </div>
        <span class="entry-rule">入口只决定初始内容，不限制后续编辑</span>
      </div>
      <div class="mode-picker">
        <span class="bar-label">当前模式</span>
        ${Object.entries(MODES).map(([key, mode]) => {
          const unavailable = key === "structure" && !hasCoordinates();
          return `<button class="mode-button ${state.mode === key ? "active" : ""} ${unavailable ? "unavailable" : ""}" data-mode="${key}" aria-disabled="${unavailable}"><span>${mode.name}</span><small>${unavailable ? "暂无坐标" : mode.verb}</small></button>`;
        }).join("")}
        <span class="mode-rule">模式只改变可执行操作；不会隐藏或丢失其他轨道</span>
      </div>
    </section>
  `;
}

function renderSelectionBar() {
  return `
    <section class="selection-bar">
      <div class="selection-current"><span class="selection-icon">◎</span><div><small>${selectionKinds()} · 三处同步</small><strong>${formatSelection()}</strong></div></div>
      <div class="selection-presets">
        <span>快速走查：</span>
        <button data-select-preset="single">单个 18</button>
        <button data-select-preset="continuous">连续 12–20</button>
        <button data-select-preset="discontinuous">不连续 8–10 + 31–33</button>
        <button data-action="clear-selection">清除</button>
      </div>
      <span class="selection-help">点击单选 · Shift 连选 · Cmd/Ctrl 追加</span>
    </section>
  `;
}

function structurePoints() {
  const visible = state.residues.filter((item) => item.coordinates && !state.viewerHidden.has(item.id));
  return visible.map((item, index) => {
    const x = 42 + (index % 12) * 28 + Math.sin(index * 0.9) * 13;
    const y = 48 + Math.floor(index / 12) * 58 + Math.cos(index * 0.7) * 24;
    return { item, x, y };
  });
}

function renderStructure(compact = false) {
  if (!hasCoordinates()) return "";
  const points = structurePoints();
  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");
  return `
    <section class="surface structure-surface ${compact ? "compact" : ""}" data-surface="structure">
      <header class="surface-header">
        <div><span class="surface-kicker">左侧 · 同步区域</span><h2>三维结构</h2></div>
        <div class="surface-tools"><button title="适合视图">⊙</button><button class="viewer-state-button ${state.selected.size > 0 && [...state.selected].every((id) => state.viewerHidden.has(id)) ? "active" : ""}" data-action="toggle-viewer-selected" title="临时显示/隐藏所选残基；不写入 ProteinPrompt">◐</button></div>
      </header>
      <div class="structure-stage">
        <svg viewBox="0 0 390 250" role="img" aria-label="示意结构；残基可点击选择">
          <defs><linearGradient id="trace" x1="0" x2="1"><stop stop-color="#73d2c5"/><stop offset="1" stop-color="#b9e66b"/></linearGradient></defs>
          <polyline points="${polyline}" fill="none" stroke="url(#trace)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" opacity=".72"/>
          ${points.map(({ item, x, y }) => `<g class="structure-residue ${state.selected.has(item.id) ? "selected" : ""}" data-residue="${item.id}" tabindex="0"><circle cx="${x}" cy="${y}" r="${state.selected.has(item.id) ? 9 : 6}"/><text x="${x}" y="${y - 12}">${state.selected.has(item.id) ? residueLocator(item) : ""}</text></g>`).join("")}
        </svg>
        <div class="axis-gizmo"><b>Z</b><span>X</span><i>Y</i></div>
        <div class="structure-caption"><span>结构几何仅示意；不是来源坐标重现</span><strong>${formatSelection()}</strong></div>
      </div>
      <footer class="surface-footer"><span>选择单位：残基</span><span>Coordinates ${countAssigned("coordinates")} assigned · ${state.residues.length - countAssigned("coordinates")} Mask</span><span>${state.viewerHidden.size} viewer hidden · 临时</span></footer>
    </section>
  `;
}

function cellValue(item, track) {
  if (track === "sequence") return item.sequence ?? "MASK";
  if (track === "coordinates") return item.coordinates ? "●" : "MASK";
  if (track === "ss") return item.ss ?? "·";
  if (track === "sasa") return item.sasa ?? "·";
  return "";
}

function isAssigned(item, track) {
  if (track === "sequence") return item.sequence !== null;
  if (track === "coordinates") return item.coordinates;
  if (track === "ss") return item.ss !== null;
  if (track === "sasa") return item.sasa !== null;
  return false;
}

function residueProjectionState(item) {
  return isPendingDelete(item.id) ? "pending-delete" : item.state;
}

function trackProjectionState(item, track) {
  return isPendingDelete(item.id) ? "pending-delete" : item.trackStates[track];
}

function sameAnnotationTuple(left, right) {
  return left.label === right.label && left.startHandle === right.startHandle && left.endHandle === right.endHandle;
}

function isSourceAnnotation(annotation) {
  return annotation.state === "source";
}

function annotationProjectionState(annotation) {
  const pending = annotation.state === "source" && state.draftPreview?.functionPendingTuples?.some((tuple) => sameAnnotationTuple(tuple, annotation));
  const layoutPending = annotation.state === "source" && state.draftPreview?.kind === "delete" && state.draftPreview.impact.functionTuples.some((tuple) => sameAnnotationTuple(tuple, annotation));
  if (pending || layoutPending) return "pending-delete";
  return annotation.state;
}

function annotationAt(item) {
  return state.annotations.find((annotation) => annotationContains(annotation, item));
}

function isPendingDelete(id) {
  return state.residueTombstones.some((item) => item.id === id)
    || (state.draftPreview?.kind === "delete" && state.draftPreview.ids.includes(id));
}

function visibleResidues(focus = false) {
  const residues = projectedResidues();
  if (!focus || state.selected.size === 0) return residues;
  const indices = [...state.selected].map((id) => residues.findIndex((item) => item.id === id)).filter((index) => index >= 0);
  const start = Math.max(0, Math.min(...indices) - 5);
  const end = Math.min(residues.length, Math.max(...indices) + 6);
  return residues.slice(start, end);
}

function renderTrackLabel(track) {
  if (track === "sequence") {
    return `
      <div class="track-label sticky sequence-track-label" data-track="sequence">
        <div class="track-label-copy"><strong>Sequence</strong><small>${countAssigned("sequence")} assigned · ${state.residues.length - countAssigned("sequence")} Mask</small></div>
        <div class="inline-sequence-actions" aria-label="Sequence direct operations">
          <button class="${state.sequenceAction === "指定" ? "active" : ""}" data-sequence-action="指定">指定</button>
          <button class="${state.sequenceAction === "Mask" ? "active" : ""}" data-sequence-action="Mask">Mask</button>
          <button class="${state.sequenceAction === "插入" ? "active" : ""}" data-sequence-action="插入">＋插入</button>
          <button class="danger ${state.sequenceAction === "删除" ? "active" : ""}" data-sequence-action="删除">删除</button>
        </div>
      </div>
    `;
  }
  return `<button class="track-label sticky" data-track="${track}"><strong>${TRACKS[track].label}</strong><small>${countAssigned(track)} / ${state.residues.length} · ${TRACKS[track].unit}</small></button>`;
}

function isResidueTombstone(item) {
  return item.state === "pending-delete";
}

function matrixChainStart(residues, index) {
  return index > 0 && residues[index - 1].chain !== residues[index].chain ? "chain-start" : "";
}

function renderAxisProjectionCell(item, index, residues) {
  const locator = residueLocator(item);
  const chainStart = matrixChainStart(residues, index);
  if (isResidueTombstone(item)) {
    return `<div class="axis-cell state-pending-delete tombstone-cell ${chainStart}" title="来源 ${locator} · pending-delete · 只读删除证据"><small>源 ${item.chain}</small><strong>${locator.split(":")[1]}</strong></div>`;
  }
  return `<button class="axis-cell state-${residueProjectionState(item)} ${state.selected.has(item.id) ? "selected" : ""} ${chainStart}" data-residue="${item.id}" title="${locator}"><small>${item.chain}</small><strong>${locator.split(":")[1]}</strong></button>`;
}

function renderFunctionProjectionCell(item, index, residues) {
  const chainStart = matrixChainStart(residues, index);
  if (isResidueTombstone(item)) {
    return `<div class="track-cell function-cell state-pending-delete tombstone-cell ${chainStart}" title="来源 ${residueLocator(item)} · Function annotations · pending-delete">×</div>`;
  }
  const annotation = annotationAt(item);
  const begins = annotation && item.id === annotation.startHandle;
  const annotationState = annotation ? annotationProjectionState(annotation) : "source";
  return `<button class="track-cell function-cell ${annotation ? `assigned ribbon annotation-${annotationState}` : "unassigned"} ${begins ? "ribbon-start" : ""} ${state.selected.has(item.id) ? "selected" : ""} ${isPendingDelete(item.id) ? "state-pending-delete" : ""} ${chainStart}" data-residue="${item.id}" data-track="function" title="${annotation ? `${annotationTuple(annotation)} · ${annotationState}` : "未指定 function tuple"}">${begins ? annotation.label : annotation ? "↔" : "·"}</button>`;
}

function renderTrackProjectionCell(item, track, index, residues) {
  const chainStart = matrixChainStart(residues, index);
  if (isResidueTombstone(item)) {
    return `<div class="track-cell ${isAssigned(item, track) ? "assigned" : "unassigned masked"} state-pending-delete tombstone-cell ${chainStart}" title="来源 ${residueLocator(item)} · ${TRACKS[track].label} · pending-delete">${cellValue(item, track)}</div>`;
  }
  return `<button class="track-cell ${isAssigned(item, track) ? "assigned" : "unassigned masked"} state-${trackProjectionState(item, track)} ${state.selected.has(item.id) ? "selected" : ""} ${chainStart}" data-residue="${item.id}" data-track="${track}" title="${residueLocator(item)} · ${TRACKS[track].label} · ${trackProjectionState(item, track)} · ${isAssigned(item, track) ? "已指定" : "Mask"}">${cellValue(item, track)}</button>`;
}

function renderMatrix({ focus = false, compact = false } = {}) {
  const residues = visibleResidues(focus);
  const gridStyle = `--residue-count:${residues.length}`;
  const tracks = Object.keys(TRACKS).filter((track) => !state.hiddenTracks.has(track));
  return `
    <section class="surface matrix-surface ${focus ? "focus-matrix" : ""} ${compact ? "compact" : ""}" data-surface="matrix">
      <header class="surface-header matrix-header">
        <div><span class="surface-kicker">${focus ? "所选区域与邻近残基" : "下方 · 共享残基位置"}</span><h2>${focus ? "Selection lens" : "ProteinPrompt 残基矩阵"}</h2></div>
        <div class="matrix-meta"><span>一列 = 当前 locator 或只读删除证据</span><strong>${chainSummary()} · ${state.residues.length} current${state.residueTombstones.length ? ` · ${state.residueTombstones.length} pending-delete` : ""}</strong></div>
      </header>
      ${!hasCoordinates() ? `<div class="coordinate-notice"><b>三维区已自动收起</b><span>此 Prompt 没有坐标；不是缺少必填模板。共享残基矩阵已获得更多空间。</span></div>` : ""}
      <div class="track-controls">
        <span>轨道行：</span>
        ${Object.entries(TRACKS).map(([key, track]) => `<button class="${state.hiddenTracks.has(key) ? "off" : "on"}" data-toggle-track="${key}">${track.short}</button>`).join("")}
        <span class="track-rule">默认同时显示；手动隐藏不改变内容</span>
      </div>
      <div class="matrix-scroll">
        <div class="residue-grid axis-row" style="${gridStyle}">
          <div class="track-label sticky"><strong>Residue locators</strong><small>chain : position</small></div>
          ${residues.map((item, index) => renderAxisProjectionCell(item, index, residues)).join("")}
        </div>
        ${tracks.map((track) => {
          if (track === "function") {
            return `<div class="residue-grid track-row ${state.activeTrack === track ? "active-track" : ""}" style="${gridStyle}">
              <button class="track-label sticky" data-track="${track}"><strong>${TRACKS[track].label}</strong><small>interval ribbons · 示意 label</small></button>
              ${residues.map((item, index) => renderFunctionProjectionCell(item, index, residues)).join("")}
            </div>`;
          }
          return `<div class="residue-grid track-row ${track === "sequence" ? "sequence-row" : ""} ${state.activeTrack === track ? "active-track" : ""}" style="${gridStyle}">
            ${renderTrackLabel(track)}
            ${residues.map((item, index) => renderTrackProjectionCell(item, track, index, residues)).join("")}
          </div>`;
        }).join("")}
      </div>
      <footer class="matrix-legend">
        <span><i class="legend-mark source"></i>source</span><span><i class="legend-mark current"></i>current</span><span><i class="legend-mark changed"></i>changed</span><span><i class="legend-mark cleared"></i>cleared</span><span><i class="legend-mark inserted"></i>inserted</span><span><i class="legend-mark pending-delete"></i>pending-delete</span><span class="matrix-selection-readout">矩阵选择：<b>${formatSelection()}</b></span>
      </footer>
    </section>
  `;
}

function renderSequenceTools() {
  const selection = formatSelection();
  const action = state.sequenceAction;
  if (action === "插入") {
    return `
      <div class="tool-section operation-detail">
        <span class="section-label">Sequence · 直接插入</span>
        <strong>在选择中的最后一个 chain/residue locator 后插入</strong>
        <p>${selection}</p>
        <label class="field"><span>插入数量</span><input type="number" min="1" max="12" value="${state.insertCount}" data-sequence-field="insert-count" /></label>
        <span class="section-label inset">新增残基的 Sequence 初始状态</span>
        <div class="insert-initial-options">
          <button class="${state.insertInitial === "assigned" ? "active" : ""}" data-insert-initial="assigned">指定氨基酸</button>
          <button class="${state.insertInitial === "mask" ? "active" : ""}" data-insert-initial="mask">Mask</button>
        </div>
        ${state.insertInitial === "assigned" ? `<label class="field"><span>氨基酸（示意）</span><select data-sequence-field="insert-value">${["G", "A", "S", "V"].map((value) => `<option ${state.sequenceValue === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>` : `<div class="mask-explanation">新增残基由 backend preview 分配身份；Sequence 值为 Mask。</div>`}
        <button class="button wide" data-sequence-preview="insert">预览插入</button>
      </div>
    `;
  }
  if (action === "删除") {
    return `
      <div class="tool-section operation-detail danger-detail">
        <span class="section-label">Sequence · 直接删除</span>
        <strong>删除所选 chain/residue locator</strong>
        <p>${selection}</p>
        <div class="mask-explanation">删除会让后端重建有序残基投影并同步处理所有轨道；它不是 Sequence Mask。</div>
        <button class="button wide danger" data-sequence-preview="delete">预览删除及受影响轨道</button>
      </div>
    `;
  }
  if (action === "Mask") {
    return `
      <div class="tool-section operation-detail">
        <span class="section-label">Sequence · 直接 Mask</span>
        <strong>保留残基位置，清除 Sequence 值</strong>
        <p>${selection}</p>
        <button class="button wide" data-sequence-preview="mask">预览 Sequence Mask</button>
      </div>
    `;
  }
  return `
    <div class="tool-section operation-detail">
      <span class="section-label">Sequence · 直接指定</span>
      <strong>为所选 chain/residue locator 指定氨基酸</strong>
      <p>${selection}</p>
      <label class="field"><span>氨基酸（示意）</span><select data-sequence-field="sequence-value">${["G", "A", "S", "V"].map((value) => `<option ${state.sequenceValue === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>
      <button class="button wide" data-sequence-preview="specify">预览指定</button>
    </div>
  `;
}

function renderConditionTools() {
  if (state.activeTrack === "function") {
    return `
      <div class="tool-section operation-detail">
        <span class="section-label">Function annotations · 区间直接编辑</span>
        <strong>Function 只按完整 (label, start, end) tuple 对应</strong>
        <p>${formatSelection()}</p>
        <div class="track-direct-actions"><button data-function-action="insert">添加 tuple</button><button data-function-action="replace">替换 / 拆分 tuple</button></div>
        <button class="button wide danger" data-function-action="delete">删除 source tuple</button>
        <p class="panel-note">替换不会产生 annotation changed：旧 tuple 为 pending-delete，新 tuple 为 inserted。</p>
      </div>
    `;
  }
  return `
    <div class="tool-section operation-detail">
      <span class="section-label">${TRACKS[state.activeTrack].label} · 轨道直接编辑</span>
      <strong>此处不再经过通用操作意图面板</strong>
      <p>${formatSelection()}</p>
      <label class="field"><span>示意值</span>${state.activeTrack === "sasa" ? `<div><input value="32"/><em>Å²</em></div>` : `<select><option>选择示意值…</option><option>未裁决词表 / 值域</option></select>`}</label>
      <div class="track-direct-actions"><button data-preview-intent="指定 ${TRACKS[state.activeTrack].label}">指定所选残基</button><button data-preview-intent="Mask ${TRACKS[state.activeTrack].label}">Mask 所选残基</button></div>
      <p class="panel-note">未修改的其他轨道自动保持；本区只展示当前轨道的直接指定与 Mask。</p>
    </div>
  `;
}

function renderLayoutTools() {
  return `
    <div class="tool-section"><span class="section-label">有序残基操作</span><div class="intent-grid"><button class="intent active" data-layout-intent="插入残基">＋ 插入残基</button><button class="intent danger" data-layout-intent="删除残基">− 删除残基</button><button class="intent" data-layout-intent="编辑链">编辑链</button></div><p class="panel-note">用户只操作 chain/residue locator；backend preview 负责身份分配与全轨道重对齐。</p></div>
    <div class="tool-section"><span class="section-label">当前有序残基</span><div class="layout-summary"><b>${chainSummary()}</b><span>${state.residues.length} residues · ${new Set(state.residues.map((item) => item.chain)).size} chains</span></div></div>
  `;
}

function renderStructureTools() {
  return `
    <div class="tool-section"><span class="section-label">残基刚体操作</span><div class="transform-grid"><button data-transform="G">G <small>移动</small></button><button data-transform="R">R <small>旋转</small></button></div><div class="axis-buttons"><button data-axis="X">X</button><button data-axis="Y">Y</button><button data-axis="Z">Z</button><button class="muted" disabled>S 不支持</button></div><p class="panel-note">操作单位是当前残基集合，不提供原子选择、缩放或隐式结构优化。详细行为属于原型 5。</p></div>
  `;
}

function renderDraftPreview() {
  const preview = state.draftPreview;
  if (!preview) return "";
  if (preview.kind === "insert") {
    return `
      <div class="draft-preview actionable-preview">
        <span>未应用 · 插入预览</span>
        <strong>${preview.afterLocator} 后新增 ${preview.count} 个残基</strong>
        <div class="preview-axis-change"><b>${preview.beforeLength} residues</b><i>→</i><b>${preview.afterLength} residues</b></div>
        <p>Sequence：${preview.initialSequence === "assigned" ? `指定为 ${preview.sequenceValue}` : "Mask"}；Coordinates、SS8、SASA 与 Function 均未指定。</p>
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply" data-action="apply-sequence-preview">应用插入</button></div>
      </div>
    `;
  }
  if (preview.kind === "delete") {
    const impact = preview.impact;
    return `
      <div class="draft-preview actionable-preview delete-preview">
        <span>Backend preview · 删除</span>
        <strong>待删除 ${preview.ids.length} 个 chain/residue locators</strong>
        <p>${preview.selection}</p>
        <div class="preview-axis-change"><b>${preview.beforeLength} residues</b><i>→</i><b>${preview.afterLength} residues</b></div>
        <div class="impact-counts"><span>SEQ ${impact.sequence}</span><span>XYZ ${impact.coordinates}</span><span>SS8 ${impact.ss}</span><span>SASA ${impact.sasa}</span></div>
        <p>受影响 Function tuples：${impact.functionTuples.length ? impact.functionTuples.map(annotationTuple).join("、") : "无"}${impact.viewerHidden ? `；另移除 ${impact.viewerHidden} 个临时 viewer hidden 状态` : ""}</p>
        ${renderDiagnostics(preview.diagnostics)}
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply danger" data-action="apply-sequence-preview">确认删除</button></div>
      </div>
    `;
  }
  if (preview.kind?.startsWith("function-")) {
    const blocked = hasBlockingDiagnostics(preview);
    return `
      <div class="draft-preview actionable-preview">
        <span>Backend preview · Function tuple correspondence</span>
        <strong>${preview.selection}</strong>
        ${preview.functionPendingTuples.map((tuple) => `<p><b>pending-delete</b> ${annotationTuple(tuple)}</p>`).join("")}
        ${preview.functionInsertedTuples.map((tuple) => `<p><b>inserted</b> ${annotationTuple(tuple)}</p>`).join("")}
        ${renderDiagnostics(preview.diagnostics)}
        <div class="preview-actions"><button data-action="clear-preview">关闭预览</button><button class="apply" data-action="apply-function-preview" ${blocked ? "disabled" : ""}>${blocked ? "先修正 diagnostics" : "应用 tuple preview"}</button></div>
      </div>
    `;
  }
  if (["specify", "mask"].includes(preview.kind)) {
    return `
      <div class="draft-preview actionable-preview">
        <span>未应用 · Sequence ${preview.kind === "specify" ? "指定" : "Mask"} 预览</span>
        <strong>${preview.selection}</strong>
        <p>${preview.kind === "specify" ? `Sequence 将指定为 ${preview.sequenceValue}` : "仅 Sequence 变为 Mask；其他轨道保持不变"}</p>
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply" data-action="apply-sequence-preview">应用${preview.kind === "specify" ? "指定" : " Mask"}</button></div>
      </div>
    `;
  }
  return `<div class="draft-preview"><span>未应用 · 示意预览</span><strong>${preview.intent} ${TRACKS[preview.track].label}</strong><p>${preview.selection}</p><button data-action="clear-preview">清除预览</button></div>`;
}

function renderDiagnostics(diagnostics = []) {
  return `
    <div class="backend-diagnostics">
      <span>DIAGNOSTICS · 一次返回 ${diagnostics.length} 条</span>
      ${diagnostics.length ? `<ul>${diagnostics.map((item) => `<li class="${item.severity}"><b>${item.locator}</b><em>${item.message}</em></li>`).join("")}</ul>` : `<p>没有可定位 diagnostics</p>`}
    </div>
  `;
}

function renderEditor() {
  const selectedItems = selectedResidues();
  return `
    <aside class="surface editor-surface ${state.draftPreview ? "previewing" : ""}" data-surface="editor">
      <header class="surface-header">
        <div><span class="surface-kicker">右侧 · 联合编辑</span><h2>${MODES[state.mode].name}模式</h2></div>
        <span class="mode-chip">${MODES[state.mode].verb}</span>
      </header>
      <div class="editor-selection">
        <div><small>${selectionKinds()} · 与三维/矩阵同步</small><strong>${formatSelection()}</strong></div>
        <span>${selectedItems.length}</span>
      </div>
      <div class="track-tabs" role="tablist">
        ${Object.entries(TRACKS).map(([key, track]) => `<button class="${state.activeTrack === key ? "active" : ""}" data-track="${key}"><b>${track.short}</b><span>${countAssigned(key)} ${key === "function" ? "intervals" : "assigned"}</span></button>`).join("")}
      </div>
      <div class="editor-tools">
        ${state.mode === "structure" ? renderStructureTools() : state.activeTrack === "sequence" ? renderSequenceTools() : state.mode === "layout" ? renderLayoutTools() : renderConditionTools()}
        ${renderDraftPreview()}
      </div>
      <footer class="editor-footer"><span>当前编辑对象</span><strong>${state.mode === "structure" ? "structure coordinates" : state.activeTrack === "sequence" ? `Sequence · ${state.sequenceAction}` : state.mode === "layout" ? "chain/residue positions" : TRACKS[state.activeTrack].label}</strong></footer>
    </aside>
  `;
}

function compatibilitySummary() {
  const chains = new Set(state.residues.map((item) => item.chain)).size;
  if (chains > 1) return "当前连接 ESM-3 Binding（示意）：多链不可运行；Prompt 仍可保存";
  if (countAssigned("sequence") === 0 && countAssigned("coordinates") === 0) return "当前连接模型（示意）：可保存；运行能力由后续科学操作判断";
  return "当前连接模型兼容性（示意）：可用于后续运行检查";
}

function renderSummary(inline = false) {
  const assigned = Object.keys(TRACKS).filter((key) => key !== "function").map((key) => `${TRACKS[key].short} ${countAssigned(key)}/${state.residues.length}`);
  return `
    <section class="prompt-summary ${inline ? "inline" : ""} ${state.summaryOpen ? "open" : "closed"}">
      <div class="summary-title"><span>整份 ProteinPrompt 摘要</span><strong>${chainSummary()} · ${state.residues.length} residues</strong></div>
      <div class="summary-counts">${assigned.map((item) => `<span>${item}</span>`).join("")}<span>FUNC ${state.annotations.length} intervals</span></div>
      <div class="summary-health"><span class="ok">项目格式问题：0</span><span>${compatibilitySummary()}</span></div>
      <button data-action="summary">${state.summaryOpen ? "收起" : "展开"}</button>
    </section>
  `;
}

function renderVariantA() {
  const noStructure = !hasCoordinates();
  return `
    <main class="workspace variant-a ${noStructure ? "no-structure" : ""}">
      ${renderSelectionBar()}
      <div class="variant-question">${VARIANTS.A.question}</div>
      <div class="work-grid">
        ${renderStructure()}
        ${renderMatrix()}
        ${renderEditor()}
      </div>
      ${renderSummary()}
    </main>
  `;
}

function renderVariantB() {
  const noStructure = !hasCoordinates();
  return `
    <main class="workspace variant-b ${noStructure ? "no-structure" : ""}">
      ${renderSummary(true)}
      ${renderSelectionBar()}
      <div class="variant-question adopted">已采用 · ${VARIANTS.B.note}</div>
      <div class="work-grid">
        ${renderStructure(true)}
        ${renderMatrix({ compact: true })}
        ${renderEditor()}
      </div>
    </main>
  `;
}

function renderVariantC() {
  const noStructure = !hasCoordinates();
  return `
    <main class="workspace variant-c ${noStructure ? "no-structure" : ""}">
      ${renderSelectionBar()}
      <div class="variant-question">${VARIANTS.C.question}</div>
      <div class="work-grid">
        ${renderStructure()}
        ${renderMatrix({ focus: true })}
        ${renderEditor()}
        ${renderMatrix({ compact: true })}
      </div>
      ${renderSummary()}
    </main>
  `;
}

function serializableState() {
  return {
    prototype: "2 · Prompt Studio information architecture",
    adoptedVariant: "B · Residue ledger",
    variant: `${state.variant} · ${VARIANTS[state.variant].name}`,
    entry: `${state.entry} · ${ENTRIES[state.entry].source}`,
    mode: `${state.mode} · ${MODES[state.mode].name}`,
    activeTrack: state.activeTrack,
    selectionKind: selectionKinds(),
    selectedLocators: state.residues.filter((item) => state.selected.has(item.id)).map(residueLocator),
    prompt: {
      chains: chainSummary(),
      length: state.residues.length,
      orderedResidues: state.residues.map((item) => ({
        locator: residueLocator(item),
        state: residueProjectionState(item),
        tracks: {
          sequence: { value: item.sequence, state: trackProjectionState(item, "sequence") },
          coordinates: { value: item.coordinates ? "assigned" : "Mask", state: trackProjectionState(item, "coordinates") },
          ss: { value: item.ss, state: trackProjectionState(item, "ss") },
          sasa: { value: item.sasa, state: trackProjectionState(item, "sasa") },
        },
      })),
      assigned: Object.fromEntries(Object.keys(TRACKS).map((track) => [track, countAssigned(track)])),
      hiddenTrackRows: [...state.hiddenTracks],
      functionAnnotations: state.annotations.map((annotation) => ({ tuple: annotationTuple(annotation), state: annotationProjectionState(annotation) })),
      pendingDelete: {
        residues: state.residueTombstones.map((item) => ({
          locator: item.locator,
          state: item.state,
          tracks: Object.fromEntries(Object.entries(item.trackStates).map(([track, trackState]) => [track, { state: trackState }])),
        })),
        functionAnnotations: state.annotationTombstones.map((annotation) => ({ tuple: annotationTuple(annotation), state: annotation.state })),
      },
      hasCoordinates: hasCoordinates(),
      compatibility: compatibilitySummary(),
    },
    viewerState: {
      hiddenLocators: state.residues.filter((item) => state.viewerHidden.has(item.id)).map(residueLocator),
      persistedInProteinPrompt: false,
    },
    authoringFlow: {
      opened: true,
      preview: state.savePreview,
      nextApplyIntent: "replace",
      workflowRevision: state.workflowRevision,
      sessionDiagnostics: state.operationDiagnostics,
    },
    localDraftPreview: serializeLocalPreview(),
    undoDepth: state.undoStack.length,
    dirty: state.dirty,
    lastAction: state.lastAction,
  };
}

function serializeLocalPreview() {
  const preview = state.draftPreview;
  if (!preview) return null;
  return {
    kind: preview.kind ?? "track-preview",
    track: preview.track,
    selection: preview.selection,
    afterLocator: preview.afterLocator,
    count: preview.count,
    beforeLength: preview.beforeLength,
    afterLength: preview.afterLength,
    pendingFunctionTuples: preview.functionPendingTuples?.map(annotationTuple),
    removedFunctionTuples: preview.functionRemovedTuples?.map(annotationTuple),
    insertedFunctionTuples: preview.functionInsertedTuples?.map(annotationTuple),
    diagnostics: preview.diagnostics,
  };
}

function renderPrototypeControls() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  const variant = VARIANTS[state.variant];
  return `
    <nav class="prototype-switcher" aria-label="Prototype variant switcher">
      <button data-variant-cycle="-1" aria-label="Previous variant">←</button>
      <div><small>THROWAWAY VARIANT</small><strong>${state.variant} · ${variant.name}${variant.adopted ? ' · 已采用' : ''}</strong><span>${variant.note}</span></div>
      <button data-variant-cycle="1" aria-label="Next variant">→</button>
    </nav>
    <details class="state-inspector">
      <summary>Prototype state</summary>
      <pre>${escapeHtml(JSON.stringify(serializableState(), null, 2))}</pre>
    </details>
  `;
}

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function render() {
  document.querySelector("#app").innerHTML = `
    <div class="app-shell variant-${state.variant.toLowerCase()}">
      ${renderTopbar()}
      ${renderEntryBar()}
      ${state.variant === "A" ? renderVariantA() : state.variant === "B" ? renderVariantB() : renderVariantC()}
      ${renderSavePreview()}
      ${renderPrototypeControls()}
      <div class="toasts"></div>
    </div>
  `;
  bindEvents();
  renderToasts();
  if (state.draftPreview) document.querySelector(".draft-preview")?.scrollIntoView({ block: "nearest" });
}

function bindEvents() {
  document.querySelectorAll("[data-entry]").forEach((button) => button.addEventListener("click", () => setEntry(button.dataset.entry)));
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => switchMode(button.dataset.mode)));
  document.querySelectorAll("[data-select-preset]").forEach((button) => button.addEventListener("click", () => selectPreset(button.dataset.selectPreset)));
  document.querySelectorAll("[data-residue]").forEach((button) => button.addEventListener("click", (event) => {
    if (button.dataset.track) state.activeTrack = button.dataset.track;
    handleResidueClick(button.dataset.residue, event, button.closest("[data-surface=structure]") ? "三维结构" : "残基矩阵");
  }));
  document.querySelectorAll("[data-track]").forEach((button) => {
    if (button.dataset.residue) return;
    button.addEventListener("click", () => setActiveTrack(button.dataset.track));
  });
  document.querySelectorAll("[data-toggle-track]").forEach((button) => button.addEventListener("click", () => toggleTrack(button.dataset.toggleTrack)));
  document.querySelectorAll("[data-sequence-action]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    setSequenceAction(button.dataset.sequenceAction);
  }));
  document.querySelectorAll("[data-insert-initial]").forEach((button) => button.addEventListener("click", () => {
    state.insertInitial = button.dataset.insertInitial;
    state.draftPreview = null;
    state.lastAction = `插入 residue 的 Sequence 初始状态：${state.insertInitial === "assigned" ? "指定值" : "Mask"}`;
    render();
  }));
  document.querySelectorAll("[data-sequence-field]").forEach((field) => field.addEventListener("change", () => {
    if (field.dataset.sequenceField === "insert-count") state.insertCount = Math.max(1, Math.min(12, Number(field.value) || 1));
    else state.sequenceValue = field.value;
    state.draftPreview = null;
    state.lastAction = "更新 Sequence 操作参数";
    render();
  }));
  document.querySelectorAll("[data-sequence-preview]").forEach((button) => button.addEventListener("click", () => createSequencePreview(button.dataset.sequencePreview)));
  document.querySelectorAll("[data-preview-intent]").forEach((button) => button.addEventListener("click", () => createPreview(button.dataset.previewIntent)));
  document.querySelectorAll("[data-function-action]").forEach((button) => button.addEventListener("click", () => createFunctionPreview(button.dataset.functionAction)));
  document.querySelectorAll("[data-layout-intent]").forEach((button) => button.addEventListener("click", () => createPreview(button.dataset.layoutIntent)));
  document.querySelectorAll("[data-transform]").forEach((button) => button.addEventListener("click", () => createPreview(`${button.dataset.transform} · ${button.textContent.trim()}`)));
  document.querySelectorAll("[data-axis]").forEach((button) => button.addEventListener("click", () => {
    state.lastAction = `结构变换轴约束：${button.dataset.axis}`;
    addToast(`轴约束 ${button.dataset.axis}（交互示意；未应用坐标变换）`);
    render();
  }));
  document.querySelectorAll("[data-variant-cycle]").forEach((button) => button.addEventListener("click", () => cycleVariant(Number(button.dataset.variantCycle))));
  document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (action === "summary") {
      state.summaryOpen = !state.summaryOpen;
      state.lastAction = `${state.summaryOpen ? "展开" : "收起"}整份 Prompt 摘要`;
      render();
    } else if (action === "clear-selection") setSelection([], "清除选择");
    else if (action === "toggle-viewer-selected") toggleViewerSelected();
    else if (action === "apply-sequence-preview") applySequencePreview();
    else if (action === "apply-function-preview") applyFunctionPreview();
    else if (action === "undo") undoPromptEdit();
    else if (action === "clear-preview") {
      state.draftPreview = null;
      state.lastAction = "清除未应用预览";
      render();
    } else if (action === "save") savePrompt();
    else if (action === "clear-save-preview") {
      state.savePreview = null;
      state.lastAction = "返回编辑；未调用 apply";
      render();
    }
    else if (action === "cancel") {
      initializeEntry(state.entry);
      state.lastAction = "取消编辑：恢复当前入口的初始状态（原型内存）";
      addToast("已恢复入口初始状态；真实产品将返回 Workflow");
      render();
    }
  }));
}

document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undoPromptEdit();
    return;
  }
  if (event.key === "ArrowLeft") cycleVariant(-1);
  if (event.key === "ArrowRight") cycleVariant(1);
});

initializeEntry("pdb");
render();
