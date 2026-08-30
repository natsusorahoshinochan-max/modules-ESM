// THROWAWAY UI PROTOTYPE — not production code.
// Three structurally different project/versioning variants, switchable via
// ?variant= on one prototype route. The question: does a researcher always
// know which project is being edited, what is saved, and what copy, version
// branching, and restore will produce?

const VARIANTS = {
  A: {
    label: "A · 上下文画布",
    name: "Context canvas",
    question: "把项目身份和保存状态固定在 Workflow 周围，是否足以消除对象与保存边界的混淆？",
  },
  B: {
    label: "B · 版本时间线",
    name: "Version timeline",
    question: "把命名版本与分支来源做成主轴，是否能让旧版本继续修改的结果一眼可见？",
  },
  C: {
    label: "C · 实验项目库",
    name: "Experiment library",
    question: "让项目、Workflow 和保存边界三列常驻，是否更适合频繁搜索、复制、删除和恢复？",
  },
};

const DEFAULT_WORKSPACE = {
  revision: 1,
  nodeCount: 5,
  generationSteps: 80,
  promptRevision: 1,
  promptSummary: "链 A · 76 residues · coordinates 72/76（全部示意）",
  canvasLayout: "空间画布 · 5 个 Node Instances",
  updatedAt: "干净默认值",
};

const DEFAULT_TEMPLATE = {
  id: "DEFAULT-ESM3",
  name: "默认示例 · ESM-3 ProteinPrompt 设计",
  description: "PDB → 编写 ProteinPrompt → ESM-3 生成 → 评分 → 筛选",
};

const sampleProjects = [
  {
    id: "PRJ-019",
    name: "抗体 CDR 条件生成",
    updatedAt: "今天 14:18",
    current: {
      revision: 8,
      nodeCount: 7,
      generationSteps: 64,
      promptRevision: 4,
      promptSummary: "链 H/L · 228 residues · coordinates 211/228（全部示意）",
      canvasLayout: "空间画布 · 7 个 Node Instances",
      updatedAt: "今天 14:18",
    },
    versions: [
      {
        id: "VER-019-01",
        name: "第一次生成参数",
        createdAt: "08-28 17:42",
        snapshot: {
          revision: 4,
          nodeCount: 6,
          generationSteps: 40,
          promptRevision: 2,
          promptSummary: "链 H/L · 228 residues · coordinates 211/228（全部示意）",
          canvasLayout: "空间画布 · 6 个 Node Instances",
          updatedAt: "命名版本 · 08-28 17:42",
        },
      },
      {
        id: "VER-019-02",
        name: "调整 Prompt 后",
        createdAt: "08-29 11:06",
        snapshot: {
          revision: 6,
          nodeCount: 7,
          generationSteps: 60,
          promptRevision: 3,
          promptSummary: "链 H/L · 228 residues · coordinates 205/228（全部示意）",
          canvasLayout: "空间画布 · 7 个 Node Instances",
          updatedAt: "命名版本 · 08-29 11:06",
        },
      },
    ],
    retainedHeads: [],
    currentOrigin: null,
    latestRun: {
      id: "RUN-019-08",
      workflowRevision: 8,
      summary: "12 Candidates · 已完成（示意）",
    },
  },
  {
    id: "PRJ-014",
    name: "金属结合位点探索",
    updatedAt: "昨天 19:32",
    current: {
      revision: 5,
      nodeCount: 8,
      generationSteps: 96,
      promptRevision: 3,
      promptSummary: "链 A · 143 residues · function annotations 2（全部示意）",
      canvasLayout: "空间画布 · 8 个 Node Instances",
      updatedAt: "昨天 19:32",
    },
    versions: [
      {
        id: "VER-014-01",
        name: "保留结合位点坐标",
        createdAt: "08-27 09:20",
        snapshot: {
          revision: 3,
          nodeCount: 7,
          generationSteps: 72,
          promptRevision: 2,
          promptSummary: "链 A · 143 residues · function annotations 2（全部示意）",
          canvasLayout: "空间画布 · 7 个 Node Instances",
          updatedAt: "命名版本 · 08-27 09:20",
        },
      },
    ],
    retainedHeads: [],
    currentOrigin: null,
    latestRun: null,
  },
  {
    id: "PRJ-006",
    name: "多序列溶解度筛选",
    updatedAt: "08-25 16:04",
    current: {
      revision: 11,
      nodeCount: 9,
      generationSteps: 0,
      promptRevision: 0,
      promptSummary: "FASTA · 48 sequences（全部示意）",
      canvasLayout: "空间画布 · 9 个 Node Instances",
      updatedAt: "08-25 16:04",
    },
    versions: [],
    retainedHeads: [],
    currentOrigin: null,
    latestRun: {
      id: "RUN-006-11",
      workflowRevision: 11,
      summary: "48 sequence Candidates · 已完成（示意）",
    },
  },
];

const clone = (value) => structuredClone(value);
const initialVariant = new URLSearchParams(location.search).get("variant")?.toUpperCase();
const SHOW_PROTOTYPE_CONTROLS =
  location.protocol === "file:" || ["127.0.0.1", "localhost"].includes(location.hostname);

const state = {
  variant: VARIANTS[initialVariant] ? initialVariant : "A",
  projects: clone(sampleProjects),
  deletedProjects: [],
  currentProjectId: null,
  workspace: clone(DEFAULT_WORKSPACE),
  viewingVersionId: null,
  priorCurrentBeforeVersion: null,
  autosave: "template",
  savedAt: null,
  projectPanelOpen: false,
  projectTab: "projects",
  projectSearch: "",
  dialog: null,
  pendingProjectTarget: null,
  promptStudio: {
    open: false,
    dirty: false,
    editCount: 0,
    lastEditedTrack: null,
  },
  lastAction: "已打开干净的默认示例；默认示例保持不变",
  toasts: [],
  idCounter: 30,
};

let autosaveTimer = null;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function currentProject() {
  return state.projects.find((project) => project.id === state.currentProjectId) ?? null;
}

function currentVersion() {
  const project = currentProject();
  return project?.versions.find((version) => version.id === state.viewingVersionId) ?? null;
}

function currentName() {
  return currentProject()?.name ?? DEFAULT_TEMPLATE.name;
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
    .map((toast) => `<div class="toast ${toast.tone}">${escapeHtml(toast.text)}</div>`)
    .join("");
}

function record(text) {
  state.lastAction = text;
}

