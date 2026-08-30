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

const SHOW_PROTOTYPE_CONTROLS = ["127.0.0.1", "localhost"].includes(location.hostname);
const variantFromUrl = new URLSearchParams(location.search).get("variant")?.toUpperCase();

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "B",
  entry: "pdb",
  mode: "condition",
  residues: [],
  annotations: [],
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
  nextInsertedResidue: 1,
  undoStack: [],
  draftPreview: null,
  dirty: false,
  lastAction: "从结构开始：已建立 1CRN 示例 Prompt",
  toast: [],
};

function residue({ chain, number = null, identity = number, sourceNumber = number, sequence = null, coordinates = false, ss = null, sasa = null, change = "source" }) {
  return {
    id: `${chain}:${identity}`,
    chain,
    number,
    identity: String(identity),
    sourceNumber,
    sequence,
    coordinates,
    ss,
    sasa,
    change,
  };
}

function buildPrompt(entry) {
  if (entry === "blank") {
    return {
      residues: [
        ...Array.from({ length: 36 }, (_, index) => residue({ chain: "A", number: index + 1, change: "new" })),
        ...Array.from({ length: 18 }, (_, index) => residue({ chain: "B", number: index + 1, change: "new" })),
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
        { id: "fn-1", chain: "A", start: 3, end: 8, label: "function label（示意）" },
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
        sequence: position % 11 === 0 ? null : letter,
        coordinates: hasCoordinates,
        ss: position >= 14 && position <= 31 ? (position % 6 < 4 ? "H" : "-") : null,
        sasa: position % 4 === 0 ? Math.round(18 + 55 * Math.abs(Math.sin(position))) : null,
        change: position === 22 ? "cleared" : position >= 35 && position <= 37 ? "modified" : "source",
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
        change: index < 2 ? "new" : "source",
      }),
    ),
  ];
  return {
    residues,
    annotations: [
      { id: "fn-1", chain: "A", start: 15, end: 21, label: "binding region（示意）" },
      { id: "fn-2", chain: "A", start: 31, end: 38, label: "motif（示意）" },
      { id: "fn-3", chain: "B", start: 5, end: 14, label: "interaction region（示意）" },
    ],
  };
}

