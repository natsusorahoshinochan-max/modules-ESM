import { useState } from 'react'
import { client, type ModuleRecord } from './host-client'

type Props = { disabled: boolean; refresh(): Promise<void>; fail(error: unknown): void }

function ModuleSettings({ module, disabled, refresh, fail }: Props & { module: ModuleRecord }) {
  const [settings, setSettings] = useState(module.settings)
  const [pending, setPending] = useState(false)
  async function perform(action: () => Promise<unknown>) {
    setPending(true)
    try { await action(); await refresh() } catch (error) { fail(error) } finally { setPending(false) }
  }
  return <details><summary>{module.name} · {module.enabled ? 'enabled' : 'disabled'}</summary>
    <p>{module.entry_point}</p>{module.load_error && <p role="alert">{module.load_error}</p>}
    <fieldset disabled={disabled || pending}><legend>Deployment settings</legend>
      {Object.entries(module.settings_schema).map(([name, declaration]) => {
        const field = declaration && typeof declaration === 'object' ? declaration as Record<string, unknown> : {}
        return <label key={name}>{String(field.title ?? name)}{typeof declaration === 'string' && <small>{declaration}</small>}
          <input aria-label={`${module.name}: ${name}`} type={field.secret ? 'password' : 'text'} autoComplete="off" value={String(settings[name] ?? '')} onChange={event => setSettings(current => ({ ...current, [name]: event.target.value }))} />
        </label>
      })}
      {!Object.keys(module.settings_schema).length && <p>No deployment settings declared.</p>}
      <button onClick={() => void perform(() => client.configure(module.id, settings))}>Save settings</button>
      <button onClick={() => void perform(() => client.enable(module.id, !module.enabled))}>{module.enabled ? 'Disable' : 'Enable'}</button>
      <button onClick={() => void perform(() => client.uninstall(module.id))}>Uninstall</button>
    </fieldset>
  </details>
}

export function ModuleManagement({ modules, disabled, refresh, fail }: Props & { modules: ModuleRecord[] }) {
  const [entry, setEntry] = useState('workbench_notes:module')
  const [file, setFile] = useState<File | null>(null)
  const [pending, setPending] = useState(false)
  async function install() {
    if (!file) return
    setPending(true)
    try { await client.installPackage(file, entry); await refresh() } catch (error) { fail(error) } finally { setPending(false) }
  }
  return <><h2>Modules</h2><p>Choose a module wheel. Its Python dependencies must already be installed in the server environment.</p>
    <label>Module package<input type="file" accept=".whl" disabled={disabled || pending} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
    <label>Entry point<input value={entry} disabled={disabled || pending} onChange={event => setEntry(event.target.value)} /></label>
    <button disabled={disabled || pending || !file} onClick={() => void install()}>{pending ? 'Installing…' : 'Install package'}</button>
    <button disabled={disabled || pending} onClick={() => client.install(entry).then(refresh).catch(fail)}>Register module</button>
    <p>Register module uses a package already installed in the server environment.</p>
    {modules.map(module => <ModuleSettings key={module.id} module={module} disabled={disabled || pending} refresh={refresh} fail={fail} />)}
    {!modules.length && <p>No modules enabled. Projects and canvas are available.</p>}
  </>
}