function saveStatus() {
  if (state.promptStudio.open && state.promptStudio.dirty) {
    return {
      tone: "warn",
      label: "Prompt Studio 有未保存更改",
      detail: "尚未写回 Workflow；项目自动保存不包含这份 Studio 草稿",
    };
  }
  if (!currentProject()) {
    return {
      tone: "template",
      label: "干净默认示例",
      detail: "模板不可变；第一次修改会自动建立个人副本",
    };
  }
  if (currentVersion()) {
    return {
      tone: "snapshot",
      label: `正在查看命名版本 · ${currentVersion().name}`,
      detail: "该版本不会被覆盖；继续修改会创建新的编辑分支",
    };
  }
  if (state.autosave === "saving") {
    return { tone: "saving", label: "正在自动保存…", detail: "个人项目当前工作" };
  }
  return {
    tone: "saved",
    label: "当前工作已自动保存",
    detail: state.savedAt ? `最近保存 ${state.savedAt}` : "个人项目当前工作",
  };
}

function ensurePersonalCopy(reason) {
  if (currentProject()) return currentProject();
  const project = {
    id: `PRJ-${state.idCounter++}`,
    name: "我的实验 · 默认示例副本",
    updatedAt: "刚刚",
    current: clone(state.workspace),
    versions: [],
    retainedHeads: [],
    currentOrigin: { kind: "default-copy", label: DEFAULT_TEMPLATE.name },
    latestRun: null,
  };
  state.projects.unshift(project);
  state.currentProjectId = project.id;
  state.autosave = "saving";
  record(`${reason}：已自动建立个人副本 ${project.id}；默认示例保持不变`);
  addToast("已自动建立个人副本；默认示例保持不变", "success");
  return project;
}

function beginBranchFromVersion(reason) {
  const project = currentProject();
  const version = currentVersion();
  if (!project || !version) return;
  const retained = {
    id: `HEAD-${state.idCounter++}`,
    label: `打开“${version.name}”前的当前工作`,
    retainedAt: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
    snapshot: clone(state.priorCurrentBeforeVersion ?? project.current),
  };
  project.retainedHeads.unshift(retained);
  project.currentOrigin = { kind: "named-version", versionId: version.id, label: version.name };
  state.viewingVersionId = null;
  state.priorCurrentBeforeVersion = null;
  record(`${reason}：从命名版本“${version.name}”创建新的编辑分支；旧版本与打开前当前工作均保留`);
  addToast(`已从“${version.name}”分出当前工作；原内容均保留`, "success");
}

function scheduleAutosave(action) {
  const project = currentProject();
  if (!project) return;
  clearTimeout(autosaveTimer);
  project.current = clone(state.workspace);
  project.updatedAt = "刚刚";
  state.autosave = "saving";
  record(action);
  render();
  const projectId = project.id;
  autosaveTimer = setTimeout(() => {
    const target = state.projects.find((item) => item.id === projectId);
    if (!target) return;
    target.current = clone(state.workspace);
    target.updatedAt = "刚刚";
    if (state.currentProjectId === projectId && !state.viewingVersionId) {
      state.autosave = "saved";
      state.savedAt = new Date().toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      render();
    }
  }, 720);
}

function simulateWorkflowEdit() {
  ensurePersonalCopy("第一次修改 Workflow");
  if (currentVersion()) beginBranchFromVersion("修改示例生成参数");
  state.workspace.generationSteps += 8;
  state.workspace.revision += 1;
  state.workspace.updatedAt = "刚刚";
  scheduleAutosave(`已修改示例生成参数中的 steps 为 ${state.workspace.generationSteps}；此节点未完整体现可调整参数`);
}

function newBlankProject() {
  if (guardPromptStudio({ kind: "new-blank" })) return;
  const project = {
    id: `PRJ-${state.idCounter++}`,
    name: "未命名蛋白质实验",
    updatedAt: "刚刚",
    current: {
      revision: 1,
      nodeCount: 0,
      generationSteps: 0,
      promptRevision: 0,
      promptSummary: "尚未创建 ProteinPrompt",
      canvasLayout: "空白空间画布",
      updatedAt: "刚刚",
    },
    versions: [],
    retainedHeads: [],
    currentOrigin: { kind: "blank", label: "空白 Workflow" },
    latestRun: null,
  };
  state.projects.unshift(project);
  openProjectNow(project.id);
  record(`已新建并打开空白个人项目 ${project.id}`);
  addToast("已新建空白个人项目", "success");
}

function guardPromptStudio(target) {
  if (!state.promptStudio.open || !state.promptStudio.dirty) return false;
  state.pendingProjectTarget = target;
  state.projectPanelOpen = false;
  state.dialog = { type: "prompt-exit" };
  record("项目切换已暂停：Prompt Studio 的草稿尚未写回 Workflow");
  render();
  return true;
}

function requestOpenProject(projectId, versionId = null) {
  if (guardPromptStudio({ kind: "project", projectId, versionId })) return;
  openProjectNow(projectId, versionId);
}

function openProjectNow(projectId, versionId = null) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  clearTimeout(autosaveTimer);
  state.currentProjectId = project.id;
  state.workspace = clone(project.current);
  state.viewingVersionId = null;
  state.priorCurrentBeforeVersion = null;
  state.autosave = "saved";
  state.savedAt = project.updatedAt;
  state.projectPanelOpen = false;
  if (versionId) openNamedVersion(project.id, versionId);
  else {
    record(`已打开个人项目“${project.name}” · ${project.id}`);
    render();
  }
}

function requestOpenDefault() {
  if (guardPromptStudio({ kind: "default" })) return;
  openDefaultNow();
}

function openDefaultNow() {
  clearTimeout(autosaveTimer);
  state.currentProjectId = null;
  state.workspace = clone(DEFAULT_WORKSPACE);
  state.viewingVersionId = null;
  state.priorCurrentBeforeVersion = null;
  state.autosave = "template";
  state.savedAt = null;
  state.projectPanelOpen = false;
  record("已重新打开干净的默认示例；个人项目没有被覆盖");
  render();
}

function openNamedVersion(projectId, versionId) {
  const project = state.projects.find((item) => item.id === projectId);
  const version = project?.versions.find((item) => item.id === versionId);
  if (!project || !version) return;
  state.currentProjectId = project.id;
  state.priorCurrentBeforeVersion = clone(project.current);
  state.viewingVersionId = version.id;
  state.workspace = clone(version.snapshot);
  state.autosave = "snapshot";
  state.projectPanelOpen = false;
  record(`已打开命名版本“${version.name}”；原版本与打开前当前工作均不会被覆盖`);
  render();
}

