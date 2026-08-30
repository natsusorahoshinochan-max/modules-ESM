// THROWAWAY UI PROTOTYPE — not production code.
// Three variants of the import / merge / manual residue-alignment workspace,
// switchable via ?variant=. The prototype answers one question: can a
// researcher verify every source-to-target residue correspondence before merge?

const VARIANTS = {
  A: { name: "Mapping ledger", label: "A · 对应账本", question: "可视对齐、精确对应表与合并账本同屏，能否让临时草稿不被误认成科学对应？" },
  B: { name: "Evidence split", label: "B · 证据分屏（已采用）", question: "把可视证据与精确对应并排放大，是否更容易发现错位和碰撞？", adopted: true },
  C: { name: "Gated confirmation", label: "C · 关卡式确认", question: "把导入、对齐、轨道和最终合并分阶段，能否减少跳步误确认？" },
};

const SHOW_PROTOTYPE_CONTROLS = location.protocol === "file:" || ["127.0.0.1", "localhost"].includes(location.hostname);
const variantFromUrl = new URLSearchParams(location.search).get("variant")?.toUpperCase();
const TARGET_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKI";
const MISSING_SOURCE_NUMBERS = new Set([9, 20]);

function buildTarget() {
  return [...TARGET_SEQUENCE].map((letter, index) => ({
    id: `A:${index + 1}`,
    number: index + 1,
    letter,
    currentCoordinates: [5, 6, 7, 17].includes(index + 1),
  }));
}

function buildSource() {
  return [...TARGET_SEQUENCE]
    .map((letter, index) => ({ number: index + 1, letter }))
    .filter((item) => !MISSING_SOURCE_NUMBERS.has(item.number))
    .map((item, observedIndex) => ({
      id: `pdb:A:${item.number}`,
      number: item.number,
      observedIndex,
      // One real scientific disagreement is deliberately retained after the
      // two missing intervals are aligned. The value is illustrative.
      letter: item.number === 17 ? "I" : item.letter,
      coordinates: `PDB coordinates A:${item.number}（示意）`,
    }));
}

const target = buildTarget();
const source = buildSource();

function positionalMapping() {
  return Object.fromEntries(source.map((item, index) => [item.id, target[index]?.id ?? null]));
}

const state = {
  variant: VARIANTS[variantFromUrl] ? variantFromUrl : "B",
  mapping: positionalMapping(),
  alignmentTouched: false,
  selectedSourceId: "pdb:A:10",
  tableFilter: "issues",
  alignmentReviewed: false,
  alignmentReviewNote: "",
  includedTracks: { sequence: true, coordinates: true },
  resolutions: { sequence: {}, coordinates: {} },
  mergePreview: false,
  mergeConfirmed: false,
  step: 2,
  moveStart: 10,
  moveEnd: 19,
  moveOffset: 1,
  lastAction: "已导入 PDB；按来源观察数组位置建立临时草稿，尚未确认科学对应",
  toasts: [],
};

function targetById(id) {
  return target.find((item) => item.id === id);
}

function sourceById(id) {
  return source.find((item) => item.id === id);
}

function mappedTarget(item) {
  return targetById(state.mapping[item.id]);
}

function mappingIndex(item) {
  return target.findIndex((candidate) => candidate.id === state.mapping[item.id]);
}

function mappingOccupants() {
  const byTarget = new Map();
  source.forEach((item) => {
    const targetId = state.mapping[item.id];
    if (!targetId) return;
    const items = byTarget.get(targetId) ?? [];
    items.push(item);
    byTarget.set(targetId, items);
  });
  return byTarget;
}

function collisionTargetIds() {
  return new Set([...mappingOccupants()].filter(([, items]) => items.length > 1).map(([targetId]) => targetId));
}

function alignmentFacts() {
  const collisions = collisionTargetIds();
  const unmapped = source.filter((item) => !state.mapping[item.id]);
  const letterMismatches = source.filter((item) => {
    const mapped = mappedTarget(item);
    return mapped && mapped.letter !== item.letter;
  });
  const exactNumber = source.filter((item) => mappedTarget(item)?.number === item.number);
  return {
    collisions,
    unmapped,
    letterMismatches,
    exactNumber,
    mappedCount: source.length - unmapped.length,
    canReview: collisions.size === 0 && state.alignmentTouched,
  };
}

function invalidateReview(message) {
  state.alignmentReviewed = false;
  state.alignmentReviewNote = "";
  state.mergePreview = false;
  state.mergeConfirmed = false;
  state.resolutions = { sequence: {}, coordinates: {} };
  if (state.step > 2) state.step = 2;
  state.lastAction = message;
}

