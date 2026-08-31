// THROWAWAY UI PROTOTYPE — not production code.
// Three variants of one import / correspondence / merge workspace, switchable
// via ?variant=. Variant B remains the adopted evidence-split direction.

const VARIANTS = {
  A: { label: "A · 对应账本", question: "把完整 correspondence 与逐轨道决策放在同一账本里，是否容易核对？" },
  B: { label: "B · 证据分屏（已采用）", question: "证据、精确 correspondence 与 merge dossier 分屏，是否最容易定位问题？", adopted: true },
  C: { label: "C · 关卡式确认", question: "用 Open → correspondence → track decisions → Preview / Apply 关卡，是否能减少误应用？" },
};

const SHOW_PROTOTYPE_CONTROLS = location.protocol === "file:" || ["127.0.0.1", "localhost"].includes(location.hostname);
const variantFromUrl = new URLSearchParams(location.search).get("variant")?.toUpperCase();
const TARGET_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKI";
const MISSING_SOURCE_POSITIONS = new Set([9, 20]);

function opaqueHandle(scope, index) {
  return `${scope}_${(((index + 11) * 2654435761) >>> 0).toString(36)}`;
}

function makeTargetResidues() {
  return [...TARGET_SEQUENCE].map((letter, index) => ({
    handle: opaqueHandle("t", index),
    chain: "A",
    position: index + 1,
    letter,
    hasStructure: [5, 6, 7, 17].includes(index + 1),
  }));
}

function makeSourceResidues() {
  return [...TARGET_SEQUENCE]
    .map((letter, index) => ({ chain: "A", position: index + 1, letter }))
    .filter((item) => !MISSING_SOURCE_POSITIONS.has(item.position))
    .map((item, observedIndex) => ({
      ...item,
      handle: opaqueHandle("s", observedIndex),
      observedIndex,
      letter: item.position === 17 ? "I" : item.letter,
    }));
}

const target = makeTargetResidues();
const source = makeSourceResidues();

function locatorDraftSuggestion() {
  return Object.fromEntries(source.map((sourceItem) => [
    sourceItem.handle,
    target.find((targetItem) => targetItem.chain === sourceItem.chain && targetItem.position === sourceItem.position)?.handle ?? null,
  ]));
}

const TRACKS = [
  { key: "sequence", label: "Sequence", sourceAvailable: true, sourceDetail: "28 observed residues", currentDetail: "30 residues" },
  { key: "structure", label: "Structure", sourceAvailable: true, sourceDetail: "28 residue coordinate sets", currentDetail: "4 local coordinate sets" },
  { key: "secondary_structure", label: "Secondary structure", sourceAvailable: false, sourceDetail: "not provided", currentDetail: "current values present" },
  { key: "sasa", label: "SASA", sourceAvailable: false, sourceDetail: "not provided", currentDetail: "current values present" },
  { key: "function_annotations", label: "Function annotations", sourceAvailable: true, sourceDetail: "1 exact annotation tuple", currentDetail: "2 exact annotation tuples" },
];

const CURRENT_ANNOTATIONS = [
  { key: "current_tuple_motif", label: "motif", startPosition: 5, endPosition: 7, provenance: "manual evidence" },
  { key: "current_tuple_active", label: "active_site", startPosition: 17, endPosition: 17, provenance: "curated evidence" },
];

const SOURCE_ANNOTATION = {
  key: "source_tuple_binding",
  label: "binding_site",
  startPosition: 5,
  endPosition: 7,
  provenance: "annotation sidecar · imported evidence",
};

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "B",
  correspondence: locatorDraftSuggestion(),
  suggestionProvenance: "prototype stub · chain + residue locator pairing",
  selectedSourceHandle: source.find((item) => item.position === 10).handle,
  tableFilter: "diagnostics",
  correspondenceReviewed: false,
  correspondenceNote: "",
  decisions: {
    sequence: "conflict",
    structure: "conflict",
    secondary_structure: "preserve",
    sasa: "adopt",
    function_annotations: "adopt",
  },
  previewGenerated: false,
  applied: false,
  step: 2,
  lastAction: "Open 完成；已生成 chain + residue locator temporary suggestion，尚未确认",
  toasts: [],
};

function sourceByHandle(handle) {
  return source.find((item) => item.handle === handle);
}

function targetByHandle(handle) {
  return target.find((item) => item.handle === handle);
}

function sourceByPosition(position) {
  return source.find((item) => item.position === position);
}

function mappedTarget(item) {
  return targetByHandle(state.correspondence[item.handle]);
}

function locator(item, side) {
  return `${side} · chain ${item.chain} · residue ${item.position}`;
}

function shortLocator(item) {
  return `${item.chain}·${item.position}`;
}

function residueSetLocator(items, side) {
  const positions = items.map((item) => item.position);
  const consecutive = positions.every((position, index) => index === 0 || position === positions[index - 1] + 1);
  const positionLabel = positions.length === 1
    ? `residue ${positions[0]}`
    : consecutive
      ? `residues ${positions[0]}–${positions.at(-1)}`
      : `residues ${positions.join(", ")}`;
  return `${side} · chain A · ${positionLabel}`;
}

function exactAnnotationTuple(label, startItem, endItem, side) {
  return `(${label}, ${locator(startItem, side)}, ${locator(endItem, side)})`;
}

