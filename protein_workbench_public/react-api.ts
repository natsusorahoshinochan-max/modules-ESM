/** Public React extension contract. Runtime React is supplied by the host. */
import type * as React from 'react'

export interface PackageInfo { id: string; project_id: string; format: string; entry: string; files: string[] }
export interface FlowNode { id: string; type: string; parameters: Record<string, unknown>; inputs: Record<string, string[]> }
export interface Edge { source: string; source_port: string; target: string; target_port: string }
export interface ModuleHost {
  readonly readOnly: boolean
  createInput(input: { format: string; entry: string; files: Record<string, Blob> }): Promise<PackageInfo>
  addNode(node: Omit<FlowNode, 'id'>): Promise<string>
  connect(edge: Edge): Promise<void>
  readFile(packageId: string, key: string): Promise<Blob>
}
export interface ModuleActionProps { host: ModuleHost }
export interface EditorProps { parameters: Record<string, unknown>; onChange(parameters: Record<string, unknown>): void; readOnly: boolean }
export interface ViewerProps { package: PackageInfo; host: ModuleHost }
export interface Extensions {
  actions?: { id: string; name: string; component: React.ComponentType<ModuleActionProps> }[]
  editors?: { node: string; component: React.ComponentType<EditorProps> }[]
  viewers?: { id: string; name: string; formats: string[]; component: React.ComponentType<ViewerProps> }[]
}
export interface ModuleEntry {
  runtime: { react: 19 }
  register(runtime: { React: typeof React }): Extensions
}