function addToast(text, tone = "") {
  const id = `${Date.now()}-${Math.random()}`;
  state.toasts.push({ id, text, tone });
  setTimeout(() => {
    state.toasts = state.toasts.filter((item) => item.id !== id);
    renderToasts();
  }, 3200);
}

function renderToasts() {
  const root = document.querySelector(".toasts");
  if (!root) return;
  root.innerHTML = state.toasts.map((item) => `<div class="toast ${item.tone}">${item.text}</div>`).join("");
}

function resetDraft() {
  state.mapping = positionalMapping();
  state.alignmentTouched = false;
  state.selectedSourceId = "pdb:A:10";
  invalidateReview("已重建按数组位置临时草稿；所有对齐与合并确认失效");
  addToast("已重置临时草稿", "warn");
  render();
}

function insertGapBefore(sourceId) {
  const selected = sourceById(sourceId);
  if (!selected) return;
  const selectedIndex = source.findIndex((item) => item.id === sourceId);
  for (let index = source.length - 1; index >= selectedIndex; index -= 1) {
    const item = source[index];
    const currentIndex = mappingIndex(item);
    state.mapping[item.id] = currentIndex >= 0 && currentIndex + 1 < target.length ? target[currentIndex + 1].id : null;
  }
  state.alignmentTouched = true;
  invalidateReview(`已在来源 A:${selected.number} 前插入 gap；其后对应整体右移 1`);
  state.selectedSourceId = sourceId;
  addToast(`来源 A:${selected.number} 前已插入 gap；对应需重新核对`);
  render();
}

function moveInterval(startNumber, endNumber, offset) {
  const affected = source.filter((item) => item.number >= startNumber && item.number <= endNumber);
  affected.forEach((item) => {
    const currentIndex = mappingIndex(item);
    const nextIndex = currentIndex + offset;
    state.mapping[item.id] = nextIndex >= 0 && nextIndex < target.length ? target[nextIndex].id : null;
  });
  state.alignmentTouched = true;
  invalidateReview(`已移动来源 A:${startNumber}–${endNumber} 区间 ${offset > 0 ? "+" : ""}${offset}；对应需重新核对`);
  addToast(`已移动 ${affected.length} 个来源残基`, "warn");
  render();
}

function setPreciseMapping(sourceId, targetId) {
  const item = sourceById(sourceId);
  if (!item) return;
  state.mapping[sourceId] = targetId || null;
  state.alignmentTouched = true;
  state.selectedSourceId = sourceId;
  invalidateReview(`已精确指定来源 A:${item.number} → ${targetId ? `目标 ${targetId}` : "不映射"}`);
  addToast("精确对应已修改；旧确认失效", "warn");
  render();
}

function reviewAlignment() {
  const facts = alignmentFacts();
  if (!facts.canReview) {
    addToast(facts.collisions.size ? `仍有 ${facts.collisions.size} 个目标残基被重复映射，不能确认` : "必须先手动调整临时草稿，再确认残基对应", "danger");
    return;
  }
  state.alignmentReviewed = true;
  state.alignmentReviewNote = `已显式核对 ${facts.mappedCount} 个来源对应；${facts.unmapped.length} 个来源残基不映射`;
  state.mergePreview = false;
  state.mergeConfirmed = false;
  state.lastAction = state.alignmentReviewNote;
  state.step = Math.max(state.step, 3);
  addToast("残基对应已确认；合并尚未确认", "success");
  render();
}

function trackConflict(trackKey, sourceItem) {
  const mapped = mappedTarget(sourceItem);
  if (!mapped || !state.includedTracks[trackKey]) return false;
  if (trackKey === "sequence") return mapped.letter !== sourceItem.letter;
  if (trackKey === "coordinates") return mapped.currentCoordinates;
  return false;
}

function conflicts(trackKey) {
  return source.filter((item) => trackConflict(trackKey, item));
}

function unresolvedConflicts() {
  return ["sequence", "coordinates"].flatMap((trackKey) =>
    conflicts(trackKey)
      .filter((item) => !state.resolutions[trackKey][item.id])
      .map((item) => ({ trackKey, item }))
  );
}

function setResolution(trackKey, sourceId, choice) {
  state.resolutions[trackKey][sourceId] = choice;
  state.mergePreview = false;
  state.mergeConfirmed = false;
  if (state.step > 3) state.step = 3;
  state.lastAction = `${trackKey === "sequence" ? "Sequence" : "Coordinates"} 冲突：${choice === "source" ? "采用 PDB" : "保留当前 Prompt"}`;
  render();
}

