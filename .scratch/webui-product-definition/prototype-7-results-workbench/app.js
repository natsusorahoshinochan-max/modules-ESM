// THROWAWAY UI PROTOTYPE — not production code.
// Three structurally different Results Workbench variants, switchable via
// ?variant= on one prototype route. The question: can a researcher identify
// exactly which Candidates are compared, where they came from, whether a
// filter changed the Workflow, and which Run an export belongs to?

const VARIANTS = {
  A: {
    label: "A · 候选账本（仅供比较）",
    name: "Candidate ledger",
    question: "让表格成为主索引，能否在高密度信息下保持当前 Candidate、勾选集合与来源清楚？",
  },
  B: {
    label: "B · 谱系工作台（已采用）",
    name: "Lineage workbench",
    question: "让父结构 → 子代序列 → 再折叠结构成为主轴，能否避免靠名称猜测亲子关系？",
  },
  C: {
    label: "C · 审阅篮（仅供比较）",
    name: "Review basket",
    question: "让比较与导出共享一个明确勾选集合，能否减少筛选、比较和导出对象之间的混淆？",
  },
};

const RUN = {
  id: "RUN-2026-08-30-017",
  short: "Run 017",
  workflowRevision: 11,
  finishedAt: "2026-08-30 14:26",
  outcome: "成功 · 6 个再次折叠结构 Candidates",
};

const CURRENT_WORKFLOW_REVISION = 12;
const ROOT_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG";

const CANDIDATES = [
  {
    id: "SF-STR-031",
    label: "Refolded structure 031",
    rootId: "E3-STR-007",
    sequenceId: "MPNN-SEQ-031",
    family: "P01",
    sequence: ROOT_SEQUENCE,
    changed: "A:18 V→I · A:42 Q→E（示意）",
    method: "SimpleFold Method（示意）",
    confidence: 0.91,
    solubility: 0.74,
    rmsd: 1.38,
    alignment: "SAE-P01",
    color: "#a8d968",
    shape: 0,
  },
  {
    id: "SF-STR-032",
    label: "Refolded structure 032",
    rootId: "E3-STR-007",
    sequenceId: "MPNN-SEQ-032",
    family: "P01",
    sequence: `${ROOT_SEQUENCE.slice(0, 25)}V${ROOT_SEQUENCE.slice(26, 56)}A${ROOT_SEQUENCE.slice(57)}`,
    changed: "A:26 K→V · A:57 T→A（示意）",
    method: "SimpleFold Method（示意）",
    confidence: 0.88,
    solubility: 0.79,
    rmsd: 1.72,
    alignment: "SAE-P01",
    color: "#6ed6c8",
    shape: 1,
  },
  {
    id: "SF-STR-033",
    label: "Refolded structure 033",
    rootId: "E3-STR-007",
    sequenceId: "MPNN-SEQ-033",
    family: "P01",
    sequence: `${ROOT_SEQUENCE.slice(0, 9)}A${ROOT_SEQUENCE.slice(10, 64)}M${ROOT_SEQUENCE.slice(65)}`,
    changed: "A:10 G→A · A:65 I→M（示意）",
    method: "SimpleFold Method（示意）",
    confidence: 0.84,
    solubility: 0.63,
    rmsd: 2.11,
    alignment: "SAE-P01",
    color: "#f0bd62",
    shape: 2,
  },
  {
    id: "SF-STR-044",
    label: "Refolded structure 044",
    rootId: "E3-STR-012",
    sequenceId: "MPNN-SEQ-044",
    family: "P02",
    sequence: `${ROOT_SEQUENCE.slice(0, 14)}M${ROOT_SEQUENCE.slice(15, 50)}V${ROOT_SEQUENCE.slice(51)}`,
    changed: "A:15 L→M · A:51 A→V（示意）",
    method: "ESMFold2 Method（示意）",
    confidence: 0.93,
    solubility: 0.68,
    rmsd: 1.24,
    alignment: "SAE-P02",
    color: "#9fa9ef",
    shape: 3,
  },
  {
    id: "SF-STR-045",
    label: "Refolded structure 045",
    rootId: "E3-STR-012",
    sequenceId: "MPNN-SEQ-045",
    family: "P02",
    sequence: `${ROOT_SEQUENCE.slice(0, 33)}N${ROOT_SEQUENCE.slice(34, 70)}K${ROOT_SEQUENCE.slice(71)}`,
    changed: "A:34 K→N · A:71 R→K（示意）",
    method: "ESMFold2 Method（示意）",
    confidence: 0.86,
    solubility: 0.71,
    rmsd: 1.89,
    alignment: "SAE-P02",
    color: "#d991cf",
    shape: 4,
  },
  {
    id: "SF-STR-052",
    label: "Refolded structure 052",
    rootId: "E3-STR-019",
    sequenceId: "MPNN-SEQ-052",
    family: "P03",
    sequence: `${ROOT_SEQUENCE.slice(0, 5)}Y${ROOT_SEQUENCE.slice(6, 45)}L${ROOT_SEQUENCE.slice(46)}`,
    changed: "A:6 K→Y · A:46 R→L（示意）",
    method: "SimpleFold Method（示意）",
    confidence: 0.77,
    solubility: 0.82,
    rmsd: 2.62,
    alignment: null,
    color: "#e58d7a",
    shape: 5,
  },
];

