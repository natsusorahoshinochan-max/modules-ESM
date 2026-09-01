export type JsonObject = Record<string, unknown>
export type ProjectMetadata = { id: string; name: string; seed: boolean; project_kind: 'default_example' | 'canonical_verification' | 'personal'; copied_from_project_id: string | null; latest_run_id: string | null }
export type WorkflowNode = { node_id: string; node_type_id: string; binding_id: string; node_parameters: Record<string, unknown>; binding_parameters: Record<string, unknown> }
export type Workflow = { schema_version: string; workflow_id: string; nodes: WorkflowNode[]; edges: Array<{ source_node_id: string; source_port: string; target_node_id: string; target_port: string }>; observation_selectors: JsonObject[]; selection_objectives: JsonObject[] }
export type WorkflowDraft = { project_id: string; draft_revision: number; workflow: Workflow; authoring_compositions: Array<{ composition_id: string; capability_id: string; normalized_document: JsonObject; managed_node_ids: string[]; exposed_outputs: Array<{ role: string; node_id: string; port_name: string }> }> }
export type CatalogSnapshot = { contracts: Array<{ reference: { contract_kind: string; contract_id: string }; descriptor: JsonObject }>; availability: JsonObject[] }
export type PromptProjectionState = 'source' | 'current' | 'changed' | 'cleared' | 'inserted' | 'pending-delete'
export type PromptResidue = { residue_handle: string; chain_id: string; residue_label: string; position: number }
export type PromptTrackValue = { residue_handle: string; value: null | string | number | { atoms: Array<{ atom_handle: string; atom_label: string; coordinates: [number, number, number] }> }; state: PromptProjectionState }
export type PromptFunctionAnnotation = { label: string; start_residue_handle: string; end_residue_handle: string; state: PromptProjectionState }
export type PromptDiagnostic = { code: string; message: string; field_path: Array<string | number>; residue_handle?: string }
export type PromptSnapshot = { document: JsonObject; residues: PromptResidue[]; tracks: Record<string, PromptTrackValue[]>; function_annotations: PromptFunctionAnnotation[]; source: JsonObject }
export type PromptPreview = Omit<PromptSnapshot, 'document' | 'source'> & { normalized_document: JsonObject; preview_digest: string; changes: JsonObject[]; random_selections: JsonObject[]; source_merges: JsonObject[]; diagnostics: PromptDiagnostic[]; summary: JsonObject }
export type RunStatus = 'admitted' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'
export type RunReceipt = { project_id: string; run_id: string; workflow_commit_id: string; admitted_sequence: number; event_cursor: string }
type NodeDispositionBase = { node_id: string; terminal_sequence: number }
export type NodeDisposition =
  | NodeDispositionBase & { outcome: 'succeeded'; blocked_by: []; resolution: 'executed' | 'cache_replayed' }
  | NodeDispositionBase & { outcome: 'blocked'; blocked_by: string[] }
  | NodeDispositionBase & { outcome: 'failed' | 'cancelled' | 'interrupted'; blocked_by: [] }
export type RunProjection = { project_id: string; run_id: string; workflow_commit_id: string; status: RunStatus; ledger_cursor: string; node_dispositions: NodeDisposition[]; outputs: JsonObject[]; artifact_index: JsonObject[]; selection_results?: Array<{ status: string; selection_node_id: string; selected_candidate_ids: string[]; objectives: JsonObject[] }> }
export type RunEvent =
  | { type: 'run_admitted'; workflow_commit_id: string }
  | { type: 'run_started'; started_at: string }
  | { type: 'node_attempt_started'; node_id: string; node_attempt_id: string }
  | { type: 'node_disposition'; disposition: NodeDisposition }
  | { type: 'run_terminal'; status: Extract<RunStatus, 'succeeded' | 'failed' | 'cancelled' | 'interrupted'> }
  | { type: 'engine_invocation_started' | 'engine_invocation_terminal' | 'node_attempt_terminal' | 'operation_attempt_started' | 'operation_attempt_terminal' | 'readiness_attested' | 'replay_complete' | 'replay_started' | 'selection_terminal' }