function currentAnnotationView(annotation) {
  const startItem = target.find((item) => item.position === annotation.startPosition);
  const endItem = target.find((item) => item.position === annotation.endPosition);
  return {
    ...annotation,
    locator: annotation.startPosition === annotation.endPosition
      ? locator(startItem, "target")
      : `${locator(startItem, "target")} → ${locator(endItem, "target")}`,
    tuple: exactAnnotationTuple(annotation.label, startItem, endItem, "target"),
  };
}

function annotationProjection() {
  const sourceItems = source.filter((item) => item.position >= SOURCE_ANNOTATION.startPosition && item.position <= SOURCE_ANNOTATION.endPosition);
  const mappedItems = sourceItems.map(mappedTarget);
  const targetItems = mappedItems.filter(Boolean);
  const sourceGaps = sourceItems.filter((item, index) => !mappedItems[index]);
  const sameChain = targetItems.length === sourceItems.length && targetItems.every((item) => item.chain === targetItems[0].chain);
  const orderedAndContinuous = sameChain && targetItems.every((item, index) => index === 0 || (
    item.chain === targetItems[index - 1].chain && item.position === targetItems[index - 1].position + 1
  ));
  const sourceLocator = residueSetLocator(sourceItems, "source");
  const targetLocator = targetItems.length ? residueSetLocator(targetItems, "target") : "target · no matched residues";
  return {
    sourceLocator,
    targetLocator,
    sourceGaps,
    sameChain,
    orderedAndContinuous,
    valid: sourceGaps.length === 0 && sameChain && orderedAndContinuous,
    locator: `${targetLocator} ← ${sourceLocator}`,
    tuple: targetItems.length
      ? exactAnnotationTuple(SOURCE_ANNOTATION.label, targetItems[0], targetItems.at(-1), "target")
      : `(${SOURCE_ANNOTATION.label}, unresolved target start, unresolved target end)`,
    sourceTuple: exactAnnotationTuple(SOURCE_ANNOTATION.label, sourceItems[0], sourceItems.at(-1), "source"),
    provenance: SOURCE_ANNOTATION.provenance,
  };
}

function correspondenceRows() {
  const usedTargetHandles = new Set(Object.values(state.correspondence).filter(Boolean));
  const sourceRows = source.map((sourceItem) => {
    const targetItem = mappedTarget(sourceItem);
    return targetItem
      ? { kind: "match", source: sourceItem, target: targetItem }
      : { kind: "source_gap", source: sourceItem, target: null };
  });
  const targetGapRows = target
    .filter((targetItem) => !usedTargetHandles.has(targetItem.handle))
    .map((targetItem) => ({ kind: "target_gap", source: null, target: targetItem }));
  return [...sourceRows, ...targetGapRows];
}

function rowStatus(row) {
  if (row.kind === "source_gap") return { cls: "source-gap", label: "source_gap · source explicitly unpaired" };
  if (row.kind === "target_gap") return { cls: "target-gap", label: "target_gap · target explicitly has no source" };
  if (row.source.position === row.target.position && row.source.letter === row.target.letter) return { cls: "exact", label: "match · locator + sequence agree" };
  if (row.source.letter === row.target.letter) return { cls: "sequence", label: "match · sequence agrees; locators differ" };
  return { cls: "mismatch", label: "match · sequence conflict" };
}

function correspondenceFacts() {
  const rows = correspondenceRows();
  const matches = rows.filter((row) => row.kind === "match");
  const sourceGaps = rows.filter((row) => row.kind === "source_gap");
  const targetGaps = rows.filter((row) => row.kind === "target_gap");
  const locatorMatches = matches.filter((row) => row.source.position === row.target.position);
  return {
    rows,
    matches,
    sourceGaps,
    targetGaps,
    locatorMatches,
    sourceDispositionCount: matches.length + sourceGaps.length,
    targetDispositionCount: matches.length + targetGaps.length,
  };
}

function invalidateAfterCorrespondenceChange(message) {
  state.correspondenceReviewed = false;
  state.correspondenceNote = "";
  state.previewGenerated = false;
  state.applied = false;
  if (state.step > 2) state.step = 2;
  state.lastAction = message;
}

function invalidatePreview(message) {
  state.previewGenerated = false;
  state.applied = false;
  if (state.step > 3) state.step = 3;
  state.lastAction = message;
}

function addToast(text, tone = "") {
  const id = `${Date.now()}-${Math.random()}`;
  state.toasts.push({ id, text, tone });
  setTimeout(() => {
    state.toasts = state.toasts.filter((item) => item.id !== id);
    renderToasts();
  }, 2800);
}

function renderToasts() {
  const root = document.querySelector(".toasts");
  if (!root) return;
  root.innerHTML = state.toasts.map((item) => `<div class="toast ${item.tone}">${item.text}</div>`).join("");
}

function resetSuggestion() {
  state.correspondence = locatorDraftSuggestion();
  state.suggestionProvenance = "prototype stub · chain + residue locator pairing";
  state.selectedSourceHandle = sourceByPosition(10).handle;
  invalidateAfterCorrespondenceChange("已重建 chain + residue locator temporary suggestion；来源仍为 prototype stub，尚未确认");
  addToast("临时建议已重置；不是科学对应", "warn");
  render();
}

function applyLocatorSuggestion() {
  state.correspondence = locatorDraftSuggestion();
  state.suggestionProvenance = "prototype stub · chain + residue locator pairing";
  invalidateAfterCorrespondenceChange("已按可见 chain + residue locator 生成修订建议；建议来源已标明，仍未确认");
  addToast("locator-based suggestion 已生成；仍需逐行核对", "warn");
  render();
}

