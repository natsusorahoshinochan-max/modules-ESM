import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import * as $3Dmol from '3dmol'
import type { PromptRigidTransform } from './protocol/client'
import { axisDisplacement, length, numericValue, planeDisplacement, residueMarkers, rigidTransform, rotationAmount, unit, viewBasis, worldAxes, type TransformMode, type Vec3, type ViewportPoint, type WorldAxis } from './viewport-transform'
import './structure-viewer.css'

export type ViewerResidue = { chain: string; resi: number }
export type SelectionMode = 'replace' | 'add' | 'remove'
export type StructureViewerHandle = { frameSelection(): void; frameAll(): void; startTransform(mode: TransformMode): void }
export type ViewportEdit = {
  enabled: boolean
  origin?: Vec3
  residueIds: string[]
  blockedReason?: string
  busy: boolean
  onBegin(): void
  onPreviewTransform(transform: PromptRigidTransform): Promise<boolean>
  onConfirm(): Promise<boolean>
  onCancel(): void
}
type ViewerProps = {
  ref?: Ref<StructureViewerHandle>
  pdb?: string
  selectedResidues?: ViewerResidue[]
  residueLabel?: (residue: ViewerResidue) => string
  onSelectResidue?: (residue: ViewerResidue & { toggle: boolean; range: boolean }) => void
  onSelectResidues?: (residues: ViewerResidue[], mode: SelectionMode) => void
  viewportEdit?: ViewportEdit
  pivot?: Vec3
}
type Modal = {
  mode: TransformMode; axis?: WorldAxis; origin: Vec3; ids: string[]
  basis: ReturnType<typeof viewBasis>; start: ViewportPoint; pointer: ViewportPoint
  numeric: string; direction?: Vec3; amount: number; message: string
  revision: number; valid: boolean; confirming: boolean
}
type Gesture = { kind: 'orbit' | 'pan' | 'box' | 'pick'; pointerId: number; start: ViewportPoint; last: ViewportPoint; shift: boolean; moved: boolean }
const sameResidue = (a: ViewerResidue, b: ViewerResidue) => a.chain === b.chain && a.resi === b.resi
const noSelection: ViewerResidue[] = []
const markerAtoms = (viewer: $3Dmol.GLViewer) => viewer.selectedAtoms({}).map(atom => ({ chain: atom.chain!, resi: atom.resi!, atom: atom.atom!, x: atom.x!, y: atom.y!, z: atom.z! }))

