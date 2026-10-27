import { i18n, useLocale, localizeCatalog, LanguagePicker, text } from './i18n'
const messages = {
"discard_unsaved": {"zh-CN": " 未保存的修改将丢弃。", "en": " Unsaved changes will be discarded."},
"project_deleted": {"zh-CN": "已删除项目“{name}”", "en": "Deleted project “{name}”"},
"run_finished": {"zh-CN": "运行：{status}", "en": "Run: {status}"},
"round_suffix": {"zh-CN": " · 第 {n} 轮", "en": " · Round {n}"},
"item_suffix": {"zh-CN": " · 第 {n} 项", "en": " · Item {n}"},
"required_suffix": {"zh-CN": "（必填）", "en": " (required)"},
  "module_interface_failed": {
    "zh-CN": "模块界面无法打开：",
    "en": "Module interface failed:"
  },
  "back_to_canvas": {
    "zh-CN": "返回画布",
    "en": "Back to canvas"
  },
  "completed": {
    "zh-CN": "已完成",
    "en": "Completed"
  },
  "failed": {
    "zh-CN": "失败",
    "en": "Failed"
  },
  "cancelled": {
    "zh-CN": "已取消",
    "en": "Cancelled"
  },
  "running": {
    "zh-CN": "运行中",
    "en": "Running"
  },
  "pending": {
    "zh-CN": "等待中",
    "en": "Pending"
  },
  "not_run": {
    "zh-CN": "未执行",
    "en": "Not run"
  },
  "needs_configuration": {
    "zh-CN": "配置未完成",
    "en": "Needs configuration"
  },
  "new_project": {
    "zh-CN": "新项目",
    "en": "New project"
  },
  "wait_for_teaching_input_transfers_to_finish": {
    "zh-CN": "输入文件尚在载入，请稍后保存",
    "en": "Wait for teaching input transfers to finish before saving"
  },
  "project_list_refresh_failed": {
    "zh-CN": "项目列表载入失败：{0}",
    "en": "Project list refresh failed: {0}"
  },
  "module_refresh_failed": {
    "zh-CN": "模块载入失败：{0}",
    "en": "Module refresh failed: {0}"
  },
  "project_changed_start_the_operation_again": {
    "zh-CN": "项目已切换，请重试",
    "en": "Project changed; start the operation again"
  },
  "teaching_draft_is_saving_wait_for_the": {
    "zh-CN": "示例正在保存，请稍候",
    "en": "Teaching draft is saving; wait for the user project"
  },
  "project_is_running_or_being_deleted": {
    "zh-CN": "项目正在运行或删除",
    "en": "Project is running or being deleted"
  },
  "open_a_project_first": {
    "zh-CN": "请先打开项目",
    "en": "Open a project first"
  },
  "redone": {
    "zh-CN": "已重做",
    "en": "Redone"
  },
  "undone": {
    "zh-CN": "已撤销",
    "en": "Undone"
  },
  "enter_valid_parameter_json_before_leaving_this": {
    "zh-CN": "请填写有效参数后再离开子流程",
    "en": "Enter valid parameter JSON before leaving this subflow"
  },
  "discard_unsaved_changes_and_open_this_project": {
    "zh-CN": "放弃未保存的修改并打开项目？",
    "en": "Discard unsaved changes and open this project?"
  },
  "discard_unsaved_changes_and_create_a_project": {
    "zh-CN": "放弃未保存的修改并新建项目？",
    "en": "Discard unsaved changes and create a project?"
  },
  "enter_valid_parameter_json_before_saving": {
    "zh-CN": "请填写有效参数后再保存",
    "en": "Enter valid parameter JSON before saving"
  },
  "project_save_is_already_in_progress": {
    "zh-CN": "正在保存项目，请稍候",
    "en": "Project save is already in progress"
  },
  "project_and_layout_saved": {
    "zh-CN": "项目已保存",
    "en": "Project and layout saved"
  },
  "project_saved_package_list_refresh_failed": {
    "zh-CN": "项目已保存，文件列表刷新失败：{0}",
    "en": "Project saved; package list refresh failed: {0}"
  },
  "enter_valid_parameter_json_before_copying": {
    "zh-CN": "请填写有效参数后再复制",
    "en": "Enter valid parameter JSON before copying"
  },
  "project_copied_with_independent_inputs_and_no": {
    "zh-CN": "项目已复制",
    "en": "Project copied with independent inputs and no runs"
  },
  "save_changes_and_run": {
    "zh-CN": "保存修改并运行？",
    "en": "Save changes and run?"
  },
  "project_changed_while_saving_save_again_before": {
    "zh-CN": "保存期间项目已改变，请重新保存后运行",
    "en": "Project changed while saving; save again before running"
  },
  "running_on_the_backend": {
    "zh-CN": "正在运行…",
    "en": "Running on the backend…"
  },
  "continuing_the_original_call_on_the_backend": {
    "zh-CN": "正在继续运行…",
    "en": "Continuing the original call on the backend…"
  },
  "cancellation_requested_waiting_for_the_backend": {
    "zh-CN": "正在停止…",
    "en": "Cancellation requested; waiting for the backend…"
  },
  "delete_project_and_its_stored_packages_and": {
    "zh-CN": "删除项目“{0}”及其文件和运行记录？{1}删除后无法恢复。",
    "en": "Delete project \"{0}\" and its stored packages and runs?{1} This cannot be undone."
  },
  "added_to": {
    "zh-CN": "已采用到 {0}",
    "en": "Added to {0}"
  },
  "subflow_changed_start_the_operation_again": {
    "zh-CN": "子流程已改变，请重试",
    "en": "Subflow changed; start the operation again"
  },
  "open_an_idle_project_first": {
    "zh-CN": "请先打开未运行的项目",
    "en": "Open an idle project first"
  },
  "connect_different_nodes_use_explicit_subflow_feedback": {
    "zh-CN": "请选择不同节点；重复执行请使用子流程反馈",
    "en": "Connect different nodes; use explicit subflow feedback for repetition"
  },
  "this_connection_already_exists": {
    "zh-CN": "连线已存在",
    "en": "This connection already exists"
  },
  "port_formats_do_not_match_select_an": {
    "zh-CN": "端口格式不匹配，请添加转换节点",
    "en": "Port formats do not match; select an explicit conversion node"
  },
  "cardinality_mismatch_a_many_output_requires_a": {
    "zh-CN": "多个输出需要连接可接收多个数据包的输入",
    "en": "Cardinality mismatch: a many output requires a many input"
  },
  "input_accepts_only_one_package": {
    "zh-CN": "此输入只接受一个数据包",
    "en": "Input accepts only one package"
  },
  "preview_cancelled": {
    "zh-CN": "预览已取消",
    "en": "Preview cancelled"
  },
  "editor_workspace_closed_reopen_it_to_apply": {
    "zh-CN": "编辑器已关闭，请重新打开",
    "en": "Editor workspace closed; reopen it to apply changes"
  },
  "project_changed_reopen_this_editor": {
    "zh-CN": "项目已切换，请重新打开编辑器",
    "en": "Project changed; reopen this editor"
  },
  "editor_draft_changed_preview_the_current_node": {
    "zh-CN": "草稿已改变，请重新预览",
    "en": "Editor draft changed; preview the current node again"
  },
  "project_is_running_saving_or_being_deleted": {
    "zh-CN": "项目正在运行、保存或删除",
    "en": "Project is running, saving or being deleted"
  },
  "editor_workspace_closed": {
    "zh-CN": "编辑器已关闭",
    "en": "Editor workspace closed"
  },
  "selected_packages_are_unavailable": {
    "zh-CN": "所选文件不可用：{0}",
    "en": "Selected packages are unavailable: {0}"
  },
  "connected_input_requires_a_delivered_package_selected": {
    "zh-CN": "请先运行上游节点，再选择已生成的结果",
    "en": "Connected input requires a delivered package selected explicitly; prepare and run the source group first"
  },
  "no_delivered_package_is_selected_for": {
    "zh-CN": "尚未为 {0}{1} 选择输入文件",
    "en": "No delivered package is selected for {0}{1}"
  },
  "run": {
    "zh-CN": "运行 {0} · {1} · {2}",
    "en": "Run {0} · {1} · {2}"
  },
  "project_is_running_wait_before_accepting_edits": {
    "zh-CN": "项目正在运行，请结束后再采用编辑",
    "en": "Project is running; wait before accepting edits"
  },
  "accept_one_editor_document_or_input_at": {
    "zh-CN": "请每次采用一个编辑结果或输入",
    "en": "Accept one editor document or input at a time"
  },
  "connection_replacement_requires_an_explicit_input_update": {
    "zh-CN": "替换连线时需指定输入",
    "en": "Connection replacement requires an explicit input update"
  },
  "replacement_connection_does_not_match_the_current": {
    "zh-CN": "替换连线与目标端口不匹配",
    "en": "Replacement connection does not match the current target declaration"
  },
  "duplicate_replacement_connection": {
    "zh-CN": "替换连线重复",
    "en": "Duplicate replacement connection"
  },
  "unknown_input_port": {
    "zh-CN": "未知输入端口：{0}",
    "en": "Unknown input port: {0}"
  },
  "input_accepts_only_one_package_explicitly_replace": {
    "zh-CN": "此输入只接受一个数据包，请先替换原连接",
    "en": "Input accepts only one package; explicitly replace its connection"
  },
  "input_package_is_unavailable_or_has_an": {
    "zh-CN": "输入文件不可用或格式不匹配：{0}",
    "en": "Input package is unavailable or has an unaccepted format: {0}"
  },
  "preview_has_ended_create_a_new_preview": {
    "zh-CN": "预览已结束，请重新预览",
    "en": "Preview has ended; create a new preview"
  },
  "unknown_delivery_input_port": {
    "zh-CN": "未知交付输入端口",
    "en": "Unknown delivery input port"
  },
  "this_node_does_not_accept_editor_documents": {
    "zh-CN": "此节点不接收编辑文档",
    "en": "This node does not accept editor documents"
  },
  "editor_document_format_does_not_match_this": {
    "zh-CN": "编辑文档格式与节点不匹配",
    "en": "Editor document format does not match this node"
  },
  "previous_node": {
    "zh-CN": "历史节点",
    "en": "Previous node"
  },
  "round": {
    "zh-CN": " · 第 ",
    "en": " · Round "
  },
  "message": {
    "zh-CN": " 轮",
    "en": " "
  },
  "message_2": {
    "zh-CN": " 项",
    "en": " "
  },
  "run_2": {
    "zh-CN": "第 {0} 次 · {1}{2}",
    "en": "Run {0} · {1}{2}"
  },
  "input_files": {
    "zh-CN": "输入文件",
    "en": "Input files"
  },
  "applied_to": {
    "zh-CN": "已用于 ",
    "en": "Applied to "
  },
  "node": {
    "zh-CN": "节点",
    "en": "Node"
  },
  "this_input_is_connected_to_the_subflow": {
    "zh-CN": "此输入已有子流程边界连接",
    "en": "This input is connected to the subflow boundary"
  },
  "this_node_has_been_deleted_from_the": {
    "zh-CN": "当前画布中已删除此节点",
    "en": "This node has been deleted from the canvas"
  },
  "for_each": {
    "zh-CN": "逐项处理",
    "en": "For each"
  },
  "repeat": {
    "zh-CN": "循环",
    "en": "Repeat"
  },
  "project": {
    "zh-CN": "项目",
    "en": "Project"
  },
  "new_open": {
    "zh-CN": "新建 / 打开",
    "en": "New / Open"
  },
  "duplicate_project": {
    "zh-CN": "复制项目",
    "en": "Duplicate project"
  },
  "modules": {
    "zh-CN": "模块管理",
    "en": "Modules"
  },
  "more_imports": {
    "zh-CN": "更多导入",
    "en": "More imports"
  },
  "delete_project": {
    "zh-CN": "删除项目",
    "en": "Delete project"
  },
  "unsaved": {
    "zh-CN": "未保存",
    "en": "Unsaved"
  },
  "undo": {
    "zh-CN": "撤销",
    "en": "Undo"
  },
  "redo": {
    "zh-CN": "重做",
    "en": "Redo"
  },
  "results": {
    "zh-CN": "结果",
    "en": "Results"
  },
  "saving": {
    "zh-CN": "保存中…",
    "en": "Saving…"
  },
  "save": {
    "zh-CN": "保存",
    "en": "Save"
  },
  "run_3": {
    "zh-CN": "▷ 运行",
    "en": "▷ Run"
  },
  "stop": {
    "zh-CN": "停止",
    "en": "Stop"
  },
  "dismiss": {
    "zh-CN": "关闭提示",
    "en": "Dismiss"
  },
  "close_projects": {
    "zh-CN": "关闭项目",
    "en": "Close projects"
  },
  "open_example": {
    "zh-CN": "打开示例",
    "en": "Open example"
  },
  "project_name": {
    "zh-CN": "项目名称",
    "en": "Project name"
  },
  "create": {
    "zh-CN": "新建",
    "en": "Create"
  },
  "close_modules": {
    "zh-CN": "关闭模块管理",
    "en": "Close modules"
  },
  "close_import": {
    "zh-CN": "关闭导入",
    "en": "Close import"
  },
  "loading_input_files": {
    "zh-CN": "正在载入输入文件…",
    "en": "Loading input files…"
  },
  "node_canvas": {
    "zh-CN": "节点画布",
    "en": "Node canvas"
  },
  "subflow_navigation": {
    "zh-CN": "子流程导航",
    "en": "Subflow navigation"
  },
  "canvas": {
    "zh-CN": "主画布",
    "en": "Canvas"
  },
  "failed_view": {
    "zh-CN": "失败 · 查看",
    "en": "Failed · View"
  },
  "results_2": {
    "zh-CN": "结果 ↗",
    "en": "Results ↗"
  },
  "open": {
    "zh-CN": "打开 {0}",
    "en": "Open {0}"
  },
  "tool": {
    "zh-CN": "工具",
    "en": "Tool"
  },
  "tool_2": {
    "zh-CN": "{0} 工具",
    "en": "{0} tool"
  },
  "select_tool": {
    "zh-CN": "选择工具",
    "en": "Select tool"
  },
  "editor_draft_changed_reopen_the_current_node": {
    "zh-CN": "草稿已改变，请重新打开节点",
    "en": "Editor draft changed; reopen the current node"
  },
  "the_module_for_this_node_is_not": {
    "zh-CN": "此节点所需模块未安装。",
    "en": "The module for this node is not installed."
  },
  "open_subflow": {
    "zh-CN": "打开子流程",
    "en": "Open subflow"
  },
  "parameters": {
    "zh-CN": "计算参数",
    "en": "Parameters"
  },
  "input_sources": {
    "zh-CN": "输入来源",
    "en": "Input sources"
  },
  "connected": {
    "zh-CN": "已连接：",
    "en": "Connected: "
  },
  "upstream_node": {
    "zh-CN": "上游节点",
    "en": "Upstream node"
  },
  "use_connection": {
    "zh-CN": "使用连线",
    "en": "Use connection"
  },
  "not_selected": {
    "zh-CN": "未选择",
    "en": "Not selected"
  },
  "close_results": {
    "zh-CN": "关闭结果",
    "en": "Close results"
  },
  "select_run": {
    "zh-CN": "选择运行",
    "en": "Select run"
  },
  "run_4": {
    "zh-CN": "第",
    "en": "Run"
  },
  "message_3": {
    "zh-CN": "次运行 ·",
    "en": " ·"
  },
  "select_result_node": {
    "zh-CN": "选择结果节点",
    "en": "Select result node"
  },
  "locate_node": {
    "zh-CN": "定位节点",
    "en": "Locate node"
  },
  "continue": {
    "zh-CN": "继续运行",
    "en": "Continue"
  },
  "select_output": {
    "zh-CN": "选择输出",
    "en": "Select output"
  },
  "output": {
    "zh-CN": "输出",
    "en": "Output"
  },
  "no_results_yet": {
    "zh-CN": "暂无结果",
    "en": "No results yet"
  },
  "view_as": {
    "zh-CN": "查看方式",
    "en": "View as"
  },
  "download_zip": {
    "zh-CN": "下载 ZIP",
    "en": "Download ZIP"
  },
  "use_in_a_node": {
    "zh-CN": "用于后续节点",
    "en": "Use in a node"
  },
  "target_node": {
    "zh-CN": "接收节点",
    "en": "Target node"
  },
  "select_node": {
    "zh-CN": "选择节点",
    "en": "Select node"
  },
  "target_port": {
    "zh-CN": "接收端口",
    "en": "Target port"
  },
  "select_input": {
    "zh-CN": "选择输入",
    "en": "Select input"
  },
  "replaces_the_current_source_for_this_input": {
    "zh-CN": "采用后替换此输入的现有来源。",
    "en": "Replaces the current source for this input."
  },
  "apply": {
    "zh-CN": "采用",
    "en": "Apply"
  },
  "use_in_another_project": {
    "zh-CN": "采用到其他项目",
    "en": "Use in another project"
  },
  "target_project": {
    "zh-CN": "目标项目",
    "en": "Target project"
  },
  "select_project": {
    "zh-CN": "选择项目",
    "en": "Select project"
  },
  "applying": {
    "zh-CN": "采用中…",
    "en": "Applying…"
  },
  "files": {
    "zh-CN": "文件",
    "en": "Files"
  }
};
const t = i18n.translator(messages)
import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { DisplayText, Edge, Flow, FlowNode, Scope, ModuleHost, PackageInfo, EditorContext, EditorUpdate } from '@protein-workbench/module-ui'
import { client, type Catalog, type Project, type Run } from './host-client'
import { loadExtensions, type LoadedExtensions } from './host-ui'
import { ParameterFields } from './ParameterFields'
import { ModuleManagement } from './ModuleManagement'
import { WorkflowCanvas, connectionProblem, CanvasToolPicker } from './WorkflowCanvas'
import { ScopeEditor } from './ScopeEditor'
import { callLabel, callPath, copyNode, declarationFor, flowAt, replaceFlow } from './flow-model'

