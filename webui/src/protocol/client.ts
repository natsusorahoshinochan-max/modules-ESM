import type { ModuleUiManifest } from '../module-ui'
import type { ProjectWorkspace, WorkflowVersion, WorkflowVersionView, WorkflowCommitSnapshot, WorkflowScienceComparison } from '../project-workspace'
import type { ProjectInputInspection, ProjectInputPublication } from '../input-sources'

export type JsonObject = Record<string, unknown>
export type ContractReference = { contract_kind: string; contract_id: string }
export type AuthoringCapabilities = { node_roles: Array<{ node_type: ContractReference; role: 'ordinary_node' }>; protocol_digest: string; schema_namespace: string }
export type ProjectMetadata = { id: string; name: string; seed: boolean; project_kind: 'default_example' | 'canonical_verification' | 'personal'; copied_from_project_id: string | null; reference_results_project_id: string | null; created_at: string; modified_at: string; deleted_at: string | null; latest_run_id: string | null }
export type WorkflowNode = { node_id: string; node_type_id: string; binding_id: string; node_parameters: Record<string, unknown>; binding_parameters: Record<string, unknown> }
export type Workflow = { schema_version: string; workflow_id: string; nodes: WorkflowNode[]; edges: Array<{ source_node_id: string; source_port: string; target_node_id: string; target_port: string }>; observation_selectors: JsonObject[]; selection_objectives: JsonObject[] }
export type WorkflowDraft = { project_id: string; draft_revision: number; workflow: Workflow }
export type CatalogSnapshot = { contracts: Array<{ reference: ContractReference; descriptor: JsonObject }>; availability: JsonObject[] }
export type CandidateReference = { candidate_id: string; data_type_id: string; content_digest: string }
export type ResultCandidate = { item_index: number; reference: CandidateReference; parent_ids: string[]; metadata: JsonObject; sequence: string | null; has_structure: boolean }
export type ResultCollectionPage = { collection_id: string; item_type: string; total: number; offset: number; items: ResultCandidate[] }
export type ResultLocation = { node_id: string; output_port: string; value_index: number }
export type PublishedObservation = { subject: CandidateReference; metric: ContractReference; method: ContractReference; context: JsonObject; context_profile: JsonObject; value: unknown; residue_axis: unknown; source_partition: string }
export type PublishedAlignment = { subject: CandidateReference; reference: CandidateReference; transform: { maps_from_role: string; maps_to_role: string; row_vector_rotation: number[][]; translation: number[] }; rmsd: number; coverage: number; method: ContractReference; [field: string]: unknown }
export type PublishedPrompt = { residue_ids: string[]; sequence: Array<string | null>; coordinates: Array<{ atoms: Array<[string, [number, number, number]]> } | null>; secondary_structure: Array<string | null> | null; sasa: Array<number | null> | null; function_annotations: Array<{ label: string; start_residue_id: string; end_residue_id: string }> }
export type PublishedStructure = { text: string; format: 'pdb' | 'mmcif' }
export type PublishedResultValue =
  | { kind: 'scores'; value: { collection_id: string; entries: PublishedObservation[] } }
  | { kind: 'candidate_sequences'; value: { entries: Array<{ subject: CandidateReference; sequence: string }> } }
  | { kind: 'alignment'; value: PublishedAlignment }
  | { kind: 'sequence'; value: { sequence: string; residue_ids: string[] | null } }
  | { kind: 'structure'; value: PublishedStructure }
  | { kind: 'prompt'; value: PublishedPrompt }
  | { kind: 'axis_layout'; value: { residue_ids: string[]; chain_ids: string[] } }
export type CanonicalTypedValue = { port_type_id: string; value: unknown }
export type PublishedOutput = { node_id: string; output_port: string; port_type: ContractReference; content_digest: string; result_identity: string; value_count: number; producer_provenance: JsonObject }
export type PublishedArtifact = { artifact_reference: string; artifact_kind: string; node_id: string; output_port: string; media_type: string; filename: string; size: number; content_digest: string; candidate_id?: string }

