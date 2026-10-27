/** Public React extension contract. Runtime React is supplied by the host. */
import type * as React from 'react'

export type Locale = 'zh-CN' | 'en'
export type DisplayText = string | { 'zh-CN'?: string; en?: string }
export type Translate = (key: string, values?: Record<string, unknown>) => string
export interface I18n {
  error(error: unknown): string
  text(value: DisplayText | undefined, values?: Record<string, unknown>): string
  translator(messages: Record<string, DisplayText>): Translate
  useLocale(): Locale
  LanguagePicker: React.ComponentType
}

export interface PackageInfo { id: string; project_id: string; format: string; entry: string; files: string[] }
export interface InputPort { name?: string; accepts: string[]; cardinality: 'one' | 'many'; required: boolean }
export interface OutputPort { format: string; cardinality: 'one' | 'many'; name?: string }
export interface Flow { nodes: FlowNode[]; edges: Edge[] }
export interface Scope {
  inputs: Record<string, InputPort>
  outputs: Record<string, OutputPort>
  body: Flow
  input_bindings: { input: string; node: string; port: string }[]
  output_bindings: { output: string; node: string; port: string }[]
  item_input?: string
  rounds?: number
  feedback?: Record<string, string>
}
export interface FlowNode { id: string; type: string; parameters: Record<string, unknown>; inputs: Record<string, string[]>; document?: string; tools?: Record<string, string>; tool_parameters?: Record<string, Record<string, unknown>>; scope?: Scope }
export interface Edge { source: string; source_port: string; target: string; target_port: string }
export interface InteractionPreview { id: string; data: unknown; outputs: string[] }
export type InteractionInput = string | { interaction: string; output: string }
export interface EditorUpdate {
  document?: { interaction: string; output: string }
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
  readonly document?: PackageInfo
  readonly inputs: Record<string, { packages: PackageInfo[]; available?: {package: PackageInfo; label: string}[]; unavailable?: string }>
  readonly host: ModuleHost
  update(change: EditorUpdate): Promise<void>
}
export interface ModuleHost {
  readonly readOnly: boolean
  createInput(input: { format: string; entry: string; files: Record<string, Blob> }): Promise<PackageInfo>
  addNode(node: Omit<FlowNode, 'id'>): Promise<string>
  connect(edge: Edge): Promise<void>
  preview(interaction: string, inputs: Record<string, InteractionInput[]>, parameters: Record<string, unknown>, options?: {signal?: AbortSignal}): Promise<InteractionPreview>
  cancelPreview(id: string): Promise<void>
  readPreviewFile(id: string, output: string, key: string, options?: {signal?: AbortSignal}): Promise<Blob>
  readFile(packageId: string, key: string): Promise<Blob>
}
export interface ModuleActionProps { host: ModuleHost }
export interface ResultActionProps { host: ModuleHost; packages: readonly PackageInfo[] }
export interface EditorProps { context: EditorContext; parameters: Record<string, unknown>; onChange(parameters: Record<string, unknown>): void; onDraftChange?(): void; onClose?(): void; readOnly: boolean }
export interface ViewerProps { package: PackageInfo; host: ModuleHost }
export interface Extensions {
  resultActions?: { id: string; name: DisplayText; component: React.ComponentType<ResultActionProps> }[]
  actions?: { id: string; name: DisplayText; component: React.ComponentType<ModuleActionProps> }[]
  editors?: { inline?: boolean; node: string; component: React.ComponentType<EditorProps>; workspace?: { title: DisplayText; openLabel?: DisplayText } }[]
  viewers?: { id: string; name: DisplayText; formats: string[]; defaultFor?: string[]; component: React.ComponentType<ViewerProps> }[]
}
export interface ModuleEntry {
  runtime: { react: 19 }
  register(runtime: { React: typeof React; i18n: I18n }): Extensions
}
