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
  availabilityReason?: { code: string; message: string; retryable: boolean }
}

export type PortPresentation = {
  label?: string
  name: string
  meaning: string
} & ({
  missing: true
  portTypeId?: never
  multiplicity?: never
  required?: never
} | {
  missing?: false
  portTypeId: string
  multiplicity: 'one' | 'many'
  required: boolean
})

export type NodeTypePresentation = {
  missing?: boolean
  title: string
  category: string
  inputs: PortPresentation[]
  outputs: PortPresentation[]
}

export type ParameterValueContract = {
  type?: string | string[]
  title?: string
  scientific_meaning?: string
  enum?: unknown[]
  const?: unknown
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  multipleOf?: number
  minLength?: number
  maxLength?: number
  minItems?: number
  maxItems?: number
  uniqueItems?: boolean
  pattern?: string
  items?: ParameterValueContract
  properties?: Record<string, ParameterValueContract>
  required?: string[]
  default?: unknown
}

export type ParameterPresentation = {
  undeclared?: boolean
  key: string
  label: string
  value: string
  scope: 'node' | 'binding'
  valueType: string
  required: boolean
  groupId: string
  groupTitle: string
  description: string
  unit?: string
  resourceKind?: string
  contract: ParameterValueContract
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
  const availability = new Map(catalog.availability.map((item) => [(item.binding as JsonObject).contract_id, item]))
  return catalog.contracts.flatMap((contract): BindingOption[] => {
    if (contract.reference.contract_kind !== 'binding' || descriptorReference(contract.descriptor, 'node_type') !== nodeTypeId) return []
    const methodId = descriptorReference(contract.descriptor, 'method')
    if (!methodId) return []
    const observation = availability.get(contract.reference.contract_id)!
    return [{ id: contract.reference.contract_id, label: methodLabel(methods.get(methodId) ?? {}, methodId), available: observation.available as boolean, availabilityReason: observation.reason as BindingOption['availabilityReason'] }]
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

function parameterPresentationsForScope(parameters: JsonObject | undefined, values: Record<string, unknown>, scope: 'node' | 'binding', groups: Array<{ id: string; title: string; parameters: string[] }> = []): ParameterPresentation[] {
  const nodeLabels: Record<string, string> = { effective_seed: '有效种子', num_samples: '生成数量', k: '保留数量', num_sequences: '每个父结构', temperature: '温度', backbone_noise: '骨架噪声' }
  const declared = Object.entries(parameters ?? {}).map(([key, value]): ParameterPresentation => {
    const descriptor = value as JsonObject
    const valueContract = descriptor.value_contract as ParameterValueContract
    const group = groups.find((item) => item.parameters.includes(key))
    return {
      key,
      label: scope === 'binding' ? `模型参数 · ${key}` : nodeLabels[key] ?? key,
      value: displayParameterValue(values[key]),
      scope,
      valueType: Array.isArray(valueContract.type) ? 'json' : valueContract.type ?? 'string',
      required: descriptor.required === true,
      groupId: `${scope}:${group?.id ?? 'parameters'}`,
      groupTitle: group?.title ?? (scope === 'binding' ? '模型专属参数' : '科学参数'),
      description: descriptor.scientific_meaning as string,
      unit: descriptor.unit as string | undefined,
      resourceKind: descriptor.resource_kind as string | undefined,
      contract: valueContract,
    }
  })
  return [...declared, ...Object.entries(values).filter(([key]) => !Object.hasOwn(parameters ?? {}, key)).map(([key, value]): ParameterPresentation => ({
    key,
    label: `${scope === 'node' ? '节点' : '模型'}参数 · ${key}`,
    value: JSON.stringify(value),
    scope,
    undeclared: true,
    valueType: 'json',
    required: false,
    groupId: `${scope}:undeclared`,
    groupTitle: '已保存但当前未声明的参数',
    description: '当前模块未声明此参数，原值仍保留。可在确认不再需要后主动移除；移除后须手动保存项目。',
    contract: {},
  }))]
}

export function parameterPresentations(catalog: CatalogSnapshot, node: WorkflowNode): ParameterPresentation[] {
  const nodeType = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === node.node_type_id)
  const binding = catalog.contracts.find((contract) => contract.reference.contract_kind === 'binding' && contract.reference.contract_id === node.binding_id)
  if (!nodeType || !binding) return []
  return [
    ...parameterPresentationsForScope(nodeType.descriptor.node_parameters as JsonObject | undefined, node.node_parameters, 'node', nodeType.descriptor.parameter_groups as Array<{ id: string; title: string; parameters: string[] }>),
    ...parameterPresentationsForScope(binding.descriptor.binding_parameters as JsonObject | undefined, node.binding_parameters, 'binding'),
  ]
}

export function missingNodeContracts(catalog: CatalogSnapshot, node: WorkflowNode): string[] {
  return ([['node_type', node.node_type_id], ['binding', node.binding_id]] as const)
    .filter(([kind, id]) => !catalog.contracts.some(contract => contract.reference.contract_kind === kind && contract.reference.contract_id === id))
    .map(([, id]) => id)
}

/** A saved endpoint locates a wire; its scientific contract is unavailable. */
export function missingPortPresentation(name: string): PortPresentation {
  return { name, missing: true, meaning: '模块缺失，保留已保存的端口和连线；启用兼容模块后恢复。' }
}

export function nodeTypePresentation(catalog: CatalogSnapshot, nodeTypeId: string): NodeTypePresentation {
  const descriptor = catalog.contracts.find((contract) => contract.reference.contract_kind === 'node_type' && contract.reference.contract_id === nodeTypeId)?.descriptor
  if (!descriptor) return { missing: true, title: nodeTypeId, category: '缺失模块', inputs: [], outputs: [] }
  const ports = (field: 'inputs' | 'outputs'): PortPresentation[] => ((descriptor[field] as JsonObject[] | undefined) ?? []).map((port) => ({
    name: String(port.name),
    portTypeId: String((port.port_type as JsonObject).contract_id),
    multiplicity: port.multiplicity as 'one' | 'many',
    required: port.required as boolean,
    meaning: String(port.scientific_meaning),
  }))
  const inputs = ports('inputs')
  const outputs = ports('outputs')
  return {
    title: String(descriptor.title),
    category: String(descriptor.category),
    inputs,
    outputs,
  }
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
      node_parameters: nodeTypeId === 'prompt_authoring.author' ? { document: {} } : parameterDefaults(nodeType.descriptor.node_parameters as JsonObject | undefined),
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
  const terms = query.trim().toLowerCase().split(/\s+/)
  const entries = paletteEntries(catalog, capabilities).filter((entry) => terms.every((term) => `${entry.title} ${entry.id} ${entry.purpose} ${entry.providerGroups.join(' ')}`.toLowerCase().includes(term)))
  const groups = new Map<string, PaletteEntry[]>()
  for (const entry of entries) {
    const labels = taxonomy === 'purpose' ? [entry.purpose] : entry.providerGroups
    for (const label of labels) groups.set(label, [...(groups.get(label) ?? []), entry])
  }
  return [...groups].sort(([left], [right]) => left.localeCompare(right)).map(([label, groupEntries]) => ({ label, entries: groupEntries }))
}
