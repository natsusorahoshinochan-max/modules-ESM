import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef, type GridApi, type ICellRendererParams, type ICellEditorParams, type CellKeyDownEvent } from 'ag-grid-community'
import type { PromptSnapshot, PromptPreview, PromptTrackValue } from './protocol/client'
import { cellKey, copyMatrix, emptyMatrixSelection, parseMatrixValue, pasteMatrix, selectMatrixCell, type MatrixCell, type MatrixEdit, type MatrixSelection, type MatrixTrack } from './residue-matrix'

ModuleRegistry.registerModules([AllCommunityModule])
const rows: { track: MatrixTrack; label: string; unit: string }[] = [
  { track: 'sequence', label: 'Sequence', unit: '氨基酸' },
  { track: 'coordinates', label: 'Coordinates', unit: 'named atoms' },
  { track: 'secondary_structure', label: 'SS8', unit: '二级结构' },
  { track: 'sasa', label: 'SASA', unit: 'Å²' },
  { track: 'function', label: 'Function', unit: '区间注释' },
]
type Row = typeof rows[number]
type Props = {
  projection: PromptSnapshot | PromptPreview
  locators: Map<string, string>
  selection: string[]
  focus: MatrixCell
  hiddenTracks: Set<MatrixTrack>
  disabled: boolean
  reveal: { revision: number; takeFocus: boolean }
  drafts: ReadonlyMap<string, string | number | null>
  onSelection: (selection: MatrixSelection) => void
  onEdit: (edits: MatrixEdit[]) => void
  onOpen: (cell: MatrixCell) => void
  onClear: (cells: MatrixCell[]) => void
}
const theme = themeQuartz.withParams({ backgroundColor: '#151b17', foregroundColor: '#e2e8e1', borderColor: '#39463d', headerBackgroundColor: '#202b23', headerTextColor: '#d0dcd1', accentColor: '#dfbd66', fontFamily: 'system-ui, sans-serif', fontSize: 12, rowBorder: true })