const LINEAGE = {
  P01: {
    parent: { id: "E3-STR-007", role: "父结构 Candidate", method: "ESM-3 structure generation（示意）", data: "ProteinStructure · 76 residues（示意）" },
    sequences: {
      "MPNN-SEQ-031": { id: "MPNN-SEQ-031", role: "子代序列 Candidate", method: "ProteinMPNN inverse folding（示意）", data: "ProteinSequence · 76 residues（示意）" },
      "MPNN-SEQ-032": { id: "MPNN-SEQ-032", role: "子代序列 Candidate", method: "ProteinMPNN inverse folding（示意）", data: "ProteinSequence · 76 residues（示意）" },
      "MPNN-SEQ-033": { id: "MPNN-SEQ-033", role: "子代序列 Candidate", method: "ProteinMPNN inverse folding（示意）", data: "ProteinSequence · 76 residues（示意）" },
    },
  },
  P02: {
    parent: { id: "E3-STR-012", role: "父结构 Candidate", method: "ESM-3 structure generation（示意）", data: "ProteinStructure · 76 residues（示意）" },
    sequences: {
      "MPNN-SEQ-044": { id: "MPNN-SEQ-044", role: "子代序列 Candidate", method: "ProteinMPNN inverse folding（示意）", data: "ProteinSequence · 76 residues（示意）" },
      "MPNN-SEQ-045": { id: "MPNN-SEQ-045", role: "子代序列 Candidate", method: "ProteinMPNN inverse folding（示意）", data: "ProteinSequence · 76 residues（示意）" },
    },
  },
  P03: {
    parent: { id: "E3-STR-019", role: "父结构 Candidate", method: "ESM-3 structure generation（示意）", data: "ProteinStructure · 76 residues（示意）" },
    sequences: {
      "MPNN-SEQ-052": { id: "MPNN-SEQ-052", role: "子代序列 Candidate", method: "ProteinMPNN inverse folding（示意）", data: "ProteinSequence · 76 residues（示意）" },
    },
  },
};

const initialVariant = new URLSearchParams(location.search).get("variant")?.toUpperCase();
const SHOW_PROTOTYPE_CONTROLS = location.protocol === "file:" || ["127.0.0.1", "localhost"].includes(location.hostname);

const state = {
  variant: VARIANTS[initialVariant] ? initialVariant : "B",
  focusId: "SF-STR-031",
  checkedIds: ["SF-STR-031"],
  compareMode: "single",
  lineageFocus: "SF-STR-031",
  filter: "all",
  search: "",
  sortKey: "confidence",
  sortDirection: "desc",
  saveFilterDialog: false,
  workflowFilterSaved: false,
  workflowRevision: CURRENT_WORKFLOW_REVISION,
  exportDialog: false,
  exportReceipt: null,
  provenanceDialog: false,
  lastAction: "已打开最近一次 Run 的 Results；当前 Workflow 已修改",
  toasts: [],
};

const candidateById = (id) => CANDIDATES.find((candidate) => candidate.id === id);
const focusedCandidate = () => candidateById(state.focusId) ?? CANDIDATES[0];
const checkedCandidates = () => state.checkedIds.map(candidateById).filter(Boolean);

function metricValue(candidate, key) {
  if (key === "id") return candidate.id;
  return candidate[key];
}

function visibleCandidates() {
  const needle = state.search.trim().toLowerCase();
  let rows = CANDIDATES.filter((candidate) => {
    if (needle && !`${candidate.id} ${candidate.rootId} ${candidate.sequenceId}`.toLowerCase().includes(needle)) return false;
    if (state.filter === "soluble" && candidate.solubility < 0.72) return false;
    if (state.filter === "p01" && candidate.family !== "P01") return false;
    if (state.filter === "aligned" && !candidate.alignment) return false;
    if (state.filter === "checked" && !state.checkedIds.includes(candidate.id)) return false;
    return true;
  });
  rows.sort((a, b) => {
    const left = metricValue(a, state.sortKey);
    const right = metricValue(b, state.sortKey);
    const result = typeof left === "string" ? left.localeCompare(right) : left - right;
    return state.sortDirection === "asc" ? result : -result;
  });
  return rows;
}

function hiddenCheckedCount() {
  const visible = new Set(visibleCandidates().map((candidate) => candidate.id));
  return state.checkedIds.filter((id) => !visible.has(id)).length;
}

function commonAlignment() {
  const selected = checkedCandidates();
  if (selected.length < 2) return null;
  const evidenceId = selected[0].alignment;
  if (!evidenceId || selected.some((candidate) => candidate.alignment !== evidenceId)) return null;
  return evidenceId;
}

function filterDescription() {
  if (state.filter === "soluble") return "示意 Solubility ≥ 0.72";
  if (state.filter === "p01") return "父结构 Candidate = E3-STR-007";
  if (state.filter === "aligned") return "已有 Structure Alignment Evidence";
  if (state.filter === "checked") return "只显示已勾选 Candidates";
  return "无条件（显示全部）";
}

function addToast(text, tone = "") {
  const id = `${Date.now()}-${Math.random()}`;
  state.toasts.push({ id, text, tone });
  setTimeout(() => {
    state.toasts = state.toasts.filter((toast) => toast.id !== id);
    renderToasts();
  }, 3400);
}

function renderToasts() {
  const root = document.querySelector(".toasts");
  if (!root) return;
  root.innerHTML = state.toasts.map((toast) => `<div class="toast ${toast.tone}">${toast.text}</div>`).join("");
}

function record(text) {
  state.lastAction = text;
}

function setFocus(candidateId) {
  const candidate = candidateById(candidateId);
  if (!candidate) return;
  state.focusId = candidateId;
  state.lineageFocus = candidateId;
  record(`当前焦点 Candidate：${candidateId}`);
  render();
}