function resolveAll(trackKey, choice) {
  conflicts(trackKey).forEach((item) => { state.resolutions[trackKey][item.id] = choice; });
  state.mergePreview = false;
  state.mergeConfirmed = false;
  state.lastAction = `${trackKey === "sequence" ? "Sequence" : "Coordinates"} 的全部冲突已选择${choice === "source" ? "采用 PDB" : "保留当前"}`;
  addToast(state.lastAction);
  render();
}

function mergeCounts(trackKey) {
  const counts = { added: 0, retained: 0, replaced: 0, unresolved: 0, unavailable: 0 };
  if (!state.includedTracks[trackKey]) {
    counts.retained = target.length;
    return counts;
  }
  const mappedSourceIds = new Set();
  source.forEach((item) => {
    const mapped = mappedTarget(item);
    if (!mapped) return;
    mappedSourceIds.add(mapped.id);
    if (trackKey === "sequence") {
      if (mapped.letter === item.letter) counts.retained += 1;
      else {
        const choice = state.resolutions.sequence[item.id];
        if (!choice) counts.unresolved += 1;
        else if (choice === "source") counts.replaced += 1;
        else counts.retained += 1;
      }
    } else if (trackKey === "coordinates") {
      if (!mapped.currentCoordinates) counts.added += 1;
      else {
        const choice = state.resolutions.coordinates[item.id];
        if (!choice) counts.unresolved += 1;
        else if (choice === "source") counts.replaced += 1;
        else counts.retained += 1;
      }
    }
  });
  target.filter((item) => !mappedSourceIds.has(item.id)).forEach((item) => {
    if (trackKey === "sequence" || item.currentCoordinates) counts.retained += 1;
    else counts.unavailable += 1;
  });
  return counts;
}

function buildMergePreview() {
  if (!state.alignmentReviewed) {
    addToast("先显式确认残基对应；临时草稿不能直接合并", "danger");
    return;
  }
  const unresolved = unresolvedConflicts();
  if (unresolved.length) {
    addToast(`仍有 ${unresolved.length} 个逐轨道冲突未处理`, "danger");
    return;
  }
  state.mergePreview = true;
  state.mergeConfirmed = false;
  state.step = 4;
  state.lastAction = "统一合并预览已生成；ProteinPrompt 尚未改变";
  addToast("合并预览已生成，尚未应用");
  render();
}

function confirmMerge() {
  if (!state.mergePreview || unresolvedConflicts().length || !state.alignmentReviewed) {
    addToast("合并条件尚未满足", "danger");
    return;
  }
  state.mergeConfirmed = true;
  state.lastAction = "已确认合并；本次结果只存在原型内存中";
  addToast("合并已确认（原型内存状态）", "success");
  render();
}

function statusTone(item) {
  const targetItem = mappedTarget(item);
  if (!targetItem) return { cls: "unmapped", label: "未映射" };
  if (collisionTargetIds().has(targetItem.id)) return { cls: "collision", label: "重复目标" };
  if (targetItem.number === item.number && targetItem.letter === item.letter) return { cls: "exact", label: "编号+序列一致" };
  if (targetItem.letter === item.letter) return { cls: "sequence", label: "序列一致 / 编号不同" };
  return { cls: "mismatch", label: "序列不一致" };
}

function renderTopbar() {
  const facts = alignmentFacts();
  const unresolved = unresolvedConflicts().length;
  const banner = state.mergeConfirmed
    ? { cls: "confirmed", eyebrow: "合并已确认", title: "最终 ProteinPrompt 合并结果仅存在原型内存中", text: "刷新页面会恢复初始导入；这不是生产保存。" }
    : state.alignmentReviewed
      ? { cls: "reviewed", eyebrow: "残基对应已核对 · 合并未确认", title: state.alignmentReviewNote, text: unresolved ? `仍有 ${unresolved} 个逐轨道冲突待处理。` : "可以生成统一合并预览；当前 ProteinPrompt 仍未改变。" }
      : { cls: "draft", eyebrow: "临时对齐草稿 · 未确认", title: "仅按来源观察数组位置建立，不是最终科学对应关系", text: `PDB 观察到 28 residues；目标为 30 residues。${facts.collisions.size ? ` 另有 ${facts.collisions.size} 个重复目标映射。` : " 必须手动调整并确认。"}` };
  return `
    <header class="topbar">
      <div class="brand"><span class="brand-mark">PW</span><div><strong>Protein Workbench</strong><small>Prompt Studio · 一次性原型 4</small></div></div>
      <div class="prompt-title"><span class="prototype-badge">THROWAWAY</span><strong>FASTA Prompt · ubiquitin N-terminal 30 residues（真实序列）</strong><span>导入 PDB 结构（缺失区间与坐标均为示意）</span></div>
      <div class="top-actions"><button class="button ghost" data-action="reset">重置导入</button><button class="button" data-action="attempt-preview">生成统一合并预览</button><button class="button primary" data-action="confirm-merge" ${state.mergePreview && !state.mergeConfirmed ? "" : "disabled"}>确认最终合并</button></div>
    </header>
    <section class="draft-banner ${banner.cls}"><div><span>${banner.eyebrow}</span><strong>${banner.title}</strong></div><p>${banner.text}</p></section>
  `;
}

