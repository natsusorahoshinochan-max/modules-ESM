import type { PromptTrackKey } from './protocol/client'

export type MatrixTrack = PromptTrackKey | 'function'
export type MatrixCell = { handle: string; track: MatrixTrack }
export type MatrixSelection = { active: MatrixCell | null; anchor: MatrixCell | null; cells: MatrixCell[] }
export type MatrixEdit = MatrixCell & { value: string | number | null }
export const matrixTracks: MatrixTrack[] = ['sequence', 'coordinates', 'secondary_structure', 'sasa', 'function']
export const emptyMatrixSelection: MatrixSelection = { active: null, anchor: null, cells: [] }
export const cellKey = (cell: MatrixCell) => `${cell.handle}:${cell.track}`
const amino = /^[ACDEFGHIKLMNPQRSTVWYBXZJUO]$/
const ss8 = /^[HBEGITSC]$/

export function selectMatrixCell(current: MatrixSelection, cell: MatrixCell, handles: string[], tracks: MatrixTrack[], modifiers: { shift: boolean; toggle: boolean }): MatrixSelection {
  if (modifiers.shift && current.anchor) {
    const fromColumn = handles.indexOf(current.anchor.handle), toColumn = handles.indexOf(cell.handle)
    const fromRow = tracks.indexOf(current.anchor.track), toRow = tracks.indexOf(cell.track)
    if ([fromColumn, toColumn, fromRow, toRow].some(index => index < 0)) return { active: cell, anchor: cell, cells: [cell] }
    return { active: cell, anchor: current.anchor, cells: tracks.slice(Math.min(fromRow, toRow), Math.max(fromRow, toRow) + 1).flatMap(track => handles.slice(Math.min(fromColumn, toColumn), Math.max(fromColumn, toColumn) + 1).map(handle => ({ handle, track }))) }
  }
  const key = cellKey(cell)
  return { active: cell, anchor: cell, cells: modifiers.toggle ? current.cells.some(item => cellKey(item) === key) ? current.cells.filter(item => cellKey(item) !== key) : [...current.cells, cell] : [cell] }
}

export function parseMatrixValue(track: MatrixTrack, text: string): string | number | null {
  const value = text.trim()
  if (track === 'coordinates' || track === 'function') throw new Error(`${track === 'coordinates' ? 'Coordinates' : 'Function'} 请使用单元格的专用编辑入口。`)
  if (value === '' || track === 'sequence' && value === '_' || value.toLowerCase() === 'mask') return null
  if (track === 'sequence') { if (!amino.test(value.toUpperCase())) throw new Error('Sequence 必须是一个氨基酸字母，或 Mask。'); return value.toUpperCase() }
  if (track === 'secondary_structure') { if (value === '-') return '-' ; if (!ss8.test(value.toUpperCase())) throw new Error('SS8 必须是 H/B/E/G/I/T/S/C，或 Mask。'); return value.toUpperCase() }
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric < 0) throw new Error('SASA 必须是非负有限数值（Å²），或 Mask。')
  return numeric
}

export function orderedCells(cells: MatrixCell[], handles: string[], tracks = matrixTracks): MatrixCell[] {
  const keys = new Set(cells.map(cellKey))
  return tracks.flatMap(track => handles.filter(handle => keys.has(cellKey({ handle, track }))).map(handle => ({ handle, track })))
}

/** Parse and validate the entire paste before returning any edit. */
export function pasteMatrix(text: string, selection: MatrixSelection, handles: string[], tracks = matrixTracks): MatrixEdit[] {
  if (!selection.active) throw new Error('先选择粘贴起点。')
  const rows = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n').map(row => row.split('\t'))
  if (rows.some(row => row.length !== rows[0].length)) throw new Error('粘贴内容的每行列数必须相同。')
  const cells = orderedCells(selection.cells, handles, tracks)
  if (rows.length === 1 && rows[0].length === 1 && cells.length > 1) return cells.map(cell => ({ ...cell, value: parseMatrixValue(cell.track, rows[0][0]) }))
  if (cells.length > 1) {
    const selectedTracks = tracks.filter(track => cells.some(cell => cell.track === track))
    const selectedHandles = handles.filter(handle => cells.some(cell => cell.handle === handle))
    if (cells.length !== selectedTracks.length * selectedHandles.length || rows.length !== selectedTracks.length || rows[0].length !== selectedHandles.length) throw new Error(`粘贴范围不匹配：选区为 ${selectedTracks.length} 行 × ${selectedHandles.length} 列；未修改任何单元格。`)
    return selectedTracks.flatMap((track, row) => selectedHandles.map((handle, column) => ({ handle, track, value: parseMatrixValue(track, rows[row][column]) })))
  }
  const startColumn = handles.indexOf(selection.active.handle), startRow = tracks.indexOf(selection.active.track)
  if (startColumn < 0 || startRow < 0 || startColumn + rows[0].length > handles.length || startRow + rows.length > tracks.length) throw new Error('粘贴范围超出当前残基矩阵；未修改任何单元格。')
  return rows.flatMap((row, rowIndex) => row.map((value, columnIndex) => ({ handle: handles[startColumn + columnIndex], track: tracks[startRow + rowIndex], value: parseMatrixValue(tracks[startRow + rowIndex], value) })))
}

export function copyMatrix(selection: MatrixSelection, handles: string[], read: (cell: MatrixCell) => string, tracks = matrixTracks): string {
  const cells = orderedCells(selection.cells, handles, tracks)
  const columns = handles.filter(handle => cells.some(cell => cell.handle === handle))
  const rows = tracks.filter(track => cells.some(cell => cell.track === track))
  const keys = new Set(cells.map(cellKey))
  return rows.map(track => columns.map(handle => keys.has(cellKey({ handle, track })) ? read({ handle, track }) : '').join('\t')).join('\n')
}
