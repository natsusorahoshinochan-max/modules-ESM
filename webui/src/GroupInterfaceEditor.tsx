import type { CatalogSnapshot, Workflow } from './protocol/client'
import { groupNodes, groupPortId, groupPorts, type CanvasState, type GroupPort } from './canvas-groups'
import { nodeTypePresentation } from './workflow-authoring'

export function GroupInterfaceEditor({ canvas, workflow, catalog, groupId, onChange }: { canvas: CanvasState; workflow: Workflow; catalog: CatalogSnapshot; groupId: string; onChange: (ports: GroupPort[]) => void }) {
  const group = canvas.groups!.find(item => item.id === groupId)!
  const members = groupNodes(canvas, groupId)
  const automatic = groupPorts({ ...canvas, groups: canvas.groups!.map(item => item.id === groupId ? { ...item, ports: [] } : item) }, workflow, groupId)
  const exposed = groupPorts(canvas, workflow, groupId)
  return <details className="group-interface-editor nodrag nowheel"><summary>组输入 / 输出 · {exposed.length} 个公开端口</summary><p>每个公开端口对应一个成员端口。已有跨组连接或父组映射的端口会保留；先移除该连接或父组映射才能隐藏。</p>{workflow.nodes.filter(node => members.has(node.node_id)).map(node => {
    const presentation = nodeTypePresentation(catalog, node.node_type_id)
    return <fieldset key={node.node_id}><legend>{presentation.title} · {node.node_id}</legend>{(['input', 'output'] as const).flatMap(direction => (direction === 'input' ? presentation.inputs : presentation.outputs).map(port => {
      const reference: GroupPort = { nodeId: node.node_id, portName: port.name, direction }
      const id = groupPortId(reference)
      const current = exposed.find(item => groupPortId(item) === id)
      return <label key={id}><input type="checkbox" checked={!!current} disabled={automatic.some(item => groupPortId(item) === id)} onChange={event => onChange(event.target.checked ? [...group.ports, reference] : group.ports.filter(item => groupPortId(item) !== id))} />{direction === 'input' ? '输入' : '输出'} · {port.name}{current && <input key={current.label ?? ''} aria-label={`公开端口名称 ${node.node_id} ${port.name}`} placeholder={port.name} defaultValue={current.label ?? ''} onBlur={event => { const label = event.target.value.trim() || undefined; if (label !== current.label) onChange([...group.ports.filter(item => groupPortId(item) !== id), { ...reference, label }]) }} onKeyDown={event => { if (event.nativeEvent.isComposing) return; if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { event.stopPropagation(); event.currentTarget.value = current.label ?? ''; event.currentTarget.blur() } }} />}</label>
    }))}</fieldset>
  })}</details>
}
