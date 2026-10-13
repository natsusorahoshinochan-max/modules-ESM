import type { JsonObject, ProjectMetadata, RunProjection, Workflow, WorkflowDraft } from './protocol/client'

export type WorkspaceProject = ProjectMetadata & {
  created_at: string
  modified_at: string
  deleted_at: string | null
  reference_results_project_id: string | null
}

export type ProjectWorkspace = {
  project_id: string
  workspace_revision: number
  draft: WorkflowDraft | null
  ui_state_revision: number
  ui_state: JsonObject
  source_version_id: string | null
  return_workspace_revision: number | null
}

export type WorkflowVersion = {
  project_id: string
  version_id: string
  name: string
  created_at: string
  workspace_revision: number
  draft_revision: number
  ui_state_revision: number
}

export type WorkflowVersionView = {
  version: WorkflowVersion
  workspace: ProjectWorkspace
  return_workspace_revision: number
}

export type WorkflowCommitSnapshot = {
  project_id: string
  workflow_commit_id: string
  source_draft_revision: number
  workflow: Workflow
  scientific_definitions: JsonObject[]
  scientific_identity: JsonObject
}

export type WorkflowScienceComparison = {
  project_id: string
  workflow_project_id: string
  workflow_commit_id: string
  status: 'current' | 'stale' | 'unknown'
  issues: Array<{ code: string; severity: 'error' | 'warning'; message: string; field_path: Array<string | number>; node_id?: string }>
}

export type ProjectWorkspaceApi = {
  projects(name?: string): Promise<{ projects: WorkspaceProject[] }>
  deletedProjects(): Promise<{ projects: WorkspaceProject[] }>
  renameProject(projectId: string, name: string): Promise<WorkspaceProject>
  duplicateProject(projectId: string, name: string): Promise<WorkspaceProject>
  trashProject(projectId: string): Promise<WorkspaceProject>
  restoreProject(projectId: string): Promise<WorkspaceProject>
  deleteProject(projectId: string): Promise<{ project_id: string; deleted: true }>
  projectWorkspace(projectId: string): Promise<ProjectWorkspace>
  workflowVersions(projectId: string): Promise<{ project_id: string; versions: WorkflowVersion[] }>
  nameWorkflowVersion(projectId: string, name: string): Promise<WorkflowVersion>
  workflowVersion(projectId: string, versionId: string): Promise<WorkflowVersionView>
  forkVersion(projectId: string, versionId: string, workflow: Workflow, uiState: JsonObject, returnWorkspaceRevision: number): Promise<ProjectWorkspace>
  returnWorkspace(projectId: string, workspaceRevision: number): Promise<ProjectWorkspace>
  cancelRun(projectId: string, runId: string): Promise<JsonObject>
  runProjection(projectId: string, runId: string): Promise<RunProjection>
}

export type ProjectWorkspaceError = {
  error: { code: string; message: string; details: { run_ids?: string[] } }
}

export function workspaceErrorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : (reason as ProjectWorkspaceError).error.message
}