function toggleChecked(candidateId) {
  if (state.checkedIds.includes(candidateId)) {
    state.checkedIds = state.checkedIds.filter((id) => id !== candidateId);
    record(`已从比较 / 导出集合移除 ${candidateId}`);
  } else {
    state.checkedIds = [...state.checkedIds, candidateId];
    record(`已勾选 ${candidateId}；比较与导出使用同一明确集合`);
  }
  if (state.compareMode === "overlay" && !commonAlignment()) {
    state.compareMode = state.checkedIds.length >= 2 ? "side" : "single";
    addToast("勾选集合已改变，原叠加证据不再覆盖全部 Candidate", "warn");
  }
  render();
}

function setCompareMode(mode) {
  if (mode === "single") {
    state.compareMode = mode;
    record(`单候选查看：${state.focusId}`);
    render();
    return;
  }
  if (state.checkedIds.length < 2) {
    addToast("请先勾选至少两个 Candidates", "warn");
    return;
  }
  if (mode === "overlay" && !commonAlignment()) {
    addToast("当前勾选集合没有共同的已有 Structure Alignment Evidence；不能叠加", "danger");
    return;
  }
  state.compareMode = mode;
  record(mode === "side" ? `并排比较 ${state.checkedIds.length} 个 Candidates` : `使用 ${commonAlignment()} 叠加 ${state.checkedIds.length} 个 Candidates`);
  render();
}

function setFilter(value) {
  state.filter = value;
  record(`临时表格筛选：${filterDescription()}；Workflow 未改变`);
  render();
}

function setSort(key) {
  if (state.sortKey === key) state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  else {
    state.sortKey = key;
    state.sortDirection = key === "id" ? "asc" : "desc";
  }
  record(`当前视图按 ${key} ${state.sortDirection === "asc" ? "升序" : "降序"}排列；Workflow 未改变`);
  render();
}

function setSearch(value) {
  state.search = value;
  record(`当前视图搜索：${value || "清空"}；Workflow 未改变`);
  render();
}

function openSaveFilter() {
  if (state.filter === "all") {
    addToast("当前没有临时筛选条件可保存", "warn");
    return;
  }
  state.saveFilterDialog = true;
  record("正在核对：把临时条件保存为 Workflow 筛选 Node Instance");
  render();
}

function confirmSaveFilter() {
  state.saveFilterDialog = false;
  state.workflowFilterSaved = true;
  state.workflowRevision += 1;
  record(`已新增可编辑筛选 Node Instance · Workflow v${state.workflowRevision}；当前 Results 仍来自 Workflow v${RUN.workflowRevision}`);
  addToast("Workflow 已改变；当前旧 Results 未重算", "success");
  render();
}

function openExport() {
  if (!state.checkedIds.length) {
    addToast("请先勾选至少一个 Candidate", "warn");
    return;
  }
  state.exportDialog = true;
  record(`正在核对 ${state.checkedIds.length} 个 Candidates 的固定 ZIP 与 Run 来源`);
  render();
}

function confirmExport() {
  state.exportDialog = false;
  state.exportReceipt = {
    filename: `protein-workbench_run-017_${state.checkedIds.length}-candidates.zip`,
    ids: [...state.checkedIds],
    runId: RUN.id,
    workflowRevision: RUN.workflowRevision,
  };
  record(`已模拟导出 ${state.exportReceipt.filename}；来源 ${RUN.short} / Workflow v${RUN.workflowRevision}`);
  addToast("固定 ZIP 已模拟生成；来源记录随包保存", "success");
  render();
}

function setLineageFocus(id) {
  state.lineageFocus = id;
  record(`谱系焦点：${id}`);
  render();
}

function showProvenance() {
  state.provenanceDialog = true;
  record(`查看 ${RUN.id} 与 Workflow revision 来源`);
  render();
}

function closeDialogs() {
  state.saveFilterDialog = false;
  state.exportDialog = false;
  state.provenanceDialog = false;
  render();
}

function resetPrototype() {
  state.focusId = "SF-STR-031";
  state.checkedIds = ["SF-STR-031"];
  state.compareMode = "single";
  state.lineageFocus = "SF-STR-031";
  state.filter = "all";
  state.search = "";
  state.sortKey = "confidence";
  state.sortDirection = "desc";
  state.saveFilterDialog = false;
  state.workflowFilterSaved = false;
  state.workflowRevision = CURRENT_WORKFLOW_REVISION;
  state.exportDialog = false;
  state.exportReceipt = null;
  state.provenanceDialog = false;
  record("已重置内存状态；Results 仍来自修改前 Workflow");
  render();
}

function switchVariant(offset) {
  const keys = Object.keys(VARIANTS);
  const index = keys.indexOf(state.variant);
  state.variant = keys[(index + offset + keys.length) % keys.length];
  const url = new URL(location.href);
  url.searchParams.set("variant", state.variant);
  history.replaceState({}, "", url);
  record(`已切换到 ${VARIANTS[state.variant].label}；完整状态保持`);
  render();
}

function statusPill(text, tone = "") {
  return `<span class="status-pill ${tone}">${text}</span>`;
}

