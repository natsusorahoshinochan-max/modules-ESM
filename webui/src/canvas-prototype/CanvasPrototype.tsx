/// <reference types="vite/client" />
// Throwaway A-layout prototype: direct manipulation of nodes, ports and parameters.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent as PE } from 'react'
import { getFields, getKind, getTool, initialGraph, kinds, newNode, nodeHeight, nodeWidth, type CanvasNode, type CanvasEdge, type Field, type Graph, type Point, type Kind } from './fixture'
import './prototype.css'

type View = Point & { scale: number }
type Socket = { node: string; side: 'input' | 'output'; index: number }
type Wire = { fixed: Socket; original: number | null; point: Point; hover: Socket | null; reason: string; moved: boolean }
type Placement = { kind: Kind; point: Point; valid: boolean }
type Gesture = { type: 'pan' | 'nodes' | 'box'; pointer: number; start: Point; view: View; graph: Graph; ids: string[]; additive: boolean; moved: boolean }
const copy = <T,>(value: T): T => structuredClone(value)
const editable = (target: EventTarget | null) => target instanceof HTMLElement && !!target.closest('input,textarea,.cp-tool-picker,[contenteditable]')
const sameSocket = (a: Socket | null, b: Socket) => a?.node === b.node && a.side === b.side && a.index === b.index
const curve = (a: Point, b: Point) => { const reach = Math.max(54, Math.abs(b.x - a.x) * .45); return `M${a.x},${a.y} C${a.x + reach},${a.y} ${b.x - reach},${b.y} ${b.x},${b.y}` }

function ToolPicker({ node, onChange, onOpen }: { node: CanvasNode; onChange: (id: string) => void; onOpen: () => void }) {
  const tools = getKind(node).tools!
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const listId = `tools-${node.id}`
  const selected = tools.findIndex(tool => tool.id === node.tool)
  const show = () => { setActive(selected); setOpen(true); onOpen() }
  const choose = (index: number) => { if (tools[index].id !== node.tool) onChange(tools[index].id); setOpen(false) }
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const blur = () => setOpen(false)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('blur', blur)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('blur', blur) }
  }, [open])
  return <div className="cp-tool-picker" ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}>
    <button type="button" className="cp-tool-trigger" role="combobox" aria-label={`${getKind(node).title} 工具`} aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? listId : undefined} aria-activedescendant={open ? `${listId}-${active}` : undefined} onClick={() => open ? setOpen(false) : show()} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false) }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); if (!open) show(); else setActive(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + tools.length) % tools.length) }
      if (open && (event.key === 'Home' || event.key === 'End')) { event.preventDefault(); setActive(event.key === 'Home' ? 0 : tools.length - 1) }
      if (open && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); choose(active) }
    }}><span>{tools[selected].name}</span><span aria-hidden="true">{open ? '▴' : '▾'}</span></button>
    {open && <div className="cp-tool-options" role="listbox" id={listId} aria-label={`${getKind(node).title} 可选工具`}>{tools.map((tool, index) => <button type="button" role="option" tabIndex={-1} id={`${listId}-${index}`} aria-selected={tool.id === node.tool} className={active === index ? 'cp-option-active' : ''} key={tool.id} onPointerDown={event => event.preventDefault()} onPointerMove={() => setActive(index)} onClick={() => choose(index)}><span>{tool.name}</span><span aria-hidden="true">{tool.id === node.tool ? '✓' : ''}</span></button>)}</div>}
  </div>
}

