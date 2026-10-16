import { expect, test } from '@playwright/test'
import { PublicV2Client, type JsonObject, type Workflow, type ProspectiveInput } from '../../src/protocol/client'
import type { ProjectWorkspace, WorkspaceProject } from '../../src/project-workspace'
import { WorkspaceEditor } from '../../src/workspace-editor'

function project(id = 'personal', kind: WorkspaceProject['project_kind'] = 'personal'): WorkspaceProject {
  return { id, name: id, seed: kind !== 'personal', project_kind: kind, copied_from_project_id: null, reference_results_project_id: null, created_at: '2026-09-22', modified_at: '2026-09-22', deleted_at: null, latest_run_id: null }
}
function workflow(id = 'personal', count = 1): Workflow {
  return { schema_version: '2.1.0', workflow_id: id, nodes: [{ node_id: 'take', node_type_id: 'collection_ops.take_candidates', binding_id: 'collection_ops.take_candidates.direct', node_parameters: { k: count }, binding_parameters: {} }], edges: [], observation_selectors: [], selection_objectives: [] }
}
function workspace(id = 'personal', revision = 1): ProjectWorkspace {
  return { project_id: id, workspace_revision: revision, draft: { project_id: id, draft_revision: revision, workflow: workflow(id) }, ui_state_revision: revision, ui_state: { canvas: { viewport: { x: 0, y: 0, zoom: 1 } } }, source_version_id: null, return_workspace_revision: null }
}
type Save = { workflow?: Workflow; ui_state?: JsonObject; expected_draft_revision?: number; expected_workspace_revision?: number }
class EditorClient extends PublicV2Client {
  head = workspace()
  saves: Array<{ projectId: string; change: Save }> = []
  copies: string[] = []
  copiedInputs: ProspectiveInput[] = []
  saveResponse = async (projectId: string, change: Save): Promise<ProjectWorkspace> => {
    this.head = { ...this.head, project_id: projectId, workspace_revision: this.head.workspace_revision + 1,
      draft: change.workflow ? { project_id: projectId, draft_revision: this.head.draft!.draft_revision + 1, workflow: change.workflow } : this.head.draft,
      ui_state: change.ui_state ?? this.head.ui_state, ui_state_revision: this.head.ui_state_revision + (change.ui_state ? 1 : 0) }
    return this.head
  }
  override saveWorkspace(projectId: string, change: Save) { this.saves.push({ projectId, change }); return this.saveResponse(projectId, change) }
  override async projectWorkspace(projectId: string) { return { ...this.head, project_id: projectId } }
  override async copyExample(projectId: string, name: string, saved?: { workflow: Workflow; ui_state: JsonObject; inputs: ProspectiveInput[] }) {
    this.copies.push(projectId)
    this.copiedInputs = saved?.inputs ?? []
    this.head = workspace('copy', 7)
    if (saved) this.head = { ...this.head, draft: { project_id: 'copy', draft_revision: 7, workflow: { ...saved.workflow, workflow_id: 'copy' } }, ui_state: saved.ui_state }
    return { ...project('copy'), name, copied_from_project_id: projectId }
  }

}

async function opened(client = new EditorClient()) {
  const editor = new WorkspaceEditor(client)
  await editor.open(project(), client.head)
  return { editor, client }
}

for (const kind of ['personal', 'default_example'] as const) {
  test(`${kind}: graph and layout edits stay in memory until manual save`, async () => {
    const client = new EditorClient()
    const editor = new WorkspaceEditor(client)
    const original = structuredClone(client.head)
    editor.open(project('personal', kind), client.head)
    const ui = { canvas: { positions: { take: { x: 20, y: 40 } } } }
    await editor.edit(() => ({ workflow: workflow('personal', 2), ui_state: ui }))
    expect(client.copies, 'Editing must not create a persistent tutorial copy').toEqual([])
    expect(client.saves, 'Editing must not persist the workspace').toEqual([])
    expect(editor.getSnapshot().desired).toEqual({ workflow: workflow('personal', 2), ui_state: ui })
    expect(client.head).toEqual(original)
    expect(editor.getSnapshot().acknowledged).toEqual(original)
  })
}

