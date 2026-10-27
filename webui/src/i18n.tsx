import { useSyncExternalStore } from 'react'
import type { DisplayText, Locale, I18n } from '@protein-workbench/module-ui'

const preferenceKey = 'workbench.language'
export function initialLocale(storage: Pick<Storage, 'getItem'> | undefined, language: string): Locale {
  try { const saved = storage?.getItem(preferenceKey); if (saved === 'en' || saved === 'zh-CN') return saved } catch { /* Browser storage may be unavailable. */ }
  return /^zh\b/i.test(language) ? 'zh-CN' : 'en'
}
function browserStorage() { try { return globalThis.localStorage } catch { return undefined } }
let locale: Locale = initialLocale(browserStorage(), typeof navigator === 'undefined' ? 'en' : navigator.language)
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export const useLocale = () => useSyncExternalStore(subscribe, () => locale, () => 'en' as Locale)
export function setLocale(next: Locale) {
  if (next !== 'en' && next !== 'zh-CN') return
  locale = next
  try { localStorage.setItem(preferenceKey, next) } catch { /* Keep the choice for this session. */ }
  if (typeof document !== 'undefined') document.documentElement.lang = next
  listeners.forEach(listener => listener())
}
export function text(value: DisplayText | undefined, values: Record<string, unknown> = {}): string {
  const message = typeof value === 'string' ? value : value?.[locale] ?? value?.en ?? value?.['zh-CN'] ?? ''
  return message.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match)
}
export function LanguagePicker() {
  const current = useLocale()
  return <select className="language-picker" aria-label={current === 'en' ? 'Language' : '语言'} value={current} onChange={event => setLocale(event.target.value as Locale)}>
    <option value="zh-CN">中文</option><option value="en">English</option>
  </select>
}
export const i18n: I18n = { error: errorText, text, useLocale, LanguagePicker, translator: messages => (key, values) => text(messages[key] ?? key, values) }
if (typeof document !== 'undefined') document.documentElement.lang = locale

export function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'displayMessage' in error) {
    const item = error as { displayMessage: DisplayText; values?: Record<string, unknown> }
    return text(item.displayMessage, item.values)
  }
  return error instanceof Error ? error.message : String(error)
}

export function localizeCatalog(source: import('./host-client').Catalog<DisplayText>): import('./host-client').Catalog {
  return {
    ...source,
    nodes: source.nodes.map(node => ({...node, name: text(node.name),
      inputs: Object.fromEntries(Object.entries(node.inputs).map(([key, port]) => [key, {...port, name: port.name === undefined ? undefined : text(port.name)}])),
      outputs: Object.fromEntries(Object.entries(node.outputs).map(([key, port]) => [key, {...port, name: port.name === undefined ? undefined : text(port.name)}])),
      tools: Object.fromEntries(Object.entries(node.tools ?? {}).map(([key, tool]) => [key, {...tool, name: text(tool.name)}])),
    })),
    modules: source.modules.map(module => ({...module, name: text(module.name)})),
    tools: source.tools?.map(tool => ({...tool, name: text(tool.name)})),
  }
}
