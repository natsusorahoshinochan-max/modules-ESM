import { useEffect, useRef, useState } from 'react'
import * as $3Dmol from '3dmol'
import type { CandidateResults } from './candidate-results'
import './structure-components.css'

export type StructuralComponent = { component_index: number; model_id: string; chain_id: string; label_chain_id: string; residue_number: string; insertion_code: string; residue_name: string; record: string; kind: string; atom_count: number }
export type ComponentReading = { components: StructuralComponent[]; atoms: Array<{ component_index: number; name: string; element: string; x: number; y: number; z: number }> }
const kindLabels: Record<string, string> = { protein: '蛋白', nucleic_acid: '核酸', water: '水', metal: '金属', other: '配体 / 其他组分' }
const label = (component: StructuralComponent) => `${component.residue_name} ${component.chain_id}:${component.residue_number}${component.insertion_code}`

export function StructureComponents({ results, candidateKey }: { results: CandidateResults; candidateKey: string }) {
  const [reading, setReading] = useState<ComponentReading>()
  const [error, setError] = useState('')
  const storageKey = `protein_io.components:${results.componentSelectionKey(candidateKey)}`
  const [selected, setSelected] = useState<number[]>(() => JSON.parse(sessionStorage.getItem(storageKey) ?? '[]') as number[])
  const [format, setFormat] = useState<'pdb' | 'mmcif'>('pdb')
  const [busy, setBusy] = useState(false)
  const [displayedAtoms, setDisplayedAtoms] = useState(0)
  const canvas = useRef<HTMLDivElement>(null)
  const viewer = useRef<$3Dmol.GLViewer | undefined>(undefined)
  const selectionRef = useRef(selected)
  selectionRef.current = selected
  const changeSelection = (next: number[]) => { setSelected(next); sessionStorage.setItem(storageKey, JSON.stringify(next)) }
  const latestChange = useRef(changeSelection)
  latestChange.current = changeSelection
  useEffect(() => {
    let active = true
    results.components(candidateKey).then(value => { if (active) setReading(value) }, cause => { if (active) setError(String(cause)) })
    return () => { active = false }
  }, [results, candidateKey])
  useEffect(() => {
    if (!reading || !canvas.current) return
    const element = canvas.current
    const scene = $3Dmol.createViewer(element, { backgroundColor: '#111512', antialias: true })
    viewer.current = scene
    const model = scene.addModel()
    model.addAtoms(reading.atoms.map((atom, index) => ({ x: atom.x, y: atom.y, z: atom.z, elem: atom.element, atom: atom.name, serial: index + 1, properties: { component_index: atom.component_index } })))
    scene.setStyle({}, { sphere: { scale: 0.3 } })
    scene.setClickable({}, true, (atom: $3Dmol.AtomSpec) => {
      const index = atom.properties!.component_index as number
      const current = selectionRef.current
      latestChange.current(current.includes(index) ? current.filter(item => item !== index) : [...current, index])
    })
    scene.zoomTo(); scene.render()
    setDisplayedAtoms(model.selectedAtoms({}).length)
    const resize = new ResizeObserver(() => { if (element.clientWidth && element.clientHeight) { scene.resize(); scene.render() } })
    resize.observe(element)
    return () => { resize.disconnect(); scene.clear(); viewer.current = undefined; element.replaceChildren() }
  }, [reading])
  useEffect(() => {
    const scene = viewer.current
    if (!scene) return
    scene.setStyle({}, { sphere: { scale: 0.3 } })
    scene.addStyle({ predicate: atom => selected.includes(atom.properties!.component_index as number) }, { sphere: { color: '#f1c760', scale: 0.45 } })
    scene.render()
  }, [selected, reading])
  const download = async () => {
    setBusy(true); setError('')
    try {
      const value = await results.exportComponents(candidateKey, selected, format)
      if (!value) return
      const url = URL.createObjectURL(new Blob([value.text], { type: format === 'pdb' ? 'chemical/x-pdb' : 'chemical/x-mmcif' }))
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `components.${format === 'pdb' ? 'pdb' : 'cif'}`; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) { setError(String(cause)) }
    finally { setBusy(false) }
  }
  return <section className="structure-components" aria-label="结构组分">
    <h4>结构组分</h4><p>所有原子按元素显示；金色为已选组分。点击原子或勾选列表选择，原结构保持不变。</p>
    {error && <p role="alert">{error}</p>}
    {!reading ? <p>正在读取组分…</p> : <>
      <div ref={canvas} className="component-viewport" aria-label="结构组分视口" />
      <p role="status" aria-label="结构组分显示">显示 {displayedAtoms} 个原子 · 已选 {reading.atoms.filter(atom => selected.includes(atom.component_index)).length} 个原子</p>
      <div className="component-actions"><button onClick={() => { viewer.current?.zoomTo(); viewer.current?.render() }}>显示全部组分</button><button disabled={!selected.length} onClick={() => { viewer.current?.zoomTo({ predicate: atom => selected.includes(atom.properties!.component_index as number) }); viewer.current?.render() }}>聚焦所选组分</button><button onClick={() => changeSelection(reading.components.map(component => component.component_index))}>选择全部组分</button><button onClick={() => changeSelection([])}>清空组分选择</button></div>
      <div className="component-list"><table><thead><tr><th>选择</th><th>组分</th><th>类别</th><th>残基编号</th><th>插入码</th><th>模型</th><th>原子数</th></tr></thead><tbody>{reading.components.map(component => <tr key={component.component_index}><td><input type="checkbox" aria-label={`选择组分 ${label(component)}`} checked={selected.includes(component.component_index)} onChange={event => changeSelection(event.target.checked ? [...selected, component.component_index] : selected.filter(index => index !== component.component_index))} /></td><td>{label(component)}{component.label_chain_id !== component.chain_id && <small>label chain: {component.label_chain_id}</small>}</td><td>{kindLabels[component.kind]}</td><td>{component.residue_number}</td><td>{component.insertion_code || "—"}</td><td>{component.model_id}</td><td>{component.atom_count}</td></tr>)}</tbody></table></div>
      <div className="component-actions"><label>组分导出格式<select aria-label="组分导出格式" value={format} onChange={event => setFormat(event.target.value as 'pdb' | 'mmcif')} disabled={busy}><option value="pdb">PDB</option><option value="mmcif">mmCIF</option></select></label><button disabled={!selected.length || busy} onClick={() => void download()}>导出所选组分</button></div>
    </>}
  </section>
}
