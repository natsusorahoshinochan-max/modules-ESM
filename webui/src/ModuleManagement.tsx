import { i18n, text } from './i18n'
const messages = {
  "enabled": {
    "zh-CN": "已启用",
    "en": "Enabled"
  },
  "disabled": {
    "zh-CN": "已停用",
    "en": "Disabled"
  },
  "deployment_settings": {
    "zh-CN": "部署设置",
    "en": "Deployment settings"
  },
  "no_configuration_needed": {
    "zh-CN": "无需配置",
    "en": "No configuration needed"
  },
  "save_settings": {
    "zh-CN": "保存设置",
    "en": "Save settings"
  },
  "disable": {
    "zh-CN": "停用",
    "en": "Disable"
  },
  "enable": {
    "zh-CN": "启用",
    "en": "Enable"
  },
  "uninstall": {
    "zh-CN": "卸载",
    "en": "Uninstall"
  },
  "module_file_whl": {
    "zh-CN": "模块文件 (.whl)",
    "en": "Module file (.whl)"
  },
  "entry_point": {
    "zh-CN": "入口",
    "en": "Entry point"
  },
  "installing": {
    "zh-CN": "安装中…",
    "en": "Installing…"
  },
  "install_file": {
    "zh-CN": "安装文件",
    "en": "Install file"
  },
  "load_installed_module": {
    "zh-CN": "载入已安装模块",
    "en": "Load installed module"
  },
  "no_modules_installed": {
    "zh-CN": "尚未安装模块",
    "en": "No modules installed"
  }
};
const t = i18n.translator(messages)
import { useRef, useState } from 'react'
import { client, type ModuleRecord } from './host-client'

type Props = { disabled: boolean; refresh(): Promise<void>; invalidateRefresh(): void; fail(error: unknown): void }
type Perform = (action: () => Promise<unknown>) => Promise<void>

function ModuleSettings({ module, perform }: { module: ModuleRecord; perform: Perform }) {
  const [settings, setSettings] = useState(module.settings)
  return <details><summary>{module.name} · {module.enabled ? t("enabled") : t("disabled")}</summary>
    {module.load_error && <p role="alert">{module.load_error}</p>}
    <fieldset><legend>{t("deployment_settings")}</legend>
      {Object.entries(module.settings_schema).map(([name, declaration]) => {
        const field = declaration && typeof declaration === 'object' ? declaration as Record<string, unknown> : {}
        return <label key={name}>{text((field.title ?? name) as import('@protein-workbench/module-ui').DisplayText)}
          <input aria-label={`${module.name}: ${name}`} type={field.secret ? 'password' : 'text'} autoComplete="off" value={String(settings[name] ?? '')} onChange={event => setSettings(current => ({ ...current, [name]: event.target.value }))} />
        </label>
      })}
      {!Object.keys(module.settings_schema).length && <p>{t("no_configuration_needed")}</p>}
      <button onClick={() => void perform(() => client.configure(module.id, settings))}>{t("save_settings")}</button>
      <button onClick={() => void perform(() => client.enable(module.id, !module.enabled))}>{module.enabled ? t("disable") : t("enable")}</button>
      <button onClick={() => void perform(() => client.uninstall(module.id))}>{t("uninstall")}</button>
    </fieldset>
  </details>
}

export function ModuleManagement({ modules, disabled, refresh, invalidateRefresh, fail }: Props & { modules: ModuleRecord[] }) {
  const [entry, setEntry] = useState('workbench_notes:module')
  const [file, setFile] = useState<File | null>(null)
  const [pending, setPending] = useState(false)
  const pendingNow = useRef(false)
  async function perform(action: () => Promise<unknown>) {
    if (disabled || pendingNow.current) return
    pendingNow.current = true; setPending(true); invalidateRefresh()
    try { await action(); await refresh() } catch (error) { fail(error) } finally { pendingNow.current = false; setPending(false) }
  }
  return <><fieldset disabled={disabled || pending}>
    <label>{t("module_file_whl")}<input type="file" accept=".whl" disabled={disabled || pending} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
    <label>{t("entry_point")}<input value={entry} disabled={disabled || pending} onChange={event => setEntry(event.target.value)} /></label>
    <button disabled={disabled || pending || !file} onClick={() => { if (file) void perform(() => client.installPackage(file, entry)) }}>{pending ? t("installing") : t("install_file")}</button>
    <button disabled={disabled || pending} onClick={() => void perform(() => client.install(entry))}>{t("load_installed_module")}</button>

    {modules.map(module => <ModuleSettings key={module.id + module.installation_id} module={module} perform={perform} />)}
    {!modules.length && <p>{t("no_modules_installed")}</p>}
    </fieldset>
  </>
}