function structureSvg(candidate, compact = false) {
  const paths = [
    "M28 99 C40 22 78 32 96 82 S155 132 178 72 S224 22 246 83 S282 132 304 54",
    "M31 82 C58 137 83 125 104 59 S151 20 167 90 S213 139 244 68 S284 35 308 101",
    "M27 108 C53 58 83 37 113 87 S164 129 189 62 S236 30 254 93 S290 119 309 70",
    "M25 74 C55 20 89 48 105 104 S158 136 184 70 S229 22 251 76 S284 133 310 90",
    "M25 96 C46 136 87 114 103 53 S151 24 173 82 S219 138 243 78 S284 29 310 61",
    "M27 65 C52 121 83 135 110 68 S161 34 184 98 S226 122 250 58 S289 46 310 110",
  ];
  const path = paths[candidate.shape % paths.length];
  return `<svg class="structure-svg ${compact ? "compact" : ""}" viewBox="0 0 336 160" role="img" aria-label="${candidate.id} 的结构几何示意">
    <defs>
      <linearGradient id="g-${candidate.id}" x1="0" x2="1"><stop stop-color="${candidate.color}"/><stop offset="1" stop-color="#e7f2e9"/></linearGradient>
      <filter id="glow-${candidate.id}"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <g opacity=".18" stroke="#7f9489" stroke-width="1"><path d="M16 136H320"/><path d="M32 20V142"/><path d="M96 20V142"/><path d="M160 20V142"/><path d="M224 20V142"/><path d="M288 20V142"/></g>
    <path d="${path}" fill="none" stroke="url(#g-${candidate.id})" stroke-width="11" stroke-linecap="round" filter="url(#glow-${candidate.id})"/>
    <path d="${path}" fill="none" stroke="#f4fff7" stroke-opacity=".5" stroke-width="2" stroke-linecap="round"/>
    <circle cx="28" cy="99" r="4" fill="${candidate.color}"/><circle cx="304" cy="54" r="4" fill="#e9f2e9"/>
  </svg>`;
}

function overlaySvg(candidates) {
  const paths = [
    "M28 99 C40 22 78 32 96 82 S155 132 178 72 S224 22 246 83 S282 132 304 54",
    "M31 82 C58 137 83 125 104 59 S151 20 167 90 S213 139 244 68 S284 35 308 101",
    "M27 108 C53 58 83 37 113 87 S164 129 189 62 S236 30 254 93 S290 119 309 70",
  ];
  return `<svg class="structure-svg overlay-svg" viewBox="0 0 336 160" role="img" aria-label="已有结构对齐结果叠加示意">
    <g opacity=".18" stroke="#7f9489"><path d="M16 136H320"/><path d="M32 20V142"/><path d="M96 20V142"/><path d="M160 20V142"/><path d="M224 20V142"/><path d="M288 20V142"/></g>
    ${candidates.map((candidate, index) => `<path d="${paths[index % paths.length]}" transform="translate(${index * 1.5} ${index * -1.5})" fill="none" stroke="${candidate.color}" stroke-width="8" stroke-opacity=".7" stroke-linecap="round"/>`).join("")}
  </svg>`;
}

function metricStrip(candidate) {
  return `<div class="metric-strip">
    <div><span>Confidence</span><strong>${candidate.confidence.toFixed(2)}</strong><small>Score Observation · 示意</small></div>
    <div><span>Solubility</span><strong>${candidate.solubility.toFixed(2)}</strong><small>Score Observation · 示意</small></div>
    <div><span>RMSD to parent</span><strong>${candidate.rmsd.toFixed(2)} Å</strong><small>Metric / Method · 示意</small></div>
  </div>`;
}

function selectionSummary() {
  const hidden = hiddenCheckedCount();
  return `<div class="selection-summary ${hidden ? "warn" : ""}">
    <div><span>比较 / 导出集合</span><strong>${state.checkedIds.length} 个 Candidates</strong><small>${state.checkedIds.length ? state.checkedIds.join(" · ") : "尚未勾选"}</small></div>
    ${hidden ? `<b>${hidden} 个已勾选 Candidate 被当前临时筛选隐藏；仍保留在集合中</b>` : `<b>当前视图未隐藏已勾选 Candidate</b>`}
  </div>`;
}

function filterControls(compact = false) {
  return `<div class="filter-controls ${compact ? "compact" : ""}">
    <label class="search-field"><span>搜索身份 / 来源</span><input value="${state.search}" oninput="setSearch(this.value)" placeholder="Candidate ID…" /></label>
    <label><span>临时筛选</span><select onchange="setFilter(this.value)">
      <option value="all" ${state.filter === "all" ? "selected" : ""}>全部 Candidates</option>
      <option value="soluble" ${state.filter === "soluble" ? "selected" : ""}>示意 Solubility ≥ 0.72</option>
      <option value="p01" ${state.filter === "p01" ? "selected" : ""}>父结构 E3-STR-007</option>
      <option value="aligned" ${state.filter === "aligned" ? "selected" : ""}>已有 Structure Alignment Evidence</option>
      <option value="checked" ${state.filter === "checked" ? "selected" : ""}>只显示已勾选</option>
    </select></label>
    <div class="view-scope"><span>作用域</span><b>仅当前视图</b><small>排序与筛选没有修改 Workflow</small></div>
    <button class="button ${state.filter === "all" ? "" : "accent"}" onclick="openSaveFilter()" ${state.filter === "all" ? "disabled" : ""}>保存为流程筛选</button>
  </div>`;
}

