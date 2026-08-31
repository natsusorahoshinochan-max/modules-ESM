// THROWAWAY UI PROTOTYPE — not production code.
// Three variants of the preview language for residue operations, switchable
// via ?variant= on this prototype-only page. Prototype 2's matrix-first
// information hierarchy is treated as an already-adopted constraint.

const VARIANTS = {
  A: {
    name: "Change ledger",
    label: "A · 变更账本（已采用）",
    question: "逐轨道 transaction ledger 能否让变化足够可复述？",
    adopted: true,
  },
  B: {
    name: "Before / after split",
    label: "B · 前后对照",
    question: "把当前态与拟应用态同轴并列，是否最容易发现误操作？",
  },
  C: {
    name: "Operation recipe",
    label: "C · 操作配方",
    question: "先组成可朗读配方再逐项确认，是否更适合高风险批量编辑？",
  },
};

const TRACKS = {
  sequence: { label: "Sequence", short: "SEQ", unit: "residue", defaultValue: "G" },
  coordinates: { label: "Coordinates", short: "XYZ", unit: "conditioning", defaultValue: "assigned" },
  ss: { label: "Secondary structure", short: "SS8", unit: "state", defaultValue: "H" },
  sasa: { label: "SASA", short: "SASA", unit: "Å²", defaultValue: "32" },
};

const INTENT_LABELS = {
  keep: "保留",
  specify: "指定",
  mask: "Mask / 清除",
};

const SHOW_PROTOTYPE_CONTROLS = location.protocol === "file:" || ["127.0.0.1", "localhost"].includes(location.hostname);
const variantFromUrl = new URLSearchParams(location.search).get("variant")?.toUpperCase();

function track(source, current = source, preserved = false) {
  return { source, current, preserved };
}

function residue({ id, chain = "A", positionLabel, sourceNumber, sequence, coordinates, ss, sasa, residueState = "source" }) {
  return {
    // `id` is an opaque authoring handle used only by this in-memory client.
    // User-facing code always renders `chain` + `positionLabel` instead.
    id,
    chain,
    positionLabel: String(positionLabel),
    sourceNumber,
    residueState,
    tracks: {
      sequence: track(sequence),
      coordinates: track(coordinates),
      ss: track(ss),
      sasa: track(sasa),
    },
  };
}

function annotation({ label, startId, endId }) {
  return { label, startId, endId };
}

// Fixture values stand in for handles returned by `open`; their spelling has
// no positional meaning and is never rendered or accepted as user input.
const SOURCE_HANDLE_FIXTURE = "q7mv n2kt x9pa c4rw u8jd b3hs z6fe m1yc v5ng k8wl p2dz t7bx f4qa y9mr d1vk s6cp g3tn w8hf a5rx j2mu e7kb l4zs r9pd h1xg n6cw q3fj v8ty c2ml z5ba k1sn u7er p4gv x2qd m9hc f6wa t3jy b8nk r5xp d2lu y4se g7cm v1zh s9fa e3wr l8qb c6pt".split(" ");

function sourceHandle(position) {
  return SOURCE_HANDLE_FIXTURE[position - 1];
}

// The backend stub owns one monotonic, unbounded sequence. The client only
// consumes the returned opaque string and never derives it from residue facts.
function backendOpaqueHandle(serial) {
  return `h-${(serial + 1).toString(36).padStart(12, "0")}`;
}

function backendInsertionFixture(anchors, mode) {
  return anchors.map((anchor, index) => ({
    afterHandle: anchor.id,
    residueHandle: backendOpaqueHandle(state.nextBackendHandleIndex + index),
    chain: anchor.chain,
    positionLabel: mode === "random" ? `${anchor.positionLabel} 后随机插入` : `${anchor.positionLabel} 后插入 ${index + 1}`,
  }));
}

function buildInitialPrompt() {
  const sequence = "TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN";
  const ssPattern = "--EEE-TT--HHHHHHH-TT--EEE--TT---HHHHH--TT---";
  const residues = [...sequence].map((letter, index) => {
    const number = index + 1;
    return residue({
      id: sourceHandle(number),
      positionLabel: number,
      sourceNumber: number,
      sequence: letter,
      coordinates: true,
      ss: ssPattern[index] ?? "-",
      sasa: Math.round(8 + 46 * Math.abs(Math.sin(index * 0.73))),
    });
  });

  // Seed the sample with real change states so the legend can be judged before
  // any operation. Values and geometry remain explicitly illustrative.
  residues.find((item) => item.sourceNumber === 7).tracks.sequence.preserved = true;
  residues.find((item) => item.sourceNumber === 11).tracks.sequence.current = "G";
  residues.find((item) => item.sourceNumber === 17).tracks.coordinates.current = null;
  residues.find((item) => item.sourceNumber === 22).tracks.sasa.current = null;
  residues.find((item) => item.sourceNumber === 29).tracks.ss.current = "H";
  const inserted = residue({
    id: "h-5a41c90d",
    positionLabel: "18 后插入 1",
    sourceNumber: null,
    sequence: undefined,
    coordinates: undefined,
    ss: undefined,
    sasa: undefined,
    residueState: "inserted",
  });
  Object.values(inserted.tracks).forEach((value) => { value.current = null; });
  residues.splice(18, 0, inserted);

  const sourceAnnotations = [
    annotation({ label: "disulfide-rich region（示意）", startId: sourceHandle(3), endId: sourceHandle(8) }),
    annotation({ label: "binding region（示意）", startId: sourceHandle(12), endId: sourceHandle(20) }),
  ];
  const annotations = [
    ...structuredClone(sourceAnnotations),
    annotation({ label: "surface motif（示意）", startId: sourceHandle(31), endId: sourceHandle(36) }),
  ];
  return { residues, annotations, sourceAnnotations };
}

const initial = buildInitialPrompt();

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "A",
  residues: initial.residues,
  annotations: initial.annotations,
  sourceAnnotations: initial.sourceAnnotations,
  selected: new Set([8, 9, 10, 11, 12, 23, 24, 25].map(sourceHandle)),
  anchor: sourceHandle(25),
  selectionMode: "explicit",
  random: { operation: "mask", track: "coordinates", count: 6, start: 6, end: 34, seed: 1701, insertSequence: "mask", actual: [] },
  tool: "conditions",
  conditionActions: {
    sequence: { intent: "specify", value: "G" },
    coordinates: { intent: "mask", value: "assigned" },
    ss: { intent: "specify", value: "H" },
    sasa: { intent: "keep", value: "32" },
  },
  layoutOperation: "delete",
  insertCount: 2,
  insertSequence: "mask",
  functionAction: "add",
  functionLabel: "catalytic region（示意）",
  splitAt: 16,
  activeAnnotationIndex: 1,
  backendRevision: 0,
  nextBackendHandleIndex: 0,
  preview: null,
  undoStack: [],
  checklist: new Set(),
  lastAction: "已加载 1CRN 来源 Prompt（结构、轨道值与 labels 均为交互示意）",
  toasts: [],
};

function clonePrompt() {
  return {
    residues: structuredClone(state.residues),
    annotations: structuredClone(state.annotations),
    sourceAnnotations: structuredClone(state.sourceAnnotations),
  };
}

function currentSnapshot(label) {
  return {
    label,
    residues: structuredClone(state.residues),
    annotations: structuredClone(state.annotations),
    sourceAnnotations: structuredClone(state.sourceAnnotations),
    selected: [...state.selected],
    anchor: state.anchor,
    backendRevision: state.backendRevision,
    nextBackendHandleIndex: state.nextBackendHandleIndex,
  };
}

function residueIndex(id, residues = state.residues) {
  return residues.findIndex((item) => item.id === id);
}

function residueById(id, residues = state.residues) {
  return residues.find((item) => item.id === id);
}

function selectedResidues(ids = state.selected, residues = state.residues) {
  return residues.filter((item) => ids.has(item.id));
}

function residueLabel(item) {
  return `链 ${item.chain} · 位置 ${item.positionLabel}`;
}

function formatSelection(ids = state.selected, residues = state.residues) {
  if (!ids.size) return "未选择残基";
  const ordered = residues.filter((item) => ids.has(item.id));
  if (!ordered.length) return "未选择残基";
  const groups = [];
  let start = ordered[0];
  let previous = ordered[0];
  for (const item of ordered.slice(1)) {
    const contiguous = item.chain === previous.chain && residueIndex(item.id, residues) === residueIndex(previous.id, residues) + 1;
    if (!contiguous) {
      groups.push(start.id === previous.id ? residueLabel(start) : `链 ${start.chain} · 位置 ${start.positionLabel}–${previous.positionLabel}`);
      start = item;
    }
    previous = item;
  }
  groups.push(start.id === previous.id ? residueLabel(start) : `链 ${start.chain} · 位置 ${start.positionLabel}–${previous.positionLabel}`);
  return `${groups.join(" + ")} · ${ordered.length} residues`;
}

function selectionRuns(ids = state.selected) {
  const ordered = selectedResidues(ids);
  if (!ordered.length) return 0;
  let runs = 1;
  for (let index = 1; index < ordered.length; index += 1) {
    if (residueIndex(ordered[index].id) !== residueIndex(ordered[index - 1].id) + 1) runs += 1;
  }
  return runs;
}

function equalValue(left, right) {
  return left === right;
}

function trackState(item, key) {
  if (item.residueState === "inserted") return "inserted";
  const value = item.tracks[key];
  if (equalValue(value.current, value.source)) return value.preserved ? "current" : "source";
  if (value.current === null && value.source !== null && value.source !== undefined) return "cleared";
  return "changed";
}

