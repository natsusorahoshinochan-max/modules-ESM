import type { CatalogSnapshot, PromptSnapshot, PublicV2Client, Workflow, WorkflowNode } from './protocol/client'
import type { ParameterChoices } from './WorkflowParameters'
import { nodeTypePresentation, parameterPresentations, type ParameterValueContract } from './workflow-authoring'
import type { PublishedResults } from './published-results'
import { workspaceErrorMessage } from './project-workspace'
import type { StructureInputInspection } from './input-sources'

export type NodeParameterChoices = { choices: ParameterChoices; source?: string; notice?: string }
export type WorkflowParameterChoices = Record<string, NodeParameterChoices>
type ChoicesClient = Pick<PublicV2Client, 'listProjectInputs' | 'inspectProjectInput' | 'openPrompt' | 'compareWorkflowScience'>
const residueFields = new Set(['residue_id', 'residue_ids', 'designable_residue_ids', 'fixed_residue_ids', 'tied_residue_groups'])
const chainFields = new Set(['chain_ids', 'designed_chains', 'fixed_chains'])
const axisType = 'structure_transform.resolved_residue_axis'

function needsLayout(field: string, contract: ParameterValueContract): boolean {
  return residueFields.has(field) || chainFields.has(field) || Object.entries(contract.properties ?? {}).some(([key, value]) => needsLayout(key, value)) || Boolean(contract.items && needsLayout(field, contract.items))
}

function snapshotChoices(snapshot: PromptSnapshot): ParameterChoices {
  const residues = snapshot.residues.filter(residue => residue.state !== 'pending-delete')
  return {
    chains: [...new Set(residues.map(residue => residue.chain_id))].map(value => ({ value, label: `Chain ${value}` })),
    residues: residues.map(residue => ({ value: residue.residue_id, label: residue.residue_id })),
  }
}

/** A read-only prospective author asks the scientific owner for the exact connected axis. */
function sourcePreview(workflow: Workflow, source: WorkflowNode, outputPort: string, portType: string) {
  let serial = 1
  while (workflow.nodes.some(node => [ `parameter-source-preview-${serial}`, `parameter-source-preview-${serial}-axis` ].includes(node.node_id))) serial += 1
  const nodeId = `parameter-source-preview-${serial}`
  let staged = workflow
  let sourceNodeId = source.node_id
  if (portType === 'protein.structure') {
    const axisId = `${nodeId}-axis`
    staged = { ...staged, nodes: [...staged.nodes, { node_id: axisId, node_type_id: 'structure_transform.resolve_residue_axis', binding_id: 'structure_transform.resolve_residue_axis.direct', node_parameters: {}, binding_parameters: {} }], edges: [...staged.edges, { source_node_id: sourceNodeId, source_port: outputPort, target_node_id: axisId, target_port: 'structure' }] }
    sourceNodeId = axisId
    outputPort = 'residue_axis'
  }
  return { nodeId, workflow: {
    ...staged,
    nodes: [...staged.nodes, { node_id: nodeId, node_type_id: 'prompt_authoring.author', binding_id: 'prompt_authoring.author.direct', node_parameters: { document: {} }, binding_parameters: {} }],
    edges: [...staged.edges, { source_node_id: sourceNodeId, source_port: outputPort, target_node_id: nodeId, target_port: portType === 'protein.prompt' ? 'prompt_source' : 'structure_source' }],
  } }
}

