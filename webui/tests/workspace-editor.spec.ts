import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { PublicV2Client, type JsonObject, type Workflow } from '../src/protocol/client'
import type { ProjectWorkspace, WorkflowVersionView, WorkspaceProject } from '../src/project-workspace'
import { WorkspaceEditor } from '../src/workspace-editor'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function project(id = 'personal', kind: WorkspaceProject['project_kind'] = 'personal'): WorkspaceProject {
  return { id, name: id, seed: kind !== 'personal', project_kind: kind, copied_from_project_id: null, reference_results_project_id: null, created_at: '2026-09-22', modified_at: '2026-09-22', deleted_at: null, latest_run_id: null }
}
function workflow(id = 'personal', count = 1): Workflow {
  return { schema_version: '2.1.0', workflow_id: id, nodes: [{ node_id: 'take', node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', node_parameters: { k: count }, binding_parameters: {} }], edges: [], observation_selectors: [], selection_objectives: [] }
}
function workspace(id = 'personal', revision = 1): ProjectWorkspace {
  return { project_id: id, workspace_revision: revision, draft: { project_id: id, draft_revision: revision, workflow: workflow(id) }, ui_state_revision: revision, ui_state: { canvas: { viewport: { x: 0, y: 0, zoom: 1 } } }, source_version_id: null, return_workspace_revision: null }
}
type Save = { workflow?: Workflow; ui_state?: JsonObject; expected_draft_revision?: number }
class EditorClient extends PublicV2Client {
  head = workspace()
  saves: Array<{ projectId: string; change: Save }> = []
  copies: string[] = []
  forks: Array<{ projectId: string; versionId: string; workflow: Workflow; ui: JsonObject; returnRevision: number }> = []
  returns: number[] = []
  reads = 0
  readProjects: string[] = []
  saveResponse = async (projectId: string, change: Save): Promise<ProjectWorkspace> => {
    this.head = { ...this.head, project_id: projectId, workspace_revision: this.head.workspace_revision + 1,
      draft: change.workflow ? { project_id: projectId, draft_revision: this.head.draft!.draft_revision + 1, workflow: change.workflow } : this.head.draft,
      ui_state: change.ui_state ?? this.head.ui_state, ui_state_revision: this.head.ui_state_revision + (change.ui_state ? 1 : 0) }
    return this.head
  }
  override saveWorkspace(projectId: string, change: Save) { this.saves.push({ projectId, change }); return this.saveResponse(projectId, change) }
  override async projectWorkspace(projectId: string) { this.reads += 1; this.readProjects.push(projectId); return this.head }
  override async copyExample(projectId: string, name: string) {
    this.copies.push(projectId)
    this.head = workspace('copy', 7)
    return { ...project('copy'), name, copied_from_project_id: projectId }
  }
  override async forkVersion(projectId: string, versionId: string, value: Workflow, ui: JsonObject, returnRevision: number) {
    this.forks.push({ projectId, versionId, workflow: value, ui, returnRevision })
    this.head = { ...workspace(projectId, 9), draft: { project_id: projectId, draft_revision: 9, workflow: value }, ui_state: ui, source_version_id: versionId, return_workspace_revision: returnRevision }
    return this.head
  }
  override async returnWorkspace(_projectId: string, revision: number) { this.returns.push(revision); this.head = workspace('personal', revision); return this.head }
}

async function opened(client = new EditorClient()) {
  const editor = new WorkspaceEditor(client)
  await editor.open(project(), client.head)
  return { editor, client }
}

test('a graph edit publishes Workflow and layout together; layout alone preserves the science revision', async () => {
  const { editor, client } = await opened()
  const ui = { canvas: { positions: { take: { x: 20, y: 40 } } } }
  await editor.edit(current => ({ workflow: workflow(current.workflow.workflow_id, 2), ui_state: ui }))
  expect(client.saves).toHaveLength(1)
  expect(client.saves[0].change).toEqual({ workflow: workflow('personal', 2), ui_state: ui })
  const draft = client.head.draft
  await editor.edit(() => ({ ui_state: { ...ui, collapsed: ['take'] } }))
  expect(client.saves[1].change).not.toHaveProperty('workflow')
  expect(client.head.draft).toBe(draft)
  expect(editor.getSnapshot().acknowledged).toBe(client.head)
})

test('queued saves keep the latest desired edit while the earlier receipt is pending', async () => {
  const { editor, client } = await opened()
  const held = deferred<ProjectWorkspace>()
  const started = deferred<void>()
  const saveNormally = client.saveResponse
  client.saveResponse = (id, change) => { if (client.saves.length === 1) { started.resolve(); return held.promise } return saveNormally(id, change) }
  const first = editor.edit(() => ({ workflow: workflow('personal', 2) }))
  await started.promise
  const second = editor.edit(current => ({ workflow: workflow(current.workflow.workflow_id, 3) }))
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
  expect(client.saves).toHaveLength(1)
  held.resolve(await saveNormally('personal', { workflow: workflow('personal', 2) }))
  await Promise.all([first, second, editor.flush()])
  expect(client.saves.map(save => save.change.workflow!.nodes[0].node_parameters.k)).toEqual([2, 3])
  expect(editor.getSnapshot().acknowledged!.draft!.workflow).toEqual(workflow('personal', 3))
})

test('a failed long edit remains desired, pauses writes, and retries through the owner without a second commit', async () => {
  const { editor, client } = await opened()
  const session = (await editor.beginEdit())!
  const saveNormally = client.saveResponse
  client.saveResponse = async () => { throw new Error('disk unavailable') }
  await expect(session.commit({ workflow: workflow('personal', 2) })).rejects.toThrow('disk unavailable')
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 2))
  expect(editor.getSnapshot().acknowledged!.draft!.workflow).toEqual(workflow())
  expect(editor.getSnapshot().phase).toBe('error')
  await expect(editor.flush()).rejects.toThrow('disk unavailable')
  expect(client.saves).toHaveLength(1)
  client.saveResponse = saveNormally
  await editor.retry()
  expect(client.saves).toHaveLength(2)
  expect(editor.getSnapshot().acknowledged!.draft!.workflow).toEqual(workflow('personal', 2))
  await editor.undo()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow())
})