function annotationTuple(item) {
  return `${item.label}\u0000${item.startId}\u0000${item.endId}`;
}

function annotationProjection(annotations = state.annotations) {
  const remainingSource = new Map();
  state.sourceAnnotations.forEach((item) => {
    const tuple = annotationTuple(item);
    remainingSource.set(tuple, (remainingSource.get(tuple) ?? 0) + 1);
  });
  const current = annotations.map((item) => {
    const tuple = annotationTuple(item);
    const available = remainingSource.get(tuple) ?? 0;
    if (available) remainingSource.set(tuple, available - 1);
    return { ...item, state: available ? "source" : "inserted" };
  });
  const pending = [];
  state.sourceAnnotations.forEach((item) => {
    const tuple = annotationTuple(item);
    const count = remainingSource.get(tuple) ?? 0;
    if (!count) return;
    pending.push({ ...item, state: "pending-delete" });
    remainingSource.set(tuple, count - 1);
  });
  return [...current, ...pending];
}

function annotationState(item) {
  return item.state ?? (state.sourceAnnotations.some((sourceItem) => annotationTuple(sourceItem) === annotationTuple(item)) ? "source" : "inserted");
}

function annotationStateAtIndex(index, annotations = state.annotations) {
  return annotationProjection(annotations)[index]?.state ?? "inserted";
}

function sourceTuplePendingAfter(item, annotations) {
  const tuple = annotationTuple(item);
  return annotationProjection(annotations).some((projected) => projected.state === "pending-delete" && annotationTuple(projected) === tuple);
}

function countAssigned(key, residues = state.residues) {
  return residues.filter((item) => item.tracks[key].current !== null && item.tracks[key].current !== undefined).length;
}

function valueText(key, value) {
  if (value === null || value === undefined) return "Mask";
  if (key === "coordinates") return value ? "set" : "Mask";
  if (key === "sasa") return String(Math.round(Number(value)));
  return String(value);
}

function addToast(text, tone = "") {
  const id = `${Date.now()}-${Math.random()}`;
  state.toasts.push({ id, text, tone });
  setTimeout(() => {
    state.toasts = state.toasts.filter((item) => item.id !== id);
    renderToasts();
  }, 3000);
}

function renderToasts() {
  const root = document.querySelector(".toasts");
  if (!root) return;
  root.innerHTML = state.toasts.map((item) => `<div class="toast ${item.tone}">${item.text}</div>`).join("");
}

function restorePrePreviewSelection() {
  const previous = state.preview?.selectionBeforePreview;
  if (!previous) return;
  state.selected = new Set(previous.filter((id) => residueById(id)));
  state.anchor = state.selected.has(state.preview.anchorBeforePreview) ? state.preview.anchorBeforePreview : [...state.selected].at(-1) ?? null;
}

function clearPreview(reason = "预览已取消；ProteinPrompt 未改变") {
  if (!state.preview) return;
  restorePrePreviewSelection();
  state.preview = null;
  if (state.selectionMode === "random") state.random.actual = [];
  state.checklist = new Set();
  state.lastAction = reason;
  addToast(reason);
  render();
}

function selectIds(ids, source, mode = "explicit") {
  state.selected = new Set(ids.filter((id) => residueById(id)));
  state.anchor = ids.at(-1) ?? null;
  state.selectionMode = mode;
  state.preview = null;
  state.checklist = new Set();
  state.lastAction = `${source}：${formatSelection()}`;
  render();
}

function selectPreset(kind) {
  if (kind === "single") return selectIds([sourceHandle(16)], "明确选择单残基");
  if (kind === "continuous") {
    const start = residueIndex(sourceHandle(12));
    const end = residueIndex(sourceHandle(20));
    return selectIds(state.residues.slice(start, end + 1).map((item) => item.id), "按当前残基轴选择链 A · 位置 12–20");
  }
  if (kind === "changed") return selectIds([sourceHandle(11), sourceHandle(17), sourceHandle(22), sourceHandle(29), "h-5a41c90d"], "选择当前变化位置");
  return selectIds([8, 9, 10, 11, 12, 23, 24, 25].map(sourceHandle), "明确选择不连续区间");
}

function diagnostic(severity, locator, message, handles = []) {
  return { severity, locator, message, handles };
}

// This is the prototype's only sampling boundary. It stands in for `preview`:
// the UI submits randomness parameters and receives actual opaque handles plus
// readable locators. No frontend sampler is used to predict the result.
function backendPreviewStub(request) {
  if (request.kind === "explicit-insert") {
    return { insertions: backendInsertionFixture(Array.from({ length: request.count }, () => request.anchor), "explicit") };
  }
  const diagnostics = [];
  const candidates = state.residues.filter((item) => item.sourceNumber !== null && item.sourceNumber >= request.start && item.sourceNumber <= request.end);
  if (request.start > request.end) diagnostics.push(diagnostic("error", "Eligible scope", "范围起点必须不晚于终点"));
  if (request.count < 1) diagnostics.push(diagnostic("error", "Count", "数量必须至少为 1"));
  if (request.count > candidates.length) diagnostics.push(diagnostic("error", "Eligible scope", `请求 ${request.count} 个位置，但当前范围只有 ${candidates.length} 个可用位置`));

  const score = (item) => {
    let value = Number(request.seed) >>> 0;
    for (const character of item.id) value = Math.imul(value ^ character.charCodeAt(0), 2654435761) >>> 0;
    return value;
  };
  const actual = diagnostics.some((item) => item.severity === "error")
    ? []
    : [...candidates].sort((left, right) => score(left) - score(right)).slice(0, request.count).sort((left, right) => residueIndex(left.id) - residueIndex(right.id));
  const insertions = request.operation === "insert" ? backendInsertionFixture(actual, "random") : [];
  return {
    diagnostics,
    actualHandles: actual.map((item) => item.id),
    actualLocators: actual.map(residueLabel),
    insertions,
    effectiveRandomness: { seed: request.seed, count: request.count, scope: `链 A · 位置 ${request.start}–${request.end}` },
  };
}

function handleResidueClick(id, event, source) {
  if (event.shiftKey && state.anchor) {
    const from = residueIndex(state.anchor);
    const to = residueIndex(id);
    const [start, end] = from < to ? [from, to] : [to, from];
    return selectIds(state.residues.slice(start, end + 1).map((item) => item.id), `${source} Shift 区间选择`);
  }
  if (event.metaKey || event.ctrlKey) {
    const next = new Set(state.selected);
    next.has(id) ? next.delete(id) : next.add(id);
    state.anchor = id;
    return selectIds([...next], `${source}追加选择`);
  }
  selectIds([id], `${source}选择`);
}

function previewResiduesForSelection() {
  if (!state.preview) return state.residues;
  if (state.preview.kind !== "delete") return state.preview.projectedResidues;
  const removedInserted = new Set(state.preview.removedInsertedIds);
  return state.residues.filter((item) => !removedInserted.has(item.id));
}

function handlePreviewResidueClick(id, event, source) {
  const residues = previewResiduesForSelection();
  const clickedIndex = residueIndex(id, residues);
  const anchorIndex = residueIndex(state.anchor, residues);
  if (event.shiftKey && anchorIndex >= 0 && clickedIndex >= 0) {
    const [start, end] = anchorIndex < clickedIndex ? [anchorIndex, clickedIndex] : [clickedIndex, anchorIndex];
    state.selected = new Set(residues.slice(start, end + 1).map((item) => item.id));
  } else if (event.metaKey || event.ctrlKey) {
    const next = new Set([...state.selected].filter((handle) => residueById(handle, residues)));
    next.has(id) ? next.delete(id) : next.add(id);
    state.selected = next;
  } else {
    state.selected = new Set([id]);
  }
  state.anchor = id;
  state.lastAction = `${source}定位 preview：${formatSelection(state.selected, residues)}`;
  render();
}

function normalizedSpecifiedValue(key, raw) {
  if (key === "coordinates") return true;
  if (key === "sasa") return Number(raw);
  return String(raw).toUpperCase();
}

function annotationDeleteConsequences(ids, annotations = state.annotations, residues = state.residues) {
  const target = new Set(ids);
  const endpointLosses = [];
  const membershipRealigned = [];
  annotations.forEach((item) => {
    if (target.has(item.startId) || target.has(item.endId)) {
      endpointLosses.push(item);
      return;
    }
    const start = residueIndex(item.startId, residues);
    const end = residueIndex(item.endId, residues);
    if (start < 0 || end < 0) return;
    if (residues.slice(Math.min(start, end), Math.max(start, end) + 1).some((residueItem) => target.has(residueItem.id))) {
      membershipRealigned.push(item);
    }
  });
  return { endpointLosses, membershipRealigned };
}