function candidateTable(compact = false) {
  const rows = visibleCandidates();
  const sortMark = (key) => state.sortKey === key ? (state.sortDirection === "asc" ? " ↑" : " ↓") : "";
  return `<div class="table-wrap ${compact ? "compact" : ""}">
    <table>
      <thead><tr>
        <th class="check-col"><span title="比较与导出使用同一勾选集合">勾选</span></th>
        <th><button onclick="setSort('id')">Candidate${sortMark("id")}</button></th>
        <th>来源关系</th>
        <th><button onclick="setSort('confidence')">Confidence（示意）${sortMark("confidence")}</button></th>
        <th><button onclick="setSort('solubility')">Solubility（示意）${sortMark("solubility")}</button></th>
        <th><button onclick="setSort('rmsd')">RMSD Å（示意）${sortMark("rmsd")}</button></th>
        <th>对齐证据</th>
      </tr></thead>
      <tbody>${rows.map((candidate) => `<tr class="${candidate.id === state.focusId ? "focused" : ""} ${state.checkedIds.includes(candidate.id) ? "checked" : ""}">
        <td class="check-col"><input type="checkbox" aria-label="勾选 ${candidate.id}" ${state.checkedIds.includes(candidate.id) ? "checked" : ""} onchange="toggleChecked('${candidate.id}')" /></td>
        <td><button class="candidate-link" onclick="setFocus('${candidate.id}')"><b>${candidate.id}</b><small>${candidate.label}</small></button></td>
        <td><span class="lineage-mini">${candidate.rootId}</span><small>↳ ${candidate.sequenceId}</small></td>
        <td><strong>${candidate.confidence.toFixed(2)}</strong></td>
        <td><strong>${candidate.solubility.toFixed(2)}</strong></td>
        <td><strong>${candidate.rmsd.toFixed(2)}</strong></td>
        <td>${candidate.alignment ? statusPill(candidate.alignment, "evidence") : statusPill("无", "muted")}</td>
      </tr>`).join("")}</tbody>
    </table>
    ${rows.length ? "" : `<div class="empty-table">当前临时筛选没有可见 Candidate；Workflow 与已勾选集合均未改变。</div>`}
  </div>`;
}

function compareToolbar() {
  return `<div class="compare-toolbar">
    <div class="segmented">
      <button class="${state.compareMode === "single" ? "active" : ""}" onclick="setCompareMode('single')">单候选</button>
      <button class="${state.compareMode === "side" ? "active" : ""}" onclick="setCompareMode('side')">并排比较</button>
      <button class="${state.compareMode === "overlay" ? "active" : ""}" onclick="setCompareMode('overlay')">已有对齐结果叠加</button>
    </div>
    <span>${state.compareMode === "single" ? `焦点 · ${state.focusId}` : `勾选集合 · ${state.checkedIds.length} 个`}</span>
  </div>`;
}

function compareStage() {
  const focus = focusedCandidate();
  const selected = checkedCandidates();
  if (state.compareMode === "single") {
    return `<div class="compare-stage single-stage">
      <div class="viewer-heading"><div><span>单候选结构</span><h2>${focus.id}</h2><p>${focus.label} · ${focus.method}</p></div>${statusPill("结构几何示意", "illustrative")}</div>
      <div class="structure-canvas">${structureSvg(focus)}<div class="viewer-tools"><button>旋转</button><button>居中</button><button>表面</button><small>仅查看器操作 · 示意</small></div></div>
      ${metricStrip(focus)}
    </div>`;
  }
  if (state.compareMode === "overlay") {
    const evidence = commonAlignment();
    return `<div class="compare-stage overlay-stage">
      <div class="viewer-heading"><div><span>使用已有结构对齐结果叠加</span><h2>${evidence}</h2><p>${selected.map((candidate) => candidate.id).join(" · ")}</p></div>${statusPill("Workflow 已产生", "evidence")}</div>
      <div class="overlay-canvas">${overlaySvg(selected)}<div class="overlay-legend">${selected.map((candidate) => `<span><i style="background:${candidate.color}"></i>${candidate.id}</span>`).join("")}</div></div>
      <div class="evidence-note"><b>这是已有 Structure Alignment Evidence 的查看结果</b><span>对齐身份、残基轴对应、transform 与 Method 随 ${evidence} 记录（内容示意）。当前视图没有发起新的对齐计算。</span></div>
    </div>`;
  }
  return `<div class="compare-stage side-stage">
    <div class="viewer-heading"><div><span>并排比较 · 不执行结构叠加</span><h2>${selected.length} 个 Candidates</h2><p>${selected.map((candidate) => candidate.id).join(" · ")}</p></div>${statusPill("布局比较", "muted")}</div>
    <div class="side-scroll">${selected.map((candidate) => `<article class="mini-viewer"><header><b>${candidate.id}</b><span style="background:${candidate.color}"></span></header>${structureSvg(candidate, true)}<dl><div><dt>Confidence</dt><dd>${candidate.confidence.toFixed(2)}（示意）</dd></div><div><dt>Solubility</dt><dd>${candidate.solubility.toFixed(2)}（示意）</dd></div><div><dt>RMSD</dt><dd>${candidate.rmsd.toFixed(2)} Å（示意）</dd></div></dl></article>`).join("")}</div>
  </div>`;
}

function lineageNodes(candidate = focusedCandidate(), horizontal = false) {
  const family = LINEAGE[candidate.family];
  const parent = family.parent;
  const sequence = family.sequences[candidate.sequenceId];
  const nodes = [
    { ...parent, tone: "parent" },
    { ...sequence, tone: "sequence" },
    { id: candidate.id, role: "再次折叠结构 Candidate", method: candidate.method, data: "ProteinStructure · PDB available（示意）", tone: "refold" },
  ];
  return `<div class="lineage-chain ${horizontal ? "horizontal" : ""}">
    ${nodes.map((node, index) => `${index ? `<div class="lineage-arrow"><span>${index === 1 ? "ProteinMPNN" : candidate.method.split(" ")[0]}</span><b>→</b><small>Method · 示意</small></div>` : ""}<button class="lineage-node ${node.tone} ${state.lineageFocus === node.id ? "active" : ""}" onclick="setLineageFocus('${node.id}')"><span>${node.role}</span><strong>${node.id}</strong><small>${node.data}</small></button>`).join("")}
  </div>`;
}