export type RunEventEnvelope = { schema_namespace: 'protein-workbench-public/v2'; project_id: string; run_id: string; sequence: number; cursor: string; emitted_at: string; event: RunEvent }

export class PublicV2Client {
  constructor(private readonly baseUrl = '') {}
  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: init?.body ? { 'Content-Type': 'application/json' } : undefined })
    if (!response.ok) throw await response.json()
    return response.json() as Promise<T>
  }
  catalog() { return this.json<CatalogSnapshot>('/api/v2/catalog') }
  authoringCapabilities() { return this.json<JsonObject>('/api/v2/authoring-capabilities') }
  projects(name?: string) { return this.json<{ projects: ProjectMetadata[] }>(`/api/v2/projects${name ? `?name=${encodeURIComponent(name)}` : ''}`) }
  createProject(name: string) { return this.json<ProjectMetadata>('/api/v2/projects', { method: 'POST', body: JSON.stringify({ name }) }) }
  copyExample(projectId: string, name: string) { return this.json<ProjectMetadata>(`/api/v2/projects/${projectId}:copy`, { method: 'POST', body: JSON.stringify({ name }) }) }
  workflowDraft(projectId: string) { return this.json<WorkflowDraft>(`/api/v2/projects/${projectId}/workflow/draft`) }
  saveWorkflowDraft(projectId: string, workflow: Workflow) { return this.json<WorkflowDraft>(`/api/v2/projects/${projectId}/workflow/draft`, { method: 'PUT', body: JSON.stringify({ workflow }) }) }
  openPrompt(projectId: string, compositionId: string) { return this.json<PromptSnapshot>(`/api/v2/projects/${projectId}/prompt-authoring:open`, { method: 'POST', body: JSON.stringify({ mode: 'reopen', composition_id: compositionId }) }) }
  previewPrompt(projectId: string, compositionId: string, document: JsonObject) { return this.json<PromptPreview>(`/api/v2/projects/${projectId}/prompt-authoring:preview`, { method: 'POST', body: JSON.stringify({ composition_id: compositionId, document }) }) }
  applyPrompt(projectId: string, compositionId: string, preview: PromptPreview) { return this.json<{ draft: WorkflowDraft }>(`/api/v2/projects/${projectId}/prompt-authoring:apply`, { method: 'POST', body: JSON.stringify({ intent: 'replace', composition_id: compositionId, normalized_document: preview.normalized_document, preview_digest: preview.preview_digest }) }) }
  commitWorkflow(projectId: string, workflow: Workflow) { return this.json<{ workflow_commit_id: string }>(`/api/v2/projects/${projectId}/workflow:commit`, { method: 'POST', body: JSON.stringify({ workflow }) }) }
  startRun(projectId: string, workflowCommitId: string) { return this.json<RunReceipt>(`/api/v2/projects/${projectId}/runs`, { method: 'POST', body: JSON.stringify({ workflow_commit_id: workflowCommitId, client_request_id: crypto.randomUUID() }) }) }
  runProjection(projectId: string, runId: string) { return this.json<RunProjection>(`/api/v2/projects/${projectId}/runs/${runId}`) }
  typedValue(projectId: string, runId: string, nodeId: string, outputPort: string, index = 0) { return this.json<{ port_type_id: string; value: unknown }>(`/api/v2/projects/${projectId}/runs/${runId}/outputs/${nodeId}/${outputPort}/values/${index}`) }
  runEvents(projectId: string, runId: string, afterCursor?: string) { const scheme = location.protocol === 'https:' ? 'wss' : 'ws'; const query = afterCursor ? `?after_sequence=${encodeURIComponent(afterCursor)}` : ''; return new WebSocket(`${scheme}://${location.host}${this.baseUrl}/api/v2/projects/${projectId}/runs/${runId}/events${query}`) }
}
