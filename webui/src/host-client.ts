import type { Flow, PackageInfo, InteractionPreview } from '@protein-workbench/module-ui'
export interface Project { id: string; name: string; tutorial?: boolean; flow: Flow; layout: Record<string, { x: number; y: number }>; missing_modules?: string[]; running?: boolean }
export interface NodeDeclaration { id: string; module_id: string; name: string; inputs: Record<string, { accepts: string[]; cardinality: string; required: boolean }>; outputs: Record<string, { format: string; cardinality: string }>; parameters: Record<string, unknown>; tools?: Record<string, { id: string; name: string }> }
export interface ToolDeclaration { id: string; name: string; module_id: string; slot: string; parameters: Record<string, unknown>; capabilities: Record<string, unknown> }
export interface ModuleRecord { installation_id: string; ui_url: string | null; available?: boolean; load_error?: string; id: string; name: string; enabled: boolean; entry_point: string; settings: Record<string, unknown>; settings_schema: Record<string, unknown>; ui: string | null }
export interface Catalog { nodes: NodeDeclaration[]; modules: ModuleRecord[]; tools?: ToolDeclaration[] }
export interface RunNode { status: string; outputs: Record<string, string[]>; diagnostics: string[]; kind?: 'node' | 'scope'; location?: { parent_scope: string; node_id: string; round?: number; item?: number } }
export interface Run { id: string; status: string; diagnostics: string[]; flow?: Flow; calls?: Record<string, unknown>; nodes: Record<string, RunNode>; scopes?: Record<string, { iterations: { index: number; nodes: Record<string, string> }[] }> }
async function json<T>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST', keepalive = false): Promise<T> {
  const response = await fetch('/api' + path, { method, keepalive, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail))
  return result as T
}
function receivedProject(project: Project): Project {
  function flowDefaults(flow: Flow): Flow {
    return {...flow, edges: flow.edges ?? [], nodes: (flow.nodes ?? []).map(node => ({
      ...node, parameters: node.parameters ?? {}, inputs: node.inputs ?? {},
      ...(node.scope ? {scope: {...node.scope,
        inputs: Object.fromEntries(Object.entries(node.scope.inputs ?? {}).map(([name, port]) => [name, {...port, cardinality: port.cardinality ?? 'one', required: port.required ?? true}])),
        outputs: Object.fromEntries(Object.entries(node.scope.outputs ?? {}).map(([name, port]) => [name, {...port, cardinality: port.cardinality ?? 'one'}])),
        input_bindings: node.scope.input_bindings ?? [], output_bindings: node.scope.output_bindings ?? [],
        body: flowDefaults(node.scope.body ?? {nodes: [], edges: []}),
      }} : {}),
    }))}
  }
  return {...project, flow: flowDefaults(project.flow)}
}
const projectJson = (path: string, body?: unknown, method?: string) => json<Project>(path, body, method).then(receivedProject)
export const client = {
  beginInteraction: (project: string, interaction: string, inputs: Record<string, string[]>, parameters: Record<string, unknown>) => json<{id:string}>(`/projects/${encodeURIComponent(project)}/interactions`, {interaction, inputs, parameters}),
  executeInteraction: (id: string) => json<InteractionPreview>(`/interactions/${encodeURIComponent(id)}/execute`, {}),
  readPreviewFile: async (id: string, output: string, key: string, options?: {signal?: AbortSignal}) => {
    const query = new URLSearchParams({output, key})
    const response = await fetch(`/api/interactions/${encodeURIComponent(id)}/file?${query}`, {signal:options?.signal})
    if (!response.ok) throw new Error((await response.json()).detail)
    return response.blob()
  },
  cancelInteraction: (id: string) => json(`/interactions/${encodeURIComponent(id)}`, undefined, 'DELETE', true),
  acceptInteraction: (id: string, output: string) => json<PackageInfo>(`/interactions/${encodeURIComponent(id)}/accept`, {output}),
  tutorial: () => projectJson('/tutorial'),
  copy: (project: Project, name: string, inputPackages: string[] = []) => projectJson(`/projects/${project.id}/copies`, { name, flow: project.flow, layout: project.layout, ...(inputPackages.length ? { input_packages: inputPackages } : {}) }),
  discardDraftInput: (id: string) => json(`/draft-inputs/${encodeURIComponent(id)}`, undefined, 'DELETE', true),
  catalog: () => json<Catalog>('/catalog'),
  projects: () => json<Project[]>('/projects').then(projects => projects.map(receivedProject)),
  createProject: (name: string) => projectJson('/projects', { name }),
  project: (id: string) => projectJson(`/projects/${id}`),
  save: (project: Project) => projectJson(`/projects/${project.id}`, { flow: project.flow, layout: project.layout }, 'PUT'),
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
  continueRun: (run: string, node: string) => json<Run>(`/runs/${encodeURIComponent(run)}/nodes/${encodeURIComponent(node)}/continue`, undefined, 'POST'),
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
