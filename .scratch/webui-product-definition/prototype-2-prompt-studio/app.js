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
const AMINO_ACID_CODES = new Set("ACDEFGHIKLMNPQRSTVWY".split(""));
const SS8_CODES = new Set(["H", "B", "E", "G", "I", "T", "S", "-"]);
const MATRIX_TRACK_ORDER = ["axis", "sequence", "coordinates", "ss", "sasa", "function"];

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
  keyboardFocus: null,
  keyboardDraft: null,
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
  state.keyboardFocus = null;
  state.keyboardDraft = null;
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

function keyboardTargetIds() {
  const focusedId = state.keyboardFocus?.residueId;
  if (!focusedId || !residueById(focusedId)) return selectedResidues().map((item) => item.id);
  if (state.selected.has(focusedId)) return selectedResidues().map((item) => item.id);
  return [focusedId];
}

function isKeyboardFocused(item, track) {
  return state.keyboardFocus?.residueId === item.id && state.keyboardFocus?.track === track;
}

function keyboardDraftFor(item, track) {
  let draft = state.keyboardDraft;
  const preview = state.draftPreview;
  if (!draft && preview?.track === track && preview.ids?.includes(item.id)) {
    if (["track-specify", "track-mask", "track-restore"].includes(preview.kind)) {
      draft = { track, ids: preview.ids, value: preview.value };
    } else if (track === "sequence" && ["specify", "mask"].includes(preview.kind)) {
      draft = { track, ids: preview.ids, value: preview.kind === "specify" ? preview.sequenceValue : null };
    }
  }
  if (!draft || draft.track !== track || !draft.ids?.includes(item.id)) return null;
  return draft;
}

function keyboardCellValue(item, track) {
  const draft = keyboardDraftFor(item, track);
  if (!draft) return cellValue(item, track);
  if (track === "coordinates") return draft.value ? "●" : "MASK";
  if (track === "sequence") return draft.value ?? "MASK";
  if (track === "ss") return draft.value ?? "·";
  if (track === "sasa") return draft.value || "0";
  return draft.value;
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
  state.keyboardDraft = null;
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
  const preview = state.draftPreview?.kind === "insert" ? state.draftPreview : null;
  const previewOrders = preview ? insertionProjectionOrders(preview.afterId, preview.count) : [];
  const previewResidues = preview ? preview.backendResidues.map((projection, index) => ({
    id: projection.handle,
    chain: projection.chain,
    sourceNumber: null,
    sequence: preview.initialSequence === "assigned" ? (preview.sequenceValues?.[index] ?? preview.sequenceValue) : null,
    coordinates: false,
    ss: null,
    sasa: null,
    sourceValues: { sequence: null, coordinates: false, ss: null, sasa: null },
    state: "inserted",
    trackStates: { sequence: "inserted", coordinates: "inserted", ss: "inserted", sasa: "inserted" },
    projectionOrder: previewOrders[index],
    previewInserted: true,
    previewOrdinal: index + 1,
  })) : [];
  return [...state.residues, ...state.residueTombstones, ...previewResidues]
    .sort((left, right) => left.projectionOrder - right.projectionOrder);
}

function insertionProjectionOrders(afterId, count) {
  const after = residueById(afterId);
  const lower = after.projectionOrder;
  const upper = [...state.residues, ...state.residueTombstones]
    .sort((left, right) => left.projectionOrder - right.projectionOrder)
    .find((item) => item.projectionOrder > lower)?.projectionOrder ?? lower + 1;
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
  state.keyboardDraft = null;
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
  state.keyboardDraft = null;
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
  state.keyboardDraft = null;
  state.lastAction = `当前编辑对象：${TRACKS[track].label}`;
  render();
}

