import { useEffect, useState } from 'react'
import { InteractionDialog } from './InteractionDialog'
import { workspaceErrorMessage } from './project-workspace'
import type { ModuleSettingsProjection, PublicV2Client } from './protocol/client'

export function ModuleSettings({ api, onClose }: { api: PublicV2Client; onClose: () => void }) {
  const [settings, setSettings] = useState<ModuleSettingsProjection>()
  const [selected, setSelected] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [clear, setClear] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    let active = true
    void api.moduleSettings().then(value => { if (active) setSettings(value) }, reason => { if (active) setError(workspaceErrorMessage(reason)) })
    return () => { active = false }
  }, [api])
  const binding = settings?.bindings.find(item => item.binding_id === selected)
  const choose = (id: string) => {
    const entry = settings?.bindings.find(item => item.binding_id === id)
    setSelected(id); setClear([]); setSaved(false); setError('')
    setValues(Object.fromEntries(entry?.fields.map(field => [field.name, field.name in entry.values ? field.value_category === 'json_value' ? JSON.stringify(entry.values[field.name]) : String(entry.values[field.name]) : '']) ?? []))
  }
  const save = async () => {
    if (!binding) return
    setBusy(true); setError(''); setSaved(false)
    try {
      const updates: Record<string, unknown> = {}
      for (const field of binding.fields) {
        const text = values[field.name] ?? ''
        if (clear.includes(field.name)) updates[field.name] = null
        else if (field.value_category === 'credential_handle' && !text) continue
        else updates[field.name] = text === '' ? null : field.value_category === 'json_value' ? JSON.parse(text) as unknown : text
      }
      setSettings(await api.updateModuleSettings(selected, updates))
      setValues(current => Object.fromEntries(Object.entries(current).map(([name, value]) => [name, binding.fields.find(field => field.name === name)?.value_category === 'credential_handle' ? '' : value])))
      setClear([]); setSaved(true)
    } catch (reason) { setError(workspaceErrorMessage(reason)) } finally { setBusy(false) }
  }
  return <InteractionDialog title="模块运行设置" busy={busy} onClose={onClose}>
    <p>设置由模块声明，适用于此应用安装。路径须能由后端访问；计算参数仍在节点中编辑。运行期间不能保存设置。</p>
    {error && <p role="alert">{error}</p>}
    <label>运行路线<select aria-label="运行路线" value={selected} disabled={busy} onChange={event => choose(event.target.value)}><option value="">选择路线</option>{settings?.bindings.map(entry => <option key={entry.binding_id} value={entry.binding_id}>{entry.package_id} / {entry.binding_id}</option>)}</select></label>
    {binding?.fields.map(field => <div key={field.name}>
      <label>{field.name}<input aria-label={field.name} type={field.value_category === 'credential_handle' ? 'password' : 'text'} autoComplete="off" value={values[field.name] ?? ''} disabled={busy || clear.includes(field.name)} placeholder={field.value_category === 'credential_handle' && binding.configured_secrets.includes(field.name) ? '已设置；留空保留' : ''} onChange={event => { setValues(current => ({ ...current, [field.name]: event.target.value })); setSaved(false) }} /></label>
      {field.value_category === 'credential_handle' && <label><input type="checkbox" checked={clear.includes(field.name)} disabled={busy} onChange={event => setClear(current => event.target.checked ? [...current, field.name] : current.filter(name => name !== field.name))} />清除 {field.name}</label>}
      {field.value_category === 'json_value' && <small>JSON 值；文本使用双引号。</small>}
    </div>)}
    {saved && <p role="status">设置已保存</p>}
    <footer><button disabled={busy || !binding} onClick={() => void save()}>保存设置</button><button disabled={busy} onClick={onClose}>取消</button></footer>
  </InteractionDialog>
}