function renderImportFacts(compact = false) {
  return `
    <section class="surface import-facts ${compact ? "compact" : ""}">
      <div class="surface-header"><div><span class="surface-kicker">Import facts</span><h2>来源事实，不等于对应关系</h2></div><span class="surface-note">PDB 内容示意</span></div>
      <div class="facts-body">
        <article><span>当前目标</span><strong>FASTA · chain A · 30 residues</strong><small>Sequence 30 assigned；Coordinates 4 assigned（手工 motif，示意）；SS8 / SASA / functions 保留当前。</small></article>
        <article><span>新来源</span><strong>PDB · chain A · 28 observed residues</strong><small>编号 A:1–30；未观察 A:9、A:20。来源提供 Sequence + Coordinates。</small></article>
        <article class="warning"><span>初始规则</span><strong>只按 observed array position</strong><small>来源第 9 项 A:10 暂映射到目标 A:9。此草稿故意不使用编号或自动比对。</small></article>
      </div>
    </section>`;
}

function renderAlignmentStrip(extraClass = "") {
  const occupants = mappingOccupants();
  const selected = sourceById(state.selectedSourceId);
  return `
    <section class="surface alignment-strip ${extraClass}">
      <div class="surface-header"><div><span class="surface-kicker">Synchronized visual alignment</span><h2>上下序列对齐</h2></div><span class="surface-note">选中：${selected ? `来源 A:${selected.number}` : "无"}</span></div>
      <div class="alignment-scroll">
        <div class="alignment-grid" style="--residue-count:${target.length}">
          <div class="lane-label"><b>目标 FASTA</b><small>ResidueLayout</small></div>
          ${target.map((item) => `<button class="residue-cell target-cell ${collisionTargetIds().has(item.id) ? "collision" : ""}" data-target-id="${item.id}"><small>A:${item.number}</small><strong>${item.letter}</strong></button>`).join("")}
          <div class="lane-label source-label"><b>来源 PDB</b><small>observed residues</small></div>
          ${target.map((targetItem) => {
            const items = occupants.get(targetItem.id) ?? [];
            if (!items.length) return `<div class="gap-cell"><span>gap</span></div>`;
            return `<div class="source-stack">${items.map((item) => {
              const status = statusTone(item);
              return `<button class="residue-cell source-cell ${status.cls} ${state.selectedSourceId === item.id ? "selected" : ""}" data-source-id="${item.id}" title="${status.label}"><small>A:${item.number}</small><strong>${item.letter}</strong></button>`;
            }).join("")}</div>`;
          }).join("")}
          <div class="lane-label"><b>对应证据</b><small>编号 / sequence</small></div>
          ${target.map((targetItem) => {
            const items = occupants.get(targetItem.id) ?? [];
            if (!items.length) return `<div class="evidence-cell missing">无来源</div>`;
            if (items.length > 1) return `<div class="evidence-cell collision">${items.length}× 冲突</div>`;
            const status = statusTone(items[0]);
            return `<div class="evidence-cell ${status.cls}">${status.cls === "exact" ? "✓" : status.cls === "sequence" ? "SEQ✓" : "≠"}</div>`;
          }).join("")}
        </div>
      </div>
      <div class="alignment-legend"><span><i class="exact"></i>编号+序列一致</span><span><i class="sequence"></i>仅序列一致</span><span><i class="mismatch"></i>序列不一致</span><span><i class="collision"></i>重复目标</span><b>颜色始终伴随文字/符号，不单独承载含义</b></div>
    </section>`;
}