function lineageFocusDetails() {
  const candidate = focusedCandidate();
  const family = LINEAGE[candidate.family];
  let item;
  if (state.lineageFocus === family.parent.id) item = family.parent;
  else if (state.lineageFocus === candidate.sequenceId) item = family.sequences[candidate.sequenceId];
  else item = { id: candidate.id, role: "再次折叠结构 Candidate", method: candidate.method, data: "ProteinStructure · PDB available（示意）" };
  return `<div class="lineage-focus"><span>谱系焦点</span><h3>${item.id}</h3><b>${item.role}</b><p>${item.method}</p><small>${item.data}</small></div>`;
}

function sequencePanel(candidate = focusedCandidate()) {
  const chunks = candidate.sequence.match(/.{1,10}/g) ?? [];
  return `<div class="sequence-panel"><div class="surface-title"><div><span>当前 Candidate sequence</span><h3>${candidate.id} · Chain A</h3></div>${statusPill("76 residues · 示意", "illustrative")}</div><div class="sequence-text">${chunks.map((chunk, index) => `<span><small>${index * 10 + 1}</small>${chunk}</span>`).join("")}</div><p>${candidate.changed}</p></div>`;
}

function sourceDossier(candidate = focusedCandidate()) {
  return `<div class="source-dossier">
    <div class="surface-title"><div><span>Candidate 身份与来源</span><h3>${candidate.id}</h3></div>${statusPill(candidate.family, "family")}</div>
    <dl>
      <div><dt>数据</dt><dd>ProteinStructure · PDB available（示意）</dd></div>
      <div><dt>父结构</dt><dd>${candidate.rootId}</dd></div>
      <div><dt>直接来源</dt><dd>${candidate.sequenceId}</dd></div>
      <div><dt>生成 Method</dt><dd>${candidate.method}</dd></div>
      <div><dt>Run</dt><dd>${RUN.id}</dd></div>
      <div><dt>Workflow</dt><dd>v${RUN.workflowRevision} · 当前为 v${state.workflowRevision}</dd></div>
    </dl>
  </div>`;
}

function runBanner() {
  return `<div class="stale-banner">
    <div><span>来自修改前的流程</span><strong>当前 Results = ${RUN.short} · Workflow v${RUN.workflowRevision}</strong><small>当前 Workflow 已是 v${state.workflowRevision}；仍可查看、比较、临时筛选与导出旧 Results。</small></div>
    <button onclick="showProvenance()">查看 Run 来源</button>
  </div>`;
}

function actionBar() {
  return `<div class="action-bar">
    <div><span>已勾选</span><strong>${state.checkedIds.length}</strong><small>${hiddenCheckedCount() ? `${hiddenCheckedCount()} 个被当前筛选隐藏` : "全部在当前视图可见"}</small></div>
    <button class="button" onclick="setCompareMode('side')">并排比较</button>
    <button class="button" onclick="setCompareMode('overlay')">已有对齐结果叠加</button>
    <button class="button primary" onclick="openExport()">导出固定 ZIP</button>
  </div>`;
}

function workflowFilterCard() {
  if (!state.workflowFilterSaved) return "";
  return `<div class="workflow-filter-card"><span>Workflow 已新增</span><strong>筛选候选 · Node Instance（示意）</strong><small>${filterDescription()} · 可回到画布继续编辑 · 尚未重新运行</small></div>`;
}

function renderVariantA() {
  return `<main class="workspace variant-a">
    <section class="surface candidate-ledger">
      <div class="surface-header"><div><span>Results index</span><h1>候选账本</h1></div><div><b>${visibleCandidates().length} / ${CANDIDATES.length}</b><small>当前可见 / Run 中全部</small></div></div>
      ${filterControls()}
      ${selectionSummary()}
      ${candidateTable()}
    </section>
    <section class="right-workbench">
      <div class="surface compare-surface">${compareToolbar()}${compareStage()}</div>
      <div class="detail-grid">
        <section class="surface lineage-surface"><div class="surface-header"><div><span>Lineage</span><h2>父子来源</h2></div><small>点击角色查看</small></div>${lineageNodes()}${lineageFocusDetails()}</section>
        <section class="surface dossier-surface">${sourceDossier()}${sequencePanel()}${workflowFilterCard()}</section>
      </div>
    </section>
  </main>`;
}

function familyRail() {
  return `<aside class="surface family-rail"><div class="surface-header"><div><span>Lineage families</span><h2>父结构家族</h2></div></div>${Object.entries(LINEAGE).map(([familyId, family]) => {
    const members = CANDIDATES.filter((candidate) => candidate.family === familyId);
    const active = focusedCandidate().family === familyId;
    return `<button class="family-card ${active ? "active" : ""}" onclick="setFocus('${members[0].id}')"><span>${familyId} · ${members.length} 个再折叠结构</span><strong>${family.parent.id}</strong><small>ESM-3 父结构 Candidate（示意）</small></button>`;
  }).join("")}</aside>`;
}