function assignSourceToTarget(sourceHandle, targetHandle) {
  if (targetHandle) {
    const displaced = source.find((item) => item.handle !== sourceHandle && state.correspondence[item.handle] === targetHandle);
    if (displaced) state.correspondence[displaced.handle] = null;
  }
  state.correspondence[sourceHandle] = targetHandle || null;
  state.suggestionProvenance = "manual correspondence edit";
  state.selectedSourceHandle = sourceHandle;
  const sourceItem = sourceByHandle(sourceHandle);
  const targetItem = targetByHandle(targetHandle);
  invalidateAfterCorrespondenceChange(
    targetItem
      ? `已指定 ${locator(sourceItem, "source")} ↔ ${locator(targetItem, "target")}；旧确认失效`
      : `已把 ${locator(sourceItem, "source")} 明确设为 source_gap；旧确认失效`,
  );
  addToast("correspondence 已修改；每个 source / target 仍各处置一次", "warn");
  render();
}

function insertTargetGapBefore(sourceHandle) {
  const sourceItem = sourceByHandle(sourceHandle);
  const currentTarget = mappedTarget(sourceItem);
  const startIndex = target.findIndex((item) => item.handle === currentTarget.handle);
  const occupants = new Map(source
    .filter((item) => state.correspondence[item.handle])
    .map((item) => [state.correspondence[item.handle], item]));
  const nextGapIndex = target.findIndex((item, index) => index > startIndex && !occupants.has(item.handle));
  if (nextGapIndex < 0) {
    state.correspondence[sourceHandle] = null;
  } else {
    for (let index = nextGapIndex; index > startIndex; index -= 1) {
      const displaced = occupants.get(target[index - 1].handle);
      if (displaced) state.correspondence[displaced.handle] = target[index].handle;
    }
  }
  state.suggestionProvenance = "manual correspondence edit";
  state.selectedSourceHandle = sourceHandle;
  invalidateAfterCorrespondenceChange(`已在 ${locator(sourceItem, "source")} 前声明 target_gap；后续临时 matches 右移 1`);
  addToast("target_gap 已显式加入；correspondence 待重新核对", "warn");
  render();
}

function reviewCorrespondence() {
  const facts = correspondenceFacts();
  state.correspondenceReviewed = true;
  state.correspondenceNote = `已核对 ${facts.matches.length} match、${facts.sourceGaps.length} source_gap、${facts.targetGaps.length} target_gap；source ${facts.sourceDispositionCount}/${source.length}、target ${facts.targetDispositionCount}/${target.length} 各处置一次`;
  state.previewGenerated = false;
  state.applied = false;
  state.step = Math.max(state.step, 3);
  state.lastAction = state.correspondenceNote;
  addToast("correspondence 已确认；尚未生成 Preview", "success");
  render();
}

function trackByKey(key) {
  return TRACKS.find((track) => track.key === key);
}

function trackConflicts(trackKey) {
  if (trackKey === "sequence") {
    return source
      .filter((sourceItem) => mappedTarget(sourceItem) && mappedTarget(sourceItem).letter !== sourceItem.letter)
      .map((sourceItem) => {
        const targetItem = mappedTarget(sourceItem);
        return {
          key: sourceItem.handle,
          locator: `${locator(targetItem, "target")} ↔ ${locator(sourceItem, "source")}`,
          current: `Sequence ${targetItem.letter}`,
          imported: `Sequence ${sourceItem.letter}`,
        };
      });
  }
  if (trackKey === "structure") {
    return source
      .filter((sourceItem) => mappedTarget(sourceItem)?.hasStructure)
      .map((sourceItem) => ({
        key: sourceItem.handle,
        locator: `${locator(mappedTarget(sourceItem), "target")} ↔ ${locator(sourceItem, "source")}`,
        current: "current local coordinates",
        imported: "imported coordinates",
      }));
  }
  if (trackKey === "function_annotations") {
    const projection = annotationProjection();
    const inserted = {
      key: SOURCE_ANNOTATION.key,
      locator: projection.locator,
      current: `exclude exact source tuple ${projection.sourceTuple}; provenance: ${projection.provenance}`,
      imported: !projection.valid
        ? `cannot insert exact tuple ${projection.sourceTuple}: target projection is not same-chain, continuous, and order-preserving; provenance: ${projection.provenance}`
        : `insert exact projected tuple ${projection.tuple}; provenance: ${projection.provenance}`,
    };
    const pendingDeletes = CURRENT_ANNOTATIONS.map(currentAnnotationView).map((annotation) => ({
      key: annotation.key,
      locator: annotation.locator,
      current: `preserve exact tuple ${annotation.tuple}; provenance: ${annotation.provenance}`,
      imported: `pending-delete exact tuple ${annotation.tuple}; provenance: ${annotation.provenance}`,
    }));
    return [inserted, ...pendingDeletes];
  }
  return [];
}

function setDecision(trackKey, decision) {
  state.decisions[trackKey] = decision;
  invalidatePreview(`${trackByKey(trackKey).label}: ${decision}`);
  render();
}