function setSequenceAction(action) {
  state.activeTrack = "sequence";
  state.sequenceAction = action;
  state.mode = ["插入", "删除"].includes(action) ? "layout" : "condition";
  state.draftPreview = null;
  state.keyboardDraft = null;
  state.lastAction = `Sequence 轨道直接操作：${action}`;
  if (state.selected.size === 0) {
    addToast("请先选择要操作的残基", "warn");
    render();
    return;
  }
  if (action === "插入") {
    beginKeyboardInsertion();
    return;
  }
  if (action === "删除") {
    createSequencePreview("delete");
    return;
  }
  if (action === "Mask") {
    createSequencePreview("mask");
    return;
  }
  state.keyboardDraft = { kind: "track-value", track: "sequence", ids: keyboardTargetIds(), value: state.sequenceValue };
  commitKeyboardDraftToPreview(true);
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
    state.lastAction = `即时预览删除：${formatSelection()}`;
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

function createTrackPreview(draft, keepDraft = false) {
  const items = selectedResidues(new Set(draft.ids));
  if (items.length === 0) {
    addToast("当前预览中的残基已不存在，请重新选择", "warn");
    state.keyboardDraft = null;
    render();
    return;
  }
  const numericValue = draft.track === "sasa" ? Number(draft.value) : draft.value;
  if (draft.track === "sasa" && (!Number.isFinite(numericValue) || numericValue < 0)) {
    addToast("SASA 必须是大于或等于 0 的数字（Å²）", "warn");
    renderToasts();
    return;
  }
  state.draftPreview = {
    kind: draft.kind === "coordinates-toggle" ? (draft.value ? "track-restore" : "track-mask") : "track-specify",
    track: draft.track,
    ids: items.map((item) => item.id),
    selection: formatSelection(new Set(items.map((item) => item.id))),
    value: numericValue,
  };
  if (!keepDraft) state.keyboardDraft = null;
  state.lastAction = `Backend preview：${TRACKS[draft.track].label} 键盘编辑`;
  render();
}

function createKeyboardFunctionPreview(draft, keepDraft = false) {
  const items = selectedResidues(new Set(draft.ids));
  if (items.length === 0) {
    addToast("请先选择 Function tuple 的 residue locator", "warn");
    state.keyboardDraft = null;
    render();
    return;
  }
  const first = items[0];
  const last = items.at(-1);
  const existing = draft.annotation
    ? state.annotations.find((annotation) => sameAnnotationTuple(annotation, draft.annotation))
    : null;
  const startHandle = existing?.startHandle ?? first.id;
  const endHandle = existing?.endHandle ?? last.id;
  const startItem = residueById(startHandle);
  const endItem = residueById(endHandle);
  const locator = locatorOnly([startHandle, endHandle]);
  const sameChain = Boolean(startItem && endItem && startItem.chain === endItem.chain);
  const contiguousSelection = existing || (sameChain && items.every((item, index) => index === 0 || indexById(item.id) === indexById(items[index - 1].id) + 1));
  const diagnostics = [];
  if (!draft.label.trim()) diagnostics.push({ severity: "error", locator, message: "Function tuple label 不可为空" });
  if (!sameChain) diagnostics.push({ severity: "error", locator, message: "Function interval 的 endpoints 必须属于同一 chain" });
  if (!contiguousSelection) diagnostics.push({ severity: "error", locator, message: "空白位置必须先选择同一 chain 的连续区间" });
  if (sameChain && indexById(startHandle) > indexById(endHandle)) diagnostics.push({ severity: "error", locator, message: "Function interval 的 start locator 必须位于 end locator 之前" });
  const pendingTuples = existing && isSourceAnnotation(existing) ? [{ ...existing }] : [];
  pendingTuples.forEach((annotation) => diagnostics.push({
    severity: "warning",
    locator: annotationLocator(annotation),
    message: `原 tuple ${annotationTuple(annotation)} 将进入 pending-delete`,
  }));
  state.draftPreview = {
    kind: existing ? "function-replace" : "function-insert",
    track: "function",
    selection: existing ? annotationLocator(existing) : formatSelection(new Set(items.map((item) => item.id))),
    functionRemovedTuples: existing ? [{ ...existing }] : [],
    functionPendingTuples: pendingTuples,
    functionInsertedTuples: [{
      label: draft.label.trim(),
      chain: startItem?.chain ?? first.chain,
      startHandle,
      endHandle,
      locator,
      state: "inserted",
    }],
    diagnostics,
  };
  if (!keepDraft) state.keyboardDraft = null;
  state.lastAction = `Backend preview：Function ${existing ? "replace" : "insert"} 完整 tuple`;
  render();
}

function createKeyboardInsertionPreview(draft, keepDraft = false) {
  const after = residueById(draft.afterId);
  if (!after) {
    addToast("插入锚点已不存在，请重新选择", "warn");
    state.keyboardDraft = null;
    render();
    return;
  }
  const count = Math.max(1, Math.min(12, draft.count));
  const typed = draft.sequenceText.toUpperCase();
  const validSequence = [...typed].every((letter) => AMINO_ACID_CODES.has(letter));
  const sequenceValues = !typed ? [] : typed.length === 1 ? Array(count).fill(typed) : [...typed];
  const diagnostics = [];
  if (!validSequence) diagnostics.push({ severity: "error", locator: residueLocator(after), message: "插入序列只能包含标准单字母氨基酸代码" });
  if (typed.length > 1 && typed.length !== count) diagnostics.push({ severity: "error", locator: residueLocator(after), message: `插入数量 ${count} 与输入序列长度 ${typed.length} 不一致` });
  state.draftPreview = {
    kind: "insert",
    track: "sequence",
    selection: formatSelection(new Set([after.id])),
    afterId: after.id,
    afterLocator: residueLocator(after),
    chain: after.chain,
    count,
    backendResidues: backendPreviewInsertion(after, count),
    initialSequence: typed ? "assigned" : "mask",
    sequenceValue: typed.length === 1 ? typed : null,
    sequenceValues,
    beforeLength: state.residues.length,
    afterLength: state.residues.length + count,
    diagnostics,
  };
  if (!keepDraft) state.keyboardDraft = null;
  state.lastAction = `Backend preview：在 ${residueLocator(after)} 后新增 ${count} 个残基`;
  render();
}

function commitKeyboardDraftToPreview(keepDraft = false) {
  const draft = state.keyboardDraft;
  if (!draft) return;
  if (draft.kind === "insert") createKeyboardInsertionPreview(draft, keepDraft);
  else if (draft.kind === "function-label") createKeyboardFunctionPreview(draft, keepDraft);
  else createTrackPreview(draft, keepDraft);
}

function applySequencePreview() {
  const preview = state.draftPreview;
  if (!preview || !["insert", "delete", "specify", "mask"].includes(preview.kind)) return;
  if (hasBlockingDiagnostics(preview)) return;

  if (preview.kind === "insert") {
    const insertionIndex = indexById(preview.afterId);
    pushUndo(`插入 ${preview.count} 个残基`);
    const projectionOrders = insertionProjectionOrders(preview.afterId, preview.count);
    const inserted = preview.backendResidues.map((projection, index) => ({
      ...residue({
        handle: projection.handle,
        chain: projection.chain,
        sourceNumber: null,
        sequence: preview.initialSequence === "assigned" ? (preview.sequenceValues?.[index] ?? preview.sequenceValue) : null,
        state: "inserted",
      }),
      projectionOrder: projectionOrders[index],
    }));
    state.residues.splice(insertionIndex + 1, 0, ...inserted);
    state.selected = new Set(inserted.map((item) => item.id));
    state.anchor = inserted.at(-1)?.id ?? null;
    state.keyboardFocus = inserted.length ? { residueId: inserted.at(-1).id, track: "sequence" } : state.keyboardFocus;
    state.draftPreview = null;
    state.keyboardDraft = null;
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
    state.keyboardFocus = neighbor ? { residueId: neighbor.id, track: "axis" } : null;
    state.draftPreview = null;
    state.keyboardDraft = null;
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
  state.keyboardDraft = null;
  state.savePreview = null;
  state.dirty = true;
  state.lastAction = `已${preview.kind === "specify" ? `指定为 ${preview.sequenceValue}` : "Mask"} ${targetIds.size} 个 Sequence 值`;
  addToast(`${state.lastAction}；可撤销`);
  render();
}

function applyTrackPreview() {
  const preview = state.draftPreview;
  if (!preview || !["track-specify", "track-mask", "track-restore"].includes(preview.kind)) return;
  const targetIds = new Set(preview.ids.filter((id) => residueById(id)));
  if (targetIds.size === 0) {
    addToast("预览中的残基已不存在，请重新选择", "warn");
    state.draftPreview = null;
    render();
    return;
  }
  pushUndo(`键盘编辑 ${TRACKS[preview.track].label}`);
  state.residues = state.residues.map((item) => {
    if (!targetIds.has(item.id)) return item;
    const nextValue = preview.track === "coordinates" ? Boolean(preview.value) : preview.value;
    const sourceValue = item.sourceValues[preview.track];
    const projectionState = item.state === "inserted"
      ? "inserted"
      : nextValue === sourceValue
        ? "current"
        : (nextValue === null || nextValue === false) && (sourceValue !== null && sourceValue !== false)
          ? "cleared"
          : "changed";
    return {
      ...item,
      [preview.track]: nextValue,
      trackStates: { ...item.trackStates, [preview.track]: projectionState },
    };
  });
  state.draftPreview = null;
  state.keyboardDraft = null;
  state.savePreview = null;
  state.dirty = true;
  state.lastAction = `已应用 ${TRACKS[preview.track].label} 键盘编辑：${targetIds.size} 个残基`;
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
  if (!preview || hasBlockingDiagnostics(preview)) return;
  pushUndo(`应用 ${preview.kind} tuple preview`);
  preview.functionPendingTuples.forEach((tuple) => {
    state.annotationTombstones.push(annotationTombstone(tuple));
  });
  state.annotations = state.annotations.filter((annotation) =>
    !preview.functionRemovedTuples.some((tuple) => sameAnnotationTuple(tuple, annotation)),
  );
  state.annotations.push(...preview.functionInsertedTuples.map((tuple) => ({ ...tuple })));
  state.operationDiagnostics.push(...preview.diagnostics.map((item) => ({ ...item })));
  state.draftPreview = null;
  state.keyboardDraft = null;
  state.savePreview = null;
  state.dirty = true;
  state.lastAction = `已应用 Function tuple preview：${preview.kind.replace("function-", "")}`;
  addToast(`${state.lastAction}；可撤销`);
  render();
}

function toggleTrack(track) {
  if (state.hiddenTracks.has(track)) state.hiddenTracks.delete(track);
  else {
    state.hiddenTracks.add(track);
    if (state.keyboardFocus?.track === track) {
      state.keyboardFocus = { residueId: state.keyboardFocus.residueId, track: "axis" };
      state.keyboardDraft = null;
      state.draftPreview = null;
    }
  }
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
  return (preview.diagnostics ?? []).some((item) => item.severity === "error");
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
  if (state.keyboardDraft || state.draftPreview) {
    state.lastAction = "请先应用或取消当前即时预览，再保存";
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
  const localPreviewOpen = Boolean(state.keyboardDraft || state.draftPreview);
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
      <footer><span>${blocked ? blockMessage : "apply 接收此 normalized document + confirmed preview digest；intent = replace"}</span><div><button class="button ghost" data-action="clear-save-preview">返回编辑</button><button class="button primary" data-action="save" ${blocked ? "disabled" : ""}>确认并写回 Workflow</button></div></footer>
    </section>
  `;
}

function renderTopbar() {
  const localPreviewOpen = Boolean(state.keyboardDraft || state.draftPreview);
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
        <button class="button primary" data-action="save" ${saveBlocked ? "disabled" : ""}>${localPreviewOpen ? "先应用/取消当前操作" : state.savePreview ? "确认 replace 写回 Workflow" : "保存"}</button>
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
  return state.draftPreview?.functionInsertedTuples?.find((annotation) => annotationContains(annotation, item))
    ?? state.annotations.find((annotation) => annotationContains(annotation, item));
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
  if (item.previewInserted) {
    return `<div class="axis-cell preview-inserted ${chainStart}" title="即时插入预览 · 尚未应用"><small>新增</small><strong>+${item.previewOrdinal}</strong></div>`;
  }
  if (isResidueTombstone(item)) {
    return `<div class="axis-cell state-pending-delete tombstone-cell ${chainStart}" title="来源 ${locator} · pending-delete · 只读删除证据"><small>源 ${item.chain}</small><strong>${locator.split(":")[1]}</strong></div>`;
  }
  return `<button class="axis-cell state-${residueProjectionState(item)} ${state.selected.has(item.id) ? "selected" : ""} ${isKeyboardFocused(item, "axis") ? "keyboard-focus" : ""} ${chainStart}" data-residue="${item.id}" title="${locator}"><small>${item.chain}</small><strong>${locator.split(":")[1]}</strong></button>`;
}

function renderFunctionProjectionCell(item, index, residues) {
  const chainStart = matrixChainStart(residues, index);
  if (item.previewInserted) {
    return `<div class="track-cell function-cell preview-inserted ${chainStart}" title="即时插入预览 · Function 未指定">·</div>`;
  }
  if (isResidueTombstone(item)) {
    return `<div class="track-cell function-cell state-pending-delete tombstone-cell ${chainStart}" title="来源 ${residueLocator(item)} · Function annotations · pending-delete">×</div>`;
  }
  const annotation = annotationAt(item);
  const begins = annotation && item.id === annotation.startHandle;
  const draft = keyboardDraftFor(item, "function");
  const draftBegins = draft && (draft.annotation ? item.id === draft.annotation.startHandle : item.id === draft.ids[0]);
  const annotationState = annotation ? annotationProjectionState(annotation) : "source";
  const assigned = annotation || draft;
  const content = draft ? (draftBegins ? draft.label : "↔") : begins ? annotation.label : annotation ? "↔" : "·";
  return `<button class="track-cell function-cell ${assigned ? `assigned ribbon annotation-${annotationState}` : "unassigned"} ${begins || draftBegins ? "ribbon-start" : ""} ${draft ? "keyboard-draft-cell" : ""} ${isKeyboardFocused(item, "function") ? "keyboard-focus" : ""} ${state.selected.has(item.id) ? "selected" : ""} ${isPendingDelete(item.id) ? "state-pending-delete" : ""} ${chainStart}" data-residue="${item.id}" data-track="function" title="${annotation ? `${annotationTuple(annotation)} · ${annotationState}` : "未指定 function tuple"}">${escapeHtml(content)}</button>`;
}

function renderTrackProjectionCell(item, track, index, residues) {
  const chainStart = matrixChainStart(residues, index);
  if (item.previewInserted) {
    return `<div class="track-cell ${isAssigned(item, track) ? "assigned" : "unassigned masked"} preview-inserted ${chainStart}" title="即时插入预览 · ${TRACKS[track].label}">${cellValue(item, track)}</div>`;
  }
  if (isResidueTombstone(item)) {
    return `<div class="track-cell ${isAssigned(item, track) ? "assigned" : "unassigned masked"} state-pending-delete tombstone-cell ${chainStart}" title="来源 ${residueLocator(item)} · ${TRACKS[track].label} · pending-delete">${cellValue(item, track)}</div>`;
  }
  const draft = keyboardDraftFor(item, track);
  const draftAssigned = draft ? !(draft.value === null || draft.value === false) : isAssigned(item, track);
  return `<button class="track-cell ${draftAssigned ? "assigned" : "unassigned masked"} state-${trackProjectionState(item, track)} ${draft ? "keyboard-draft-cell" : ""} ${isKeyboardFocused(item, track) ? "keyboard-focus" : ""} ${state.selected.has(item.id) ? "selected" : ""} ${chainStart}" data-residue="${item.id}" data-track="${track}" title="${residueLocator(item)} · ${TRACKS[track].label} · ${trackProjectionState(item, track)} · ${isAssigned(item, track) ? "已指定" : "Mask"}">${keyboardCellValue(item, track)}</button>`;
}

function renderMatrixLegend() {
  return `<details class="matrix-legend-popover"><summary>状态图例</summary><div>${CHANGE_STATES.map((key) => `<span><i class="legend-mark ${key}"></i>${key}</span>`).join("")}</div></details>`;
}

function renderKeyboardHint() {
  if (!state.keyboardFocus) return `<span class="keyboard-hint">点击单元格后可使用键盘</span>`;
  return `<span class="keyboard-hint active">方向键导航 · 直接输入 / Space / + 即时预览 · Enter 应用 · Esc 取消</span>`;
}

function renderMatrix({ focus = false, compact = false } = {}) {
  const residues = visibleResidues(focus);
  const gridStyle = `--residue-count:${residues.length}`;
  const tracks = Object.keys(TRACKS).filter((track) => !state.hiddenTracks.has(track));
  return `
    <section class="surface matrix-surface ${focus ? "focus-matrix" : ""} ${compact ? "compact" : ""}" data-surface="matrix">
      <header class="surface-header matrix-header">
        <div><span class="surface-kicker">${focus ? "所选区域与邻近残基" : "下方 · 共享残基位置"}</span><h2>${focus ? "Selection lens" : "ProteinPrompt 残基矩阵"}</h2></div>
        <div class="matrix-meta"><span>一列 = 当前 locator、即时预览或只读删除证据</span><strong>${chainSummary()} · ${state.residues.length} current${state.draftPreview?.kind === "insert" ? ` · +${state.draftPreview.count} preview` : ""}${state.residueTombstones.length ? ` · ${state.residueTombstones.length} pending-delete` : ""}</strong></div>
      </header>
      ${!hasCoordinates() ? `<div class="coordinate-notice"><b>三维区已自动收起</b><span>此 Prompt 没有坐标；不是缺少必填模板。共享残基矩阵已获得更多空间。</span></div>` : ""}
      <div class="track-controls">
        <span>轨道行：</span>
        ${Object.entries(TRACKS).map(([key, track]) => `<button class="${state.hiddenTracks.has(key) ? "off" : "on"}" data-toggle-track="${key}">${track.short}</button>`).join("")}
        ${renderMatrixLegend()}
        ${renderKeyboardHint()}
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
    </section>
  `;
}

function renderSequenceTools() {
  return `
    <div class="tool-section operation-detail current-operation-reference">
      <span class="section-label">Sequence · 当前操作参考</span>
      <strong>${state.sequenceAction}</strong>
      <p>${formatSelection()}</p>
      <div class="mask-explanation">行内操作或键盘输入会立即显示预览；Enter 应用，Esc 取消。</div>
    </div>
  `;
}

function renderConditionTools() {
  const hints = {
    coordinates: "Space 切换 Mask / 恢复会话内原始 coordinates",
    ss: "直接输入 H/B/E/G/I/T/S/-",
    sasa: "直接输入大于或等于 0 的数值；单位 Å²",
    function: "直接输入完整 tuple 的 label；现有 endpoints 保持不变",
  };
  return `
    <div class="tool-section operation-detail current-operation-reference">
      <span class="section-label">${TRACKS[state.activeTrack].label} · 当前操作参考</span>
      <strong>${hints[state.activeTrack]}</strong>
      <p>${formatSelection()}</p>
      <div class="mask-explanation">操作会立即显示预览；Enter 应用，Esc 取消。未修改的其他轨道保持不变。</div>
    </div>
  `;
}

function renderLayoutTools() {
  return `
    <div class="tool-section current-operation-reference"><span class="section-label">布局 · 当前操作参考</span><strong>请使用 Sequence 行内的插入 / 删除，或按 +</strong><p class="panel-note">操作会立即显示共享轴变化；Enter 应用，Esc 取消。</p></div>
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
    const blocked = hasBlockingDiagnostics(preview);
    return `
      <div class="draft-preview actionable-preview">
        <span>即时预览 · 插入</span>
        <strong>${preview.afterLocator} 后新增 ${preview.count} 个残基</strong>
        <div class="preview-axis-change"><b>${preview.beforeLength} residues</b><i>→</i><b>${preview.afterLength} residues</b></div>
        <p>Sequence：${preview.initialSequence === "assigned" ? `指定为 ${escapeHtml((preview.sequenceValues ?? [preview.sequenceValue]).join(""))}` : "Mask"}；Coordinates、SS8、SASA 与 Function 均未指定。</p>
        ${renderDiagnostics(preview.diagnostics)}
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply" data-action="apply-sequence-preview" ${blocked ? "disabled" : ""}>${blocked ? "先修正 diagnostics" : "应用插入"}</button></div>
      </div>
    `;
  }
  if (preview.kind === "delete") {
    const impact = preview.impact;
    return `
      <div class="draft-preview actionable-preview delete-preview">
        <span>即时预览 · 删除</span>
        <strong>待删除 ${preview.ids.length} 个 chain/residue locators</strong>
        <p>${preview.selection}</p>
        <div class="preview-axis-change"><b>${preview.beforeLength} residues</b><i>→</i><b>${preview.afterLength} residues</b></div>
        <div class="impact-counts"><span>SEQ ${impact.sequence}</span><span>XYZ ${impact.coordinates}</span><span>SS8 ${impact.ss}</span><span>SASA ${impact.sasa}</span></div>
        <p>受影响 Function tuples：${impact.functionTuples.length ? impact.functionTuples.map(annotationTuple).join("、") : "无"}${impact.viewerHidden ? `；另移除 ${impact.viewerHidden} 个临时 viewer hidden 状态` : ""}</p>
        ${renderDiagnostics(preview.diagnostics)}
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply danger" data-action="apply-sequence-preview">应用删除</button></div>
      </div>
    `;
  }
  if (preview.kind?.startsWith("function-")) {
    const blocked = hasBlockingDiagnostics(preview);
    return `
      <div class="draft-preview actionable-preview">
        <span>即时预览 · Function tuple</span>
        <strong>${preview.selection}</strong>
        ${preview.functionPendingTuples.map((tuple) => `<p><b>pending-delete</b> ${annotationTuple(tuple)}</p>`).join("")}
        ${preview.functionInsertedTuples.map((tuple) => `<p><b>inserted</b> ${annotationTuple(tuple)}</p>`).join("")}
        ${renderDiagnostics(preview.diagnostics)}
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply" data-action="apply-function-preview" ${blocked ? "disabled" : ""}>${blocked ? "先修正 diagnostics" : "应用"}</button></div>
      </div>
    `;
  }
  if (["specify", "mask"].includes(preview.kind)) {
    return `
      <div class="draft-preview actionable-preview">
        <span>即时预览 · Sequence ${preview.kind === "specify" ? "指定" : "Mask"}</span>
        <strong>${preview.selection}</strong>
        <p>${preview.kind === "specify" ? `Sequence 将指定为 ${preview.sequenceValue}` : "仅 Sequence 变为 Mask；其他轨道保持不变"}</p>
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply" data-action="apply-sequence-preview">应用${preview.kind === "specify" ? "指定" : " Mask"}</button></div>
      </div>
    `;
  }
  if (["track-specify", "track-mask", "track-restore"].includes(preview.kind)) {
    const value = preview.track === "coordinates"
      ? preview.value ? "恢复本次会话保留的原始 coordinates" : "Mask coordinates"
      : `${preview.value}${preview.track === "sasa" ? " Å²" : ""}`;
    return `
      <div class="draft-preview actionable-preview">
        <span>即时预览 · ${TRACKS[preview.track].label}</span>
        <strong>${preview.selection}</strong>
        <p>${escapeHtml(String(value))}；未修改的其他轨道保持不变。</p>
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply" data-action="apply-track-preview">应用</button></div>
      </div>
    `;
  }
  return `<div class="draft-preview"><span>即时预览</span><strong>${preview.intent} ${TRACKS[preview.track].label}</strong><p>${preview.selection}</p><button data-action="clear-preview">取消</button></div>`;
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
    keyboardFocus: state.keyboardFocus ? {
      locator: residueById(state.keyboardFocus.residueId) ? residueLocator(residueById(state.keyboardFocus.residueId)) : null,
      track: state.keyboardFocus.track,
    } : null,
    previewInput: state.keyboardDraft ? {
      kind: state.keyboardDraft.kind,
      track: state.keyboardDraft.track,
      locators: state.keyboardDraft.ids ? selectedResidues(new Set(state.keyboardDraft.ids)).map(residueLocator) : [],
      afterLocator: state.keyboardDraft.afterId && residueById(state.keyboardDraft.afterId) ? residueLocator(residueById(state.keyboardDraft.afterId)) : null,
      value: state.keyboardDraft.value ?? state.keyboardDraft.label ?? state.keyboardDraft.sequenceText ?? null,
      count: state.keyboardDraft.count ?? null,
    } : null,
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

function beginKeyboardInsertion() {
  const after = residueById(state.keyboardFocus?.residueId) ?? selectedResidues().at(-1);
  if (!after) return;
  state.keyboardFocus = { residueId: after.id, track: "sequence" };
  state.mode = "layout";
  state.activeTrack = "sequence";
  state.sequenceAction = "插入";
  state.draftPreview = null;
  state.keyboardDraft = {
    kind: "insert",
    track: "sequence",
    afterId: after.id,
    count: 1,
    countText: "",
    explicitCount: false,
    sequenceText: "",
  };
  state.lastAction = `键盘插入草稿：${residueLocator(after)} 后 1 个 Mask residue`;
  commitKeyboardDraftToPreview(true);
}

function beginCoordinateToggle() {
  if (state.keyboardDraft?.kind === "coordinates-toggle" || (state.draftPreview?.track === "coordinates" && ["track-mask", "track-restore"].includes(state.draftPreview.kind))) {
    state.keyboardDraft = null;
    state.draftPreview = null;
    state.lastAction = "取消 Coordinates mask/unmask 草稿";
    render();
    return;
  }
  const ids = keyboardTargetIds();
  const items = selectedResidues(new Set(ids));
  if (items.length === 0) return;
  const shouldMask = items.every((item) => item.coordinates);
  if (!shouldMask && items.some((item) => !item.sourceValues.coordinates)) {
    addToast("这些残基没有可恢复的原始 coordinates；请从结构或其他来源重新指定", "warn");
    renderToasts();
    return;
  }
  state.mode = "condition";
  state.activeTrack = "coordinates";
  state.draftPreview = null;
  state.keyboardDraft = { kind: "coordinates-toggle", track: "coordinates", ids, value: !shouldMask };
  state.lastAction = `Coordinates 即时预览：${shouldMask ? "Mask" : "恢复会话内原始值"}`;
  commitKeyboardDraftToPreview(true);
}

function beginTrackKeyboardDraft(track, key) {
  const ids = keyboardTargetIds();
  if (ids.length === 0) return false;
  if (track === "sequence") {
    const value = key.toUpperCase();
    if (!AMINO_ACID_CODES.has(value)) return false;
    state.keyboardDraft = { kind: "track-value", track, ids, value };
  } else if (track === "ss") {
    const value = key.toUpperCase();
    if (!SS8_CODES.has(value)) return false;
    state.keyboardDraft = { kind: "track-value", track, ids, value };
  } else if (track === "sasa") {
    if (!/[0-9.]/.test(key)) return false;
    const current = state.keyboardDraft?.track === "sasa" ? String(state.keyboardDraft.value) : "";
    if (key === "." && current.includes(".")) return true;
    state.keyboardDraft = { kind: "track-value", track, ids, value: `${current}${key}` };
  } else if (track === "function") {
    if (key.length !== 1) return false;
    const focused = residueById(state.keyboardFocus.residueId);
    const existingDraft = state.keyboardDraft?.kind === "function-label" ? state.keyboardDraft : null;
    const annotation = existingDraft?.annotation
      ?? state.annotations.find((candidate) => annotationContains(candidate, focused));
    const functionIds = existingDraft?.ids ?? (annotation
      ? state.residues.filter((item) => annotationContains(annotation, item)).map((item) => item.id)
      : ids);
    const current = existingDraft?.label ?? "";
    state.keyboardDraft = { kind: "function-label", track, ids: functionIds, label: `${current}${key}`, annotation: annotation ? { ...annotation } : null };
  } else return false;
  state.mode = "condition";
  state.activeTrack = track;
  state.draftPreview = null;
  state.lastAction = `${TRACKS[track].label} 即时预览`;
  commitKeyboardDraftToPreview(true);
  return true;
}

function editKeyboardDraftWithBackspace() {
  const draft = state.keyboardDraft;
  if (!draft) return false;
  if (draft.kind === "insert") {
    if (draft.sequenceText) draft.sequenceText = draft.sequenceText.slice(0, -1);
    else if (draft.countText) {
      draft.countText = draft.countText.slice(0, -1);
      draft.explicitCount = Boolean(draft.countText);
      draft.count = draft.countText ? Math.max(1, Math.min(12, Number(draft.countText))) : Math.max(1, draft.sequenceText.length || 1);
    } else state.keyboardDraft = null;
  } else if (draft.kind === "function-label") {
    draft.label = draft.label.slice(0, -1);
    if (!draft.label) state.keyboardDraft = null;
  } else if (draft.track === "sasa") {
    draft.value = String(draft.value).slice(0, -1);
    if (!draft.value) state.keyboardDraft = null;
  } else state.keyboardDraft = null;
  state.lastAction = "更新即时预览";
  if (state.keyboardDraft) commitKeyboardDraftToPreview(true);
  else {
    state.draftPreview = null;
    render();
  }
  return true;
}

function editKeyboardInsertion(key) {
  const draft = state.keyboardDraft;
  if (draft?.kind !== "insert") return false;
  if (/^[0-9]$/.test(key)) {
    draft.countText = `${draft.countText}${key}`.replace(/^0+/, "");
    draft.explicitCount = true;
    draft.count = Math.max(1, Math.min(12, Number(draft.countText) || 1));
  } else {
    const value = key.toUpperCase();
    if (!AMINO_ACID_CODES.has(value)) return false;
    draft.sequenceText += value;
    if (!draft.explicitCount) draft.count = Math.min(12, draft.sequenceText.length);
  }
  state.lastAction = `键盘插入草稿：${draft.count} 个 residue`;
  commitKeyboardDraftToPreview(true);
  return true;
}

function moveKeyboardFocus(key) {
  const focus = state.keyboardFocus;
  if (!focus) return false;
  const itemIndex = indexById(focus.residueId);
  if (itemIndex < 0) return false;
  const visibleTracks = MATRIX_TRACK_ORDER.filter((track) => track === "axis" || !state.hiddenTracks.has(track));
  let nextItemIndex = itemIndex;
  let nextTrackIndex = Math.max(0, visibleTracks.indexOf(focus.track));
  if (key === "ArrowLeft") nextItemIndex = Math.max(0, itemIndex - 1);
  if (key === "ArrowRight") nextItemIndex = Math.min(state.residues.length - 1, itemIndex + 1);
  if (key === "ArrowUp") nextTrackIndex = Math.max(0, nextTrackIndex - 1);
  if (key === "ArrowDown") nextTrackIndex = Math.min(visibleTracks.length - 1, nextTrackIndex + 1);
  const next = state.residues[nextItemIndex];
  state.keyboardFocus = { residueId: next.id, track: visibleTracks[nextTrackIndex] };
  state.selected = new Set([next.id]);
  state.anchor = next.id;
  state.keyboardDraft = null;
  state.draftPreview = null;
  state.lastAction = `键盘导航：${residueLocator(next)} · ${visibleTracks[nextTrackIndex]}`;
  render();
  return true;
}

function applyCurrentPreviewFromKeyboard() {
  const preview = state.draftPreview;
  if (!preview || hasBlockingDiagnostics(preview)) return false;
  if (["insert", "delete", "specify", "mask"].includes(preview.kind)) applySequencePreview();
  else if (preview.kind.startsWith("function-")) applyFunctionPreview();
  else if (["track-specify", "track-mask", "track-restore"].includes(preview.kind)) applyTrackPreview();
  else return false;
  return true;
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
  const focus = state.keyboardFocus;
  if (focus) {
    const selector = focus.track === "axis"
      ? `button.axis-cell[data-residue="${focus.residueId}"]`
      : `button.track-cell[data-residue="${focus.residueId}"][data-track="${focus.track}"]`;
    document.querySelector(selector)?.focus({ preventScroll: true });
  }
}

function bindEvents() {
  document.querySelectorAll("[data-entry]").forEach((button) => button.addEventListener("click", () => setEntry(button.dataset.entry)));
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => switchMode(button.dataset.mode)));
  document.querySelectorAll("[data-select-preset]").forEach((button) => button.addEventListener("click", () => selectPreset(button.dataset.selectPreset)));
  document.querySelectorAll("[data-residue]").forEach((button) => button.addEventListener("click", (event) => {
    if (button.dataset.track) state.activeTrack = button.dataset.track;
    state.keyboardFocus = { residueId: button.dataset.residue, track: button.dataset.track ?? "axis" };
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
    else if (action === "apply-track-preview") applyTrackPreview();
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
  if (event.key === "Escape") {
    if (state.keyboardDraft || state.draftPreview) {
      event.preventDefault();
      state.keyboardDraft = null;
      state.draftPreview = null;
      state.lastAction = "取消即时预览";
      render();
    }
    return;
  }
  if (!state.keyboardFocus) {
    if (event.key === "ArrowLeft") cycleVariant(-1);
    if (event.key === "ArrowRight") cycleVariant(1);
    return;
  }
  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    moveKeyboardFocus(event.key);
    return;
  }
  if (event.key === "Enter" && state.draftPreview) {
    event.preventDefault();
    applyCurrentPreviewFromKeyboard();
    return;
  }
  if (event.key === "Backspace" && state.keyboardDraft) {
    event.preventDefault();
    editKeyboardDraftWithBackspace();
    return;
  }
  if (event.key === "+") {
    event.preventDefault();
    beginKeyboardInsertion();
    return;
  }
  if (state.keyboardDraft?.kind === "insert") {
    if (editKeyboardInsertion(event.key)) event.preventDefault();
    return;
  }
  const track = state.keyboardFocus.track;
  if (track === "coordinates" && (event.key === " " || event.code === "Space")) {
    event.preventDefault();
    beginCoordinateToggle();
    return;
  }
  if (beginTrackKeyboardDraft(track, event.key)) event.preventDefault();
});

document.addEventListener("paste", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable) return;
  const draft = state.keyboardDraft;
  if (draft?.kind !== "insert") return;
  const text = event.clipboardData?.getData("text")?.replace(/\s+/g, "").toUpperCase() ?? "";
  if (!text || ![...text].every((letter) => AMINO_ACID_CODES.has(letter))) {
    addToast("粘贴的插入序列只能包含标准单字母氨基酸代码", "warn");
    renderToasts();
    return;
  }
  if (text.length > 12) {
    addToast("此原型一次最多插入 12 个残基；请缩短粘贴序列", "warn");
    renderToasts();
    return;
  }
  event.preventDefault();
  draft.sequenceText = text;
  if (!draft.explicitCount) draft.count = draft.sequenceText.length;
  state.lastAction = `粘贴插入序列：${draft.sequenceText.length} 个 residues`;
  commitKeyboardDraftToPreview(true);
});

initializeEntry("pdb");
render();
