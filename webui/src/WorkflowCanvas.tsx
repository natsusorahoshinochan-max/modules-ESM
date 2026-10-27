import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import type { Edge, Flow, FlowNode } from '@protein-workbench/module-ui'
import type { Catalog } from './host-client'
import { declarationFor } from './flow-model'

type Position = { x: number; y: number }
type View = Position & { scale: number }
type Socket = { node: string; port: string; side: 'input' | 'output' }
interface Props {
  flow: Flow
  focusRequest?: {id: string; token: number}
  catalog: Catalog
  layout: Record<string, Position>
  disabled: boolean
  selectedSource: { source: string; source_port: string }
  onSource(node: string, port: string): void
  onTarget(node: string, port: string): void
  onMove(id: string, position: Position): void
  onMoveMany?(positions: Record<string, Position>): void
  onDisconnect(index: number): void
  onConnect?(edge: Edge, replacingIndex?: number): void | Promise<void>
  onDelete?(ids: string[]): void
  onCopy?(ids: string[]): void
  onAdd?(type: string, position: Position): void | Promise<void>
  renderNode(node: FlowNode, index: number): ReactNode
  renderNodeResult?(node: FlowNode, index: number): ReactNode
  renderNodeSummary?(node: FlowNode, index: number): ReactNode
}
const WIDTH = 300
const HEADER = 40
const ROW = 28
const palette = ['#ad7b24', '#348a86', '#8b68b5', '#467fad', '#7d8c3b', '#b77155']
const curve = (a: Position, b: Position) => { const d = Math.max(55, Math.abs(b.x - a.x) * .45); return `M${a.x},${a.y} C${a.x + d},${a.y} ${b.x - d},${b.y} ${b.x},${b.y}` }
const editable = (target: EventTarget | null) => target instanceof HTMLElement && !!target.closest('input,textarea,select,[contenteditable="true"],[role="combobox"]')
const sameEdge = (a: Edge, b: Edge) => a.source === b.source && a.source_port === b.source_port && a.target === b.target && a.target_port === b.target_port

/** The same trigger opens and closes the picker; options are supplied by the live tool catalog. */
export function CanvasToolPicker({ value, options, label, disabled = false, onChange }: {
  value: string
  options: { id: string; name: string }[]
  label: string
  disabled?: boolean
  onChange(value: string): void
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const selected = options.findIndex(option => option.id === value)
  function show() { setActive(Math.max(0, selected)); setOpen(true) }
  function choose(index: number) { if (options[index]) onChange(options[index].id); setOpen(false); trigger.current?.focus() }
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const close = () => setOpen(false)
    document.addEventListener('pointerdown', outside); window.addEventListener('blur', close)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('blur', close) }
  }, [open])
  useEffect(() => { if (disabled) setOpen(false) }, [disabled])
  return <div className="canvas-tool-picker" ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}>
    <button ref={trigger} type="button" role="combobox" aria-label={label} aria-expanded={open} aria-haspopup="listbox" disabled={disabled}
      onClick={() => open ? setOpen(false) : show()}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false) }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); if (!open) show(); else if (options.length) setActive(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length) }
        if (open && (event.key === 'Home' || event.key === 'End')) { event.preventDefault(); setActive(event.key === 'Home' ? 0 : options.length - 1) }
        if (open && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); choose(active) }
      }}><span>{options[selected]?.name ?? (value ? '工具暂不可用' : '选择工具')}</span><span aria-hidden="true">{open ? '▴' : '▾'}</span></button>
    {open && <div role="listbox" aria-label={label + '选项'}>{options.map((option, index) => <button key={option.id} type="button" role="option" tabIndex={-1} aria-selected={option.id === value} className={active === index ? 'active' : ''} onPointerDown={event => event.preventDefault()} onPointerMove={() => setActive(index)} onClick={() => choose(index)}><span>{option.name}</span><span aria-hidden="true">{option.id === value ? '✓' : ''}</span></button>)}</div>}
  </div>
}