function returnToProjectCurrent() {
  const project = currentProject();
  if (!project) return;
  state.workspace = clone(state.priorCurrentBeforeVersion ?? project.current);
  state.viewingVersionId = null;
  state.priorCurrentBeforeVersion = null;
  state.autosave = "saved";
  record("已返回打开命名版本前的项目当前工作；没有建立新分支");
  render();
}

function openPromptStudio() {
  state.promptStudio = { open: true, dirty: false, editCount: 0, lastEditedTrack: null };
  record("已打开 Prompt Studio；项目当前工作仍保持已保存状态");
  render();
}

function editPromptDraft(track = "所选 ProteinPrompt 内容") {
  state.promptStudio.dirty = true;
  state.promptStudio.editCount += 1;
  state.promptStudio.lastEditedTrack = track;
  record(`${track} 的示意草稿已修改，但尚未写回 Workflow，也未进入项目自动保存`);
  render();
}

function savePromptStudio(continueAfter = false) {
  if (state.promptStudio.dirty) {
    ensurePersonalCopy("保存 ProteinPrompt");
    if (currentVersion()) beginBranchFromVersion("保存 ProteinPrompt");
    state.workspace.promptRevision += 1;
    state.workspace.revision += 1;
    const summaryBase = state.workspace.promptSummary.replace(/ · Studio edit r\d+（示意）$/, "");
    state.workspace.promptSummary = `${summaryBase} · Studio edit r${state.workspace.promptRevision}（示意）`;
    state.promptStudio = { open: false, dirty: false, editCount: 0, lastEditedTrack: null };
    scheduleAutosave("ProteinPrompt 已明确保存回 Workflow；项目当前工作正在自动保存");
  } else {
    state.promptStudio = { open: false, dirty: false, editCount: 0, lastEditedTrack: null };
    record("已关闭 Prompt Studio；没有需要写回 Workflow 的修改");
    render();
  }
  if (continueAfter) setTimeout(continuePendingTarget, 0);
}

function cancelPromptStudio(continueAfter = false) {
  state.promptStudio = { open: false, dirty: false, editCount: 0, lastEditedTrack: null };
  record("已放弃 Prompt Studio 草稿；Workflow 与项目自动保存内容保持不变");
  render();
  if (continueAfter) setTimeout(continuePendingTarget, 0);
}

function continuePendingTarget() {
  const target = state.pendingProjectTarget;
  state.pendingProjectTarget = null;
  state.dialog = null;
  if (!target) return render();
  if (target.kind === "default") openDefaultNow();
  else if (target.kind === "new-blank") newBlankProject();
  else if (target.kind === "project") openProjectNow(target.projectId, target.versionId);
}

function createNamedVersion(name) {
  const project = currentProject();
  const trimmed = name.trim();
  if (!project || !trimmed || currentVersion()) return;
  const version = {
    id: `VER-${project.id.slice(4)}-${String(project.versions.length + 1).padStart(2, "0")}`,
    name: trimmed,
    createdAt: new Date().toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }),
    snapshot: clone(state.workspace),
  };
  project.versions.push(version);
  state.dialog = null;
  record(`已创建命名版本“${trimmed}”；包含 Workflow、参数、ProteinPrompt 和画布布局`);
  addToast(`命名版本“${trimmed}”已创建`, "success");
  render();
}

function renameProject(name) {
  const project = currentProject();
  const trimmed = name.trim();
  if (!project || !trimmed) return;
  const oldName = project.name;
  project.name = trimmed;
  state.dialog = null;
  scheduleAutosave(`项目已从“${oldName}”重命名为“${trimmed}”；正在自动保存`);
}

function copyProject() {
  const source = currentProject();
  if (!source) return;
  const copyProject = {
    id: `PRJ-${state.idCounter++}`,
    name: `${source.name} · 副本`,
    updatedAt: "刚刚",
    current: clone(state.workspace),
    versions: [],
    retainedHeads: [],
    currentOrigin: { kind: "project-copy", projectId: source.id, label: source.name },
    latestRun: null,
  };
  state.projects.unshift(copyProject);
  state.dialog = null;
  state.currentProjectId = copyProject.id;
  state.workspace = clone(copyProject.current);
  state.viewingVersionId = null;
  state.priorCurrentBeforeVersion = null;
  state.autosave = "saved";
  state.savedAt = "刚刚";
  record(`已复制为新项目 ${copyProject.id}；命名版本和 Run / Results 未复制，新项目尚未运行`);
  addToast("已打开独立项目副本；命名版本与 Run / Results 未复制", "success");
  render();
}

function deleteCurrentProject() {
  const project = currentProject();
  if (!project) return;
  state.projects = state.projects.filter((item) => item.id !== project.id);
  state.deletedProjects.unshift({ ...project, deletedAt: "刚刚" });
  state.dialog = null;
  state.currentProjectId = null;
  state.workspace = clone(DEFAULT_WORKSPACE);
  state.viewingVersionId = null;
  state.priorCurrentBeforeVersion = null;
  state.autosave = "template";
  state.savedAt = null;
  state.projectPanelOpen = state.variant !== "C";
  state.projectTab = "deleted";
  record(`项目“${project.name}”已完整移入最近删除；现在显示干净默认示例`);
  addToast("完整项目已移入最近删除，可恢复", "warn");
  render();
}

function restoreProject(projectId) {
  const project = state.deletedProjects.find((item) => item.id === projectId);
  if (!project) return;
  state.deletedProjects = state.deletedProjects.filter((item) => item.id !== projectId);
  const { deletedAt, ...restored } = project;
  state.projects.unshift(restored);
  state.projectTab = "projects";
  record(`已恢复原项目“${project.name}” · ${project.id}；版本与 Run / Results 一同恢复，没有创建副本`);
  addToast("已恢复原项目身份和全部项目内容", "success");
  render();
}

function originLabel(project = currentProject()) {
  if (!project) return "不可变默认示例";
  if (currentVersion()) return `命名版本快照 · ${currentVersion().name}`;
  const origin = project.currentOrigin;
  if (!origin) return "个人项目当前工作";
  if (origin.kind === "default-copy") return "首次修改默认示例时自动建立的个人副本";
  if (origin.kind === "project-copy") return `独立副本 · 来自 ${origin.projectId}`;
  if (origin.kind === "named-version") return `编辑分支 · 来自“${origin.label}”`;
  return origin.label;
}