function makeConditionsPreview() {
  const selected = selectedResidues();
  const projected = clonePrompt();
  const selectedIds = new Set(state.selected);
  const rows = [];
  const diagnostics = [];

  if (!selected.length) diagnostics.push(diagnostic("error", "Selection", "请先在残基轴或结构导航中选择操作对象"));

  Object.entries(state.conditionActions).forEach(([key, action]) => {
    let changed = 0;
    const normalized = normalizedSpecifiedValue(key, action.value);
    if (action.intent === "specify" && key === "sequence" && !/^[A-Z]$/.test(normalized)) {
      diagnostics.push(diagnostic("error", `${TRACKS[key].label} · ${formatSelection()}`, "Sequence 指定值必须是单个大写 residue code", [...state.selected]));
    }
    if (action.intent === "specify" && key === "ss" && !/^[A-Z-]$/.test(normalized)) {
      diagnostics.push(diagnostic("error", `${TRACKS[key].label} · ${formatSelection()}`, "SS8 指定值必须是一个状态字符", [...state.selected]));
    }
    if (action.intent === "specify" && key === "sasa" && (!Number.isFinite(normalized) || normalized < 0)) {
      diagnostics.push(diagnostic("error", `${TRACKS[key].label} · ${formatSelection()}`, "absolute SASA 必须是非负 Å² 数值", [...state.selected]));
    }
    projected.residues.forEach((item) => {
      if (!selectedIds.has(item.id)) return;
      const value = item.tracks[key];
      const before = value.current;
      if (action.intent === "keep") value.preserved = true;
      if (action.intent === "specify" && !diagnostics.some((item) => item.locator.startsWith(TRACKS[key].label))) {
        value.current = normalized;
        value.preserved = false;
      }
      if (action.intent === "mask") {
        value.current = null;
        value.preserved = false;
      }
      if (!equalValue(before, value.current)) changed += 1;
    });
    let detail = `${selected.length} 个位置明确保留当前值；不会发生隐式变化`;
    if (action.intent === "specify") detail = `${changed} 个位置将写入 ${valueText(key, normalized)}`;
    if (action.intent === "mask") detail = `${changed} 个位置将变为 Mask；残基本身保留`;
    rows.push({ key, label: TRACKS[key].label, intent: INTENT_LABELS[action.intent], detail, changed, noop: changed === 0 });
  });

  const changedTotal = rows.reduce((sum, row) => sum + row.changed, 0);
  return {
    kind: "conditions",
    title: `一次应用 ${selected.length} 个残基上的多轨道条件编辑`,
    subtitle: `残基成员与顺序不变；${changedTotal} 个逐轨道值会改变。保留、指定与 Mask 被逐轨道列出。`,
    sentence: `${formatSelection()}：${rows.map((row) => `${row.label} ${row.intent}`).join("；")}。残基成员与顺序不变。`,
    rows,
    diagnostics,
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: [...state.selected],
    danger: false,
    impact: [`residues ${state.residues.length} → ${state.residues.length}`, `${changedTotal} track values change`],
  };
}

function makeLayoutPreview() {
  const selected = selectedResidues();
  const projected = clonePrompt();
  const diagnostics = [];
  if (!selected.length) diagnostics.push(diagnostic("error", "Selection", "请先选择插入锚点或待删除残基"));

  if (state.layoutOperation === "add") {
    const anchor = selected.at(-1);
    const insertionIndex = anchor ? residueIndex(anchor.id, projected.residues) : projected.residues.length - 1;
    const count = Number(state.insertCount);
    if (count < 1) diagnostics.push(diagnostic("error", "Insert count", "新增数量必须至少为 1"));
    const insertionProjection = !anchor || diagnostics.some((item) => item.severity === "error")
      ? []
      : backendPreviewStub({ kind: "explicit-insert", anchor, count }).insertions;
    const inserted = insertionProjection.map((insertion) => {
      const item = residue({
        id: insertion.residueHandle,
        chain: insertion.chain,
        positionLabel: insertion.positionLabel,
        sourceNumber: null,
        sequence: undefined,
        coordinates: undefined,
        ss: undefined,
        sasa: undefined,
        residueState: "inserted",
      });
      Object.values(item.tracks).forEach((value) => { value.current = null; });
      if (state.insertSequence === "assigned") item.tracks.sequence.current = "G";
      return item;
    });
    projected.residues.splice(insertionIndex + 1, 0, ...inserted);
    return {
      kind: "add",
      title: anchor ? `在 ${residueLabel(anchor)} 后新增 ${count} 个残基` : "新增残基",
      subtitle: `后端 preview stub 分配实际插入位置；残基数 ${state.residues.length} → ${projected.residues.length}。`,
      sentence: `${anchor ? `在 ${residueLabel(anchor)} 后` : "在选定位置"}新增 ${count} 个残基；Sequence ${state.insertSequence === "assigned" ? "指定为 G（示意）" : "为 Mask"}；Coordinates、SS8、SASA 均为 Mask；现有 function intervals 保留当前端点。`,
      rows: [
        { label: "残基成员与顺序", intent: "新增", detail: `${state.residues.length} → ${projected.residues.length}；实际位置：${inserted.map(residueLabel).join("；") || "等待有效预览"}`, changed: inserted.length },
        { label: "Sequence", intent: state.insertSequence === "assigned" ? "指定" : "Mask", detail: `${count} 个新增位置`, changed: count },
        { label: "Coordinates / SS8 / SASA", intent: "Mask", detail: `${count} 个新增位置全部未指定`, changed: count * 3 },
        { label: "Function intervals", intent: "保留", detail: "现有区间继续使用当前可定位端点", changed: 0, noop: true },
      ],
      diagnostics,
      projectedResidues: projected.residues,
      projectedAnnotations: projected.annotations,
      projectedSelection: inserted.map((item) => item.id),
      backendHandleCount: inserted.length,
      danger: false,
      impact: [`residues ${state.residues.length} → ${projected.residues.length}`, `${inserted.length} inserted`, `${inserted.length * 4} inserted track slots`],
    };
  }

  const ids = new Set(state.selected);
  const { endpointLosses, membershipRealigned } = annotationDeleteConsequences(ids);
  const lost = Object.keys(TRACKS).map((key) => ({ key, count: selected.filter((item) => item.tracks[key].current !== null && item.tracks[key].current !== undefined).length }));
  projected.annotations = projected.annotations.filter((item) => !ids.has(item.startId) && !ids.has(item.endId));
  projected.residues = projected.residues.filter((item) => !ids.has(item.id));
  const endpointTuples = new Set(endpointLosses.map(annotationTuple));
  const pendingEndpointTuples = annotationProjection(projected.annotations).filter((item) => item.state === "pending-delete" && endpointTuples.has(annotationTuple(item)));
  endpointLosses.forEach((item) => diagnostics.push(diagnostic(
    "warning",
    annotationReadable(item),
    "删除命中 exact endpoint；此完整 function tuple 将从当前 collection 移除",
    [item.startId, item.endId],
  )));
  return {
    kind: "delete",
    title: `删除 ${selected.length} 个残基`,
    subtitle: `残基数 ${state.residues.length} → ${projected.residues.length}；endpoint tuple 精确移除，内部删除只重对齐 interval membership。`,
    sentence: `删除 ${formatSelection()}；残基数减少 ${selected.length}；Sequence、Coordinates、SS8、SASA 对应值全部移除；${endpointLosses.length} 个 endpoint-linked tuples 从当前 collection 移除，其中 ${pendingEndpointTuples.length} 个 source tuples 投影为 pending-delete；${membershipRealigned.length} 个 intervals 保留 exact endpoints 并重对齐成员。`,
    rows: [
      { label: "残基成员与顺序", intent: "待删除", detail: `${state.residues.length} → ${projected.residues.length}；${formatSelection()}`, changed: selected.length },
      ...lost.map((item) => ({ label: TRACKS[item.key].label, intent: "随残基移除", detail: `丢失 ${item.count} 个已指定值；不是 Mask`, changed: item.count })),
      { label: "Function tuples", intent: endpointLosses.length ? "移除 / pending-delete" : "保留", detail: endpointLosses.length ? `${endpointLosses.length} 个当前 tuples 移除；${pendingEndpointTuples.length} 个 source tuples 为 pending-delete` : "没有 exact endpoint 被删除", changed: endpointLosses.length, noop: endpointLosses.length === 0 },
      { label: "Interval membership", intent: membershipRealigned.length ? "重对齐" : "保留", detail: membershipRealigned.length ? `${membershipRealigned.map((item) => annotationReadable(item)).join("；")}；完整 tuple 不变` : "没有仅内部成员被删除的 interval", changed: 0, noop: membershipRealigned.length === 0 },
    ],
    diagnostics,
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: [],
    pendingDeleteIds: selected.filter((item) => item.residueState !== "inserted").map((item) => item.id),
    removedInsertedIds: selected.filter((item) => item.residueState === "inserted").map((item) => item.id),
    danger: true,
    impact: [`residues ${state.residues.length} → ${projected.residues.length}`, ...lost.map((item) => `${TRACKS[item.key].short} −${item.count}`), `FUNC tuples −${endpointLosses.length}`, `source pending-delete ${pendingEndpointTuples.length}`, `interval memberships realigned ${membershipRealigned.length}`],
  };
}

