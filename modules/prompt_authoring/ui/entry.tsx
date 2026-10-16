import { useState } from 'react'
import type { PublishedPrompt } from '../../../webui/src/protocol/client'
import type { ModuleViewerProps } from '../../../webui/src/module-ui'
import '../../../webui/src/published-outputs.css'

function PromptValue({ value }: { value: PublishedPrompt }) {
  const [page, setPage] = useState(0)
  const residueIds = value.residue_ids
  const offset = page * 100
  return <section aria-label="已发布 Prompt"><p>{residueIds.length} 个残基；Mask 表示该残基没有条件，未提供整条轨道与 Mask 分别显示。</p>
    <div className="published-prompt-scroll"><table><thead><tr><th>残基身份</th><th>序列</th><th>原子坐标（Å）</th><th>二级结构（SS8）</th><th>SASA（Å²）</th></tr></thead><tbody>{residueIds.slice(offset, offset + 100).map((id, row) => {
      const index = offset + row
      const coordinates = value.coordinates[index]
      return <tr key={id}><th scope="row">{id}</th><td>{value.sequence[index] ?? 'Mask'}</td><td>{coordinates === null ? 'Mask' : <details><summary>{coordinates.atoms.length} 个原子</summary>{coordinates.atoms.map(([name, position]) => <p key={name}>{name}: ({position.join(', ')})</p>)}</details>}</td><td>{value.secondary_structure === null ? '未提供整条轨道' : value.secondary_structure[index] ?? 'Mask'}</td><td>{value.sasa === null ? '未提供整条轨道' : value.sasa[index] ?? 'Mask'}</td></tr>
    })}</tbody></table></div>
    {residueIds.length > 100 && <div className="published-pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{offset + 1}–{Math.min(offset + 100, residueIds.length)} / {residueIds.length}</span><button disabled={offset + 100 >= residueIds.length} onClick={() => setPage(page + 1)}>下一页</button></div>}
    <h4>功能注释</h4>{value.function_annotations.length === 0 ? <p>没有功能注释。</p> : <ul>{value.function_annotations.map((annotation, index) => <li key={index}>{annotation.label} · {annotation.start_residue_id} → {annotation.end_residue_id}</li>)}</ul>}
  </section>
}

function Prompt({ reading }: ModuleViewerProps) { return <PromptValue value={reading.value as PublishedPrompt} /> }
export function register() { return { Prompt } }