function previewDiagnostics() {
  const facts = correspondenceFacts();
  const diagnostics = [];

  if (!state.correspondenceReviewed) {
    diagnostics.push({
      severity: "error",
      category: "correspondence_unconfirmed",
      track: "Correspondence",
      locator: "source · chain A ↔ target · chain A",
      message: "Preview may inspect this temporary suggestion, but Apply requires explicit correspondence confirmation.",
    });
  }

  TRACKS.forEach((track) => {
    const decision = state.decisions[track.key];
    if (decision === "adopt" && !track.sourceAvailable) {
      diagnostics.push({
        severity: "error",
        category: "missing adopted track",
        track: track.label,
        locator: `source bundle · chain A · track ${track.label}`,
        message: `${track.label} was selected for adopt, but the opened source does not provide it.`,
      });
    }
    if (decision === "conflict") {
      const conflicts = trackConflicts(track.key);
      (conflicts.length ? conflicts : [{
        locator: `source bundle · chain A · track ${track.label}`,
        current: "preserve current track",
        imported: "adopt source track",
      }]).forEach((item) => {
        diagnostics.push({
          severity: "error",
          category: "track conflict · decision unresolved",
          track: track.label,
          locator: item.locator,
          message: `Conflict evidence — ${item.current} / ${item.imported}. Resolve the whole track to adopt or preserve before Apply.`,
        });
      });
    }
  });

  if (state.decisions.function_annotations === "adopt") {
    const projection = annotationProjection();
    diagnostics.push(!projection.valid ? {
      severity: "error",
      category: "annotation loss",
      track: "Function annotations",
      locator: projection.locator,
      message: `Cannot insert exact tuple ${projection.sourceTuple}: its full interval does not project to one same-chain, continuous, order-preserving target interval. Provenance: ${projection.provenance}.`,
    } : {
      severity: "info",
      category: "annotation inserted",
      track: "Function annotations",
      locator: projection.locator,
      message: `Insert exact projected tuple ${projection.tuple}. Provenance: ${projection.provenance}.`,
    });
    CURRENT_ANNOTATIONS.map(currentAnnotationView).forEach((annotation) => diagnostics.push({
      severity: "warning",
      category: "annotation loss · pending-delete",
      track: "Function annotations",
      locator: annotation.locator,
      message: `Pending-delete exact current tuple ${annotation.tuple}. Provenance: ${annotation.provenance}.`,
    }));
  }

  facts.sourceGaps.forEach((row) => diagnostics.push({
    severity: "warning",
    category: "source_gap",
    track: "Correspondence",
    locator: locator(row.source, "source"),
    message: "This source residue is explicitly not paired to a target residue.",
  }));
  facts.targetGaps.forEach((row) => diagnostics.push({
    severity: "warning",
    category: "target_gap",
    track: "Correspondence",
    locator: locator(row.target, "target"),
    message: "This target residue has no matched source residue; existing target track values are preserved, and the source contributes no value at this locator.",
  }));
  return diagnostics;
}

function generatePreview() {
  state.previewGenerated = true;
  state.applied = false;
  state.step = 4;
  const blockers = previewDiagnostics().filter((item) => item.severity === "error").length;
  state.lastAction = `Preview 已生成；${blockers} blocking diagnostics；ProteinPrompt 尚未改变`;
  addToast(blockers ? `Preview 已生成：${blockers} 个 blocking diagnostics` : "Preview 已生成，可 Apply", blockers ? "warn" : "success");
  render();
}

function applyMerge() {
  const blockers = previewDiagnostics().filter((item) => item.severity === "error");
  if (!state.previewGenerated || blockers.length) {
    addToast(`不能 Apply：${blockers.length || "尚未生成"} blocking diagnostics`, "danger");
    return;
  }
  state.applied = true;
  state.lastAction = "Apply 完成；结果仅存在原型内存中";
  addToast("Apply 完成（原型内存状态）", "success");
  render();
}

function renderTopbar() {
  const diagnostics = state.previewGenerated ? previewDiagnostics() : [];
  const blockers = diagnostics.filter((item) => item.severity === "error").length;
  const banner = state.applied
    ? { cls: "confirmed", eyebrow: "APPLY COMPLETE · PROTOTYPE MEMORY ONLY", title: "完整 correspondence 与逐轨道决策已应用", text: "刷新即重置；这不是正式保存。" }
    : state.previewGenerated
      ? { cls: blockers ? "draft" : "reviewed", eyebrow: "PREVIEW · NOT APPLIED", title: `${diagnostics.length} diagnostics · ${blockers} blocking`, text: blockers ? "按 locator 解决 blocking diagnostics 后才能 Apply。" : "Preview 无 blocking diagnostics；Apply 前仍可返回修改。" }
      : state.correspondenceReviewed
        ? { cls: "reviewed", eyebrow: "CORRESPONDENCE REVIEWED · PREVIEW NOT GENERATED", title: state.correspondenceNote, text: "逐 track 选择 adopt / preserve / conflict，然后生成 Preview。" }
        : { cls: "draft", eyebrow: "TEMPORARY SUGGESTION · UNCONFIRMED", title: `Proposal source: ${state.suggestionProvenance}`, text: "它不是已确认的科学对应。可先 Preview 查看 correspondence_unconfirmed 与其它 diagnostics；Apply 必须等待确认。" };
  return `
    <header class="topbar">
      <div class="brand"><span class="brand-mark">PW</span><div><strong>Protein Workbench</strong><small>Prompt Studio · prototype 4</small></div></div>
      <div class="prompt-title"><span class="prototype-badge">THROWAWAY</span><strong>Import bundle · chain A correspondence</strong><span>internal opaque handles stay hidden</span></div>
      <div class="top-actions"><button class="button ghost" data-action="reset">Reset suggestion</button><button class="button" data-action="preview">Generate Preview</button><button class="button primary" data-action="apply" ${state.previewGenerated && !blockers && !state.applied ? "" : "disabled"}>Apply merge</button></div>
    </header>
    <section class="draft-banner ${banner.cls}"><div><span>${banner.eyebrow}</span><strong>${banner.title}</strong></div><p>${banner.text}</p></section>
  `;
}

