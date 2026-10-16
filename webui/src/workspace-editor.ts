import { createDefaultExampleCanvas } from './default-example-canvas'
import type { JsonObject, PromptVersionContext, PublicV2Client, Workflow, ProspectiveInput } from './protocol/client'
import type { ProjectInputPublication, InputSourceClient } from './input-sources'
import type { ProjectWorkspace, WorkflowVersionView, WorkspaceProject } from './project-workspace'

export type EditableWorkspace = { workflow: Workflow; ui_state: JsonObject }
export type WorkspaceChange = { workflow: Workflow; ui_state?: JsonObject } | { workflow?: never; ui_state: JsonObject }
export type WorkspaceEditorSnapshot = {
  project?: WorkspaceProject
  desired?: EditableWorkspace
  acknowledged?: ProjectWorkspace
  version?: WorkflowVersionView
  phase: 'idle' | 'ready' | 'saving' | 'error'
  dirty: boolean
  readOnly: boolean
  error?: unknown
  canUndo: boolean
  canRedo: boolean
  undoLabel?: string
  redoLabel?: string
}
export type WorkspaceEditSession = {
  readonly base: EditableWorkspace
  readonly submitted: boolean
  writableProject(): Promise<WorkspaceProject>
  versionContext(): PromptVersionContext | undefined
  commit(proposal: { workflow: Workflow; updateUi?: (currentUi: JsonObject) => JsonObject }): Promise<ProjectWorkspace | undefined>
}
type EditorClient = Pick<PublicV2Client, 'copyExample' | 'projectWorkspace' | 'saveWorkspace' | 'forkVersion' | 'returnWorkspace' | 'commitWorkflow' | 'listProjectInputs' | 'publishProjectInput' | 'inspectProjectInput' | 'authoringAction' | 'openPrompt' | 'previewPrompt' | 'compareWorkflowScience'>
type HistoryEntry = { previous: EditableWorkspace; workflow: boolean; ui: boolean; label: string }
type SaveAttempt = { target: EditableWorkspace; workspaceRevision: number; draftRevision: number; version?: WorkflowVersionView }
type Session = {
  project: WorkspaceProject
  desired: EditableWorkspace
  saved: EditableWorkspace
  acknowledged: ProjectWorkspace
  version?: WorkflowVersionView
  scienceRevision: number
  history: HistoryEntry[]
  future: HistoryEntry[]
  running?: Promise<ProjectWorkspace | undefined>
  failed?: SaveAttempt
  error?: unknown
  copyTarget?: WorkspaceProject
  readOnly: boolean
  returning?: boolean
  inputRequests: number
  inputs: Array<{ input: ProspectiveInput; publication: ProjectInputPublication }>
}
const blankWorkflow = (projectId: string): Workflow => ({ schema_version: '2.1.0', workflow_id: projectId, nodes: [], edges: [] })
function same(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) !== Array.isArray(right)) return false
  const keys = Object.keys(left)
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && same((left as JsonObject)[key], (right as JsonObject)[key]))
}

