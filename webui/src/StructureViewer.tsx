import { useEffect, useRef } from 'react'
import * as $3Dmol from '3dmol'

const noSelectedResidues: Array<{ chain: string; resi: number }> = []

export function StructureViewer({ pdb = '', selectedResidues = noSelectedResidues, onSelectResidue }: { pdb?: string; selectedResidues?: Array<{ chain: string; resi: number }>; onSelectResidue?: (residue: { chain: string; resi: number }) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<ReturnType<typeof $3Dmol.createViewer> | undefined>(undefined)
  const selectHandler = useRef(onSelectResidue)
  const selectedRef = useRef(selectedResidues)

  useEffect(() => { selectHandler.current = onSelectResidue }, [onSelectResidue])
  useEffect(() => { selectedRef.current = selectedResidues }, [selectedResidues])

  useEffect(() => {
    if (!ref.current) return
    const viewer = $3Dmol.createViewer(ref.current, { backgroundColor: '#111512', antialias: true })
    viewerRef.current = viewer
    const load = pdb ? Promise.resolve(pdb) : fetch('/3GB1.pdb').then((response) => response.text())
    void load.then((value) => {
      viewer.addModel(value, 'pdb')
      viewer.setStyle({}, { cartoon: { color: 'spectrum', opacity: 0.94 } })
      for (const residue of selectedRef.current) viewer.addStyle({ chain: residue.chain, resi: residue.resi }, { stick: { color: '#f1c760' }, cartoon: { color: '#f1c760' } })
      const interactiveViewer = viewer as typeof viewer & { setClickable: (selection: object, clickable: boolean, callback: (atom: { chain: string; resi: number }) => void) => void }
      interactiveViewer.setClickable({}, true, (atom) => selectHandler.current?.({ chain: atom.chain, resi: atom.resi }))
      viewer.zoomTo()
      viewer.render()
    })
    return () => { viewer.clear(); viewerRef.current = undefined }
  }, [pdb])

  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    viewer.setStyle({}, { cartoon: { color: 'spectrum', opacity: 0.94 } })
    for (const residue of selectedResidues) viewer.addStyle({ chain: residue.chain, resi: residue.resi }, { stick: { color: '#f1c760' }, cartoon: { color: '#f1c760' } })
    viewer.render()
  }, [selectedResidues])

  return <div className="structure-viewer" ref={ref} />
}