function renderVariantB() {
  return `<main class="workspace variant-b">
    ${familyRail()}
    <section class="surface lineage-main">
      <div class="surface-header"><div><span>Scientific lineage first</span><h1>${focusedCandidate().rootId} 的设计谱系</h1></div>${statusPill(`焦点 ${state.focusId}`, "focus")}</div>
      ${lineageNodes(focusedCandidate(), true)}
      <div class="lineage-main-grid"><div class="surface inset">${compareToolbar()}${compareStage()}</div><div class="lineage-evidence">${lineageFocusDetails()}${sourceDossier()}</div></div>
    </section>
    <aside class="surface family-actions">${selectionSummary()}${sequencePanel()}${workflowFilterCard()}<div class="mini-action-stack"><button class="button" onclick="setCompareMode('side')">并排勾选集合</button><button class="button" onclick="setCompareMode('overlay')">叠加已有对齐结果</button><button class="button primary" onclick="openExport()">导出固定 ZIP</button></div></aside>
    <section class="surface bottom-ledger"><div class="bottom-filter">${filterControls(true)}</div>${candidateTable(true)}</section>
  </main>`;
}

function basketItems() {
  const items = checkedCandidates();
  return `<div class="basket-items">${items.length ? items.map((candidate, index) => `<article class="basket-item ${candidate.id === state.focusId ? "focused" : ""}"><span>${String(index + 1).padStart(2, "0")}</span><button onclick="setFocus('${candidate.id}')"><b>${candidate.id}</b><small>${candidate.rootId} → ${candidate.sequenceId}</small></button><button class="remove" onclick="toggleChecked('${candidate.id}')" title="从篮中移除">×</button></article>`).join("") : `<div class="empty-basket">从候选列表勾选要比较与导出的 Candidate。</div>`}</div>`;
}

function candidateCards() {
  return `<div class="candidate-card-list">${visibleCandidates().map((candidate) => `<article class="candidate-card ${candidate.id === state.focusId ? "focused" : ""}"><label><input type="checkbox" aria-label="勾选 ${candidate.id}" ${state.checkedIds.includes(candidate.id) ? "checked" : ""} onchange="toggleChecked('${candidate.id}')" /><span>加入审阅篮</span></label><button onclick="setFocus('${candidate.id}')"><strong>${candidate.id}</strong><small>${candidate.rootId} → ${candidate.sequenceId}</small><b>${candidate.confidence.toFixed(2)} · ${candidate.solubility.toFixed(2)} · ${candidate.rmsd.toFixed(2)} Å</b></button></article>`).join("")}</div>`;
}

function renderVariantC() {
  return `<main class="workspace variant-c">
    <aside class="surface candidate-queue"><div class="surface-header"><div><span>Candidate queue</span><h1>候选与临时视图</h1></div><b>${visibleCandidates().length}/${CANDIDATES.length}</b></div>${filterControls(true)}${candidateCards()}</aside>
    <section class="surface review-stage"><div class="surface-header"><div><span>Review basket</span><h1>比较工作台</h1></div>${statusPill(`${state.checkedIds.length} 个已勾选`, "focus")}</div>${compareToolbar()}${compareStage()}${lineageNodes(focusedCandidate(), true)}</section>
    <aside class="surface review-basket"><div class="surface-header"><div><span>One explicit set</span><h2>比较 / 导出篮</h2></div></div>${basketItems()}${selectionSummary()}<div class="basket-modes"><button class="button" onclick="setCompareMode('side')">并排</button><button class="button" onclick="setCompareMode('overlay')">已有对齐结果叠加</button></div><button class="button primary wide" onclick="openExport()">导出篮中固定 ZIP</button>${workflowFilterCard()}</aside>
    <section class="surface review-evidence"><div class="evidence-columns">${sourceDossier()}${sequencePanel()}<div class="lineage-evidence compact">${lineageFocusDetails()}<div class="view-only"><span>临时筛选</span><strong>${filterDescription()}</strong><small>Workflow ${state.workflowFilterSaved ? `已因明确保存而变为 v${state.workflowRevision}` : "未改变"}</small><button class="button" onclick="openSaveFilter()" ${state.filter === "all" ? "disabled" : ""}>保存为流程筛选</button></div></div></div></section>
  </main>`;
}

function saveFilterModal() {
  if (!state.saveFilterDialog) return "";
  return `<div class="modal-backdrop" onclick="if(event.target===this) closeDialogs()"><section class="modal-card filter-modal">
    <div class="modal-heading"><div><span>明确改变 Workflow</span><h2>保存为流程筛选？</h2><p>当前表格视图不会被整体保存；只把下列示意条件建立为可编辑筛选 Node Instance。</p></div><button class="icon-button" onclick="closeDialogs()">×</button></div>
    <div class="scope-contrast"><article><span>现在 · 临时视图</span><strong>${filterDescription()}</strong><small>只影响 ${visibleCandidates().length} 行的显示；排序 ${state.sortKey} / ${state.sortDirection} 仍只是视图。</small></article><b>→</b><article class="workflow"><span>确认后 · Workflow v${state.workflowRevision + 1}</span><strong>新增“筛选候选”Node Instance（示意）</strong><small>条件：${filterDescription()}。节点可编辑；不会重算当前 ${RUN.short}。</small></article></div>
    <div class="old-result-warning"><b>当前 Results 不会改变</b><span>它们继续来自 ${RUN.id} / Workflow v${RUN.workflowRevision}，直到下一次 Run 产生新结果。</span></div>
    <div class="modal-actions"><button class="button" onclick="closeDialogs()">取消</button><button class="button primary" onclick="confirmSaveFilter()">确认新增流程筛选</button></div>
  </section></div>`;
}