test('undo and redo restore local graph and layout without persistence', async () => {
  const { editor, client } = await opened()
  const original = structuredClone(editor.getSnapshot().desired)
  const changed = { workflow: workflow('personal', 2), ui_state: { collapsed: ['take'] } }
  await editor.edit(() => changed)
  await editor.undo()
  expect(editor.getSnapshot().desired).toEqual(original)
  await editor.redo()
  expect(editor.getSnapshot().desired).toEqual(changed)
  expect(client.saves).toEqual([])
})

test('navigation neither writes nor consumes undo history', async () => {
  const { editor, client } = await opened()
  await editor.navigate(ui => ({ ...ui, navigation: 'group' }))
  expect(editor.getSnapshot().desired!.ui_state.navigation).toBe('group')
  expect(editor.getSnapshot().canUndo).toBe(false)
  expect(client.saves).toEqual([])
})

test('a long edit preserves intervening layout without saving on confirmation', async () => {
  const { editor, client } = await opened()
  const session = (await editor.beginEdit())!
  await editor.navigate(ui => ({ ...ui, navigation: 'group' }))
  await session.commit({ workflow: workflow('personal', 2) })
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 2))
  expect(editor.getSnapshot().desired!.ui_state.navigation).toBe('group')
  expect(client.saves).toEqual([])
})

test('a long edit cannot replace a different project session', async () => {
  const { editor, client } = await opened()
  const session = (await editor.beginEdit())!
  editor.open(project('other'), workspace('other'))
  await expect(session.commit({ workflow: workflow('personal', 2) })).rejects.toThrow('项目已切换')
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('other'))
  expect(client.saves).toEqual([])
})

test('a newer scientific edit invalidates a same-project long proposal', async () => {
  const { editor } = await opened()
  const session = (await editor.beginEdit())!
  await editor.edit(() => ({ workflow: workflow('personal', 3) }))
  await expect(session.commit({ workflow: workflow('personal', 2) })).rejects.toThrow()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
  expect(session.base.workflow).toEqual(workflow())
})

test('navigation preserves an existing redo operation', async () => {
  const { editor } = await opened()
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  await editor.undo()
  expect(editor.getSnapshot().canRedo).toBe(true)
  await editor.navigate(ui => ({ ...ui, navigation: 'group' }))
  expect(editor.getSnapshot().canRedo).toBe(true)
  await editor.redo()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 2))
  expect(editor.getSnapshot().desired!.ui_state.navigation).toBe('group')
})

test('manual save publishes graph and layout together against the acknowledged head', async () => {
  const { editor, client } = await opened()
  const changed = { workflow: workflow('personal', 2), ui_state: { collapsed: ['take'] } }
  await editor.edit(() => changed)
  expect(editor.getSnapshot().dirty).toBe(true)
  await editor.save()
  expect(client.saves).toEqual([{ projectId: 'personal', change: { ...changed, expected_draft_revision: 1, expected_workspace_revision: 1 } }])
  expect(editor.getSnapshot().dirty).toBe(false)
  expect(editor.getSnapshot().acknowledged?.ui_state).toEqual(changed.ui_state)
})

test('edits during an explicit save remain local and require another save', async () => {
  const { editor, client } = await opened()
  let complete!: (workspace: ProjectWorkspace) => void
  client.saveResponse = () => new Promise(resolve => { complete = resolve })
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  const saving = editor.save()
  await editor.edit(() => ({ workflow: workflow('personal', 3) }))
  complete({ ...workspace('personal', 2), draft: { project_id: 'personal', draft_revision: 2, workflow: workflow('personal', 2) } })
  await saving
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
  expect(editor.getSnapshot().dirty).toBe(true)
  expect(client.saves).toHaveLength(1)
})

