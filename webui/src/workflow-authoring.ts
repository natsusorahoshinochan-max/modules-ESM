import type { AuthoringCapabilities, CatalogSnapshot, JsonObject, Workflow, WorkflowNode } from './protocol/client'

export type PaletteTaxonomy = 'purpose' | 'provider'

export type PaletteEntry = {
  id: string
  title: string
  purpose: string
  providerGroups: string[]
}

export type PaletteGroup = {
  label: string
  entries: PaletteEntry[]
}

export type BindingOption = {
  id: string
  label: string
  available: boolean
}

export type NodeTypePresentation = {
  title: string
  category: string
  inputs: string[]
  outputs: string[]
}

export type ParameterPresentation = {
  key: string
  label: string
  value: string
  scope: 'node' | 'binding'
  valueType: string
  required: boolean
}

type Contract = CatalogSnapshot['contracts'][number]

function descriptorReference(descriptor: JsonObject, field: string): string | undefined {
  const reference = descriptor[field] as JsonObject | undefined
  return typeof reference?.contract_id === 'string' ? reference.contract_id : undefined
}

function methodPackage(descriptor: JsonObject, methodId: string): string {
  const modelIdentity = descriptor.model_identity as JsonObject | undefined
  for (const key of ['source', 'provider', 'architecture', 'folding_model', 'model', 'confidence_latent_model']) {
    if (typeof modelIdentity?.[key] === 'string') return modelIdentity[key]
  }
  const algorithmIdentity = descriptor.algorithm_identity as JsonObject | undefined
  const binary = algorithmIdentity?.binary as JsonObject | undefined
  if (typeof binary?.name === 'string') return binary.name
  return methodId.split('.')[0]
}

function methodLabel(descriptor: JsonObject, methodId: string): string {
  const modelIdentity = descriptor.model_identity as JsonObject | undefined
  for (const key of ['model', 'folding_model', 'confidence_latent_model']) {
    if (typeof modelIdentity?.[key] === 'string') return modelIdentity[key]
  }
  const algorithmIdentity = descriptor.algorithm_identity as JsonObject | undefined
  return typeof algorithmIdentity?.name === 'string' ? algorithmIdentity.name : methodId
}

export function bindingOptions(catalog: CatalogSnapshot, nodeTypeId: string): BindingOption[] {
  const methods = new Map(catalog.contracts.filter((contract) => contract.reference.contract_kind === 'method').map((contract) => [contract.reference.contract_id, contract.descriptor]))
  const availability = new Map(catalog.availability.flatMap((item): Array<[string, boolean]> => {
    const binding = item.binding as JsonObject | undefined
    return typeof binding?.contract_id === 'string' && typeof item.available === 'boolean' ? [[binding.contract_id, item.available]] : []
  }))
  return catalog.contracts.flatMap((contract): BindingOption[] => {
    if (contract.reference.contract_kind !== 'binding' || descriptorReference(contract.descriptor, 'node_type') !== nodeTypeId) return []
    const methodId = descriptorReference(contract.descriptor, 'method')
    if (!methodId) return []
    return [{ id: contract.reference.contract_id, label: methodLabel(methods.get(methodId) ?? {}, methodId), available: availability.get(contract.reference.contract_id) ?? false }]
  })
}

function parameterDefaults(parameters: JsonObject | undefined): Record<string, unknown> {
  return Object.fromEntries(Object.entries(parameters ?? {}).flatMap(([key, value]) => {
    const descriptor = value as JsonObject
    return Object.hasOwn(descriptor, 'default') ? [[key, descriptor.default]] : []
  }))
}

function displayParameterValue(value: unknown): string {
  if (value === undefined) return ''
  return value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function parameterPresentationsForScope(parameters: JsonObject | undefined, values: Record<string, unknown>, scope: 'node' | 'binding'): ParameterPresentation[] {
  const nodeLabels: Record<string, string> = { effective_seed: '有效种子', num_samples: '生成数量', k: '保留数量', num_sequences: '每个父结构', temperature: '温度', backbone_noise: '骨架噪声' }
  return Object.entries(parameters ?? {}).map(([key, value]) => {
    const descriptor = value as JsonObject
    const valueContract = descriptor.value_contract as JsonObject | undefined
    return {
      key,
      label: scope === 'binding' ? `模型参数 · ${key}` : nodeLabels[key] ?? key,
      value: displayParameterValue(values[key]),
      scope,
      valueType: typeof valueContract?.type === 'string' ? valueContract.type : 'string',
      required: descriptor.required === true,
    }
  })
}

export function parameterPresentations(catalog: CatalogSnapshot, node: WorkflowNode): ParameterPresentation[] {
  const nodeType = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === node.node_type_id)
  const binding = catalog.contracts.find((contract) => contract.reference.contract_kind === 'binding' && contract.reference.contract_id === node.binding_id)
  if (!nodeType) throw new Error(`Node Type ${node.node_type_id} is absent from the active Catalog`)
  if (!binding) throw new Error(`Binding ${node.binding_id} is absent from the active Catalog`)
  return [
    ...parameterPresentationsForScope(nodeType.descriptor.node_parameters as JsonObject | undefined, node.node_parameters, 'node'),
    ...parameterPresentationsForScope(binding.descriptor.binding_parameters as JsonObject | undefined, node.binding_parameters, 'binding'),
  ]
}