function exportModal() {
  if (!state.exportDialog) return "";
  return `<div class="modal-backdrop" onclick="if(event.target===this) closeDialogs()"><section class="modal-card export-modal">
    <div class="modal-heading"><div><span>固定 ZIP · 无格式选择</span><h2>导出 ${state.checkedIds.length} 个 Candidates</h2><p>${state.checkedIds.join(" · ")}</p></div><button class="icon-button" onclick="closeDialogs()">×</button></div>
    <div class="export-origin"><span>导出来源</span><strong>${RUN.id}</strong><b>Workflow v${RUN.workflowRevision} · 来自修改前的流程</b><small>当前 Workflow 为 v${state.workflowRevision}；导出说明文件会记录这个差异。</small></div>
    <div class="zip-contents"><article><b>PDB/</b><span>每个勾选 Candidate 的 PDB 结构（示意）</span></article><article><b>sequences.fasta</b><span>所有勾选 Candidates 的序列</span></article><article><b>scores.csv</b><span>Score Observations 与 Metric / Method 信息（示意）</span></article><article><b>README.txt</b><span>Candidate 身份、父子来源、Method、Run 与 Workflow revision</span></article></div>
    <p class="modal-note">临时筛选不需要先保存回 Workflow，也不要求重新运行；ZIP 只包含当前明确勾选集合。</p>
    <div class="modal-actions"><button class="button" onclick="closeDialogs()">取消</button><button class="button primary" onclick="confirmExport()">确认模拟导出固定 ZIP</button></div>
  </section></div>`;
}

function provenanceModal() {
  if (!state.provenanceDialog) return "";
  return `<div class="modal-backdrop" onclick="if(event.target===this) closeDialogs()"><section class="modal-card provenance-modal">
    <div class="modal-heading"><div><span>Results provenance</span><h2>${RUN.id}</h2><p>项目只向用户显示最近一次 Run；这里没有历史 Run 列表。</p></div><button class="icon-button" onclick="closeDialogs()">×</button></div>
    <dl><div><dt>结束</dt><dd>${RUN.finishedAt}</dd></div><div><dt>结果</dt><dd>${RUN.outcome}</dd></div><div><dt>使用的 Workflow</dt><dd>Workflow v${RUN.workflowRevision}</dd></div><div><dt>当前 Workflow</dt><dd>Workflow v${state.workflowRevision}</dd></div><div><dt>差异状态</dt><dd>来自修改前的流程 · 仍允许查看、比较、筛选和导出</dd></div></dl>
    <div class="modal-actions"><button class="button primary" onclick="closeDialogs()">返回 Results</button></div>
  </section></div>`;
}

function exportReceipt() {
  if (!state.exportReceipt) return "";
  return `<div class="export-receipt"><button onclick="state.exportReceipt=null;render()">×</button><span>最近模拟导出</span><strong>${state.exportReceipt.filename}</strong><small>${state.exportReceipt.runId} · Workflow v${state.exportReceipt.workflowRevision} · ${state.exportReceipt.ids.join(" / ")}</small></div>`;
}

function prototypeSwitcher() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  const variant = VARIANTS[state.variant];
  return `<div class="prototype-switcher"><button onclick="switchVariant(-1)" aria-label="上一个方案">←</button><div><span>THROWAWAY PROTOTYPE 7 · ?variant=${state.variant}</span><strong>${variant.label} · ${variant.name}</strong><small>${variant.question}</small></div><button onclick="switchVariant(1)" aria-label="下一个方案">→</button></div>
    <details class="state-inspector"><summary>原型状态 · ${state.lastAction}</summary><pre>${JSON.stringify({ variant: state.variant, focusCandidate: state.focusId, checkedCandidates: state.checkedIds, compareMode: state.compareMode, commonAlignmentEvidence: commonAlignment(), lineageFocus: state.lineageFocus, currentView: { filter: filterDescription(), search: state.search, sort: `${state.sortKey}:${state.sortDirection}`, visibleCandidateIds: visibleCandidates().map((candidate) => candidate.id), hiddenChecked: hiddenCheckedCount() }, workflow: { currentRevision: state.workflowRevision, filterNodeSaved: state.workflowFilterSaved }, results: { runId: RUN.id, workflowRevision: RUN.workflowRevision, stale: true }, exportReceipt: state.exportReceipt, lastAction: state.lastAction }, null, 2)}</pre></details>`;
}

function render() {
  const root = document.getElementById("app");
  const variantContent = state.variant === "A" ? renderVariantA() : state.variant === "B" ? renderVariantB() : renderVariantC();
  root.innerHTML = `<div class="app-shell">
    <header class="topbar"><div class="brand"><div class="brand-mark">PW</div><div><b>Protein Workbench</b><small>Results Workbench · 原型 7</small></div></div><div class="project"><span>项目 · Ubiquitin-like inverse-fold study（示意）</span><strong>当前 Workflow v${state.workflowRevision}</strong></div><div class="top-actions"><span class="prototype-badge">一次性原型</span><button class="button" onclick="resetPrototype()">重置原型</button><button class="button" onclick="showProvenance()">${RUN.short}</button></div></header>
    ${runBanner()}
    <div class="question-bar"><span>唯一产品问题</span><strong>能否准确识别比较对象、Candidate 来源、筛选作用域和导出 Run 归属？</strong><small>第 5 节 · 数据与 Metric 均为示意</small></div>
    ${variantContent}
    ${actionBar()}
    ${prototypeSwitcher()}
    ${saveFilterModal()}${exportModal()}${provenanceModal()}${exportReceipt()}
    <div class="toasts"></div>
  </div>`;
}

document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && (target.matches("input, textarea, select") || target.isContentEditable)) return;
  if (event.key === "ArrowLeft") switchVariant(-1);
  if (event.key === "ArrowRight") switchVariant(1);
  if (event.key === "Escape" && (state.saveFilterDialog || state.exportDialog || state.provenanceDialog)) closeDialogs();
});

render();