test('a long edit applies its UI operation to the latest layout and keeps its fixed scientific proposal', async () => {
  const { editor, client } = await opened()
  const session = (await editor.beginEdit())!
  const lateUi = { canvas: { viewport: { x: 80, y: 120, zoom: 2 } }, collapsed: ['take'] }
  await editor.edit(() => ({ ui_state: lateUi }))
  await session.commit({ workflow: workflow('personal', 2), updateUi: current => ({ ...current, added: { x: 400, y: 300 } }) })
  expect(client.saves.at(-1)!.change).toEqual({ workflow: workflow('personal', 2), ui_state: { ...lateUi, added: { x: 400, y: 300 } }, expected_draft_revision: 1 })
  expect(session.base.workflow).toEqual(workflow())
})

test('a later scientific edit invalidates a long proposal even before that edit is acknowledged', async () => {
  const { editor, client } = await opened()
  const session = (await editor.beginEdit())!
  const held = deferred<ProjectWorkspace>()
  const started = deferred<void>()
  const saveNormally = client.saveResponse
  client.saveResponse = () => { started.resolve(); return held.promise }
  const later = editor.edit(() => ({ workflow: workflow('personal', 3) }))
  await started.promise
  await expect(session.commit({ workflow: workflow('personal', 2) })).rejects.toThrow()
  expect(client.saves).toHaveLength(1)
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
  expect(session.base.workflow).toEqual(workflow())
  held.resolve(await saveNormally('personal', { workflow: workflow('personal', 3) }))
  await later
})

test('read-only tutorial sessions do not copy; Input preparation maps scope and uses the copied Draft revision', async () => {
  const client = new EditorClient()
  client.head = workspace('tutorial', 30)
  const editor = new WorkspaceEditor(client)
  await editor.open(project('tutorial', 'default_example'), client.head)
  const session = (await editor.beginEdit())!
  expect(client.copies).toEqual([])
  const writable = await session.writableProject()
  expect(writable.id).toBe('copy')
  expect(session.base.workflow.workflow_id).toBe('copy')
  await session.commit({ workflow: workflow(session.base.workflow.workflow_id, 2) })
  expect(client.copies).toEqual(['tutorial'])
  expect(client.saves).toHaveLength(1)
  expect(client.saves[0]).toEqual({ projectId: 'copy', change: { workflow: workflow('copy', 2), expected_draft_revision: 7 } })
})

