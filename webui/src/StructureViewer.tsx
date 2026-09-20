import { useEffect, useRef } from 'react'
import * as $3Dmol from '3dmol'

const noSelectedResidues: Array<{ chain: string; resi: number }> = []
type ViewerProps = {
  pdb?: string
  selectedResidues?: Array<{ chain: string; resi: number }>
  onSelectResidue?: (residue: { chain: string; resi: number; toggle: boolean; range: boolean }) => void
  pivot?: [number, number, number]
}

export function StructureViewer({ pdb = '', selectedResidues = noSelectedResidues, onSelectResidue, pivot }: ViewerProps) {
  const ref = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<ReturnType<typeof $3Dmol.createViewer> | undefined>(undefined)
  const selectHandler = useRef(onSelectResidue)
  useEffect(() => { selectHandler.current = onSelectResidue }, [onSelectResidue])

  useEffect(() => {
    if (!ref.current) return
    if (!pdb) { viewerRef.current?.clear(); return }
    const viewer = viewerRef.current ?? $3Dmol.createViewer(ref.current, { backgroundColor: '#111512', antialias: true })
    viewerRef.current = viewer
    viewer.clear()
    viewer.addModel(pdb, 'pdb')
    viewer.setStyle({}, { cartoon: { color: 'spectrum', opacity: 0.94 }, line: { color: 'spectrum' } })
    viewer.setClickable({}, true, (atom, _viewer, event) => selectHandler.current?.({ chain: atom.chain, resi: atom.resi, toggle: event.ctrlKey || event.metaKey, range: event.shiftKey }))
    viewer.zoomTo()
    viewer.render()
  }, [pdb])

  useEffect(() => () => { viewerRef.current?.clear() }, [])

  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    viewer.setStyle({}, { cartoon: { color: 'spectrum', opacity: 0.94 }, line: { color: 'spectrum' } })
    for (const residue of selectedResidues) viewer.addStyle({ chain: residue.chain, resi: residue.resi }, { stick: { color: '#f1c760' }, cartoon: { color: '#f1c760' } })
    viewer.removeAllShapes()
    viewer.removeAllLabels()
    if (pivot) {
      const position = { x: pivot[0], y: pivot[1], z: pivot[2] }
      viewer.addSphere({ center: position, radius: 0.45, color: '#ff6688', opacity: 0.9 })
      viewer.addLabel('Rotation center', { position, fontSize: 11, backgroundOpacity: 0.5 })
    }
    viewer.render()
  }, [pdb, pivot, selectedResidues])

  return <div className={`structure-viewer${pdb ? '' : ' is-empty'}`} ref={ref}>{!pdb && <p className="structure-empty" role="status">没有可显示的结构坐标</p>}</div>
}