function makeRandomPreview(redraw = false) {
  if (redraw) state.random.seed += 1;
  const response = backendPreviewStub(state.random);
  const projected = clonePrompt();
  const actualItems = response.actualHandles.map((id) => residueById(id));
  const diagnostics = [...response.diagnostics];
  state.random.actual = response.actualLocators;

  if (state.random.operation === "mask") {
    let changed = 0;
    projected.residues.forEach((item) => {
      if (!response.actualHandles.includes(item.id)) return;
      if (item.tracks[state.random.track].current !== null) changed += 1;
      item.tracks[state.random.track].current = null;
      item.tracks[state.random.track].preserved = false;
    });
    return {
      kind: "random-mask",
      title: `随机 Mask ${TRACKS[state.random.track].label} · ${actualItems.length} 个实际位置`,
      subtitle: "实际选择由 backend preview stub 返回；确认应用使用同一份 preview，不在前端重新抽样。",
      sentence: `seed ${state.random.seed}、count ${state.random.count}、${response.effectiveRandomness.scope}；实际位置为 ${response.actualLocators.join("；") || "无"}；仅 ${TRACKS[state.random.track].label} 变为 Mask。`,
      rows: [
        { label: "后端实际选择", intent: "随机 Mask", detail: response.actualLocators.join("；") || "没有可应用位置", changed: actualItems.length },
        ...Object.keys(TRACKS).map((key) => key === state.random.track
          ? { label: TRACKS[key].label, intent: "Mask", detail: `${changed} 个当前值会被清除`, changed }
          : { label: TRACKS[key].label, intent: "保留", detail: "未被本次随机操作触及", changed: 0, noop: true }),
        { label: "Function intervals", intent: "保留", detail: "区间 collection 不变", changed: 0, noop: true },
      ],
      diagnostics,
      backendActual: response,
      projectedResidues: projected.residues,
      projectedAnnotations: projected.annotations,
      projectedSelection: response.actualHandles,
      danger: false,
      impact: [`seed ${state.random.seed}`, `actual ${actualItems.length}`, `${TRACKS[state.random.track].short} cleared ${changed}`],
    };
  }

  const inserted = [];
  [...response.insertions].sort((left, right) => residueIndex(right.afterHandle, projected.residues) - residueIndex(left.afterHandle, projected.residues)).forEach((insertion) => {
    const anchor = residueById(insertion.afterHandle, projected.residues);
    const item = residue({
      id: insertion.residueHandle,
      chain: insertion.chain,
      positionLabel: insertion.positionLabel,
      sourceNumber: null,
      sequence: undefined,
      coordinates: undefined,
      ss: undefined,
      sasa: undefined,
      residueState: "inserted",
    });
    Object.values(item.tracks).forEach((value) => { value.current = null; });
    if (state.random.insertSequence === "assigned") item.tracks.sequence.current = "G";
    projected.residues.splice(residueIndex(anchor.id, projected.residues) + 1, 0, item);
    inserted.push(item);
  });
  inserted.sort((left, right) => residueIndex(left.id, projected.residues) - residueIndex(right.id, projected.residues));
  state.random.actual = inserted.map(residueLabel);
  return {
    kind: "random-insert",
    title: `随机插入 · ${inserted.length} 个实际位置`,
    subtitle: "插入位置与内部身份均由 backend preview stub 分配；界面只显示 chain/position locator。",
    sentence: `seed ${state.random.seed}、count ${state.random.count}、${response.effectiveRandomness.scope}；实际插入位置为 ${inserted.map(residueLabel).join("；") || "无"}。`,
    rows: [
      { label: "后端实际插入位置", intent: "新增", detail: inserted.map(residueLabel).join("；") || "没有可应用位置", changed: inserted.length },
      { label: "Sequence", intent: state.random.insertSequence === "assigned" ? "指定" : "Mask", detail: `${inserted.length} 个新增位置`, changed: inserted.length },
      { label: "Coordinates / SS8 / SASA", intent: "Mask", detail: `${inserted.length} 个新增位置全部未指定`, changed: inserted.length * 3 },
      { label: "Function intervals", intent: "保留", detail: "现有区间端点不变", changed: 0, noop: true },
    ],
    diagnostics,
    backendActual: response,
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: inserted.map((item) => item.id),
    backendHandleCount: inserted.length,
    danger: false,
    impact: [`seed ${state.random.seed}`, `residues ${state.residues.length} → ${projected.residues.length}`, `inserted ${inserted.length}`],
  };
}

function selectionAsContinuousRange() {
  const items = selectedResidues();
  if (!items.length || selectionRuns() !== 1) return null;
  return { startId: items[0].id, endId: items.at(-1).id };
}

function activeAnnotation(annotations = state.annotations) {
  return annotations[state.activeAnnotationIndex] ?? null;
}

function annotationReadable(item, residues = state.residues) {
  const start = residueById(item.startId, residues);
  const end = residueById(item.endId, residues);
  return `${item.label} · ${start ? residueLabel(start) : "起点已删除"} → ${end ? residueLabel(end) : "终点已删除"}`;
}

function makeFunctionPreview() {
  const projected = clonePrompt();
  const active = activeAnnotation(projected.annotations);
  const range = selectionAsContinuousRange();
  const rows = [];
  const diagnostics = [];
  let title = "Function annotation preview";
  let sentence = "Function annotation collection 保持不变。";

  if (["add", "modify"].includes(state.functionAction) && !range) {
    diagnostics.push(diagnostic("error", `Selection · ${formatSelection()}`, "添加或修改 interval 需要一个连续残基区间；不连续选择不会被自动扩张", [...state.selected]));
  }
  if (["modify", "split", "delete"].includes(state.functionAction) && !active) {
    diagnostics.push(diagnostic("error", "Function interval", "请选择要操作的 function annotation tuple"));
  }
  const blocked = diagnostics.some((item) => item.severity === "error");

  if (state.functionAction === "add" && !blocked) {
    const created = annotation({ label: state.functionLabel, ...range });
    projected.annotations.push(created);
    const createdState = annotationProjection(projected.annotations)[projected.annotations.length - 1].state;
    title = `添加 1 条 function annotation interval`;
    sentence = `在 ${formatSelection()} 添加 “${created.label}”；exact tuple projection 为 ${createdState}，其他 function intervals 与逐残基轨道保留当前值。`;
    rows.push({ label: "Function tuple", intent: createdState, detail: annotationReadable(created, projected.residues), changed: 1 });
  }

  if (state.functionAction === "modify" && !blocked) {
    const before = structuredClone(active);
    active.label = state.functionLabel;
    active.startId = range.startId;
    active.endId = range.endId;
    if (annotationTuple(before) === annotationTuple(active)) {
      const exactState = annotationStateAtIndex(state.activeAnnotationIndex);
      title = `Function annotation tuple 保持不变`;
      sentence = `${annotationReadable(active)} 的完整 (label, start, end) tuple 未改变；这是 ${exactState} no-op。`;
      rows.push({ label: "Function tuple", intent: `${exactState} / no-op`, detail: annotationReadable(active), changed: 0, noop: true });
    } else {
      const replacementState = annotationProjection(projected.annotations)[state.activeAnnotationIndex].state;
      title = `替换 1 个 function annotation tuple`;
      sentence = `旧 tuple ${annotationReadable(before)} 被移除；新 tuple ${annotationReadable(active)} 的 exact projection 为 ${replacementState}。Function annotation 没有可供“修改”的稳定公共 ID。`;
      rows.push({ label: "旧 Function tuple", intent: sourceTuplePendingAfter(before, projected.annotations) ? "pending-delete" : "移除 inserted tuple", detail: annotationReadable(before), changed: 1 });
      rows.push({ label: "新 Function tuple", intent: replacementState, detail: annotationReadable(active), changed: 1 });
    }
  }

  if (state.functionAction === "split" && !blocked) {
    const start = residueIndex(active.startId, projected.residues);
    const end = residueIndex(active.endId, projected.residues);
    const splitResidue = projected.residues.find((item) => item.sourceNumber === state.splitAt);
    const splitId = splitResidue?.id;
    const splitIndex = residueIndex(splitId, projected.residues);
    if (start < 0 || end < 0 || splitIndex <= start || splitIndex > end) {
      diagnostics.push(diagnostic("error", `链 A · 位置 ${state.splitAt}`, "拆分点必须位于所选 interval 内部且不能是首个残基", splitResidue ? [splitResidue.id] : []));
    } else {
      const before = structuredClone(active);
      const originalEnd = active.endId;
      active.endId = projected.residues[splitIndex - 1].id;
      const created = annotation({ label: active.label, startId: splitId, endId: originalEnd });
      projected.annotations.push(created);
      const splitProjection = annotationProjection(projected.annotations);
      const firstState = splitProjection[state.activeAnnotationIndex].state;
      const secondState = splitProjection[projected.annotations.length - 1].state;
      title = `把 1 个 function tuple 拆分为 2 个结果 tuples`;
      sentence = `旧 tuple ${annotationReadable(before)} 被移除；结果为 ${annotationReadable(active)} (${firstState}) 与 ${annotationReadable(created)} (${secondState})；不创建逐残基 null mask。`;
      rows.push({ label: "旧 Function tuple", intent: sourceTuplePendingAfter(before, projected.annotations) ? "pending-delete" : "移除 inserted tuple", detail: annotationReadable(before), changed: 1 });
      rows.push({ label: "新 Function tuple 1", intent: firstState, detail: annotationReadable(active), changed: 1 });
      rows.push({ label: "新 Function tuple 2", intent: secondState, detail: annotationReadable(created), changed: 1 });
    }
  }

  if (state.functionAction === "delete" && !blocked) {
    projected.annotations.splice(state.activeAnnotationIndex, 1);
    title = `删除 1 个 function annotation tuple`;
    sentence = `删除 ${annotationReadable(active)}；残基成员、顺序与四条逐残基轨道保留当前值。`;
    rows.push({ label: "Function tuple", intent: sourceTuplePendingAfter(active, projected.annotations) ? "pending-delete" : "移除 inserted tuple", detail: annotationReadable(active), changed: 1 });
  }

  rows.push({ label: "残基成员与顺序", intent: "保留", detail: `${state.residues.length} residues；位置与顺序不变`, changed: 0, noop: true });
  rows.push({ label: "SEQ / XYZ / SS8 / SASA", intent: "保留", detail: "所有逐残基值不变", changed: 0, noop: true });
  return {
    kind: `function-${state.functionAction}`,
    title,
    subtitle: "Function annotations 使用 interval 操作；不是可逐残基 Mask 的 scalar track。",
    sentence,
    rows,
    diagnostics,
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: [...state.selected],
    danger: state.functionAction === "delete",
    impact: [`residues unchanged ${state.residues.length}`, `function intervals ${state.annotations.length} → ${projected.annotations.length}`, "per-residue tracks unchanged"],
  };
}

