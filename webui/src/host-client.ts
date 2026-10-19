import type { Edge, FlowNode, PackageInfo } from '@protein-workbench/module-ui'
export interface Project { id: string; name: string; flow: { nodes: FlowNode[]; edges: Edge[] }; layout: Record<string, { x: number; y: number }>; missing_modules?: string[]; running?: boolean }
export interface NodeDeclaration { id: string; module_id: string; name: string; inputs: Record<string, { accepts: string[]; cardinality: string; required: boolean }>; outputs: Record<string, { format: string; cardinality: string }>; parameters: Record<string, unknown>; tools?: Record<string, { id: string; name: string }> }
export interface ToolDeclaration { id: string; name: string; module_id: string; slot: string; parameters: Record<string, unknown>; capabilities: Record<string, unknown> }
export interface ModuleRecord { installation_id: string; ui_url: string | null; available?: boolean; load_error?: string; id: string; name: string; enabled: boolean; entry_point: string; settings: Record<string, unknown>; settings_schema: Record<string, unknown>; ui: string | null }
export interface Catalog { nodes: NodeDeclaration[]; modules: ModuleRecord[]; tools?: ToolDeclaration[] }
export interface Run { id: string; status: string; diagnostics: string[]; nodes: Record<string, { status: string; outputs: Record<string, string[]>; diagnostics: string[] }> }
async function json<T>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  const response = await fetch('/api' + path, { method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail))
  return result as T
}
export const client = {
  catalog: () => json<Catalog>('/catalog'),
  projects: () => json<Project[]>('/projects'),
  createProject: (name: string) => json<Project>('/projects', { name }),
  project: (id: string) => json<Project>(`/projects/${id}`),
  save: (project: Project) => json<Project>(`/projects/${project.id}`, { flow: project.flow, layout: project.layout }, 'PUT'),
  installPackage: async (file: File, entry_point: string) => {
    const query = new URLSearchParams({ filename: file.name, entry_point })
    const response = await fetch('/api/module-packages?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Workbench-Module-Package': 'wheel' }, body: file })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail)
    return result as ModuleRecord
  },
  install: (entry_point: string) => json<ModuleRecord>('/modules', { entry_point }),
  configure: (id: string, settings: Record<string, unknown>) => json<ModuleRecord>(`/modules/${encodeURIComponent(id)}/settings`, { settings }, 'PUT'),
  enable: (id: string, enabled: boolean) => json<ModuleRecord>(`/modules/${encodeURIComponent(id)}/enabled`, { enabled }, 'PUT'),
  uninstall: (id: string) => json(`/modules/${encodeURIComponent(id)}`, undefined, 'DELETE'),
  deleteProject: (id: string) => json(`/projects/${encodeURIComponent(id)}`, undefined, 'DELETE'),
  adopt: (target: string, packageId: string) => json<PackageInfo>(`/projects/${encodeURIComponent(target)}/adoptions`, { package_id: packageId }),
  exportUrl: (id: string) => `/api/packages/${encodeURIComponent(id)}/export.zip`,
  packages: (id: string) => json<PackageInfo[]>(`/projects/${id}/packages`),
  run: (id: string) => json<Run>(`/projects/${id}/runs`, {}),
  cancelRun: (id: string) => json<Run>(`/runs/${encodeURIComponent(id)}/cancel`, {}),
  runs: (id: string) => json<Run[]>(`/projects/${id}/runs`),
  fileUrl: (id: string, key: string) => `/api/packages/${encodeURIComponent(id)}/file?key=${encodeURIComponent(key)}`,
  readFile: async (id: string, key: string) => {
    const response = await fetch(client.fileUrl(id, key))
    if (!response.ok) throw new Error((await response.json()).detail)
    return response.blob()
  },
  createInput: async (project: string, input: { format: string; entry: string; files: Record<string, Blob> }): Promise<PackageInfo> => {
    const { upload_id } = await json<{ upload_id: string }>(`/projects/${project}/uploads`, {})
    const base = `/projects/${project}/uploads/${upload_id}`
    try {
      for (const [key, file] of Object.entries(input.files)) {
        const response = await fetch('/api' + base + '/files?key=' + encodeURIComponent(key), { method: 'PUT', body: file })
        if (!response.ok) throw new Error((await response.json()).detail)
      }
      return await json<PackageInfo>(base + '/commit', { format: input.format, entry: input.entry, files: Object.fromEntries(Object.keys(input.files).map(key => [key, key])) })
    } catch (error) {
      await json(base, undefined, 'DELETE').catch(() => {})
      throw error
    }
  },
}