function renderAlignmentTools() {
  const selected = sourceById(state.selectedSourceId);
  const facts = alignmentFacts();
  return `
    <section class="surface alignment-tools">
      <div class="surface-header"><div><span class="surface-kicker">Manual alignment</span><h2>手动调整</h2></div><span class="surface-note">任何改动都会撤销旧确认</span></div>
      <div class="tools-body">
        <div class="selected-card"><span>当前来源残基</span><strong>${selected ? `PDB A:${selected.number} · ${selected.letter}` : "未选择"}</strong><small>暂对应 ${selected && mappedTarget(selected) ? `${mappedTarget(selected).id} · ${mappedTarget(selected).letter}` : "不映射"}</small></div>
        <button class="button wide" data-action="insert-gap" ${selected ? "" : "disabled"}>在当前来源残基前插入 gap</button>
        <div class="quick-actions"><button data-action="gap-10">在 A:10 前插入 gap</button><button data-action="gap-21">在 A:21 前插入 gap</button></div>
        <div class="tool-group"><b>移动来源区间</b><div class="move-grid"><label>从<input type="number" value="${state.moveStart}" min="1" max="30" data-field="move-start"></label><label>到<input type="number" value="${state.moveEnd}" min="1" max="30" data-field="move-end"></label><label>位移<input type="number" value="${state.moveOffset}" min="-5" max="5" data-field="move-offset"></label></div><button class="button wide" data-action="move-interval">移动区间并同步两种视图</button></div>
        <div class="issue-summary"><b>当前草稿</b><span>${facts.mappedCount}/28 mapped</span><span>${facts.unmapped.length} unmapped source</span><span class="${facts.collisions.size ? "danger" : ""}">${facts.collisions.size} duplicate targets</span><span>${facts.exactNumber.length}/28 source numbers match target identities</span><span class="${state.alignmentTouched ? "" : "danger"}">${state.alignmentTouched ? "已手动调整" : "尚未手动调整"}</span></div>
      </div>
      <div class="surface-footer"><button class="button ghost" data-action="reset">恢复按位置草稿</button><button class="button primary" data-action="review-alignment" ${facts.canReview ? "" : "disabled"}>确认残基对应</button></div>
    </section>`;
}

function renderMappingTable() {
  const facts = alignmentFacts();
  const rows = source.filter((item) => {
    if (state.tableFilter === "all") return true;
    const status = statusTone(item).cls;
    return status !== "exact";
  });
  return `
    <section class="surface mapping-table-surface">
      <div class="surface-header"><div><span class="surface-kicker">Exact residue correspondence</span><h2>精确残基对应表</h2></div><div class="table-filter"><button class="${state.tableFilter === "issues" ? "active" : ""}" data-filter="issues">仅问题 ${source.length - facts.exactNumber.length}</button><button class="${state.tableFilter === "all" ? "active" : ""}" data-filter="all">全部 28</button></div></div>
      <div class="table-scroll"><table><thead><tr><th>来源 PDB residue identity</th><th>来源值</th><th>目标 ResidueLayout identity</th><th>目标值</th><th>核对状态</th></tr></thead><tbody>
        ${rows.map((item) => {
          const mapped = mappedTarget(item);
          const status = statusTone(item);
          return `<tr class="${status.cls} ${state.selectedSourceId === item.id ? "selected" : ""}" data-row-source="${item.id}"><td><button class="row-select" data-source-id="${item.id}">PDB A:${item.number}</button></td><td class="mono">${item.letter}</td><td><select data-mapping-source="${item.id}"><option value="">— 不映射 —</option>${target.map((candidate) => `<option value="${candidate.id}" ${mapped?.id === candidate.id ? "selected" : ""}>${candidate.id}</option>`).join("")}</select></td><td class="mono">${mapped?.letter ?? "—"}</td><td><span class="status-chip ${status.cls}">${status.label}</span></td></tr>`;
        }).join("")}
      </tbody></table></div>
      <div class="table-note">上下序列与本表共享同一 mapping state；在任一处选择或修改都会同步另一处。来源 identity 与目标 identity 始终分别显示。</div>
    </section>`;
}