function renderImportFacts(compact = false) {
  return `
    <section class="surface import-facts ${compact ? "compact" : ""}">
      <div class="surface-header"><div><span class="surface-kicker">Open result</span><h2>来源事实与建议 provenance</h2></div><span class="surface-note">Open does not confirm correspondence</span></div>
      <div class="facts-body">
        <article><span>Target</span><strong>FASTA · chain A · 30 residues</strong><small>Sequence and current tracks are available. UI locates residues by chain + residue position.</small></article>
        <article><span>Source</span><strong>Import bundle · chain A · 28 observed residues</strong><small>PDB structure plus one annotation sidecar tuple; residues 9 and 20 are not observed.</small></article>
        <article class="warning"><span>Current correspondence provenance</span><strong>${state.suggestionProvenance}</strong><small>No suggestion or manual edit is silently promoted to scientific correspondence; every disposition still requires explicit review.</small></article>
      </div>
    </section>`;
}

function renderAlignmentStrip(extraClass = "") {
  const facts = correspondenceFacts();
  const sourceByTarget = new Map(facts.matches.map((row) => [row.target.handle, row.source]));
  const selected = sourceByHandle(state.selectedSourceHandle);
  return `
    <section class="surface alignment-strip ${extraClass}">
      <div class="surface-header"><div><span class="surface-kicker">Synchronized evidence</span><h2>chain + residue locator 对照</h2></div><span class="surface-note">selected: ${selected ? locator(selected, "source") : "none"}</span></div>
      <div class="alignment-scroll">
        <div class="alignment-grid" style="--residue-count:${target.length}">
          <div class="lane-label"><b>Target</b><small>chain / residue</small></div>
          ${target.map((item) => `<div class="residue-cell target-cell"><small>${shortLocator(item)}</small><strong>${item.letter}</strong></div>`).join("")}
          <div class="lane-label source-label"><b>Source</b><small>observed chain / residue</small></div>
          ${target.map((targetItem) => {
            const sourceItem = sourceByTarget.get(targetItem.handle);
            if (!sourceItem) return `<div class="gap-cell"><span>target_gap</span></div>`;
            const status = rowStatus({ kind: "match", source: sourceItem, target: targetItem });
            return `<button class="residue-cell source-cell ${status.cls} ${state.selectedSourceHandle === sourceItem.handle ? "selected" : ""}" data-source-handle="${sourceItem.handle}" title="${status.label}"><small>${shortLocator(sourceItem)}</small><strong>${sourceItem.letter}</strong></button>`;
          }).join("")}
          <div class="lane-label"><b>Disposition</b><small>explicit row type</small></div>
          ${target.map((targetItem) => {
            const sourceItem = sourceByTarget.get(targetItem.handle);
            if (!sourceItem) return `<div class="evidence-cell target-gap">target_gap</div>`;
            const status = rowStatus({ kind: "match", source: sourceItem, target: targetItem });
            return `<div class="evidence-cell ${status.cls}">match${status.cls === "exact" ? " ✓" : status.cls === "sequence" ? " · SEQ✓" : " · ≠"}</div>`;
          }).join("")}
        </div>
      </div>
      <div class="source-gap-rail ${facts.sourceGaps.length ? "" : "empty"}"><b>source_gap</b>${facts.sourceGaps.length ? facts.sourceGaps.map((row) => `<button data-source-handle="${row.source.handle}">${locator(row.source, "source")} · ${row.source.letter}</button>`).join("") : "<span>none</span>"}</div>
      <div class="alignment-legend"><span><i class="exact"></i>match · locator + sequence agree</span><span><i class="sequence"></i>match · locator differs</span><span><i class="mismatch"></i>match · sequence conflict</span><span><i class="target-gap"></i>target_gap</span><b>三种 row type 始终显式显示</b></div>
    </section>`;
}

function renderAlignmentTools() {
  const selected = sourceByHandle(state.selectedSourceHandle);
  const selectedTarget = selected ? mappedTarget(selected) : null;
  const facts = correspondenceFacts();
  return `
    <section class="surface alignment-tools">
      <div class="surface-header"><div><span class="surface-kicker">Correspondence editor</span><h2>逐项处置 source 与 target</h2></div><span class="surface-note">one disposition each</span></div>
      <div class="tools-body">
        <div class="selected-card"><span>Selected source locator</span><strong>${selected ? `${locator(selected, "source")} · ${selected.letter}` : "none"}</strong><small>${selectedTarget ? `match ↔ ${locator(selectedTarget, "target")} · ${selectedTarget.letter}` : "source_gap · explicitly unpaired"}</small></div>
        <button class="button wide" data-action="source-gap" ${selected ? "" : "disabled"}>Set selected source to source_gap</button>
        <button class="button wide" data-action="target-gap-before" ${selected && selectedTarget ? "" : "disabled"}>Insert target_gap before selected source</button>
        <div class="quick-actions"><button data-action="gap-10" ${mappedTarget(sourceByPosition(10)) ? "" : "disabled"}>target_gap before source A·10</button><button data-action="gap-21" ${mappedTarget(sourceByPosition(21)) ? "" : "disabled"}>target_gap before source A·21</button></div>
        <div class="tool-group"><b>Explicit suggestion action</b><button class="button wide" data-action="locator-suggestion">Regenerate chain + residue locator draft · still unconfirmed</button></div>
        <div class="issue-summary"><b>Coverage invariant</b><span>source ${facts.sourceDispositionCount}/${source.length} exactly once</span><span>target ${facts.targetDispositionCount}/${target.length} exactly once</span><span>${facts.matches.length} match</span><span>${facts.sourceGaps.length} source_gap</span><span>${facts.targetGaps.length} target_gap</span><span>${facts.locatorMatches.length}/${facts.matches.length} locator matches</span></div>
      </div>
      <div class="surface-footer"><button class="button ghost" data-action="reset">Reset temporary suggestion</button><button class="button primary" data-action="review">Confirm correspondence</button></div>
    </section>`;
}