function initializeEntry(entry, announce = false) {
  const prompt = buildPrompt(entry);
  state.entry = entry;
  state.mode = ENTRIES[entry].defaultMode;
  state.residues = prompt.residues;
  state.annotations = prompt.annotations;
  state.selected = new Set();
  state.anchor = null;
  state.viewerHidden = new Set();
  state.activeTrack = "sequence";
  state.hiddenTracks = new Set();
  state.sequenceAction = "指定";
  state.sequenceValue = "G";
  state.insertInitial = "mask";
  state.insertCount = 1;
  state.nextInsertedResidue = 1;
  state.undoStack = [];
  state.draftPreview = null;
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

function residueIdentity(item) {
  return `${item.chain}:${item.identity}`;
}

function selectedResidues(ids = state.selected) {
  return state.residues.filter((item) => ids.has(item.id));
}

function cloneResidues(items) {
  return items.map((item) => ({ ...item }));
}

function cloneAnnotations(items) {
  return items.map((item) => ({ ...item }));
}

function pushUndo(label) {
  state.undoStack.push({
    label,
    residues: cloneResidues(state.residues),
    annotations: cloneAnnotations(state.annotations),
    selected: [...state.selected],
    anchor: state.anchor,
    viewerHidden: [...state.viewerHidden],
    nextInsertedResidue: state.nextInsertedResidue,
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
  state.selected = new Set(previous.selected);
  state.anchor = previous.anchor;
  state.viewerHidden = new Set(previous.viewerHidden);
  state.nextInsertedResidue = previous.nextInsertedResidue;
  state.draftPreview = null;
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
      groups.push(start.id === previous.id ? residueIdentity(start) : `${residueIdentity(start)}–${previous.identity}`);
      start = item;
    }
    previous = item;
  }
  groups.push(start.id === previous.id ? residueIdentity(start) : `${residueIdentity(start)}–${previous.identity}`);
  return `${groups.join(" + ")} · ${ordered.length} residues`;
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
    items.some((item) => item.chain === annotation.chain && item.sourceNumber !== null && item.sourceNumber >= annotation.start && item.sourceNumber <= annotation.end),
  );
  return {
    sequence: items.filter((item) => item.sequence !== null).length,
    coordinates: items.filter((item) => item.coordinates).length,
    ss: items.filter((item) => item.ss !== null).length,
    sasa: items.filter((item) => item.sasa !== null).length,
    functionIntervals: affectedAnnotations.map((item) => item.label),
    viewerHidden: [...state.viewerHidden].filter((id) => ids.has(id)).length,
  };
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
      afterIdentity: residueIdentity(after),
      chain: after.chain,
      count,
      initialSequence: state.insertInitial,
      sequenceValue: state.insertInitial === "assigned" ? state.sequenceValue : null,
      beforeLength: state.residues.length,
      afterLength: state.residues.length + count,
    };
    state.lastAction = `预览插入：在 ${residueIdentity(after)} 后新增 ${count} 个残基`;
    render();
    return;
  }
  if (kind === "delete") {
    if (items.length === state.residues.length) {
      addToast("此原型不演示删除全部残基；请保留至少一个 residue identity", "warn");
      renderToasts();
      return;
    }
    state.draftPreview = {
      kind,
      track: "sequence",
      ids: items.map((item) => item.id),
      selection: formatSelection(),
      beforeLength: state.residues.length,
      afterLength: state.residues.length - items.length,
      impact: deletionImpact(items),
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
    if (insertionIndex < 0) {
      addToast("插入位置已变化，请重新建立预览", "warn");
      state.draftPreview = null;
      render();
      return;
    }
    pushUndo(`插入 ${preview.count} 个残基`);
    const inserted = Array.from({ length: preview.count }, () => {
      const identity = `new${state.nextInsertedResidue}`;
      state.nextInsertedResidue += 1;
      return residue({
        chain: preview.chain,
        identity,
        sourceNumber: null,
        sequence: preview.initialSequence === "assigned" ? preview.sequenceValue : null,
        change: "new",
      });
    });
    state.residues.splice(insertionIndex + 1, 0, ...inserted);
    state.selected = new Set(inserted.map((item) => item.id));
    state.anchor = inserted.at(-1)?.id ?? null;
    state.draftPreview = null;
    state.dirty = true;
    state.lastAction = `已插入 ${inserted.length} 个残基：${formatSelection()}`;
    addToast(`${state.lastAction}；其他轨道均为 Mask`);
    render();
    return;
  }

  const targetIds = new Set(preview.ids.filter((id) => residueById(id)));
  if (targetIds.size === 0) {
    addToast("预览中的残基已不存在，请重新选择", "warn");
    state.draftPreview = null;
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
    state.residues = state.residues.filter((item) => !targetIds.has(item.id));
    targetIds.forEach((id) => state.viewerHidden.delete(id));
    state.annotations = state.annotations.filter((annotation) =>
      state.residues.some((item) => item.chain === annotation.chain && item.sourceNumber !== null && item.sourceNumber >= annotation.start && item.sourceNumber <= annotation.end),
    );
    const neighbor = state.residues[Math.min(firstDeletedIndex, state.residues.length - 1)];
    state.selected = new Set(neighbor ? [neighbor.id] : []);
    state.anchor = neighbor?.id ?? null;
    state.draftPreview = null;
    state.dirty = true;
    state.lastAction = `已删除 ${targetIds.size} 个 residue identities；各轨道已按共享轴同步`;
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
      change: item.change === "new" ? "new" : preview.kind === "specify" ? "modified" : "cleared",
    };
  });
  state.draftPreview = null;
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

function toggleTrack(track) {
  if (state.hiddenTracks.has(track)) state.hiddenTracks.delete(track);
  else state.hiddenTracks.add(track);
  state.lastAction = `${state.hiddenTracks.has(track) ? "暂时隐藏" : "显示"}${TRACKS[track].label} 行`;
  render();
}

function savePrompt() {
  state.dirty = false;
  state.draftPreview = null;
  state.lastAction = "保存 ProteinPrompt（原型内存状态）";
  addToast("ProteinPrompt 已保存到原型内存；未写入 Workflow 后端");
  render();
}

