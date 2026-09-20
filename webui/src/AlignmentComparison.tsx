import { useEffect, useRef, useState } from 'react'
import * as $3Dmol from '3dmol'
import { PublicV2Client, type RunProjection } from './protocol/client'
import { alignedCoordinate, candidateDetail, locationKey, referenceKey, type AlignmentView, type CandidateView } from './result-explorer'

const client = new PublicV2Client()

function EvidenceOverlay({ alignment, candidates, run }: { alignment: AlignmentView; candidates: CandidateView[]; run: RunProjection }) {
  const container = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<$3Dmol.GLViewer | undefined>(undefined)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    let viewer: $3Dmol.GLViewer | undefined
    const subject = candidates.find((candidate) => referenceKey(candidate.reference) === referenceKey(alignment.subject))!
    const reference = candidates.find((candidate) => referenceKey(candidate.reference) === referenceKey(alignment.reference))!
    void Promise.all([candidateDetail(client, run, subject), candidateDetail(client, run, reference)]).then(([subjectDetail, referenceDetail]) => {
      if (!active) return
      setLoading(false)
      if (!subjectDetail.pdb || !referenceDetail.pdb) { setError('此对齐的精确候选缺少可显示的结构。'); return }
      viewer = viewerRef.current ?? $3Dmol.createViewer(container.current!, { backgroundColor: '#111512', antialias: true })
      viewerRef.current = viewer
      viewer.clear()
      const subjectModel = viewer.addModel(subjectDetail.pdb, 'pdb')
      for (const atom of subjectModel.selectedAtoms({})) {
        const [x, y, z] = alignedCoordinate([atom.x, atom.y, atom.z], alignment.transform)
        atom.x = x; atom.y = y; atom.z = z
      }
      viewer.addModel(referenceDetail.pdb, 'pdb')
      viewer.setStyle({ model: 0 }, { cartoon: { color: '#eab86c', opacity: 0.86 }, line: { color: '#eab86c' } })
      viewer.setStyle({ model: 1 }, { cartoon: { color: '#6dced1', opacity: 0.86 }, line: { color: '#6dced1' } })
      viewer.zoomTo(); viewer.render()
    }, (reason) => { if (active) { setLoading(false); setError(reason instanceof Error ? reason.message : JSON.stringify(reason)) } })
    return () => { active = false; viewer?.clear() }
  }, [alignment, candidates, run])
  return <><div className="alignment-viewer" ref={container} />{loading && <p>加载对齐结构…</p>}{error && <p role="alert">{error}</p>}</>
}

export function AlignmentComparison({ alignments, candidates, run }: { alignments: AlignmentView[]; candidates: CandidateView[]; run: RunProjection }) {
  const selected = new Set(candidates.map((candidate) => referenceKey(candidate.reference)))
  const available = alignments.filter((alignment) => selected.has(referenceKey(alignment.subject)) && selected.has(referenceKey(alignment.reference)))
  const [choice, setChoice] = useState('')
  const alignment = available.find((item) => locationKey(item.source) === choice) ?? available[0]
  return <section className="alignment-comparison"><h3>使用已发布证据叠加</h3>{alignment ? <>
    <label>对齐来源<select value={locationKey(alignment.source)} onChange={(event) => setChoice(event.target.value)}>{available.map((entry) => <option key={locationKey(entry.source)} value={locationKey(entry.source)}>{entry.subject.candidate_id} → {entry.reference.candidate_id} · {entry.method.contract_id} · {entry.source.node_id}/{entry.source.output_port} [{entry.source.value_index}]</option>)}</select></label>
    <p>橙色 subject：{alignment.subject.candidate_id}；青色 reference：{alignment.reference.candidate_id}。RMSD {alignment.rmsd.toPrecision(5)} Å · coverage {alignment.coverage.toPrecision(4)}</p>
    <EvidenceOverlay alignment={alignment} candidates={candidates} run={run} />
    <details><summary>精确角色、变换与来源</summary><pre>{JSON.stringify(alignment, null, 2)}</pre></details>
  </> : <p>当前勾选项之间没有已发布的精确结构对齐证据，可以并排比较。</p>}</section>
}