export function StructureViewer(props: ViewerProps) {
  const { pdb = '', selectedResidues = noSelection, pivot } = props
  const host = useRef<HTMLDivElement>(null), canvasHost = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<$3Dmol.GLViewer | undefined>(undefined)
  const initializedView = useRef(false)
  const latest = useRef(props)
  useEffect(() => { latest.current = props })
  const modal = useRef<Modal | undefined>(undefined)
  const gesture = useRef<Gesture | undefined>(undefined)
  const pointer = useRef<ViewportPoint | undefined>(undefined)
  const previewTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [operation, setOperation] = useState<Modal>()
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('replace')
  const selectionModeRef = useRef(selectionMode)
  const [boxTool, setBoxTool] = useState(false)
  const boxToolRef = useRef(false)
  const [box, setBox] = useState<{ start: ViewportPoint; end: ViewportPoint }>()
  const [markers, setMarkers] = useState<Array<ViewerResidue & ViewportPoint>>([])
  const [hover, setHover] = useState('')
  const [notice, setNotice] = useState('')
  const [help, setHelp] = useState(false)
  const activePivot = operation?.origin ?? pivot
  const syncModal = () => setOperation(modal.current ? { ...modal.current } : undefined)
  const setBoxMode = (active: boolean) => { boxToolRef.current = active; setBoxTool(active) }
  const project = (point: Vec3): ViewportPoint => viewerRef.current!.modelToScreen([{ x: point[0], y: point[1], z: point[2] }])[0]
  const frameAll = () => { if (modal.current) return; viewerRef.current?.zoomTo(); viewerRef.current?.render() }
  const frameSelection = () => {
    if (modal.current) return
    const selected = latest.current.selectedResidues ?? []
    if (!selected.length) { setNotice('先选择残基，再聚焦选区。'); return }
    viewerRef.current?.zoomTo({ or: selected }); viewerRef.current?.render()
  }
  const dispatchPreview = () => {
    clearTimeout(previewTimer.current)
    const current = modal.current
    if (!current || !current.direction || !current.valid) return Promise.resolve(false)
    const revision = current.revision
    const transform = rigidTransform(current.mode, current.origin, current.direction, current.amount, current.ids)
    current.message = '正在预览…'; syncModal()
    const pending = latest.current.viewportEdit!.onPreviewTransform(transform).then(valid => {
      if (modal.current === current && current.revision === revision) { current.valid = valid; current.message = valid ? 'Enter / 左键确认 · Esc / 右键取消' : '预览未通过，请调整或取消'; syncModal() }
      return valid && modal.current === current && current.revision === revision
    })
    return pending
  }
  const updateTransform = () => {
    const current = modal.current
    if (!current || current.confirming) return
    const delta = { x: current.pointer.x - current.start.x, y: current.pointer.y - current.start.y }
    current.revision += 1; current.valid = false
    const numeric = current.numeric ? numericValue(current.numeric) : undefined
    if (current.numeric && numeric === undefined) { current.message = '继续输入完整数值'; syncModal(); return }
    if (current.mode === 'translate') {
      if (current.axis) {
        current.direction = worldAxes[current.axis]
        const mouseAmount = axisDisplacement(delta, current.origin, current.direction, project)
        if (numeric === undefined && mouseAmount === undefined) { current.message = '此轴接近视线，请输入数值'; syncModal(); return }
        current.amount = numeric ?? mouseAmount!
      } else {
        const displacement = planeDisplacement(delta, current.origin, current.basis.right, current.basis.up, project)
        if (displacement && length(displacement) > 1e-8 && (!current.numeric || !current.direction)) current.direction = unit(displacement)
        if (!current.direction) { current.message = '移动鼠标建立方向，或按 X / Y / Z 选轴'; syncModal(); return }
        current.amount = numeric ?? (displacement ? length(displacement) : 0)
      }
    } else {
      current.direction = current.axis ? worldAxes[current.axis] : current.basis.normal
      const mouseAmount = rotationAmount(current.start, current.pointer, current.origin, current.direction, project)
      if (numeric === undefined && mouseAmount === undefined) { current.message = '当前角度无法由鼠标确定，请输入角度'; syncModal(); return }
      current.amount = numeric ?? mouseAmount!
    }
    current.valid = true; current.message = '预览待更新'; syncModal()
    clearTimeout(previewTimer.current)
    previewTimer.current = setTimeout(() => { void dispatchPreview() }, 90)
  }
  const cancel = () => {
    if (!modal.current) {
      const drag = gesture.current; gesture.current = undefined
      if (drag && canvasHost.current?.hasPointerCapture(drag.pointerId)) canvasHost.current.releasePointerCapture(drag.pointerId)
      setBoxMode(false); setBox(undefined); return
    }
    clearTimeout(previewTimer.current)
    modal.current = undefined; syncModal()
    latest.current.viewportEdit?.onCancel()
    host.current?.focus()
  }
  const confirm = async () => {
    const current = modal.current
    if (!current || !current.valid || current.confirming) return
    clearTimeout(previewTimer.current)
    current.confirming = true; syncModal()
    const valid = await dispatchPreview()
    if (modal.current !== current) return
    if (valid && await latest.current.viewportEdit!.onConfirm()) { modal.current = undefined; syncModal() }
    else { current.confirming = false; syncModal() }
    host.current?.focus()
  }
  const startTransform = (mode: TransformMode) => {
    const edit = latest.current.viewportEdit
    if (!edit?.enabled || modal.current) return
    if (edit.blockedReason || !edit.residueIds.length || !edit.origin || edit.busy) { setNotice(edit.blockedReason ?? '先选择有坐标的残基，并等待当前操作完成。'); return }
    const viewer = viewerRef.current
    if (!viewer || !canvasHost.current) return
    const rect = canvasHost.current.getBoundingClientRect()
    const start = pointer.current ?? { x: rect.left + window.scrollX + rect.width * 0.65, y: rect.top + window.scrollY + rect.height / 2 }
    cancel()
    edit.onBegin()
    modal.current = { mode, origin: [...edit.origin], ids: [...edit.residueIds], basis: viewBasis(viewer.getView()), start, pointer: start, numeric: '', amount: 0, message: '移动鼠标，或输入数值 / X Y Z 选轴', revision: 0, valid: false, confirming: false }
    setBoxMode(false); setNotice(''); syncModal(); host.current?.focus()
  }
  useImperativeHandle(props.ref, () => ({ frameAll, frameSelection, startTransform }))

  useEffect(() => {
    const container = canvasHost.current
    if (!container) return
    const viewer = $3Dmol.createViewer(container, { backgroundColor: '#111512', antialias: true, nomouse: true })
    viewerRef.current = viewer
    initializedView.current = false
    const revealMarkers = () => {
      if (!boxToolRef.current) return
      const rect = container.getBoundingClientRect()
      setMarkers(residueMarkers(markerAtoms(viewer)).map(marker => {
        const p: ViewportPoint = viewer.modelToScreen([{ x: marker.point[0], y: marker.point[1], z: marker.point[2] }])[0]
        return { chain: marker.chain, resi: marker.resi, x: p.x - rect.left - window.scrollX, y: p.y - rect.top - window.scrollY }
      }))
    }
    viewer.setViewChangeCallback(revealMarkers)
    const wheel = (event: WheelEvent) => { event.preventDefault(); if (!modal.current) viewer.zoom(Math.exp(-event.deltaY * 0.001)) }
    container.addEventListener('wheel', wheel, { passive: false })
    const resize = new ResizeObserver(() => { if (container.clientWidth && container.clientHeight) { viewer.resize(); viewer.render(); revealMarkers() } })
    resize.observe(container)
    return () => { clearTimeout(previewTimer.current); resize.disconnect(); container.removeEventListener('wheel', wheel); viewer.setViewChangeCallback(null); viewer.clear(); viewerRef.current = undefined; container.replaceChildren() }
  }, [])

  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    if (!pdb) { viewer.clear(); return }
    const loaded = initializedView.current
    const view = viewer.getView(), slab = viewer.getSlab()
    viewer.clear(); viewer.addModel(pdb, 'pdb')
    viewer.setStyle({}, { cartoon: { color: 'spectrum', opacity: 0.94 }, line: { color: 'spectrum' } })
    viewer.setClickable({}, true, () => undefined)
    if (loaded) { viewer.setView(view); viewer.setSlab(slab.near, slab.far) } else viewer.zoomTo()
    initializedView.current = true
    viewer.render()
  }, [pdb])

  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    viewer.setStyle({}, { cartoon: { color: 'spectrum', opacity: 0.94 }, line: { color: 'spectrum' } })
    for (const residue of selectedResidues) viewer.addStyle(residue, { stick: { color: '#f1c760' }, cartoon: { color: '#f1c760' } })
    viewer.removeAllShapes(); viewer.removeAllLabels()
    if (activePivot) viewer.addSphere({ center: { x: activePivot[0], y: activePivot[1], z: activePivot[2] }, radius: 0.45, color: '#ff6688', opacity: 0.9 })
    viewer.render()
  }, [pdb, activePivot, selectedResidues])

  useEffect(() => {
    if (!boxTool) { setMarkers([]); return }
    viewerRef.current?.render()
  }, [boxTool])

  const pick = (event: { clientX: number; clientY: number }) => {
    const viewer = viewerRef.current, rect = canvasHost.current?.getBoundingClientRect()
    if (!viewer || !rect) return undefined
    const hits: Array<{ clickable: $3Dmol.AtomSpec; distance: number }> = viewer.targetedObjects(2 * (event.clientX - rect.left) / rect.width - 1, 1 - 2 * (event.clientY - rect.top) / rect.height, {})
    return hits[0]?.clickable
  }
  const choose = (residues: ViewerResidue[], shift = false) => {
    const current = latest.current
    let mode = selectionModeRef.current
    if (shift) mode = residues.length === 1 && (current.selectedResidues ?? []).some(item => sameResidue(item, residues[0])) ? 'remove' : 'add'
    if (current.onSelectResidues) current.onSelectResidues(residues, mode)
    else if (residues[0]) current.onSelectResidue?.({ ...residues[0], toggle: shift || mode !== 'replace', range: false })
  }
  const point = (event: { pageX: number; pageY: number }): ViewportPoint => ({ x: event.pageX, y: event.pageY })
  const localPoint = (p: ViewportPoint) => { const rect = canvasHost.current!.getBoundingClientRect(); return { x: p.x - rect.left - window.scrollX, y: p.y - rect.top - window.scrollY } }
  const selectable = Boolean(props.onSelectResidues || props.onSelectResidue)
  return <div ref={host} tabIndex={0} className={`structure-viewer${pdb ? '' : ' is-empty'}`} aria-label="三维结构视口" onKeyDown={event => {
    if ((event.target as HTMLElement).matches('input,select,textarea')) return
    const key = event.key.toLowerCase()
    if (modal.current) {
      event.stopPropagation(); event.preventDefault()
      if (event.metaKey || event.ctrlKey) return
      if (key === 'escape') cancel()
      else if (key === 'enter') void confirm()
      else if (!modal.current.confirming && /^[xyz]$/.test(key)) { modal.current.axis = modal.current.axis === key ? undefined : key as WorldAxis; modal.current.direction = undefined; updateTransform() }
      else if (!modal.current.confirming && /^[0-9.-]$/.test(key)) { modal.current.numeric += key; updateTransform() }
      else if (!modal.current.confirming && key === 'backspace') { modal.current.numeric = modal.current.numeric.slice(0, -1); updateTransform() }
      return
    }
    if (event.metaKey || event.ctrlKey) return
    if (['g','r','b','escape','home','.'].includes(key)) { event.stopPropagation(); event.preventDefault() }
    if (key === 'g' || key === 'r') startTransform(key === 'g' ? 'translate' : 'rotate')
    if (key === 'b' && selectable) setBoxMode(true)
    if (key === 'escape') cancel()
    if (key === 'home') frameAll()
    if (key === '.') frameSelection()
  }}>
    <div ref={canvasHost} className="sv-canvas" onContextMenu={event => { event.preventDefault(); if (modal.current) cancel() }} onPointerDown={event => {
      event.preventDefault(); event.stopPropagation(); host.current?.focus(); pointer.current = point(event)
      if (modal.current) { if (event.button === 2) cancel(); else if (event.button === 0) void confirm(); return }
      if (event.button !== 0 && event.button !== 1) return
      const kind = event.button === 1 ? event.shiftKey ? 'pan' : 'orbit' : boxToolRef.current ? 'box' : 'pick'
      gesture.current = { kind, pointerId: event.pointerId, start: point(event), last: point(event), shift: event.shiftKey, moved: false }
      event.currentTarget.setPointerCapture(event.pointerId)
      if (kind === 'box') setBox({ start: localPoint(point(event)), end: localPoint(point(event)) })
    }} onPointerMove={event => {
      pointer.current = point(event)
      if (modal.current) { modal.current.pointer = point(event); if (!modal.current.numeric || !modal.current.direction) updateTransform(); return }
      const drag = gesture.current, viewer = viewerRef.current
      if (!drag || !viewer) {
        const atom = pick(event)
        const residue = atom ? { chain: atom.chain!, resi: atom.resi! } : undefined
        setHover(atom && residue ? `${latest.current.residueLabel?.(residue) ?? `${residue.chain}${residue.resi}`} · ${atom.resn}` : '')
        return
      }
      const p = point(event), dx = p.x - drag.last.x, dy = p.y - drag.last.y
      drag.moved ||= Math.hypot(p.x - drag.start.x, p.y - drag.start.y) > 3
      if (drag.kind === 'orbit') { viewer.rotate(dx * 0.4, 'vy'); viewer.rotate(dy * 0.4, 'vx') }
      if (drag.kind === 'pan') viewer.translateScene(dx, dy)
      if (drag.kind === 'box') setBox({ start: localPoint(drag.start), end: localPoint(p) })
      drag.last = p
    }} onPointerUp={event => {
      const drag = gesture.current; gesture.current = undefined
      if (!drag) return
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
      if (drag.kind === 'pick' && !drag.moved) { const atom = pick(event); choose(atom ? [{ chain: atom.chain!, resi: atom.resi! }] : [], drag.shift) }
      if (drag.kind === 'box') {
        const end = point(event), viewer = viewerRef.current!
        const chosen = residueMarkers(markerAtoms(viewer)).filter(marker => { const p = project(marker.point); return p.x >= Math.min(end.x, drag.start.x) && p.x <= Math.max(end.x, drag.start.x) && p.y >= Math.min(end.y, drag.start.y) && p.y <= Math.max(end.y, drag.start.y) })
        choose(chosen, drag.shift); setBox(undefined); setBoxMode(false)
      }
    }} onPointerCancel={() => { gesture.current = undefined; setBox(undefined) }} />
    {!pdb && <p className="structure-empty" role="status">没有可显示的结构坐标</p>}
    {pdb && <>
      <div className="sv-tools" onPointerDown={event => event.stopPropagation()}>
        <button disabled={!!operation} onClick={frameAll}>显示全部</button><button disabled={!!operation || !selectedResidues.length} onClick={frameSelection}>聚焦选区</button>
        {selectable && <><select aria-label="三维选择方式" disabled={!!operation} value={selectionMode} onChange={event => { const mode = event.target.value as SelectionMode; selectionModeRef.current = mode; setSelectionMode(mode) }}><option value="replace">替换选区</option><option value="add">增加选区</option><option value="remove">移除选区</option></select><button disabled={!!operation} aria-pressed={boxTool} onClick={() => { setBoxMode(!boxTool); host.current?.focus() }}>B 框选</button></>}
        {props.viewportEdit?.enabled && <><button disabled={!!operation} onClick={() => startTransform('translate')}>G 移动</button><button disabled={!!operation} onClick={() => startTransform('rotate')}>R 旋转</button></>}
        <button aria-label="视口操作帮助" aria-expanded={help} onClick={() => setHelp(!help)}>?</button>
      </div>
      {boxTool && <div className="sv-markers" aria-hidden="true">{markers.map(marker => <i key={`${marker.chain}:${marker.resi}`} style={{ left: marker.x, top: marker.y }} />)}</div>}
      {box && <div className="sv-box" style={{ left: Math.min(box.start.x, box.end.x), top: Math.min(box.start.y, box.end.y), width: Math.abs(box.start.x - box.end.x), height: Math.abs(box.start.y - box.end.y) }} />}
      <div className="sv-status" role="status">{operation ? <><strong>{operation.mode === 'translate' ? 'G 移动' : 'R 旋转'} · {operation.axis ? `世界 ${operation.axis.toUpperCase()}` : operation.mode === 'translate' ? '视平面' : '视线轴'} · {operation.numeric || operation.amount.toFixed(2)} {operation.mode === 'translate' ? 'Å' : '°'}</strong><span>{operation.message}</span><button disabled={!operation.valid || operation.confirming} onClick={() => void confirm()}>确认</button><button onClick={cancel}>取消</button></> : boxTool ? '穿透框选：CA 标记；无 CA 时为全部原子质心 · Esc 退出' : hover || notice || '中键旋转 · Shift + 中键平移 · 滚轮缩放'}</div>
      {help && <div className="sv-help">单击选择残基，Shift + 单击切换追加。B 拖框按当前选择方式操作，穿透前后结构。Home 显示全部，. 聚焦选区。G / R 开始调整；X / Y / Z 约束世界轴，再按同轴解除。数字精确输入，Backspace 修改；Enter / 左键确认，Esc / 右键取消。</div>}
    </>}
  </div>
}