function latestRunLabel(project = currentProject()) {
  if (!project) return "默认示例 Run（示意内容未裁决）";
  return project.latestRun
    ? `${project.latestRun.id} · Workflow v${project.latestRun.workflowRevision} · ${project.latestRun.summary}`
    : "尚未运行 · 没有 Results";
}

function projectSearchMatches(project) {
  const needle = state.projectSearch.trim().toLowerCase();
  if (!needle) return true;
  return `${project.name} ${project.id} ${project.versions.map((version) => version.name).join(" ")}`
    .toLowerCase()
    .includes(needle);
}

function renderHeader() {
  const project = currentProject();
  const version = currentVersion();
  const saving = saveStatus();
  return `
    <header class="topbar">
      <button class="brand" data-action="open-default" title="打开干净默认示例">
        <span class="brand-mark">PW</span>
        <span>Protein Workbench</span>
      </button>
      <button class="project-context" data-action="toggle-project-panel">
        <span class="project-kicker">${project ? "个人项目" : "启动默认示例"}${version ? " · 命名版本" : ""}</span>
        <strong>${escapeHtml(currentName())}</strong>
        <span class="identity">${project ? project.id : DEFAULT_TEMPLATE.id}${version ? ` / ${version.id}` : ""}</span>
      </button>
      <div class="save-indicator ${saving.tone}">
        <span class="save-dot"></span>
        <span><strong>${escapeHtml(saving.label)}</strong><small>${escapeHtml(saving.detail)}</small></span>
      </div>
      <div class="top-actions">
        <button class="button" data-action="new-blank">新建空白</button>
        <button class="button" data-action="toggle-project-panel">项目</button>
        <button class="button" data-action="open-version-dialog" ${!project || version ? "disabled" : ""}>创建命名版本</button>
      </div>
    </header>`;
}

function renderProjectList(compact = false) {
  const projects = state.projects;
  const rows = projects
    .map((project) => {
      const current = project.id === state.currentProjectId;
      const versions = project.versions
        .map(
          (version) => `
            <button class="version-row ${state.viewingVersionId === version.id ? "active" : ""}" data-action="open-version" data-project-id="${project.id}" data-version-id="${version.id}">
              <span>命名版本</span>
              <strong>${escapeHtml(version.name)}</strong>
              <small>${escapeHtml(version.createdAt)} · Workflow v${version.snapshot.revision}</small>
            </button>`,
        )
        .join("");
      return `
        <section class="project-row ${current ? "current" : ""} ${projectSearchMatches(project) ? "" : "filtered-out"}" data-project-search="${escapeHtml(`${project.name} ${project.id} ${project.versions.map((v) => v.name).join(" ")}`.toLowerCase())}">
          <button class="project-row-main" data-action="open-project" data-project-id="${project.id}">
            <span class="project-row-title"><strong>${escapeHtml(project.name)}</strong>${current ? '<em>当前</em>' : ""}</span>
            <span>${project.id} · ${project.current.nodeCount} Nodes · ${project.versions.length} 个命名版本</span>
            <small>${escapeHtml(project.updatedAt)} · ${project.latestRun ? "有最近 Run" : "尚未运行"}</small>
          </button>
          ${compact ? "" : `<div class="version-list">${versions || '<span class="empty-inline">没有命名版本</span>'}</div>`}
        </section>`;
    })
    .join("");
  return rows || '<div class="empty-state">没有个人项目</div>';
}

function renderDeletedList() {
  if (!state.deletedProjects.length) {
    return '<div class="empty-state">最近删除为空。删除完整项目后可在这里恢复。</div>';
  }
  return state.deletedProjects
    .map(
      (project) => `
        <section class="deleted-row">
          <div>
            <strong>${escapeHtml(project.name)}</strong>
            <span>${project.id} · ${project.versions.length} 个命名版本</span>
            <small>${project.latestRun ? `包含 ${project.latestRun.id} 与 Results` : "没有 Run / Results"} · 删除于 ${project.deletedAt}</small>
          </div>
          <button class="button primary" data-action="restore-project" data-project-id="${project.id}">恢复</button>
        </section>`,
    )
    .join("");
}

function renderProjectPanel() {
  if (!state.projectPanelOpen) return "";
  return `
    <div class="project-panel-backdrop" data-action="close-project-panel"></div>
    <aside class="project-panel">
      <div class="panel-heading">
        <div><span class="eyebrow">PROJECTS</span><h2>项目与命名版本</h2></div>
        <button class="icon-button" data-action="close-project-panel" aria-label="关闭">×</button>
      </div>
      <button class="default-project-row" data-action="open-default">
        <span><strong>${DEFAULT_TEMPLATE.name}</strong><small>每次启动都从干净副本打开 · 不可变</small></span>
        ${!currentProject() ? "<em>当前</em>" : ""}
      </button>
      <div class="tabs">
        <button class="${state.projectTab === "projects" ? "active" : ""}" data-action="project-tab" data-value="projects">个人项目 ${state.projects.length}</button>
        <button class="${state.projectTab === "deleted" ? "active" : ""}" data-action="project-tab" data-value="deleted">最近删除 ${state.deletedProjects.length}</button>
      </div>
      ${
        state.projectTab === "projects"
          ? `<label class="search-field"><span>⌕</span><input id="project-search" value="${escapeHtml(state.projectSearch)}" placeholder="搜索项目、ID 或命名版本" autocomplete="off" /></label>
             <div class="project-list">${renderProjectList()}</div>`
          : `<div class="project-list deleted-list">${renderDeletedList()}</div>`
      }
      <div class="panel-footnote">示意项目顺序不代表产品默认排序。</div>
    </aside>`;
}