/** Check only public port declarations and graph topology; scientific validation belongs to modules. */
export function connectionProblem(flow: Flow, catalog: Catalog, edge: Edge, replacingIndex?: number): string {
  const source = flow.nodes.find(node => node.id === edge.source), target = flow.nodes.find(node => node.id === edge.target)
  const output = declarationFor(source, catalog)?.outputs[edge.source_port], input = declarationFor(target, catalog)?.inputs[edge.target_port]
  if (!source || !target || !output || !input) return '端口已不存在'
  if (source.id === target.id) return '不能连接节点自身'
  if (!input.accepts.includes(output.format)) return '端口格式不兼容，请使用明确的转换节点'
  if (input.cardinality === 'one' && output.cardinality === 'many') return '此输入只接受一个数据包'
  const edges = flow.edges.filter((_, index) => index !== replacingIndex)
  if (edges.some(item => sameEdge(item, edge))) return '这条连接已存在'
  if (input.cardinality === 'one' && ((target.inputs?.[edge.target_port]?.length ?? 0) > 0 || edges.some(item => item.target === edge.target && item.target_port === edge.target_port))) return '此输入已有数据或连线'
  const pending = [edge.target], visited = new Set<string>()
  while (pending.length) {
    const id = pending.pop()!
    if (id === edge.source) return '此连接会形成循环'
    if (visited.has(id)) continue
    visited.add(id)
    edges.filter(item => item.source === id).forEach(item => pending.push(item.target))
  }
  return ''
}