/** Choices are suggestions from exact source facts; existing parameter values are never rewritten. */
export async function loadWorkflowParameterChoices(client: ChoicesClient, projectId: string, workflow: Workflow, catalog: CatalogSnapshot, results?: PublishedResults): Promise<WorkflowParameterChoices> {
  const reading = results?.captureReading()
  const publishedRun = reading?.run
  const { inputs } = await client.listProjectInputs(projectId)
  const inputChoices = inputs.map(input => ({ value: input.project_input_ref, label: `${input.filename} · ${input.project_input_ref}` }))
  const sourceLoads = new Map<string, Promise<NodeParameterChoices>>()
  let comparison: ReturnType<ChoicesClient['compareWorkflowScience']> | undefined
  const loadSource = (source: WorkflowNode, outputPort: string, portType: string) => {
    const key = JSON.stringify([source.node_id, outputPort])
    let pending = sourceLoads.get(key)
    if (pending) return pending
    pending = (async (): Promise<NodeParameterChoices> => {
      const sourceLabel = `${source.node_id} / ${outputPort}`
      if (portType === 'protein.structure' && source.node_type_id === 'protein_io.import_structure') {
        const inspection = await client.inspectProjectInput(projectId, source.node_parameters.project_input_ref as string, 'structure') as StructureInputInspection
        return { choices: { chains: inspection.chain_ids.map(value => ({ value, label: `Chain ${value}` })) }, source: `${sourceLabel} · 后端 Input 链检查` }
      }
      const output = publishedRun?.outputs.find(item => item.node_id === source.node_id && item.output_port === outputPort && item.port_type.contract_id === axisType && item.value_count === 1)
      if (output) {
        comparison ??= client.compareWorkflowScience(publishedRun!.project_id, publishedRun!.workflow_commit_id, projectId, workflow)
        if ((await comparison).status !== 'current') return { choices: {}, notice: `${sourceLabel} 的已发布残基轴尚未确认与当前流程一致；请先执行当前来源。` }
        const payload = await reading!.value({ node_id: source.node_id, output_port: outputPort, value_index: 0 })
        if (!payload) return { choices: {} }
        if (payload.kind !== 'axis_layout') throw new Error('已发布来源不是残基轴布局')
        const axis = payload.value
        return { choices: {
          chains: [...new Set(axis.chain_ids)].map(value => ({ value, label: `Chain ${value}` })),
          residues: axis.residue_ids.map(value => ({ value, label: value })),
        }, source: `${sourceLabel} · Run ${publishedRun!.run_id}` }
      }
      const canPreview = portType === 'protein.prompt' || portType === 'protein.structure' || source.node_type_id === 'structure_transform.resolve_residue_axis'
      if (canPreview) {
        const preview = sourcePreview(workflow, source, outputPort, portType)
        const snapshot = await client.openPrompt(projectId, preview.nodeId, preview.workflow)
        const choices = snapshotChoices(snapshot)
        return { choices, source: `${sourceLabel} · 当前来源投影`, ...(snapshot.baseline_diagnostics.length ? { notice: snapshot.baseline_diagnostics.map(item => item.message).join('；') } : {}) }
      }
      return { choices: {}, notice: `${sourceLabel} 尚无可用的当前残基轴证据；请先执行来源并取得与当前流程一致的结果。` }
    })()
    sourceLoads.set(key, pending)
    return pending
  }
  const entries = await Promise.all(workflow.nodes.map(async (node): Promise<[string, NodeParameterChoices]> => {
    const parameters = parameterPresentations(catalog, node)
    const choices: ParameterChoices = Object.fromEntries(parameters.filter(parameter => parameter.resourceKind === 'project_input').map(parameter => [parameter.key, inputChoices]))
    if (!parameters.some(parameter => needsLayout(parameter.key, parameter.contract))) return [node.node_id, { choices, ...(Object.keys(choices).length && !inputs.length ? { notice: '项目暂无 Input；可通过“添加来源”上传或粘贴输入。' } : {}) }]
    const inputPorts = nodeTypePresentation(catalog, node.node_type_id).inputs
    const edges = workflow.edges.filter(edge => edge.target_node_id === node.node_id && [axisType, 'protein.prompt', 'protein.structure'].includes(inputPorts.find(port => port.name === edge.target_port)!.portTypeId!))
    if (edges.length !== 1) return [node.node_id, { choices, notice: edges.length ? '存在多个布局来源；尚无唯一的参数选项依据。' : '尚未连接可读取的结构、Prompt 或残基轴来源；已有参数值仍保留。' }]
    const edge = edges[0]
    try {
      const source = await loadSource(workflow.nodes.find(item => item.node_id === edge.source_node_id)!, edge.source_port, inputPorts.find(port => port.name === edge.target_port)!.portTypeId!)
      return [node.node_id, { ...source, choices: { ...choices, ...source.choices } }]
    } catch (reason) {
      return [node.node_id, { choices, notice: `来源 ${edge.source_node_id} / ${edge.source_port} 无法提供选项：${workspaceErrorMessage(reason)}` }]
    }
  }))
  return Object.fromEntries(entries)
}