function renderTopbar() {
  return `
    <header class="topbar">
      <div class="brand"><span class="brand-mark">PW</span><div><strong>Prompt Studio</strong><small>PROTOTYPE 2 · THROWAWAY</small></div></div>
      <div class="prompt-heading">
        <span class="crumb">Workflow / 编写 ProteinPrompt</span>
        <strong>${ENTRIES[state.entry].label}</strong>
        <span class="legal-badge">${hasCoordinates() ? "含坐标" : "无坐标 · 合法 Prompt"}</span>
      </div>
      <div class="top-actions">
        <button class="button ghost" data-action="cancel">取消</button>
        <button class="button ghost" data-action="undo" ${state.undoStack.length ? "" : "disabled"}>撤销${state.undoStack.length ? ` (${state.undoStack.length})` : ""}</button>
        <button class="button" data-action="summary">整份 Prompt 摘要</button>
        <button class="button primary" data-action="save">保存 ProteinPrompt</button>
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
          ${points.map(({ item, x, y }) => `<g class="structure-residue ${state.selected.has(item.id) ? "selected" : ""}" data-residue="${item.id}" tabindex="0"><circle cx="${x}" cy="${y}" r="${state.selected.has(item.id) ? 9 : 6}"/><text x="${x}" y="${y - 12}">${state.selected.has(item.id) ? item.id : ""}</text></g>`).join("")}
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

function annotationAt(item) {
  if (item.sourceNumber === null) return null;
  return state.annotations.find((annotation) => annotation.chain === item.chain && item.sourceNumber >= annotation.start && item.sourceNumber <= annotation.end);
}

function isPendingDelete(id) {
  return state.draftPreview?.kind === "delete" && state.draftPreview.ids.includes(id);
}

function visibleResidues(focus = false) {
  if (!focus || state.selected.size === 0) return state.residues;
  const indices = [...state.selected].map(indexById).filter((index) => index >= 0);
  const start = Math.max(0, Math.min(...indices) - 5);
  const end = Math.min(state.residues.length, Math.max(...indices) + 6);
  return state.residues.slice(start, end);
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

function renderMatrix({ focus = false, compact = false } = {}) {
  const residues = visibleResidues(focus);
  const gridStyle = `--residue-count:${residues.length}`;
  const tracks = Object.keys(TRACKS).filter((track) => !state.hiddenTracks.has(track));
  return `
    <section class="surface matrix-surface ${focus ? "focus-matrix" : ""} ${compact ? "compact" : ""}" data-surface="matrix">
      <header class="surface-header matrix-header">
        <div><span class="surface-kicker">${focus ? "所选区域与邻近残基" : "下方 · 共享残基轴"}</span><h2>${focus ? "Selection lens" : "ProteinPrompt 残基矩阵"}</h2></div>
        <div class="matrix-meta"><span>一列 = 一个残基身份</span><strong>${chainSummary()} · ${state.residues.length} total</strong></div>
      </header>
      ${!hasCoordinates() ? `<div class="coordinate-notice"><b>三维区已自动收起</b><span>此 Prompt 没有坐标；不是缺少必填模板。共享残基矩阵已获得更多空间。</span></div>` : ""}
      <div class="track-controls">
        <span>轨道行：</span>
        ${Object.entries(TRACKS).map(([key, track]) => `<button class="${state.hiddenTracks.has(key) ? "off" : "on"}" data-toggle-track="${key}">${track.short}</button>`).join("")}
        <span class="track-rule">默认同时显示；手动隐藏不改变内容</span>
      </div>
      <div class="matrix-scroll">
        <div class="residue-grid axis-row" style="${gridStyle}">
          <div class="track-label sticky"><strong>Residue axis</strong><small>chain : identity</small></div>
          ${residues.map((item, index) => `<button class="axis-cell change-${item.change} ${state.selected.has(item.id) ? "selected" : ""} ${isPendingDelete(item.id) ? "pending-delete" : ""} ${index > 0 && residues[index - 1].chain !== item.chain ? "chain-start" : ""}" data-residue="${item.id}" title="${residueIdentity(item)}"><small>${item.chain}</small><strong>${item.identity}</strong></button>`).join("")}
        </div>
        ${tracks.map((track) => {
          if (track === "function") {
            return `<div class="residue-grid track-row ${state.activeTrack === track ? "active-track" : ""}" style="${gridStyle}">
              <button class="track-label sticky" data-track="${track}"><strong>${TRACKS[track].label}</strong><small>interval ribbons · 示意 label</small></button>
              ${residues.map((item, index) => {
                const annotation = annotationAt(item);
                const begins = annotation && item.sourceNumber === annotation.start;
                return `<button class="track-cell function-cell ${annotation ? "assigned ribbon" : "unassigned"} ${begins ? "ribbon-start" : ""} ${state.selected.has(item.id) ? "selected" : ""} ${isPendingDelete(item.id) ? "pending-delete" : ""} ${index > 0 && residues[index - 1].chain !== item.chain ? "chain-start" : ""}" data-residue="${item.id}" data-track="function" title="${annotation?.label ?? "未指定 function interval"}">${begins ? annotation.label : annotation ? "↔" : "·"}</button>`;
              }).join("")}
            </div>`;
          }
          return `<div class="residue-grid track-row ${track === "sequence" ? "sequence-row" : ""} ${state.activeTrack === track ? "active-track" : ""}" style="${gridStyle}">
            ${renderTrackLabel(track)}
            ${residues.map((item, index) => `<button class="track-cell ${isAssigned(item, track) ? "assigned" : "unassigned masked"} change-${item.change} ${state.selected.has(item.id) ? "selected" : ""} ${isPendingDelete(item.id) ? "pending-delete" : ""} ${index > 0 && residues[index - 1].chain !== item.chain ? "chain-start" : ""}" data-residue="${item.id}" data-track="${track}" title="${residueIdentity(item)} · ${TRACKS[track].label} · ${isAssigned(item, track) ? "已指定" : "Mask"}">${cellValue(item, track)}</button>`).join("")}
          </div>`;
        }).join("")}
      </div>
      <footer class="matrix-legend">
        <span><i class="legend-mark source"></i>来源原值</span><span><i class="legend-mark modified"></i>用户修改</span><span><i class="legend-mark cleared"></i>已清除</span><span><i class="legend-mark added"></i>新增残基</span><span><i class="legend-mark pending"></i>待删除</span><span class="matrix-selection-readout">矩阵选择：<b>${formatSelection()}</b></span>
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
        <strong>在选择中的最后一个位置后插入 residue identity</strong>
        <p>${selection}</p>
        <label class="field"><span>插入数量</span><input type="number" min="1" max="12" value="${state.insertCount}" data-sequence-field="insert-count" /></label>
        <span class="section-label inset">新 residue 的 Sequence 初始状态</span>
        <div class="insert-initial-options">
          <button class="${state.insertInitial === "assigned" ? "active" : ""}" data-insert-initial="assigned">指定氨基酸</button>
          <button class="${state.insertInitial === "mask" ? "active" : ""}" data-insert-initial="mask">Mask</button>
        </div>
        ${state.insertInitial === "assigned" ? `<label class="field"><span>氨基酸（示意）</span><select data-sequence-field="insert-value">${["G", "A", "S", "V"].map((value) => `<option ${state.sequenceValue === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>` : `<div class="mask-explanation">新 residue 保留 identity；Sequence 值为 Mask。</div>`}
        <button class="button wide" data-sequence-preview="insert">预览插入</button>
      </div>
    `;
  }
  if (action === "删除") {
    return `
      <div class="tool-section operation-detail danger-detail">
        <span class="section-label">Sequence · 直接删除</span>
        <strong>删除所选 residue identity</strong>
        <p>${selection}</p>
        <div class="mask-explanation">删除改变 ResidueLayout，并同步移除所有轨道值；它不是 Sequence Mask。</div>
        <button class="button wide danger" data-sequence-preview="delete">预览删除及受影响轨道</button>
      </div>
    `;
  }
  if (action === "Mask") {
    return `
      <div class="tool-section operation-detail">
        <span class="section-label">Sequence · 直接 Mask</span>
        <strong>保留 residue identity，清除 Sequence 值</strong>
        <p>${selection}</p>
        <button class="button wide" data-sequence-preview="mask">预览 Sequence Mask</button>
      </div>
    `;
  }
  return `
    <div class="tool-section operation-detail">
      <span class="section-label">Sequence · 直接指定</span>
      <strong>为现有 residue identity 指定氨基酸</strong>
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
        <strong>Function 使用 residue interval，不使用逐残基 Mask</strong>
        <p>${formatSelection()}</p>
        <div class="track-direct-actions"><button data-preview-intent="添加 Function interval">添加区间</button><button data-preview-intent="修改或拆分 Function interval">修改 / 拆分</button></div>
        <button class="button wide danger" data-preview-intent="删除 Function interval">删除所选区间</button>
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
    <div class="tool-section"><span class="section-label">布局操作</span><div class="intent-grid"><button class="intent active" data-layout-intent="插入残基">＋ 插入残基</button><button class="intent danger" data-layout-intent="删除残基">− 删除残基</button><button class="intent" data-layout-intent="编辑链">编辑链</button></div><p class="panel-note">布局操作改变 residue identity 轴；不会被表达为某条轨道的 Mask。详细预览属于原型 3。</p></div>
    <div class="tool-section"><span class="section-label">当前 residue layout</span><div class="layout-summary"><b>${chainSummary()}</b><span>${state.residues.length} residues · ${new Set(state.residues.map((item) => item.chain)).size} chains</span></div></div>
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
        <strong>${preview.afterIdentity} 后新增 ${preview.count} 个 residue identities</strong>
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
        <span>未应用 · 删除预览</span>
        <strong>待删除 ${preview.ids.length} 个 residue identities</strong>
        <p>${preview.selection}</p>
        <div class="preview-axis-change"><b>${preview.beforeLength} residues</b><i>→</i><b>${preview.afterLength} residues</b></div>
        <div class="impact-counts"><span>SEQ ${impact.sequence}</span><span>XYZ ${impact.coordinates}</span><span>SS8 ${impact.ss}</span><span>SASA ${impact.sasa}</span></div>
        <p>受影响 Function：${impact.functionIntervals.length ? impact.functionIntervals.join("、") : "无"}${impact.viewerHidden ? `；另移除 ${impact.viewerHidden} 个临时 viewer hidden 状态` : ""}</p>
        <div class="preview-actions"><button data-action="clear-preview">取消</button><button class="apply danger" data-action="apply-sequence-preview">确认删除</button></div>
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
      <footer class="editor-footer"><span>当前编辑对象</span><strong>${state.mode === "structure" ? "structure coordinates" : state.activeTrack === "sequence" ? `Sequence · ${state.sequenceAction}` : state.mode === "layout" ? "ResidueLayout" : TRACKS[state.activeTrack].label}</strong></footer>
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
    selectedResidues: state.residues.filter((item) => state.selected.has(item.id)).map((item) => item.id),
    prompt: {
      chains: chainSummary(),
      length: state.residues.length,
      residueAxis: state.residues.map((item) => ({
        identity: residueIdentity(item),
        sequence: item.sequence,
        coordinates: item.coordinates ? "assigned" : "Mask",
        ss: item.ss,
        sasa: item.sasa,
        change: item.change,
      })),
      assigned: Object.fromEntries(Object.keys(TRACKS).map((track) => [track, countAssigned(track)])),
      hiddenTrackRows: [...state.hiddenTracks],
      functionIntervals: state.annotations,
      hasCoordinates: hasCoordinates(),
      formatIssues: [],
      compatibility: compatibilitySummary(),
    },
    viewerState: {
      hiddenResidues: [...state.viewerHidden],
      persistedInProteinPrompt: false,
    },
    draftPreview: state.draftPreview,
    undoDepth: state.undoStack.length,
    dirty: state.dirty,
    lastAction: state.lastAction,
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
    else if (action === "undo") undoPromptEdit();
    else if (action === "clear-preview") {
      state.draftPreview = null;
      state.lastAction = "清除未应用预览";
      render();
    } else if (action === "save") savePrompt();
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