export function WorkflowCanvas({ focusRequest, flow, catalog, layout, disabled, selectedSource, onSource, onTarget, onMove, onMoveMany, onDisconnect, onConnect, onDelete, onCopy, onAdd, renderNode, renderNodeSummary, renderNodeResult }: Props) {
  const stage = useRef<HTMLDivElement>(null)
  const origins = useRef<Record<string, Position>>({})
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 })
  const viewRef = useRef(view); viewRef.current = view
  const [heights, setHeights] = useState<Record<string, number>>({})
  const [moving, setMoving] = useState<Record<string, Position>>({})
  const [selected, setSelected] = useState<string[]>([])
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<string[]>([])
  const [tool, setTool] = useState<'select' | 'pan'>('select')
  const [space, setSpace] = useState(false)
  const [notice, setNotice] = useState('')
  useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),2600);return()=>clearTimeout(timer)},[notice])
  const [library, setLibrary] = useState(false)
  const [search, setSearch] = useState('')
  const [placement, setPlacement] = useState<string | null>(null)
  const [box, setBox] = useState<{ start: Position; end: Position } | null>(null)
  const gesture = useRef<{ kind: 'pan' | 'nodes' | 'box'; pointer: number; start: Position; view: View; positions: Record<string, Position>; ids: string[]; moved: boolean } | null>(null)
  const [wire, setWire] = useState<{ fixed: Socket; original?: number; point: Position; hover: Socket | null; error: string } | null>(null)
  const wireRef = useRef(wire); wireRef.current = wire
  const wirePointer = useRef<{ pointer: number; start: Position; moved: boolean } | null>(null)
  const libraryDrag = useRef<{ type: string; pointer: number; start: Position; moved: boolean } | null>(null)
  flow.nodes.forEach((node, index) => { origins.current[node.id] ??= { x: 28 + (index % 3) * 380, y: 24 + Math.floor(index / 3) * 280 } })
  const positions = Object.fromEntries(flow.nodes.map(node => [node.id, moving[node.id] ?? layout[node.id] ?? origins.current[node.id]]))
  const formats = [...new Set(catalog.nodes.flatMap(node => Object.values(node.outputs).map(output => output.format)))].sort()
  const color = (format: string) => palette[Math.max(0, formats.indexOf(format)) % palette.length]
  const nodeHeight = (id: string) => heights[id] || 160
  function local(event: {clientX: number; clientY: number}) { const rect = stage.current!.getBoundingClientRect(); return {x: event.clientX - rect.left, y: event.clientY - rect.top} }
  function world(point: Position) { const v = viewRef.current; return {x: (point.x-v.x)/v.scale, y: (point.y-v.y)/v.scale} }
  function anchor(socket: Socket) {
    const declaration = declarationFor(flow.nodes.find(node => node.id === socket.node), catalog)
    const keys = Object.keys(socket.side === 'output' ? declaration?.outputs ?? {} : declaration?.inputs ?? {})
    return {x: positions[socket.node].x + (socket.side === 'output' ? WIDTH : 0), y: positions[socket.node].y + HEADER + ROW / 2 + Math.max(0, keys.indexOf(socket.port)) * ROW}
  }
  function edgeFor(a: Socket, b: Socket): Edge { const source = a.side === 'output' ? a : b, target = a.side === 'input' ? a : b; return {source:source.node, source_port:source.port, target:target.node, target_port:target.port} }
  function at(event: {clientX:number; clientY:number}) { return document.elementFromPoint?.(event.clientX,event.clientY) ?? null }
  function socketAt(event: {clientX:number; clientY:number}): Socket | null {
    const element = at(event)?.closest<HTMLElement>('[data-socket-node]')
    return element ? {node:element.dataset.socketNode!,port:element.dataset.socketPort!,side:element.dataset.socketSide as Socket['side']} : null
  }
  function problem(a: Socket, b: Socket, original?: number) { return a.side === b.side ? '请连接一个输入和一个输出' : connectionProblem(flow,catalog,edgeFor(a,b),original) }
  function cancel() { if (gesture.current?.kind === 'pan') setView(gesture.current.view); gesture.current=null; wirePointer.current=null; libraryDrag.current=null; setMoving({}); setBox(null); setWire(null); setPlacement(null) }
  function zoom(scale: number, point?: Position) {
    if (gesture.current || wireRef.current) return
    const rect=stage.current?.getBoundingClientRect(); if(!rect) return
    const center=point ?? {x:rect.width/2,y:rect.height/2}, current=viewRef.current, next=Math.max(.2,Math.min(2.5,scale)), ratio=next/current.scale
    setView({x:center.x-(center.x-current.x)*ratio,y:center.y-(center.y-current.y)*ratio,scale:next})
  }
  function fit(ids?: string[]) {
    const nodes=ids?.length ? flow.nodes.filter(node=>ids.includes(node.id)) : flow.nodes, rect=stage.current?.getBoundingClientRect()
    if(!nodes.length||!rect||!rect.width||!rect.height) return
    const left=Math.min(...nodes.map(node=>positions[node.id].x)), top=Math.min(...nodes.map(node=>positions[node.id].y))
    const width=Math.max(...nodes.map(node=>positions[node.id].x+WIDTH))-left, height=Math.max(...nodes.map(node=>positions[node.id].y+nodeHeight(node.id)))-top
    const scale=Math.max(.2,Math.min(1.1,(rect.width-100)/width,(rect.height-120)/height))
    setView({x:(rect.width-width*scale)/2-left*scale,y:(rect.height-height*scale)/2-top*scale-20,scale})
  }
  useEffect(()=>{if(focusRequest && positions[focusRequest.id]){setSelected([focusRequest.id]);fit([focusRequest.id])}},[focusRequest])
  useLayoutEffect(()=>{
    const elements=[...(stage.current?.querySelectorAll<HTMLElement>('[data-canvas-node]') ?? [])]
    const measure=()=>{const measured=Object.fromEntries(elements.map(element=>[element.dataset.canvasNode!,element.offsetHeight]));setHeights(previous=>JSON.stringify(previous)===JSON.stringify(measured)?previous:measured)}
    measure(); if(typeof ResizeObserver==='undefined') return
    const observer=new ResizeObserver(measure);elements.forEach(element=>observer.observe(element));return()=>observer.disconnect()
  },[flow.nodes,expanded])
  useEffect(() => {
    const live = new Set(flow.nodes.map(node => node.id))
    const prune = (ids: string[]) => ids.every(id => live.has(id)) ? ids : ids.filter(id => live.has(id))
    setSelected(prune)
    setExpanded(prune)
    if (gesture.current?.ids.some(id => !live.has(id))) cancel()
  }, [flow.nodes])
  useEffect(() => {
    setSelectedEdge(null)
    wirePointer.current = null
    setWire(null)
  }, [flow.edges])
  useEffect(()=>{if(disabled) cancel()},[disabled])
  useEffect(()=>{
    const release=()=>{setSpace(false);cancel()};window.addEventListener('blur',release)
    return()=>window.removeEventListener('blur',release)
  },[])
  useEffect(()=>{
    const element=stage.current;if(!element)return
    const wheel=(event:WheelEvent)=>{
      if((event.target as HTMLElement).closest('.canvas-library,.canvas-properties'))return
      event.preventDefault()
      if(event.ctrlKey||event.metaKey||event.altKey)zoom(viewRef.current.scale*Math.exp(-event.deltaY*.008),local(event))
      else setView(current=>({...current,x:current.x-event.deltaX,y:current.y-event.deltaY}))
    }
    element.addEventListener('wheel',wheel,{passive:false});return()=>element.removeEventListener('wheel',wheel)
  },[])
  function begin(event:ReactPointerEvent,id?:string) {
    if(event.button!==0&&event.button!==1||wirePointer.current||libraryDrag.current)return
    if(editable(event.target)||(event.target as HTMLElement).closest('[data-socket-node],.canvas-overlay,.wire-target'))return
    const panning=event.button===1||space||tool==='pan'
    const handle=(event.target as HTMLElement).closest('.node-drag-handle')
    if((event.target as HTMLElement).closest('button')&&!handle)return
    event.preventDefault();event.stopPropagation();stage.current?.focus();setSelectedEdge(null)
    if(placement&&!id&&!panning){void addAt(placement,world(local(event)));return}
    const liveSelected=selected.filter(value=>positions[value])
    let ids=liveSelected
    if(id&&!panning){ids=event.shiftKey?liveSelected.includes(id)?liveSelected.filter(value=>value!==id):[...liveSelected,id]:liveSelected.includes(id)?liveSelected:[id];setSelected(ids);if(!handle||disabled)return}
    if(!id&&!panning&&!event.shiftKey){ids=[];setSelected([])}
    const start=local(event),kind=panning?'pan':id?'nodes':'box'
    gesture.current={kind,pointer:event.pointerId,start,view:{...viewRef.current},positions:{...positions},ids,moved:false}
    if(kind==='box')setBox({start,end:start})
    stage.current?.setPointerCapture?.(event.pointerId)
  }
  function startWire(event:ReactPointerEvent,socket:Socket) {
    if(disabled||event.button!==0)return
    event.preventDefault();event.stopPropagation();stage.current?.focus()
    const incoming=flow.edges.map((edge,index)=>({edge,index})).filter(item=>item.edge.target===socket.node&&item.edge.target_port===socket.port)
    const candidate=socket.side==='input'?(incoming.length===1?incoming[0]:incoming.find(item=>item.index===selectedEdge)):undefined
    if(socket.side==='input'&&incoming.length>1&&!candidate){setNotice('此输入有多条连线，请先选择要改接的连线');return}
    const fixed:Socket=candidate?{node:candidate.edge.source,port:candidate.edge.source_port,side:'output'}:socket
    const point=local(event);wirePointer.current={pointer:event.pointerId,start:point,moved:false}
    setWire({fixed,original:candidate?.index,point:world(point),hover:null,error:''});stage.current?.setPointerCapture?.(event.pointerId)
  }
  function move(event:ReactPointerEvent) {
    const point=local(event)
    const dragging=libraryDrag.current
    if(dragging?.pointer===event.pointerId){if(Math.hypot(point.x-dragging.start.x,point.y-dragging.start.y)>4){dragging.moved=true;setPlacement(dragging.type)}return}
    if(wirePointer.current?.pointer===event.pointerId&&wireRef.current){
      if(Math.hypot(point.x-wirePointer.current.start.x,point.y-wirePointer.current.start.y)<4&&!wirePointer.current.moved)return
      wirePointer.current.moved=true
      const current=wireRef.current,hover=socketAt(event),error=hover?problem(current.fixed,hover,current.original):''
      setWire({...current,point:hover&&!error?anchor(hover):world(point),hover,error});return
    }
    const active=gesture.current;if(!active||active.pointer!==event.pointerId)return
    const dx=point.x-active.start.x,dy=point.y-active.start.y
    if(Math.hypot(dx,dy)<3&&!active.moved)return
    active.moved=true
    if(active.kind==='pan')setView({...active.view,x:active.view.x+dx,y:active.view.y+dy})
    if(active.kind==='nodes'&&!disabled)setMoving(Object.fromEntries(active.ids.map(id=>[id,{x:Math.round(active.positions[id].x+dx/active.view.scale),y:Math.round(active.positions[id].y+dy/active.view.scale)}])))
    if(active.kind==='box'){
      setBox({start:active.start,end:point});const a=world(active.start),b=world(point)
      const found=flow.nodes.filter(node=>positions[node.id].x<Math.max(a.x,b.x)&&positions[node.id].x+WIDTH>Math.min(a.x,b.x)&&positions[node.id].y<Math.max(a.y,b.y)&&positions[node.id].y+nodeHeight(node.id)>Math.min(a.y,b.y)).map(node=>node.id)
      setSelected([...new Set([...active.ids,...found])])
    }
  }
  async function addAt(type:string,point:Position){if(disabled||!onAdd)return;try{await onAdd(type,{x:Math.round(point.x-WIDTH/2),y:Math.round(point.y-HEADER/2)});setPlacement(null);setLibrary(false);setNotice('已添加节点')}catch(error){setNotice(String(error))}}
  function end(event:ReactPointerEvent) {
    const drag=libraryDrag.current
    if(drag?.pointer===event.pointerId){libraryDrag.current=null;if(drag.moved){if(at(event)?.closest('.canvas-viewport')&&!at(event)?.closest('.canvas-overlay'))void addAt(drag.type,world(local(event)));else setPlacement(null)}else{setPlacement(drag.type);setLibrary(false);setNotice('在画布上点击放置节点 · Esc 取消')}return}
    if(wirePointer.current?.pointer===event.pointerId&&wireRef.current){
      const active=wireRef.current,target=socketAt(event),moved=wirePointer.current.moved
      wirePointer.current=null;setWire(null)
      if(disabled||!moved)return
      if(target){const reason=problem(active.fixed,target,active.original);if(reason){setNotice(reason+'；原连接保持不变');return}
        const edge=edgeFor(active.fixed,target)
        if(active.original!==undefined&&sameEdge(edge,flow.edges[active.original]))return
        if(onConnect)void Promise.resolve().then(()=>onConnect(edge,active.original)).then(()=>setNotice('连线已更新')).catch(error=>setNotice(String(error)))
        else setNotice('请点击输出圆点，再点击输入圆点连接')
      }else if(active.original!==undefined&&at(event)?.closest('.canvas-viewport')&&!at(event)?.closest('.canvas-node,.canvas-overlay')){onDisconnect(active.original);setNotice('已断开连线')}
      return
    }
    const active=gesture.current;if(!active||active.pointer!==event.pointerId)return
    gesture.current=null;setBox(null)
    if(active.kind==='nodes'&&active.moved&&!disabled){if(onMoveMany)onMoveMany(moving);else Object.entries(moving).forEach(([id,position])=>onMove(id,position))}
    setMoving({})
  }
  const minimapNodes=flow.nodes.map(node=>({id:node.id,...positions[node.id],height:nodeHeight(node.id)}))
  const bounds={left:Math.min(0,...minimapNodes.map(node=>node.x)),top:Math.min(0,...minimapNodes.map(node=>node.y)),right:Math.max(800,...minimapNodes.map(node=>node.x+WIDTH)),bottom:Math.max(500,...minimapNodes.map(node=>node.y+node.height))}
  return <div className="canvas-workspace">
    <div className="canvas-tools"><button disabled={disabled||!onAdd} onClick={()=>setLibrary(open=>!open)} aria-expanded={library}>＋ 添加节点</button><button onClick={()=>fit()}>适应视图 <small>⇧ F</small></button><span className="canvas-count">{flow.nodes.length} 节点 · {flow.edges.length} 连线</span></div>
    <div className={'canvas-viewport'+(tool==='pan'||space?' canvas-panning':'')+(placement?' canvas-placing':'')} ref={stage} tabIndex={0} aria-label="Node canvas"
      style={{backgroundSize:`${24*view.scale}px ${24*view.scale}px`,backgroundPosition:`${view.x}px ${view.y}px`}}
      onPointerDown={event=>begin(event)} onPointerMove={move} onPointerUp={end} onPointerCancel={cancel}
      onDoubleClick={event=>{if(!(event.target as HTMLElement).closest('.canvas-node,.canvas-overlay')&&onAdd&&!disabled)setLibrary(true)}}
      onKeyDown={event=>{
        if(editable(event.target))return
        if(event.key===' '){event.preventDefault();setSpace(true)}
        if(event.key==='Escape'){cancel();setLibrary(false);setSelectedEdge(null)}
        if(event.key.toLowerCase()==='f'){event.preventDefault();fit(event.shiftKey?undefined:selected)}
        if(event.key==='0')zoom(1)
        if(event.key.toLowerCase()==='h')setTool('pan')
        if(event.key.toLowerCase()==='v')setTool('select')
        if(event.key.toLowerCase()==='a'){event.preventDefault();if(event.metaKey||event.ctrlKey)setSelected(flow.nodes.map(node=>node.id));else if(onAdd&&!disabled)setLibrary(true)}
        if(!disabled&&(event.key==='Delete'||event.key==='Backspace')){event.preventDefault();if(selectedEdge!==null){onDisconnect(selectedEdge);setSelectedEdge(null)}else if(onDelete&&selected.length){onDelete(selected);setSelected([])}}
        if(!disabled&&(event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='d'&&onCopy){event.preventDefault();onCopy(selected)}
      }} onKeyUp={event=>{if(event.key===' ')setSpace(false)}}>
      <div className="canvas-surface" style={{transform:`translate(${view.x}px,${view.y}px) scale(${view.scale})`}}>
        <svg className="canvas-wires" width="1" height="1" aria-label="Port connections">
          {flow.edges.map((edge,index)=>{
            if(!positions[edge.source]||!positions[edge.target])return null
            const a=anchor({node:edge.source,port:edge.source_port,side:'output'}),b=anchor({node:edge.target,port:edge.target_port,side:'input'})
            const format=declarationFor(flow.nodes.find(node=>node.id===edge.source),catalog)?.outputs[edge.source_port]?.format??''
            return <g key={index} opacity={wire?.original===index?0.15:1}><path className={selectedEdge===index?'wire selected':'wire'} d={curve(a,b)} style={{stroke:selectedEdge===index?'#345bdb':color(format)}}/><path className="wire-target" tabIndex={0} role="button" aria-label={`Select connection ${edge.source_port} to ${edge.target_port}`} d={curve(a,b)} onClick={()=>{setSelectedEdge(index);setSelected([])}} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();setSelectedEdge(index);setSelected([])}}}/></g>
          })}
          {wire&&positions[wire.fixed.node]&&<path className="wire wire-preview" d={wire.fixed.side==='output'?curve(anchor(wire.fixed),wire.point):curve(wire.point,anchor(wire.fixed))}/>}
        </svg>
        {flow.nodes.map((node,index)=>{
          const declaration=declarationFor(node,catalog),inputs=Object.entries(declaration?.inputs??{}),outputs=Object.entries(declaration?.outputs??{}),position=positions[node.id],open=expanded.includes(node.id)
          return <div className={'canvas-node'+(selected.includes(node.id)?' selected':'')} data-canvas-node={node.id} key={node.id} style={{left:position.x,top:position.y,width:WIDTH,zIndex:open?3:selected.includes(node.id)?2:1}} onPointerDown={event=>begin(event,node.id)}>
            <button className="node-drag-handle" aria-label={`Move node ${index+1}`} onDoubleClick={()=>setExpanded(ids=>open?ids.filter(id=>id!==node.id):[...ids,node.id])}
              onKeyDown={event=>{const delta:Record<string,Position>={ArrowLeft:{x:-20,y:0},ArrowRight:{x:20,y:0},ArrowUp:{x:0,y:-20},ArrowDown:{x:0,y:20}};if(delta[event.key]&&!disabled){event.preventDefault();event.stopPropagation();const step=event.shiftKey?5:1;onMove(node.id,{x:position.x+delta[event.key].x*step,y:position.y+delta[event.key].y*step})}}}><small>{String(index+1).padStart(2,'0')}</small><span>{declaration?.name??node.type}</span><span className="node-grip">⠿</span></button>
            <div className="node-ports" style={{height:Math.max(inputs.length,outputs.length)*ROW}}>
              {(['input','output'] as const).map(side=><div className={side+'-ports'} key={side}>{(side==='input'?inputs:outputs).map(([port,description])=>{
                const format='format' in description?description.format:description.accepts[0]??'',socket:Socket={node:node.id,port,side}
                const connected=flow.edges.some(edge=>side==='input'?edge.target===node.id&&edge.target_port===port:edge.source===node.id&&edge.source_port===port)
                return <div className="node-port-row" key={port}><span>{description.name ?? port}</span><button type="button" className={'port-dot'+(connected?' connected':'')+(selectedSource.source===node.id&&selectedSource.source_port===port&&side==='output'?' chosen':'')} style={{'--port-color':color(format)} as CSSProperties} disabled={disabled} title={side==='input'?'拖动输入圆点改接；松到空白断开':'拖动输出圆点创建连接'} aria-label={`${side==='input'?'Connect to':'Connect from'} node ${index+1} ${side} ${port}`} data-socket-node={node.id} data-socket-port={port} data-socket-side={side} onPointerDown={event=>startWire(event,socket)} onClick={event=>{if(event.detail===0){side==='input'?onTarget(node.id,port):onSource(node.id,port)}}}/></div>
              })}</div>)}
            </div>
            {renderNodeSummary&&<div className="node-summary">{renderNodeSummary(node,index)}</div>}
            <div className="node-footer"><button aria-label={`节点 ${index+1} 参数`} aria-expanded={open} onClick={()=>{setSelected([node.id]);setExpanded(ids=>open?ids.filter(id=>id!==node.id):[...ids,node.id])}}>{open?'参数 ▴':'参数 ▾'}</button>{renderNodeResult?.(node,index)}</div>
            <div className="canvas-properties" hidden={!open}>{renderNode(node,index)}</div>
          </div>
        })}
      </div>
      {!flow.nodes.length&&<div className="canvas-empty"><strong>从一个节点开始</strong><span>添加节点，或导入你的研究数据</span></div>}
      {box&&<div className="canvas-selection-box" style={{left:Math.min(box.start.x,box.end.x),top:Math.min(box.start.y,box.end.y),width:Math.abs(box.end.x-box.start.x),height:Math.abs(box.end.y-box.start.y)}}/>}
      {wire&&<div className={'canvas-wire-notice'+(wire.error?' invalid':'')}>{wire.error||(wire.original!==undefined?'松到输入圆点改接，松到空白断开':'拖到兼容端口圆点连接')}</div>}
      {placement&&<div className="canvas-wire-notice">点击画布放置「{catalog.nodes.find(node=>node.id===placement)?.name}」 · Esc 取消</div>}
      {library&&<div className="canvas-library canvas-overlay"><div className="canvas-library-title"><strong>节点库</strong><button onClick={()=>setLibrary(false)}>×</button></div><input aria-label="Search nodes" placeholder="搜索节点…" value={search} onChange={event=>setSearch(event.target.value)}/><div className="canvas-library-items">{catalog.nodes.filter(node=>(node.name+' '+node.id).toLowerCase().includes(search.toLowerCase())).map(node=><button key={node.id} disabled={disabled} onPointerDown={event=>{if(event.button!==0||disabled)return;event.preventDefault();event.stopPropagation();libraryDrag.current={type:node.id,pointer:event.pointerId,start:local(event),moved:false};stage.current?.setPointerCapture?.(event.pointerId)}} onClick={event=>{if(event.detail===0){setPlacement(node.id);setLibrary(false);stage.current?.focus()}}}><span>{node.name}</span><span>＋</span></button>)}</div></div>}
      <div className="canvas-navigation canvas-overlay"><button aria-label="选择工具" aria-pressed={tool==='select'} onClick={()=>setTool('select')}>↖</button><button aria-label="平移工具" aria-pressed={tool==='pan'} onClick={()=>setTool('pan')}>✥</button><span className="canvas-divider"/><button aria-label="缩小" onClick={()=>zoom(view.scale/1.2)}>−</button><button onClick={()=>zoom(1)}>{Math.round(view.scale*100)}%</button><button aria-label="放大" onClick={()=>zoom(view.scale*1.2)}>＋</button><button aria-label="聚焦选中" disabled={!selected.length} onClick={()=>fit(selected)}>⊡</button></div>
      {selected.length>0&&<div className="canvas-selected-actions canvas-overlay"><span>{selected.length} 个已选</span><button onClick={()=>fit(selected)}>聚焦</button>{onCopy&&<button disabled={disabled} onClick={()=>onCopy(selected)}>复制</button>}{onDelete&&<button disabled={disabled} onClick={()=>{onDelete(selected);setSelected([])}}>删除</button>}</div>}
      <svg className="canvas-minimap canvas-overlay" viewBox={`${bounds.left} ${bounds.top} ${bounds.right-bounds.left} ${bounds.bottom-bounds.top}`} aria-label="流程概览">{minimapNodes.map(node=><rect key={node.id} x={node.x} y={node.y} width={WIDTH} height={node.height} fill={selected.includes(node.id)?'#345bdb':'#a8b2c1'}/>)}</svg>
    </div>
    {notice&&<div className="canvas-status" role="status">{notice}</div>}
  </div>
}