function buildPreview(redrawRandom = false) {
  const selectionBeforePreview = state.preview?.selectionBeforePreview ?? [...state.selected].filter((id) => residueById(id));
  const anchorBeforePreview = state.preview?.anchorBeforePreview ?? (residueById(state.anchor) ? state.anchor : selectionBeforePreview.at(-1) ?? null);
  const result = state.selectionMode === "random"
    ? makeRandomPreview(redrawRandom)
    : state.tool === "conditions"
      ? makeConditionsPreview()
      : state.tool === "layout"
        ? makeLayoutPreview()
        : makeFunctionPreview();
  state.preview = result;
  result.selectionBeforePreview = selectionBeforePreview;
  result.anchorBeforePreview = anchorBeforePreview;
  if (result.backendActual) {
    state.selected = new Set(result.projectedSelection);
    state.anchor = result.projectedSelection.at(-1) ?? null;
  }
  state.checklist = new Set();
  state.lastAction = `backend preview stub 已返回：${result.title}`;
  addToast(`预览已返回${result.diagnostics.length ? `，含 ${result.diagnostics.length} 条可定位 diagnostics` : ""}；ProteinPrompt 尚未改变`);
  render();
}

function applyPreview() {
  if (!state.preview) return;
  if (state.preview.diagnostics.some((item) => item.severity === "error")) {
    addToast("请先处理 preview 中的全部 error diagnostics", "warn");
    renderToasts();
    return;
  }
  if (state.variant === "C" && state.checklist.size < checklistItems().length) {
    addToast("请先逐项核对操作配方", "warn");
    renderToasts();
    return;
  }
  const preview = state.preview;
  const undoSnapshot = currentSnapshot(preview.title);
  undoSnapshot.selected = [...preview.selectionBeforePreview];
  undoSnapshot.anchor = preview.anchorBeforePreview;
  state.undoStack.push(undoSnapshot);
  state.residues = structuredClone(preview.projectedResidues);
  state.annotations = structuredClone(preview.projectedAnnotations);
  state.selected = new Set(preview.projectedSelection.filter((id) => residueById(id, state.residues)));
  state.anchor = [...state.selected].at(-1) ?? null;
  state.backendRevision += 1;
  state.nextBackendHandleIndex += preview.backendHandleCount ?? 0;
  if (state.activeAnnotationIndex >= state.annotations.length) state.activeAnnotationIndex = Math.max(0, state.annotations.length - 1);
  state.preview = null;
  state.checklist = new Set();
  state.lastAction = `已应用：${preview.title}`;
  addToast(`${state.lastAction}；可撤销`);
  render();
}

function undo() {
  const previous = state.undoStack.pop();
  if (!previous) {
    addToast("没有可撤销的原型编辑", "warn");
    renderToasts();
    return;
  }
  state.residues = previous.residues;
  state.annotations = previous.annotations;
  state.sourceAnnotations = previous.sourceAnnotations;
  state.selected = new Set(previous.selected);
  state.anchor = previous.anchor;
  state.backendRevision = previous.backendRevision;
  state.nextBackendHandleIndex = previous.nextBackendHandleIndex;
  state.preview = null;
  state.checklist = new Set();
  state.lastAction = `撤销：${previous.label}`;
  addToast(state.lastAction);
  render();
}

function switchTool(tool) {
  if (tool === "structure") {
    addToast("结构坐标刚体编辑属于原型 5；本原型只保留 Coordinates 条件操作", "warn");
    renderToasts();
    return;
  }
  restorePrePreviewSelection();
  state.tool = tool;
  state.preview = null;
  state.checklist = new Set();
  state.lastAction = `切换操作区：${tool === "layout" ? "新增 / 删除" : tool === "conditions" ? "条件" : "Function intervals"}；所有轨道仍可见`;
  render();
}

function switchVariant(key, updateUrl = true) {
  state.variant = key;
  if (updateUrl) {
    const url = new URL(location.href);
    url.searchParams.set("variant", key);
    history.replaceState({}, "", url);
  }
  state.checklist = new Set();
  state.lastAction = `切换原型方案：${VARIANTS[key].label}`;
  render();
}

function cycleVariant(direction) {
  const keys = Object.keys(VARIANTS);
  const index = keys.indexOf(state.variant);
  switchVariant(keys[(index + direction + keys.length) % keys.length]);
}

function annotationRange(item, residues = state.residues) {
  const start = residueIndex(item.startId, residues);
  const end = residueIndex(item.endId, residues);
  return { start, end, valid: start >= 0 && end >= start };
}

function renderTopbar() {
  return `<header class="topbar">
    <div class="brand"><span class="brand-mark">PWB</span><div><strong>Protein Workbench</strong><small>PROTEINPROMPT STUDIO</small></div></div>
    <div class="prompt-title"><span>Workflow / 编写 ProteinPrompt /</span><strong>1CRN condition design（示意）</strong><em class="prototype-badge">一次性原型 3</em></div>
    <div class="top-actions"><button class="button ghost" data-action="undo" ${state.undoStack.length ? "" : "disabled"}>撤销${state.undoStack.length ? ` (${state.undoStack.length})` : ""}</button><button class="button ghost" data-action="cancel-studio">取消</button><button class="button primary" data-action="save">保存 ProteinPrompt</button></div>
  </header>`;
}

function renderControlbar() {
  return `<section class="controlbar">
    <div class="mode-tabs"><span>编辑模式</span><div class="segmented">
      <button data-tool="layout" class="${state.tool === "layout" ? "active" : ""}">新增 / 删除</button>
      <button data-tool="conditions" class="${state.tool === "conditions" ? "active" : ""}">条件</button>
      <button data-tool="function" class="${state.tool === "function" ? "active" : ""}">Function intervals</button>
      <button data-tool="structure">结构 ↗ 原型 5</button>
    </div></div>
    <div class="selection-tabs"><span>操作来源</span><div class="segmented"><button data-selection-mode="explicit" class="${state.selectionMode === "explicit" ? "active" : ""}">明确选择</button><button data-selection-mode="random" class="${state.selectionMode === "random" ? "active" : ""}">后端随机操作</button></div></div>
    <div class="prompt-stats"><span>A · ${state.residues.length} residues</span>${Object.keys(TRACKS).map((key) => `<span>${TRACKS[key].short} ${countAssigned(key)}/${state.residues.length}</span>`).join("")}<span>FUNC ${state.annotations.length}</span></div>
  </section>`;
}

function renderSelectionPanel() {
  const randomActual = state.selectionMode === "random" && state.random.actual.length ? state.random.actual.join("；") : "尚未请求预览";
  return `<section class="surface selection-panel">
    <div class="surface-header"><div><span class="surface-kicker">Public locator contract</span><h2>${state.selectionMode === "random" ? "随机 Mask / 随机插入" : "明确选择"}</h2></div><span class="surface-note">${state.selected.size} selected</span></div>
    <div class="selection-readout"><span>用户可定位的 chain / position</span><strong>${state.selectionMode === "random" ? randomActual : formatSelection()}</strong><small>${state.selectionMode === "random" ? `count ${state.random.count} · 链 A / 位置 ${state.random.start}–${state.random.end} · seed ${state.random.seed}` : "内部 opaque handles 不显示；矩阵与结构导航同步"}</small></div>
    <div class="selection-body">
      ${state.selectionMode === "explicit" ? `<div class="preset-grid"><button data-preset="single">链 A · 位置 16</button><button data-preset="continuous">链 A · 位置 12–20</button><button data-preset="disjoint">不连续 8–12 + 23–25</button><button data-preset="changed">全部变化位置</button></div><div class="semantic-note">选择只确定操作对象；领域操作为保留、指定、Mask、新增或删除。</div>` : `<div class="form-grid">
        <label class="field full"><span>随机操作</span><select data-random-field="operation"><option value="mask" ${state.random.operation === "mask" ? "selected" : ""}>随机 Mask</option><option value="insert" ${state.random.operation === "insert" ? "selected" : ""}>随机插入</option></select></label>
        ${state.random.operation === "mask" ? `<label class="field full"><span>Mask 目标轨道</span><select data-random-field="track">${Object.entries(TRACKS).map(([key, item]) => `<option value="${key}" ${state.random.track === key ? "selected" : ""}>${item.label}</option>`).join("")}</select></label>` : `<label class="field full"><span>新增 Sequence 初始状态</span><select data-random-field="insertSequence"><option value="mask" ${state.random.insertSequence === "mask" ? "selected" : ""}>Mask</option><option value="assigned" ${state.random.insertSequence === "assigned" ? "selected" : ""}>指定为 G（示意）</option></select></label>`}
        <label class="field"><span>数量</span><input data-random-field="count" type="number" min="1" max="30" value="${state.random.count}"></label>
        <label class="field"><span>随机种子</span><input data-random-field="seed" type="number" value="${state.random.seed}"></label>
        <label class="field"><span>允许范围起点</span><input data-random-field="start" type="number" min="1" max="46" value="${state.random.start}"></label>
        <label class="field"><span>允许范围终点</span><input data-random-field="end" type="number" min="1" max="46" value="${state.random.end}"></label>
        <button class="button" data-action="preview-random">请求后端预览</button><button class="button" data-action="redraw-random">换 seed 重抽预览</button>
      </div><div class="random-facts"><span><b>实际位置</b><br>${randomActual}</span><span><b>确认边界</b><br>确认前不修改 Prompt</span></div><div class="semantic-note">前端只提交 seed、count 与 eligible scope；backend preview stub 返回实际选择与 effective randomness。</div>`}
    </div>
  </section>`;
}