function renderWorkflowNodes() {
  const nodes = [
    { index: "01", name: "导入 PDB", detail: "链 A（示意）", type: "input" },
    { index: "02", name: "编写 ProteinPrompt", detail: `Prompt r${state.workspace.promptRevision}`, type: "prompt" },
    {
      index: "03",
      name: "ESM-3 生成",
      detail: `参数摘要（示意） · ${state.workspace.generationSteps} steps`,
      caveat: "仅作示例；未完整体现可调整参数",
      type: "generate",
    },
    { index: "04", name: "评分", detail: "Metric（示意；未裁决）", type: "score" },
    { index: "05", name: "筛选", detail: "条件（示意；未裁决）", type: "filter" },
  ];
  return `
    <div class="workflow-nodes">
      <svg class="workflow-lines" viewBox="0 0 1000 220" preserveAspectRatio="none" aria-hidden="true">
        <path d="M150 110 C190 110 190 110 230 110 M350 110 C390 110 390 110 430 110 M550 110 C590 110 590 110 630 110 M750 110 C790 110 790 110 830 110" />
      </svg>
      ${nodes
        .map(
          (node) => `
            <article class="workflow-node ${node.type}">
              <span class="node-index">${node.index}</span>
              <strong>${node.name}</strong>
              <small>${escapeHtml(node.detail)}</small>
              ${node.caveat ? `<small class="node-caveat">${escapeHtml(node.caveat)}</small>` : ""}
              ${node.type === "prompt" ? '<button class="mini-action" data-action="open-prompt-studio">编辑 ProteinPrompt</button>' : ""}
              ${node.type === "generate" ? '<button class="mini-action" data-action="simulate-edit">修改示例参数</button>' : ""}
            </article>`,
        )
        .join("")}
    </div>`;
}

function renderCanvas() {
  const project = currentProject();
  const version = currentVersion();
  return `
    <section class="canvas-panel">
      <div class="canvas-toolbar">
        <div>
          <span class="eyebrow">WORKFLOW</span>
          <strong>${state.workspace.canvasLayout}</strong>
        </div>
        <div class="canvas-toolbar-actions">
          ${version ? '<button class="button" data-action="return-current">返回打开前的当前工作</button>' : ""}
          <button class="button primary" data-action="simulate-edit">修改示例生成参数</button>
        </div>
      </div>
      ${
        version
          ? `<div class="context-banner snapshot"><strong>命名版本“${escapeHtml(version.name)}”</strong><span>不可覆盖 · 第一次修改会从此版本创建新的编辑分支，并保留打开前的当前工作。</span></div>`
          : project?.currentOrigin?.kind === "named-version"
            ? `<div class="context-banner branch"><strong>当前工作从“${escapeHtml(project.currentOrigin.label)}”分出</strong><span>旧命名版本与打开前的当前工作仍保留。</span></div>`
            : ""
      }
      <div class="canvas-stage">
        <div class="grid-fade"></div>
        ${state.workspace.nodeCount ? renderWorkflowNodes() : '<div class="blank-canvas"><strong>空白 Workflow</strong><span>从 Node Type 列表拖入节点，或在画布搜索添加。</span></div>'}
      </div>
      <footer class="canvas-footer">
        <span>Workflow v${state.workspace.revision}</span>
        <span>${escapeHtml(state.workspace.promptSummary)}</span>
        <span>示意科学内容</span>
      </footer>
    </section>`;
}

function renderContextRail() {
  const project = currentProject();
  const saving = saveStatus();
  return `
    <aside class="context-rail">
      <section class="rail-card identity-card">
        <span class="eyebrow">CURRENT OBJECT</span>
        <h3>${escapeHtml(currentName())}</h3>
        <dl>
          <div><dt>身份</dt><dd>${project ? project.id : DEFAULT_TEMPLATE.id}</dd></div>
          <div><dt>来源</dt><dd>${escapeHtml(originLabel())}</dd></div>
          <div><dt>当前</dt><dd>Workflow v${state.workspace.revision}</dd></div>
        </dl>
      </section>
      <section class="rail-card save-card ${saving.tone}">
        <span class="eyebrow">SAVE BOUNDARY</span>
        <h3>${escapeHtml(saving.label)}</h3>
        <p>${escapeHtml(saving.detail)}</p>
        <div class="boundary-row"><span>项目当前工作</span><strong>${project && !currentVersion() ? "自动保存" : "不写入"}</strong></div>
        <div class="boundary-row"><span>Prompt Studio 草稿</span><strong>明确保存</strong></div>
      </section>
      <section class="rail-card action-card">
        <span class="eyebrow">PROJECT ACTIONS</span>
        <div class="stack-actions">
          <button class="button" data-action="open-rename-dialog" ${!project || currentVersion() ? "disabled" : ""}>重命名项目</button>
          <button class="button" data-action="open-copy-dialog" ${!project ? "disabled" : ""}>复制项目</button>
          <button class="button danger" data-action="open-delete-dialog" ${!project ? "disabled" : ""}>删除到最近删除</button>
        </div>
      </section>
      <section class="rail-card run-card">
        <span class="eyebrow">LATEST RUN</span>
        <p>${escapeHtml(latestRunLabel())}</p>
      </section>
    </aside>`;
}

function renderVariantA() {
  return `
    <main class="variant-a">
      <aside class="node-library">
        <span class="eyebrow">NODE TYPES</span>
        <h3>研究用途</h3>
        ${["输入", "Prompt", "生成", "评分", "筛选", "导出"].map((item) => `<button>${item}<span>›</span></button>`).join("")}
        <p>分类与项目管理分离；此处仅示意已采用的空间画布语境。</p>
      </aside>
      ${renderCanvas()}
      ${renderContextRail()}
    </main>`;
}

function renderTimeline() {
  const project = currentProject();
  if (!project) {
    return `
      <div class="timeline-empty">
        <span class="template-node">默认示例</span><span class="timeline-arrow">第一次修改 →</span><span class="future-node">个人副本（尚未建立）</span>
        <p>默认示例本身保持不变；在 Workflow 中修改即可无阻断地建立个人副本。</p>
      </div>`;
  }
  const versionNodes = project.versions
    .map(
      (version) => `
        <button class="timeline-node version ${state.viewingVersionId === version.id ? "active" : ""}" data-action="open-version" data-project-id="${project.id}" data-version-id="${version.id}">
          <span>命名版本 · 不可覆盖</span><strong>${escapeHtml(version.name)}</strong><small>${version.id} · Workflow v${version.snapshot.revision}</small>
        </button>`,
    )
    .join("");
  const retained = project.retainedHeads
    .map(
      (head) => `
        <div class="timeline-node retained">
          <span>已保留的当前工作</span><strong>${escapeHtml(head.label)}</strong><small>${head.id} · Workflow v${head.snapshot.revision}</small>
        </div>`,
    )
    .join("");
  return `
    <div class="timeline-map">
      <div class="timeline-root">
        <span class="timeline-node project-root"><span>个人项目</span><strong>${escapeHtml(project.name)}</strong><small>${project.id}</small></span>
      </div>
      <div class="timeline-trunk"></div>
      <div class="timeline-versions">${versionNodes || '<span class="timeline-placeholder">尚无命名版本</span>'}</div>
      <div class="timeline-branches">
        <div class="timeline-node current-head">
          <span>当前编辑工作</span><strong>Workflow v${state.workspace.revision}</strong><small>${escapeHtml(originLabel(project))}</small>
        </div>
        ${retained}
      </div>
    </div>`;
}