test('the first version layout edit forks once and preserves the exact return point', async () => {
  const client = new EditorClient()
  const editor = new WorkspaceEditor(client)
  const view: WorkflowVersionView = { version: { project_id: 'personal', version_id: 'named', name: 'Original', created_at: '2026-09-22', workspace_revision: 1, draft_revision: 1, ui_state_revision: 1 }, workspace: workspace(), return_workspace_revision: 8 }
  await editor.open(project(), view.workspace, view)
  expect(client.forks).toEqual([])
  await editor.edit(() => ({ ui_state: { collapsed: ['take'] } }))
  expect(client.saves).toEqual([])
  expect(client.forks).toEqual([{ projectId: 'personal', versionId: 'named', workflow: workflow(), ui: { collapsed: ['take'] }, returnRevision: 8 }])
  await editor.returnToSavedWork()
  expect(client.returns).toEqual([8])
  expect(editor.getSnapshot().acknowledged!.workspace_revision).toBe(8)
})

for (const outcome of ['success', 'failure'] as const) {
  test(`a retired A to B to A save ${outcome} cannot replace the new session`, async () => {
    const { editor, client } = await opened()
    const held = deferred<ProjectWorkspace>()
    const started = deferred<void>()
    client.saveResponse = () => { started.resolve(); return held.promise }
    const pending = editor.edit(() => ({ workflow: workflow('personal', 2) }))
    await started.promise
    await editor.open(project('B'), workspace('B'))
    await editor.open(project(), workspace('personal', 10))
    if (outcome === 'success') held.resolve({ ...workspace('personal', 2), draft: { project_id: 'personal', draft_revision: 2, workflow: workflow('personal', 2) } })
    else held.reject(new Error('retired save failed'))
    expect(await pending).toBeUndefined()
    expect(editor.getSnapshot().acknowledged!.workspace_revision).toBe(10)
    expect(editor.getSnapshot().desired!.workflow).toEqual(workflow())
    expect(editor.getSnapshot().phase).toBe('ready')
  })
}

test('edits accepted after a failure remain queued until one explicit retry resumes publication', async () => {
  const { editor, client } = await opened()
  const saveNormally = client.saveResponse
  client.saveResponse = async () => { throw new Error('write interrupted') }
  await expect(editor.edit(() => ({ workflow: workflow('personal', 2) }))).rejects.toThrow('write interrupted')
  await expect(editor.edit(current => ({ workflow: workflow(current.workflow.workflow_id, 3) }))).rejects.toThrow('write interrupted')
  expect(client.saves).toHaveLength(1)
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
  client.saveResponse = saveNormally
  await editor.retry()
  expect(client.saves.map(save => save.change.workflow!.nodes[0].node_parameters.k)).toEqual([2, 2, 3])
  expect(editor.getSnapshot().acknowledged!.draft!.workflow).toEqual(workflow('personal', 3))
})

test('retry recognizes a published receipt after a lost response without creating another history entry', async () => {
  const { editor, client } = await opened()
  const saveNormally = client.saveResponse
  client.saveResponse = async (id, change) => { await saveNormally(id, change); throw new Error('response lost') }
  await expect(editor.edit(() => ({ workflow: workflow('personal', 2), ui_state: { collapsed: ['take'] } }))).rejects.toThrow('response lost')
  expect(editor.getSnapshot().acknowledged!.workspace_revision).toBe(1)
  expect(client.head.workspace_revision).toBe(2)
  client.saveResponse = saveNormally
  await editor.retry()
  expect(client.reads).toBe(1)
  expect(client.readProjects).toEqual(['personal'])
  expect(client.saves).toHaveLength(1)
  expect(editor.getSnapshot().acknowledged!.workspace_revision).toBe(2)
  await editor.undo()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow())
  expect(editor.getSnapshot().canUndo).toBe(false)
})