function structureCoordinates(item, index, count) {
  const angle = index * 0.67;
  const radius = 25 + 12 * Math.sin(index * 0.41) + (index / count) * 34;
  return { x: 105 + Math.cos(angle) * radius, y: 62 + Math.sin(angle) * (28 + 9 * Math.cos(index * 0.23)) };
}

function renderStructure() {
  const points = state.residues.filter((item) => item.tracks.coordinates.current || item.tracks.coordinates.source).map((item, index, items) => ({ item, ...structureCoordinates(item, index, items.length) }));
  const path = points.map((point) => `${point.x},${point.y}`).join(" ");
  const pending = new Set(state.preview?.pendingDeleteIds ?? []);
  return `<section class="surface structure-nav">
    <div class="surface-header"><div><span class="surface-kicker">Synchronized navigator</span><h2>结构导航 · 实际选择位置</h2></div><span class="surface-note">几何示意；locator 同步</span></div>
    <div class="structure-stage"><svg viewBox="0 0 210 124" preserveAspectRatio="none"><polyline class="backbone" points="${path}"/>${points.map((point) => `<g class="structure-point ${state.selected.has(point.item.id) ? "selected" : ""} ${pending.has(point.item.id) ? "pending" : ""} ${!point.item.tracks.coordinates.current ? "masked-coordinate" : ""}" data-residue="${point.item.id}" transform="translate(${point.x} ${point.y})"><circle r="${state.selected.has(point.item.id) ? 6 : 3.7}"/><text y="-8">${state.selected.has(point.item.id) ? point.item.positionLabel : ""}</text></g>`).join("")}</svg></div>
    <div class="structure-caption"><b>${formatSelection()}</b> · 空心点只显示来源参考位置：当前 Coordinates 已 Mask，不再是结构 conditioning。</div>
  </section>`;
}

function renderTrackCells(key, residues, compareResidues = null, pendingIds = new Set()) {
  return residues.map((item) => {
    const compare = compareResidues ? residueById(item.id, compareResidues) : null;
    const before = item.tracks[key].current;
    const after = compare ? compare.tracks[key].current : before;
    const changed = compare && !equalValue(before, after);
    const status = pendingIds.has(item.id) ? "pending-delete" : compare ? trackState(compare, key) : trackState(item, key);
    const value = changed ? `${valueText(key, before)}→${valueText(key, after)}` : valueText(key, after);
    const masked = after === null || after === undefined;
    return `<button class="track-cell state-${status} ${masked ? "masked" : ""} ${state.selected.has(item.id) ? "selected" : ""} ${pendingIds.has(item.id) ? "pending-delete" : ""} ${changed ? "preview-change" : ""}" data-residue="${item.id}" title="${residueLabel(item)} · ${TRACKS[key].label} · ${status}"><span class="value">${value}</span><span class="cell-state">${status}</span></button>`;
  }).join("");
}

function annotationsAtResidue(item, annotations, residues) {
  const index = residueIndex(item.id, residues);
  return annotations.filter((annotationItem) => {
    const range = annotationRange(annotationItem, residues);
    return range.valid && index >= range.start && index <= range.end;
  });
}

function renderFunctionCells(residues, annotations) {
  const projectedAnnotations = annotationProjection(annotations);
  return residues.map((item, index) => {
    const matches = annotationsAtResidue(item, projectedAnnotations, residues);
    if (!matches.length) return `<button class="track-cell masked ${state.selected.has(item.id) ? "selected" : ""}" data-residue="${item.id}"><span class="value">—</span><span class="cell-state">none</span></button>`;
    const priority = (annotationItem) => annotationState(annotationItem) === "inserted" ? 3 : annotationState(annotationItem) === "pending-delete" ? 2 : 1;
    const active = [...matches].sort((left, right) => priority(right) - priority(left))[0];
    const range = annotationRange(active, residues);
    const first = index === range.start;
    const status = annotationState(active);
    const states = [...new Set(matches.map(annotationState))];
    const overlap = matches.length > 1 ? ` +${matches.length - 1}` : "";
    return `<button class="track-cell function-ribbon ${status} ${states.length > 1 ? "tuple-replaced" : ""} ${state.selected.has(item.id) ? "selected" : ""}" data-residue="${item.id}" title="${matches.map((annotationItem) => `${annotationReadable(annotationItem, residues)} · ${annotationState(annotationItem)}`).join(" | ")}"><span class="value">${first ? `${active.label}${overlap}` : `━${overlap}`}</span><span class="cell-state">${first ? states.join(" + ") : ""}</span></button>`;
  }).join("");
}

function renderMatrix({ residues = state.residues, annotations = state.annotations, compareResidues = null, pendingIds = new Set(), compact = false } = {}) {
  return `<div class="matrix-scroll"><div class="matrix ${compact ? "compact" : ""}" style="--residue-count:${residues.length}">
    <div class="track-label"><strong>Residue axis</strong><small>chain / position locator</small></div>${residues.map((item) => `<button class="axis-cell state-${pendingIds.has(item.id) ? "pending-delete" : item.residueState} ${state.selected.has(item.id) ? "selected" : ""} ${pendingIds.has(item.id) ? "pending-delete" : ""} ${item.residueState === "inserted" ? "preview-inserted" : ""}" data-residue="${item.id}" title="${residueLabel(item)}"><small>${item.chain}</small><strong>${item.positionLabel}</strong></button>`).join("")}
    ${Object.entries(TRACKS).map(([key, meta]) => `<div class="track-label"><strong>${meta.label}</strong><small>${meta.unit}</small></div>${renderTrackCells(key, residues, compareResidues, pendingIds)}`).join("")}
    <div class="track-label"><strong>Function annotations</strong><small>tuple interval ribbons</small></div>${renderFunctionCells(residues, annotations)}
  </div></div>`;
}

function matrixProjectionProps() {
  if (!state.preview) return { residues: state.residues, annotations: state.annotations };
  if (state.preview.kind === "add") return { residues: state.preview.projectedResidues, annotations: state.preview.projectedAnnotations };
  if (state.preview.kind === "delete") {
    const removedInserted = new Set(state.preview.removedInsertedIds);
    return { residues: state.residues.filter((item) => !removedInserted.has(item.id)), annotations: state.preview.projectedAnnotations, pendingIds: new Set(state.preview.pendingDeleteIds) };
  }
  if (state.preview.kind.startsWith("function")) {
    return { residues: state.residues, annotations: state.preview.projectedAnnotations };
  }
  if (state.preview.kind === "random-insert") return { residues: state.preview.projectedResidues, annotations: state.preview.projectedAnnotations };
  return { residues: state.residues, annotations: state.annotations, compareResidues: state.preview.projectedResidues };
}

function renderMatrixSurface() {
  return `<section class="surface matrix-surface"><div class="surface-header"><div><span class="surface-kicker">Adopted Variant A matrix</span><h2>残基账本 · chain / position 共享轴</h2></div><span class="surface-note">${state.preview ? "未应用预览已叠加" : "当前 ProteinPrompt"}</span></div>${renderMatrix(matrixProjectionProps())}${renderLegend()}</section>`;
}

function renderLegend() {
  return `<div class="matrix-legend"><span><i class="legend-dot source"></i>source</span><span><i class="legend-dot current"></i>current</span><span><i class="legend-dot changed"></i>changed</span><span><i class="legend-dot cleared"></i>cleared</span><span><i class="legend-dot inserted"></i>inserted</span><span><i class="legend-dot pending"></i>pending-delete</span><b class="legend-note">六态同时使用文字与形状</b></div>`;
}

function renderConditionsEditor() {
  return `<div class="mode-explainer">同一次应用可以组合多个轨道。每条轨道只接受 <b>保留、指定、Mask</b>：保留是明确 no-op，Mask 只清除所选轨道，不删除残基。</div><div class="track-actions">${Object.entries(TRACKS).map(([key, meta]) => {
    const action = state.conditionActions[key];
    return `<div class="track-action"><label><b>${meta.label}</b><small>${meta.unit}</small></label><div class="track-action-controls"><select data-condition-intent="${key}">${Object.entries(INTENT_LABELS).map(([value, label]) => `<option value="${value}" ${action.intent === value ? "selected" : ""}>${label}</option>`).join("")}</select><input data-condition-value="${key}" value="${action.value}" ${action.intent === "specify" ? "" : "disabled"} aria-label="${meta.label} 指定值"></div></div>`;
  }).join("")}</div><div class="semantic-note">Coordinates 的 Mask 会清除结构 conditioning；它不是三维 viewer 的临时 hide/show。SASA 单位固定为 Å²。</div>`;
}