export type PromptAuthoringNodeTypeId = 'prompt_authoring.author' | 'prompt_authoring.decompose' | 'prompt_authoring.assemble'
export type ResidueDataNodeTypeId = 'residue_data.materialize_sequence'
export type StructureAnnotationNodeTypeId = 'structure_annotation.observed_to_conditioning'
export type ConditioningPortTypeId = 'residue.condition.sequence' | 'residue.condition.coordinates' | 'residue.condition.secondary_structure' | 'residue.condition.sasa' | 'residue.condition.function_annotations'
export type ObservedAnnotationPortTypeId = 'structure_annotation.secondary_structure.observed' | 'structure_annotation.sasa.observed'
export type PromptAuthorPortTypeId = 'protein.sequence' | 'structure_transform.resolved_residue_axis' | 'protein.prompt'
export const promptAuthorNodeTypeId: PromptAuthoringNodeTypeId = 'prompt_authoring.author'
export const promptAuthorDocumentParameter = 'document'
export const promptTrackKeys = ['sequence', 'coordinates', 'secondary_structure', 'sasa'] as const
export type PromptTrackKey = (typeof promptTrackKeys)[number]
export const promptTrackConditioningPortTypes: Record<PromptTrackKey, ConditioningPortTypeId> = { sequence: 'residue.condition.sequence', coordinates: 'residue.condition.coordinates', secondary_structure: 'residue.condition.secondary_structure', sasa: 'residue.condition.sasa' }

export type PromptAtomCoordinates = { atom_name: string; coordinates: [number, number, number] }
export type PromptChainDeclaration = { chain_id: string; length: number }
export type PromptTargetResidue = { residue_id: string; origin: 'source' | 'inserted' }
export type PromptTrackEditValue = string | number | { atom_coordinates: PromptAtomCoordinates[] }
export type PromptTrackEdit =
  | { track: PromptTrackKey; action: 'clear' | 'preserve'; residue_id: string }
  | { track: PromptTrackKey; action: 'replace'; residue_id: string; value: PromptTrackEditValue }
export type PromptRigidTransform = { rotation_matrix: [[number, number, number], [number, number, number], [number, number, number]]; origin: [number, number, number]; translation: [number, number, number]; residue_ids: string[] }
export type PromptDocumentFunctionAnnotation = { label: string; start_residue_id: string; end_residue_id: string }
export type PromptRandomOperation =
  | { kind: 'mask'; seed: number; count: number; track: PromptTrackKey; eligible_residue_ids?: string[] }
  | { kind: 'insert'; seed: number; count: number; eligible_chain_ids?: string[]; target_residues?: PromptTargetResidue[] }
export type PromptMergeCorrespondence =
  | { disposition: 'match' | 'insert'; source_residue_id: string; target_residue_id: string }
  | { disposition: 'source_gap'; source_residue_id: string }
  | { disposition: 'target_gap'; target_residue_id: string }
export type PromptTrackAdoption = { track: PromptTrackKey; source_residue_ids: string[]; mask_policy: 'adopt' | 'preserve' }
export type PromptSourceMerge = { source_index: number; correspondence: PromptMergeCorrespondence[]; track_adoptions: PromptTrackAdoption[]; adopt_annotations: PromptDocumentFunctionAnnotation[]; remove_annotations: PromptDocumentFunctionAnnotation[] }
export type PromptVersionContext = { version_id: string }
export type PromptAuthoringDocument = {
  chains?: PromptChainDeclaration[]
  target_residues?: PromptTargetResidue[]
  track_edits?: PromptTrackEdit[]
  rigid_transforms?: PromptRigidTransform[]
  function_annotations?: PromptDocumentFunctionAnnotation[]
  random_operations?: PromptRandomOperation[]
  source_merges?: PromptSourceMerge[]
}