function renderTrackMerge() {
  const sequenceConflicts = conflicts("sequence");
  const coordinateConflicts = conflicts("coordinates");
  const unresolved = unresolvedConflicts();
  const sequenceCounts = mergeCounts("sequence");
  const coordinateCounts = mergeCounts("coordinates");
  return `
    <section class="surface merge-surface">
      <div class="surface-header"><div><span class="surface-kicker">Unified merge preview</span><h2>按轨道选择与冲突处理</h2></div><span class="surface-note">不是“覆盖全部 / 只填空白”</span></div>
      <div class="merge-body">
        ${!state.alignmentReviewed ? `<div class="gate-message"><b>残基对应尚未确认</b><p>可以查看来源轨道，但不能生成或应用合并预览。</p></div>` : ""}
        ${state.mergePreview ? renderFinalLedger() : ""}
        <article class="track-card ${state.includedTracks.sequence ? "included" : "excluded"}">
          <div class="track-title"><label><input type="checkbox" data-track="sequence" ${state.includedTracks.sequence ? "checked" : ""}>采用 PDB Sequence</label><span>来源存在 · 当前存在</span></div>
          <p>相同值保留；不同值逐个选择当前 FASTA 或 PDB。关闭本轨道会保留全部当前 Sequence。</p>
          <div class="count-strip"><span>新增 ${sequenceCounts.added}</span><span>保留 ${sequenceCounts.retained}</span><span>替换 ${sequenceCounts.replaced}</span><span class="${sequenceCounts.unresolved ? "danger" : ""}>冲突 ${sequenceCounts.unresolved}</span></div>
          ${state.includedTracks.sequence && sequenceConflicts.length ? `<div class="bulk-actions"><button data-resolve-all="sequence:current">全部保留当前</button><button data-resolve-all="sequence:source">全部采用 PDB</button></div>${sequenceConflicts.map((item) => renderConflictRow("sequence", item)).join("")}` : `<div class="no-conflict">Sequence 来源未采用；当前 FASTA 30/30 保留。</div>`}
        </article>
        <article class="track-card ${state.includedTracks.coordinates ? "included" : "excluded"}">
          <div class="track-title"><label><input type="checkbox" data-track="coordinates" ${state.includedTracks.coordinates ? "checked" : ""}>采用 PDB Coordinates</label><span>来源存在 · 当前局部存在</span></div>
          <p>当前 Mask 位置可新增 coordinates；已有 motif coordinates 与 PDB 值逐个解决。</p>
          <div class="count-strip"><span>新增 ${coordinateCounts.added}</span><span>保留 ${coordinateCounts.retained}</span><span>替换 ${coordinateCounts.replaced}</span><span class="${coordinateCounts.unresolved ? "danger" : ""}>冲突 ${coordinateCounts.unresolved}</span></div>
          ${state.includedTracks.coordinates && coordinateConflicts.length ? `<div class="bulk-actions"><button data-resolve-all="coordinates:current">全部保留当前</button><button data-resolve-all="coordinates:source">全部采用 PDB</button></div>${coordinateConflicts.map((item) => renderConflictRow("coordinates", item)).join("")}` : `<div class="no-conflict">Coordinates 来源未采用；当前 coordinates 状态保留。</div>`}
        </article>
        <article class="track-card unavailable"><div class="track-title"><b>SS8 · SASA · Function annotations</b><span>本 PDB 来源未提供</span></div><p>这些内容保留当前 Prompt；界面不从 PDB 静默派生或清除。</p><div class="count-strip"><span>SS8 保留</span><span>SASA 保留</span><span>Functions 保留</span></div></article>
        ${state.mergePreview ? "" : `<div class="preview-placeholder"><b>统一预览尚未生成</b><span>${state.alignmentReviewed ? unresolved.length ? `先处理 ${unresolved.length} 个冲突。` : "全部冲突已处理，可以生成预览。" : "临时草稿不能直接变成 ProteinPrompt。"}</span></div>`}
      </div>
      <div class="surface-footer"><button class="button" data-action="attempt-preview" ${state.alignmentReviewed && !unresolved.length ? "" : "disabled"}>生成统一合并预览</button><button class="button primary" data-action="confirm-merge" ${state.mergePreview && !state.mergeConfirmed ? "" : "disabled"}>确认最终合并</button></div>
    </section>`;
}

function renderConflictRow(trackKey, item) {
  const mapped = mappedTarget(item);
  const choice = state.resolutions[trackKey][item.id];
  const currentText = trackKey === "sequence" ? mapped?.letter : "当前 motif XYZ";
  const sourceText = trackKey === "sequence" ? item.letter : `PDB A:${item.number} XYZ`;
  return `<div class="conflict-row ${choice ? "resolved" : ""}"><div><b>${mapped?.id ?? "unmapped"} ← PDB A:${item.number}</b><small>${choice ? `已选择：${choice === "source" ? "采用 PDB" : "保留当前"}` : "冲突待处理"}</small></div><button class="${choice === "current" ? "active" : ""}" data-resolution="${trackKey}|${item.id}|current">当前 ${currentText}</button><button class="${choice === "source" ? "active" : ""}" data-resolution="${trackKey}|${item.id}|source">PDB ${sourceText}</button></div>`;
}

