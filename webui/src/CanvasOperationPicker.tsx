import * as Dialog from '@radix-ui/react-dialog'
import { useState } from 'react'
import type { AuthoringCapabilities, CatalogSnapshot } from './protocol/client'
import { nodeTypePresentation, projectPalette, type PaletteTaxonomy } from './workflow-authoring'
import { workflowPortsMatch } from './workflow-connections'
import './workflow-authoring.css'

export function CanvasOperationPicker({ catalog, capabilities, position, requiredPort, onChoose, onClose }: {
  catalog: CatalogSnapshot
  capabilities: AuthoringCapabilities
  position: { x: number; y: number }
  requiredPort?: { direction: 'input' | 'output'; portTypeId: string; multiplicity: 'one' | 'many' }
  onChoose: (nodeTypeId: string) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [taxonomy, setTaxonomy] = useState<PaletteTaxonomy>('purpose')
  const groups = projectPalette(catalog, capabilities, taxonomy, query).map((group) => ({
    ...group,
    entries: group.entries.filter((entry) => {
      if (!requiredPort) return true
      const node = nodeTypePresentation(catalog, entry.id)
      return (requiredPort.direction === 'input' ? node.inputs : node.outputs).some(port => requiredPort.direction === 'input' ? workflowPortsMatch(requiredPort, port) : workflowPortsMatch(port, requiredPort))
    }),
  })).filter((group) => group.entries.length > 0)
  return <Dialog.Root open modal={false} onOpenChange={open => { if (!open) onClose() }}><Dialog.Portal><Dialog.Content className="canvas-operation-picker nodrag nowheel" style={{ position: 'fixed', left: Math.max(8, Math.min(position.x, window.innerWidth - 340)), top: Math.max(8, Math.min(position.y, window.innerHeight - 450)) }} aria-describedby={undefined} onEscapeKeyDown={event => { if (event.isComposing) event.preventDefault() }} onKeyDown={event => { if (event.nativeEvent.isComposing) return; const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-picker-entry]')]; const index = items.indexOf(document.activeElement as HTMLButtonElement); if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); const next = index < 0 ? (event.key === 'ArrowDown' ? 0 : items.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length; items[next]?.focus() } if (event.key === 'Enter' && event.target instanceof HTMLInputElement) { event.preventDefault(); items[0]?.click() } }}>
    <header><Dialog.Title>添加节点</Dialog.Title><button type="button" aria-label="关闭节点搜索" onClick={onClose}>×</button></header>
    <input autoFocus aria-label="搜索节点" placeholder="按功能、模型或名称搜索" value={query} onChange={(event) => setQuery(event.target.value)} />
    <div className="taxonomy-switch"><button type="button" className={taxonomy === 'purpose' ? 'active' : ''} onClick={() => setTaxonomy('purpose')}>按研究目的</button><button type="button" className={taxonomy === 'provider' ? 'active' : ''} onClick={() => setTaxonomy('provider')}>按包 / 模型</button></div>
    {requiredPort && <p className="parameter-empty-hint">显示具有兼容{requiredPort.direction === 'input' ? '输入' : '输出'}的节点。</p>}
    {groups.map((group) => <div key={group.label}><h4>{group.label}</h4>{group.entries.map((entry) => <button data-picker-entry type="button" key={entry.id} onClick={() => onChoose(entry.id)}><span>＋</span><span>{entry.title}<small>{entry.providerGroups.join(' · ')}</small></span></button>)}</div>)}
    {groups.length === 0 && <p className="parameter-empty-hint">没有匹配的操作。</p>}
  </Dialog.Content></Dialog.Portal></Dialog.Root>
}