export type PromptProjectionState = 'source' | 'current' | 'changed' | 'cleared' | 'inserted' | 'pending-delete'
export type PromptResidue = { residue_handle: string; residue_id: string; chain_id: string; residue_label: string; position: number; state: 'current' | 'inserted' | 'pending-delete' }
export type PromptCoordinatesValue = { atoms: Array<PromptAtomCoordinates & { atom_handle: string }> }
export type PromptTrackValue = { residue_handle: string; value: null | string | number | PromptCoordinatesValue; state: PromptProjectionState }
export type PromptTrackProjection = { present: boolean; values: PromptTrackValue[] }
export type PromptFunctionAnnotation = { label: string; start_residue_handle: string; end_residue_handle: string; state: PromptProjectionState }
export type PromptDiagnostic = { code: string; message: string; field_path: Array<string | number>; residue_handle?: string }
export type PromptRandomSelection = { operation_index: number; kind: 'insert' | 'mask'; realized_residue_handles: string[] }
export type PromptMergeSource = { source_index: number; source: JsonObject; residues: PromptResidue[]; tracks: Record<PromptTrackKey, PromptTrackProjection>; function_annotations: PromptFunctionAnnotation[] }
export type ESM3ConditioningProjection = {
  status: 'compatible' | 'unsupported'
  reason: string | null
  operations: Record<'generate_sequence' | 'generate_structure' | 'generate_paired', { compatible: boolean; reason: string | null }>
  effective_input: null | {
    functional_input_digest: string
    sequence: string
    secondary_structure: string | null
    sasa: Array<number | null> | null
    function_annotations: Array<{ label: string; start: number; end: number }>
    coordinates: { present: boolean; shape: number[] | null; dtype: 'float32'; unit: 'angstrom'; missing_atom_representation: 'NaN'; entries: Array<{ residue_id: string; position: number; atom_name: string; atom_index: number; coordinates: number[]; float32_bits: string[] }>; omitted_named_atoms: Array<{ residue_id: string; atom_name: string }> }
  }
}
export type PromptMergeTarget = Pick<PromptMergeSource, 'residues' | 'tracks' | 'function_annotations'> & { merge_index: number }
export type PromptSnapshot = { draft_revision: number; merge_targets: PromptMergeTarget[]; esm3_conditioning: ESM3ConditioningProjection | null; baseline_diagnostics: PromptDiagnostic[]; random_selections: PromptRandomSelection[]; document: PromptAuthoringDocument; residues: PromptResidue[]; tracks: Record<PromptTrackKey, PromptTrackProjection>; function_annotations: PromptFunctionAnnotation[]; source: JsonObject & { merge_sources?: PromptMergeSource[] } }
export type PromptPreview = Omit<PromptSnapshot, 'document' | 'source' | 'draft_revision'> & { normalized_document: PromptAuthoringDocument; changes: JsonObject[]; random_selections: PromptRandomSelection[]; source_merges: JsonObject[]; diagnostics: PromptDiagnostic[]; summary: JsonObject }
export type RunStatus = 'admitted' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'
export type RunScopeRequest = { mode: 'full' | 'to_node' | 'from_node'; node_ids: string[]; source_run_id?: string }
export type RunScope = { mode: RunScopeRequest['mode']; selected_node_ids: string[]; execution_node_ids: string[]; forced_node_ids: string[]; reused_node_ids: string[]; out_of_scope_node_ids: string[]; out_of_scope_selection_ids: string[]; source_run_id?: string }
export type RunScopePreview = { workflow_commit_id: string; scope: RunScope; blockers: Array<{ code: string; message: string; node_id?: string; field_path: Array<string | number> }>; nodes: Array<{ node_id: string; binding: ContractReference; method: ContractReference; node_parameters: JsonObject; binding_parameters: JsonObject; action: 'reuse' | 'execute'; randomness_status: 'resolved' | 'awaiting_inputs'; effective_randomness?: JsonObject }> }
export type RunReceipt = { project_id: string; run_id: string; workflow_commit_id: string; admitted_sequence: number; event_cursor: string }
type NodeDispositionBase = { node_id: string; terminal_sequence: number }
export type NodeDisposition =
  | NodeDispositionBase & { outcome: 'succeeded'; blocked_by: []; resolution: 'executed' | 'cache_replayed' }
  | NodeDispositionBase & { outcome: 'blocked'; blocked_by: string[] }
  | NodeDispositionBase & { outcome: 'failed' | 'cancelled' | 'interrupted'; blocked_by: [] }
