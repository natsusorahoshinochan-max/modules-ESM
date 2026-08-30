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

function track(source, current = source) {
  return { source, current };
}

function residue({ id, chain = "A", identity, sourceNumber, sequence, coordinates, ss, sasa, layoutState = "source" }) {
  return {
    id,
    chain,
    identity: String(identity),
    sourceNumber,
    layoutState,
    tracks: {
      sequence: track(sequence),
      coordinates: track(coordinates),
      ss: track(ss),
      sasa: track(sasa),
    },
  };
}

function annotation({ id, label, startId, endId, source = true }) {
  return {
    id,
    label,
    startId,
    endId,
    source: source ? { label, startId, endId } : null,
  };
}

function buildInitialPrompt() {
  const sequence = "TTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN";
  const ssPattern = "--EEE-TT--HHHHHHH-TT--EEE--TT---HHHHH--TT---";
  const residues = [...sequence].map((letter, index) => {
    const number = index + 1;
    return residue({
      id: `A:${number}`,
      identity: number,
      sourceNumber: number,
      sequence: letter,
      coordinates: true,
      ss: ssPattern[index] ?? "-",
      sasa: Math.round(8 + 46 * Math.abs(Math.sin(index * 0.73))),
    });
  });

  // Seed the sample with real change states so the legend can be judged before
  // any operation. Values and geometry remain explicitly illustrative.
  residues.find((item) => item.id === "A:11").tracks.sequence.current = "G";
  residues.find((item) => item.id === "A:17").tracks.coordinates.current = null;
  residues.find((item) => item.id === "A:22").tracks.sasa.current = null;
  residues.find((item) => item.id === "A:29").tracks.ss.current = "H";
  const inserted = residue({
    id: "A:new1",
    identity: "new1",
    sourceNumber: null,
    sequence: undefined,
    coordinates: undefined,
    ss: undefined,
    sasa: undefined,
    layoutState: "new",
  });
  Object.values(inserted.tracks).forEach((value) => { value.current = null; });
  residues.splice(18, 0, inserted);

  const annotations = [
    annotation({ id: "fn-1", label: "disulfide-rich region（示意）", startId: "A:3", endId: "A:8" }),
    annotation({ id: "fn-2", label: "binding region（示意）", startId: "A:12", endId: "A:20" }),
    annotation({ id: "fn-3", label: "surface motif（示意）", startId: "A:31", endId: "A:36", source: false }),
  ];
  annotations[1].endId = "A:21";
  return { residues, annotations };
}

const initial = buildInitialPrompt();

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "A",
  residues: initial.residues,
  annotations: initial.annotations,
  selected: new Set(["A:8", "A:9", "A:10", "A:11", "A:12", "A:23", "A:24", "A:25"]),
  anchor: "A:25",
  selectionMode: "explicit",
  random: { count: 6, start: 6, end: 34, seed: 1701, actual: [] },
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
  activeAnnotationId: "fn-2",
  nextResidueNumber: 2,
  nextAnnotationNumber: 4,
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
  };
}

function currentSnapshot(label) {
  return {
    label,
    residues: structuredClone(state.residues),
    annotations: structuredClone(state.annotations),
    selected: [...state.selected],
    anchor: state.anchor,
    nextResidueNumber: state.nextResidueNumber,
    nextAnnotationNumber: state.nextAnnotationNumber,
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
  return `${item.chain}:${item.identity}`;
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
      groups.push(start.id === previous.id ? residueLabel(start) : `${residueLabel(start)}–${previous.identity}`);
      start = item;
    }
    previous = item;
  }
  groups.push(start.id === previous.id ? residueLabel(start) : `${residueLabel(start)}–${previous.identity}`);
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
  if (item.layoutState === "new") return "new";
  const value = item.tracks[key];
  if (equalValue(value.current, value.source)) return "source";
  if (value.current === null && value.source !== null && value.source !== undefined) return "cleared";
  return "modified";
}