test('retry preserves a failed proposal when the persisted baseline changed independently', async () => {
  const { editor, client } = await opened()
  const session = (await editor.beginEdit())!
  client.saveResponse = async () => { throw new Error('connection lost') }
  await expect(session.commit({ workflow: workflow('personal', 2) })).rejects.toThrow('connection lost')
  client.head = { ...workspace('personal', 3), draft: { project_id: 'personal', draft_revision: 3, workflow: workflow('personal', 4) } }
  await expect(editor.retry()).rejects.toThrow()
  expect(client.saves).toHaveLength(1)
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 2))
  expect(editor.getSnapshot().phase).toBe('error')
})

test('Input preparation copy failure pauses the owner until explicit retry without losing its long session', async () => {
  const client = new EditorClient()
  client.head = workspace('tutorial', 30)
  const editor = new WorkspaceEditor(client)
  await editor.open(project('tutorial', 'default_example'), client.head)
  const session = (await editor.beginEdit())!
  const copyNormally = client.copyExample.bind(client)
  let attempts = 0
  let fail = true
  client.copyExample = async (id, name) => {
    attempts += 1
    if (fail) throw new Error('copy interrupted')
    return copyNormally(id, name)
  }
  await expect(session.writableProject()).rejects.toThrow('copy interrupted')
  expect(editor.getSnapshot().phase).toBe('error')
  expect(editor.getSnapshot().desired!.workflow.workflow_id).toBe('tutorial')
  expect(editor.getSnapshot().canUndo).toBe(false)
  expect(client.saves).toEqual([])
  await expect(session.writableProject()).rejects.toThrow('copy interrupted')
  expect(attempts).toBe(1)
  fail = false
  await editor.retry()
  expect((await session.writableProject()).id).toBe('copy')
  expect(attempts).toBe(2)
  await session.commit({ workflow: workflow(session.base.workflow.workflow_id, 2) })
  expect(client.saves[0]).toEqual({ projectId: 'copy', change: { workflow: workflow('copy', 2), expected_draft_revision: 7 } })
})

for (const editKind of ['layout', 'science'] as const) {
  for (const externalChange of [false, true]) {
    test(`failed version ${editKind} fork retries against the return head; external change=${externalChange}`, async () => {
      const client = new EditorClient()
      client.head = { ...workspace('personal', 8), draft: { project_id: 'personal', draft_revision: 8, workflow: workflow('personal', 8) }, ui_state: { current: true } }
      const editor = new WorkspaceEditor(client)
      const view: WorkflowVersionView = { version: { project_id: 'personal', version_id: 'named', name: 'Original', created_at: '2026-09-22', workspace_revision: 1, draft_revision: 1, ui_state_revision: 1 }, workspace: workspace(), return_workspace_revision: 8 }
      await editor.open(project(), view.workspace, view)
      const forkNormally = client.forkVersion.bind(client)
      let attempts = 0
      let fail = true
      client.forkVersion = async (...args) => {
        attempts += 1
        if (fail) throw new Error('fork interrupted before publication')
        return forkNormally(...args)
      }
      const proposedWorkflow = editKind === 'science' ? workflow('personal', 2) : workflow()
      const proposedUi = { collapsed: ['take'] }
      await expect(editor.edit(() => editKind === 'science' ? { workflow: proposedWorkflow, ui_state: proposedUi } : { ui_state: proposedUi })).rejects.toThrow('fork interrupted before publication')
      expect(client.head.workspace_revision).toBe(8)
      expect(editor.getSnapshot().acknowledged!.workspace_revision).toBe(1)
      expect(editor.getSnapshot().desired).toEqual({ workflow: proposedWorkflow, ui_state: proposedUi })
      if (externalChange) client.head = { ...client.head, workspace_revision: 9, ui_state: { changedElsewhere: true } }
      fail = false
      if (externalChange) {
        await expect(editor.retry()).rejects.toThrow()
        expect(attempts).toBe(1)
        expect(client.forks).toEqual([])
        expect(editor.getSnapshot().phase).toBe('error')
        expect(editor.getSnapshot().desired).toEqual({ workflow: proposedWorkflow, ui_state: proposedUi })
      } else {
        await editor.retry()
        expect(attempts).toBe(2)
        expect(client.forks).toEqual([{ projectId: 'personal', versionId: 'named', workflow: proposedWorkflow, ui: proposedUi, returnRevision: 8 }])
        expect(client.saves).toEqual([])
        expect(editor.getSnapshot().acknowledged!.return_workspace_revision).toBe(8)
        expect(editor.getSnapshot().phase).toBe('ready')
      }
    })
  }
}