test('failed publication preserves edits and an explicit retry cannot overwrite a changed head', async () => {
  const { editor, client } = await opened()
  client.saveResponse = async () => { throw new Error('write failed') }
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  await expect(editor.save()).rejects.toThrow('write failed')
  expect(editor.getSnapshot().dirty).toBe(true)
  client.head = { ...workspace('personal', 2), ui_state: { changedElsewhere: true } }
  await expect(editor.retry()).rejects.toThrow('不能自动覆盖')
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 2))
  expect(client.saves).toHaveLength(1)
})

test('retry recognizes a published save whose response failed', async () => {
  const { editor, client } = await opened()
  const publish = client.saveResponse
  client.saveResponse = async (projectId, change) => { await publish(projectId, change); throw new Error('response lost') }
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  await expect(editor.save()).rejects.toThrow('response lost')
  await editor.retry()
  expect(editor.getSnapshot().dirty).toBe(false)
  expect(editor.getSnapshot().phase).toBe('ready')
  expect(client.saves).toHaveLength(1)
})

test('discard removes local changes and history without sending a write', async () => {
  const { editor, client } = await opened()
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  editor.discard()
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow())
  expect(editor.getSnapshot().dirty).toBe(false)
  expect(editor.getSnapshot().canUndo).toBe(false)
  expect(client.saves).toEqual([])
})

test('unsaved work cannot be committed for execution', async () => {
  const { editor } = await opened()
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  await expect(editor.commitWorkflow()).rejects.toThrow('先手动保存')
})

test('an active run rejects content edits, undo and save while permitting viewing navigation', async () => {
  const { editor, client } = await opened()
  const proposal = (await editor.beginEdit())!
  editor.setReadOnly(true)
  await expect(editor.edit(() => ({ workflow: workflow('personal', 2) }))).rejects.toThrow('运行期间')
  await expect(editor.undo()).rejects.toThrow('运行期间')
  await expect(proposal.commit({ workflow: workflow('personal', 2) })).rejects.toThrow('运行期间')
  expect(() => editor.save()).toThrow('运行期间')
  await editor.navigate(ui => ({ ...ui, navigation: 'group' }))
  expect(editor.getSnapshot().dirty).toBe(false)
  expect(client.saves).toEqual([])
})

test('retry after copy publication and failed confirmation preserves later edits', async () => {
  const client = new EditorClient()
  const editor = new WorkspaceEditor(client)
  editor.open(project('personal', 'default_example'), client.head)
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  let failReading = true
  client.projectWorkspace = async projectId => {
    if (failReading) throw new Error('confirmation unavailable')
    return { ...client.head, project_id: projectId }
  }
  await expect(editor.save()).rejects.toThrow('confirmation unavailable')
  await editor.edit(() => ({ workflow: workflow('personal', 3) }))
  failReading = false
  await editor.retry()
  expect(client.copies).toHaveLength(1)
  expect(client.head.draft!.workflow).toEqual(workflow('copy', 3))
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('copy', 3))
  expect(editor.getSnapshot().dirty).toBe(false)
})

test('an outstanding tutorial input inspection prevents a save from omitting the input', async () => {
  const client = new EditorClient()
  const editor = new WorkspaceEditor(client)
  editor.open(project('personal', 'default_example'), client.head)
  let finish!: () => void
  client.inspectProjectInput = (projectId, inputRef) => new Promise(resolve => { finish = () => resolve({ project_id: projectId, project_input_ref: inputRef, content_digest: 'digest', format: 'fasta', records: [], total_length: 1 }) })
  const publishing = editor.sources.publishProjectInput('personal', { filename: 'new.fa', content_base64: 'QQ==' }, 'fasta')
  await expect(editor.save()).rejects.toThrow('输入检查尚未完成')
  expect(client.copies).toEqual([])
  finish()
  await publishing
  await editor.save()
  expect(client.copies).toHaveLength(1)
  expect(client.copiedInputs).toEqual([expect.objectContaining({ filename: 'new.fa', content_base64: 'QQ==' })])
  expect(editor.getSnapshot().dirty).toBe(false)
})