function renderVariantB() {
  const project = currentProject();
  return `
    <main class="variant-b">
      <section class="timeline-workspace">
        <div class="section-heading">
          <div><span class="eyebrow">PROJECT LINEAGE</span><h2>版本与当前工作的来源</h2></div>
          <div class="heading-actions">
            <button class="button" data-action="toggle-project-panel">搜索并打开项目</button>
            <button class="button primary" data-action="open-version-dialog" ${!project || currentVersion() ? "disabled" : ""}>创建命名版本</button>
          </div>
        </div>
        ${renderTimeline()}
        <div class="timeline-legend"><span><i class="legend-version"></i>命名版本：不可覆盖快照</span><span><i class="legend-head"></i>当前工作：自动保存</span><span><i class="legend-retained"></i>打开旧版本前的当前工作：保留</span></div>
      </section>
      <section class="timeline-side">
        ${renderCanvas()}
        <div class="timeline-side-bottom">
          ${renderContextRail()}
        </div>
      </section>
    </main>`;
}

function renderLibraryColumn() {
  return `
    <aside class="library-column">
      <div class="section-heading compact"><div><span class="eyebrow">PROJECT LIBRARY</span><h2>实验项目</h2></div><button class="icon-button" data-action="new-blank">＋</button></div>
      <label class="search-field"><span>⌕</span><input id="project-search-inline" value="${escapeHtml(state.projectSearch)}" placeholder="搜索项目或命名版本" autocomplete="off" /></label>
      <button class="default-project-row" data-action="open-default"><span><strong>干净默认示例</strong><small>每次启动打开 · 不可变</small></span>${!currentProject() ? "<em>当前</em>" : ""}</button>
      <div class="inline-project-list">${renderProjectList(true)}</div>
      <button class="recent-deleted-button" data-action="show-deleted-inline">最近删除 <strong>${state.deletedProjects.length}</strong></button>
    </aside>`;
}

function renderObjectInspector() {
  const project = currentProject();
  const saving = saveStatus();
  if (state.projectTab === "deleted" && state.variant === "C") {
    return `
      <aside class="object-inspector">
        <div class="section-heading compact"><div><span class="eyebrow">RECENTLY DELETED</span><h2>最近删除</h2></div><button class="icon-button" data-action="hide-deleted-inline">×</button></div>
        <p class="inspector-lead">恢复保持原项目身份和全部项目内容；不是复制。</p>
        <div class="deleted-list inline">${renderDeletedList()}</div>
      </aside>`;
  }
  return `
    <aside class="object-inspector">
      <div class="section-heading compact"><div><span class="eyebrow">OBJECT & SAVE</span><h2>当前对象</h2></div></div>
      <section class="object-identity">
        <span class="object-kind">${project ? "个人项目" : "默认示例"}</span>
        <h3>${escapeHtml(currentName())}</h3>
        <code>${project ? project.id : DEFAULT_TEMPLATE.id}</code>
        <p>${escapeHtml(originLabel())}</p>
      </section>
      <section class="save-boundary-table">
        <div class="boundary-title ${saving.tone}"><span class="save-dot"></span><strong>${escapeHtml(saving.label)}</strong></div>
        <div><span>Workflow / 参数 / 画布</span><strong>${project && !currentVersion() ? "自动保存" : "不写入"}</strong></div>
        <div><span>Prompt Studio 草稿</span><strong>保存后才写回</strong></div>
        <div><span>命名版本</span><strong>不可覆盖</strong></div>
        <div><span>最近 Run / Results</span><strong>${project?.latestRun ? "保留" : "无"}</strong></div>
      </section>
      <section class="object-actions">
        <button class="button" data-action="open-rename-dialog" ${!project || currentVersion() ? "disabled" : ""}>重命名</button>
        <button class="button" data-action="open-copy-dialog" ${!project ? "disabled" : ""}>复制</button>
        <button class="button" data-action="open-version-dialog" ${!project || currentVersion() ? "disabled" : ""}>命名版本</button>
        <button class="button danger" data-action="open-delete-dialog" ${!project ? "disabled" : ""}>删除</button>
      </section>
      <section class="version-summary">
        <span class="eyebrow">VERSIONS</span>
        ${
          project
            ? project.versions.map((version) => `<button data-action="open-version" data-project-id="${project.id}" data-version-id="${version.id}"><strong>${escapeHtml(version.name)}</strong><small>${version.id} · v${version.snapshot.revision}</small></button>`).join("") || "<p>没有命名版本</p>"
            : "<p>默认示例没有个人命名版本</p>"
        }
      </section>
    </aside>`;
}

function renderVariantC() {
  return `
    <main class="variant-c">
      ${renderLibraryColumn()}
      <section class="library-workspace">${renderCanvas()}</section>
      ${renderObjectInspector()}
    </main>`;
}

function renderPrototypeInspector() {
  const project = currentProject();
  const saving = saveStatus();
  return `
    <aside class="prototype-inspector">
      <span>原型状态</span>
      <strong>${project ? project.id : DEFAULT_TEMPLATE.id}${currentVersion() ? ` / ${currentVersion().id}` : ""}</strong>
      <em>${escapeHtml(saving.label)}</em>
      <small>${escapeHtml(state.lastAction)}</small>
    </aside>`;
}

function renderSwitcher() {
  if (!SHOW_PROTOTYPE_CONTROLS) return "";
  const variant = VARIANTS[state.variant];
  return `
    <nav class="prototype-switcher" aria-label="原型方案切换">
      <button data-action="previous-variant" aria-label="上一方案">←</button>
      <div><span>${escapeHtml(variant.label)}</span><small>${escapeHtml(variant.question)}</small></div>
      <button data-action="next-variant" aria-label="下一方案">→</button>
    </nav>`;
}

