import type { JsonObject, PromptVersionContext, PublicV2Client, Workflow } from './protocol/client'
import type { ProjectWorkspace, WorkflowVersionView, WorkspaceProject } from './project-workspace'

export type EditableWorkspace = { workflow: Workflow; ui_state: JsonObject }
export type WorkspaceChange = { workflow: Workflow; ui_state?: JsonObject } | { workflow?: never; ui_state: JsonObject }
export type WorkspaceEditorSnapshot = {
  project?: WorkspaceProject
  desired?: EditableWorkspace
  acknowledged?: ProjectWorkspace
  version?: WorkflowVersionView
  phase: 'idle' | 'ready' | 'saving' | 'error'
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
type EditorClient = Pick<PublicV2Client, 'copyExample' | 'projectWorkspace' | 'saveWorkspace' | 'forkVersion' | 'returnWorkspace' | 'commitWorkflow'>
type PendingEdit = { target: EditableWorkspace; workflow: boolean; ui: boolean; baseline?: { projectId: string; draftRevision: number; versionId?: string } }
type Session = {
  project: WorkspaceProject
  desired: EditableWorkspace
  acknowledged: ProjectWorkspace
  version?: WorkflowVersionView
  scienceRevision: number
  history: Array<{ previous: EditableWorkspace; workflow: boolean; ui: boolean; label: string }>
  future: Array<{ previous: EditableWorkspace; workflow: boolean; ui: boolean; label: string }>
  queue: PendingEdit[]
  running?: Promise<ProjectWorkspace | undefined>
  error?: unknown
  copying?: Promise<WorkspaceProject>
  copyTarget?: WorkspaceProject
  copiedDraftRevision?: number
  forkedDraftRevision?: number
}
const blankWorkflow = (projectId: string): Workflow => ({ schema_version: '2.1.0', workflow_id: projectId, nodes: [], edges: [], observation_selectors: [], selection_objectives: [] })
// Only used to recognize an already published edit after a failed response.
function same(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) !== Array.isArray(right)) return false
  const keys = Object.keys(left)
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && same((left as JsonObject)[key], (right as JsonObject)[key]))
}