test('retry reuses the created tutorial copy when reading its workspace initially fails', async () => {
  const client = new EditorClient()
  const tutorial = workspace('tutorial', 30)
  client.head = tutorial
  const editor = new WorkspaceEditor(client)
  await editor.open(project('tutorial', 'default_example'), tutorial)
  const session = (await editor.beginEdit())!
  let copyReads = 0
  client.projectWorkspace = async id => {
    if (id === 'tutorial') return tutorial
    copyReads += 1
    if (copyReads === 1) throw new Error('copy workspace response lost')
    return client.head
  }
  await expect(session.writableProject()).rejects.toThrow('copy workspace response lost')
  expect(client.copies).toEqual(['tutorial'])
  expect(editor.getSnapshot().phase).toBe('error')
  expect(client.saves).toEqual([])
  await editor.retry()
  expect((await session.writableProject()).id).toBe('copy')
  expect(client.copies).toEqual(['tutorial'])
  expect(copyReads).toBeGreaterThanOrEqual(2)
  expect(session.base.workflow.workflow_id).toBe('copy')
  await session.commit({ workflow: workflow('copy', 2) })
  expect(client.saves[0]).toEqual({ projectId: 'copy', change: { workflow: workflow('copy', 2), expected_draft_revision: 7 } })
})

test('Run Commit advances the acknowledged Draft and preserves desired UI and undo history', async () => {
  const { editor, client } = await opened()
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  client.commitWorkflow = async (id, value) => {
    await client.saveResponse(id, { workflow: value })
    return { workflow_commit_id: 'committed' }
  }
  const desired = editor.getSnapshot().desired
  expect(await editor.commitWorkflow()).toEqual({ workflow_commit_id: 'committed' })
  expect(editor.getSnapshot().desired).toBe(desired)
  const baseline = client.head.draft!.draft_revision
  const edit = (await editor.beginEdit())!
  await edit.commit({ workflow: workflow('personal', 3) })
  expect(client.saves.at(-1)!.change.expected_draft_revision).toBe(baseline)
  await editor.undo()
  await editor.undo()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow())
})

test('a rejected Run Commit still acknowledges the Draft saved before compilation', async () => {
  const { editor, client } = await opened()
  client.commitWorkflow = async (id, value) => {
    await client.saveResponse(id, { workflow: value })
    throw new Error('compile rejected')
  }
  await expect(editor.commitWorkflow()).rejects.toThrow('compile rejected')
  expect(editor.getSnapshot().acknowledged).toBe(client.head)
  const edit = (await editor.beginEdit())!
  await edit.commit({ workflow: workflow('personal', 2) })
  expect(client.saves.at(-1)!.change.expected_draft_revision).toBe(2)
})

test('a late Run Commit receipt cannot replace a newly opened workspace', async () => {
  const { editor, client } = await opened()
  const started = deferred<void>()
  const held = deferred<{ workflow_commit_id: string }>()
  client.commitWorkflow = () => { started.resolve(); return held.promise }
  const committing = editor.commitWorkflow()
  await started.promise
  editor.open(project('other'), workspace('other', 8))
  held.resolve({ workflow_commit_id: 'retired' })
  expect(await committing).toBeUndefined()
  expect(editor.getSnapshot().acknowledged).toEqual(workspace('other', 8))
})

test('navigation does not consume history or invalidate redo, including grouped layout', async () => {
  const { editor } = await opened()
  await editor.edit(current => ({ workflow: workflow(current.workflow.workflow_id, 2), ui_state: { canvas: { positions: { take: { x: 20, y: 30 } }, groups: [] } } }))
  await editor.navigate(ui => ({ ...ui, navigation: 'inside-group' }))
  await editor.undo()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow())
  expect(editor.getSnapshot().desired!.ui_state.navigation).toBe('inside-group')
  expect(editor.getSnapshot().canRedo).toBe(true)
  await editor.navigate(ui => ({ ...ui, navigation: 'root' }))
  await editor.redo()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 2))
  expect(editor.getSnapshot().desired!.ui_state.navigation).toBe('root')
  expect(editor.getSnapshot().canRedo).toBe(false)
})