function renderPromptStudio() {
  if (!state.promptStudio.open) return "";
  const dirty = state.promptStudio.dirty;
  return `
    <div class="studio-overlay">
      <section class="prompt-studio">
        <header class="studio-header">
          <div><span class="eyebrow">PROMPT STUDIO · EDIT SESSION</span><h2>ProteinPrompt</h2></div>
          <div class="studio-status ${dirty ? "dirty" : "clean"}"><span class="save-dot"></span>${dirty ? "有未保存更改 · 尚未写回 Workflow" : "已载入 Workflow 中的 ProteinPrompt"}</div>
        </header>
        <div class="studio-boundary-banner">
          <strong>这里使用明确保存边界</strong>
          <span>个人项目自动保存只保存 Workflow 当前工作；本 Studio 草稿必须点击“保存 ProteinPrompt”才会写回。</span>
        </div>
        <div class="studio-grid">
          <section class="structure-placeholder"><span>三维结构（示意）</span><div class="protein-sketch">⌁</div><small>coordinates track · 示意视图</small><em>显示/隐藏只改变界面状态，不清除 coordinate values</em></section>
          <section class="residue-matrix">
            <div class="prompt-content-inventory">
              <strong>完整 ProteinPrompt 可编辑内容</strong>
              <span>sequence</span><span>coordinates</span><span>secondary structure</span><span>SASA (Å²)</span><span>function annotations</span>
            </div>
            <span class="eyebrow">RESIDUE-ALIGNED CONDITIONING · SELECTED WINDOW</span>
            <div class="residue-window-summary"><b>当前视窗</b><span>链 A · 76 residues · A:41–A:46（全部示意）</span></div>
            <div class="residue-row"><b>position</b>${["A:41", "A:42", "A:43", "A:44", "A:45", "A:46"].map((x) => `<i>${x}</i>`).join("")}</div>
            <div class="residue-row"><b>sequence</b>${["G", "V", "D", "L", "T", "K"].map((x) => `<i>${x}</i>`).join("")}</div>
            <div class="residue-row"><b>coordinates</b>${["指定", "指定", "指定", "指定", "指定", "指定"].map((x) => `<i>${x}</i>`).join("")}</div>
            <div class="residue-row"><b>secondary structure</b>${["C", "H", "H", "H", "C", "C"].map((x) => `<i>${x}</i>`).join("")}</div>
            <div class="residue-row"><b>SASA <u>Å²</u></b>${["48.1", "35.6", "22.4", "19.8", "41.2", "55.7"].map((x) => `<i>${x}</i>`).join("")}</div>
            <div class="annotation-ribbon ${dirty && state.promptStudio.lastEditedTrack === "function annotations" ? "changed" : ""}"><b>function annotations · interval collection</b><span>A:42–A:45 · annotation（示意；正式词表未裁决）</span></div>
          </section>
          <section class="studio-editor">
            <span class="eyebrow">JOINT EDIT</span>
            <h3>A:42–A:45</h3>
            <p>同一选区内完整显示并编辑项目拥有的全部 conditioning 内容；下列值都只是保存边界演示。</p>
            <div class="track-editor-list">
              <button data-action="edit-prompt-draft" data-track="sequence track"><span><b>sequence</b><small>V D L T</small></span><em>修改（示意）</em></button>
              <button data-action="edit-prompt-draft" data-track="coordinates track"><span><b>coordinates</b><small>4/4 positions 指定</small></span><em>修改（示意）</em></button>
              <button data-action="edit-prompt-draft" data-track="secondary-structure track"><span><b>secondary structure</b><small>H H H C</small></span><em>修改（示意）</em></button>
              <button data-action="edit-prompt-draft" data-track="absolute SASA track"><span><b>SASA</b><small>absolute per-residue · Å²</small></span><em>修改（示意）</em></button>
              <button data-action="edit-prompt-draft" data-track="function annotations"><span><b>function annotations</b><small>interval collection · 1 interval</small></span><em>修改（示意）</em></button>
            </div>
            <p class="editor-caveat">仅作交互示意；具体残基值与 annotation 名称不构成科学或产品决定。</p>
          </section>
        </div>
        <footer class="studio-footer">
          <span>${dirty ? "项目自动保存未包含这份草稿" : "没有未保存的 Studio 修改"}</span>
          <div>
            <button class="button" data-action="cancel-prompt">取消</button>
            <button class="button primary" data-action="save-prompt" ${dirty ? "" : "disabled"}>保存 ProteinPrompt</button>
          </div>
        </footer>
      </section>
    </div>`;
}

function renderDialog() {
  if (!state.dialog) return "";
  const project = currentProject();
  if (state.dialog.type === "rename") {
    return `
      <div class="dialog-backdrop"><section class="dialog"><span class="eyebrow">RENAME PROJECT</span><h2>重命名个人项目</h2><p>项目身份 <code>${project.id}</code> 保持不变；只修改显示名称。</p><label>项目名称<input id="dialog-input" value="${escapeHtml(project.name)}" /></label><div class="dialog-actions"><button class="button" data-action="close-dialog">取消</button><button class="button primary" data-action="confirm-rename">重命名</button></div></section></div>`;
  }
  if (state.dialog.type === "version") {
    return `
      <div class="dialog-backdrop"><section class="dialog"><span class="eyebrow">NAMED VERSION</span><h2>创建不可覆盖的命名版本</h2><p>此快照包含当前 <strong>Workflow、参数、ProteinPrompt 和画布布局</strong>。最近一次 Run / Results 仍属于项目，不成为版本内容。</p><label>版本名称<input id="dialog-input" value="调整 Prompt 后" /></label><div class="snapshot-summary"><span>Workflow v${state.workspace.revision}</span><span>Prompt r${state.workspace.promptRevision}</span><span>${state.workspace.nodeCount} Nodes</span></div><div class="dialog-actions"><button class="button" data-action="close-dialog">取消</button><button class="button primary" data-action="confirm-version">创建版本</button></div></section></div>`;
  }
  if (state.dialog.type === "copy") {
    return `
      <div class="dialog-backdrop"><section class="dialog wide"><span class="eyebrow">COPY PROJECT</span><h2>复制为独立、尚未运行的实验分支</h2><p>来源 <code>${project.id}</code> · ${escapeHtml(project.name)}</p><div class="copy-comparison"><section><strong>复制</strong><ul><li>当前 Workflow</li><li>当前参数</li><li>当前 ProteinPrompt</li><li>当前画布布局</li></ul></section><section class="excluded"><strong>不复制</strong><ul><li>${project.versions.length} 个命名版本</li><li>${project.latestRun ? project.latestRun.id : "最近一次 Run"}</li><li>Run 状态与 Results</li></ul></section></div><div class="result-object"><span>确认后打开</span><strong>新项目身份 · 尚未运行 · 没有 Results</strong></div><div class="dialog-actions"><button class="button" data-action="close-dialog">取消</button><button class="button primary" data-action="confirm-copy">复制并打开</button></div></section></div>`;
  }
  if (state.dialog.type === "delete") {
    return `
      <div class="dialog-backdrop"><section class="dialog"><span class="eyebrow danger-text">DELETE PROJECT</span><h2>把完整项目移入最近删除？</h2><p><strong>${escapeHtml(project.name)}</strong> · <code>${project.id}</code></p><div class="delete-summary"><span>当前 Workflow v${state.workspace.revision}</span><span>${project.versions.length} 个命名版本</span><span>${project.latestRun ? `${project.latestRun.id} 与 Results` : "没有 Run / Results"}</span></div><p>这些内容会作为同一个项目进入“最近删除”，可恢复。此操作不是复制，也不会删除默认示例。</p><div class="dialog-actions"><button class="button" data-action="close-dialog">取消</button><button class="button danger-solid" data-action="confirm-delete">移入最近删除</button></div></section></div>`;
  }
  if (state.dialog.type === "prompt-exit") {
    return `
      <div class="dialog-backdrop"><section class="dialog"><span class="eyebrow danger-text">UNSAVED PROMPT STUDIO</span><h2>ProteinPrompt 尚未保存到 Workflow</h2><p>项目自动保存没有包含这份 Studio 草稿。切换项目之前请选择如何处理。</p><div class="save-choice"><button data-action="prompt-exit-save"><strong>保存 ProteinPrompt</strong><span>写回 Workflow，再继续切换</span></button><button data-action="prompt-exit-discard"><strong>放弃 Studio 草稿</strong><span>保持 Workflow 和项目当前工作不变</span></button><button data-action="prompt-exit-continue"><strong>继续编辑</strong><span>取消项目切换，返回 Prompt Studio</span></button></div></section></div>`;
  }
  return "";
}

