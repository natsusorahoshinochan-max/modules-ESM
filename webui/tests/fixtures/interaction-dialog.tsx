import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { InteractionDialog } from '../../src/InteractionDialog'

export function Fixture() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [nested, setNested] = useState(false)
  const [backgroundKeys, setBackgroundKeys] = useState(0)
  return <main onKeyDown={() => setBackgroundKeys(count => count + 1)}>
    <button onClick={() => setOpen(true)}>打开编辑</button>
    <output aria-label="背景快捷键次数">{backgroundKeys}</output>
    {open && <InteractionDialog title="编辑" busy={busy} onClose={() => setOpen(false)}>
      <label>名称<input /></label>
      <button onClick={() => setNested(true)}>更多设置</button>
      <label><input type="checkbox" checked={busy} onChange={event => setBusy(event.target.checked)} />等待保存</label>
      <button onClick={() => setOpen(false)}>关闭</button>
      {nested && <InteractionDialog title="更多设置" onClose={() => setNested(false)}>
        <label>数值<input /></label><button onClick={() => setNested(false)}>返回编辑</button>
      </InteractionDialog>}
    </InteractionDialog>}
  </main>
}

createRoot(document.getElementById('root')!).render(<Fixture />)