function renderMappingTable() {
  const facts = correspondenceFacts();
  const rows = facts.rows.filter((row) => state.tableFilter === "all" || rowStatus(row).cls !== "exact");
  return `
    <section class="surface mapping-table-surface">
      <div class="surface-header"><div><span class="surface-kicker">Complete correspondence</span><h2>match / source_gap / target_gap</h2></div><div class="table-filter"><button class="${state.tableFilter === "diagnostics" ? "active" : ""}" data-filter="diagnostics">Needs attention ${facts.rows.length - facts.locatorMatches.length}</button><button class="${state.tableFilter === "all" ? "active" : ""}" data-filter="all">All ${facts.rows.length}</button></div></div>
      <div class="table-scroll"><table><thead><tr><th>Row type</th><th>Source locator / value</th><th>Target locator</th><th>Target value</th><th>Evidence</th></tr></thead><tbody>
        ${rows.map((row) => {
          const status = rowStatus(row);
          if (row.kind === "target_gap") {
            return `<tr class="target-gap"><td><span class="row-kind target-gap">target_gap</span></td><td>—</td><td class="mono">${locator(row.target, "target")}</td><td class="mono">${row.target.letter}</td><td><button class="row-assign" data-assign-target="${row.target.handle}">Assign selected source</button></td></tr>`;
          }
          return `<tr class="${status.cls} ${state.selectedSourceHandle === row.source.handle ? "selected" : ""}" data-row-source="${row.source.handle}"><td><span class="row-kind ${row.kind === "match" ? "match" : "source-gap"}">${row.kind}</span></td><td><button class="row-select" data-source-handle="${row.source.handle}">${locator(row.source, "source")}</button><span class="mono value-cell">${row.source.letter}</span></td><td><select data-mapping-source="${row.source.handle}"><option value="" ${row.kind === "source_gap" ? "selected" : ""}>source_gap · no target</option>${target.map((candidate) => `<option value="${candidate.handle}" ${row.target?.handle === candidate.handle ? "selected" : ""}>${locator(candidate, "target")}</option>`).join("")}</select></td><td class="mono">${row.target?.letter ?? "—"}</td><td><span class="status-chip ${status.cls}">${status.label}</span></td></tr>`;
        }).join("")}
      </tbody></table></div>
      <div class="table-note">Selecting an occupied target moves the displaced source to <b>source_gap</b>; the old target becomes <b>target_gap</b>. This keeps every source and every target represented exactly once.</div>
    </section>`;
}

function renderDecisionButtons(track) {
  const selected = state.decisions[track.key];
  return `<div class="decision-buttons">${["adopt", "preserve", "conflict"].map((decision) => `<button class="${selected === decision ? "active" : ""}" data-decision="${track.key}|${decision}">${decision === "conflict" ? "conflict · unresolved" : decision}</button>`).join("")}</div>`;
}

function renderConflictEvidence(conflict) {
  return `<div class="conflict-row evidence-only"><div><b>${conflict.locator}</b><small>evidence only · no per-locator materialization</small></div><div class="conflict-value preserve">preserve evidence · ${conflict.current}</div><div class="conflict-value adopt">adopt evidence · ${conflict.imported}</div></div>`;
}

function renderTrackCard(track) {
  const decision = state.decisions[track.key];
  const conflicts = trackConflicts(track.key);
  const missingAdopt = decision === "adopt" && !track.sourceAvailable;
  return `
    <article class="track-card decision-${decision} ${missingAdopt ? "missing-track" : ""}">
      <div class="track-title"><div><b>${track.label}</b><span>source: ${track.sourceDetail} · current: ${track.currentDetail}</span></div><span class="decision-chip ${decision}">${decision}</span></div>
      ${renderDecisionButtons(track)}
      ${missingAdopt ? `<div class="inline-diagnostic danger"><b>missing adopted track</b><span>source bundle · chain A · track ${track.label}</span></div>` : ""}
      ${track.key === "function_annotations" ? `<p>Exact annotation tuple = (label, start residue, end residue). Evidence is separate provenance; no stable annotation ID implies “modified”.</p>` : `<p>${decision === "adopt" ? "Use source values where correspondence provides them." : decision === "preserve" ? "Keep the complete current track." : "Conflict is evidence only and cannot materialize; resolve the whole track to adopt or preserve."}</p>`}
      ${decision === "conflict" ? `<div class="bulk-actions track-resolution"><button data-track-resolution="${track.key}|preserve">all preserve · whole track</button><button data-track-resolution="${track.key}|adopt">all adopt · whole track</button></div>${conflicts.length ? conflicts.map(renderConflictEvidence).join("") : `<div class="no-conflict">No value-level conflict evidence, but the top-level conflict state is still unresolved and blocking.</div>`}` : ""}
      <div class="track-footer"><span>${track.sourceAvailable ? "source available" : "source missing"}</span><span class="${decision === "conflict" ? "danger" : ""}">${decision === "conflict" ? "blocking · choose whole-track adopt/preserve" : "materialized decision"}</span></div>
    </article>`;
}