test('default stage presentation is read-only until the first edit and persists with that edit', async () => {
  const source = JSON.parse(readFileSync(new URL('../../examples/v2/webui-3gb1.example.json', import.meta.url), 'utf8')) as { workflow: Workflow }
  const client = new EditorClient()
  const id = 'webui-3gb1-example'
  const original = { ...workspace(id), draft: { project_id: id, draft_revision: 1, workflow: source.workflow } }
  const before = structuredClone(original)
  const editor = new WorkspaceEditor(client)
  editor.open(project(id, 'default_example'), original)
  const canvas = editor.getSnapshot().desired!.ui_state.canvas as { groups: Array<{ id: string }>; currentGroup?: string }
  expect(canvas.groups).toHaveLength(5)
  expect(editor.getSnapshot().acknowledged).toBe(original)
  await editor.navigate(ui => ({ ...ui, canvas: { ...canvas, currentGroup: canvas.groups[0].id } }))
  expect(client.copies).toEqual([])
  expect(client.saves).toEqual([])
  expect(editor.getSnapshot().canUndo).toBe(false)
  expect(original).toEqual(before)
  await editor.edit(current => ({ workflow: { ...current.workflow, nodes: current.workflow.nodes.map(node => node.node_id === 'generate-paired' ? { ...node, node_parameters: { ...node.node_parameters, num_samples: 8 } } : node) } }), '修改生成数量')
  expect(client.copies).toEqual([id])
  expect(client.saves).toHaveLength(1)
  expect(client.saves[0].change.ui_state).toEqual(editor.getSnapshot().desired!.ui_state)
  expect(client.saves[0].change.workflow!.edges).toEqual(source.workflow.edges)
  await editor.undo()
  expect(editor.getSnapshot().desired!.workflow.nodes.find(node => node.node_id === 'generate-paired')!.node_parameters.num_samples).toBe(7)
  expect((editor.getSnapshot().desired!.ui_state.canvas as typeof canvas).groups).toHaveLength(5)
  editor.open(project('copy'), client.head)
  expect((editor.getSnapshot().desired!.ui_state.canvas as typeof canvas).groups).toHaveLength(5)
})

test('prepared writable example session retains unpersisted navigation in its first content save', async () => {
  const client = new EditorClient()
  const editor = new WorkspaceEditor(client)
  editor.open(project('tutorial', 'default_example'), workspace('tutorial'))
  await editor.navigate(ui => ({ ...ui, stageLocation: 'next-stage' }))
  const session = (await editor.beginEdit())!
  await session.writableProject()
  await session.commit({ workflow: workflow('copy', 2) })
  expect(client.saves[0].change.ui_state!.stageLocation).toBe('next-stage')
  expect(client.saves[0].change.workflow).toBeUndefined()
  expect(client.saves[1].change.workflow!.nodes[0].node_parameters.k).toBe(2)
})


test('navigation during the first copy is published after the pending content edit', async () => {
  const client = new EditorClient()
  const copy = client.copyExample.bind(client)
  const held = deferred<void>()
  client.copyExample = async (id, name) => { await held.promise; return copy(id, name) }
  const editor = new WorkspaceEditor(client)
  editor.open(project('tutorial', 'default_example'), workspace('tutorial'))
  const edit = editor.edit(() => ({ workflow: workflow('tutorial', 2) }))
  const navigation = editor.navigate(ui => ({ ...ui, stageLocation: 'last-stage' }))
  held.resolve()
  await Promise.all([edit, navigation])
  expect(client.head.ui_state.stageLocation).toBe('last-stage')
  expect(client.copies).toEqual(['tutorial'])
  expect(editor.getSnapshot().undoLabel).toBe('流程修改')
})


test('cancelling after writable modal preparation leaves copied presentation persisted', async () => {
  const client = new EditorClient()
  const editor = new WorkspaceEditor(client)
  editor.open(project('tutorial', 'default_example'), workspace('tutorial'))
  await editor.navigate(ui => ({ ...ui, stageLocation: 'prompt-stage' }))
  const session = (await editor.beginEdit())!
  await session.writableProject()
  expect(client.head.ui_state.stageLocation).toBe('prompt-stage')
  expect(client.saves).toHaveLength(1)
  expect(client.saves[0].change.workflow).toBeUndefined()
  expect(editor.getSnapshot().canUndo).toBe(false)
})
