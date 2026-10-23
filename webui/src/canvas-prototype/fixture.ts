// Throwaway presentation fixtures copied from local module declarations.
// No runtime discovery or scientific execution is performed by this prototype.
export type Point = { x: number; y: number }
export type Port = { key: string; label: string; format: string; color: string; accepts?: string[] }
export type Field = { key: string; type: 'text' | 'number' | 'boolean' | 'readonly'; value: string; min?: number; max?: number; step?: number; advanced?: boolean }
export type Tool = { id: string; name: string; hint: string; fields: Field[] }
export type Kind = { type: string; title: string; category: string; inputs: Port[]; outputs: Port[]; fields: Field[]; tools?: Tool[] }
export type CanvasNode = { id: string; kind: string; position: Point; fields: Record<string, string>; tool?: string; bindings?: Record<number, string> }
export type CanvasEdge = { source: string; output: number; target: string; input: number }
export type Graph = { nodes: CanvasNode[]; edges: CanvasEdge[] }
const port = (key: string, label: string, format: string, color: string, accepts?: string[]): Port => ({ key, label, format, color, accepts })
const sequence = (key = 'sequence') => port(key, '序列', 'workbench.sequence', '#e9bd70')
const generation = () => port('generated', '生成结果', 'workbench.esm3_generation', '#c5a1df')
const prediction = (key = 'structure') => port(key, '预测结构', 'workbench.prediction', '#8bb8ed')
const conditions = (key: string, accepts?: string[]) => port(key, '序列与条件', 'workbench.sequence_conditions', '#79c5b4', accepts)
const number = (key: string, value: string, min: number, advanced = false, max?: number, step = 1): Field => ({ key, type: 'number', value, min, max, step, advanced })
const bool = (key: string, value: boolean, advanced = false): Field => ({ key, type: 'boolean', value: String(value), advanced })
export const kinds: Kind[] = [
  { type: 'workbench.edit_sequence', title: '编辑序列与条件', category: '序列与条件编辑',
    inputs: [port('source', '序列', 'workbench.sequence', '#e9bd70', ['workbench.sequence', 'workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.sequence_conditions'])], outputs: [conditions('edited')],
    fields: [{ key: '长度', type: 'readonly', value: '76 aa' }, { key: '可变区域', type: 'text', value: 'A: 24–35' }] },
  { type: 'workbench.complete_sequence', title: '条件序列生成', category: '生成与设计', inputs: [conditions('source', ['workbench.sequence', 'workbench.sequence_conditions'])], outputs: [generation()], fields: [number('候选数量', '8', 1)], tools: [
    { id: 'workbench.esm3.local', name: 'ESM3 · 本地', hint: '本地模型；支持明确 Seed。', fields: [number('步数', '20', 1, true), number('Temperature', '1', 0.01, true, undefined, .01), number('Seed', '0', 0, true)] },
    { id: 'workbench.esm3.biohub', name: 'ESM3 · Biohub', hint: '需要 Biohub 凭据；远端不提供 Seed。', fields: [number('步数', '20', 1, true, 100), number('Temperature', '1', 0.01, true, undefined, .01)] },
  ] },
  { type: 'workbench.esm3_sequence', title: '提取生成序列', category: '格式转换', inputs: [generation()], outputs: [sequence()], fields: [number('链索引', '0', 0)] },
  { type: 'workbench.predict', title: '预测结构', category: '结构预测', inputs: [sequence()], outputs: [prediction()], fields: [], tools: [
    { id: 'workbench.esmfold2.local', name: 'ESMFold2 · 本地', hint: '输入为一条标准氨基酸链；支持 Seed。', fields: [number('Seed', '0', 0, false, 4294967295), number('采样步数', '200', 1, true), number('循环次数', '20', 0, true)] },
    { id: 'workbench.esmfold2.remote', name: 'ESMFold2 · Biohub', hint: '输入为一条标准氨基酸链；远端不提供 Seed。', fields: [number('采样步数', '100', 1, true, 100), number('循环次数', '20', 0, true, 20)] },
  ] },
  { type: 'workbench.evaluate_solubility', title: '评价可溶性', category: '候选评价', inputs: [sequence()], outputs: [port('evaluation', '评价', 'workbench.solubility', '#e4a394')], fields: [], tools: [
    { id: 'workbench.protein_sol', name: 'Protein-Sol', hint: '完整序列，至少 21 个残基。', fields: [bool('排除膜蛋白', false, true), bool('组氨酸带电', false, true)] },
    { id: 'workbench.soluprot.full', name: 'SoluProt · 完整', hint: '完整序列，至少 20 个残基；需要 TMHMM。', fields: [number('线程数', '1', 1, true)] },
    { id: 'workbench.soluprot.no_tm', name: 'SoluProt · 无跨膜模型', hint: '完整序列，至少 20 个残基。', fields: [number('线程数', '1', 1, true)] },
  ] },
  { type: 'workbench.represent', title: '计算序列表征', category: '表征计算', inputs: [sequence()], outputs: [port('representation', '表征', 'workbench.esmc', '#b2b9e6')], fields: [bool('Embedding', true), bool('Logits', false)], tools: [
    { id: 'workbench.esmc.local', name: 'ESMC · 本地', hint: '需要已有的 ESMC 模型目录。', fields: [] },
    { id: 'workbench.esmc.biohub', name: 'ESMC · Biohub', hint: '需要 Biohub 凭据。', fields: [] },
  ] },
  { type: 'workbench.prediction_to_structure', title: '转换预测结构', category: '格式转换', inputs: [prediction('prediction')], outputs: [port('structure', '结构', 'workbench.structure', '#82c3de')], fields: [] },
  { type: 'workbench.compare_structure', title: '比较结构', category: '结构比较', inputs: [port('subject', '待比较结构', 'workbench.structure', '#82c3de'), port('reference', '参考结构', 'workbench.reference', '#82c3de', ['workbench.reference', 'workbench.structure_set'])], outputs: [port('comparison', '比较结果', 'workbench.comparison', '#e4a394')], fields: [{ key: '方法', type: 'readonly', value: 'TM-align' }] },
  { type: 'workbench.export_sequences', title: '导出序列', category: '序列输入输出', inputs: [sequence('sequences')], outputs: [port('files', '文件', 'workbench.sequence_export', '#c3c6cb')], fields: [{ key: '格式', type: 'readonly', value: 'FASTA' }] },
]
export const getKind = (node: CanvasNode) => kinds.find(kind => kind.type === node.kind)!
export const getTool = (node: CanvasNode) => getKind(node).tools?.find(tool => tool.id === node.tool)
export const getFields = (node: CanvasNode) => [...getKind(node).fields, ...getTool(node)?.fields ?? []]
export const nodeWidth = 264
export const nodeHeight = (node: CanvasNode) => 122 + Math.max(getKind(node).inputs.length, getKind(node).outputs.length) * 32 + (getFields(node).filter(field => !field.advanced).length + (node.tool ? 1 : 0)) * 31
export function newNode(kind: Kind, position: Point): CanvasNode {
  const tool = kind.tools?.[0]
  return { id: crypto.randomUUID(), kind: kind.type, position, tool: tool?.id, fields: Object.fromEntries([...kind.fields, ...tool?.fields ?? []].map(field => [field.key, field.value])) }
}
export function initialGraph(): Graph {
  const positions = [{ x: 0, y: 80 }, { x: 334, y: 80 }, { x: 668, y: 80 }, { x: 1002, y: 80 }, { x: 1002, y: 394 }, { x: 668, y: 394 }]
  return {
    nodes: kinds.slice(0, 6).map((kind, index) => ({ ...newNode(kind, positions[index]), id: `node-${index + 1}`, ...(index === 0 ? { bindings: { 0: 'ubiquitin.fasta' } } : {}) })),
    edges: [
      { source: 'node-1', output: 0, target: 'node-2', input: 0 },
      { source: 'node-2', output: 0, target: 'node-3', input: 0 },
      { source: 'node-3', output: 0, target: 'node-4', input: 0 },
      { source: 'node-3', output: 0, target: 'node-5', input: 0 },
      { source: 'node-3', output: 0, target: 'node-6', input: 0 },
    ],
  }
}