/** Owns accepted edits and the only ordered workspace publication lifecycle. */
export class WorkspaceEditor {
  private session?: Session
  private listeners = new Set<() => void>()
  private snapshot: WorkspaceEditorSnapshot = { phase: 'idle', canUndo: false, canRedo: false }
  constructor(private readonly client: EditorClient) {}
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }

  open(project: WorkspaceProject, workspace: ProjectWorkspace, version?: WorkflowVersionView): void {
    this.session = { project, acknowledged: workspace, desired: { workflow: workspace.draft?.workflow ?? blankWorkflow(project.id), ui_state: workspace.ui_state }, version, scienceRevision: 0, history: [], future: [], queue: [] }
    this.publish(this.session)
  }

  updateProject(project: WorkspaceProject): void {
    if (this.session?.project.id === project.id) { this.session.project = project; this.publish(this.session) }
  }

  edit(update: (current: EditableWorkspace) => WorkspaceChange, label?: string): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    return this.accept(session, update(session.desired), true, undefined, label)
  }

  undo(): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    const previous = session.history.pop()
    if (!previous) return Promise.resolve(session.acknowledged)
    session.future.push({ previous: session.desired, workflow: previous.workflow, ui: previous.ui, label: previous.label })
    return this.accept(session, previous.workflow ? { workflow: previous.previous.workflow, ...(previous.ui ? { ui_state: previous.previous.ui_state } : {}) } : { ui_state: previous.previous.ui_state }, false)
  }

  redo(): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    const next = session.future.pop()
    if (!next) return Promise.resolve(session.acknowledged)
    session.history.push({ previous: session.desired, workflow: next.workflow, ui: next.ui, label: next.label })
    return this.accept(session, next.workflow ? { workflow: next.previous.workflow, ...(next.ui ? { ui_state: next.previous.ui_state } : {}) } : { ui_state: next.previous.ui_state }, false)
  }

  /** Navigation is durable but never consumes or invalidates content history. */
  navigate(updateUi: (ui: JsonObject) => JsonObject): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    for (const entry of [...session.history, ...session.future]) entry.previous = { ...entry.previous, ui_state: updateUi(entry.previous.ui_state) }
    return this.accept(session, { ui_state: updateUi(session.desired.ui_state) }, false)
  }

  flush(): Promise<ProjectWorkspace | undefined> {
    const session = this.session
    if (!session) return Promise.resolve(undefined)
    if (session.error !== undefined) return Promise.reject(session.error)
    return this.drain(session)
  }

  async commitWorkflow(): Promise<{ workflow_commit_id: string } | undefined> {
    const session = this.session
    await this.flush()
    if (!session || this.session !== session) return undefined
    // Commit publishes a Draft even when compilation fails. Keep its acknowledged
    // revision without replacing desired edits or resetting undo history.
    const committing = (async () => {
      const outcome = await this.client.commitWorkflow(session.project.id, session.desired.workflow).then(
        value => ({ value }), (error: unknown) => ({ error }),
      )
      try {
        const workspace = await this.client.projectWorkspace(session.project.id)
        if (this.session === session) session.acknowledged = workspace
      } catch (error) {
        if (this.session === session) session.error = error
        throw error
      }
      if ('error' in outcome) throw outcome.error
      return outcome.value
    })()
    session.running = committing.then(() => session.acknowledged, () => session.acknowledged)
    try { const commit = await committing; return this.session === session ? commit : undefined }
    finally {
      session.running = undefined
      this.publish(session)
      if (this.session === session && session.queue.length && session.error === undefined) await this.drain(session)
    }
  }

  async beginEdit(): Promise<WorkspaceEditSession | undefined> {
    const session = this.session
    await this.flush()
    if (!session || this.session !== session) return undefined
    const revision = session.scienceRevision
    const base = session.desired
    const baseline = { projectId: session.project.id, draftRevision: session.acknowledged.draft?.draft_revision ?? 0, versionId: session.version?.version.version_id }
    let accepted = false
    const current = () => {
      if (this.session !== session) throw new Error('项目已切换，请重新打开编辑。')
      if (session.scienceRevision !== revision) throw new Error('流程已更改；编辑提案仍保留，请重新打开后确认。')
    }
    return {
      get submitted() { return accepted },
      get base() { return { ...base, workflow: { ...base.workflow, workflow_id: session.project.id } } },
      writableProject: async () => { current(); const project = await this.writable(session); current(); return project },
      versionContext: () => session.version ? { version_id: session.version.version.version_id } : undefined,
      commit: async proposal => {
        if (accepted) return Promise.reject(new Error('此编辑已提交；保存失败请使用重试保存。'))
        current()
        const change = { workflow: proposal.workflow, ...(proposal.updateUi ? { ui_state: proposal.updateUi(session.desired.ui_state) } : {}) }
        accepted = true
        return this.accept(session, change, true, baseline)
      },
    }
  }

  async retry(): Promise<ProjectWorkspace | undefined> {
    const session = this.session
    if (!session) return undefined
    if (session.error === undefined) return this.flush()
    if (session.project.seed) {
      session.error = undefined
      session.copying = undefined
      await this.writable(session)
      return this.drain(session)
    }
    // A response or metadata error may follow successful publication. Read the head once.
    const head = await this.client.projectWorkspace(session.project.id)
    if (this.session !== session) return undefined
    const failed = session.queue[0]
    if (failed && head.workspace_revision !== (session.version?.return_workspace_revision ?? session.acknowledged.workspace_revision)) {
      const workflow = { ...failed.target.workflow, workflow_id: session.project.id }
      const expectedWorkflow = failed.workflow || session.version ? workflow : session.acknowledged.draft?.workflow
      const expectedUi = failed.ui || session.version ? failed.target.ui_state : session.acknowledged.ui_state
      if (same(head.draft?.workflow, expectedWorkflow) && same(head.ui_state, expectedUi)) {
        session.acknowledged = head
        session.queue.shift()
        if (session.version) { session.forkedDraftRevision = head.draft!.draft_revision; session.version = undefined }
      } else {
        session.error = new Error('当前工作已更改；未保存提案仍保留，不能自动覆盖。')
        this.publish(session)
        throw session.error
      }
    }
    session.error = undefined
    session.copying = undefined
    this.publish(session)
    return this.drain(session)
  }

  async returnToSavedWork(): Promise<ProjectWorkspace | undefined> {
    const session = this.session!
    await this.flush()
    if (this.session !== session) return undefined
    const revision = session.version?.return_workspace_revision ?? session.acknowledged.return_workspace_revision!
    const workspace = await this.client.returnWorkspace(session.project.id, revision)
    if (this.session !== session) return undefined
    this.open(session.project, workspace)
    return workspace
  }

  private accept(session: Session, change: WorkspaceChange, history = true, baseline?: PendingEdit['baseline'], label = change.workflow ? '流程修改' : '布局修改'): Promise<ProjectWorkspace | undefined> {
    if (history) { session.history.push({ previous: session.desired, workflow: change.workflow !== undefined, ui: change.ui_state !== undefined, label }); session.future = [] }
    session.desired = { workflow: change.workflow ?? session.desired.workflow, ui_state: change.ui_state ?? session.desired.ui_state }
    if (change.workflow) session.scienceRevision += 1
    session.queue.push({ target: session.desired, workflow: change.workflow !== undefined, ui: change.ui_state !== undefined, baseline })
    this.publish(session)
    if (session.error !== undefined) return Promise.reject(session.error)
    return this.drain(session)
  }

  private writable(session: Session): Promise<WorkspaceProject> {
    if (session.error !== undefined) return Promise.reject(session.error)
    if (!session.project.seed) return Promise.resolve(session.project)
    session.copying ??= (async () => {
      const project = session.copyTarget ??= await this.client.copyExample(session.project.id, `${session.project.name} · 我的副本`)
      const workspace = await this.client.projectWorkspace(project.id)
      session.project = project
      session.acknowledged = workspace
      session.copiedDraftRevision = workspace.draft?.draft_revision ?? 0
      session.desired = { ...session.desired, workflow: { ...session.desired.workflow, workflow_id: project.id } }
      session.history = session.history.map(entry => ({ ...entry, previous: { ...entry.previous, workflow: { ...entry.previous.workflow, workflow_id: project.id } } }))
      session.future = session.future.map(entry => ({ ...entry, previous: { ...entry.previous, workflow: { ...entry.previous.workflow, workflow_id: project.id } } }))
      this.publish(session)
      return project
    })().catch(error => { if (this.session === session) { session.error = error; this.publish(session) }; throw error })
    return session.copying
  }

  private drain(session: Session): Promise<ProjectWorkspace | undefined> {
    if (session.running) return session.running
    if (!session.queue.length) { this.publish(session); return Promise.resolve(session.acknowledged) }
    const task = (async () => {
      try {
        await this.writable(session)
        while (this.session === session && session.queue.length) {
          const edit = session.queue[0]
          const workflow = { ...edit.target.workflow, workflow_id: session.project.id }
          let workspace: ProjectWorkspace
          if (session.version) {
            workspace = await this.client.forkVersion(session.project.id, session.version.version.version_id, workflow, edit.target.ui_state, session.version.return_workspace_revision)
            session.forkedDraftRevision = workspace.draft!.draft_revision
            session.version = undefined
          } else {
            const expected = edit.baseline && (edit.baseline.projectId !== session.project.id ? session.copiedDraftRevision : edit.baseline.versionId ? session.forkedDraftRevision ?? edit.baseline.draftRevision : edit.baseline.draftRevision)
            workspace = await this.client.saveWorkspace(session.project.id, { ...(edit.workflow ? { workflow } : {}), ...(edit.ui ? { ui_state: edit.target.ui_state } : {}), ...(expected !== undefined ? { expected_draft_revision: expected } : {}) })
          }
          session.acknowledged = workspace
          session.queue.shift()
          this.publish(session)
        }
        return this.session === session ? session.acknowledged : undefined
      } catch (error) {
        if (this.session !== session) return undefined
        session.error = error
        throw error
      } finally { session.running = undefined; this.publish(session) }
    })()
    session.running = task
    this.publish(session)
    return task
  }

  private publish(session: Session): void {
    if (this.session !== session) return
    this.snapshot = { project: session.project, desired: session.desired, acknowledged: session.acknowledged, version: session.version, phase: session.error !== undefined ? 'error' : session.queue.length ? 'saving' : 'ready', error: session.error, canUndo: session.history.length > 0, canRedo: session.future.length > 0, undoLabel: session.history.at(-1)?.label, redoLabel: session.future.at(-1)?.label }
    for (const listener of this.listeners) listener()
  }
}