export function nodeTypePresentation(catalog: CatalogSnapshot, nodeTypeId: string): NodeTypePresentation {
  const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === nodeTypeId)?.descriptor
  if (!descriptor) throw new Error(`Node Type ${nodeTypeId} is absent from the active Catalog`)
  const portNames = (field: 'inputs' | 'outputs') => ((descriptor[field] as JsonObject[] | undefined) ?? []).map((port) => String(port.name))
  return { title: String(descriptor.title), category: String(descriptor.category), inputs: portNames('inputs'), outputs: portNames('outputs') }
}

export function insertOrdinaryNode(workflow: Workflow, nodeId: string, nodeTypeId: string, bindingId: string, catalog: CatalogSnapshot): Workflow {
  const nodeType = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === nodeTypeId)
  const binding = catalog.contracts.find((contract) => contract.reference.contract_kind === 'binding' && contract.reference.contract_id === bindingId)
  if (!nodeType) throw new Error(`Node Type ${nodeTypeId} is absent from the active Catalog`)
  if (!binding || descriptorReference(binding.descriptor, 'node_type') !== nodeTypeId) throw new Error(`Binding ${bindingId} does not execute Node Type ${nodeTypeId}`)
  return {
    ...workflow,
    nodes: [...workflow.nodes, {
      node_id: nodeId,
      node_type_id: nodeTypeId,
      binding_id: bindingId,
      node_parameters: parameterDefaults(nodeType.descriptor.node_parameters as JsonObject | undefined),
      binding_parameters: parameterDefaults(binding.descriptor.binding_parameters as JsonObject | undefined),
    }],
  }
}

export function selectNodeBinding(workflow: Workflow, nodeId: string, bindingId: string, catalog: CatalogSnapshot, rememberedParameters?: Record<string, unknown>): Workflow {
  const binding = catalog.contracts.find((contract) => contract.reference.contract_kind === 'binding' && contract.reference.contract_id === bindingId)
  if (!binding) throw new Error(`Binding ${bindingId} is absent from the active Catalog`)
  const node = workflow.nodes.find((item) => item.node_id === nodeId)
  if (!node || descriptorReference(binding.descriptor, 'node_type') !== node.node_type_id) throw new Error(`Binding ${bindingId} does not execute Node ${nodeId}`)
  return {
    ...workflow,
    nodes: workflow.nodes.map((item) => item.node_id === nodeId ? { ...item, binding_id: bindingId, binding_parameters: rememberedParameters ?? parameterDefaults(binding.descriptor.binding_parameters as JsonObject | undefined) } : item),
  }
}

function paletteEntries(catalog: CatalogSnapshot, capabilities: AuthoringCapabilities): PaletteEntry[] {
  const ordinaryNodeTypes = new Set(capabilities.node_roles.filter((item) => item.role === 'ordinary_node').map((item) => item.node_type.contract_id))
  const methods = new Map(catalog.contracts.filter((contract) => contract.reference.contract_kind === 'method').map((contract) => [contract.reference.contract_id, contract.descriptor]))
  const bindingsByNodeType = new Map<string, Contract[]>()
  for (const contract of catalog.contracts) {
    if (contract.reference.contract_kind !== 'binding') continue
    const nodeTypeId = descriptorReference(contract.descriptor, 'node_type')
    if (!nodeTypeId) continue
    bindingsByNodeType.set(nodeTypeId, [...(bindingsByNodeType.get(nodeTypeId) ?? []), contract])
  }
  return catalog.contracts.flatMap((contract): PaletteEntry[] => {
    if (contract.reference.contract_kind !== 'node_type' || !ordinaryNodeTypes.has(contract.reference.contract_id)) return []
    const providerGroups = new Set<string>()
    for (const binding of bindingsByNodeType.get(contract.reference.contract_id) ?? []) {
      const methodId = descriptorReference(binding.descriptor, 'method')
      if (methodId) providerGroups.add(methodPackage(methods.get(methodId) ?? {}, methodId))
    }
    return [{
      id: contract.reference.contract_id,
      title: String(contract.descriptor.title),
      purpose: String(contract.descriptor.category),
      providerGroups: [...providerGroups].sort(),
    }]
  })
}

export function projectPalette(catalog: CatalogSnapshot, capabilities: AuthoringCapabilities, taxonomy: PaletteTaxonomy, query: string): PaletteGroup[] {
  const normalizedQuery = query.toLowerCase()
  const entries = paletteEntries(catalog, capabilities).filter((entry) => `${entry.title}${entry.id}`.toLowerCase().includes(normalizedQuery))
  const groups = new Map<string, PaletteEntry[]>()
  for (const entry of entries) {
    const labels = taxonomy === 'purpose' ? [entry.purpose] : entry.providerGroups
    for (const label of labels) groups.set(label, [...(groups.get(label) ?? []), entry])
  }
  return [...groups].sort(([left], [right]) => left.localeCompare(right)).map(([label, groupEntries]) => ({ label, entries: groupEntries }))
}