function renderFinalLedger() {
  const seq = mergeCounts("sequence");
  const xyz = mergeCounts("coordinates");
  return `<div class="final-ledger ${state.mergeConfirmed ? "confirmed" : ""}"><div><span>${state.mergeConfirmed ? "已确认" : "未应用预览"}</span><strong>ProteinPrompt 合并账本</strong></div><ul><li><b>ResidueLayout</b><span>保留 30 identities；未新增、未删除</span></li><li><b>Sequence</b><span>新增 ${seq.added} · 保留 ${seq.retained} · 替换 ${seq.replaced} · 冲突 0</span></li><li><b>Coordinates</b><span>新增 ${xyz.added} · 保留 ${xyz.retained} · 替换 ${xyz.replaced} · 无来源 ${xyz.unavailable}</span></li><li><b>SS8 / SASA</b><span>来源未提供；保留当前</span></li><li><b>Function annotations</b><span>来源未提供；保留当前 intervals</span></li></ul><p>${state.mergeConfirmed ? "合并结果已写入原型内存；生产保存语义不在本原型范围。" : "确认前当前 ProteinPrompt 没有变化。"}</p></div>`;
}

function renderVariantA() {
  return `<main class="workspace variant-a">${renderImportFacts(true)}${renderAlignmentTools()}${renderAlignmentStrip()}${renderMappingTable()}${renderTrackMerge()}</main>`;
}

function renderVariantB() {
  return `<main class="workspace variant-b"><div class="evidence-column">${renderImportFacts(true)}${renderAlignmentStrip("large")}</div><div class="precision-column">${renderAlignmentTools()}${renderMappingTable()}</div><div class="merge-column">${renderTrackMerge()}</div></main>`;
}

function renderStageRail() {
  const labels = ["导入事实", "残基对齐", "轨道与冲突", "最终合并"];
  return `<aside class="stage-rail"><div><span class="surface-kicker">Gated workflow</span><h2>四个确认关卡</h2><p>后续关卡不会把前面的临时状态默认为正确。</p></div>${labels.map((label, index) => {
    const step = index + 1;
    const done = step === 1 || (step === 2 && state.alignmentReviewed) || (step === 3 && state.mergePreview) || (step === 4 && state.mergeConfirmed);
    const locked = step >= 3 && !state.alignmentReviewed;
    return `<button class="stage-button ${state.step === step ? "active" : ""} ${done ? "done" : ""}" data-step="${step}" ${locked ? "disabled" : ""}><span>${done ? "✓" : step}</span><div><b>${label}</b><small>${step === 1 ? "30 vs 28" : step === 2 ? state.alignmentReviewed ? "对应已核对" : "临时草稿" : step === 3 ? state.mergePreview ? "预览已生成" : "待选择" : state.mergeConfirmed ? "合并已确认" : "尚未应用"}</small></div></button>`;
  }).join("")}</aside>`;
}

function renderVariantC() {
  let stage;
  if (state.step === 1) stage = `<div class="stage-content import-stage">${renderImportFacts()}<div class="stage-explainer"><b>此阶段只确认导入事实</b><p>来源长度、观察编号和缺失区间不会自动决定 target ResidueLayout 对应。</p><button class="button primary" data-step="2">建立按位置临时草稿</button></div></div>`;
  else if (state.step === 2) stage = `<div class="stage-content alignment-stage">${renderAlignmentStrip()}<div class="stage-bottom">${renderAlignmentTools()}${renderMappingTable()}</div></div>`;
  else if (state.step === 3) stage = `<div class="stage-content merge-stage">${renderTrackMerge()}<div class="stage-side-note"><b>已锁定的核对事实</b><p>${state.alignmentReviewNote}</p><button class="button" data-step="2">返回修改对应</button><small>修改任何 mapping 会撤销本关卡和旧预览。</small></div></div>`;
  else stage = `<div class="stage-content final-stage"><section class="surface final-stage-card"><span class="surface-kicker">Final confirmation</span><h2>${state.mergeConfirmed ? "合并已确认" : "最终合并仍未应用"}</h2>${state.mergePreview ? renderFinalLedger() : "<p>先生成统一合并预览。</p>"}<div class="final-actions"><button class="button" data-step="3">返回轨道选择</button><button class="button primary" data-action="confirm-merge" ${state.mergePreview && !state.mergeConfirmed ? "" : "disabled"}>确认最终合并</button></div></section></div>`;
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
  const facts = alignmentFacts();
  return `<details class="state-inspector"><summary>原型状态</summary><pre>${JSON.stringify({
    variant: state.variant,
    draft: !state.alignmentReviewed,
    alignmentReviewed: state.alignmentReviewed,
    alignmentTouched: state.alignmentTouched,
    mapped: facts.mappedCount,
    collisions: [...facts.collisions],
    exactIdentityMappings: facts.exactNumber.length,
    includedTracks: state.includedTracks,
    unresolvedConflicts: unresolvedConflicts().length,
    mergePreview: state.mergePreview,
    mergeConfirmed: state.mergeConfirmed,
    lastAction: state.lastAction,
  }, null, 2)}</pre></details>`;
}

