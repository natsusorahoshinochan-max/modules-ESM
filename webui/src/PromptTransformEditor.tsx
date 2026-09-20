import { useEffect, useMemo, useState } from 'react'
import type { PromptAuthoringDocument, PromptCoordinatesValue, PromptRigidTransform, PromptSnapshot } from './protocol/client'

type Vec3 = [number, number, number]
type Axis = 'x' | 'y' | 'z'
type Mode = 'translate' | 'rotate'
type Props = {
  projection: Pick<PromptSnapshot, 'residues' | 'tracks'>
  selection: string[]
  document: PromptAuthoringDocument
  busy: boolean
  mode: Mode
  axis: Axis
  amount: string
  onAmount: (value: string) => void
  onMode: (mode: Mode) => void
  onAxis: (axis: Axis) => void
  onOrigin: (origin: Vec3 | undefined) => void
  onPreview: (document: PromptAuthoringDocument, title: string) => void
}

const axes: Axis[] = ['x', 'y', 'z']

export function PromptTransformEditor({ projection, selection, document, busy, mode, axis, amount, onAmount, onMode, onAxis, onOrigin, onPreview }: Props) {
  const [pivotMode, setPivotMode] = useState<'centroid' | 'residue' | 'custom'>('centroid')
  const [pivotResidue, setPivotResidue] = useState('')
  const [pivotAtom, setPivotAtom] = useState('')
  const [custom, setCustom] = useState(['0', '0', '0'])
  const coordinateRows = projection.tracks.coordinates.values
  const selected = projection.residues.filter(item => selection.includes(item.residue_handle) && item.state !== 'pending-delete')
  const coordinates = selected.map(item => coordinateRows.find(row => row.residue_handle === item.residue_handle)!.value as PromptCoordinatesValue | null)
  const hasMasked = coordinates.some(value => value === null)
  const availablePivots = projection.residues.filter(item => item.state !== 'pending-delete' && coordinateRows.some(row => row.residue_handle === item.residue_handle && row.value !== null))
  const pivot = pivotResidue ? availablePivots.find(item => item.residue_handle === pivotResidue) : availablePivots[0]
  const pivotAtoms = pivot ? (coordinateRows.find(row => row.residue_handle === pivot.residue_handle)!.value as PromptCoordinatesValue).atoms : []
  const atom = pivotAtom ? pivotAtoms.find(item => item.atom_name === pivotAtom) : pivotAtoms.find(item => item.atom_name === 'CA') ?? pivotAtoms[0]
  const centroid = useMemo(() => {
    const atoms = projection.tracks.coordinates.values.filter(row => selection.includes(row.residue_handle) && row.state !== 'pending-delete' && row.value !== null).flatMap(row => (row.value as PromptCoordinatesValue).atoms)
    if (!atoms.length) return undefined
    return axes.map((_, index) => atoms.reduce((sum, item) => sum + item.coordinates[index], 0) / atoms.length) as Vec3
  }, [projection.tracks.coordinates.values, selection])
  const origin = useMemo(() => pivotMode === 'custom' ? custom.map(Number) as Vec3 : pivotMode === 'residue' ? atom?.coordinates : centroid, [atom, centroid, custom, pivotMode])
  useEffect(() => { onOrigin(origin); return () => onOrigin(undefined) }, [onOrigin, origin])
  const current = projection.residues.filter(item => item.state !== 'pending-delete')
  const boundaries = current.flatMap((item, index) => {
    const next = current[index + 1]
    return next && item.chain_id === next.chain_id && selection.includes(item.residue_handle) !== selection.includes(next.residue_handle) ? [`${item.residue_id} ↔ ${next.residue_id}`] : []
  })
  const canPreview = !busy && selected.length > 0 && !hasMasked && Boolean(origin) && amount.trim() !== '' && (pivotMode !== 'custom' || custom.every(value => value.trim() !== ''))
  const preview = () => {
    if (!origin) return
    const rotation: PromptRigidTransform['rotation_matrix'] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    const translation: Vec3 = [0, 0, 0]
    const index = axes.indexOf(axis)
    if (mode === 'translate') translation[index] = Number(amount)
    else {
      const angle = Number(amount) * Math.PI / 180
      const first = (index + 1) % 3, second = (index + 2) % 3
      rotation[first][first] = Math.cos(angle); rotation[first][second] = -Math.sin(angle)
      rotation[second][first] = Math.sin(angle); rotation[second][second] = Math.cos(angle)
    }
    const transform: PromptRigidTransform = { rotation_matrix: rotation, origin, translation, residue_ids: selected.map(item => item.residue_id) }
    onPreview({ ...document, rigid_transforms: [...document.rigid_transforms ?? [], transform] }, `${mode === 'translate' ? '位移' : '旋转'} · 世界 ${axis.toUpperCase()} · ${amount}${mode === 'translate' ? ' Å' : '°'}`)
    onAmount('0')
  }
  return <section className="ps-editor-section" aria-label="精确刚体变换">
    <span className="ps-kicker">WORLD COORDINATES</span>
    <div className="ps-action-row"><button className={mode === 'translate' ? 'active' : ''} onClick={() => onMode('translate')}>G 位移</button><button className={mode === 'rotate' ? 'active' : ''} onClick={() => onMode('rotate')}>R 旋转</button></div>
    <div className="ps-action-row">{axes.map(item => <button key={item} className={axis === item ? 'active' : ''} onClick={() => onAxis(item)}>{item.toUpperCase()}</button>)}</div>
    <label>{mode === 'translate' ? '位移 Å' : '角度 °'}<input id="prompt-transform-amount" aria-label="变换数值" type="number" step="any" value={amount} onChange={event => onAmount(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && canPreview) { event.preventDefault(); preview(); event.currentTarget.closest<HTMLElement>('.prompt-studio')?.focus() } }} /></label>
    <label>旋转中心<select aria-label="旋转中心" value={pivotMode} onChange={event => setPivotMode(event.target.value as typeof pivotMode)}><option value="centroid">选区全部原子几何中心</option><option value="residue">明确残基与原子</option><option value="custom">自定义世界坐标</option></select></label>
    {pivotMode === 'residue' && <><select aria-label="中心残基" value={pivot?.residue_handle ?? ''} onChange={event => { setPivotResidue(event.target.value); setPivotAtom('') }}><option value="" disabled>选择现有中心残基</option>{availablePivots.map(item => <option key={item.residue_handle} value={item.residue_handle}>{item.residue_id}</option>)}</select><select aria-label="中心原子" value={atom?.atom_name ?? ''} onChange={event => setPivotAtom(event.target.value)}><option value="" disabled>选择现有中心原子</option>{pivotAtoms.map(item => <option key={item.atom_name}>{item.atom_name}</option>)}</select></>}
    {pivotMode === 'custom' && <div className="ps-vector-input">{axes.map((item, index) => <label key={item}>{item.toUpperCase()}<input aria-label={`旋转中心 ${item.toUpperCase()}`} type="number" step="any" value={custom[index]} onChange={event => setCustom(values => values.map((value, i) => i === index ? event.target.value : value))} /></label>)}</div>}
    <p className="ps-help">中心（Å）：{origin?.map(value => value.toFixed(3)).join(', ') ?? '尚无坐标'}。预览坐标变换与镜头旋转独立。</p>
    {hasMasked && <p className="ps-help">选区含 Coordinates Mask；从选区移除后才能作刚体变换。</p>}
    {boundaries.length > 0 && <p className="ps-help">边界几何可能改变：{boundaries.join('，')}。邻居保持原位。</p>}
    <button disabled={!canPreview} onClick={preview}>预览刚体变换</button>
  </section>
}