class ExtensionBoundary extends Component<{ children: ReactNode; onReturn?: () => void }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <div role="alert">{t("module_interface_failed")} {this.state.error}{this.props.onReturn && <button onClick={this.props.onReturn}>{t("back_to_canvas")}</button>}</div> : this.props.children }
}

function frozenParameterCopy(parameters: Record<string, unknown>) {
  const snapshot = structuredClone(parameters)
  function freeze(value: unknown) {
    if (value && typeof value === 'object') {
      Object.values(value).forEach(freeze)
      Object.freeze(value)
    }
  }
  freeze(snapshot)
  return snapshot
}

const statusLabel = (status: string) => ({succeeded:t("completed"),failed:t("failed"),cancelled:t("cancelled"),running:t("running"),pending:t("pending"),blocked:t("not_run"),configuration_blocked:t("needs_configuration")}[status] ?? status)

export default function App() {
  const [{ catalog: sourceCatalog, extensions, projects }, setSnapshot] = useState<{ catalog: Catalog<DisplayText>; extensions: LoadedExtensions; projects: Project[] }>({ catalog: { nodes: [], modules: [] }, extensions: {}, projects: [] })
  const locale = useLocale()
  const catalog = useMemo(() => localizeCatalog(sourceCatalog), [sourceCatalog, locale])
  const moduleEpoch = useRef(0)
  const projectEpoch = useRef(0)
  const projectRead = useRef<object | null>(null)
  const projectReadQueued = useRef(false)
  const invalidateRefresh = () => { moduleEpoch.current += 1 }
  const [project, setProject] = useState<Project | null>(null)
  const [managementOpen, setManagementOpen] = useState(false)
  const [resultsOpen, setResultsOpen] = useState(false)
  const [focusRequest,setFocusRequest]=useState<{id:string;token:number}>()
  const [projectMenu, setProjectMenu] = useState(false)
  const [modulesOpen, setModulesOpen] = useState(false)
  const [importAction, setImportAction] = useState('')
  const [resultRun, setResultRun] = useState('')
  const [resultCall, setResultCall] = useState('')
  const [useTarget, setUseTarget] = useState('')
  const [usePort, setUsePort] = useState('')
  const [workspace, setWorkspace] = useState<{ editor: NonNullable<LoadedExtensions['editors']>[number]; context: EditorContext } | null>(null)
  const workspaceDirty = useRef(false)
  const workspaceToken = useRef<symbol | null>(null)
  const workspaceInteractions = useRef(new Set<string>())
  const workspaceRequests = useRef(new Set<AbortController>())
  const undoStack = useRef<Project[]>([])
  const redoStack = useRef<Project[]>([])
  function releaseWorkspaceOperations() {
    workspaceToken.current = null
    for (const request of workspaceRequests.current) request.abort()
    workspaceRequests.current.clear()
    for (const id of workspaceInteractions.current) { temporaryInteractions.current.delete(id); void client.cancelInteraction(id).catch(()=>{}) }
    workspaceInteractions.current.clear()
  }
  function closeWorkspace() {
    releaseWorkspaceOperations(); workspaceDirty.current = false; setWorkspace(null)
  }
  function openWorkspace(node: FlowNode, editor: NonNullable<LoadedExtensions['editors']>[number]) {
    const token = Symbol('editor workspace');workspaceToken.current=token;workspaceDirty.current=false
    setWorkspace({editor,context:editorContext(node,token)})
  }

  const currentProject = useRef<Project | null>(null)
  const [scopePath, setScopePath] = useState<string[]>([])
  const scopePathNow = useRef<string[]>([])
  const activeFlow = project ? flowAt(project.flow, scopePath) ?? project.flow : undefined
  const activeScope = project && scopePath.length ? flowAt(project.flow, scopePath.slice(0, -1))?.nodes.find(node => node.id === scopePath.at(-1)) : undefined
  const liveProject = useRef(true)
  const projectSession = useRef(0)
  const opening = useRef(0)
  const runningNow = useRef(false)
  const submittingRun = useRef(false)
  const runOperationEpoch = useRef(0)
  const [{dirty}, setDirty] = useState({dirty: false, revision: 0})
  const dirtyNow = useRef(false)
  const draftRevision = useRef(0)
  const parameterSnapshots = useRef(new WeakMap<Record<string, unknown>, Record<string, unknown>>())
  function markDirty(value: boolean) { if (value) draftRevision.current += 1; dirtyNow.current = value; setDirty({dirty: value, revision: draftRevision.current}) }
  const canvas = useRef<HTMLElement>(null)
  const [saving, setSaving] = useState(false)
  const savingNow = useRef(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [moduleError, setModuleError] = useState('')
  const [projectListError, setProjectListError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),3200);return()=>clearTimeout(timer)},[notice])
  const [projectName, setProjectName] = useState(t("new_project"))
  const draftInputs = useRef<PackageInfo[]>([])
  const pendingInputTransfers = useRef(new Set<{ session: number }>())
  const [inputTransfers, setInputTransfers] = useState(0)
  function ensureInputsTransferred(current: Project) {
    if (current.tutorial && [...pendingInputTransfers.current].some(transfer => transfer.session === projectSession.current)) throw new Error(t("wait_for_teaching_input_transfers_to_finish"))
  }
  async function discardDraftInputs() {
    for (const token of temporaryInteractions.current) void client.cancelInteraction(token).catch(() => {})
    temporaryInteractions.current.clear()
    const inputs = draftInputs.current; draftInputs.current = []
    await Promise.all(inputs.map(input => client.discardDraftInput(input.id).catch(fail)))
  }
  const temporaryInteractions = useRef(new Set<string>())
  const packagesNow = useRef<PackageInfo[]>([])
  const [packages, setPackages] = useState<PackageInfo[]>([])
  packagesNow.current = packages
  const [selectedPackage, setSelectedPackage] = useState('')
  const [viewer, setViewer] = useState('')
  const [adoptionTarget, setAdoptionTarget] = useState('')
  const [adopting, setAdopting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deletingProject = useRef('')
  const projectBusy = running || (deleting && deletingProject.current === project?.id)
  const locked = projectBusy || (saving && !!project?.tutorial)
  const waitingForTeachingInputs = !!project?.tutorial && inputTransfers > 0
  const [runs, setRuns] = useState<Run[]>([])
  const cancellableRuns = runs.filter(item => item.status === 'running')
  const [connection, setConnection] = useState<Edge>({ source: '', source_port: '', target: '', target_port: '' })
  const fail = (failure: unknown) => { if (liveProject.current) setError(i18n.error(failure)) }
  const errorText = i18n.error
  async function refreshProjects() {
    const epoch = ++projectEpoch.current
    const current = () => liveProject.current && epoch === projectEpoch.current
    const read = {}
    projectRead.current = read
    try {
      const nextProjects = await client.projects()
      if (!current()) return
      setSnapshot(previous => current() ? { ...previous, projects: nextProjects } : previous)
      setProjectListError('')
    } catch (failure) { if (current()) setProjectListError(t("project_list_refresh_failed", {"0": errorText(failure)})) }
    finally { if (projectRead.current === read) projectRead.current = null }
  }
  function projectChanged() {
    projectEpoch.current += 1
    if (!projectRead.current) return
    // A confirmed write supersedes this read immediately, even if it never settles.
    projectRead.current = null
    if (projectReadQueued.current) return
    projectReadQueued.current = true
    queueMicrotask(() => {
      projectReadQueued.current = false
      if (liveProject.current && !projectRead.current) void refreshProjects()
    })
  }
  function commitProject(saved: Project) {
    if (!liveProject.current) return
    projectChanged()
    setSnapshot(previous => ({ ...previous, projects: previous.projects.some(item => item.id === saved.id) ? previous.projects.map(item => item.id === saved.id ? saved : item) : [...previous.projects, saved] }))
  }
  function removeProject(id: string) {
    if (!liveProject.current) return
    projectChanged()
    setSnapshot(previous => ({ ...previous, projects: previous.projects.filter(item => item.id !== id) }))
  }
  async function refresh() {
    void refreshProjects()
    const request = ++moduleEpoch.current
    const current = () => liveProject.current && request === moduleEpoch.current
    let next: Catalog<DisplayText> | undefined
    try {
      next = await client.catalog()
      if (!current()) return
      const nextExtensions = await loadExtensions(next.modules)
      if (!current()) return
      const loaded = next
      setSnapshot(previous => current() ? { ...previous, catalog: loaded, extensions: nextExtensions } : previous)
      setModuleError('')
    } catch (failure) {
      if (!current()) return
      const loaded = next
      setSnapshot(previous => current() ? { ...previous, catalog: loaded ?? previous.catalog, extensions: {} } : previous)
      setModuleError(t("module_refresh_failed", {"0": errorText(failure)}))
    }
  }
  useEffect(() => { refresh().then(() => openTutorial(true)).catch(fail) }, [])
  useEffect(() => {
    liveProject.current = true
    function dispose() {
      if (!liveProject.current) return
      liveProject.current = false; projectSession.current += 1; opening.current += 1; currentProject.current = null
      releaseWorkspaceOperations()
      void discardDraftInputs()
    }
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirtyNow.current || workspaceDirty.current) { event.preventDefault(); event.returnValue = '' } }
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) dispose() }
    window.addEventListener('beforeunload', beforeUnload)
    window.addEventListener('pagehide', pageHide)
    return () => { window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('pagehide', pageHide); dispose() }
  }, [])
  function change(update: (current: Project) => Project) {
    if (!liveProject.current) throw new Error(t("project_changed_start_the_operation_again"))
    if (savingNow.current && currentProject.current?.tutorial) throw new Error(t("teaching_draft_is_saving_wait_for_the"))
    if (runningNow.current || deletingProject.current === currentProject.current?.id) throw new Error(t("project_is_running_or_being_deleted"))
    if (!currentProject.current) throw new Error(t("open_a_project_first"))
    const previous = currentProject.current
    currentProject.current = update(previous)
    undoStack.current.push(previous); redoStack.current = []
    setProject(currentProject.current); markDirty(true); setNotice('')
  }
  function restoreHistory(redo = false) {
    if (locked || saving || workspace || !currentProject.current) return
    const source = redo ? redoStack.current : undoStack.current
    const target = redo ? undoStack.current : redoStack.current
    const previous = source.pop()
    if (!previous || previous.id !== currentProject.current.id) return
    target.push(currentProject.current); currentProject.current = previous
    let path = scopePathNow.current
    while (path.length && !flowAt(previous.flow, path)) path = path.slice(0, -1)
    if (path.length !== scopePathNow.current.length) {
      scopePathNow.current = path; setScopePath(path)
      setConnection({source:'',source_port:'',target:'',target_port:''})
    }
    setProject(previous); markDirty(true); setNotice(redo ? t("redone") : t("undone"))
  }
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z' || (event.target instanceof HTMLElement && event.target.closest('input,textarea,select,[contenteditable=true]'))) return
      if (workspace) return
      event.preventDefault(); restoreHistory(event.shiftKey)
    }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [locked, saving, workspace])
  function changeFlow(update: (flow: Flow) => Flow, path = scopePathNow.current) {
    change(current => ({...current, flow: replaceFlow(current.flow, path, update)}))
  }
  function changeScope(scope: Scope) {
    if (!activeScope) return
    const id = activeScope.id, parentPath = scopePath.slice(0, -1)
    change(current => {
      let flow = replaceFlow(current.flow, parentPath, body => ({
        ...body,
        nodes: body.nodes.map(node => node.id === id ? {...node, scope, inputs: Object.fromEntries(Object.entries(node.inputs).filter(([port]) => scope.inputs[port]))} : node),
        edges: body.edges.filter(edge => (edge.source !== id || scope.outputs[edge.source_port]) && (edge.target !== id || scope.inputs[edge.target_port])),
      }))
      if (parentPath.length) flow = replaceFlow(flow, parentPath.slice(0, -1), body => ({...body, nodes: body.nodes.map(node => node.id === parentPath.at(-1) && node.scope ? {
        ...node, scope: {...node.scope,
          input_bindings: node.scope.input_bindings.filter(binding => binding.node !== id || scope.inputs[binding.port]),
          output_bindings: node.scope.output_bindings.filter(binding => binding.node !== id || scope.outputs[binding.port]),
        },
      } : node)}))
      return {...current, flow}
    })
  }
  function navigateScope(path: string[]) {
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); fail(new Error(t("enter_valid_parameter_json_before_leaving_this"))); return }
    if (!currentProject.current || !flowAt(currentProject.current.flow, path)) return
    scopePathNow.current = path; setScopePath(path); setConnection({source:'',source_port:'',target:'',target_port:''})
  }
  async function openTutorial(automatic = false) {
    if (!liveProject.current) return
    const request = opening.current
    const example = await client.tutorial()
    if (!liveProject.current) return
    if (automatic && (request !== opening.current || currentProject.current)) return
    await open(example.id, undefined, automatic)
  }
  async function open(id: string, approvedRevision?: number, preserveError = false) {
    if (!liveProject.current) return
    if (runningNow.current || (dirtyNow.current && draftRevision.current !== approvedRevision && !window.confirm(t("discard_unsaved_changes_and_open_this_project")))) return
    const leavingRevision = draftRevision.current
    const request = ++opening.current
    const [next, files, history] = await Promise.all([client.project(id), client.packages(id), client.runs(id)])
    if (!liveProject.current || request !== opening.current) return
    if (dirtyNow.current && draftRevision.current !== leavingRevision && !window.confirm(t("discard_unsaved_changes_and_open_this_project"))) return
    void discardDraftInputs()
    closeWorkspace(); undoStack.current = []; redoStack.current = []
    projectSession.current += 1; setInputTransfers(0); currentProject.current = next; setProject(next); markDirty(false); setNotice('')
    runningNow.current = !!next.running || history.some(run => run.status === 'running'); setRunning(runningNow.current)
    scopePathNow.current = []; setScopePath([]); setConnection({source:'',source_port:'',target:'',target_port:''}); setPackages(files); setRuns(history); setResultRun(''); setResultCall(''); setUseTarget(''); setUsePort(''); setSelectedPackage(''); setViewer(''); setAdoptionTarget(''); if (!preserveError) setError('')
    return true
  }
  async function createProject() {
    if (dirtyNow.current && !window.confirm(t("discard_unsaved_changes_and_create_a_project"))) return
    const approvedRevision = draftRevision.current
    const session = projectSession.current, openedAt = opening.current
    setError('')
    const next = await client.createProject(projectName)
    commitProject(next)
    if (session === projectSession.current && openedAt === opening.current) await open(next.id, approvedRevision, true)
  }
  async function save() {
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); throw new Error(t("enter_valid_parameter_json_before_saving")) }
    const snapshot = currentProject.current
    if (!snapshot) throw new Error(t("open_a_project_first"))
    if (savingNow.current) throw new Error(t("project_save_is_already_in_progress"))
    ensureInputsTransferred(snapshot)
    const session = projectSession.current
    const revision = draftRevision.current
    savingNow.current = true; setSaving(true); setError('')
    try {
      const saved = snapshot.tutorial ? await client.copy(snapshot, projectName, draftInputs.current.map(input => input.id)) : await client.save(snapshot)
      if (!liveProject.current) return false
      commitProject(saved)
      if (currentProject.current !== snapshot || draftRevision.current !== revision) return false
      if (snapshot.tutorial) {
        projectSession.current += 1; setPackages([]); setRuns([]); setSelectedPackage(''); setViewer('')
        void discardDraftInputs()
      }
      currentProject.current = saved; setProject(saved); markDirty(false); setNotice(t("project_and_layout_saved"))
      if (snapshot.tutorial) {
        const target = { projectId: saved.id, session: projectSession.current, epoch: runOperationEpoch.current }
        const openedAt = opening.current
        const current = () => liveProject.current && currentProject.current === saved && currentRunOperation(target) && opening.current === openedAt
        void client.packages(saved.id).then(files => { if (current()) setPackages(files) }).catch(failure => {
          if (current()) fail(new Error(t("project_saved_package_list_refresh_failed", {"0": failure instanceof Error ? failure.message : String(failure)})))
        })
      }
      return true
    } catch (failure) {
      if (session !== projectSession.current) return false
      throw failure
    } finally { savingNow.current = false; setSaving(false) }
  }
  async function copyProject() {
    if (savingNow.current || runningNow.current || !currentProject.current) return
    if (document.activeElement instanceof HTMLElement && canvas.current?.contains(document.activeElement)) document.activeElement.blur()
    const invalid = canvas.current?.querySelector<HTMLTextAreaElement>('textarea:invalid')
    if (invalid) { invalid.reportValidity(); throw new Error(t("enter_valid_parameter_json_before_copying")) }
    const snapshot = currentProject.current
    ensureInputsTransferred(snapshot)
    const session = projectSession.current
    const revision = draftRevision.current
    savingNow.current = true; setSaving(true); setError('')
    try {
      const copied = await client.copy(snapshot, projectName, snapshot.tutorial ? draftInputs.current.map(input => input.id) : [])
      if (!liveProject.current) return
      commitProject(copied)
      if (session !== projectSession.current || draftRevision.current !== revision) return
      if (await open(copied.id, revision)) setNotice(t("project_copied_with_independent_inputs_and_no"))
    } catch (failure) { if (session === projectSession.current) throw failure }
    finally { savingNow.current = false; setSaving(false) }
  }
  function currentRunOperation(target: { projectId: string; session: number; epoch: number }) {
    return currentProject.current?.id === target.projectId && projectSession.current === target.session && runOperationEpoch.current === target.epoch
  }
  async function run() {
    if (!project) return
    const epoch = ++runOperationEpoch.current
    const session = projectSession.current
    if (dirtyNow.current || currentProject.current?.tutorial) {
      if (!window.confirm(t("save_changes_and_run"))) return
      const saved = await save()
      if (!saved && session !== projectSession.current) return
      if (!saved) throw new Error(t("project_changed_while_saving_save_again_before"))
    }
    const runProject = currentProject.current
    if (!runProject || epoch !== runOperationEpoch.current) return
    const target = { projectId: runProject.id, session: projectSession.current, epoch }
    opening.current += 1; submittingRun.current = true
    runningNow.current = true; setRunning(true); setError(''); setNotice(t("running_on_the_backend"))
    try {
      const result = await client.run(target.projectId)
      if (!currentRunOperation(target)) return
      if (result.status !== 'running') {
        const files = await client.packages(target.projectId)
        if (!currentRunOperation(target)) return
        setPackages(files)
      }
      setRuns(items => [...items.filter(item => item.id !== result.id), result])
      runningNow.current = result.status === 'running'; setRunning(runningNow.current)
      setNotice(`Run ${result.status}`)
    } catch (failure) {
      // A lost submission response leaves the lock until a current poll confirms state.
      if (currentRunOperation(target)) fail(failure)
    } finally { if (currentRunOperation(target)) submittingRun.current = false }
  }
  async function continueRun(runId: string, nodeId: string) {
    const current = currentProject.current
    if (!current || runningNow.current || savingNow.current || submittingRun.current) return
    const target = { projectId: current.id, session: projectSession.current, epoch: ++runOperationEpoch.current }
    opening.current += 1; submittingRun.current = true
    runningNow.current = true; setRunning(true); setError(''); setNotice(t("continuing_the_original_call_on_the_backend"))
    try {
      const result = await client.continueRun(runId, nodeId)
      if (!currentRunOperation(target)) return
      if (result.status !== 'running') {
        const files = await client.packages(target.projectId)
        if (!currentRunOperation(target)) return
        setPackages(files)
      }
      setRuns(items => [...items.filter(item => item.id !== result.id), result])
      runningNow.current = result.status === 'running'; setRunning(runningNow.current)
      setNotice(`Run ${result.status}`)
    } catch (failure) { if (currentRunOperation(target)) fail(failure) }
    finally { if (currentRunOperation(target)) submittingRun.current = false }
  }
  async function cancelRun() {
    const current = currentProject.current
    if (!current || submittingRun.current || !cancellableRuns.length) return
    const target = { projectId: current.id, session: projectSession.current, epoch: ++runOperationEpoch.current }
    submittingRun.current = true; runningNow.current = true; setRunning(true)
    try {
      await Promise.all(cancellableRuns.map(item => client.cancelRun(item.id)))
      if (!currentRunOperation(target)) return
      setNotice(t("cancellation_requested_waiting_for_the_backend"))
    } catch (failure) { if (currentRunOperation(target)) fail(failure) }
    finally { if (currentRunOperation(target)) submittingRun.current = false }
  }
  useEffect(() => {
    if (!project) return
    const projectId = project.id
    const session = projectSession.current
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      const target = { projectId, session, epoch: runOperationEpoch.current }
      const current = () => !stopped && currentRunOperation(target)
      try {
        if (submittingRun.current) return
        const history = await client.runs(projectId)
        if (!current()) return
        const active = history.some(item => item.status === 'running')
        const wasRunning = runningNow.current
        let files: PackageInfo[] | undefined
        if (active || wasRunning) {
          files = await client.packages(projectId)
          if (!current()) return
        }
        setRuns(history); runningNow.current = active; setRunning(active)
        if (files) {
          setPackages(files)
          if (!active) setNotice(t('run_finished', {status:statusLabel(history.at(-1)?.status ?? 'succeeded')}))
        }
      } catch (failure) { if (current()) fail(failure) }
      finally { if (!stopped) timer = setTimeout(poll, 500) }
    }
    timer = setTimeout(poll, 500)
    return () => { stopped = true; clearTimeout(timer) }
  }, [project?.id, projectSession.current])

  async function deleteProject() {
    const current = currentProject.current
    if (!current || runningNow.current || savingNow.current || deletingProject.current) return
    const message = t("delete_project_and_its_stored_packages_and", {"0": current.name, "1": dirty ? t('discard_unsaved') : ''})
    if (!window.confirm(message)) return
    const session = projectSession.current
    deletingProject.current = current.id; setDeleting(true); setError('')
    opening.current += 1
    try {
      await client.deleteProject(current.id)
      removeProject(current.id)
      if (session !== projectSession.current) return
      projectSession.current += 1; currentProject.current = null
      setProject(null); markDirty(false); setPackages([]); setRuns([]); setSelectedPackage(''); setViewer(''); setAdoptionTarget('')
      setConnection({ source: '', source_port: '', target: '', target_port: '' })
      setNotice(t("project_deleted", {name:current.name}))
    } catch (failure) { if (session === projectSession.current) fail(failure) }
    finally { deletingProject.current = ''; setDeleting(false) }
  }
  async function adopt() {
    if (!selectedPackage || !adoptionTarget || adopting) return
    const session = projectSession.current
    const targetName = projects.find(item => item.id === adoptionTarget)?.name ?? adoptionTarget
    setAdopting(true); setError('')
    try {
      await client.adopt(adoptionTarget, selectedPackage)
      if (session !== projectSession.current) return
      setNotice(t("added_to", {"0": targetName}))
    } catch (failure) { if (session === projectSession.current) fail(failure) }
    finally { setAdopting(false) }
  }
  const host = useMemo<ModuleHost>(() => {
    const origin = projectSession.current
    const path = scopePath
    function activeProject() {
      if (!liveProject.current || origin !== projectSession.current) throw new Error(t("project_changed_start_the_operation_again"))
      if (scopePathNow.current.join('/') !== path.join('/')) throw new Error(t("subflow_changed_start_the_operation_again"))
      if (savingNow.current && currentProject.current?.tutorial) throw new Error(t("teaching_draft_is_saving_wait_for_the"))
      if (!currentProject.current || runningNow.current || deletingProject.current === currentProject.current.id) throw new Error(t("open_an_idle_project_first"))
      return currentProject.current
    }
    return {
      readOnly: locked || !project,
      async createInput(input) {
        const current = activeProject()
        const transfer = current.tutorial ? { session: origin } : null
        if (transfer) { pendingInputTransfers.current.add(transfer); setInputTransfers(count => count + 1) }
        try {
          const result = await client.createInput(current.id, input)
          if (current.tutorial) {
            try { activeProject() } catch (failure) { await client.discardDraftInput(result.id); throw failure }
            draftInputs.current.push(result)
            markDirty(true)
          }
          activeProject()
          const files = await client.packages(current.id)
          activeProject(); setPackages([...files, ...draftInputs.current]); return result
        } finally {
          if (transfer) {
            pendingInputTransfers.current.delete(transfer)
            if (origin === projectSession.current) setInputTransfers([...pendingInputTransfers.current].filter(item => item.session === origin).length)
          }
        }
      },
      async addNode(node) {
        activeProject()
        const id = crypto.randomUUID(), ownedNode = structuredClone(node)
        changeFlow(flow => ({...flow, nodes:[...flow.nodes,{...ownedNode,id}]}), path); return id
      },
      async connect(edge) {
        const current = activeProject()
        const flow = flowAt(current.flow, path)!
        const source = flow.nodes.find(node => node.id === edge.source)
        const target = flow.nodes.find(node => node.id === edge.target)
        const output = declarationFor(source, catalog)?.outputs[edge.source_port]
        const input = declarationFor(target, catalog)?.inputs[edge.target_port]
        const boundary = path.length ? flowAt(current.flow,path.slice(0,-1))?.nodes.find(node=>node.id===path.at(-1))?.scope : undefined
        if (edge.source === edge.target) throw new Error(t("connect_different_nodes_use_explicit_subflow_feedback"))
        if (flow.edges.some(item => JSON.stringify(item) === JSON.stringify(edge))) throw new Error(t("this_connection_already_exists"))
        if (!output || !input || !input.accepts.includes(output.format)) throw new Error(t("port_formats_do_not_match_select_an"))
        if (input.cardinality === 'one' && output.cardinality === 'many') throw new Error(t("cardinality_mismatch_a_many_output_requires_a"))
        if (input.cardinality === 'one' && (target?.inputs[edge.target_port]?.length || flow.edges.some(item => item.target === edge.target && item.target_port === edge.target_port) || boundary?.input_bindings.some(item=>item.node===edge.target&&item.port===edge.target_port))) throw new Error(t("input_accepts_only_one_package"))
        changeFlow(flow => ({...flow, edges:[...flow.edges,structuredClone(edge)]}), path)
      },
      async preview(interaction, inputs, parameters, options) {
        // The session survives harmless React renders, but never project changes.
        const current = currentProject.current
        if (!current || !liveProject.current || origin !== projectSession.current) throw new Error(t("project_changed_start_the_operation_again"))
        const { id } = await client.beginInteraction(current.id, interaction, inputs, parameters)
        if (!liveProject.current || origin !== projectSession.current) { await client.cancelInteraction(id); throw new Error(t("project_changed_start_the_operation_again")) }
        if (options?.signal?.aborted) { await client.cancelInteraction(id); throw new Error(t("preview_cancelled")) }
        temporaryInteractions.current.add(id)
        const cancel = () => { temporaryInteractions.current.delete(id); void client.cancelInteraction(id).catch(() => {}) }
        options?.signal?.addEventListener('abort', cancel, {once:true})
        try {
          const result = await client.executeInteraction(id)
          if (options?.signal?.aborted) throw new Error(t("preview_cancelled"))
          if (!liveProject.current || origin !== projectSession.current) throw new Error(t("project_changed_start_the_operation_again"))
          return result
        } catch (failure) {
          temporaryInteractions.current.delete(id); await client.cancelInteraction(id).catch(() => {}); throw failure
        } finally { options?.signal?.removeEventListener('abort', cancel) }
      },
      async cancelPreview(id) { temporaryInteractions.current.delete(id); await client.cancelInteraction(id) },
      readPreviewFile: client.readPreviewFile,
      readFile: client.readFile,
    }
  }, [project, locked, sourceCatalog, scopePath])
  function editorContext(node: FlowNode, workspaceSession?: symbol): EditorContext {
    const session = projectSession.current, revision = draftRevision.current, projectId = project!.id
    const path = scopePath
    const declaration = declarationFor(node, catalog)
    function currentTarget() {
      if (workspaceSession && workspaceToken.current !== workspaceSession) throw new Error(t("editor_workspace_closed_reopen_it_to_apply"))
      const current = currentProject.current
      if (!liveProject.current || session !== projectSession.current || current?.id !== projectId) throw new Error(t("project_changed_reopen_this_editor"))
      if (revision !== draftRevision.current || scopePathNow.current.join('/') !== path.join('/') || !flowAt(current.flow, path)?.nodes.some(item => item.id === node.id && item.type === node.type)) throw new Error(t("editor_draft_changed_preview_the_current_node"))
      if (runningNow.current || deletingProject.current === projectId || (savingNow.current && current.tutorial)) throw new Error(t("project_is_running_saving_or_being_deleted"))
      return current
    }
    const edges = activeFlow!.edges.filter(edge => edge.source === node.id || edge.target === node.id)
    const boundaryBindings = activeScope?.scope?.input_bindings.filter(binding=>binding.node===node.id) ?? []
    let parameters = parameterSnapshots.current.get(node.parameters)
    if (!parameters) {
      parameters = frozenParameterCopy(node.parameters)
      parameterSnapshots.current.set(node.parameters, parameters)
    }
    async function workspaceRequest<T>(operation: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
      if (workspaceToken.current !== workspaceSession) throw new Error(t("editor_workspace_closed"))
      const controller = new AbortController()
      workspaceRequests.current.add(controller)
      const abort = () => controller.abort(signal?.reason)
      signal?.addEventListener('abort', abort, {once:true})
      if (signal?.aborted) abort()
      try { return await operation(controller.signal) }
      finally { signal?.removeEventListener('abort', abort); workspaceRequests.current.delete(controller) }
    }
    const editorHost: ModuleHost = workspaceSession ? {...host,
      async preview(interaction, inputs, parameters, options) {
        currentTarget()
        const result=await workspaceRequest(signal=>host.preview(interaction,inputs,parameters,{signal}),options?.signal)
        if(workspaceToken.current!==workspaceSession){await host.cancelPreview(result.id);throw new Error(t("editor_workspace_closed"))}
        workspaceInteractions.current.add(result.id);return result
      },
      readPreviewFile(id, output, key, options) {
        return workspaceRequest(signal=>host.readPreviewFile(id,output,key,{signal}),options?.signal)
      },
      async cancelPreview(id) {workspaceInteractions.current.delete(id);await host.cancelPreview(id)},
    } : host
    return {
      projectId, nodeId: node.id, revision, parameters, bindings: structuredClone(node.inputs), edges: structuredClone(edges), host: editorHost,
      document: packagesNow.current.find(item => item.id === node.document),
      inputs: Object.fromEntries(Object.entries(declaration?.inputs ?? {}).map(([port, input]) => {
        const ids = node.inputs[port] ?? []
        const selected = ids.flatMap(id => packagesNow.current.filter(item => item.id === id))
        const missing = ids.filter(id => !selected.some(item => item.id === id))
        const connected = edges.some(edge => edge.target === node.id && edge.target_port === port) || boundaryBindings.some(binding=>binding.port===port)
        const unavailable = missing.length ? t("selected_packages_are_unavailable", {"0": missing.join(', ')}) : connected ? t("connected_input_requires_a_delivered_package_selected") : !ids.length ? t("no_delivered_package_is_selected_for", {"0": port, "1": input.required ? t('required_suffix') : ''}) : undefined
        const available = runs.flatMap((run, runIndex) => Object.entries(run.nodes).flatMap(([callId, result]) => {
          const sourceId = result.location?.node_id ?? callId
          if (result.status !== 'succeeded' || JSON.stringify(callPath(run, callId)) !== JSON.stringify(path)) return []
          return edges.filter(edge => edge.target === node.id && edge.target_port === port && edge.source === sourceId).flatMap(edge =>
            (result.outputs[edge.source_port] ?? []).flatMap(id => {
              const pkg = packagesNow.current.find(item => item.id === id && input.accepts.includes(item.format))
              return pkg ? [{package: structuredClone(pkg), label: t("run", {"0": runIndex + 1, "1": callLabel(run, callId), "2": edge.source_port})}] : []
            }))
        }))
        return [port, {packages: structuredClone(selected), available, ...(unavailable ? {unavailable} : {})}]
      })),
      async update(update: EditorUpdate) {
        const parameters = update.parameters ? structuredClone(update.parameters) : undefined
        currentTarget()
        if ((await client.project(projectId)).running) throw new Error(t("project_is_running_wait_before_accepting_edits"))
        currentTarget()
        let inputs = { ...node.inputs, ...update.inputs }
        let document = node.document
        if (update.document && update.delivery) throw new Error(t("accept_one_editor_document_or_input_at"))
        const replace = update.replaceConnections ?? []
        const additions = update.connections ?? []
        const changedPorts = new Set([...Object.keys(update.inputs ?? {}), ...(update.delivery ? [update.delivery.port] : [])])
        if (replace.some(port => !changedPorts.has(port))) throw new Error(t("connection_replacement_requires_an_explicit_input_update"))
        const current = currentTarget()
        for (const edge of additions) {
          const source = flowAt(current.flow, path)?.nodes.find(item => item.id === edge.source)
          const output = declarationFor(source, catalog)?.outputs[edge.source_port]
          const input = declaration?.inputs[edge.target_port]
          if (edge.target !== node.id || !replace.includes(edge.target_port) || !input || !output || !input.accepts.includes(output.format) || (input.cardinality === 'one' && output.cardinality === 'many')) throw new Error(t("replacement_connection_does_not_match_the_current"))
        }
        if (new Set(additions.map(edge => JSON.stringify(edge))).size !== additions.length) throw new Error(t("duplicate_replacement_connection"))
        function validateBindings(values: Record<string, string[]>, extra?: PackageInfo) {
          for (const port of changedPorts) {
            const input = declaration?.inputs[port]
            if (!input) throw new Error(t("unknown_input_port", {"0": port}))
            const ids = values[port] ?? []
            const incoming = [...edges.filter(edge => !replace.includes(edge.target_port)), ...additions].filter(edge => edge.target === node.id && edge.target_port === port).length + boundaryBindings.filter(binding=>binding.port===port).length
            if (input.cardinality === 'one' && ids.length + incoming > 1) throw new Error(t("input_accepts_only_one_package_explicitly_replace"))
            for (const id of ids) {
              const pkg = extra?.id === id ? extra : packagesNow.current.find(item => item.id === id)
              if (!pkg || pkg.project_id !== projectId || !input.accepts.includes(pkg.format)) throw new Error(t("input_package_is_unavailable_or_has_an", {"0": port}))
            }
          }
        }
        if (update.delivery || update.document) {
          const delivery = update.delivery ?? update.document!
          if ('interaction' in delivery && !temporaryInteractions.current.has(delivery.interaction)) throw new Error(t("preview_has_ended_create_a_new_preview"))
          if ('port' in delivery) {
            if (!declaration?.inputs[delivery.port]) throw new Error(t("unknown_delivery_input_port"))
            validateBindings({...inputs, [delivery.port]: []})
          } else if (!declaration?.document_format) throw new Error(t("this_node_does_not_accept_editor_documents"))
          const transfer = project!.tutorial ? {session} : null
          if (transfer) { pendingInputTransfers.current.add(transfer); setInputTransfers(count => count + 1) }
          try {
            const received = 'interaction' in delivery ? await client.acceptInteraction(delivery.interaction, delivery.output) : await client.createInput(projectId, delivery.input)
            try {
              if ((await client.project(projectId)).running) throw new Error(t("project_is_running_wait_before_accepting_edits"))
              currentTarget()
            } catch (failure) {
              if (received.project_id === 'tutorial') await client.discardDraftInput(received.id)
              throw failure
            }
            if ('port' in delivery) {
              inputs = {...inputs, [delivery.port]: [received.id]}
              validateBindings(inputs, received)
            } else {
              if (received.project_id !== projectId || received.format !== declaration?.document_format) throw new Error(t("editor_document_format_does_not_match_this"))
              document = received.id
              validateBindings(inputs)
            }
            if (project!.tutorial) draftInputs.current.push(received)
            packagesNow.current = [...packagesNow.current, received]; setPackages(packagesNow.current)
          } finally {
            if (transfer) { pendingInputTransfers.current.delete(transfer); if (session === projectSession.current) setInputTransfers([...pendingInputTransfers.current].filter(item => item.session === session).length) }
          }
        } else validateBindings(inputs)
        currentTarget()
        changeFlow(flow => ({...flow,
          nodes: flow.nodes.map(item => item.id === node.id ? {...item, ...(parameters ? {parameters} : {}), inputs, ...(document ? {document} : {})} : item),
          edges: [...flow.edges.filter(edge => !(edge.target === node.id && replace.includes(edge.target_port))), ...additions],
        }), path)
        const accepted = update.document ?? update.delivery
        if (accepted && 'interaction' in accepted) {
          const token = accepted.interaction
          temporaryInteractions.current.delete(token)
          void client.cancelInteraction(token).catch(() => {})
        }
      },
    }
  }
  const selected = packages.find(item => item.id === selectedPackage)
  const viewers = extensions.viewers?.filter(item => item.formats.includes(selected?.format ?? '')) ?? []
  const activeViewer = viewers.find(item => item.id === viewer) ?? viewers.find(item => item.defaultFor?.includes(selected?.format ?? '')) ?? [...viewers].sort((a,b)=>a.id.localeCompare(b.id))[0]
  const Viewer = activeViewer?.component
  function resultName(run: Run, id: string) {
    const result=run.nodes[id], path=callPath(run,id), original=result?.location?.node_id??id
    const flow=run.flow?flowAt(run.flow,path):project?flowAt(project.flow,path):undefined
    const node=flow?.nodes.find(item=>item.id===original)
    const index=flow?.nodes.findIndex(item=>item.id===original)??-1
    return `${index>=0?String(index+1).padStart(2,'0')+' ':''}${declarationFor(node,catalog)?.name??t("previous_node")}${result?.location?.round?t("round_suffix", {n:result.location.round}):''}${result?.location?.item?t("item_suffix", {n:result.location.item}):''}`
  }
  function packageDescription(pkg: PackageInfo) {
    for (const [index, run] of runs.entries()) for (const [id, result] of Object.entries(run.nodes)) {
      for (const values of Object.values(result.outputs)) if(values.includes(pkg.id))return t("run_2", {"0": index+1, "1": resultName(run,id), "2": values.length>1?' · '+(values.indexOf(pkg.id)+1):''})
    }
    function inputName(flow: Flow):string|undefined {
      for(const node of flow.nodes){if(node.document===pkg.id||Object.values(node.inputs).some(ids=>ids.includes(pkg.id)))return declarationFor(node,catalog)?.name;if(node.scope){const found=inputName(node.scope.body);if(found)return found}}
    }
    return `${project?inputName(project.flow)??t("input_files"):t("input_files")} · ${packages.indexOf(pkg)+1}`
  }
  const viewedRun=runs.find(run=>run.id===resultRun)??(resultRun==='inputs'?undefined:runs.at(-1))
  const viewedCalls=viewedRun?Object.keys(viewedRun.nodes):[]
  const viewedCall=viewedRun?.nodes[resultCall]?resultCall:viewedCalls[0]??''
  const viewedNode=viewedRun?.nodes[viewedCall]
  const resultPackages=viewedRun?Object.entries(viewedNode?.outputs??{}).flatMap(([port,ids])=>ids.flatMap((id,index)=>{const pkg=packages.find(item=>item.id===id);return pkg?[{pkg,port,index}]:[]})):packages.filter(pkg=>!runs.some(run=>Object.values(run.nodes).some(node=>Object.values(node.outputs).some(ids=>ids.includes(pkg.id))))).map((pkg,index)=>({pkg,port:'',index}))
  useEffect(()=>{if(!resultsOpen)return;if(!resultPackages.some(item=>item.pkg.id===selectedPackage)){setSelectedPackage(resultPackages[0]?.pkg.id??'');setViewer('')}},[resultsOpen,viewedRun?.id,viewedCall,packages,selectedPackage])
  function openNodeResults(node: FlowNode) {
    const match=[...runs].reverse().flatMap(run=>Object.entries(run.nodes).filter(([id,result])=>(result.location?.node_id??id)===node.id&&callPath(run,id).join('/')===scopePath.join('/')).map(([id])=>({run,id})))[0]
    setResultRun(match?.run.id??'inputs');setResultCall(match?.id??'');setSelectedPackage(match?Object.values(match.run.nodes[match.id].outputs).flat()[0]??'':node.document??Object.values(node.inputs).flat()[0]??'');setViewer('');setResultsOpen(true)
  }
  async function useResult() {
    const node=activeFlow?.nodes.find(item=>item.id===useTarget)
    if(!node||!selected||!usePort)return
    await editorContext(node).update({inputs:{[usePort]:[selected.id]},replaceConnections:[usePort]})
    setNotice(t("applied_to")+(declarationFor(node,catalog)?.name??t("node")));setUseTarget('');setUsePort('')
  }
  function updateNode(id: string, update: Partial<FlowNode>) {
    const ownedUpdate = update.parameters ? {...update, parameters: structuredClone(update.parameters)} : update
    changeFlow(flow => ({...flow,nodes:flow.nodes.map(node=>node.id===id?{...node,...ownedUpdate}:node)}))
  }

  async function connectCanvas(edge: Edge, replacingIndex?: number) {
    const flow = activeFlow!
    const problem = connectionProblem(flow, catalog, edge, replacingIndex)
    if (problem) throw new Error(problem)
    const input = declarationFor(flow.nodes.find(node => node.id === edge.target), catalog)?.inputs[edge.target_port]
    if (input?.cardinality === 'one' && activeScope?.scope?.input_bindings.some(binding => binding.node === edge.target && binding.port === edge.target_port)) throw new Error(t("this_input_is_connected_to_the_subflow"))
    changeFlow(current => ({...current, edges: [...current.edges.filter((_, index) => index !== replacingIndex), structuredClone(edge)]}))
  }
  function addCanvasNode(type: string, position: {x:number;y:number}) {
    const id = crypto.randomUUID()
    const scope = type==='host.map'||type==='host.repeat'?{inputs:{},outputs:{},body:{nodes:[],edges:[]},input_bindings:[],output_bindings:[],...(type==='host.map'?{item_input:''}:{rounds:2,feedback:{}})}:undefined
    change(current => ({...current, flow: replaceFlow(current.flow, scopePath, flow => ({...flow, nodes: [...flow.nodes, {id,type,parameters:{},inputs:{},...(scope?{scope}:{})}]})), layout: {...current.layout, [id]:position}}))
  }
  function copyCanvasNodes(ids: string[]) {
    const copies = activeFlow!.nodes.filter(node => ids.includes(node.id)).map(node => ({original:node.id, node:{...copyNode(node),id:crypto.randomUUID()}}))
    change(current => ({...current, flow: replaceFlow(current.flow, scopePath, flow => ({...flow, nodes:[...flow.nodes,...copies.map(item=>item.node)]})), layout:{...current.layout,...Object.fromEntries(copies.map(item=>[item.node.id,{x:(current.layout[item.original]?.x??(28+activeFlow!.nodes.findIndex(node=>node.id===item.original)%3*380))+36,y:(current.layout[item.original]?.y??(24+Math.floor(activeFlow!.nodes.findIndex(node=>node.id===item.original)/3)*280))+36}]))}}))
  }
  function removeCanvasNodes(ids: string[]) {
    change(current => {
      let flow = replaceFlow(current.flow, scopePath, body => ({...body,nodes:body.nodes.filter(node=>!ids.includes(node.id)),edges:body.edges.filter(edge=>!ids.includes(edge.source)&&!ids.includes(edge.target))}))
      if (scopePath.length) flow = replaceFlow(flow,scopePath.slice(0,-1),body=>({...body,nodes:body.nodes.map(node=>node.id===scopePath.at(-1)&&node.scope?{...node,scope:{...node.scope,input_bindings:node.scope.input_bindings.filter(binding=>!ids.includes(binding.node)),output_bindings:node.scope.output_bindings.filter(binding=>!ids.includes(binding.node))}}:node)}))
      return {...current,flow,layout:Object.fromEntries(Object.entries(current.layout).filter(([id])=>!ids.includes(id)))}
    })
  }
  function disconnect(index: number) { changeFlow(flow=>({...flow,edges:flow.edges.filter((_,i)=>i!==index)})) }
  function locateCall(run: Run, id: string) {
    const original = run.nodes[id]?.location?.node_id ?? id
    const path = callPath(run,id)
    if (!currentProject.current || !flowAt(currentProject.current.flow,path)?.nodes.some(node=>node.id===original)) { setNotice(t("this_node_has_been_deleted_from_the")); return }
    navigateScope(path)
    setFocusRequest({id:original,token:Date.now()})
  }
  const canvasCatalog={...catalog,nodes:[...catalog.nodes,...(['host.map','host.repeat'].map(id=>({id,name:id==='host.map'?t("for_each"):t("repeat"),module_id:'host',inputs:{},outputs:{},parameters:{}})))]}
  const WorkspaceEditor = workspace?.editor.component
  return <div className="workbench workbench-fullscreen"><div className="workbench-base" inert={!!workspace}>
    <header><div className="project-menu-anchor"><button className="project-trigger" aria-expanded={projectMenu} onClick={()=>setProjectMenu(!projectMenu)}>{project?.name??t("project")} ▾</button>{projectMenu&&<div className="project-menu"><button onClick={()=>{setManagementOpen(true);setProjectMenu(false)}}>{t("new_open")}</button><button disabled={!project||locked||saving} onClick={()=>{setProjectMenu(false);void copyProject().catch(fail)}}>{t("duplicate_project")}</button><button onClick={()=>{setModulesOpen(true);setProjectMenu(false)}}>{t("modules")}</button><details><summary>{t("more_imports")}</summary>{extensions.actions?.map(action=><button key={action.id} onClick={()=>{setImportAction(action.id);setProjectMenu(false)}}>{text(action.name)}</button>)}</details><button disabled={!project||project.tutorial||locked||saving} onClick={()=>{setProjectMenu(false);void deleteProject()}}>{t("delete_project")}</button></div>}</div>
    {dirty&&<span className="unsaved-dot" title={t("unsaved")} aria-label={t("unsaved")}/>}<div className="header-spacer"/><LanguagePicker/>
    <button aria-label={t("undo")} title={t("undo")} disabled={locked||!undoStack.current.length} onClick={()=>restoreHistory()}>↶</button><button aria-label={t("redo")} title={t("redo")} disabled={locked||!redoStack.current.length} onClick={()=>restoreHistory(true)}>↷</button>
    <button aria-expanded={resultsOpen} onClick={()=>setResultsOpen(!resultsOpen)}>{t("results")}</button><button disabled={!project||locked||saving||waitingForTeachingInputs} onClick={()=>save().catch(fail)}>{saving?t("saving"):t("save")}</button><button className="primary" disabled={!project||locked||saving||waitingForTeachingInputs} onClick={()=>run().catch(fail)}>{t("run_3")}</button>{running&&<button disabled={submittingRun.current||!cancellableRuns.length} onClick={()=>void cancelRun()}>{t("stop")}</button>}</header>
    {([{ message: error, dismiss: setError }, { message: moduleError, dismiss: setModuleError }, { message: projectListError, dismiss: setProjectListError }]).map(({ message, dismiss }, index) => message && <div key={index} role="alert" className="error">{message}<button aria-label={t("dismiss")} onClick={() => dismiss('')}>×</button></div>)}
    {notice&&<p role="status">{notice}</p>}
    {managementOpen&&<aside className="workbench-management" aria-label={t("project")}><div className="panel-heading"><h2>{t("project")}</h2><button aria-label={t("close_projects")} onClick={()=>setManagementOpen(false)}>×</button></div><button disabled={projectBusy} onClick={()=>{void openTutorial().then(()=>setManagementOpen(false)).catch(fail)}}>{t("open_example")}</button><form onSubmit={e=>{e.preventDefault();void createProject().then(()=>setManagementOpen(false)).catch(fail)}}><label>{t("project_name")}<input value={projectName} onChange={e=>setProjectName(e.target.value)}/></label><button disabled={projectBusy}>{t("create")}</button></form><ul>{projects.map(item=><li key={item.id}><button disabled={projectBusy} onClick={()=>open(item.id).then(()=>setManagementOpen(false)).catch(fail)}>{item.name}</button></li>)}</ul></aside>}
    {modulesOpen&&<aside className="workbench-management" aria-label={t("modules")}><div className="panel-heading"><h2>{t("modules")}</h2><button aria-label={t("close_modules")} onClick={()=>setModulesOpen(false)}>×</button></div><ModuleManagement modules={catalog.modules} disabled={locked} refresh={refresh} invalidateRefresh={invalidateRefresh} fail={fail}/></aside>}
    {importAction&&<aside className="workbench-management"><div className="panel-heading"><h2>{text(extensions.actions?.find(action=>action.id===importAction)?.name)}</h2><button aria-label={t("close_import")} onClick={()=>setImportAction('')}>×</button></div>{extensions.actions?.filter(action=>action.id===importAction).map(action=><ExtensionBoundary key={action.id}><action.component host={host}/></ExtensionBoundary>)}</aside>}
    <main>{waitingForTeachingInputs&&<p role="status">{t("loading_input_files")}</p>}{project&&<>
        <section key={projectSession.current} className="canvas" aria-label={t("node_canvas")} ref={canvas}>
          <nav hidden={!scopePath.length} className="scope-navigation" aria-label={t("subflow_navigation")}><button onClick={()=>navigateScope([])} disabled={!scopePath.length}>{t("canvas")}</button>{scopePath.map((id,index)=><button key={id} disabled={index===scopePath.length-1} onClick={()=>navigateScope(scopePath.slice(0,index+1))}>{index+1}: {declarationFor(flowAt(project.flow,scopePath.slice(0,index))?.nodes.find(node=>node.id===id),catalog)?.name??id}</button>)}</nav>
          {activeScope?.scope && <ScopeEditor key={activeScope.id} node={activeScope} catalog={catalog} disabled={locked} onChange={changeScope} />}
          <WorkflowCanvas key={`canvas:${scopePath.join('/')}`} focusRequest={focusRequest} flow={activeFlow!} catalog={canvasCatalog} layout={project.layout} disabled={locked} selectedSource={connection}
            onSource={(source,source_port)=>setConnection({source,source_port,target:'',target_port:''})}
            onTarget={(target,target_port)=>{const edge={...connection,target,target_port};setConnection(edge);if(edge.source&&edge.source_port)void host.connect(edge).then(()=>setConnection({source:'',source_port:'',target:'',target_port:''})).catch(fail)}}
            onMove={(id,position)=>change(current=>({...current,layout:{...current.layout,[id]:{...current.layout[id],...position}}}))} onDisconnect={disconnect}
            onConnect={connectCanvas} onAdd={addCanvasNode} onCopy={copyCanvasNodes} onDelete={removeCanvasNodes}
            onMoveMany={positions=>change(current=>({...current,layout:{...current.layout,...positions}}))}
            renderNodeResult={node=>{const record=[...runs].reverse().find(run=>Object.entries(run.nodes).some(([id,r])=>(r.location?.node_id??id)===node.id&&callPath(run,id).join('/')===scopePath.join('/')));const calls=record?Object.entries(record.nodes).filter(([id,r])=>(r.location?.node_id??id)===node.id&&callPath(record,id).join('/')===scopePath.join('/')):[];return calls.length||node.document||Object.values(node.inputs).some(ids=>ids.length)?<button onClick={()=>openNodeResults(node)}>{calls.some(([,r])=>r.status==='failed')?t("failed_view"):calls.some(([,r])=>r.status==='running')?t("running"):t("results_2")}</button>:null}}
            renderNodeSummary={node=> {
              const editor = extensions.editors?.find(item=>item.node===node.type)
              const declaration = declarationFor(node,catalog)
              const InlineEditor=editor?.inline?editor.component:null
              return <>
                {InlineEditor&&<ExtensionBoundary key={node.id+editor?.installation_id}><InlineEditor context={editorContext(node)} parameters={node.parameters} readOnly={locked} onChange={(parameters: Record<string,unknown>)=>updateNode(node.id,{parameters})}/></ExtensionBoundary>}
                {editor?.workspace && <button disabled={locked} onClick={()=>openWorkspace(node,editor)}>{text(editor.workspace.openLabel) || t("open", {"0": text(editor.workspace.title)})}</button>}
                {Object.entries(declaration?.tools??{}).map(([slot,contract])=><label key={slot}>{t("tool")}<CanvasToolPicker label={t("tool_2", {"0": declaration?.name})} disabled={locked} value={node.tools?.[slot]??''} options={[{id:'',name:t("select_tool")},...(catalog.tools??[]).filter(tool=>tool.slot===contract.id)]} onChange={value=>updateNode(node.id,{tools:{...node.tools,[slot]:value},tool_parameters:{...node.tool_parameters,[slot]:{}}})} /></label>)}
              </>
            }}
            renderNode={(node) => {
            const declaration = declarationFor(node, catalog)
            const editor = extensions.editors?.find(item => item.node === node.type)
            const Editor = editor?.component
            const context = editorContext(node)
            const editorSession = projectSession.current
            function currentEditorTarget() {
              if (!liveProject.current || editorSession !== projectSession.current || context.projectId !== currentProject.current?.id || context.revision !== draftRevision.current || scopePathNow.current.join('/')!==scopePath.join('/') || !flowAt(currentProject.current.flow, scopePath)?.nodes.some(item => item.id === node.id && item.type === node.type)) throw new Error(t("editor_draft_changed_reopen_the_current_node"))
              if (runningNow.current || deletingProject.current === context.projectId || (savingNow.current && currentProject.current.tutorial)) throw new Error(t("project_is_running_saving_or_being_deleted"))
            }
            return <article className="node" key={node.id}>
              {!declaration&&<p role="alert">{t("the_module_for_this_node_is_not")}</p>}
              {node.scope ? <button onClick={()=>navigateScope([...scopePath,node.id])}>{t("open_subflow")}</button> : editor?.workspace || editor?.inline ? null : Editor ? <ExtensionBoundary key={node.id + editor?.installation_id}><Editor context={context} parameters={context.parameters} readOnly={locked} onChange={(parameters: Record<string, unknown>) => {
                try {
                  currentEditorTarget()
                  updateNode(node.id, {parameters})
                } catch (failure) { fail(failure) }
              }} onDraftChange={() => {
                try { currentEditorTarget(); markDirty(true); setNotice('') }
                catch (failure) { fail(failure) }
              }} /></ExtensionBoundary> : <ParameterFields schema={declaration?.parameters??{}} value={node.parameters} disabled={locked} onChange={(parameters: Record<string,unknown>)=>updateNode(node.id,{parameters})}/> }
              {Object.entries(declaration?.tools ?? {}).map(([slot, contract]) => {
                const tool=catalog.tools?.find(item=>item.id===node.tools?.[slot]&&item.slot===contract.id)
                return tool&&<fieldset key={slot} disabled={locked}><legend>{t("parameters")}</legend><ParameterFields schema={tool.parameters} value={node.tool_parameters?.[slot]??{}} disabled={locked} onChange={parameters=>updateNode(node.id,{tool_parameters:{...node.tool_parameters,[slot]:parameters}})}/></fieldset>
              })}
              {!!Object.keys(declaration?.inputs??{}).length&&<details className="node-inputs"><summary>{t("input_sources")}</summary>{Object.entries(declaration?.inputs??{}).map(([port,input])=>{const connected=activeFlow!.edges.find(edge=>edge.target===node.id&&edge.target_port===port);return <label key={port}>{input.name??port}{connected&&<small>{t("connected")}{declarationFor(activeFlow!.nodes.find(item=>item.id===connected.source),catalog)?.name??t("upstream_node")}</small>}<select disabled={locked} multiple={input.cardinality==='many'} value={input.cardinality==='many'?node.inputs[port]??[]:node.inputs[port]?.[0]??''} onChange={e=>{const ids=Array.from(e.target.selectedOptions).map(option=>option.value).filter(Boolean);void editorContext(node).update({inputs:{[port]:ids},...(ids.length?{replaceConnections:[port]}:{})}).catch(fail)}}><option value="">{connected?t("use_connection"):t("not_selected")}</option>{packages.filter(pkg=>input.accepts.includes(pkg.format)).map(pkg=><option key={pkg.id} value={pkg.id}>{packageDescription(pkg)}</option>)}</select></label>})}</details>}

            </article>
          }} />
        </section>
        {resultsOpen&&<aside className="workbench-results" aria-label={t("results")}><div className="panel-heading"><h2>{t("results")}</h2><button aria-label={t("close_results")} onClick={()=>setResultsOpen(false)}>×</button></div>
          <div className="result-selectors"><select aria-label={t("select_run")} value={viewedRun?.id??'inputs'} onChange={e=>{setResultRun(e.target.value);setResultCall('');setSelectedPackage('');setViewer('')}}><option value="inputs">{t("input_files")}</option>{runs.map((run,index)=><option key={run.id} value={run.id}>{t("run_4")} {index+1}  {t("message_3")} {statusLabel(run.status)}</option>)}</select>{viewedRun&&<select aria-label={t("select_result_node")} value={viewedCall} onChange={e=>{setResultCall(e.target.value);setSelectedPackage('');setViewer('')}}>{viewedCalls.map(id=><option key={id} value={id}>{resultName(viewedRun,id)} · {statusLabel(viewedRun.nodes[id].status)}</option>)}</select>}</div>
          {viewedRun?.diagnostics.map((message,i)=><p role="status" key={i}>{message}</p>)}
          {viewedNode&&<div className="result-status"><button onClick={()=>locateCall(viewedRun!,viewedCall)}>{t("locate_node")}</button>{['failed','cancelled'].includes(viewedNode.status)&&(viewedRun?.calls?.[viewedCall]!==undefined||viewedRun?.scopes?.[viewedCall]!==undefined)&&<button disabled={locked||saving} onClick={()=>void continueRun(viewedRun!.id,viewedCall)}>{t("continue")}</button>}{viewedNode.diagnostics?.map((message,i)=><p role="alert" key={i}>{message}</p>)}</div>}
          {resultPackages.length>1&&<select aria-label={t("select_output")} value={selectedPackage} onChange={e=>{setSelectedPackage(e.target.value);setViewer('')}}>{resultPackages.map(({pkg,index,port})=><option key={pkg.id} value={pkg.id}>{viewedRun?`${declarationFor(viewedRun.flow&&flowAt(viewedRun.flow,callPath(viewedRun,viewedCall))?.nodes.find(node=>node.id===(viewedNode?.location?.node_id??viewedCall)),catalog)?.outputs[port]?.name??t("output")} ${index+1}`:packageDescription(pkg)}</option>)}</select>}
          {!resultPackages.length&&<p className="empty-result">{t("no_results_yet")}</p>}
          {selected&&resultPackages.some(item=>item.pkg.id===selected.id)&&<section className="package">

            {Viewer&&<ExtensionBoundary key={selected.id+activeViewer?.id+activeViewer?.installation_id}><Viewer package={selected} host={host}/></ExtensionBoundary>}
            {viewers.length>1&&<details><summary>{t("view_as")}</summary><select aria-label={t("view_as")} value={activeViewer?.id??''} onChange={e=>setViewer(e.target.value)}>{viewers.map(item=><option key={item.id} value={item.id}>{text(item.name)}</option>)}</select></details>}
            <div className="result-actions"><a href={client.exportUrl(selected.id)} download>{t("download_zip")}</a><details><summary>{t("use_in_a_node")}</summary><select aria-label={t("target_node")} value={useTarget} onChange={e=>{setUseTarget(e.target.value);setUsePort('')}}><option value="">{t("select_node")}</option>{activeFlow!.nodes.filter(node=>Object.values(declarationFor(node,catalog)?.inputs??{}).some(input=>input.accepts.includes(selected.format))).map(node=><option key={node.id} value={node.id}>{String(activeFlow!.nodes.indexOf(node)+1).padStart(2,'0')} {declarationFor(node,catalog)?.name}</option>)}</select><select aria-label={t("target_port")} value={usePort} onChange={e=>setUsePort(e.target.value)}><option value="">{t("select_input")}</option>{Object.entries(declarationFor(activeFlow?.nodes.find(node=>node.id===useTarget),catalog)?.inputs??{}).filter(([,input])=>input.accepts.includes(selected.format)).map(([port,input])=><option key={port} value={port}>{input.name??port}</option>)}</select>{useTarget&&usePort&&<small>{t("replaces_the_current_source_for_this_input")}</small>}<button disabled={locked||!useTarget||!usePort} onClick={()=>void useResult().catch(fail)}>{t("apply")}</button></details></div>
            {extensions.resultActions?.map(action=><details key={action.id}><summary>{text(action.name)}</summary><ExtensionBoundary><action.component host={host} packages={[selected]}/></ExtensionBoundary></details>)}
            <details><summary>{t("use_in_another_project")}</summary><select aria-label={t("target_project")} value={adoptionTarget} disabled={adopting} onChange={e=>setAdoptionTarget(e.target.value)}><option value="">{t("select_project")}</option>{projects.filter(item=>item.id!==project.id).map(item=><option key={item.id} value={item.id}>{text(item.name)}</option>)}</select><button disabled={!adoptionTarget||adopting} onClick={()=>void adopt()}>{adopting?t("applying"):t("apply")}</button></details>
            <details><summary>{t("files")}</summary><ul>{selected.files.map(key=><li key={key}><a href={client.fileUrl(selected.id,key)} download>{key}</a></li>)}</ul></details>
          </section>}
        </aside>}

      </>}
    </main></div>
    {workspace && WorkspaceEditor && <section className="editor-workspace-overlay" role="dialog" aria-modal="true" aria-label={text(workspace.editor.workspace?.title)}><ExtensionBoundary onReturn={closeWorkspace} key={workspace.context.projectId+workspace.context.nodeId+workspace.editor.installation_id}><WorkspaceEditor context={workspace.context} parameters={workspace.context.parameters} readOnly={locked} onClose={closeWorkspace} onDraftChange={()=>{workspaceDirty.current=true}} onChange={(parameters: Record<string, unknown>)=>{void workspace.context.update({parameters}).catch(fail)}} /></ExtensionBoundary></section>}
    </div>
}