export default function CanvasPrototype() {
  const [graph, setGraphState] = useState<Graph>(initialGraph)
  const graphRef = useRef(graph)
  const [selected, setSelected] = useState<string[]>([])
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<string[]>([])
  const [view, setViewState] = useState<View>({ x: 60, y: 30, scale: 1 })
  const viewRef = useRef(view)
  const [history, setHistory] = useState<{ past: Graph[]; future: Graph[] }>({ past: [], future: [] })
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [tool, setTool] = useState<'select' | 'pan'>('select')
  const [space, setSpace] = useState(false)
  const [help, setHelp] = useState(false)
  const [debug, setDebug] = useState(false)
  const [box, setBox] = useState<{ start: Point; end: Point } | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [animateView, setAnimateView] = useState(false)
  const [size, setSize] = useState({ width: 1, height: 1 })
  const [heights, setHeights] = useState<Record<string, number>>({})
  const [wire, setWireState] = useState<Wire | null>(null)
  const wireRef = useRef<Wire | null>(null)
  const [placement, setPlacementState] = useState<Placement | null>(null)
  const placementRef = useRef<Placement | null>(null)
  const stage = useRef<HTMLDivElement>(null)
  const workspace = useRef<HTMLElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const specialPointer = useRef<number | null>(null)
  const libraryDrag = useRef<{ kind: Kind; start: Point; pointer: number } | null>(null)
  const insertion = useRef<Point | null>(null)
  const editBefore = useRef<Graph | null>(null)
  const fitTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fitted = useRef(false)
  const setGraph = (next: Graph) => { graphRef.current = next; setGraphState(next) }
  const setView = (next: View) => { viewRef.current = next; setViewState(next) }
  const setWire = (next: Wire | null) => { wireRef.current = next; setWireState(next) }
  const setPlacement = (next: Placement | null) => { placementRef.current = next; setPlacementState(next) }
  const busy = () => !!(gesture.current || wireRef.current || placementRef.current || libraryDrag.current)
  const height = (node: CanvasNode) => heights[node.id] ?? nodeHeight(node)
  function remember(before: Graph) { setHistory(state => ({ past: [...state.past.slice(-39), copy(before)], future: [] })) }
  function commit(next: Graph, message: string) { remember(graphRef.current); setGraph(next); setSelectedEdge(null); setAnnouncement(message) }
  function finishField() {
    if (editBefore.current && JSON.stringify(editBefore.current) !== JSON.stringify(graphRef.current)) { remember(editBefore.current); setAnnouncement('参数已修改') }
    editBefore.current = null
  }
  function undo(redo = false) {
    if (busy()) return
    const next = redo ? history.future[0] : history.past.at(-1)
    if (!next) return
    setHistory(redo ? { past: [...history.past, copy(graphRef.current)], future: history.future.slice(1) } : { past: history.past.slice(0, -1), future: [copy(graphRef.current), ...history.future] })
    setGraph(copy(next)); setSelectedEdge(null); setSelected(ids => ids.filter(id => next.nodes.some(node => node.id === id))); setAnnouncement(redo ? '已重做' : '已撤销')
  }
  function fit(ids?: string[]) {
    const nodes = ids?.length ? graphRef.current.nodes.filter(node => ids.includes(node.id)) : graphRef.current.nodes
    const rect = stage.current?.getBoundingClientRect(); if (!nodes.length || !rect) return
    const left = Math.min(...nodes.map(n => n.position.x)), top = Math.min(...nodes.map(n => n.position.y))
    const width = Math.max(...nodes.map(n => n.position.x + nodeWidth)) - left, tall = Math.max(...nodes.map(n => n.position.y + height(n))) - top
    const scale = Math.max(.2, Math.min(1.1, (rect.width - 96) / width, (rect.height - 130) / tall))
    if (fitTimer.current) clearTimeout(fitTimer.current)
    setAnimateView(true); setView({ x: (rect.width - width * scale) / 2 - left * scale, y: (rect.height - 64 - tall * scale) / 2 - top * scale, scale })
    fitTimer.current = setTimeout(() => setAnimateView(false), 260)
  }
  function zoom(scale: number, point = { x: size.width / 2, y: size.height / 2 }) {
    if (busy()) return
    const current = viewRef.current, next = Math.min(2, Math.max(.2, scale)), ratio = next / current.scale
    setAnimateView(false); setView({ x: point.x - (point.x - current.x) * ratio, y: point.y - (point.y - current.y) * ratio, scale: next })
  }
  function local(event: { clientX: number; clientY: number }): Point { const r = stage.current!.getBoundingClientRect(); return { x: event.clientX - r.left, y: event.clientY - r.top } }
  function world(point: Point) { const v = viewRef.current; return { x: (point.x - v.x) / v.scale, y: (point.y - v.y) / v.scale } }
  function anchor(socket: Socket): Point {
    const node = graphRef.current.nodes.find(n => n.id === socket.node)!
    return { x: node.position.x + (socket.side === 'output' ? nodeWidth : 0), y: node.position.y + 60 + socket.index * 32 }
  }
  function port(socket: Socket) { const kind = getKind(graphRef.current.nodes.find(n => n.id === socket.node)!); return (socket.side === 'output' ? kind.outputs : kind.inputs)[socket.index] }
  function edgeFor(a: Socket, b: Socket): CanvasEdge { const output = a.side === 'output' ? a : b, input = a.side === 'input' ? a : b; return { source: output.node, output: output.index, target: input.node, input: input.index } }
  function invalid(a: Socket, b: Socket, original: number | null): string {
    if (a.side === b.side) return '请连接一个输入和一个输出'
    if (a.node === b.node) return '不能连接节点自身'
    const edge = edgeFor(a, b), output = a.side === 'output' ? a : b, input = a.side === 'input' ? a : b
    const declared = port(input), format = port(output).format
    if (!(declared.accepts ?? [declared.format]).includes(format)) return '格式不兼容，请选择明确的转换节点'
    const target = graphRef.current.nodes.find(n => n.id === edge.target)!
    if (target.bindings?.[edge.input]) return '此输入已绑定文件，请先移除文件绑定'
    const edges = graphRef.current.edges.filter((_, index) => index !== original)
    if (edges.some(e => e.target === edge.target && e.input === edge.input)) return '此输入已有连接，请先拖出原连线'
    const seen = new Set<string>(), queue = [edge.target]
    while (queue.length) { const id = queue.pop()!; if (id === edge.source) return '此连接会形成循环'; if (seen.has(id)) continue; seen.add(id); edges.filter(e => e.source === id).forEach(e => queue.push(e.target)) }
    return ''
  }
  function socketAt(event: { clientX: number; clientY: number }): Socket | null {
    const at = document.elementFromPoint(event.clientX, event.clientY)
    const direct = at?.closest<HTMLElement>('[data-port-node]')
    const read = (element: HTMLElement): Socket => ({ node: element.dataset.portNode!, side: element.dataset.portSide as Socket['side'], index: Number(element.dataset.portIndex) })
    if (direct) return read(direct)
    if (at?.closest('.cp-overlay,.cp-floating-library,.cp-node')) return null
    let closest: { socket: Socket; distance: number } | null = null
    stage.current?.querySelectorAll<HTMLElement>('[data-port-node]').forEach(element => {
      const r = element.querySelector('i')!.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2
      const distance = Math.hypot(x - event.clientX, y - event.clientY)
      if (distance < 18 && (!closest || distance < closest.distance) && document.elementFromPoint(x, y)?.closest('[data-port-node]') === element) closest = { socket: read(element), distance }
    })
    return (closest as { socket: Socket } | null)?.socket ?? null
  }
  function canvasAt(event: { clientX: number; clientY: number }, blank = false) {
    const element = document.elementFromPoint(event.clientX, event.clientY)
    return !!element?.closest('.cp-stage') && !element.closest(blank ? '.cp-node,.cp-overlay,.cp-wire-hit' : '.cp-overlay')
  }
  function capture(pointer: number) { workspace.current!.setPointerCapture(pointer) }
  function release(pointer: number | null) { if (pointer !== null && workspace.current?.hasPointerCapture(pointer)) workspace.current.releasePointerCapture(pointer) }
  function startWire(event: PE, socket: Socket) {
    if (event.button !== 0 || busy()) return
    event.preventDefault(); event.stopPropagation(); stage.current?.focus(); setAnimateView(false); setSelectedEdge(null)
    const original = socket.side === 'input' ? graphRef.current.edges.findIndex(e => e.target === socket.node && e.input === socket.index) : -1
    const old = graphRef.current.edges[original]
    setWire({ fixed: old ? { node: old.source, side: 'output', index: old.output } : socket, original: original < 0 ? null : original, point: world(local(event)), hover: null, reason: '', moved: false })
    specialPointer.current = event.pointerId; capture(event.pointerId)
  }
  function begin(event: PE, id?: string) {
    if (event.button !== 0 && event.button !== 1 || busy()) return
    const target = event.target as HTMLElement
    if (target.closest('input,textarea,.cp-tool-picker,.cp-overlay,[data-port-node],.cp-wire-hit')) return
    const panning = event.button === 1 || space || tool === 'pan'
    if (target.closest('button') && !target.closest('.cp-node-head')) return
    event.preventDefault(); event.stopPropagation(); stage.current?.focus(); setAnimateView(false); setSelectedEdge(null)
    let ids = selected
    if (id && !panning) { ids = event.shiftKey ? selected.includes(id) ? selected.filter(item => item !== id) : [...selected, id] : selected.includes(id) ? selected : [id]; setSelected(ids); if (!target.closest('.cp-node-head')) return }
    const point = local(event), type = panning ? 'pan' : id ? 'nodes' : 'box'
    if (type === 'box') { if (!event.shiftKey) setSelected([]); setBox({ start: point, end: point }) }
    gesture.current = { type, pointer: event.pointerId, start: point, view: { ...viewRef.current }, graph: copy(graphRef.current), ids, additive: event.shiftKey, moved: false }; capture(event.pointerId)
  }
  function move(event: PE) {
    if (libraryDrag.current) {
      const drag = libraryDrag.current
      if (drag.pointer !== event.pointerId) return
      if (Math.hypot(event.clientX - drag.start.x, event.clientY - drag.start.y) < 5 && !placementRef.current) return
      setPlacement({ kind: drag.kind, point: world(local(event)), valid: canvasAt(event) }); return
    }
    if (wireRef.current) {
      if (event.pointerId !== specialPointer.current) return
      const current = wireRef.current, hover = socketAt(event), reason = hover ? invalid(current.fixed, hover, current.original) : ''
      setWire({ ...current, moved: true, hover, reason, point: hover && !reason ? anchor(hover) : world(local(event)) }); return
    }
    if (placementRef.current) { setPlacement({ ...placementRef.current, point: world(local(event)), valid: canvasAt(event) }); return }
    const g = gesture.current; if (!g || g.pointer !== event.pointerId) return
    const point = local(event), dx = point.x - g.start.x, dy = point.y - g.start.y
    if (Math.hypot(dx, dy) < 3 && !g.moved) return
    g.moved = true
    if (g.type === 'pan') setView({ ...g.view, x: g.view.x + dx, y: g.view.y + dy })
    if (g.type === 'nodes') setGraph({ ...g.graph, nodes: g.graph.nodes.map(node => g.ids.includes(node.id) ? { ...node, position: { x: node.position.x + dx / g.view.scale, y: node.position.y + dy / g.view.scale } } : node) })
    if (g.type === 'box') {
      setBox({ start: g.start, end: point }); const a = world(g.start), b = world(point)
      const found = g.graph.nodes.filter(node => node.position.x < Math.max(a.x, b.x) && node.position.x + nodeWidth > Math.min(a.x, b.x) && node.position.y < Math.max(a.y, b.y) && node.position.y + height(node) > Math.min(a.y, b.y)).map(node => node.id)
      setSelected(g.additive ? [...new Set([...g.ids, ...found])] : found)
    }
  }
  function add(kind: Kind, point: Point) {
    const node = newNode(kind, { x: point.x - nodeWidth / 2, y: point.y - 22 })
    commit({ ...graphRef.current, nodes: [...graphRef.current.nodes, node] }, `已添加「${kind.title}」`); setSelected([node.id]); setPlacement(null); setLibraryOpen(false); insertion.current = null
  }
  function end(event: PE) {
    if (libraryDrag.current) {
      const drag = libraryDrag.current; if (event.pointerId !== drag.pointer) return
      const placing = placementRef.current; libraryDrag.current = null; release(drag.pointer)
      if (placing) { if (canvasAt(event)) add(drag.kind, world(local(event))); else { setPlacement(null); setAnnouncement('已取消添加') } } else chooseFromLibrary(drag.kind)
      return
    }
    if (wireRef.current) {
      if (event.pointerId !== specialPointer.current) return
      const active = wireRef.current, target = socketAt(event)
      if (active.moved && target) {
        const reason = invalid(active.fixed, target, active.original)
        if (reason) setAnnouncement(`${reason}；原连接保持不变`)
        else {
          const edge = edgeFor(active.fixed, target), old = active.original === null ? null : graphRef.current.edges[active.original]
          if (JSON.stringify(edge) !== JSON.stringify(old)) commit({ ...graphRef.current, edges: [...graphRef.current.edges.filter((_, i) => i !== active.original), edge] }, old ? '已改接连线' : '已连接端口')
        }
      } else if (active.moved && active.original !== null && canvasAt(event, true)) commit({ ...graphRef.current, edges: graphRef.current.edges.filter((_, i) => i !== active.original) }, '已断开连线')
      else if (active.moved) setAnnouncement('已取消连线操作')
      setWire(null); release(specialPointer.current); specialPointer.current = null; return
    }
    const g = gesture.current; if (!g || g.pointer !== event.pointerId) return
    if (g.type === 'nodes' && g.moved && g.ids.length) { remember(g.graph); setAnnouncement(`已移动 ${g.ids.length} 个节点`) }
    gesture.current = null; setBox(null); release(event.pointerId)
  }
  function cancelGesture() {
    const g = gesture.current
    if (g?.type === 'nodes') setGraph(g.graph)
    if (g?.type === 'pan') setView(g.view)
    gesture.current = null; setBox(null); release(g?.pointer ?? null)
    release(specialPointer.current); specialPointer.current = null; setWire(null)
    if (libraryDrag.current) { release(libraryDrag.current.pointer); libraryDrag.current = null }
    setPlacement(null)
  }
  function startLibraryDrag(event: PE, kind: Kind) {
    if (event.button !== 0) return
    event.preventDefault(); event.stopPropagation(); stage.current?.focus(); setAnimateView(false)
    libraryDrag.current = { kind, pointer: event.pointerId, start: { x: event.clientX, y: event.clientY } }; capture(event.pointerId)
  }
  function chooseFromLibrary(kind: Kind) {
    setLibraryOpen(false); setPlacement({ kind, point: insertion.current ?? world({ x: size.width / 2, y: size.height / 2 }), valid: false }); setAnnouncement('点击画布放置节点，Esc 取消'); stage.current?.focus()
  }
  function remove() {
    if (busy()) return
    if (selectedEdge !== null) { commit({ ...graphRef.current, edges: graphRef.current.edges.filter((_, i) => i !== selectedEdge) }, '已删除连线'); return }
    if (!selected.length) return
    commit({ nodes: graphRef.current.nodes.filter(node => !selected.includes(node.id)), edges: graphRef.current.edges.filter(edge => !selected.includes(edge.source) && !selected.includes(edge.target)) }, `已删除 ${selected.length} 个节点`); setSelected([])
  }
  function duplicate() {
    if (!selected.length || busy()) return
    const map = new Map(selected.map(id => [id, crypto.randomUUID()]))
    const nodes = graphRef.current.nodes.filter(node => map.has(node.id)).map(node => ({ ...copy(node), id: map.get(node.id)!, position: { x: node.position.x + 44, y: node.position.y + 44 } }))
    const edges = graphRef.current.edges.filter(edge => map.has(edge.source) && map.has(edge.target)).map(edge => ({ ...edge, source: map.get(edge.source)!, target: map.get(edge.target)! }))
    commit({ nodes: [...graphRef.current.nodes, ...nodes], edges: [...graphRef.current.edges, ...edges] }, `已复制 ${nodes.length} 个节点`); setSelected(nodes.map(node => node.id))
  }
  function toggleExpanded(id: string) { setSelected([id]); setExpanded(ids => ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id]) }
  function switchTool(node: CanvasNode, id: string) {
    const kind = getKind(node), next = kind.tools!.find(item => item.id === id)!
    const fields = Object.fromEntries([...kind.fields.map(field => [field.key, node.fields[field.key]]), ...next.fields.map(field => [field.key, field.value])])
    commit({ ...graphRef.current, nodes: graphRef.current.nodes.map(n => n.id === node.id ? { ...n, tool: id, fields } : n) }, `已选择 ${next.name}，工具参数采用其默认值`)
  }
  function field(node: CanvasNode, definition: Field) {
    const key = definition.key, label = `${getKind(node).title} ${key}`, value = node.fields[key]
    const change = (value: string, immediate = false) => {
      const next = { ...graphRef.current, nodes: graphRef.current.nodes.map(n => n.id === node.id ? { ...n, fields: { ...n.fields, [key]: value } } : n) }
      if (immediate) commit(next, `${key}已更新`); else setGraph(next)
    }
    return <label className="cp-field" key={key}><span>{key}</span>{definition.type === 'readonly' ? <output aria-label={label}>{value}</output> : definition.type === 'boolean' ? <button type="button" role="switch" aria-label={label} aria-checked={value === 'true'} className={`cp-toggle ${value === 'true' ? 'on' : ''}`} onClick={() => change(String(value !== 'true'), true)}><span>{value === 'true' ? '开启' : '关闭'}</span><i /></button> : <input aria-label={label} type={definition.type} value={value} min={definition.min} max={definition.max} step={definition.step} required={definition.type === 'number'} onFocus={() => { editBefore.current = copy(graphRef.current) }} onChange={event => change(event.target.value)} onBlur={event => {
      if (!event.currentTarget.checkValidity()) { if (editBefore.current) setGraph(editBefore.current); editBefore.current = null; setAnnouncement(`${key}超出允许范围，已恢复原值`) } else finishField()
    }} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { if (editBefore.current) setGraph(editBefore.current); editBefore.current = null; event.currentTarget.blur() } }} />}</label>
  }
  function socketButton(node: CanvasNode, side: Socket['side'], index: number) {
    const kind = getKind(node), p = (side === 'input' ? kind.inputs : kind.outputs)[index]
    if (!p) return <span />
    const socket: Socket = { node: node.id, side, index }, compatible = wire && !invalid(wire.fixed, socket, wire.original)
    const hovered = wire && sameSocket(wire.hover, socket), connected = graph.edges.some(edge => side === 'input' ? edge.target === node.id && edge.input === index : edge.source === node.id && edge.output === index)
    return <span className={`cp-${side}-port`} style={{ '--port': p.color } as CSSProperties}><button type="button" className={`cp-port-dot ${compatible ? 'cp-port-compatible' : ''} ${hovered ? wire.reason ? 'cp-port-invalid' : 'cp-port-hover' : ''}`} data-port-node={node.id} data-port-side={side} data-port-index={index} aria-label={`${kind.title} ${side === 'input' ? '输入' : '输出'} ${p.label}`} title={`${p.format}${side === 'input' && connected ? ' · 拖出可断开或改接' : ' · 拖动连线'}`} onPointerDown={event => startWire(event, socket)}><i className={connected || node.bindings?.[index] && side === 'input' ? 'connected' : ''} /></button><span>{p.label}</span></span>
  }
  useLayoutEffect(() => {
    const elements = [...stage.current!.querySelectorAll<HTMLElement>('[data-node]')]
    const measure = () => { const next = Object.fromEntries(elements.map(element => [element.dataset.node!, element.offsetHeight])); setHeights(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next) }
    measure(); const observer = new ResizeObserver(measure); elements.forEach(element => observer.observe(element)); return () => observer.disconnect()
  }, [graph.nodes.length, expanded])
  useLayoutEffect(() => {
    const element = stage.current!
    const resize = () => { const r = element.getBoundingClientRect(); setSize({ width: r.width, height: r.height }); if (!fitted.current && r.width > 0) { if (r.width < 1100) setView({ x: 40, y: 20, scale: .9 }); else fit(); fitted.current = true } }
    resize(); const observer = new ResizeObserver(resize); observer.observe(element); return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const element = stage.current!
    const wheel = (event: WheelEvent) => {
      if ((event.target as HTMLElement).closest('input,.cp-tool-picker,.cp-overlay')) return
      event.preventDefault(); if (busy()) return
      setAnimateView(false); const rect = element.getBoundingClientRect()
      if (event.ctrlKey || event.metaKey || event.altKey) {
        const current = viewRef.current, next = Math.min(2, Math.max(.2, current.scale * Math.exp(-event.deltaY * .006))), ratio = next / current.scale
        const point = { x: event.clientX - rect.left, y: event.clientY - rect.top }
        setView({ x: point.x - (point.x - current.x) * ratio, y: point.y - (point.y - current.y) * ratio, scale: next })
      } else setView({ ...viewRef.current, x: viewRef.current.x - event.deltaX, y: viewRef.current.y - event.deltaY })
    }
    element.addEventListener('wheel', wheel, { passive: false }); return () => { element.removeEventListener('wheel', wheel); if (fitTimer.current) clearTimeout(fitTimer.current) }
  }, [])
  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && busy()) { event.preventDefault(); cancelGesture(); setAnnouncement('已取消操作，原状态保持不变'); return }
      if (editable(event.target)) return
      if (help || debug) { if (event.key === 'Escape') { setHelp(false); setDebug(false) }; return }
      const modifier = event.metaKey || event.ctrlKey
      if (event.code === 'Space') { event.preventDefault(); setSpace(true) }
      if (event.key === 'Escape') { setLibraryOpen(false); setSelected([]); setSelectedEdge(null) }
      if (busy()) return
      if (modifier && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(event.shiftKey) }
      if (modifier && event.key.toLowerCase() === 'a') { event.preventDefault(); setSelected(graphRef.current.nodes.map(node => node.id)); setSelectedEdge(null) }
      if (modifier && event.key.toLowerCase() === 'd') { event.preventDefault(); duplicate() }
      if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); remove() }
      if (event.key.toLowerCase() === 'f') { event.preventDefault(); fit(event.shiftKey ? undefined : selected) }
      if (event.key.toLowerCase() === 'a' && !modifier) { insertion.current = null; setLibraryOpen(value => !value) }
      if (event.key.toLowerCase() === 'v') setTool('select')
      if (event.key.toLowerCase() === 'h') setTool('pan')
      if (event.key === '+' || event.key === '=') zoom(viewRef.current.scale * 1.2)
      if (event.key === '-') zoom(viewRef.current.scale / 1.2)
      if (event.key === '0') zoom(1)
      if (event.key === '?') setHelp(value => !value)
    }
    const up = (event: KeyboardEvent) => { if (event.code === 'Space') setSpace(false) }
    const blur = () => { setSpace(false); cancelGesture() }
    window.addEventListener('keydown', down); window.addEventListener('keyup', up); window.addEventListener('blur', blur)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur) }
  })
  const library = <section className="cp-library cp-panel"><div className="cp-panel-title"><strong>节点库</strong><button aria-label="关闭节点库" onClick={() => setLibraryOpen(false)}>×</button></div><div className="cp-search"><span>⌕</span><input autoFocus placeholder="搜索节点…" aria-label="搜索节点" value={search} onChange={event => setSearch(event.target.value)} /></div><p className="cp-library-hint">拖到画布，或点击后选择放置位置</p><div className="cp-library-list">{kinds.filter(kind => `${kind.title} ${kind.category}`.includes(search)).map(kind => <button key={kind.type} data-library-kind={kind.type} onPointerDown={event => startLibraryDrag(event, kind)} onClick={event => { if (event.detail === 0) chooseFromLibrary(kind) }}><span>{kind.title}<small>{kind.category}</small></span><span className="cp-plus">⠿</span></button>)}{!kinds.some(kind => `${kind.title} ${kind.category}`.includes(search)) && <p>没有匹配的节点</p>}</div></section>
  const canvas = <div className={`cp-stage ${space || tool === 'pan' ? 'cp-pan' : ''} ${wire ? 'cp-wiring' : ''} ${placement ? 'cp-placing' : ''}`} ref={stage} tabIndex={0} role="region" aria-label="工作流画布" onPointerDown={event => { if (placementRef.current && !libraryDrag.current) { if (event.button === 0 && canvasAt(event)) { event.preventDefault(); event.stopPropagation(); add(placementRef.current.kind, world(local(event))) }; return }; begin(event) }} onDoubleClick={event => { if (!(event.target as HTMLElement).closest('.cp-node,.cp-overlay,.cp-wire-hit')) { insertion.current = world(local(event)); setLibraryOpen(true) } }} style={{ backgroundSize: `${24 * view.scale}px ${24 * view.scale}px`, backgroundPosition: `${view.x}px ${view.y}px` }}>
    <div className={`cp-world ${animateView ? 'cp-ease-view' : ''}`} style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
      <svg className="cp-wires" aria-label="数据流连接">{graph.edges.map((edge, index) => {
        if (wire?.original === index) return null
        const a = anchor({ node: edge.source, side: 'output', index: edge.output }), b = anchor({ node: edge.target, side: 'input', index: edge.input }), color = port({ node: edge.source, side: 'output', index: edge.output }).color
        return <g key={index}><path className={selectedEdge === index ? 'cp-selected-wire' : selected.length && !selected.includes(edge.source) && !selected.includes(edge.target) ? 'cp-dim-wire' : ''} d={curve(a, b)} stroke={color} /><path className="cp-wire-hit" role="button" tabIndex={0} aria-label={`选择连线 ${index + 1}`} d={curve(a, b)} onPointerDown={event => { event.stopPropagation(); setSelectedEdge(index); setSelected([]); stage.current?.focus() }} onKeyDown={event => { if (event.key === 'Enter') { setSelectedEdge(index); setSelected([]) } }} /></g>
      })}
      {wire && <path className={`cp-wire-preview ${wire.reason ? 'invalid' : ''}`} stroke={wire.reason ? '#e79d8d' : port(wire.fixed).color} d={wire.fixed.side === 'output' ? curve(anchor(wire.fixed), wire.point) : curve(wire.point, anchor(wire.fixed))} />}
      </svg>
      {graph.nodes.map((node, index) => { const kind = getKind(node), open = expanded.includes(node.id), fields = getFields(node), activeTool = getTool(node); return <article className={`cp-node ${selected.includes(node.id) ? 'cp-selected' : ''} ${open ? 'cp-expanded' : ''}`} key={node.id} data-node={node.id} style={{ left: node.position.x, top: node.position.y, width: nodeWidth, zIndex: selected.includes(node.id) ? 4 : open ? 3 : 1 }} onPointerDown={event => begin(event, node.id)}>
        <button className="cp-node-head" aria-label={`选择 ${kind.title}`} onClick={event => { if (event.detail === 0) setSelected([node.id]) }} onDoubleClick={event => { event.stopPropagation(); toggleExpanded(node.id) }}><span className="cp-node-mark">{String(index + 1).padStart(2, '0')}</span><strong>{kind.title}</strong><span className="cp-grip">⠿</span></button>
        <div className="cp-ports">{Array.from({ length: Math.max(kind.inputs.length, kind.outputs.length) }, (_, row) => <div className="cp-port-row" key={row}>{socketButton(node, 'input', row)}{socketButton(node, 'output', row)}</div>)}</div>
        <div className="cp-node-fields">{kind.tools && <div className="cp-field"><span>工具</span><ToolPicker node={node} onChange={id => switchTool(node, id)} onOpen={() => setSelected([node.id])} /></div>}{fields.filter(field => !field.advanced).map(definition => field(node, definition))}</div>
        {node.bindings && Object.entries(node.bindings).map(([input, file]) => <div className="cp-input-binding" key={input}><span>↳ {file}</span><button aria-label={`移除输入文件 ${file}`} title="移除文件绑定" onClick={() => commit({ ...graphRef.current, nodes: graphRef.current.nodes.map(n => { if (n.id !== node.id) return n; const bindings = { ...n.bindings }; delete bindings[Number(input)]; return { ...n, bindings } }) }, '已移除文件绑定')}>×</button></div>)}
        <div className="cp-node-foot"><span><i />未运行</span><button aria-expanded={open} aria-label={`${open ? '收起' : '展开'} ${kind.title} 属性`} onClick={() => toggleExpanded(node.id)}>{open ? '收起属性 ▴' : '属性 ▾'}</button></div>
        {open && <div className="cp-node-details">{activeTool && <p className="cp-tool-hint">{activeTool.hint}</p>}{fields.some(field => field.advanced) && <div className="cp-advanced-fields">{fields.filter(field => field.advanced).map(definition => field(node, definition))}</div>}<div className="cp-port-detail"><strong>端口格式</strong>{[...kind.inputs.map(p => ({ ...p, direction: '输入' })), ...kind.outputs.map(p => ({ ...p, direction: '输出' }))].map((p, i) => <div key={i}><span style={{ color: p.color }}>{p.direction} · {p.label}</span><code>{p.format.slice(0, p.format.indexOf('.') + 1)}<wbr />{p.format.slice(p.format.indexOf('.') + 1)}</code></div>)}</div></div>}
      </article> })}
      {placement && <div className={`cp-node-preview ${placement.valid ? '' : 'invalid'}`} style={{ left: placement.point.x - nodeWidth / 2, top: placement.point.y - 22, width: nodeWidth }}><strong>{placement.kind.title}</strong><span>{placement.valid ? '松开放置' : '移到画布放置'}</span></div>}
    </div>
    {wire && <div className={`cp-wire-feedback cp-overlay ${wire.reason ? 'invalid' : ''}`} role="status">{wire.reason || (wire.hover ? '松开连接' : wire.original !== null ? '拖到端口改接 · 放到空白断开 · Esc 取消' : '拖到兼容端口连接 · Esc 取消')}</div>}
    {placement && <div className="cp-placement-feedback cp-overlay">{placement.kind.title} · {libraryDrag.current ? '拖到画布松手放置' : '点击画布放置'} · Esc 取消</div>}
    {box && <div className="cp-selection-box" style={{ left: Math.min(box.start.x, box.end.x), top: Math.min(box.start.y, box.end.y), width: Math.abs(box.start.x - box.end.x), height: Math.abs(box.start.y - box.end.y) }} />}
    {!graph.nodes.length && !placement && <div className="cp-canvas-empty"><h2>从一个节点开始</h2><button onClick={() => setLibraryOpen(true)}>＋ 添加节点</button></div>}
    <div className="cp-canvas-tools cp-overlay"><button title="选择 V" aria-label="选择工具" aria-pressed={tool === 'select'} className={tool === 'select' ? 'active' : ''} onClick={() => setTool('select')}>↖</button><button title="平移 H / 空格拖动" aria-label="平移工具" aria-pressed={tool === 'pan'} className={tool === 'pan' ? 'active' : ''} onClick={() => setTool('pan')}>✥</button><hr /><button aria-label="缩小" onClick={() => zoom(view.scale / 1.2)}>−</button><button className="cp-scale" aria-label="恢复百分之百" onClick={() => zoom(1)}>{Math.round(view.scale * 100)}%</button><button aria-label="放大" onClick={() => zoom(view.scale * 1.2)}>＋</button><hr /><button title="适应全部 Shift F" aria-label="适应全部" onClick={() => { if (!busy()) fit() }}>⊡</button></div>
    <div className="cp-selection-actions cp-overlay">{selectedEdge !== null ? <><span>已选连线</span><button onClick={remove}>断开</button></> : selected.length > 0 && <><span>{selected.length} 个已选</span><button onClick={() => fit(selected)}>聚焦</button><button onClick={duplicate}>复制</button><button onClick={remove}>删除</button></>}</div>
    <div className="cp-minimap cp-overlay" aria-label="画布总览"><svg viewBox="-100 -40 1500 790" role="img" aria-label="节点位置总览">{graph.nodes.map(node => <rect key={node.id} x={node.position.x} y={node.position.y} width={nodeWidth} height={height(node)} fill={selected.includes(node.id) ? '#a9c4b8' : '#606965'} />)}<rect x={-view.x / view.scale} y={-view.y / view.scale} width={size.width / view.scale} height={size.height / view.scale} fill="none" stroke="#bcc8c0" strokeWidth="7" /></svg></div>
  </div>
  return <div className="canvas-prototype">
    <header className="cp-topbar"><div className="cp-brand"><span className="cp-brand-symbol">⠿</span><strong>Protein Workbench</strong></div><div className="cp-project-name">序列设计与结构预测<span className="cp-dirty" title="未保存" /></div><div className="cp-top-actions"><button aria-label="撤销" title="撤销 ⌘Z / Ctrl Z" disabled={!history.past.length || busy()} onClick={() => undo()}>↶</button><button aria-label="重做" title="重做 ⇧⌘Z / Ctrl Shift Z" disabled={!history.future.length || busy()} onClick={() => undo(true)}>↷</button><span className="cp-divider" /><button disabled title="原型尚未接入项目保存">保存</button><button className="cp-run" disabled title="原型尚未接入科学计算">▷ 运行</button></div></header>
    <nav className="cp-toolbar" aria-label="工作台操作"><button className={libraryOpen ? 'active' : ''} onClick={() => { cancelGesture(); insertion.current = null; setLibraryOpen(value => !value) }}>＋ 添加节点 <kbd>A</kbd></button><button onClick={() => { if (!busy()) fit() }}>适应视图 <kbd>⇧F</kbd></button><span className="cp-toolbar-spacer" /><span className="cp-graph-count">{graph.nodes.length} 节点 · {graph.edges.length} 连线</span><button aria-label="快捷键" onClick={() => setHelp(value => !value)}>?</button></nav>
    <main className="cp-workspace" ref={workspace} onPointerMove={move} onPointerUp={end} onPointerCancel={cancelGesture}><div className="cp-free-layout">{canvas}{libraryOpen && <div className={`cp-floating-library ${placement ? 'cp-library-dragging' : ''}`}>{library}</div>}</div></main>
    <footer className="cp-statusbar"><span role="status" aria-live="polite">{announcement || '空格拖动画布 · 双指平移 · 捏合缩放'}</span><span>拖动端口连线 · Shift 多选</span><button onClick={() => setDebug(value => !value)}>查看状态</button></footer>
    {help && <div className="cp-modal-backdrop" onClick={() => setHelp(false)}><section className="cp-help cp-panel" role="dialog" aria-modal="true" aria-label="快捷键" onClick={event => event.stopPropagation()}><div className="cp-panel-title"><strong>在画布上工作</strong><button aria-label="关闭快捷键" onClick={() => setHelp(false)}>×</button></div>{[['移动节点', '拖动节点标题'], ['平移画布', '空格 + 拖动 / 中键 / 双指'], ['缩放', '捏合 / Ctrl 或 Alt 滚轮'], ['连接 / 改接', '拖动端口'], ['断开连接', '拖已连接的输入到空白'], ['节点属性', '节点内展开 / 收起'], ['添加节点', '从节点库拖入 / 点击后放置'], ['框选 / 追加', '空白拖动 / Shift'], ['适应选中 / 全部', 'F / Shift F'], ['撤销 / 重做', '⌘ Z / ⇧ ⌘ Z（或 Ctrl）'], ['取消当前操作', 'Esc']].map(([label, key]) => <div className="cp-help-row" key={label}><span>{label}</span><kbd>{key}</kbd></div>)}</section></div>}
    {debug && <div className="cp-debug cp-panel"><div className="cp-panel-title"><strong>原型状态</strong><button onClick={() => setDebug(false)}>关闭</button></div><pre>{JSON.stringify({ viewport: view, selected, expanded, history: { undo: history.past.length, redo: history.future.length }, graph }, null, 2)}</pre></div>}
  </div>
}