type SelectionInput = { node_id: string; output_port: string; content_digest: string; result_identity: string }
export type RunProjection = { project_id: string; run_id: string; workflow_commit_id: string; status: RunStatus; scope: RunScope; ledger_cursor: string; node_dispositions: NodeDisposition[]; outputs: PublishedOutput[]; artifact_index: PublishedArtifact[]; selection_results?: Array<{ status: string; selection_node_id: string; candidate_input: SelectionInput; selected_candidate_ids: string[]; objectives: Array<JsonObject & { score_collection_input: SelectionInput }> }> }
export type RunDiagnostic = { code: string; message: string; retryable: boolean; correlation_id: string; details: JsonObject }
export type RunEvent =
  | { type: 'run_admitted'; workflow_commit_id: string }
  | { type: 'run_started'; started_at: string }
  | { type: 'node_attempt_started'; node_id: string; node_attempt_id: string }
  | { type: 'node_attempt_terminal'; node_attempt_id: string; status: string; error?: RunDiagnostic }
  | { type: 'node_disposition'; disposition: NodeDisposition }
  | { type: 'run_terminal'; status: Extract<RunStatus, 'succeeded' | 'failed' | 'cancelled' | 'interrupted'> }
  | { type: 'engine_invocation_started' | 'engine_invocation_terminal' | 'operation_attempt_started' | 'operation_attempt_terminal' | 'readiness_attested' | 'replay_complete' | 'replay_started' | 'selection_terminal' }
export type RunEventEnvelope = { schema_namespace: 'protein-workbench-public/v2'; project_id: string; run_id: string; sequence: number; cursor: string; emitted_at: string; event: RunEvent }