function renderPreviewPanel() {
  if (!state.previewGenerated) return `<div class="preview-placeholder"><b>Preview not generated</b><span>Generate at any time; unconfirmed correspondence and conflict tracks return blocking diagnostics.</span></div>`;
  const diagnostics = previewDiagnostics();
  const blockers = diagnostics.filter((item) => item.severity === "error").length;
  return `
    <section class="preview-panel ${state.applied ? "applied" : ""}">
      <div class="preview-heading"><div><span>${state.applied ? "APPLIED · PROTOTYPE MEMORY" : "PREVIEW · NOT APPLIED"}</span><strong>Unified merge result</strong></div><b class="${blockers ? "danger" : ""}">${diagnostics.length} diagnostics · ${blockers} blocking</b></div>
      <div class="track-plan">${TRACKS.map((track) => `<span><b>${track.label}</b>${state.decisions[track.key]}</span>`).join("")}</div>
      <div class="diagnostics-list">
        ${diagnostics.length ? diagnostics.map((item) => `<article class="diagnostic ${item.severity}"><div><span>${item.category}</span><b>${item.track}</b></div><strong>${item.locator}</strong><p>${item.message}</p></article>`).join("") : `<div class="no-diagnostics">No diagnostics. Every preview issue has a locator and has been resolved.</div>`}
      </div>
      <p class="preview-note">${state.applied ? "Applied to prototype memory only." : blockers ? "Resolve every blocking diagnostic; warnings remain visible for informed Apply." : "No blockers. Apply remains an explicit separate action."}</p>
    </section>`;
}

function renderTrackMerge() {
  const diagnostics = state.previewGenerated ? previewDiagnostics() : [];
  const blockers = diagnostics.filter((item) => item.severity === "error").length;
  return `
    <section class="surface merge-surface">
      <div class="surface-header"><div><span class="surface-kicker">Track decisions + Preview</span><h2>逐 track adopt / preserve / conflict</h2></div><span class="surface-note">5 contract tracks</span></div>
      <div class="merge-body">
        ${!state.correspondenceReviewed ? `<div class="gate-message"><b>Correspondence is unconfirmed</b><p>Preview is available and will include blocking correspondence_unconfirmed; Apply remains disabled.</p></div>` : ""}
        ${TRACKS.map(renderTrackCard).join("")}
        ${renderPreviewPanel()}
      </div>
      <div class="surface-footer"><button class="button" data-action="preview">Generate Preview</button><button class="button primary" data-action="apply" ${state.previewGenerated && !blockers && !state.applied ? "" : "disabled"}>Apply merge</button></div>
    </section>`;
}

function renderVariantA() {
  return `<main class="workspace variant-a">${renderImportFacts(true)}${renderAlignmentTools()}${renderAlignmentStrip()}${renderMappingTable()}${renderTrackMerge()}</main>`;
}

function renderVariantB() {
  return `<main class="workspace variant-b"><div class="evidence-column">${renderImportFacts(true)}${renderAlignmentStrip("large")}</div><div class="precision-column">${renderAlignmentTools()}${renderMappingTable()}</div><div class="merge-column">${renderTrackMerge()}</div></main>`;
}

function renderStageRail() {
  const labels = ["Open facts", "Correspondence", "Track decisions", "Preview / Apply"];
  return `<aside class="stage-rail"><div><span class="surface-kicker">Gated workflow</span><h2>四个显式关卡</h2><p>临时建议、确认后的 correspondence、Preview 与 Apply 是不同状态。</p></div>${labels.map((label, index) => {
    const step = index + 1;
    const done = step === 1 || (step === 2 && state.correspondenceReviewed) || (step === 3 && state.previewGenerated) || (step === 4 && state.applied);
    const locked = (step === 3 && !state.correspondenceReviewed) || (step === 4 && !state.previewGenerated);
    const detail = step === 1 ? "source opened" : step === 2 ? state.correspondenceReviewed ? "confirmed" : "temporary suggestion" : step === 3 ? state.previewGenerated ? "decisions previewed" : "five tracks" : state.applied ? "applied" : "not applied";
    return `<button class="stage-button ${state.step === step ? "active" : ""} ${done ? "done" : ""}" data-step="${step}" ${locked ? "disabled" : ""}><span>${done ? "✓" : step}</span><div><b>${label}</b><small>${detail}</small></div></button>`;
  }).join("")}</aside>`;
}

function renderVariantC() {
  let stage;
  if (state.step === 1) stage = `<div class="stage-content import-stage">${renderImportFacts()}<div class="stage-explainer"><div><b>Open only records source facts</b><p>The visible temporary suggestion names its stub provenance and cannot be applied.</p></div><button class="button primary" data-step="2">Inspect correspondence</button></div></div>`;
  else if (state.step === 2) stage = `<div class="stage-content alignment-stage">${renderAlignmentStrip()}<div class="stage-bottom">${renderAlignmentTools()}${renderMappingTable()}</div></div>`;
  else if (state.step === 3) stage = `<div class="stage-content merge-stage">${renderTrackMerge()}<div class="stage-side-note"><b>Reviewed correspondence</b><p>${state.correspondenceNote}</p><button class="button" data-step="2">Return to edit</button><small>Any correspondence edit invalidates the review and Preview.</small></div></div>`;
  else stage = `<div class="stage-content final-stage"><section class="surface final-stage-card"><span class="surface-kicker">Preview / Apply</span><h2>${state.applied ? "Applied in prototype memory" : "Review all locatable diagnostics"}</h2>${renderPreviewPanel()}<div class="final-actions"><button class="button" data-step="3">Back to track decisions</button><button class="button primary" data-action="apply" ${state.previewGenerated && !previewDiagnostics().some((item) => item.severity === "error") && !state.applied ? "" : "disabled"}>Apply merge</button></div></section></div>`;
  return `<main class="workspace variant-c">${renderStageRail()}${stage}</main>`;
}