export function ResidueMatrix({ projection, locators, selection, focus, hiddenTracks, disabled, reveal, drafts, onSelection, onEdit, onOpen, onClear }: Props) {
  const revealedRevision = useRef(0)
  const pointerSelecting = useRef(false)
  const pointerModifiers = useRef({ shift: false, toggle: false })
  const extending = useRef(false)
  const api = useRef<GridApi<Row> | null>(null)
  const [chosen, setChosen] = useState<MatrixSelection>(emptyMatrixSelection)
  const chosenRef = useRef(chosen)
  const [error, setError] = useState('')
  const current = projection.residues.filter(residue => residue.state !== 'pending-delete')
  const handles = current.map(residue => residue.residue_handle)
  const rowData = useMemo(() => rows.filter(row => !hiddenTracks.has(row.track)), [hiddenTracks])
  const tracks = rowData.map(row => row.track)
  const values = useMemo(() => new Map<string, PromptTrackValue>(Object.entries(projection.tracks).flatMap(([track, projection]) => projection.values.map(item => [`${item.residue_handle}:${track}`, item] as const))), [projection.tracks])
  const read = (cell: MatrixCell): string => {
    if (drafts.has(cellKey(cell))) return String(drafts.get(cellKey(cell)) ?? 'Mask')
    if (cell.track === 'function') {
      const index = projection.residues.findIndex(item => item.residue_handle === cell.handle)
      return projection.function_annotations.filter(item => item.state !== 'pending-delete' && projection.residues.findIndex(row => row.residue_handle === item.start_residue_handle) <= index && projection.residues.findIndex(row => row.residue_handle === item.end_residue_handle) >= index).map(item => item.label).join(' · ') || '—'
    }
    const item = values.get(cellKey(cell))
    if (!projection.tracks[cell.track].present) return 'Absent'
    if (item?.value == null) return 'Mask'
    if (typeof item.value === 'object') return `${item.value.atoms.length} atoms`
    return String(item.value)
  }
  const changeSelection = (next: MatrixSelection) => { chosenRef.current = next; setChosen(next); onSelection(next); api.current?.refreshCells({ force: true }) }
  const revealCell = useCallback((cell: MatrixCell, takeFocus = false) => {
    const grid = api.current
    if (!grid || !grid.getColumn(cell.handle)) return
    grid.ensureColumnVisible(cell.handle, 'middle')
    const index = rowData.findIndex(row => row.track === cell.track)
    if (index >= 0) { grid.ensureIndexVisible(index); if (takeFocus) grid.setFocusedCell(index, cell.handle) }
  }, [rowData])
  useEffect(() => {
    const selectedHandles = [...new Set(chosenRef.current.cells.map(cell => cell.handle))]
    if (selectedHandles.length !== selection.length || selection.some(handle => !selectedHandles.includes(handle)) || chosenRef.current.active?.handle !== focus.handle || chosenRef.current.active?.track !== focus.track) {
      const next = { active: focus.handle ? focus : null, anchor: focus.handle ? focus : null, cells: selection.map(handle => ({ handle, track: focus.track })) }
      chosenRef.current = next
      setChosen(next)
      api.current?.refreshCells({ force: true })
    }
    revealCell(focus)
  }, [focus, selection, revealCell])
  useEffect(() => {
    if (reveal.revision === revealedRevision.current) return
    revealedRevision.current = reveal.revision
    revealCell(focus, reveal.takeFocus)
  }, [reveal, focus, revealCell])

  const columnDefs: ColDef<Row>[] = [
    { colId: 'track', headerName: '残基 / 轨道', pinned: 'left', width: 142, suppressNavigable: true, cellRenderer: (params: ICellRendererParams<Row>) => <span className="rm-row-title"><strong>{params.data?.label}</strong><small>{params.data?.unit}</small></span> },
    ...projection.residues.map(residue => {
      const handle = residue.residue_handle
      const isCurrent = residue.state !== 'pending-delete'
      return {
        colId: handle, headerName: locators.get(handle) ?? residue.residue_id, width: 88, minWidth: 70, sortable: false, resizable: true, cellDataType: false, suppressNavigable: !isCurrent,
        valueGetter: params => params.data ? read({ handle, track: params.data.track }) : '',
        editable: params => !disabled && isCurrent && Boolean(params.data && !['coordinates', 'function'].includes(params.data.track)),
        cellEditorParams: (params: ICellEditorParams<Row>) => ({ getValidationErrors: ({ value }: { value: unknown }) => {
          if (!params.data || String(value ?? '') === String(params.value ?? '')) return null
          try { parseMatrixValue(params.data.track, String(value ?? '')); return null } catch (reason) { return [reason instanceof Error ? reason.message : String(reason)] }
        } }),
        cellEditor: 'agTextCellEditor',
        cellClassRules: {
          'rm-selected': params => Boolean(params.data && chosenRef.current.cells.some(cell => cell.handle === handle && cell.track === params.data!.track)),
          'rm-pending': params => Boolean(params.data && drafts.has(cellKey({ handle, track: params.data.track }))),
          'rm-deleted': () => !isCurrent,
        },
        cellRenderer: (params: ICellRendererParams<Row>) => {
          if (!params.data) return null
          const cell = { handle, track: params.data.track }
          const state = cell.track === 'function' ? '' : values.get(cellKey(cell))?.state ?? ''
          return <span data-cell={cellKey(cell)} className={`rm-cell state-${state}`} aria-label={`${locators.get(handle)} ${params.data.label} ${read(cell)} ${state}`}><strong>{read(cell)}</strong><small>{!isCurrent ? '已删除' : drafts.has(cellKey(cell)) ? '待确认' : state}</small>{['coordinates', 'function'].includes(cell.track) && <button disabled={!isCurrent || disabled} tabIndex={-1} aria-label={`编辑 ${locators.get(handle)} ${params.data.label}`} onClick={() => onOpen(cell)}>编辑</button>}</span>
        },
      } satisfies ColDef<Row>
    }),
  ]
  const selectedCount = chosen.cells.length
  const onCellKeyDown = (event: CellKeyDownEvent<Row>) => {
    const key = event.event as KeyboardEvent | undefined
    if (disabled || !key || key.isComposing || !event.data || !event.column || event.column.getColId() === 'track' || !handles.includes(event.column.getColId()) || api.current?.getEditingCells().length) return
    const cell = { handle: event.column.getColId(), track: event.data.track }
    if (key.key === 'Delete' || key.key === 'Backspace') { key.preventDefault(); if (!disabled) onClear(chosenRef.current.cells.length ? chosenRef.current.cells : [cell]); return }
    if ((key.key === 'Enter' || key.key === 'F2') && ['coordinates', 'function'].includes(cell.track)) { key.preventDefault(); onOpen(cell) }
  }
  return <div className="residue-matrix" aria-label="共享残基矩阵" onClickCapture={event => {
    if (disabled || !(event.target instanceof Element)) return
    // Embedded controls own their click; refreshing the cell here would unmount them before their handler.
    if (event.target.closest('button,input,textarea,select,a[href],[contenteditable="true"]')) return
    const element = event.target.closest('[role="gridcell"][col-id]')
    if (!element || !event.currentTarget.contains(element)) return
    const handle = element.getAttribute('col-id')
    const rowId = element.closest('[role="row"][row-id]')?.getAttribute('row-id')
    const track = tracks.find(value => value === rowId)
    if (!handle || !handles.includes(handle) || !track) return
    // Grid option click callbacks are asynchronous; selection must precede toolbar input.
    changeSelection(selectMatrixCell(chosenRef.current, { handle, track }, handles, tracks, { shift: event.shiftKey, toggle: event.ctrlKey || event.metaKey }))
  }} onPointerDownCapture={event => { pointerSelecting.current = true; pointerModifiers.current = { shift: event.shiftKey, toggle: event.ctrlKey || event.metaKey } }} onPointerUpCapture={() => { setTimeout(() => { pointerSelecting.current = false }, 0) }} onKeyDownCapture={event => { if (event.nativeEvent.isComposing) return; pointerSelecting.current = false; extending.current = event.shiftKey && event.key.startsWith('Arrow') }} onCopy={event => {
    if ((event.target as HTMLElement).closest('input,textarea,[contenteditable="true"]')) return
    event.preventDefault(); event.clipboardData.setData('text/plain', copyMatrix(chosenRef.current, handles, read, tracks))
  }} onPaste={event => {
    if ((event.target as HTMLElement).closest('input,textarea,[contenteditable="true"]') || disabled) return
    event.preventDefault()
    try { const edits = pasteMatrix(event.clipboardData.getData('text'), chosenRef.current, handles, tracks); setError(''); onEdit(edits) } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }}>
    <div className="rm-context" aria-live="polite"><strong>{focus.handle ? `${locators.get(focus.handle)} · ${rows.find(row => row.track === focus.track)?.label}` : '点击单元格开始'}</strong><span>{selectedCount} 个单元格 · Shift 连选 · Ctrl/⌘ 追加</span></div>
    {error && <p className="ps-help" role="alert">{error}<button onClick={() => setError('')}>关闭</button></p>}
    <div className="rm-grid"><AgGridReact<Row>
      theme={theme} rowData={rowData} columnDefs={columnDefs} getRowId={params => params.data.track}
      rowHeight={68} headerHeight={42} animateRows={false} readOnlyEdit
      singleClickEdit={false} stopEditingWhenCellsLoseFocus enterNavigatesVerticallyAfterEdit invalidEditValueMode="block"
      defaultColDef={{ suppressMovable: true, suppressHeaderMenuButton: true, suppressKeyboardEvent: params => {
        const event = params.event
        if (event.isComposing) return true
        if (params.editing) return false
        return (event.metaKey || event.ctrlKey) || event.shiftKey && event.key.startsWith('Arrow') || ['Delete', 'Backspace'].includes(event.key)
      } }}
      onGridReady={event => { api.current = event.api; revealCell(focus) }}
      onColumnHeaderClicked={event => {
        const column = event.column
        if (disabled || !column || !('getColId' in column) || !handles.includes(column.getColId())) return
        const cell = { handle: column.getColId(), track: focus.track }
        changeSelection(selectMatrixCell(chosenRef.current, cell, handles, tracks, pointerModifiers.current))
        revealCell(cell, true)
      }}
      onCellKeyDown={event => {
        if (!('column' in event)) return
        onCellKeyDown(event)
        const key = event.event as KeyboardEvent | undefined
        if (disabled || !key || key.isComposing || !key.shiftKey || !key.key.startsWith('Arrow') || !event.data || !event.column || !handles.includes(event.column.getColId()) || api.current?.getEditingCells().length) return
        key.preventDefault()
        const column = handles.indexOf(event.column.getColId()), row = tracks.indexOf(event.data.track)
        const handle = handles[Math.max(0, Math.min(handles.length - 1, column + (key.key === 'ArrowLeft' ? -1 : key.key === 'ArrowRight' ? 1 : 0)))]
        const track = tracks[Math.max(0, Math.min(tracks.length - 1, row + (key.key === 'ArrowUp' ? -1 : key.key === 'ArrowDown' ? 1 : 0)))]
        if (handle && track) { const cell = { handle, track }; changeSelection(selectMatrixCell(chosenRef.current, cell, handles, tracks, { shift: true, toggle: false })); revealCell(cell, true) }
      }}
      onCellFocused={event => {
        if (event.rowIndex == null || !event.column || typeof event.column === 'string' || event.column.getColId() === 'track' || !handles.includes(event.column.getColId())) return
        const row = rowData[event.rowIndex]
        if (!row) return
        const cell = { handle: event.column.getColId(), track: row.track }
        // Mouse modifier selection is handled by the click event, keyboard movement by focus.
        if (!disabled && !pointerSelecting.current && !extending.current && (chosenRef.current.active ? cellKey(chosenRef.current.active) : '') !== cellKey(cell)) {
          changeSelection({ active: cell, anchor: cell, cells: [cell] })
        }
      }}
      onCellEditRequest={event => {
        if (!event.data || event.newValue === event.oldValue) return
        const cell = { handle: event.column.getColId(), track: event.data.track }
        try { const value = parseMatrixValue(cell.track, String(event.newValue ?? '')); setError(''); onEdit([{ ...cell, value }]) } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
      }}
    /></div>
    <div className="rm-hint">直接键入 / F2 编辑 · Enter 下一轨道 · Tab 下一残基 · Esc 取消输入 · Ctrl/⌘ C/V 复制粘贴</div>
  </div>
}