function renderLayoutEditor() {
  return `<div class="mode-explainer"><b>新增 / 删除</b>改变残基成员与顺序；这与把已有残基上的某条轨道设为 Mask 是不同类别的科学操作。</div><div class="layout-actions"><button class="operation-card ${state.layoutOperation === "add" ? "active" : ""}" data-layout-operation="add"><h3>新增残基</h3><p>在 chain / position locator 后新增；每条新轨道明确指定或 Mask</p></button><button class="operation-card ${state.layoutOperation === "delete" ? "active" : ""}" data-layout-operation="delete"><h3>删除残基</h3><p>残基与全部轨道对应值一起移除</p></button></div>${state.layoutOperation === "add" ? `<div class="form-grid" style="margin-top:8px"><label class="field"><span>新增数量</span><input data-layout-field="count" type="number" min="1" max="12" value="${state.insertCount}"></label><label class="field"><span>新增 Sequence 状态</span><select data-layout-field="sequence"><option value="mask" ${state.insertSequence === "mask" ? "selected" : ""}>Mask / 未指定</option><option value="assigned" ${state.insertSequence === "assigned" ? "selected" : ""}>指定为 G（示意）</option></select></label></div><div class="semantic-note">科学身份由 backend preview stub 创建且不显示；界面只呈现链与插入位置。Coordinates、SS8 和 SASA 在本例中为 Mask。</div>` : `<div class="semantic-note">删除预览会逐轨道列出丢失值，并一次显示所有可定位的 function interval diagnostics；不会自动修复。</div>`}`;
}

function renderFunctionEditor() {
  return `<div class="mode-explainer">Function annotations 是有标签的 residue intervals；只提供添加、修改、拆分和删除，不提供逐残基 Mask。</div><div class="annotation-list">${state.annotations.map((item, index) => {
    const range = annotationRange(item);
    const start = residueById(item.startId);
    const end = residueById(item.endId);
    return `<button data-annotation-index="${index}" class="${state.activeAnnotationIndex === index ? "active" : ""}"><span>${item.label}</span><small>${range.valid ? `${residueLabel(start)} → ${residueLabel(end)}` : "端点失效"} · ${annotationStateAtIndex(index)}</small></button>`;
  }).join("")}</div><div class="function-actions">${["add", "modify", "split", "delete"].map((value) => `<button data-function-action="${value}" class="${state.functionAction === value ? "active" : ""}">${{ add: "添加", modify: "修改", split: "拆分", delete: "删除" }[value]}</button>`).join("")}</div><div class="form-grid">
    <label class="field full"><span>Function label（示意；正式词表未裁决）</span><input data-function-field="label" value="${state.functionLabel}"></label>
    ${state.functionAction === "split" ? `<label class="field full"><span>第二个 interval 起点 · 链 A 的位置</span><input data-function-field="split" type="number" min="2" max="46" value="${state.splitAt}"></label>` : ""}
  </div><div class="semantic-note">Annotation 没有稳定公共 ID。修改会在预览中显示为旧完整 tuple pending-delete + 新完整 tuple inserted。</div>`;
}

function renderRandomEditor() {
  return `<div class="mode-explainer">随机操作的正式语义只来自 backend preview。这里不会用前端 sampler 预判结果。</div><div class="selection-readout"><span>请求</span><strong>${state.random.operation === "mask" ? `随机 Mask ${TRACKS[state.random.track].label}` : "随机插入残基"}</strong><small>seed ${state.random.seed} · count ${state.random.count} · 链 A / 位置 ${state.random.start}–${state.random.end}</small></div><div class="semantic-note">“生成预览”返回全部实际位置、effective randomness、完整 track 后果与所有 diagnostics；换 seed 后重抽，确认后才应用。</div>`;
}

function renderEditor() {
  const random = state.selectionMode === "random";
  return `<section class="surface editor-surface"><div class="surface-header"><div><span class="surface-kicker">Joint operation composer</span><h2>${random ? "后端随机 authoring" : state.tool === "conditions" ? "多轨道条件编辑" : state.tool === "layout" ? "残基成员编辑" : "Function intervals"}</h2></div><span class="surface-note">${state.selected.size} residues</span></div><div class="selection-readout" style="margin:8px 8px 0"><span>${random ? "backend preview 返回的实际位置" : "操作对象"}</span><strong>${random ? (state.random.actual.join("；") || "等待预览") : formatSelection()}</strong></div><div class="editor-body">${random ? renderRandomEditor() : state.tool === "conditions" ? renderConditionsEditor() : state.tool === "layout" ? renderLayoutEditor() : renderFunctionEditor()}</div><div class="editor-footer"><button class="button ghost" data-action="reset-composer">重置本区</button><button class="button primary" data-action="build-preview">${random ? "请求 backend preview" : "生成未应用预览"}</button></div></section>`;
}

function renderPreviewContent(recipe = false) {
  if (!state.preview) return `<div class="preview-empty"><div><b>尚无待确认变更</b><p>先组成残基新增/删除、逐轨道条件、Function tuple 或随机操作，再请求预览。预览期间 ProteinPrompt 本体不会变化。</p></div></div>`;
  if (recipe) return renderRecipe();
  return `<div class="preview-body"><div class="preview-headline"><span>backend preview · 未应用</span><strong>${state.preview.title}</strong><p>${state.preview.subtitle}</p></div>${renderDiagnostics()}<div class="ledger">${state.preview.rows.map((row) => `<div class="ledger-row ${row.noop ? "noop" : ""}"><b>${row.label}</b><span class="intent">${row.intent}</span><p>${row.detail}</p></div>`).join("")}</div><div class="impact-tags">${state.preview.impact.map((item) => `<span>${item}</span>`).join("")}</div><div class="preview-summary"><b>完整 Prompt summary</b><span>${state.preview.projectedResidues.length} residues · ${Object.keys(TRACKS).map((key) => `${TRACKS[key].short} ${countAssigned(key, state.preview.projectedResidues)}`).join(" · ")} · FUNC ${state.preview.projectedAnnotations.length}</span></div></div>`;
}

function renderDiagnostics() {
  const diagnostics = state.preview?.diagnostics ?? [];
  if (!diagnostics.length) return `<div class="diagnostics clean"><b>Diagnostics · 0</b><span>没有需要用户处理的问题</span></div>`;
  return `<div class="diagnostics"><div class="diagnostics-title"><b>一次返回全部可定位 diagnostics · ${diagnostics.length}</b><span>${diagnostics.filter((item) => item.severity === "error").length} errors</span></div>${diagnostics.map((item, index) => `<button data-diagnostic-index="${index}" class="diagnostic ${item.severity}"><b>${item.severity}</b><span>${item.locator}</span><p>${item.message}</p></button>`).join("")}</div>`;
}

function renderPreviewActions() {
  if (!state.preview) return "";
  const blocked = state.preview.diagnostics.some((item) => item.severity === "error") || (state.variant === "C" && state.checklist.size < checklistItems().length);
  return `<div class="preview-actions"><button class="button ghost" data-action="cancel-preview">取消预览</button><button class="button apply ${state.preview.danger ? "danger" : ""}" data-action="apply-preview" ${blocked ? "disabled" : ""}>${state.preview.danger ? "确认并应用高影响变更" : "确认并一次应用"}</button></div>`;
}

function renderPreviewSurface() {
  return `<section class="surface preview-surface"><div class="surface-header"><div><span class="surface-kicker">Variant A · transaction language</span><h2>变更账本</h2></div><span class="surface-note">${state.preview ? "Prompt 尚未改变" : "等待预览"}</span></div>${renderPreviewContent()}${renderPreviewActions()}</section>`;
}

function renderCompareSurface() {
  const afterResidues = state.preview?.projectedResidues ?? state.residues;
  const afterAnnotations = state.preview?.projectedAnnotations ?? state.annotations;
  return `<section class="surface compare-surface"><div class="surface-header"><div><span class="surface-kicker">Variant B · same-axis comparison</span><h2>${state.preview ? state.preview.title : "当前态 / 拟应用态"}</h2></div><span class="surface-note">${state.preview ? "右侧仍是未应用提案" : "尚无提案"}</span></div>${state.preview ? `<div class="compare-diagnostics">${renderDiagnostics()}</div>` : ""}<div class="before-after"><section><div class="compare-title"><b>当前 ProteinPrompt</b><span>${state.residues.length} residues</span></div>${renderMatrix({ residues: state.residues, annotations: state.annotations, pendingIds: new Set(state.preview?.pendingDeleteIds ?? []) })}</section><section><div class="compare-title"><b>拟应用后</b><span>${afterResidues.length} residues</span></div>${renderMatrix({ residues: afterResidues, annotations: afterAnnotations })}</section></div>${renderPreviewActions()}</section>`;
}

function checklistItems() {
  if (!state.preview) return [];
  const operationObject = state.selectionMode === "random" ? (state.random.actual.join("；") || "没有实际位置") : formatSelection();
  const items = [
    `我已核对操作对象：${operationObject}`,
    ["add", "delete", "random-insert"].includes(state.preview.kind) ? `我已核对残基成员与顺序：${state.residues.length} → ${state.preview.projectedResidues.length}` : `我确认残基成员与顺序保留 ${state.residues.length} residues`,
    "我已逐条核对 Sequence、Coordinates、SS8、SASA 和 Function intervals 的保留、指定、Mask、新增或删除",
  ];
  if (state.selectionMode === "random") items.unshift(`我已核对后端实际位置、count ${state.random.count}、链 A / 位置 ${state.random.start}–${state.random.end} 与 seed ${state.random.seed}`);
  return items;
}