/** Accepted edits stay local. Only an explicit save publishes a complete workspace. */
export class WorkspaceEditor {
  private session?: Session
  private listeners = new Set<() => void>()
  private snapshot: WorkspaceEditorSnapshot = { phase: 'idle', dirty: false, readOnly: false, canUndo: false, canRedo: false }
  constructor(private readonly client: EditorClient) {}
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }

  open(project: WorkspaceProject, workspace: ProjectWorkspace, version?: WorkflowVersionView): void {
    const workflow = workspace.draft?.workflow ?? blankWorkflow(project.id)
    const preset = project.project_kind === 'default_example' && project.id === 'webui-3gb1-example'
    const ui_state = preset ? { ...workspace.ui_state, canvas: createDefaultExampleCanvas(workflow) } : workspace.ui_state
    const desired = { workflow, ui_state }
    this.session = { project, acknowledged: workspace, desired, saved: desired, version, scienceRevision: 0, history: [], future: [], readOnly: false, inputs: [], inputRequests: 0 }
    this.publish(this.session)
  }

  close(): void {
    this.session = undefined
    this.snapshot = { phase: 'idle', dirty: false, readOnly: false, canUndo: false, canRedo: false }
    for (const listener of this.listeners) listener()
  }

  updateProject(project: WorkspaceProject): void {
    if (this.session?.project.id === project.id) { this.session.project = project; this.publish(this.session) }
  }

  setReadOnly(readOnly: boolean): void {
    if (this.session && this.session.readOnly !== readOnly) { this.session.readOnly = readOnly; this.publish(this.session) }
  }

  async edit(update: (current: EditableWorkspace) => WorkspaceChange, label?: string): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    this.assertEditable(session)
    return this.accept(session, update(session.desired), true, label)
  }

  async undo(): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    this.assertEditable(session)
    const previous = session.history.pop()
    if (!previous) return Promise.resolve(session.acknowledged)
    session.future.push({ previous: session.desired, workflow: previous.workflow, ui: previous.ui, label: previous.label })
    return this.accept(session, previous.workflow ? { workflow: previous.previous.workflow, ...(previous.ui ? { ui_state: previous.previous.ui_state } : {}) } : { ui_state: previous.previous.ui_state }, false)
  }

  async redo(): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    this.assertEditable(session)
    const next = session.future.pop()
    if (!next) return Promise.resolve(session.acknowledged)
    session.history.push({ previous: session.desired, workflow: next.workflow, ui: next.ui, label: next.label })
    return this.accept(session, next.workflow ? { workflow: next.previous.workflow, ...(next.ui ? { ui_state: next.previous.ui_state } : {}) } : { ui_state: next.previous.ui_state }, false)
  }

  /** Viewing changes stay local and never consume or invalidate content history. */
  navigate(updateUi: (ui: JsonObject) => JsonObject): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    if (session.returning) return Promise.reject(new Error('正在返回已保存工作，请稍后再调整视图。'))
    for (const entry of [...session.history, ...session.future]) entry.previous = { ...entry.previous, ui_state: updateUi(entry.previous.ui_state) }
    session.desired = { ...session.desired, ui_state: updateUi(session.desired.ui_state) }
    this.publish(session)
    return Promise.resolve(session.acknowledged)
  }

  save(): Promise<ProjectWorkspace | undefined> {
    const session = this.session
    if (!session) return Promise.resolve(undefined)
    this.assertEditable(session)
    if (session.running) return session.running
    if (session.inputRequests) return Promise.reject(new Error('输入检查尚未完成，请等待后再保存。'))
    if (session.error !== undefined) return Promise.reject(session.error)
    if (!session.project.seed && !session.version && !this.dirty(session) && session.acknowledged.draft) return Promise.resolve(session.acknowledged)
    // Capture this click's content. Edits made during the request remain unsaved.
    const target = session.desired
    const task = this.publishSave(session, target)
    session.running = task
    this.publish(session)
    return task
  }

  private async publishSave(session: Session, target: EditableWorkspace): Promise<ProjectWorkspace | undefined> {
    try {
      if (session.project.seed) {
        const project = session.copyTarget ??= await this.client.copyExample(session.project.id, `${session.project.name} · 我的副本`, { ...target, inputs: session.inputs.map(entry => entry.input) })
        const workspace = await this.client.projectWorkspace(project.id)
        if (this.session !== session) return undefined
        const rehome = (value: EditableWorkspace) => ({ ...value, workflow: { ...value.workflow, workflow_id: project.id } })
        session.project = project
        session.copyTarget = undefined
        session.acknowledged = workspace
        session.desired = rehome(session.desired)
        session.saved = rehome(session.saved)
        session.history = session.history.map(entry => ({ ...entry, previous: rehome(entry.previous) }))
        session.future = session.future.map(entry => ({ ...entry, previous: rehome(entry.previous) }))
        target = rehome(target)
        session.saved = { workflow: workspace.draft!.workflow, ui_state: workspace.ui_state }
        session.inputs = []
        if (same(target, session.saved)) return workspace
      }
      const attempt: SaveAttempt = { target, workspaceRevision: session.acknowledged.workspace_revision, draftRevision: session.acknowledged.draft?.draft_revision ?? 0, version: session.version }
      session.failed = attempt
      const workspace = attempt.version
        ? await this.client.forkVersion(session.project.id, attempt.version.version.version_id, target.workflow, target.ui_state, attempt.version.return_workspace_revision)
        : await this.client.saveWorkspace(session.project.id, { workflow: target.workflow, ui_state: target.ui_state, expected_draft_revision: attempt.draftRevision, expected_workspace_revision: attempt.workspaceRevision })
      if (this.session !== session) return undefined
      session.acknowledged = workspace
      session.saved = target
      session.version = undefined
      session.failed = undefined
      return workspace
    } catch (error) {
      if (this.session !== session) return undefined
      session.error = error
      throw error
    } finally { session.running = undefined; this.publish(session) }
  }

  async retry(): Promise<ProjectWorkspace | undefined> {
    const session = this.session
    if (!session) return undefined
    this.assertEditable(session)
    if (session.running) return session.running
    if (session.error === undefined) return this.save()
    const failed = session.failed
    if (failed) {
      // A failed response may follow publication. Confirm that exact save once;
      // never overwrite a changed head under the guise of retrying.
      const head = await this.client.projectWorkspace(session.project.id)
      if (this.session !== session) return undefined
      const expectedRevision = failed.version?.return_workspace_revision ?? failed.workspaceRevision
      if (head.workspace_revision !== expectedRevision) {
        if (!same(head.draft?.workflow, failed.target.workflow) || !same(head.ui_state, failed.target.ui_state)) {
          session.error = new Error('当前工作已更改；未保存修改仍保留，不能自动覆盖。')
          this.publish(session)
          throw session.error
        }
        session.acknowledged = head
        session.saved = failed.target
        session.version = undefined
      }
    }
    session.failed = undefined
    session.error = undefined
    this.publish(session)
    return this.save()
  }

  async commitWorkflow(): Promise<{ workflow_commit_id: string } | undefined> {
    const session = this.session
    if (!session) return undefined
    this.assertEditable(session)
    if (session.running) await session.running
    if (this.session !== session) return undefined
    if (session.error !== undefined) throw session.error
    if (this.dirty(session) || session.project.seed || session.version || !session.acknowledged.draft) throw new Error('请先手动保存项目再运行。')
    const target = session.desired
    const outcome = await this.client.commitWorkflow(session.project.id, target.workflow).then(value => ({ value }), (error: unknown) => ({ error }))
    const workspace = await this.client.projectWorkspace(session.project.id)
    if (this.session !== session) return undefined
    session.acknowledged = workspace
    this.publish(session)
    if ('error' in outcome) throw outcome.error
    return outcome.value
  }

  async beginEdit(): Promise<WorkspaceEditSession | undefined> {
    const session = this.session
    if (!session) return undefined
    this.assertEditable(session)
    const revision = session.scienceRevision
    const base = session.desired
    let accepted = false
    const current = () => {
      if (this.session !== session) throw new Error('项目已切换，请重新打开编辑。')
      this.assertEditable(session)
      if (session.scienceRevision !== revision) throw new Error('流程已更改；编辑提案仍保留，请重新打开后确认。')
    }
    return {
      get submitted() { return accepted },
      get base() { return { ...base, workflow: { ...base.workflow, workflow_id: session.project.id } } },
      writableProject: async () => { current(); return session.project },
      versionContext: () => session.version ? { version_id: session.version.version.version_id } : undefined,
      commit: async proposal => {
        if (accepted) throw new Error('此编辑已采用。')
        current()
        const change = { workflow: { ...proposal.workflow, workflow_id: session.project.id }, ...(proposal.updateUi ? { ui_state: proposal.updateUi(session.desired.ui_state) } : {}) }
        accepted = true
        return this.accept(session, change, true)
      },
    }
  }

  /** Called only after an explicit discard choice. */
  discard(): void {
    const session = this.session!
    if (session.running) throw new Error('正在保存，请稍后再离开。')
    session.desired = session.saved
    session.inputs = []
    session.history = []; session.future = []
    session.error = undefined; session.failed = undefined
    session.scienceRevision += 1
    this.publish(session)
  }

  async returnToSavedWork(): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    this.assertEditable(session)
    if (session.running) throw new Error('正在保存，请稍后返回已保存工作。')
    if (this.dirty(session)) throw new Error('请先处理尚未保存的修改。')
    const revision = session.version?.return_workspace_revision ?? session.acknowledged.return_workspace_revision!
    session.returning = true
    const task = (async () => {
      try {
        const workspace = await this.client.returnWorkspace(session.project.id, revision)
        if (this.session !== session) return undefined
        this.open(session.project, workspace)
        return workspace
      } finally {
        session.returning = false
        session.running = undefined
        this.publish(session)
      }
    })()
    session.running = task
    this.publish(session)
    return task
  }

  private accept(session: Session, change: WorkspaceChange, history = true, label = change.workflow ? '流程修改' : '布局修改'): Promise<ProjectWorkspace | undefined> {
    if (history) { session.history.push({ previous: session.desired, workflow: change.workflow !== undefined, ui: change.ui_state !== undefined, label }); session.future = [] }
    session.desired = { workflow: change.workflow ?? session.desired.workflow, ui_state: change.ui_state ?? session.desired.ui_state }
    if (change.workflow) session.scienceRevision += 1
    this.publish(session)
    return Promise.resolve(session.acknowledged)
  }

  /** Resolve inputs for the current editing scope without making a tutorial copy. */
  readonly sources: InputSourceClient & Pick<PublicV2Client, 'authoringAction' | 'openPrompt' | 'previewPrompt' | 'compareWorkflowScience'> = {
    listProjectInputs: async projectId => {
      const session = this.session
      const result = await this.client.listProjectInputs(projectId)
      return { ...result, inputs: [...result.inputs, ...(session?.project.id === projectId ? session.inputs.map(entry => entry.publication) : [])] }
    },
    publishProjectInput: async (projectId, input, format) => {
      const session = this.session!
      this.assertEditable(session)
      if (session.running) throw new Error('正在保存，请稍后添加输入。')
      if (session.copyTarget) throw new Error('首次保存尚未确认，请重试保存后添加输入。')
      if (session.project.id !== projectId) throw new Error('项目已切换，请重新打开编辑。')
      if (!session.project.seed) return this.client.publishProjectInput(projectId, input)
      const prospective: ProspectiveInput = { ...input, project_input_ref: crypto.randomUUID() }
      session.inputRequests += 1
      try {
        const inspection = await this.client.inspectProjectInput(projectId, prospective.project_input_ref, format, prospective)
        if (this.session !== session || session.project.id !== projectId) throw new Error('项目已切换，请重新打开编辑。')
        const publication: ProjectInputPublication = { schema_namespace: 'protein-workbench-public/v2', project_id: projectId, project_input_ref: prospective.project_input_ref, filename: input.filename, size: atob(input.content_base64).length, content_digest: inspection.content_digest }
        session.inputs.push({ input: prospective, publication })
        this.publish(session)
        return publication
      } finally { session.inputRequests -= 1 }
    },
    authoringAction: <T = JsonObject>(projectId: string, actionId: string, parameters: object, inputs?: ProspectiveInput[]) => this.client.authoringAction<T>(projectId, actionId, parameters, inputs ?? this.prospectiveInputs(projectId)),
    inspectProjectInput: (projectId, inputRef, format) => this.client.inspectProjectInput(projectId, inputRef, format, this.session?.project.id === projectId ? this.session.inputs.find(entry => entry.input.project_input_ref === inputRef)?.input : undefined),
    openPrompt: (projectId, nodeId, workflow) => this.client.openPrompt(projectId, nodeId, workflow, this.prospectiveInputs(projectId)),
    previewPrompt: (projectId, nodeId, document, workflow, versionContext) => this.client.previewPrompt(projectId, nodeId, document, workflow, versionContext, this.prospectiveInputs(projectId)),
    compareWorkflowScience: (projectId, commitId, workflowProjectId, workflow) => this.client.compareWorkflowScience(projectId, commitId, workflowProjectId, workflow),
  }
  private prospectiveInputs(projectId: string): ProspectiveInput[] | undefined { return this.session?.project.id === projectId ? this.session.inputs.map(entry => entry.input) : undefined }

  private dirty(session: Session): boolean { return session.inputs.length > 0 || !same(session.desired, session.saved) }
  private assertEditable(session: Session): void { if (session.returning) throw new Error('正在返回已保存工作，请稍后再编辑。'); if (session.readOnly) throw new Error('项目运行期间不能修改；请等待运行结束或取消运行。') }
  private publish(session: Session): void {
    if (this.session !== session) return
    this.snapshot = { project: session.project, desired: session.desired, acknowledged: session.acknowledged, version: session.version, phase: session.error !== undefined ? 'error' : session.running ? 'saving' : 'ready', dirty: this.dirty(session), readOnly: session.readOnly || !!session.returning, error: session.error, canUndo: !session.readOnly && !session.returning && session.history.length > 0, canRedo: !session.readOnly && !session.returning && session.future.length > 0, undoLabel: session.history.at(-1)?.label, redoLabel: session.future.at(-1)?.label }
    for (const listener of this.listeners) listener()
  }
}
