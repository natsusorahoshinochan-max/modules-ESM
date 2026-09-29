import { useCallback, useEffect, useState } from 'react'
import { ArchiveRestore, Copy, FolderOpen, History, Plus, Save, Trash2, X } from 'lucide-react'
import { workspaceErrorMessage, type ProjectWorkspace, type ProjectWorkspaceApi, type ProjectWorkspaceError, type WorkflowVersion, type WorkflowVersionView, type WorkspaceProject } from './project-workspace'
import './project-workspace.css'
import { InteractionDialog } from './InteractionDialog'

type Props = {
  api: ProjectWorkspaceApi
  currentProjectId: string
  beforeAction: () => Promise<boolean>
  onOpenProject: (project: WorkspaceProject) => Promise<void>
  onViewVersion: (project: WorkspaceProject, view: WorkflowVersionView) => Promise<void>
  onReturnWorkspace: (project: WorkspaceProject) => Promise<ProjectWorkspace | undefined>
  onProjectChanged: (project: WorkspaceProject | null, deletedId?: string) => void
  onCreateProject: () => Promise<void>
  onClose: () => void
}

type PendingDelete = { project: WorkspaceProject; runIds: string[] }

export function ProjectWorkspaceDialog({ api, currentProjectId, beforeAction, onOpenProject, onViewVersion, onReturnWorkspace, onProjectChanged, onCreateProject, onClose }: Props) {
  const [projects, setProjects] = useState<WorkspaceProject[]>([])
  const [deletedProjects, setDeletedProjects] = useState<WorkspaceProject[]>([])
  const [selectedId, setSelectedId] = useState(currentProjectId)
  const [tab, setTab] = useState<'active' | 'deleted'>('active')
  const [query, setQuery] = useState('')
  const [workspace, setWorkspace] = useState<ProjectWorkspace>()
  const [versions, setVersions] = useState<WorkflowVersion[]>([])
  const [nameDraft, setNameDraft] = useState<{ projectId: string; value: string }>()
  const [versionName, setVersionName] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<WorkspaceProject>()
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>()
  const [waiting, setWaiting] = useState(false)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [workspaceLoadError, setWorkspaceLoadError] = useState('')
  const project = (tab === 'active' ? projects : deletedProjects).find((entry) => entry.id === selectedId)
  const name = nameDraft?.projectId === selectedId ? nameDraft.value : project?.name ?? ''

  const refresh = useCallback(async () => {
    const [active, deleted] = await Promise.all([api.projects(), api.deletedProjects()])
    setProjects(active.projects)
    setDeletedProjects(deleted.projects)
  }, [api])

  useEffect(() => {
    let active = true
    void refresh().then(() => { if (active) setLoading(false) }, (reason) => { if (active) { setError(workspaceErrorMessage(reason)); setLoading(false) } })
    return () => { active = false }
  }, [refresh])

  useEffect(() => {
    if (!project || tab !== 'active') { setWorkspace(undefined); setVersions([]); setWorkspaceLoading(false); return }
    let active = true
    setWorkspaceLoading(true)
    setWorkspaceLoadError('')
    setWorkspace(undefined)
    setVersions([])
    void Promise.all([api.projectWorkspace(project.id), api.workflowVersions(project.id)]).then(([current, history]) => {
      if (active) { setWorkspace(current); setVersions(history.versions); setWorkspaceLoading(false) }
    }, (reason) => { if (active) { setWorkspaceLoadError(workspaceErrorMessage(reason)); setWorkspaceLoading(false) } })
    return () => { active = false }
  }, [api, project, tab])

  const run = async (operation: () => Promise<void>) => {
    setBusy(true)
    setError('')
    setMessage('')
    try { if (await beforeAction()) await operation() } catch (reason) { setError(workspaceErrorMessage(reason)) } finally { setBusy(false) }
  }

  const movedToTrash = useCallback(async (removed: WorkspaceProject) => {
    setPendingDelete(undefined)
    setWaiting(false)
    onProjectChanged(null, removed.id)
    await refresh()
    setMessage(`“${removed.name}”已移至最近删除，内容与运行证据保留。`)
  }, [onProjectChanged, refresh])

  const trash = async (target: WorkspaceProject) => {
    try { await movedToTrash(await api.trashProject(target.id)) } catch (reason) {
      if (!(reason instanceof Error) && (reason as ProjectWorkspaceError).error.code === 'project_has_active_runs') {
        setPendingDelete({ project: target, runIds: (reason as ProjectWorkspaceError).error.details.run_ids ?? [] })
      } else { throw reason }
    }
  }

  useEffect(() => {
    if (!waiting || !pendingDelete) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const attempt = async () => {
      try {
        const removed = await api.trashProject(pendingDelete.project.id)
        if (!stopped) await movedToTrash(removed)
      } catch (reason) {
        if (stopped) return
        if (!(reason instanceof Error) && (reason as ProjectWorkspaceError).error.code === 'project_has_active_runs') {
          timer = setTimeout(() => void attempt(), 1500)
        } else { setWaiting(false); setError(workspaceErrorMessage(reason)) }
      }
    }
    timer = setTimeout(() => void attempt(), 1500)
    return () => { stopped = true; if (timer !== undefined) clearTimeout(timer) }
  }, [api, movedToTrash, pendingDelete, waiting])

  const selectedProjects = (tab === 'active' ? projects : deletedProjects).filter((item) => item.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const disabled = busy || waiting
  const writable = project && !project.seed

  return <InteractionDialog className="project-workspace-dialog" title="项目与版本" busy={busy} onClose={onClose}>
    <header><FolderOpen size={22} /><div><h2 id="workspace-title">项目与版本</h2><p>保存的流程、布局与输入可在重新打开后恢复。</p></div><button className="workspace-icon" aria-label="关闭项目管理" disabled={busy} onClick={onClose}><X size={20} /></button></header>
    <div className="workspace-tabs" role="tablist" aria-label="项目列表"><button role="tab" aria-selected={tab === 'active'} disabled={disabled} onClick={() => { setTab('active'); setSelectedId(currentProjectId) }}>项目 ({projects.length})</button><button role="tab" aria-selected={tab === 'deleted'} disabled={disabled} onClick={() => { setTab('deleted'); setSelectedId(deletedProjects[0]?.id ?? '') }}>最近删除 ({deletedProjects.length})</button></div>
    {error && <p className="workspace-error" role="alert">{error}</p>}
    {message && <p className="workspace-message" role="status">{message}</p>}
    <div className="workspace-body">
      <aside><label>搜索项目<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按名称查找" /></label>{loading ? <p role="status">正在读取项目…</p> : selectedProjects.length === 0 ? <p>没有匹配的项目。</p> : <ul>{selectedProjects.map((item) => <li key={item.id}><button disabled={disabled} className={item.id === selectedId ? 'selected' : ''} onClick={() => { setSelectedId(item.id); setConfirmDelete(undefined) }}><strong>{item.name}</strong><small>{item.id === currentProjectId ? '当前项目 · ' : ''}{item.seed ? '只读示例' : '个人项目'}{item.latest_run_id ? ' · 有运行记录' : ''}</small>{item.deleted_at && <small>删除于 {new Date(item.deleted_at).toLocaleString()}</small>}</button></li>)}</ul>}<button disabled={disabled} onClick={() => void run(onCreateProject)}><Plus size={16} />新建项目</button></aside>
      <main>{!project ? <p>选择项目以查看保存内容。</p> : tab === 'deleted' ? <section><h3>{project.name}</h3><p>恢复后保留原项目身份、输入、命名版本及运行证据。</p><div className="workspace-actions"><button disabled={disabled} onClick={() => void run(async () => { const restored = await api.restoreProject(project.id); onProjectChanged(restored); await refresh(); setTab('active'); setSelectedId(restored.id); setMessage('项目已恢复。') })}><ArchiveRestore size={16} />恢复项目</button><button className="workspace-danger" disabled={disabled} onClick={() => setConfirmDelete(project)}><Trash2 size={16} />永久删除…</button></div>{confirmDelete?.id === project.id && <div className="workspace-confirm" role="alert"><p>永久删除“{project.name}”的输入、版本和运行证据，无法恢复。</p><button disabled={disabled} onClick={() => setConfirmDelete(undefined)}>保留项目</button><button className="workspace-danger" disabled={disabled} onClick={() => void run(async () => { await api.deleteProject(project.id); onProjectChanged(null, project.id); setConfirmDelete(undefined); setSelectedId(''); await refresh(); setMessage('项目已永久删除。') })}>确认永久删除</button></div>}</section> : <>
        <section><h3>{project.name}</h3><small className="workspace-identity">{project.id}</small><div className="workspace-actions"><button disabled={disabled} onClick={() => void run(() => onOpenProject(project))}><FolderOpen size={16} />打开项目</button><button disabled={disabled || !workspace?.draft} onClick={() => void run(async () => { const copy = await api.duplicateProject(project.id, `${project.name} · 副本`); onProjectChanged(copy); await refresh(); setSelectedId(copy.id); setMessage('已复制当前流程、所需输入与布局；副本尚无运行结果。') })}><Copy size={16} />复制项目</button><button className="workspace-danger" disabled={disabled || !writable} onClick={() => void run(() => trash(project))}><Trash2 size={16} />移至最近删除</button></div><form onSubmit={(event) => { event.preventDefault(); void run(async () => { const renamed = await api.renameProject(project.id, name.trim()); onProjectChanged(renamed); await refresh(); setNameDraft({ projectId: renamed.id, value: renamed.name }); setMessage('项目已重命名。') }) }}><label>项目名称<input maxLength={256} disabled={disabled || !writable} value={name} onChange={(event) => setNameDraft({ projectId: project.id, value: event.target.value })} /></label><button disabled={disabled || !writable || !name.trim() || name.trim() === project.name}>保存名称</button></form>{project.seed && <p className="workspace-muted">示例保持只读，可复制为个人项目。</p>}</section>
        <section><h3><History size={17} />当前工作</h3>{!workspace ? <p role={workspaceLoadError ? 'alert' : 'status'}>{workspaceLoading ? '读取保存状态…' : workspaceLoadError || '尚无保存内容'}</p> : <><p>流程：{workspace.draft ? `Draft ${workspace.draft.draft_revision} 已保存` : '尚无保存的 Draft'}<br />布局：{workspace.ui_state_revision === 0 ? '尚无保存的布局' : `UI ${workspace.ui_state_revision} 已保存`}</p>{workspace.source_version_id && <p>当前工作来自命名版本：{versions.find((item) => item.version_id === workspace.source_version_id)?.name ?? workspace.source_version_id}</p>}{workspace.return_workspace_revision !== null && <button disabled={disabled} onClick={() => void run(async () => { const returned = await onReturnWorkspace(project); if (returned) setWorkspace(returned); setMessage('已返回打开旧版本前的工作。') })}>返回打开版本前的工作</button>}</>}</section>
        <section><h3><Save size={17} />命名版本</h3><p className="workspace-muted">可保存未完成流程。打开旧版先查看，首次修改时建立新的当前工作。</p><form onSubmit={(event) => { event.preventDefault(); void run(async () => { await api.nameWorkflowVersion(project.id, versionName.trim()); setVersions((await api.workflowVersions(project.id)).versions); setVersionName(''); setMessage('已保存流程与布局的精确版本。') }) }}><label>版本名称<input value={versionName} maxLength={256} disabled={disabled || !writable} onChange={(event) => setVersionName(event.target.value)} placeholder="例如：初始设计方案" /></label><button disabled={disabled || !writable || !workspace?.draft || !versionName.trim()}>保存版本</button></form>{versions.length === 0 ? <p className="workspace-muted">尚未命名版本。</p> : <ul className="workspace-version-list">{versions.map((version) => <li key={version.version_id}><div><strong>{version.name}</strong><small>{new Date(version.created_at).toLocaleString()} · Draft {version.draft_revision} · UI {version.ui_state_revision}</small></div><button disabled={disabled} onClick={() => void run(async () => { const view = await api.workflowVersion(project.id, version.version_id); await onViewVersion(project, view) })}>查看版本</button></li>)}</ul>}</section>
      </>}</main>
    </div>
    {pendingDelete && <section className="workspace-running-delete" role="status"><strong>“{pendingDelete.project.name}”仍有运行尚未结束。</strong><p>{waiting ? '正在等待运行关闭后移至最近删除。关闭此窗口会停止等待删除。' : '可以等待完成，或明确取消运行后删除。'}</p><div className="workspace-actions"><button disabled={busy} onClick={() => { setWaiting(false); setPendingDelete(undefined) }}>保留项目</button><button disabled={disabled} onClick={() => setWaiting(true)}>等待完成后删除</button><button className="workspace-danger" disabled={disabled || pendingDelete.runIds.length === 0} onClick={() => void run(async () => { for (const runId of pendingDelete.runIds) await api.cancelRun(pendingDelete.project.id, runId); setWaiting(true) })}>取消运行后删除</button></div></section>}
  </InteractionDialog>
}