function renderRecipe() {
  const steps = state.preview.rows.map((row, index) => `<div class="recipe-step"><span>${index + 1}</span><div><b>${row.label} · ${row.intent}</b><p>${row.detail}</p></div></div>`).join("");
  return `<div class="preview-body">${renderDiagnostics()}<div class="recipe-list">${steps}</div><div class="recite"><b>请复述：</b><br>${state.preview.sentence}</div><div class="checklist">${checklistItems().map((item, index) => `<label><input type="checkbox" data-check="${index}" ${state.checklist.has(index) ? "checked" : ""}><span>${item}</span></label>`).join("")}</div></div>`;
}

function renderRecipeSurface() {
  return `<section class="surface recipe-surface"><div class="surface-header"><div><span class="surface-kicker">Variant C · command recipe</span><h2>操作配方与复述清单</h2></div><span class="surface-note">${state.preview ? "逐项核对后可应用" : "等待配方"}</span></div>${renderPreviewContent(true)}${renderPreviewActions()}</section>`;
}

function renderVariant() {
  if (state.variant === "A") return `<main class="workspace variant-a">${renderSelectionPanel()}${renderStructure()}${renderMatrixSurface()}${renderEditor()}${renderPreviewSurface()}</main>`;
  if (state.variant === "B") return `<main class="workspace variant-b">${renderSelectionPanel()}${renderStructure()}${renderEditor()}${renderCompareSurface()}</main>`;
  return `<main class="workspace variant-c">${renderSelectionPanel()}${renderEditor()}${renderStructure()}${renderMatrixSurface()}${renderRecipeSurface()}</main>`;
}

function rawState() {
  const statusCounts = { source: 0, current: 0, changed: 0, cleared: 0, inserted: 0, "pending-delete": 0 };
  const renderedResidues = state.preview?.projectedResidues ?? state.residues;
  renderedResidues.forEach((item) => Object.keys(TRACKS).forEach((key) => { statusCounts[trackState(item, key)] += 1; }));
  (state.preview?.pendingDeleteIds ?? []).forEach(() => { statusCounts["pending-delete"] += Object.keys(TRACKS).length; });
  const locatorFor = (handle) => {
    const item = residueById(handle, renderedResidues) ?? residueById(handle);
    return item ? { chain: item.chain, position: item.positionLabel } : null;
  };
  return {
    throwawayPrototype: true,
    variant: `${state.variant} · ${VARIANTS[state.variant].name}`,
    productQuestion: "应用前能否准确复述残基成员、顺序与每条轨道变化？",
    residueAxis: { length: renderedResidues.length, locators: renderedResidues.map((item) => ({ chain: item.chain, position: item.positionLabel, state: item.residueState })) },
    selection: { mode: state.selectionMode, locators: [...state.selected].map(locatorFor).filter(Boolean), random: state.selectionMode === "random" ? { ...state.random, actual: [...state.random.actual] } : null },
    changeStateCounts: statusCounts,
    annotations: annotationProjection(state.preview?.projectedAnnotations ?? state.annotations).map((item) => ({ label: item.label, start: locatorFor(item.startId), end: locatorFor(item.endId), state: annotationState(item), valid: annotationRange(item, renderedResidues).valid })),
    preview: state.preview ? { kind: state.preview.kind, title: state.preview.title, sentence: state.preview.sentence, impact: state.preview.impact, diagnostics: state.preview.diagnostics.map(({ severity, locator, message }) => ({ severity, locator, message })) } : null,
    undoDepth: state.undoStack.length,
    lastAction: state.lastAction,
  };
}

function renderPrototypeControls() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  return `<div class="prototype-switcher"><button data-variant-cycle="-1" aria-label="上一个方案">←</button><div><small>THROWAWAY PROTOTYPE · ?variant=${state.variant}</small><strong>${VARIANTS[state.variant].label} · ${VARIANTS[state.variant].name}</strong><span>${VARIANTS[state.variant].question}</span></div><button data-variant-cycle="1" aria-label="下一个方案">→</button></div><details class="state-inspector"><summary>原型完整状态 · ${state.lastAction}</summary><pre>${JSON.stringify(rawState(), null, 2)}</pre></details>`;
}

function bindEvents() {
  document.querySelectorAll("[data-tool]").forEach((button) => button.addEventListener("click", () => switchTool(button.dataset.tool)));
  document.querySelectorAll("[data-selection-mode]").forEach((button) => button.addEventListener("click", () => {
    restorePrePreviewSelection();
    state.selectionMode = button.dataset.selectionMode;
    state.preview = null;
    state.random.actual = [];
    state.lastAction = `操作来源切换为${state.selectionMode === "random" ? "后端随机操作" : "明确选择"}`;
    render();
  }));
  document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => selectPreset(button.dataset.preset)));
  document.querySelectorAll("[data-residue]").forEach((button) => button.addEventListener("click", (event) => {
    const handle = button.dataset.residue;
    if (state.preview && residueById(handle, previewResiduesForSelection())) {
      handlePreviewResidueClick(handle, event, button.closest(".structure-nav") ? "结构导航" : "残基矩阵");
      return;
    }
    handleResidueClick(handle, event, button.closest(".structure-nav") ? "结构导航" : "残基矩阵");
  }));
  document.querySelectorAll("[data-random-field]").forEach((field) => field.addEventListener("change", () => {
    restorePrePreviewSelection();
    const key = field.dataset.randomField;
    state.random[key] = ["count", "seed", "start", "end"].includes(key) ? Number(field.value) : field.value;
    state.random.actual = [];
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-condition-intent]").forEach((field) => field.addEventListener("change", () => {
    restorePrePreviewSelection();
    state.conditionActions[field.dataset.conditionIntent].intent = field.value;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-condition-value]").forEach((field) => field.addEventListener("change", () => {
    restorePrePreviewSelection();
    state.conditionActions[field.dataset.conditionValue].value = field.value;
    state.preview = null;
  }));
  document.querySelectorAll("[data-layout-operation]").forEach((button) => button.addEventListener("click", () => {
    restorePrePreviewSelection();
    state.layoutOperation = button.dataset.layoutOperation;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-layout-field]").forEach((field) => field.addEventListener("change", () => {
    restorePrePreviewSelection();
    if (field.dataset.layoutField === "count") state.insertCount = Number(field.value);
    else state.insertSequence = field.value;
    state.preview = null;
  }));
  document.querySelectorAll("[data-annotation-index]").forEach((button) => button.addEventListener("click", () => {
    restorePrePreviewSelection();
    state.activeAnnotationIndex = Number(button.dataset.annotationIndex);
    const active = activeAnnotation();
    if (active) state.functionLabel = active.label;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-function-action]").forEach((button) => button.addEventListener("click", () => {
    restorePrePreviewSelection();
    state.functionAction = button.dataset.functionAction;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-function-field]").forEach((field) => field.addEventListener("change", () => {
    restorePrePreviewSelection();
    if (field.dataset.functionField === "label") state.functionLabel = field.value;
    else state.splitAt = Number(field.value);
    state.preview = null;
  }));
  document.querySelectorAll("[data-check]").forEach((field) => field.addEventListener("change", () => {
    const index = Number(field.dataset.check);
    field.checked ? state.checklist.add(index) : state.checklist.delete(index);
    render();
  }));
  document.querySelectorAll("[data-diagnostic-index]").forEach((button) => button.addEventListener("click", () => {
    const item = state.preview?.diagnostics[Number(button.dataset.diagnosticIndex)];
    if (!item?.handles.length) return;
    state.selected = new Set(item.handles.filter((id) => residueById(id) || residueById(id, state.preview.projectedResidues)));
    state.anchor = [...state.selected].at(-1) ?? null;
    state.lastAction = `定位 diagnostic：${item.locator}`;
    render();
  }));
  document.querySelectorAll("[data-variant-cycle]").forEach((button) => button.addEventListener("click", () => cycleVariant(Number(button.dataset.variantCycle))));
  document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (action === "preview-random") buildPreview(false);
    if (action === "redraw-random") buildPreview(true);
    if (action === "build-preview") buildPreview();
    if (action === "cancel-preview") clearPreview();
    if (action === "apply-preview") applyPreview();
    if (action === "undo") undo();
    if (action === "reset-composer") {
      restorePrePreviewSelection();
      state.preview = null;
      state.conditionActions = {
        sequence: { intent: "specify", value: "G" }, coordinates: { intent: "mask", value: "assigned" }, ss: { intent: "specify", value: "H" }, sasa: { intent: "keep", value: "32" },
      };
      state.layoutOperation = "delete";
      state.functionAction = "add";
      state.lastAction = "当前操作区已重置；ProteinPrompt 未改变";
      render();
    }
    if (action === "save") addToast("原型检查：当前 Prompt 格式可保存；尚未写回 Workflow");
    if (action === "cancel-studio") addToast("原型：会返回 Workflow 且不写回本轮未保存修改", "warn");
  }));
}

function render() {
  document.querySelector("#app").innerHTML = `<div class="app-shell">${renderTopbar()}${renderControlbar()}${renderVariant()}</div>${renderPrototypeControls()}<div class="toasts"></div>`;
  bindEvents();
  renderToasts();
}

document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && (target.matches("input, textarea, select") || target.isContentEditable)) return;
  if (event.key === "ArrowLeft") cycleVariant(-1);
  if (event.key === "ArrowRight") cycleVariant(1);
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undo();
  }
  if (event.key === "Escape" && state.preview) clearPreview();
});

render();