test('named-version edits publish one complete fork only on manual save', async () => {
  const client = new EditorClient()
  client.head = workspace('personal', 8)
  const editor = new WorkspaceEditor(client)
  const viewed = workspace('personal', 2)
  const forks: unknown[] = []
  client.forkVersion = async (projectId, versionId, workflow, uiState, returnRevision) => {
    forks.push({ projectId, versionId, workflow, uiState, returnRevision })
    return { ...workspace(projectId, 9), draft: { project_id: projectId, draft_revision: 9, workflow }, ui_state: uiState, source_version_id: versionId, return_workspace_revision: returnRevision }
  }
  editor.open(project(), viewed, { workspace: viewed, return_workspace_revision: 8, version: { project_id: 'personal', version_id: 'version-2', name: 'Original', created_at: '2026-10-16', workspace_revision: 2, draft_revision: 2, ui_state_revision: 2 } })
  const changed = { workflow: workflow('personal', 4), ui_state: { canvas: { collapsed: ['take'] } } }
  await editor.edit(() => changed)
  expect(forks).toEqual([])
  await editor.save()
  expect(forks).toEqual([{ projectId: 'personal', versionId: 'version-2', workflow: changed.workflow, uiState: changed.ui_state, returnRevision: 8 }])
  expect(client.saves).toEqual([])
  expect(editor.getSnapshot().dirty).toBe(false)
  expect(editor.getSnapshot().acknowledged!.return_workspace_revision).toBe(8)
})

test('returning to saved work blocks edits and duplicate operations until the response settles', async () => {
  const { editor, client } = await opened()
  client.head.return_workspace_revision = 1
  const session = (await editor.beginEdit())!
  let finish!: (workspace: ProjectWorkspace) => void
  let calls = 0
  client.returnWorkspace = () => { calls += 1; return new Promise(resolve => { finish = resolve }) }
  const returning = editor.returnToSavedWork()
  expect(editor.getSnapshot().readOnly).toBe(true)
  await expect(editor.edit(() => ({ workflow: workflow('personal', 3) }))).rejects.toThrow('正在返回')
  await expect(editor.navigate(ui => ({ ...ui, navigation: 'different' }))).rejects.toThrow('正在返回')
  await expect(session.commit({ workflow: workflow('personal', 3) })).rejects.toThrow('正在返回')
  await expect(editor.returnToSavedWork()).rejects.toThrow('正在返回')
  expect(calls).toBe(1)
  finish(workspace('personal', 2))
  await returning
  expect(editor.getSnapshot().readOnly).toBe(false)
  await editor.edit(() => ({ workflow: workflow('personal', 3) }))
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
})

test('a proposal opened during tutorial save keeps edits under the resulting personal identity', async () => {
  const client = new EditorClient()
  const editor = new WorkspaceEditor(client)
  editor.open(project('personal', 'default_example'), client.head)
  const publishCopy = client.copyExample.bind(client)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  client.copyExample = async (...args) => { await gate; return publishCopy(...args) }
  await editor.edit(() => ({ workflow: workflow('personal', 2) }))
  const saving = editor.save()
  const session = (await editor.beginEdit())!
  const captured = { ...session.base.workflow, nodes: workflow('personal', 3).nodes }
  expect(captured.workflow_id).toBe('personal')
  release()
  await saving
  expect(editor.getSnapshot().project!.id).toBe('copy')
  await session.commit({ workflow: captured })
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('copy', 3))
  expect(editor.getSnapshot().dirty).toBe(true)
  await editor.save()
  expect(client.head.draft!.workflow).toEqual(workflow('copy', 3))
})

test('failed return releases the editing lock and preserves the current workspace', async () => {
  const { editor, client } = await opened()
  const original = editor.getSnapshot().desired
  client.returnWorkspace = async () => { throw new Error('return failed') }
  await expect(editor.returnToSavedWork()).rejects.toThrow('return failed')
  expect(editor.getSnapshot().readOnly).toBe(false)
  expect(editor.getSnapshot().desired).toEqual(original)
  await editor.edit(() => ({ workflow: workflow('personal', 3) }))
  expect(editor.getSnapshot().desired!.workflow).toEqual(workflow('personal', 3))
})
