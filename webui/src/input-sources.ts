import type { CatalogSnapshot, PromptAuthoringDocument, PromptChainDeclaration, Workflow } from './protocol/client'
import { connectWorkflowPorts } from './workflow-connections'
import { insertOrdinaryNode, nodeTypePresentation } from './workflow-authoring'

export type ProjectInputPublication = {
  schema_namespace: 'protein-workbench-public/v2'
  project_id: string
  project_input_ref: string
  filename: string
  size: number
  content_digest: string
}

type InputInspectionIdentity = { project_id: string; project_input_ref: string; content_digest: string }
export type FastaInputInspection = InputInspectionIdentity & {
  format: 'fasta'
  records: Array<{ record_index: number; header: string; display_name: string; line_number: number; length: number }>
  total_length: number
}
export type StructureInputInspection = InputInspectionIdentity & { format: 'pdb' | 'mmcif'; chain_ids: string[] }
export type ProjectInputInspection = FastaInputInspection | StructureInputInspection
export type InputSourceClient = {
  listProjectInputs: (projectId: string) => Promise<{ project_id: string; inputs: ProjectInputPublication[] }>
  publishProjectInput: (projectId: string, input: { filename: string; content_base64: string }, format: 'fasta' | 'pdb' | 'mmcif') => Promise<ProjectInputPublication>
  inspectProjectInput: (projectId: string, inputRef: string, format: 'fasta' | 'pdb' | 'mmcif' | 'structure') => Promise<ProjectInputInspection>
}

export type PromptSourceChoice =
  | { kind: 'blank'; chains: PromptChainDeclaration[] }
  | { kind: 'fasta'; projectInputRef: string; chains: PromptChainDeclaration[] }
  | { kind: 'structure'; projectInputRef: string; chainIds: string[] }
  | { kind: 'prompt'; nodeId: string; outputPort: string }

export type PromptSourcePlan = { workflow: Workflow; nodeId: string; document: PromptAuthoringDocument; addedNodeIds: string[] }
export type CandidateInputPlan = { workflow: Workflow; nodeId: string; addedNodeIds: string[] }
export type ExistingPromptSource = { nodeId: string; outputPort: string; title: string }

/** The canvas owns scientific nodes and connections; this builder stages them without saving. */
export function preparePromptSource(workflow: Workflow, catalog: CatalogSnapshot, source: PromptSourceChoice, mergeTargetNodeId?: string): PromptSourcePlan {
  let staged = workflow
  const addedNodeIds: string[] = []
  const add = (nodeTypeId: string, prefix: string, parameters: Record<string, unknown>) => {
    const nodeId = nextNodeId(staged, prefix)
    staged = insertOrdinaryNode(staged, nodeId, nodeTypeId, `${nodeTypeId}.direct`, catalog)
    staged = { ...staged, nodes: staged.nodes.map(node => node.node_id === nodeId ? { ...node, node_parameters: { ...node.node_parameters, ...parameters } } : node) }
    addedNodeIds.push(nodeId)
    return nodeId
  }
  const connect = (sourceNodeId: string, sourcePort: string, targetNodeId: string, targetPort: string) => {
    staged = connectWorkflowPorts(staged, catalog, { nodeId: sourceNodeId, portName: sourcePort, direction: 'output' }, { nodeId: targetNodeId, portName: targetPort, direction: 'input' })
  }

  let upstream: { nodeId: string; outputPort: string; targetPort: string } | undefined
  const document: PromptAuthoringDocument = source.kind === 'blank' || source.kind === 'fasta' ? { chains: source.chains.map(chain => ({ ...chain })) } : {}
  if (source.kind === 'fasta') {
    const nodeId = add('protein_io.import_sequence', 'source-fasta', { project_input_ref: source.projectInputRef })
    upstream = { nodeId, outputPort: 'sequence', targetPort: 'sequence_source' }
  } else if (source.kind === 'structure') {
    const imported = add('protein_io.import_structure', 'source-structure', { project_input_ref: source.projectInputRef })
    const selected = add('structure_transform.select_chains', 'source-chains', { chain_ids: [...source.chainIds] })
    const resolved = add('structure_transform.resolve_residue_axis', 'source-axis', {})
    connect(imported, 'structure', selected, 'structure')
    connect(selected, 'structure', resolved, 'structure')
    upstream = { nodeId: resolved, outputPort: 'residue_axis', targetPort: 'structure_source' }
  } else if (source.kind === 'prompt') {
    upstream = { nodeId: source.nodeId, outputPort: source.outputPort, targetPort: 'prompt_source' }
  }

  if (source.kind === 'prompt' && mergeTargetNodeId) {
    connect(source.nodeId, source.outputPort, mergeTargetNodeId, 'merge_sources')
  } else {
    const author = add('prompt_authoring.author', 'source-prompt', { document })
    if (upstream) connect(upstream.nodeId, upstream.outputPort, author, upstream.targetPort)
    if (mergeTargetNodeId) connect(author, 'protein_prompt', mergeTargetNodeId, 'merge_sources')
    else return { workflow: staged, nodeId: author, document, addedNodeIds }
  }
  const target = staged.nodes.find(node => node.node_id === mergeTargetNodeId)!
  return { workflow: staged, nodeId: target.node_id, document: target.node_parameters.document as PromptAuthoringDocument, addedNodeIds }
}

export function prepareCandidateInput(workflow: Workflow, catalog: CatalogSnapshot, projectInputRef: string): CandidateInputPlan {
  const nodeId = nextNodeId(workflow, 'source-records')
  const staged = insertOrdinaryNode(workflow, nodeId, 'protein_io.import_sequences', 'protein_io.import_sequences.direct', catalog)
  return {
    workflow: { ...staged, nodes: staged.nodes.map(node => node.node_id === nodeId ? { ...node, node_parameters: { project_input_ref: projectInputRef } } : node) },
    nodeId,
    addedNodeIds: [nodeId],
  }
}

export function existingPromptSources(workflow: Workflow, catalog: CatalogSnapshot, mergeTargetNodeId?: string): ExistingPromptSource[] {
  const excluded = new Set(mergeTargetNodeId ? [mergeTargetNodeId] : [])
  const pending = [...excluded]
  while (pending.length) {
    const current = pending.pop()!
    for (const edge of workflow.edges) {
      if (edge.source_node_id === current && !excluded.has(edge.target_node_id)) {
        excluded.add(edge.target_node_id)
        pending.push(edge.target_node_id)
      }
    }
  }
  return workflow.nodes.filter(node => !excluded.has(node.node_id)).flatMap(node => {
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    return presentation.outputs.filter(port => port.portTypeId === 'protein.prompt').filter(port => !workflow.edges.some(edge => edge.source_node_id === node.node_id && edge.source_port === port.name && edge.target_node_id === mergeTargetNodeId && edge.target_port === 'merge_sources')).map(port => ({ nodeId: node.node_id, outputPort: port.name, title: presentation.title }))
  })
}

function nextNodeId(workflow: Workflow, prefix: string) {
  const ids = new Set(workflow.nodes.map(node => node.node_id))
  let index = 1
  while (ids.has(`${prefix}-${index}`)) index += 1
  return `${prefix}-${index}`
}

export function inputContentBase64(content: Uint8Array): string {
  const chunks: string[] = []
  for (let index = 0; index < content.length; index += 8192) chunks.push(String.fromCharCode(...content.subarray(index, index + 8192)))
  return btoa(chunks.join(''))
}