function renderPrototypeSwitcher() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  const keys = Object.keys(VARIANTS);
  const index = keys.indexOf(state.variant);
  const previous = keys[(index - 1 + keys.length) % keys.length];
  const next = keys[(index + 1) % keys.length];
  return `<div class="prototype-switcher"><button data-variant="${previous}" aria-label="上一个方案">←</button><div><span>PROTOTYPE VARIANT</span><strong>${VARIANTS[state.variant].label}</strong><small>${VARIANTS[state.variant].question}</small></div><button data-variant="${next}" aria-label="下一个方案">→</button></div>`;
}

function renderStateInspector() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  const facts = correspondenceFacts();
  return `<details class="state-inspector"><summary>Prototype state</summary><pre>${JSON.stringify({
    variant: state.variant,
    suggestionProvenance: state.suggestionProvenance,
    correspondenceReviewed: state.correspondenceReviewed,
    correspondence: { match: facts.matches.length, source_gap: facts.sourceGaps.length, target_gap: facts.targetGaps.length },
    sourceDisposition: `${facts.sourceDispositionCount}/${source.length}`,
    targetDisposition: `${facts.targetDispositionCount}/${target.length}`,
    decisions: state.decisions,
    previewGenerated: state.previewGenerated,
    diagnostics: state.previewGenerated ? previewDiagnostics().map(({ severity, category, track, locator }) => ({ severity, category, track, locator })) : [],
    applied: state.applied,
    lastAction: state.lastAction,
  }, null, 2)}</pre></details>`;
}

function render() {
  const root = document.querySelector("#app");
  const body = state.variant === "A" ? renderVariantA() : state.variant === "B" ? renderVariantB() : renderVariantC();
  root.innerHTML = `<div class="app-shell">${renderTopbar()}${body}</div>${renderPrototypeSwitcher()}${renderStateInspector()}<div class="toasts"></div>`;
  renderToasts();
}

function setVariant(key) {
  state.variant = key;
  const params = new URLSearchParams(location.search);
  params.set("variant", key);
  history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
  state.lastAction = `切换到 ${VARIANTS[key].label}；完整原型状态保持`;
  render();
}

document.addEventListener("click", (event) => {
  const variantButton = event.target.closest("[data-variant]");
  if (variantButton) return setVariant(variantButton.dataset.variant);
  const sourceButton = event.target.closest("[data-source-handle]");
  if (sourceButton) {
    state.selectedSourceHandle = sourceButton.dataset.sourceHandle;
    state.lastAction = `selected ${locator(sourceByHandle(state.selectedSourceHandle), "source")}`;
    return render();
  }
  const assignTargetButton = event.target.closest("[data-assign-target]");
  if (assignTargetButton) return assignSourceToTarget(state.selectedSourceHandle, assignTargetButton.dataset.assignTarget);
  const filterButton = event.target.closest("[data-filter]");
  if (filterButton) { state.tableFilter = filterButton.dataset.filter; return render(); }
  const decisionButton = event.target.closest("[data-decision]");
  if (decisionButton) {
    const [trackKey, decision] = decisionButton.dataset.decision.split("|");
    return setDecision(trackKey, decision);
  }
  const trackResolutionButton = event.target.closest("[data-track-resolution]");
  if (trackResolutionButton) {
    const [trackKey, decision] = trackResolutionButton.dataset.trackResolution.split("|");
    return setDecision(trackKey, decision);
  }
  const stepButton = event.target.closest("[data-step]");
  if (stepButton) { state.step = Number(stepButton.dataset.step); state.lastAction = `进入关卡 ${state.step}`; return render(); }
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action) return;
  if (action === "reset") return resetSuggestion();
  if (action === "locator-suggestion") return applyLocatorSuggestion();
  if (action === "source-gap") return assignSourceToTarget(state.selectedSourceHandle, null);
  if (action === "target-gap-before") return insertTargetGapBefore(state.selectedSourceHandle);
  if (action === "gap-10") return insertTargetGapBefore(sourceByPosition(10).handle);
  if (action === "gap-21") return insertTargetGapBefore(sourceByPosition(21).handle);
  if (action === "review") return reviewCorrespondence();
  if (action === "preview") return generatePreview();
  if (action === "apply") return applyMerge();
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-mapping-source]")) return assignSourceToTarget(event.target.dataset.mappingSource, event.target.value);
});

document.addEventListener("keydown", (event) => {
  if (!SHOW_PROTOTYPE_CONTROLS || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  if (event.target.matches("input, textarea, select, [contenteditable='true']")) return;
  const keys = Object.keys(VARIANTS);
  const index = keys.indexOf(state.variant);
  setVariant(keys[(index + (event.key === "ArrowRight" ? 1 : -1) + keys.length) % keys.length]);
});

render();
