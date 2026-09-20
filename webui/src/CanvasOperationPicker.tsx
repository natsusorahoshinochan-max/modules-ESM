import { useState } from 'react'
import type { AuthoringCapabilities, CatalogSnapshot } from './protocol/client'
import { nodeTypePresentation, projectPalette, type PaletteTaxonomy } from './workflow-authoring'
import './workflow-authoring.css'

export function CanvasOperationPicker({ catalog, capabilities, position, requiredPort, onChoose, onClose }: {
  catalog: CatalogSnapshot
  capabilities: AuthoringCapabilities
  position: { x: number; y: number }
  requiredPort?: { direction: 'input' | 'output'; portTypeId: string }
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
      return Object.values(requiredPort.direction === 'input' ? node.inputPortTypes : node.outputPortTypes).includes(requiredPort.portTypeId)
    }),
  })).filter((group) => group.entries.length > 0)
  return <section className="canvas-operation-picker nodrag nowheel" style={{ left: position.x, top: position.y }} role="dialog" aria-label="添加节点" onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}>
    <header><strong>添加节点</strong><button type="button" aria-label="关闭节点搜索" onClick={onClose}>×</button></header>
    <input autoFocus aria-label="搜索节点" placeholder="按功能、模型或名称搜索" value={query} onChange={(event) => setQuery(event.target.value)} />
    <div className="taxonomy-switch"><button type="button" className={taxonomy === 'purpose' ? 'active' : ''} onClick={() => setTaxonomy('purpose')}>按研究目的</button><button type="button" className={taxonomy === 'provider' ? 'active' : ''} onClick={() => setTaxonomy('provider')}>按包 / 模型</button></div>
    {requiredPort && <p className="parameter-empty-hint">显示具有兼容{requiredPort.direction === 'input' ? '输入' : '输出'}的节点。</p>}
    {groups.map((group) => <div key={group.label}><h4>{group.label}</h4>{group.entries.map((entry) => <button type="button" key={entry.id} onClick={() => onChoose(entry.id)}><span>＋</span><span>{entry.title}<small>{entry.providerGroups.join(' · ')}</small></span></button>)}</div>)}
    {groups.length === 0 && <p className="parameter-empty-hint">没有匹配的操作。</p>}
  </section>
}
