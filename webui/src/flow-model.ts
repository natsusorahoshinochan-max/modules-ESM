import { i18n } from './i18n'
const messages = {
  "for_each_package": {
    "zh-CN": "逐项处理",
    "en": "For each package"
  },
  "repeat_subflow": {
    "zh-CN": "循环",
    "en": "Repeat subflow"
  },
  "subflow_changed_return_to_its_parent": {
    "zh-CN": "子流程已改变，请返回上一级",
    "en": "Subflow changed; return to its parent"
  }
};
const t = i18n.translator(messages)
import type { Flow, FlowNode } from '@protein-workbench/module-ui'
import type { Catalog, NodeDeclaration, Run } from './host-client'

export function declarationFor(node: FlowNode | undefined, catalog: Catalog): NodeDeclaration | undefined {
  if (!node) return undefined
  if ((node.type === 'host.map' || node.type === 'host.repeat') && node.scope) return {
    id: node.type, module_id: 'host', name: node.type === 'host.map' ? t("for_each_package") : t("repeat_subflow"),
    inputs: node.scope.inputs, outputs: node.scope.outputs, parameters: {},
  }
  return catalog.nodes.find(item => item.id === node.type)
}

export function flowAt(root: Flow, path: readonly string[]): Flow | undefined {
  let current = root
  for (const id of path) {
    const next = current.nodes.find(node => node.id === id)?.scope?.body
    if (!next) return undefined
    current = next
  }
  return current
}

export function replaceFlow(root: Flow, path: readonly string[], update: (flow: Flow) => Flow): Flow {
  if (!path.length) return update(root)
  const [id, ...tail] = path
  if (!root.nodes.some(node => node.id === id && node.scope)) throw new Error(t("subflow_changed_return_to_its_parent"))
  return { ...root, nodes: root.nodes.map(node => node.id === id && node.scope ? { ...node, scope: { ...node.scope, body: replaceFlow(node.scope.body, tail, update) } } : node) }
}

/** Copying a scope creates new graph identities and keeps its explicit connections. */
export function copyNode(node: FlowNode): Omit<FlowNode, 'id'> {
  const copied = structuredClone(node)
  function rewrite(current: FlowNode) {
    if (!current.scope) return
    const ids = new Map(current.scope.body.nodes.map(child => [child.id, crypto.randomUUID()]))
    current.scope.body.nodes.forEach(child => { child.id = ids.get(child.id)!; rewrite(child) })
    current.scope.body.edges = current.scope.body.edges.map(edge => ({ ...edge, source: ids.get(edge.source)!, target: ids.get(edge.target)! }))
    current.scope.input_bindings = current.scope.input_bindings.map(binding => ({ ...binding, node: ids.get(binding.node)! }))
    current.scope.output_bindings = current.scope.output_bindings.map(binding => ({ ...binding, node: ids.get(binding.node)! }))
  }
  rewrite(copied)
  return copied
}

export function callLabel(run: Run, id: string): string {
  const labels: string[] = []
  const visited = new Set<string>()
  let current: string | undefined = id
  while (current && !visited.has(current)) {
    visited.add(current)
    const location: Run['nodes'][string]['location'] = run.nodes[current]?.location
    labels.unshift(location ? `${location.round ? `Round ${location.round} · ` : ''}${location.item ? `Item ${location.item} · ` : ''}${location.node_id}` : current)
    current = location?.parent_scope
  }
  return labels.join(' / ')
}

export function callPath(run: Run, id: string): string[] {
  const path: string[]=[]
  const visited=new Set<string>()
  let parent=run.nodes[id]?.location?.parent_scope
  while(parent&&!visited.has(parent)) {
    visited.add(parent)
    const location: Run['nodes'][string]['location']=run.nodes[parent]?.location
    path.unshift(location?.node_id??parent)
    parent=location?.parent_scope
  }
  return path
}