function render() {
  const root = document.querySelector("#app");
  const variantBody = state.variant === "A" ? renderVariantA() : state.variant === "B" ? renderVariantB() : renderVariantC();
  root.innerHTML = `<div class="app-shell">${renderTopbar()}${variantBody}</div>${renderPrototypeSwitcher()}${renderStateInspector()}<div class="toasts"></div>`;
  renderToasts();
  requestAnimationFrame(() => {
    document.querySelector(`tr[data-row-source="${state.selectedSourceId}"]`)?.scrollIntoView({ block: "nearest" });
  });
}

function setVariant(key) {
  if (!VARIANTS[key]) return;
  state.variant = key;
  const params = new URLSearchParams(location.search);
  params.set("variant", key);
  history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
  state.lastAction = `切换到 ${VARIANTS[key].label}；完整对齐与合并状态保持不变`;
  render();
}

document.addEventListener("click", (event) => {
  const variantButton = event.target.closest("[data-variant]");
  if (variantButton) return setVariant(variantButton.dataset.variant);
  const sourceButton = event.target.closest("[data-source-id]");
  if (sourceButton) {
    state.selectedSourceId = sourceButton.dataset.sourceId;
    state.lastAction = `已在同步视图中选择来源 ${sourceById(state.selectedSourceId)?.id}`;
    return render();
  }
  const filterButton = event.target.closest("[data-filter]");
  if (filterButton) { state.tableFilter = filterButton.dataset.filter; return render(); }
  const stepButton = event.target.closest("[data-step]");
  if (stepButton) { state.step = Number(stepButton.dataset.step); state.lastAction = `进入关卡 ${state.step}`; return render(); }
  const resolutionButton = event.target.closest("[data-resolution]");
  if (resolutionButton) {
    const [trackKey, sourceId, choice] = resolutionButton.dataset.resolution.split("|");
    return setResolution(trackKey, sourceId, choice);
  }
  const resolveAllButton = event.target.closest("[data-resolve-all]");
  if (resolveAllButton) {
    const [trackKey, choice] = resolveAllButton.dataset.resolveAll.split(":");
    return resolveAll(trackKey, choice);
  }
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action) return;
  if (action === "reset") return resetDraft();
  if (action === "insert-gap") return insertGapBefore(state.selectedSourceId);
  if (action === "gap-10") return insertGapBefore("pdb:A:10");
  if (action === "gap-21") return insertGapBefore("pdb:A:21");
  if (action === "move-interval") return moveInterval(state.moveStart, state.moveEnd, state.moveOffset);
  if (action === "review-alignment") return reviewAlignment();
  if (action === "attempt-preview") return buildMergePreview();
  if (action === "confirm-merge") return confirmMerge();
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-mapping-source]")) return setPreciseMapping(event.target.dataset.mappingSource, event.target.value);
  if (event.target.matches("[data-track]")) {
    const trackKey = event.target.dataset.track;
    state.includedTracks[trackKey] = event.target.checked;
    state.resolutions[trackKey] = {};
    state.mergePreview = false;
    state.mergeConfirmed = false;
    if (state.step > 3) state.step = 3;
    state.lastAction = `${trackKey === "sequence" ? "Sequence" : "Coordinates"} 来源轨道：${event.target.checked ? "采用并逐项处理" : "不采用，保留当前"}`;
    return render();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-field='move-start']")) state.moveStart = Number(event.target.value);
  if (event.target.matches("[data-field='move-end']")) state.moveEnd = Number(event.target.value);
  if (event.target.matches("[data-field='move-offset']")) state.moveOffset = Number(event.target.value);
});

document.addEventListener("keydown", (event) => {
  if (!SHOW_PROTOTYPE_CONTROLS || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  const targetElement = event.target;
  if (targetElement.matches("input, textarea, select, [contenteditable='true']")) return;
  const keys = Object.keys(VARIANTS);
  const current = keys.indexOf(state.variant);
  setVariant(keys[(current + (event.key === "ArrowRight" ? 1 : -1) + keys.length) % keys.length]);
});

render();
