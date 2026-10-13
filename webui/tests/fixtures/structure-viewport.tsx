import { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { StructureViewer, type ViewerResidue } from '../../src/StructureViewer'
import type { PromptRigidTransform } from '../../src/protocol/client'

const pdb = `ATOM      1  CA  ALA A   1      -3.000  -2.000   0.000  1.00 20.00           C
ATOM      2  CA  GLY A   2       0.000   2.000   1.000  1.00 20.00           C
ATOM      3  N   SER A   3       3.000  -1.000  -1.000  1.00 20.00           N
ATOM      4  C   SER A   3       4.000   0.000  -1.000  1.00 20.00           C
END
`

export function Fixture() {
  const [version, setVersion] = useState(0)
  const [delay, setDelay] = useState(false)
  const release = useRef<(() => void) | undefined>(undefined)
  const [waiting, setWaiting] = useState(false)
  const [selected, setSelected] = useState<ViewerResidue[]>([])
  const [commits, setCommits] = useState<PromptRigidTransform[]>([])
  const [cancelled, setCancelled] = useState(0)
  const preview = useRef<PromptRigidTransform | undefined>(undefined)
  return <>
    <StructureViewer pdb={`${pdb}REMARK ${version}\n`} selectedResidues={selected} onSelectResidues={(picked, mode) => setSelected(current => mode === 'replace' ? picked : mode === 'remove' ? current.filter(item => !picked.some(candidate => candidate.chain === item.chain && candidate.resi === item.resi)) : [...new Map([...current, ...picked].map(item => [`${item.chain}:${item.resi}`, item])).values()])}
      viewportEdit={{ enabled: true, busy: false, origin: [0, 0, 0], residueIds: selected.map(item => `${item.chain}${item.resi}`), onBegin: () => { preview.current = undefined }, onPreviewTransform: async transform => { preview.current = transform; if (delay) { setWaiting(true); await new Promise<void>(resolve => { release.current = resolve }); setWaiting(false) }; return true }, onConfirm: async () => { if (!preview.current) return false; setCommits(current => [...current, preview.current!]); return true }, onCancel: () => { preview.current = undefined; setCancelled(count => count + 1) } }} />
    <button onClick={() => setVersion(value => value + 1)}>刷新模型</button>
    <label><input type="checkbox" checked={delay} onChange={event => setDelay(event.target.checked)} />延迟预览</label>
    <button disabled={!waiting} onClick={() => release.current?.()}>完成预览响应</button>
    <output aria-label="模型版本">{version}</output>
    <output aria-label="选中残基">{selected.map(item => `${item.chain}${item.resi}`).join(',')}</output>
    <output aria-label="已确认变换">{JSON.stringify(commits)}</output>
    <output aria-label="取消次数">{cancelled}</output>
  </>
}

createRoot(document.getElementById('root')!).render(<Fixture />)