export type ProspectiveInput = { project_input_ref: string; filename: string; content_base64: string }
export class PublicV2Client {
  constructor(private readonly baseUrl = '') {}
  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: init?.body ? { 'Content-Type': 'application/json' } : undefined })
    if (!response.ok) throw await response.json()
    return response.json() as Promise<T>
  }
  moduleUi() { return this.json<ModuleUiManifest>('/api/v2/module-ui') }
  catalog() { return this.json<CatalogSnapshot>('/api/v2/catalog') }
  authoringCapabilities() { return this.json<AuthoringCapabilities>('/api/v2/authoring-capabilities') }
  projects(name?: string) { return this.json<{ projects: ProjectMetadata[] }>(`/api/v2/projects${name ? `?name=${encodeURIComponent(name)}` : ''}`) }
  createProject(name: string) { return this.json<ProjectMetadata>('/api/v2/projects', { method: 'POST', body: JSON.stringify({ name }) }) }
  listProjectInputs(projectId: string) { return this.json<{ project_id: string; inputs: ProjectInputPublication[] }>(`/api/v2/projects/${projectId}/inputs`) }
  publishProjectInput(projectId: string, input: { filename: string; content_base64: string }) { return this.json<ProjectInputPublication>(`/api/v2/projects/${projectId}/inputs`, { method: 'POST', body: JSON.stringify(input) }) }
  inspectProjectInput(projectId: string, inputRef: string, format: 'fasta' | 'pdb' | 'mmcif' | 'structure', input?: ProspectiveInput) { return this.json<ProjectInputInspection>(`/api/v2/projects/${projectId}/inputs/${inputRef}:inspect`, { method: 'POST', body: JSON.stringify({ format, ...(input ? { input } : {}) }) }) }
  copyExample(projectId: string, name: string, workspace?: { workflow: Workflow; ui_state: JsonObject; inputs: ProspectiveInput[] }) { return this.json<ProjectMetadata>(`/api/v2/projects/${projectId}:copy`, { method: 'POST', body: JSON.stringify({ name, ...workspace }) }) }
  deletedProjects() { return this.json<{ projects: ProjectMetadata[] }>('/api/v2/projects/deleted') }
  renameProject(projectId: string, name: string) { return this.json<ProjectMetadata>(`/api/v2/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify({ name }) }) }
  duplicateProject(projectId: string, name: string) { return this.json<ProjectMetadata>(`/api/v2/projects/${projectId}:duplicate`, { method: 'POST', body: JSON.stringify({ name }) }) }
  trashProject(projectId: string) { return this.json<ProjectMetadata>(`/api/v2/projects/${projectId}:trash`, { method: 'POST' }) }
  restoreProject(projectId: string) { return this.json<ProjectMetadata>(`/api/v2/projects/${projectId}:restore`, { method: 'POST' }) }
  deleteProject(projectId: string) { return this.json<{ project_id: string; deleted: true }>(`/api/v2/projects/${projectId}`, { method: 'DELETE' }) }
  projectWorkspace(projectId: string) { return this.json<ProjectWorkspace>(`/api/v2/projects/${projectId}/workspace`) }
  saveWorkspace(projectId: string, change: { workflow?: Workflow; ui_state?: JsonObject; expected_draft_revision?: number; expected_workspace_revision?: number }) { return this.json<ProjectWorkspace>(`/api/v2/projects/${projectId}/workspace`, { method: 'PUT', body: JSON.stringify(change) }) }
  workflowVersions(projectId: string) { return this.json<{ project_id: string; versions: WorkflowVersion[] }>(`/api/v2/projects/${projectId}/versions`) }
  nameWorkflowVersion(projectId: string, name: string) { return this.json<WorkflowVersion>(`/api/v2/projects/${projectId}/versions`, { method: 'POST', body: JSON.stringify({ name }) }) }
  workflowVersion(projectId: string, versionId: string) { return this.json<WorkflowVersionView>(`/api/v2/projects/${projectId}/versions/${versionId}`) }
  forkVersion(projectId: string, versionId: string, workflow: Workflow, uiState: JsonObject, returnWorkspaceRevision: number) { return this.json<ProjectWorkspace>(`/api/v2/projects/${projectId}/versions/${versionId}:fork`, { method: 'POST', body: JSON.stringify({ workflow, ui_state: uiState, return_workspace_revision: returnWorkspaceRevision }) }) }
  returnWorkspace(projectId: string, workspaceRevision: number) { return this.json<ProjectWorkspace>(`/api/v2/projects/${projectId}/workspace:return`, { method: 'POST', body: JSON.stringify({ workspace_revision: workspaceRevision }) }) }
  workflowCommit(projectId: string, commitId: string) { return this.json<WorkflowCommitSnapshot>(`/api/v2/projects/${projectId}/workflow/commits/${commitId}`) }
  compareWorkflowScience(projectId: string, commitId: string, workflowProjectId: string, workflow: Workflow) { return this.json<WorkflowScienceComparison>(`/api/v2/projects/${projectId}/workflow/commits/${commitId}:compare`, { method: 'POST', body: JSON.stringify({ workflow_project_id: workflowProjectId, workflow }) }) }
  workflowDraft(projectId: string) { return this.json<WorkflowDraft>(`/api/v2/projects/${projectId}/workflow/draft`) }
  openPrompt(projectId: string, nodeId: string, workflow?: Workflow, prospectiveInputs?: ProspectiveInput[]) { return this.json<PromptSnapshot>(`/api/v2/projects/${projectId}/prompt-authoring:open`, { method: 'POST', body: JSON.stringify({ node_id: nodeId, ...(workflow ? { workflow } : {}), ...(prospectiveInputs?.length ? { prospective_inputs: prospectiveInputs } : {}) }) }) }
  previewPrompt(projectId: string, nodeId: string, document: PromptAuthoringDocument, workflow?: Workflow, versionContext?: PromptVersionContext, prospectiveInputs?: ProspectiveInput[]) { return this.json<PromptPreview>(`/api/v2/projects/${projectId}/prompt-authoring:preview`, { method: 'POST', body: JSON.stringify({ node_id: nodeId, document, ...(workflow ? { workflow } : {}), ...(prospectiveInputs?.length ? { prospective_inputs: prospectiveInputs } : {}), ...(versionContext ? { version_context: versionContext } : {}) }) }) }
  observationOptions(workflow: Workflow, ranking: boolean) { return this.json<{ options: Array<{ source: { node_id: string; output_port: string }; partition: string; metric_id: string; method_id: string; context: JsonObject }> }>(`/api/v2/projects/${workflow.workflow_id}/workflow:observation-options`, { method: 'POST', body: JSON.stringify({ workflow: { nodes: workflow.nodes, edges: workflow.edges }, ranking }) }) }
  commitWorkflow(projectId: string, workflow: Workflow) { return this.json<{ workflow_commit_id: string }>(`/api/v2/projects/${projectId}/workflow:commit`, { method: 'POST', body: JSON.stringify({ workflow }) }) }
  previewRunScope(projectId: string, workflowCommitId: string, scope: RunScopeRequest) { return this.json<RunScopePreview>(`/api/v2/projects/${projectId}/runs/preview`, { method: 'POST', body: JSON.stringify({ workflow_commit_id: workflowCommitId, scope }) }) }
  startRun(projectId: string, workflowCommitId: string, scope: RunScopeRequest = { mode: 'full', node_ids: [] }) { return this.json<RunReceipt>(`/api/v2/projects/${projectId}/runs`, { method: 'POST', body: JSON.stringify({ workflow_commit_id: workflowCommitId, client_request_id: crypto.randomUUID(), scope }) }) }
  runProjection(projectId: string, runId: string) { return this.json<RunProjection>(`/api/v2/projects/${projectId}/runs/${runId}`) }
  cancelRun(projectId: string, runId: string) { return this.json<JsonObject>(`/api/v2/projects/${projectId}/runs/${runId}:cancel`, { method: 'POST' }) }
  resultCollection(projectId: string, runId: string, source: ResultLocation, offset = 0, limit = 100) { return this.json<ResultCollectionPage>(`/api/v2/projects/${projectId}/runs/${runId}/results:collection`, { method: 'POST', body: JSON.stringify({ ...source, offset, limit }) }) }
  resultAction<T>(projectId: string, runId: string, source: ResultLocation, actionId: string, parameters: JsonObject) { return this.json<T>(`/api/v2/projects/${projectId}/runs/${runId}/results:action`, { method: 'POST', body: JSON.stringify({ ...source, action_id: actionId, parameters }) }) }
  resultStructure(projectId: string, runId: string, source: ResultLocation, itemIndex: number) { return this.json<PublishedStructure>(`/api/v2/projects/${projectId}/runs/${runId}/results:structure`, { method: 'POST', body: JSON.stringify({ ...source, item_index: itemIndex }) }) }
  resultValue(projectId: string, runId: string, source: ResultLocation) { return this.json<PublishedResultValue>(`/api/v2/projects/${projectId}/runs/${runId}/results:value`, { method: 'POST', body: JSON.stringify(source) }) }
  typedValue(projectId: string, runId: string, nodeId: string, outputPort: string, index = 0) { return this.json<CanonicalTypedValue>(`/api/v2/projects/${projectId}/runs/${runId}/outputs/${nodeId}/${outputPort}/values/${index}`) }
  artifactUrl(projectId: string, runId: string, artifactReference: string) { return `${this.baseUrl}/api/v2/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactReference)}` }
  runEvents(projectId: string, runId: string, afterCursor?: string) {
    const url = new URL(`${this.baseUrl}/api/v2/projects/${projectId}/runs/${runId}/events`, globalThis.location?.href)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    if (afterCursor) url.searchParams.set('after_sequence', afterCursor)
    return new WebSocket(url)
  }
}
