import { useState } from 'react'
import type { ModuleViewerProps } from '../../../webui/src/module-ui'

type Representation = {
  sequence: string
  residue_ids: string[] | null
  mean_embedding?: number[] | null
  sequence_logits?: number[][] | null
}

function ESMCValues({ reading }: ModuleViewerProps) {
  const value = reading.value as Representation
  const [position, setPosition] = useState(1)
  const selected = Math.min(position, value.sequence.length)
  const row = value.sequence_logits?.[selected - 1]
  return <section aria-label="ESMC 数值">
    <h3>整序列 embedding</h3>
    {value.mean_embedding ? <pre>{JSON.stringify(value.mean_embedding)}</pre> : <p>未获取 embedding</p>}
    <h3>逐位置 logits（非概率）</h3>
    {value.sequence_logits ? <>
      <label>序列位置<input aria-label="序列位置" type="number" min={1} max={value.sequence.length} value={selected}
        onChange={event => { const next = Number(event.target.value); if (Number.isInteger(next) && next >= 1 && next <= value.sequence.length) setPosition(next) }} /></label>
      <p>位置 {selected} · {value.sequence[selected - 1]}{value.residue_ids ? ` · ${value.residue_ids[selected - 1]}` : ''}</p>
      <table><thead><tr><th>模型类别索引</th><th>logit</th></tr></thead><tbody>
        {row?.map((logit, index) => <tr key={index}><td>{index}</td><td>{logit}</td></tr>)}
      </tbody></table>
    </> : <p>未获取实际 logits</p>}
  </section>
}
export function register() { return { ESMCValues } }
