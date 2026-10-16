import { useEffect, useState } from 'react'
import { InteractionDialog } from './InteractionDialog'
import { workspaceErrorMessage } from './project-workspace'
import type { ModuleInventory, PublicV2Client } from './protocol/client'

export function ModuleManager({ api, beforeChange, onActivated, onClose }: {
  api: PublicV2Client
  beforeChange: () => Promise<boolean>
  onActivated: () => void
  onClose: () => void
}) {
  const [inventory, setInventory] = useState<ModuleInventory>()
  const [enabled, setEnabled] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let current = true
    void api.modules().then(value => {
      if (current) { setInventory(value); setEnabled(value.modules.filter(module => module.enabled).map(module => module.package_id)) }
    }, reason => { if (current) setError(workspaceErrorMessage(reason)) })
    return () => { current = false }
  }, [api])
  const change = async (action: () => Promise<ModuleInventory>) => {
    setBusy(true); setError('')
    try {
      if (!await beforeChange()) return
      await action()
      onActivated()
    } catch (reason) { setError(workspaceErrorMessage(reason)) } finally { setBusy(false) }
  }
  return <InteractionDialog title="模块管理" busy={busy} onClose={onClose}>
    <p>安装模块以添加节点和专用界面。更改模块不会删除项目、输入或运行结果。运行期间不能更改模块。</p>
    {error && <p role="alert">{error}</p>}
    <label>选择模块包（.whl）<input aria-label="选择模块包" type="file" accept=".whl" disabled={busy} onChange={event => {
      const file = event.target.files?.[0]
      event.target.value = ''
      if (file) void change(async () => {
        const bytes = new Uint8Array(await file.arrayBuffer())
        let binary = ''
        for (const byte of bytes) binary += String.fromCharCode(byte)
        return api.installModule(file.name, btoa(binary))
      })
    }} /></label>
    {inventory ? <>
      <h3>已安装模块</h3>
      {inventory.modules.length === 0 && <p>尚未安装模块。载体仍可创建、打开和保存项目。</p>}
      {inventory.modules.map(module => <div key={module.package_id}>
        <label><input type="checkbox" aria-label={`启用 ${module.package_id}`} checked={enabled.includes(module.package_id)} disabled={busy} onChange={event => setEnabled(current => event.target.checked ? [...current, module.package_id] : current.filter(id => id !== module.package_id))} />{module.package_id}（{module.origin === 'bundled' ? '随附' : '外部'}）</label>
        <button disabled={busy} onClick={() => void change(() => api.uninstallModule(module.package_id))}>卸载 {module.package_id}</button>
      </div>)}
      <button disabled={busy} onClick={() => setEnabled([])}>取消全部启用</button>
      <button disabled={busy} onClick={() => void change(() => api.setEnabledModules(enabled))}>应用启用状态</button>
      {inventory.bundled_packages.length > 0 && <><h3>可安装的随附模块</h3>{inventory.bundled_packages.map(module => <button key={module.package_id} disabled={busy} onClick={() => void change(() => api.installBundledModule(module.package_id))}>安装 {module.package_id}</button>)}</>}
    </> : <p role="status">正在读取模块…</p>}
    <footer><button disabled={busy} onClick={onClose}>关闭</button></footer>
  </InteractionDialog>
}