function annotationState(item) {
  if (!item.source) return "new";
  return item.label === item.source.label && item.startId === item.source.startId && item.endId === item.source.endId ? "source" : "modified";
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

function clearPreview(reason = "预览已取消；ProteinPrompt 未改变") {
  if (!state.preview) return;
  state.preview = null;
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
  if (kind === "single") return selectIds(["A:16"], "明确选择单残基");
  if (kind === "continuous") {
    const start = residueIndex("A:12");
    const end = residueIndex("A:20");
    return selectIds(state.residues.slice(start, end + 1).map((item) => item.id), "按当前 ResidueLayout 选择连续 A:12–20");
  }
  if (kind === "modified") return selectIds(["A:11", "A:17", "A:22", "A:29", "A:new1"], "选择当前变化位置");
  return selectIds(["A:8", "A:9", "A:10", "A:11", "A:12", "A:23", "A:24", "A:25"], "明确选择不连续区间");
}

function lcg(seed) {
  let value = Math.abs(Number(seed) || 1) >>> 0;
  return () => {
    value = (1664525 * value + 1013904223) >>> 0;
    return value / 4294967296;
  };
}

function chooseRandom(redraw = false) {
  if (redraw) state.random.seed += 1;
  const { start, end, count, seed } = state.random;
  const candidates = state.residues.filter((item) => item.sourceNumber !== null && item.sourceNumber >= start && item.sourceNumber <= end);
  const actualCount = Math.max(1, Math.min(Number(count) || 1, candidates.length));
  const random = lcg(seed);
  const pool = [...candidates];
  for (let index = pool.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(random() * (index + 1));
    [pool[index], pool[swap]] = [pool[swap], pool[index]];
  }
  const ids = pool.slice(0, actualCount).sort((left, right) => residueIndex(left.id) - residueIndex(right.id)).map((item) => item.id);
  state.random.actual = ids;
  selectIds(ids, `随机选择 · count ${actualCount} · range A:${start}–${end} · seed ${seed}`, "random");
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

function normalizedSpecifiedValue(key, raw) {
  if (key === "coordinates") return true;
  if (key === "sasa") return Math.max(0, Number(raw) || 0);
  if (key === "sequence") return String(raw || "G").slice(0, 1).toUpperCase();
  return String(raw || "H").slice(0, 1).toUpperCase();
}

function affectedAnnotationsForIds(ids, annotations = state.annotations, residues = state.residues) {
  const target = new Set(ids);
  return annotations.filter((item) => {
    const start = residueIndex(item.startId, residues);
    const end = residueIndex(item.endId, residues);
    if (start < 0 || end < 0) return target.has(item.startId) || target.has(item.endId);
    return residues.slice(Math.min(start, end), Math.max(start, end) + 1).some((residueItem) => target.has(residueItem.id));
  });
}

function makeConditionsPreview() {
  const selected = selectedResidues();
  if (!selected.length) return { error: "请先选择要编辑的残基" };
  const projected = clonePrompt();
  const selectedIds = new Set(state.selected);
  const rows = [];

  Object.entries(state.conditionActions).forEach(([key, action]) => {
    let changed = 0;
    projected.residues.forEach((item) => {
      if (!selectedIds.has(item.id)) return;
      const value = item.tracks[key];
      const before = value.current;
      if (action.intent === "specify") value.current = normalizedSpecifiedValue(key, action.value);
      if (action.intent === "mask") value.current = null;
      if (!equalValue(before, value.current)) changed += 1;
    });
    let detail = `${selected.length} 个位置明确保留当前值；不会发生隐式变化`;
    if (action.intent === "specify") detail = `${changed} 个位置将写入 ${valueText(key, normalizedSpecifiedValue(key, action.value))}`;
    if (action.intent === "mask") detail = `${changed} 个位置将变为 Mask；residue identities 保留`;
    rows.push({ key, label: TRACKS[key].label, intent: INTENT_LABELS[action.intent], detail, changed, noop: changed === 0 });
  });

  const changedTotal = rows.reduce((sum, row) => sum + row.changed, 0);
  return {
    kind: "conditions",
    title: `一次应用 ${selected.length} 个残基上的多轨道条件编辑`,
    subtitle: `ResidueLayout 不变；${changedTotal} 个逐轨道值会改变。保留、指定与 Mask 被逐轨道列出。`,
    sentence: `${formatSelection()}：${rows.map((row) => `${row.label} ${row.intent}`).join("；")}。ResidueLayout 不变。`,
    rows,
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: [...state.selected],
    danger: false,
    impact: [`layout ${state.residues.length} → ${state.residues.length}`, `${changedTotal} track values change`],
  };
}

function makeLayoutPreview() {
  const selected = selectedResidues();
  if (!selected.length) return { error: "请先选择新增位置或待删除残基" };
  const projected = clonePrompt();
  if (state.layoutOperation === "add") {
    const insertionIndex = residueIndex(selected.at(-1).id, projected.residues);
    const count = Math.max(1, Math.min(12, Number(state.insertCount) || 1));
    const inserted = Array.from({ length: count }, () => {
      const id = `A:new${state.nextResidueNumber + insertedCount}`;
      insertedCount += 1;
      const item = residue({ id, identity: id.split(":")[1], sourceNumber: null, sequence: undefined, coordinates: undefined, ss: undefined, sasa: undefined, layoutState: "new" });
      Object.values(item.tracks).forEach((value) => { value.current = null; });
      if (state.insertSequence === "assigned") item.tracks.sequence.current = "G";
      return item;
    });
    projected.residues.splice(insertionIndex + 1, 0, ...inserted);
    return {
      kind: "add",
      title: `在 ${residueLabel(selected.at(-1))} 后新增 ${count} 个 residue identities`,
      subtitle: `ResidueLayout ${state.residues.length} → ${projected.residues.length}；Sequence 初始为 ${state.insertSequence === "assigned" ? "G（示意）" : "Mask"}，其他轨道均为 Mask。`,
      sentence: `在 ${residueLabel(selected.at(-1))} 后新增 ${count} 个残基；布局长度增加 ${count}；新增位置的 Sequence ${state.insertSequence === "assigned" ? "指定为 G（示意）" : "为 Mask"}；Coordinates、SS8、SASA 均为 Mask；现有 function intervals 保留当前端点身份。`,
      rows: [
        { label: "ResidueLayout", intent: "新增", detail: `${state.residues.length} → ${projected.residues.length}；新身份 ${inserted.map(residueLabel).join(", ")}`, changed: count },
        { label: "Sequence", intent: state.insertSequence === "assigned" ? "指定" : "Mask", detail: `${count} 个新增位置`, changed: count },
        { label: "Coordinates / SS8 / SASA", intent: "Mask", detail: `${count} 个新增位置全部未指定`, changed: count * 3 },
        { label: "Function intervals", intent: "保留", detail: "现有区间继续绑定原端点 residue identities", changed: 0, noop: true },
      ],
      projectedResidues: projected.residues,
      projectedAnnotations: projected.annotations,
      projectedSelection: inserted.map((item) => item.id),
      nextResidueNumber: state.nextResidueNumber + count,
      danger: false,
      impact: [`layout ${state.residues.length} → ${projected.residues.length}`, `${count} new residues`, `${count * 4} new masked/assigned track slots`],
    };
  }

  const ids = new Set(state.selected);
  const affected = affectedAnnotationsForIds(ids);
  const lost = Object.keys(TRACKS).map((key) => ({ key, count: selected.filter((item) => item.tracks[key].current !== null && item.tracks[key].current !== undefined).length }));
  projected.residues = projected.residues.filter((item) => !ids.has(item.id));
  const invalidEndpoints = projected.annotations.filter((item) => !residueById(item.startId, projected.residues) || !residueById(item.endId, projected.residues));
  return {
    kind: "delete",
    title: `删除 ${selected.length} 个 residue identities`,
    subtitle: `ResidueLayout ${state.residues.length} → ${projected.residues.length}；各轨道对应值一并移除。Function intervals 不会被自动修复。`,
    sentence: `删除 ${formatSelection()}；布局长度减少 ${selected.length}；Sequence、Coordinates、SS8、SASA 对应值全部移除；${affected.length} 条 function intervals 受影响，其中 ${invalidEndpoints.length} 条端点失效且会阻止保存，必须另行编辑。`,
    rows: [
      { label: "ResidueLayout", intent: "删除", detail: `${state.residues.length} → ${projected.residues.length}；选中身份不再存在`, changed: selected.length },
      ...lost.map((item) => ({ label: TRACKS[item.key].label, intent: "随布局移除", detail: `丢失 ${item.count} 个已指定值；不是 Mask`, changed: item.count })),
      { label: "Function intervals", intent: "受影响", detail: affected.length ? `${affected.map((item) => item.label).join("；")}；不自动修复` : "没有区间覆盖这些 residue identities", changed: affected.length },
    ],
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: [],
    pendingDeleteIds: [...state.selected],
    danger: true,
    impact: [`layout ${state.residues.length} → ${projected.residues.length}`, ...lost.map((item) => `${TRACKS[item.key].short} −${item.count}`), `FUNC affected ${affected.length}`, `invalid endpoints ${invalidEndpoints.length}`],
  };
}

let insertedCount = 0;

function selectionAsContinuousRange() {
  const items = selectedResidues();
  if (!items.length || selectionRuns() !== 1) return null;
  return { startId: items[0].id, endId: items.at(-1).id };
}

function activeAnnotation(annotations = state.annotations) {
  return annotations.find((item) => item.id === state.activeAnnotationId);
}

function makeFunctionPreview() {
  const projected = clonePrompt();
  const active = activeAnnotation(projected.annotations);
  const range = selectionAsContinuousRange();
  const rows = [];
  let title = "";
  let sentence = "";
  let pendingAnnotationIds = [];

  if (["add", "modify"].includes(state.functionAction) && !range) return { error: "添加或修改 interval 需要一个连续残基区间；当前不连续选择不会被悄悄拉成一个区间" };
  if (["modify", "split", "delete"].includes(state.functionAction) && !active) return { error: "请选择要修改的 function annotation interval" };

  if (state.functionAction === "add") {
    const created = annotation({ id: `fn-${state.nextAnnotationNumber}`, label: state.functionLabel || "label（示意）", ...range, source: false });
    projected.annotations.push(created);
    title = `添加 1 条 function annotation interval`;
    sentence = `在 ${formatSelection()} 添加 “${created.label}”；其他 function intervals 与逐残基轨道保留当前值。`;
    rows.push({ label: "Function intervals", intent: "新增", detail: `${created.label} · ${created.startId}–${created.endId}`, changed: 1 });
  }

  if (state.functionAction === "modify") {
    const before = `${active.label} · ${active.startId}–${active.endId}`;
    active.label = state.functionLabel || active.label;
    active.startId = range.startId;
    active.endId = range.endId;
    title = `修改 function annotation ${active.id}`;
    sentence = `把 ${before} 修改为 ${active.label} · ${active.startId}–${active.endId}；逐残基轨道保留当前值。`;
    rows.push({ label: "Function intervals", intent: "修改", detail: `${before} → ${active.label} · ${active.startId}–${active.endId}`, changed: 1 });
  }

  if (state.functionAction === "split") {
    const start = residueIndex(active.startId, projected.residues);
    const end = residueIndex(active.endId, projected.residues);
    const splitId = `A:${state.splitAt}`;
    const splitIndex = residueIndex(splitId, projected.residues);
    if (start < 0 || end < 0 || splitIndex <= start || splitIndex > end) return { error: `拆分点 A:${state.splitAt} 必须位于所选 interval 内部且不是首个残基` };
    const originalEnd = active.endId;
    active.endId = projected.residues[splitIndex - 1].id;
    const created = annotation({ id: `fn-${state.nextAnnotationNumber}`, label: active.label, startId: splitId, endId: originalEnd, source: false });
    projected.annotations.push(created);
    title = `把 ${active.id} 拆分为 2 条 intervals`;
    sentence = `在 ${splitId} 前拆分 “${active.label}”：${active.startId}–${active.endId} 与 ${created.startId}–${created.endId}；不创建逐残基 null mask。`;
    rows.push({ label: "Function intervals", intent: "拆分", detail: `${active.startId}–${originalEnd} → ${active.startId}–${active.endId} + ${created.startId}–${created.endId}`, changed: 2 });
  }

  if (state.functionAction === "delete") {
    projected.annotations = projected.annotations.filter((item) => item.id !== active.id);
    pendingAnnotationIds = [active.id];
    title = `删除 function annotation ${active.id}`;
    sentence = `删除 “${active.label}” ${active.startId}–${active.endId}；ResidueLayout 与四条逐残基轨道保留当前值。`;
    rows.push({ label: "Function intervals", intent: "待删除", detail: `${active.label} · ${active.startId}–${active.endId}`, changed: 1 });
  }

  rows.push({ label: "ResidueLayout", intent: "保留", detail: `${state.residues.length} residues；身份与顺序不变`, changed: 0, noop: true });
  rows.push({ label: "SEQ / XYZ / SS8 / SASA", intent: "保留", detail: "所有逐残基值不变", changed: 0, noop: true });
  return {
    kind: `function-${state.functionAction}`,
    title,
    subtitle: "Function annotations 使用 interval 操作；不是可逐残基 Mask 的 scalar track。",
    sentence,
    rows,
    projectedResidues: projected.residues,
    projectedAnnotations: projected.annotations,
    projectedSelection: [...state.selected],
    pendingAnnotationIds,
    nextAnnotationNumber: ["add", "split"].includes(state.functionAction) ? state.nextAnnotationNumber + 1 : state.nextAnnotationNumber,
    danger: state.functionAction === "delete",
    impact: [`layout unchanged ${state.residues.length}`, `function intervals ${state.annotations.length} → ${projected.annotations.length}`, "per-residue tracks unchanged"],
  };
}

function buildPreview() {
  insertedCount = 0;
  const result = state.tool === "conditions" ? makeConditionsPreview() : state.tool === "layout" ? makeLayoutPreview() : makeFunctionPreview();
  if (result.error) {
    addToast(result.error, "warn");
    renderToasts();
    return;
  }
  state.preview = result;
  state.checklist = new Set();
  state.lastAction = `已建立未应用预览：${result.title}`;
  addToast("预览已建立；ProteinPrompt 尚未改变");
  render();
}

function applyPreview() {
  if (!state.preview) return;
  if (state.variant === "C" && state.checklist.size < checklistItems().length) {
    addToast("请先逐项核对操作配方", "warn");
    renderToasts();
    return;
  }
  const preview = state.preview;
  state.undoStack.push(currentSnapshot(preview.title));
  state.residues = structuredClone(preview.projectedResidues);
  state.annotations = structuredClone(preview.projectedAnnotations);
  state.selected = new Set(preview.projectedSelection.filter((id) => residueById(id, state.residues)));
  state.anchor = [...state.selected].at(-1) ?? null;
  if (preview.nextResidueNumber) state.nextResidueNumber = preview.nextResidueNumber;
  if (preview.nextAnnotationNumber) state.nextAnnotationNumber = preview.nextAnnotationNumber;
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
  state.selected = new Set(previous.selected);
  state.anchor = previous.anchor;
  state.nextResidueNumber = previous.nextResidueNumber;
  state.nextAnnotationNumber = previous.nextAnnotationNumber;
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
  state.tool = tool;
  state.preview = null;
  state.checklist = new Set();
  state.lastAction = `切换操作区：${tool === "layout" ? "布局" : tool === "conditions" ? "条件" : "Function intervals"}；所有轨道仍可见`;
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
      <button data-tool="layout" class="${state.tool === "layout" ? "active" : ""}">布局</button>
      <button data-tool="conditions" class="${state.tool === "conditions" ? "active" : ""}">条件</button>
      <button data-tool="function" class="${state.tool === "function" ? "active" : ""}">Function intervals</button>
      <button data-tool="structure">结构 ↗ 原型 5</button>
    </div></div>
    <div class="selection-tabs"><span>选择来源</span><div class="segmented"><button data-selection-mode="explicit" class="${state.selectionMode === "explicit" ? "active" : ""}">明确选择</button><button data-selection-mode="random" class="${state.selectionMode === "random" ? "active" : ""}">可复现随机选择</button></div></div>
    <div class="prompt-stats"><span>A · ${state.residues.length} residues</span>${Object.keys(TRACKS).map((key) => `<span>${TRACKS[key].short} ${countAssigned(key)}/${state.residues.length}</span>`).join("")}<span>FUNC ${state.annotations.length}</span></div>
  </section>`;
}

function renderSelectionPanel() {
  const randomActual = state.selectionMode === "random" && state.random.actual.length ? state.random.actual.join(", ") : "尚未抽取";
  return `<section class="surface selection-panel">
    <div class="surface-header"><div><span class="surface-kicker">Selection contract</span><h2>${state.selectionMode === "random" ? "可复现随机选择" : "明确选择"}</h2></div><span class="surface-note">${state.selected.size} selected</span></div>
    <div class="selection-readout"><span>实际 residue identities</span><strong>${formatSelection()}</strong><small>${state.selectionMode === "random" ? `count ${state.random.count} · range A:${state.random.start}–${state.random.end} · seed ${state.random.seed}` : "矩阵和结构导航同步；Cmd/Ctrl 追加，Shift 连选"}</small></div>
    <div class="selection-body">
      ${state.selectionMode === "explicit" ? `<div class="preset-grid"><button data-preset="single">单残基 A:16</button><button data-preset="continuous">连续 A:12–20</button><button data-preset="disjoint">不连续 8–12 + 23–25</button><button data-preset="modified">全部变化位置</button></div><div class="semantic-note">选择只确定操作对象；尚未决定 Specify、Mask、Keep、Restore、Insert 或 Delete。</div>` : `<div class="form-grid">
        <label class="field"><span>数量</span><input data-random-field="count" type="number" min="1" max="30" value="${state.random.count}"></label>
        <label class="field"><span>随机种子</span><input data-random-field="seed" type="number" value="${state.random.seed}"></label>
        <label class="field"><span>允许范围起点</span><input data-random-field="start" type="number" min="1" max="46" value="${state.random.start}"></label>
        <label class="field"><span>允许范围终点</span><input data-random-field="end" type="number" min="1" max="46" value="${state.random.end}"></label>
        <button class="button" data-action="draw-random">按种子抽取</button><button class="button" data-action="redraw-random">种子 +1 重新抽取</button>
      </div><div class="random-facts"><span><b>实际位置</b><br>${randomActual}</span><span><b>Prompt 状态</b><br>抽取不修改 Prompt</span></div>`}
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
    <div class="surface-header"><div><span class="surface-kicker">Synchronized navigator</span><h2>结构导航 · 实际选择位置</h2></div><span class="surface-note">几何示意；选择同步真实</span></div>
    <div class="structure-stage"><svg viewBox="0 0 210 124" preserveAspectRatio="none"><polyline class="backbone" points="${path}"/>${points.map((point) => `<g class="structure-point ${state.selected.has(point.item.id) ? "selected" : ""} ${pending.has(point.item.id) ? "pending" : ""} ${!point.item.tracks.coordinates.current ? "masked-coordinate" : ""}" data-residue="${point.item.id}" transform="translate(${point.x} ${point.y})"><circle r="${state.selected.has(point.item.id) ? 6 : 3.7}"/><text y="-8">${state.selected.has(point.item.id) ? point.item.identity : ""}</text></g>`).join("")}</svg></div>
    <div class="structure-caption"><b>${formatSelection()}</b> · 空心点只显示来源参考位置：当前 Coordinates 已 Mask，不再是结构 conditioning。</div>
  </section>`;
}

function renderTrackCells(key, residues, compareResidues = null, pendingIds = new Set()) {
  return residues.map((item) => {
    const compare = compareResidues ? residueById(item.id, compareResidues) : null;
    const before = item.tracks[key].current;
    const after = compare ? compare.tracks[key].current : before;
    const changed = compare && !equalValue(before, after);
    const status = compare ? trackState(compare, key) : trackState(item, key);
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

function renderFunctionCells(residues, annotations, pendingAnnotationIds = new Set()) {
  return residues.map((item, index) => {
    const matches = annotationsAtResidue(item, annotations, residues);
    if (!matches.length) return `<button class="track-cell masked ${state.selected.has(item.id) ? "selected" : ""}" data-residue="${item.id}"><span class="value">—</span><span class="cell-state">none</span></button>`;
    const priority = (annotationItem) => pendingAnnotationIds.has(annotationItem.id) ? 4 : annotationState(annotationItem) === "new" ? 3 : annotationState(annotationItem) === "modified" ? 2 : 1;
    const active = [...matches].sort((left, right) => priority(right) - priority(left))[0];
    const range = annotationRange(active, residues);
    const first = index === range.start;
    const status = annotationState(active);
    const pending = pendingAnnotationIds.has(active.id);
    const overlap = matches.length > 1 ? ` +${matches.length - 1}` : "";
    return `<button class="track-cell function-ribbon ${status} ${pending ? "pending" : ""} ${state.selected.has(item.id) ? "selected" : ""}" data-residue="${item.id}" title="${matches.map((annotationItem) => `${annotationItem.label} · ${annotationItem.startId}–${annotationItem.endId} · ${annotationState(annotationItem)}`).join(" | ")}"><span class="value">${first ? `${active.label}${overlap}` : `━${overlap}`}</span><span class="cell-state">${first ? status : ""}</span></button>`;
  }).join("");
}

function renderMatrix({ residues = state.residues, annotations = state.annotations, compareResidues = null, pendingIds = new Set(), pendingAnnotationIds = new Set(), compact = false } = {}) {
  return `<div class="matrix-scroll"><div class="matrix ${compact ? "compact" : ""}" style="--residue-count:${residues.length}">
    <div class="track-label"><strong>ResidueLayout</strong><small>identity-complete axis</small></div>${residues.map((item) => `<button class="axis-cell ${state.selected.has(item.id) ? "selected" : ""} ${pendingIds.has(item.id) ? "pending-delete" : ""} ${item.layoutState === "new" ? "preview-new" : ""}" data-residue="${item.id}"><small>${item.chain}</small><strong>${item.identity}</strong></button>`).join("")}
    ${Object.entries(TRACKS).map(([key, meta]) => `<div class="track-label"><strong>${meta.label}</strong><small>${meta.unit}</small></div>${renderTrackCells(key, residues, compareResidues, pendingIds)}`).join("")}
    <div class="track-label"><strong>Function annotations</strong><small>interval ribbons</small></div>${renderFunctionCells(residues, annotations, pendingAnnotationIds)}
  </div></div>`;
}

function matrixProjectionProps() {
  if (!state.preview) return { residues: state.residues, annotations: state.annotations };
  if (state.preview.kind === "add") return { residues: state.preview.projectedResidues, annotations: state.preview.projectedAnnotations };
  if (state.preview.kind === "delete") return { residues: state.residues, annotations: state.annotations, pendingIds: new Set(state.preview.pendingDeleteIds) };
  if (state.preview.kind.startsWith("function")) {
    if (state.preview.kind === "function-delete") return { residues: state.residues, annotations: state.annotations, pendingAnnotationIds: new Set(state.preview.pendingAnnotationIds) };
    return { residues: state.residues, annotations: state.preview.projectedAnnotations };
  }
  return { residues: state.residues, annotations: state.annotations, compareResidues: state.preview.projectedResidues };
}

function renderMatrixSurface() {
  return `<section class="surface matrix-surface"><div class="surface-header"><div><span class="surface-kicker">Adopted from prototype 2</span><h2>残基账本 · 共享 ResidueLayout</h2></div><span class="surface-note">${state.preview ? "未应用预览已叠加" : "当前 ProteinPrompt"}</span></div>${renderMatrix(matrixProjectionProps())}${renderLegend()}</section>`;
}

function renderLegend() {
  return `<div class="matrix-legend"><span><i class="legend-dot"></i>来源原始</span><span><i class="legend-dot modified"></i>已修改</span><span><i class="legend-dot cleared"></i>已清除</span><span><i class="legend-dot new"></i>新增</span><span><i class="legend-dot pending"></i>待删除</span><b class="legend-note">状态同时使用文字与形状，不只依赖颜色</b></div>`;
}

function renderConditionsEditor() {
  return `<div class="mode-explainer">同一次应用可以组合多个轨道。每条轨道只接受 <b>保留、指定、Mask</b>：保留是明确 no-op，Mask 只清除所选轨道，不删除残基。</div><div class="track-actions">${Object.entries(TRACKS).map(([key, meta]) => {
    const action = state.conditionActions[key];
    return `<div class="track-action"><label><b>${meta.label}</b><small>${meta.unit}</small></label><div class="track-action-controls"><select data-condition-intent="${key}">${Object.entries(INTENT_LABELS).map(([value, label]) => `<option value="${value}" ${action.intent === value ? "selected" : ""}>${label}</option>`).join("")}</select><input data-condition-value="${key}" value="${action.value}" ${action.intent === "specify" ? "" : "disabled"} aria-label="${meta.label} 指定值"></div></div>`;
  }).join("")}</div><div class="semantic-note">Coordinates 的 Mask 会清除结构 conditioning；它不是三维 viewer 的临时 hide/show。SASA 单位固定为 Å²。</div>`;
}

function renderLayoutEditor() {
  return `<div class="mode-explainer"><b>新增 / 删除</b>改变 ResidueLayout；这与把已有残基上的某条轨道设为 Mask 是不同类别的科学操作。</div><div class="layout-actions"><button class="operation-card ${state.layoutOperation === "add" ? "active" : ""}" data-layout-operation="add"><h3>新增残基</h3><p>新 residue identities；新增位置选择指定或 Mask</p></button><button class="operation-card ${state.layoutOperation === "delete" ? "active" : ""}" data-layout-operation="delete"><h3>删除残基</h3><p>身份与全部轨道对应值一起移除</p></button></div>${state.layoutOperation === "add" ? `<div class="form-grid" style="margin-top:8px"><label class="field"><span>新增数量</span><input data-layout-field="count" type="number" min="1" max="12" value="${state.insertCount}"></label><label class="field"><span>新增 Sequence 状态</span><select data-layout-field="sequence"><option value="mask" ${state.insertSequence === "mask" ? "selected" : ""}>Mask / 未指定</option><option value="assigned" ${state.insertSequence === "assigned" ? "selected" : ""}>指定为 G（示意）</option></select></label></div><div class="semantic-note">新增位置必须明确选择指定或 Mask。Coordinates、SS8 和 SASA 在本次示例中为 Mask。原型身份使用 A:newN，不裁决正式重编号。</div>` : `<div class="semantic-note">删除预览会逐轨道列出丢失值，并标出受影响的 function intervals。受影响区间不会被自动修复。</div>`}`;
}

function renderFunctionEditor() {
  return `<div class="mode-explainer">Function annotations 是有标签的 residue intervals；只提供添加、修改、拆分和删除，不提供逐残基 Mask。</div><div class="annotation-list">${state.annotations.map((item) => {
    const range = annotationRange(item);
    return `<button data-annotation="${item.id}" class="${state.activeAnnotationId === item.id ? "active" : ""}"><span>${item.label}</span><small>${range.valid ? `${item.startId}–${item.endId}` : "端点失效"} · ${annotationState(item)}</small></button>`;
  }).join("")}</div><div class="function-actions">${["add", "modify", "split", "delete"].map((value) => `<button data-function-action="${value}" class="${state.functionAction === value ? "active" : ""}">${{ add: "添加", modify: "修改", split: "拆分", delete: "删除" }[value]}</button>`).join("")}</div><div class="form-grid">
    <label class="field full"><span>Function label（示意；正式词表未裁决）</span><input data-function-field="label" value="${state.functionLabel}"></label>
    ${state.functionAction === "split" ? `<label class="field full"><span>第二个 interval 起点</span><input data-function-field="split" type="number" min="2" max="46" value="${state.splitAt}"></label>` : ""}
  </div><div class="semantic-note">添加 / 修改从当前连续选择读取端点。不连续选择不会被悄悄转换成一个连续 interval。</div>`;
}

function renderEditor() {
  return `<section class="surface editor-surface"><div class="surface-header"><div><span class="surface-kicker">Joint operation composer</span><h2>${state.tool === "conditions" ? "多轨道条件编辑" : state.tool === "layout" ? "残基布局编辑" : "Function intervals"}</h2></div><span class="surface-note">${state.selected.size} residues</span></div><div class="selection-readout" style="margin:8px 8px 0"><span>操作对象</span><strong>${formatSelection()}</strong></div><div class="editor-body">${state.tool === "conditions" ? renderConditionsEditor() : state.tool === "layout" ? renderLayoutEditor() : renderFunctionEditor()}</div><div class="editor-footer"><button class="button ghost" data-action="reset-composer">重置本区</button><button class="button primary" data-action="build-preview">生成未应用预览</button></div></section>`;
}

function renderPreviewContent(recipe = false) {
  if (!state.preview) return `<div class="preview-empty"><div><b>尚无待确认变更</b><p>先在操作区组成 Layout、逐轨道条件或 Function interval 变更，再生成预览。预览期间 ProteinPrompt 本体不会变化。</p></div></div>`;
  if (recipe) return renderRecipe();
  return `<div class="preview-body"><div class="preview-headline"><span>未应用 · 可以取消</span><strong>${state.preview.title}</strong><p>${state.preview.subtitle}</p></div><div class="ledger">${state.preview.rows.map((row) => `<div class="ledger-row ${row.noop ? "noop" : ""}"><b>${row.label}</b><span class="intent">${row.intent}</span><p>${row.detail}</p></div>`).join("")}</div><div class="impact-tags">${state.preview.impact.map((item) => `<span>${item}</span>`).join("")}</div></div>`;
}

function renderPreviewActions() {
  if (!state.preview) return "";
  const blocked = state.variant === "C" && state.checklist.size < checklistItems().length;
  return `<div class="preview-actions"><button class="button ghost" data-action="cancel-preview">取消预览</button><button class="button apply ${state.preview.danger ? "danger" : ""}" data-action="apply-preview" ${blocked ? "disabled" : ""}>${state.preview.danger ? "确认并应用高影响变更" : "确认并一次应用"}</button></div>`;
}

function renderPreviewSurface() {
  return `<section class="surface preview-surface"><div class="surface-header"><div><span class="surface-kicker">Variant A · transaction language</span><h2>变更账本</h2></div><span class="surface-note">${state.preview ? "Prompt 尚未改变" : "等待预览"}</span></div>${renderPreviewContent()}${renderPreviewActions()}</section>`;
}

function renderCompareSurface() {
  const afterResidues = state.preview?.projectedResidues ?? state.residues;
  const afterAnnotations = state.preview?.projectedAnnotations ?? state.annotations;
  const pendingAnnotationIds = new Set(state.preview?.pendingAnnotationIds ?? []);
  return `<section class="surface compare-surface"><div class="surface-header"><div><span class="surface-kicker">Variant B · same-axis comparison</span><h2>${state.preview ? state.preview.title : "当前态 / 拟应用态"}</h2></div><span class="surface-note">${state.preview ? "右侧仍是未应用提案" : "尚无提案"}</span></div><div class="before-after"><section><div class="compare-title"><b>当前 ProteinPrompt</b><span>${state.residues.length} residues</span></div>${renderMatrix({ residues: state.residues, annotations: state.annotations, pendingIds: new Set(state.preview?.pendingDeleteIds ?? []), pendingAnnotationIds })}</section><section><div class="compare-title"><b>拟应用后</b><span>${afterResidues.length} residues</span></div>${renderMatrix({ residues: afterResidues, annotations: afterAnnotations })}</section></div>${renderPreviewActions()}</section>`;
}

function checklistItems() {
  if (!state.preview) return [];
  const items = [
    `我已核对操作对象：${formatSelection()}`,
    state.preview.kind === "add" || state.preview.kind === "delete" ? `我已核对 ResidueLayout：${state.residues.length} → ${state.preview.projectedResidues.length}` : `我确认 ResidueLayout 保留 ${state.residues.length} residues`,
    "我已逐条核对 Sequence、Coordinates、SS8、SASA 和 Function intervals 的保留、指定、Mask、新增或删除",
  ];
  if (state.selectionMode === "random") items.unshift(`我已核对随机实际位置、count ${state.random.count}、range A:${state.random.start}–${state.random.end} 与 seed ${state.random.seed}`);
  return items;
}

function renderRecipe() {
  const steps = state.preview.rows.map((row, index) => `<div class="recipe-step"><span>${index + 1}</span><div><b>${row.label} · ${row.intent}</b><p>${row.detail}</p></div></div>`).join("");
  return `<div class="preview-body"><div class="recipe-list">${steps}</div><div class="recite"><b>请复述：</b><br>${state.preview.sentence}</div><div class="checklist">${checklistItems().map((item, index) => `<label><input type="checkbox" data-check="${index}" ${state.checklist.has(index) ? "checked" : ""}><span>${item}</span></label>`).join("")}</div></div>`;
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
  const statusCounts = { source: 0, modified: 0, cleared: 0, new: 0 };
  state.residues.forEach((item) => Object.keys(TRACKS).forEach((key) => { statusCounts[trackState(item, key)] += 1; }));
  return {
    throwawayPrototype: true,
    variant: `${state.variant} · ${VARIANTS[state.variant].name}`,
    productQuestion: "应用前能否准确复述布局与每条轨道变化？",
    residueLayout: { chain: "A", length: state.residues.length, ids: state.residues.map((item) => item.id) },
    selection: { mode: state.selectionMode, ids: [...state.selected], random: state.selectionMode === "random" ? state.random : null },
    changeStateCounts: statusCounts,
    annotations: state.annotations.map((item) => ({ id: item.id, label: item.label, startId: item.startId, endId: item.endId, state: annotationState(item), valid: annotationRange(item).valid })),
    preview: state.preview ? { kind: state.preview.kind, title: state.preview.title, sentence: state.preview.sentence, impact: state.preview.impact } : null,
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
    state.selectionMode = button.dataset.selectionMode;
    state.preview = null;
    state.lastAction = `选择来源切换为${state.selectionMode === "random" ? "可复现随机选择" : "明确选择"}`;
    render();
  }));
  document.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => selectPreset(button.dataset.preset)));
  document.querySelectorAll("[data-residue]").forEach((button) => button.addEventListener("click", (event) => handleResidueClick(button.dataset.residue, event, button.closest(".structure-nav") ? "结构导航" : "残基矩阵")));
  document.querySelectorAll("[data-random-field]").forEach((field) => field.addEventListener("change", () => {
    state.random[field.dataset.randomField] = Number(field.value);
  }));
  document.querySelectorAll("[data-condition-intent]").forEach((field) => field.addEventListener("change", () => {
    state.conditionActions[field.dataset.conditionIntent].intent = field.value;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-condition-value]").forEach((field) => field.addEventListener("change", () => {
    state.conditionActions[field.dataset.conditionValue].value = field.value;
    state.preview = null;
  }));
  document.querySelectorAll("[data-layout-operation]").forEach((button) => button.addEventListener("click", () => {
    state.layoutOperation = button.dataset.layoutOperation;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-layout-field]").forEach((field) => field.addEventListener("change", () => {
    if (field.dataset.layoutField === "count") state.insertCount = Number(field.value);
    else state.insertSequence = field.value;
    state.preview = null;
  }));
  document.querySelectorAll("[data-annotation]").forEach((button) => button.addEventListener("click", () => {
    state.activeAnnotationId = button.dataset.annotation;
    const active = activeAnnotation();
    if (active) state.functionLabel = active.label;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-function-action]").forEach((button) => button.addEventListener("click", () => {
    state.functionAction = button.dataset.functionAction;
    state.preview = null;
    render();
  }));
  document.querySelectorAll("[data-function-field]").forEach((field) => field.addEventListener("change", () => {
    if (field.dataset.functionField === "label") state.functionLabel = field.value;
    else state.splitAt = Number(field.value);
    state.preview = null;
  }));
  document.querySelectorAll("[data-check]").forEach((field) => field.addEventListener("change", () => {
    const index = Number(field.dataset.check);
    field.checked ? state.checklist.add(index) : state.checklist.delete(index);
    render();
  }));
  document.querySelectorAll("[data-variant-cycle]").forEach((button) => button.addEventListener("click", () => cycleVariant(Number(button.dataset.variantCycle))));
  document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.action;
    if (action === "draw-random") chooseRandom(false);
    if (action === "redraw-random") chooseRandom(true);
    if (action === "build-preview") buildPreview();
    if (action === "cancel-preview") clearPreview();
    if (action === "apply-preview") applyPreview();
    if (action === "undo") undo();
    if (action === "reset-composer") {
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
