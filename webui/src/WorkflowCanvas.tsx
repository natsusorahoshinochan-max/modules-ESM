import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { Edge, Flow, FlowNode } from '@protein-workbench/module-ui'
import type { Catalog } from './host-client'
import { declarationFor } from './flow-model'

type Position = { x: number; y: number }
interface Props {
  flow: Flow
  catalog: Catalog
  layout: Record<string, Position>
  disabled: boolean
  selectedSource: { source: string; source_port: string }
  onSource(node: string, port: string): void
  onTarget(node: string, port: string): void
  onMove(id: string, position: Position): void
  onDisconnect(index: number): void
  renderNode(node: FlowNode, index: number): ReactNode
}
const WIDTH = 480
function positionAt(layout: Props['layout'], nodes: FlowNode[], index: number, heights: Record<string, number>): Position {
  let y=24
  for(let row=0;row<Math.floor(index/2);row++) y+=Math.max(heights[nodes[row*2].id]||650,heights[nodes[row*2+1]?.id]||650)+70
  return layout[nodes[index].id] ?? {x:28+(index%2)*560,y}
}

export function WorkflowCanvas({ flow, catalog, layout, disabled, selectedSource, onSource, onTarget, onMove, onDisconnect, renderNode }: Props) {
  const surface = useRef<HTMLDivElement>(null)
  const [heights, setHeights] = useState<Record<string, number>>({})
  const [moving, setMoving] = useState<{ id: string; position: Position } | null>(null)
  const drag = useRef<{ id: string; pointer: number; start: Position; origin: Position } | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null)
  const positions = Object.fromEntries(flow.nodes.map((node, index) => [node.id, moving?.id === node.id ? moving.position : positionAt(layout, flow.nodes, index, heights)]))
  useLayoutEffect(() => {
    const nodes = [...(surface.current?.querySelectorAll<HTMLElement>('[data-canvas-node]') ?? [])]
    function measure() {
      const measured = Object.fromEntries(nodes.map(node => [node.dataset.canvasNode!, node.getBoundingClientRect().height]))
      setHeights(previous => JSON.stringify(previous) === JSON.stringify(measured) ? previous : measured)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    nodes.forEach(node => observer.observe(node))
    return () => observer.disconnect()
  }, [flow.nodes])
  function anchor(edge: Edge, side: 'source' | 'target') {
    const node = flow.nodes.find(item => item.id === edge[side])
    if (!node) return null
    const declaration = declarationFor(node, catalog)
    const ports = Object.keys(side === 'source' ? declaration?.outputs ?? {} : declaration?.inputs ?? {})
    const index = ports.indexOf(edge[side === 'source' ? 'source_port' : 'target_port'])
    return { x: positions[node.id].x + (side === 'source' ? WIDTH : 0), y: positions[node.id].y + 61 + Math.max(0, index) * 30 }
  }
  const width = Math.max(1100, ...flow.nodes.map(node => positions[node.id].x + WIDTH + 60))
  const height = Math.max(420, ...flow.nodes.map(node => positions[node.id].y + (heights[node.id] || 650) + 60))
  return <><p className="canvas-help">Drag a node by its handle, or focus the handle and use arrow keys. Connect an output, then an input. {selectedSource.source && <strong>Selected output: {selectedSource.source_port}</strong>}</p>
    <div className="canvas-viewport"><div ref={surface} className="canvas-surface" style={{ width, height }}>
      <svg className="canvas-wires" width={width} height={height} aria-label="Port connections">
        <defs><marker id="connection-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#456c91" /></marker></defs>
        {flow.edges.map((edge, index) => {
          const a = anchor(edge, 'source'), b = anchor(edge, 'target')
          if (!a || !b) return null
          const reach = Math.max(70, Math.abs(b.x - a.x) / 2)
          return <g key={index}><path className={selectedEdge === index ? 'wire selected' : 'wire'} d={`M${a.x},${a.y} C${a.x + reach},${a.y} ${b.x - reach},${b.y} ${b.x},${b.y}`} markerEnd="url(#connection-arrow)" />
            <path className="wire-target" tabIndex={0} role="button" aria-label={`Select connection ${edge.source_port} to ${edge.target_port}`} d={`M${a.x},${a.y} C${a.x + reach},${a.y} ${b.x - reach},${b.y} ${b.x},${b.y}`} onClick={() => setSelectedEdge(index)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedEdge(index) } }} /></g>
        })}
      </svg>
      {!flow.nodes.length && <p className="canvas-empty">Empty canvas. Add an operation or a subflow to begin.</p>}
      {flow.nodes.map((node, index) => {
        const declaration = declarationFor(node, catalog)
        const inputs = Object.entries(declaration?.inputs ?? {}), outputs = Object.entries(declaration?.outputs ?? {})
        const position = positions[node.id]
        return <div className="canvas-node" data-canvas-node={node.id} key={node.id} style={{ left: position.x, top: position.y, width: WIDTH }}>
          <button className="node-drag-handle" aria-label={`Move node ${index + 1}`} disabled={disabled}
            onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.focus(); event.currentTarget.setPointerCapture?.(event.pointerId); drag.current = { id: node.id, pointer: event.pointerId, start: {x: event.clientX, y: event.clientY}, origin: position } }}
            onPointerMove={event => { const active = drag.current; if (!active || active.id !== node.id || active.pointer !== event.pointerId || disabled) return; setMoving({id: node.id, position: {x: Math.max(0, Math.round(active.origin.x + event.clientX - active.start.x)), y: Math.max(0, Math.round(active.origin.y + event.clientY - active.start.y))}}) }}
            onPointerUp={event => { const active = drag.current; if (!active || active.id !== node.id || active.pointer !== event.pointerId) return; drag.current = null; setMoving(null); if (!disabled) onMove(node.id, {x: Math.max(0, Math.round(active.origin.x + event.clientX - active.start.x)), y: Math.max(0, Math.round(active.origin.y + event.clientY - active.start.y))}) }}
            onPointerCancel={() => { drag.current = null; setMoving(null) }}
            onKeyDown={event => { const delta: Record<string, Position> = {ArrowLeft: {x:-20,y:0}, ArrowRight:{x:20,y:0}, ArrowUp:{x:0,y:-20}, ArrowDown:{x:0,y:20}}; if (delta[event.key] && !disabled) { event.preventDefault(); const step = event.shiftKey ? 5 : 1; onMove(node.id, {x:Math.max(0, position.x + delta[event.key].x * step), y:Math.max(0, position.y + delta[event.key].y * step)}) } }}>
            ⠿ {index + 1} · {declaration?.name ?? node.type}
          </button>
          <div className="node-ports" style={{minHeight: Math.max(inputs.length, outputs.length) * 30}}><div>{inputs.map(([port, input]) => <button className="input-port" disabled={disabled} title={`${input.accepts.join(', ')} · ${input.cardinality}`} aria-label={`Connect to node ${index + 1} input ${port}`} key={port} onClick={() => onTarget(node.id, port)}><span>●</span> {port}</button>)}</div><div>{outputs.map(([port, output]) => <button className={selectedSource.source === node.id && selectedSource.source_port === port ? 'output-port selected' : 'output-port'} disabled={disabled} title={`${output.format} · ${output.cardinality}`} aria-label={`Connect from node ${index + 1} output ${port}`} key={port} onClick={() => onSource(node.id, port)}>{port} <span>●</span></button>)}</div></div>
          {renderNode(node, index)}
        </div>
      })}
    </div></div>
    {selectedEdge !== null && flow.edges[selectedEdge] && <p>Selected connection: {flow.edges[selectedEdge].source_port} → {flow.edges[selectedEdge].target_port} <button disabled={disabled} onClick={() => { onDisconnect(selectedEdge); setSelectedEdge(null) }}>Disconnect selected connection</button></p>}
  </>
}