function render() {
  const app = document.querySelector("#app");
  const main = state.variant === "A" ? renderVariantA() : state.variant === "B" ? renderVariantB() : renderVariantC();
  app.innerHTML = `
    <div class="app-shell mode-${state.variant.toLowerCase()}">
      ${renderHeader()}
      ${main}
      ${renderProjectPanel()}
      ${renderPromptStudio()}
      ${renderDialog()}
      ${renderPrototypeInspector()}
      ${renderSwitcher()}
      <div class="toasts"></div>
    </div>`;
  renderToasts();
}

function applyProjectFilter(value) {
  state.projectSearch = value;
  const needle = value.trim().toLowerCase();
  document.querySelectorAll("[data-project-search]").forEach((row) => {
    row.classList.toggle("filtered-out", needle && !row.dataset.projectSearch.includes(needle));
  });
}

function cycleVariant(direction) {
  const keys = Object.keys(VARIANTS);
  const current = keys.indexOf(state.variant);
  state.variant = keys[(current + direction + keys.length) % keys.length];
  const url = new URL(location.href);
  url.searchParams.set("variant", state.variant);
  history.replaceState({}, "", url);
  record(`已切换到 ${VARIANTS[state.variant].label}；项目与保存状态保持不变`);
  render();
}

document.addEventListener("input", (event) => {
  if (["project-search", "project-search-inline"].includes(event.target.id)) {
    applyProjectFilter(event.target.value);
  }
});

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target || target.disabled) return;
  const action = target.dataset.action;
  if (action === "previous-variant") cycleVariant(-1);
  else if (action === "next-variant") cycleVariant(1);
  else if (action === "toggle-project-panel") {
    state.projectPanelOpen = !state.projectPanelOpen;
    render();
  } else if (action === "close-project-panel") {
    state.projectPanelOpen = false;
    render();
  } else if (action === "project-tab") {
    state.projectTab = target.dataset.value;
    render();
  } else if (action === "show-deleted-inline") {
    state.projectTab = "deleted";
    render();
  } else if (action === "hide-deleted-inline") {
    state.projectTab = "projects";
    render();
  } else if (action === "open-project") requestOpenProject(target.dataset.projectId);
  else if (action === "open-version") requestOpenProject(target.dataset.projectId, target.dataset.versionId);
  else if (action === "open-default") requestOpenDefault();
  else if (action === "new-blank") newBlankProject();
  else if (action === "simulate-edit") simulateWorkflowEdit();
  else if (action === "return-current") returnToProjectCurrent();
  else if (action === "open-prompt-studio") openPromptStudio();
  else if (action === "edit-prompt-draft") editPromptDraft(target.dataset.track);
  else if (action === "save-prompt") savePromptStudio();
  else if (action === "cancel-prompt") cancelPromptStudio();
  else if (action === "open-rename-dialog") {
    state.dialog = { type: "rename" };
    render();
  } else if (action === "open-version-dialog") {
    state.dialog = { type: "version" };
    render();
  } else if (action === "open-copy-dialog") {
    state.dialog = { type: "copy" };
    render();
  } else if (action === "open-delete-dialog") {
    state.dialog = { type: "delete" };
    render();
  } else if (action === "close-dialog") {
    state.dialog = null;
    render();
  } else if (action === "confirm-rename") renameProject(document.querySelector("#dialog-input")?.value ?? "");
  else if (action === "confirm-version") createNamedVersion(document.querySelector("#dialog-input")?.value ?? "");
  else if (action === "confirm-copy") copyProject();
  else if (action === "confirm-delete") deleteCurrentProject();
  else if (action === "restore-project") restoreProject(target.dataset.projectId);
  else if (action === "prompt-exit-save") {
    state.dialog = null;
    savePromptStudio(true);
  } else if (action === "prompt-exit-discard") {
    state.dialog = null;
    cancelPromptStudio(true);
  } else if (action === "prompt-exit-continue") {
    state.pendingProjectTarget = null;
    state.dialog = null;
    record("已取消项目切换，继续编辑 Prompt Studio 草稿");
    render();
  }
});

document.addEventListener("keydown", (event) => {
  const element = event.target;
  const editing =
    ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable;
  if (!editing && event.key === "ArrowLeft") cycleVariant(-1);
  if (!editing && event.key === "ArrowRight") cycleVariant(1);
  if (event.key === "Escape" && state.dialog) {
    if (state.dialog.type !== "prompt-exit") {
      state.dialog = null;
      render();
    }
  }
});

render();
