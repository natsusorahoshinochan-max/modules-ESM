/** Public React extension contract. Runtime React is supplied by the host. */
import type * as React from 'react'

export interface PackageInfo { id: string; project_id: string; format: string; entry: string; files: string[] }
export interface FlowNode { id: string; type: string; parameters: Record<string, unknown>; inputs: Record<string, string[]>; tools?: Record<string, string>; tool_parameters?: Record<string, Record<string, unknown>> }
export interface Edge { source: string; source_port: string; target: string; target_port: string }
export interface InteractionPreview { id: string; data: unknown; outputs: string[] }
export interface EditorUpdate {
  parameters?: Record<string, unknown>
  inputs?: Record<string, string[]>
  replaceConnections?: string[]
  connections?: Edge[]
  delivery?: { interaction: string; output: string; port: string } | { input: {format: string; entry: string; files: Record<string, Blob>}; port: string }
}
export interface EditorContext {
  readonly projectId: string
  readonly nodeId: string
  readonly revision: number
  readonly parameters: Record<string, unknown>
  readonly bindings: Record<string, string[]>
  readonly edges: Edge[]
  readonly inputs: Record<string, { packages: PackageInfo[]; unavailable?: string }>
  readonly host: ModuleHost
  update(change: EditorUpdate): Promise<void>
}
export interface ModuleHost {
  readonly readOnly: boolean
  createInput(input: { format: string; entry: string; files: Record<string, Blob> }): Promise<PackageInfo>
  addNode(node: Omit<FlowNode, 'id'>): Promise<string>
  connect(edge: Edge): Promise<void>
  preview(interaction: string, inputs: Record<string, string[]>, parameters: Record<string, unknown>, options?: {signal?: AbortSignal}): Promise<InteractionPreview>
  cancelPreview(id: string): Promise<void>
  readPreviewFile(id: string, output: string, key: string): Promise<Blob>
  readFile(packageId: string, key: string): Promise<Blob>
}
export interface ModuleActionProps { host: ModuleHost }
export interface EditorProps { context: EditorContext; parameters: Record<string, unknown>; onChange(parameters: Record<string, unknown>): void; readOnly: boolean }
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
