import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type CSSProperties } from 'react'
import { Check, ChevronLeft, Info, Plus, RotateCcw, RotateCw, Save, Trash2, X } from 'lucide-react'
import type { JsonObject, PromptAuthoringDocument, PromptDiagnostic, PromptDocumentFunctionAnnotation, PromptPreview, PromptRandomOperation, PromptSnapshot, PromptTrackEdit, PromptTrackKey, PromptTrackValue, PromptRigidTransform } from '../../../webui/src/protocol/client'
import { StructureViewer, type StructureViewerHandle, type ViewerResidue } from '../../../webui/src/StructureViewer'
import { PromptTransformEditor } from './PromptTransformEditor'
import { PromptMergeEditor, type PromptMergeDraft } from './PromptMergeEditor'
import { promptStructure } from './prompt-structure'
import { deletePromptResidues, insertPromptResidues, promptLayoutTargets } from './prompt-layout'
import { ResidueMatrix } from './ResidueMatrix'
import { cellKey, parseMatrixValue, type MatrixCell, type MatrixEdit, type MatrixSelection } from './residue-matrix'
import { InteractionDialog } from '../../../webui/src/InteractionDialog'
import './prompt-studio.css'

type ScalarTrack = 'sequence' | 'coordinates' | 'secondary_structure' | 'sasa'
type Track = ScalarTrack | 'function'
type TrackAction = 'preserve' | 'clear' | 'replace'
type Projection = PromptSnapshot | PromptPreview
type LocalPreview = { title: string; preview: PromptPreview; insertedHandles: string[]; insertedResidueIds: string[]; insertAnchor?: string }
type UndoEntry = { label: string; document: PromptAuthoringDocument; projection: Projection; selection: string[]; anchor: string; focus: { handle: string; track: Track } }
type PromptStudioProps = {
  snapshot: PromptSnapshot
  onCancel: () => void
  onAddMergeSource: (document: PromptAuthoringDocument) => Promise<PromptSnapshot | undefined>
  onPreview: (document: PromptAuthoringDocument) => Promise<PromptPreview>
  onApply: (preview: PromptPreview) => Promise<void>
}

const trackRows: Array<{ key: Track; label: string; unit: string }> = [
  { key: 'sequence', label: 'Sequence', unit: 'amino acid' },
  { key: 'coordinates', label: 'Coordinates', unit: 'named atoms' },
  { key: 'secondary_structure', label: 'Secondary structure', unit: 'SS8' },
  { key: 'sasa', label: 'SASA', unit: 'Å²' },
  { key: 'function', label: 'Function annotations', unit: 'tuple interval' },
]
const scalarTracks = trackRows.slice(0, 4) as Array<{ key: ScalarTrack; label: string; unit: string }>
const aminoAcids = new Set('ACDEFGHIKLMNPQRSTVWYBXZJUO'.split(''))
const ss8Codes = new Set('HBEGITSC'.split(''))
const states = ['source', 'current', 'changed', 'cleared', 'inserted', 'pending-delete'] as const

function trackEdits(document: PromptAuthoringDocument) { return document.track_edits ?? [] }
function targets(document: PromptAuthoringDocument) { return document.target_residues ?? [] }
function annotations(document: PromptAuthoringDocument) { return document.function_annotations ?? [] }

function requestErrorText(error: unknown) {
  return error instanceof Error ? error.message : (error as { error: { message: string } }).error.message
}

function removeOneAnnotation(document: PromptAuthoringDocument, annotation: PromptDocumentFunctionAnnotation) {
  let removed = false
  return annotations(document).filter((item) => {
    if (!removed && item.label === annotation.label && item.start_residue_id === annotation.start_residue_id && item.end_residue_id === annotation.end_residue_id) {
      removed = true
      return false
    }
    return true
  })
}

function projectedAnnotationIntents(projection: Projection, residueIdByHandle: Map<string, string>) {
  return projection.function_annotations.filter((item) => item.state !== 'pending-delete').map((item) => {
    const start_residue_id = residueIdByHandle.get(item.start_residue_handle)
    const end_residue_id = residueIdByHandle.get(item.end_residue_handle)
    if (!start_residue_id || !end_residue_id) throw new Error('Function annotation endpoint is outside the residue projection')
    return { label: item.label, start_residue_id, end_residue_id }
  })
}

function displayValue(track: ScalarTrack, item: PromptTrackValue) {
  if (item.value == null) return 'Mask'
  if (track === 'coordinates') return `${(item.value as { atoms: unknown[] }).atoms.length} atoms`
  return String(item.value)
}

function selectionText(handles: string[], projection: Projection, locators: Map<string, string>) {
  const selected = projection.residues.filter((residue) => handles.includes(residue.residue_handle) && residue.position > 0)
  if (!selected.length) return '未选择残基'
  const labels = selected.map((residue) => locators.get(residue.residue_handle) ?? residue.residue_id)
  if (labels.length <= 6) return labels.join(' + ')
  return `${labels[0]}–${labels.at(-1)} · ${labels.length} residues`
}

function trackDocument(document: PromptAuthoringDocument, selected: string[], track: PromptTrackKey, action: TrackAction, value?: string | number) {
  const retained = trackEdits(document).filter((edit) => edit.track !== track || !selected.includes(edit.residue_id))
  const additions = selected.map((residue_id) => ({ track, residue_id, action, ...(action === 'replace' ? { value } : {}) }) as PromptTrackEdit)
  return { ...document, track_edits: [...retained, ...additions] }
}

function diagnosticsHaveError(preview: PromptPreview) {
  return preview.diagnostics.length > 0
}

function diagnosticText(diagnostic: PromptDiagnostic, locators: Map<string, string>) {
  return `${diagnostic.residue_handle ? `${locators.get(diagnostic.residue_handle) ?? diagnostic.residue_handle} · ` : ''}${String(diagnostic.message)}`
}

function previewChangeText(change: JsonObject, before: Projection, after: PromptPreview, locators: Map<string, string>) {
  const handle = typeof change.residue_handle === 'string' ? change.residue_handle : undefined
  if (change.kind === 'residue_order') return '残基顺序已调整'
  if (change.kind === 'residue') return `${handle ? locators.get(handle) ?? handle : 'Residue'} · ${String(change.action)}`
  if (change.kind === 'track_presence') return `${String(change.track)} track · ${String(change.action)}`
  if (change.kind === 'function_annotation') return `Function annotation · ${String(change.action)}`
  const track = String(change.track) as ScalarTrack
  const previous = handle ? before.tracks[track].values.find((item) => item.residue_handle === handle) : undefined
  const next = handle ? after.tracks[track].values.find((item) => item.residue_handle === handle) : undefined
  const transition = previous && next ? `${displayValue(track, previous)} → ${displayValue(track, next)}` : String(change.action)
  return `${handle ? locators.get(handle) ?? handle : 'Track'} · ${track} · ${transition}`
}

export function PromptStudio({ snapshot, onCancel, onAddMergeSource, onPreview, onApply }: PromptStudioProps) {
  const initialHandleById = new Map(snapshot.residues.map((item) => [item.residue_id, item.residue_handle]))
  const initialTargetHandles = new Set((targets(snapshot.document).length ? targets(snapshot.document).map((item) => initialHandleById.get(item.residue_id)) : snapshot.residues.filter((item) => item.state !== 'pending-delete').map((item) => item.residue_handle)).filter((item): item is string => Boolean(item)))
  const initiallyEdited = snapshot.residues.filter((residue) => initialTargetHandles.has(residue.residue_handle) && scalarTracks.some(({ key }) => {
    const item = snapshot.tracks[key].values.find((value) => value.residue_handle === residue.residue_handle)
    return item && !['source', 'current'].includes(item.state)
  })).map((residue) => residue.residue_handle)
  const initialHandle = initiallyEdited[0] ?? snapshot.residues[0]?.residue_handle ?? ''
  const [mergeSourceSnapshot, setMergeSourceSnapshot] = useState(snapshot)
  const [document, setDocument] = useState<PromptAuthoringDocument>(snapshot.document)
  const [committedProjection, setCommittedProjection] = useState<Projection>(snapshot)
  const [localPreview, setLocalPreview] = useState<LocalPreview>()
  const [selection, setSelection] = useState<string[]>(initiallyEdited)
  const [anchor, setAnchor] = useState(initialHandle)
  const [focus, setFocus] = useState<{ handle: string; track: Track }>({ handle: initialHandle, track: 'sequence' })
  const [activeTrack, setActiveTrack] = useState<Track>('sequence')
  const [mode, setMode] = useState<'layout' | 'condition' | 'structure'>(snapshot.source.kind === 'blank' ? 'layout' : 'condition')
  const [hiddenTracks, setHiddenTracks] = useState<Set<Track>>(new Set())
  const [sequenceValue, setSequenceValue] = useState('')
  const [ssValue, setSsValue] = useState('')
  const [sasaValue, setSasaValue] = useState('')
  const [functionValue, setFunctionValue] = useState('binding_site')
  const [functionTargetKey, setFunctionTargetKey] = useState('')
  const [functionStart, setFunctionStart] = useState('')
  const [functionEnd, setFunctionEnd] = useState('')
  const [functionSplit, setFunctionSplit] = useState('')
  const [randomSeed, setRandomSeed] = useState('0')
  const [randomCount, setRandomCount] = useState('1')
  const [randomScope, setRandomScope] = useState<'all' | 'selection'>('all')
  const [transformMode, setTransformMode] = useState<'translate' | 'rotate'>('translate')
  const [transformAmount, setTransformAmount] = useState('0')
  const [transformAxis, setTransformAxis] = useState<'x' | 'y' | 'z'>('x')
  const [transformOrigin, setTransformOrigin] = useState<[number, number, number]>()
  const [insertCount, setInsertCount] = useState('1')
  const [insertSequence, setInsertSequence] = useState('')
  const [busy, setBusy] = useState(false)
  const [requestError, setRequestError] = useState('')
  const [chainRows, setChainRows] = useState((snapshot.document.chains ?? []).map((chain) => ({ chain_id: chain.chain_id, length: String(chain.length) })))
  const [dirty, setDirty] = useState(false)
  const [graphDirty, setGraphDirty] = useState(false)
  const [leaveOpen, setLeaveOpen] = useState(false)
  const [legendOpen, setLegendOpen] = useState(false)
  const [editorPanel, setEditorPanel] = useState<'batch' | 'function' | 'layout' | 'random' | 'structure' | 'merge' | 'evidence' | null>(null)
  const [batchActions, setBatchActions] = useState<Record<ScalarTrack, TrackAction | 'unchanged'>>({ sequence: 'unchanged', coordinates: 'unchanged', secondary_structure: 'unchanged', sasa: 'unchanged' })
  const [batchValues, setBatchValues] = useState<Record<ScalarTrack, string>>({ sequence: '', coordinates: '', secondary_structure: '', sasa: '' })
  const [narrowView, setNarrowView] = useState<'matrix' | 'structure'>('matrix')
  const [structureWidth, setStructureWidth] = useState(36)
  const [reveal, setReveal] = useState({ revision: 0, takeFocus: false })
  const [cellDrafts, setCellDrafts] = useState<Map<string, string | number | null>>(new Map())
  const [matrixCells, setMatrixCells] = useState<MatrixCell[]>([])
  const [unpreviewed, setUnpreviewed] = useState(false)
  const [mergeDirty, setMergeDirty] = useState(false)
  const [status, setStatus] = useState('')
  const [viewportActive, setViewportActive] = useState(false)
  const [saving, setSaving] = useState(false)
  const viewer = useRef<StructureViewerHandle>(null)
  const studio = useRef<HTMLDivElement>(null)
  const pendingRef = useRef<LocalPreview | undefined>(undefined)
  const desiredDocument = useRef(snapshot.document)
  const transformStart = useRef<{ document: PromptAuthoringDocument; pending?: LocalPreview } | undefined>(undefined)
  const mergeDraft = useRef<PromptMergeDraft | undefined>(undefined)
  const [mergeRevision, setMergeRevision] = useState(0)
  const redoStack = useRef<UndoEntry[]>([])
  const undoStack = useRef<UndoEntry[]>([])
  const previewRequest = useRef(0)
  const session = useRef({ document, projection: committedProjection, selection, anchor, focus })
  useEffect(() => { session.current = { document, projection: committedProjection, selection, anchor, focus } }, [document, committedProjection, selection, anchor, focus])
  const matrixQueue = useRef<Array<{ edits: MatrixEdit[]; label: string; selection: string[]; anchor: string; focus: MatrixCell }>>([])
  const matrixProcessing = useRef(false)
  const matrixFailed = useRef(false)
  useEffect(() => () => { previewRequest.current += 1; matrixQueue.current = []; matrixProcessing.current = false }, [])

  useEffect(() => {
    if (!dirty && !graphDirty && !localPreview && !unpreviewed && !mergeDirty && !busy && !viewportActive) return
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [dirty, graphDirty, localPreview, unpreviewed, mergeDirty, busy, viewportActive])

  const projection: Projection = localPreview?.preview ?? committedProjection
  const committedHandles = useMemo(() => new Set(committedProjection.residues.filter((item) => item.state !== 'pending-delete').map((item) => item.residue_handle)), [committedProjection.residues])
  const visibleDocument = localPreview?.preview.normalized_document ?? document
  const currentHandles = useMemo(() => new Set(projection.residues.filter((item) => item.state !== 'pending-delete').map((item) => item.residue_handle)), [projection.residues])
  const orderedResidues = projection.residues
  const residueIdByHandle = useMemo(() => new Map(projection.residues.map((item) => [item.residue_handle, item.residue_id])), [projection.residues])
  const displayLocators = useMemo(() => {
    const origin = new Map(targets(visibleDocument).map((item) => [String(item.residue_id), String(item.origin)]))
    const lastSource = new Map<string, string>()
    const insertCounts = new Map<string, number>()
    const locators = new Map<string, string>()
    for (const residue of orderedResidues) {
      if (!currentHandles.has(residue.residue_handle) || origin.get(residue.residue_id) !== 'inserted') {
        locators.set(residue.residue_handle, `${residue.chain_id}${residue.residue_label}`)
        if (currentHandles.has(residue.residue_handle)) { lastSource.set(residue.chain_id, residue.residue_label); insertCounts.set(residue.chain_id, 0) }
        continue
      }
      const count = (insertCounts.get(residue.chain_id) ?? 0) + 1
      insertCounts.set(residue.chain_id, count)
      locators.set(residue.residue_handle, `${residue.chain_id}${lastSource.get(residue.chain_id) ?? 'N-term'}+${count}`)
    }
    return locators
  }, [currentHandles, orderedResidues, visibleDocument])
  const structureResidueLabel = useCallback(({ chain, resi }: ViewerResidue) => {
    const residue = projection.residues.find(item => item.chain_id === chain && item.position === resi)
    if (!residue) throw new Error('Structure residue is outside the Prompt projection')
    return displayLocators.get(residue.residue_handle)!
  }, [displayLocators, projection.residues])
  const trackMaps = useMemo(() => new Map(scalarTracks.map(({ key }) => [key, new Map(projection.tracks[key].values.map((item) => [item.residue_handle, item]))])), [projection])
  const rowIndex = useMemo(() => new Map(orderedResidues.map((item, index) => [item.residue_handle, index])), [orderedResidues])
  const focusedFunctionOptions = useMemo(() => projection.function_annotations.map((annotation, index) => ({ annotation, key: `${annotation.label}:${annotation.start_residue_handle}:${annotation.end_residue_handle}:${index}` })).filter(({ annotation }) => {
    const index = rowIndex.get(focus.handle)
    const start = rowIndex.get(annotation.start_residue_handle)
    const end = rowIndex.get(annotation.end_residue_handle)
    return index !== undefined && start !== undefined && end !== undefined && annotation.state !== 'pending-delete' && start <= index && index <= end
  }), [projection.function_annotations, rowIndex, focus.handle])
  const focusedFunction = focusedFunctionOptions.find((item) => item.key === functionTargetKey)?.annotation ?? focusedFunctionOptions[0]?.annotation
  const currentCommittedResidues = projection.residues.filter((item) => currentHandles.has(item.residue_handle))
  const orderedFunctionSelection = currentCommittedResidues.filter((item) => selection.includes(item.residue_handle))
  const functionSelectionValid = orderedFunctionSelection.length === selection.length && orderedFunctionSelection.every((item, index) => index === 0 || (item.chain_id === orderedFunctionSelection[index - 1].chain_id && currentCommittedResidues.indexOf(item) === currentCommittedResidues.indexOf(orderedFunctionSelection[index - 1]) + 1))
  const selectedText = selectionText(selection, { ...projection, residues: orderedResidues }, displayLocators)
  const hasCoordinates = projection.tracks.coordinates.values.some((item) => item.value != null && item.state !== 'pending-delete')
  const selectedPositions = useMemo(() => projection.residues.filter((item) => selection.includes(item.residue_handle) && currentHandles.has(item.residue_handle)).map((item) => ({ chain: item.chain_id, resi: item.position })), [currentHandles, projection.residues, selection])
  const projectionStructure = useMemo(() => promptStructure(projection), [projection])
  const targetIntent = () => promptLayoutTargets(visibleDocument) ?? (projection.merge_targets[0]?.residues ?? committedProjection.merge_targets[0]?.residues ?? []).filter((item) => item.state !== 'pending-delete').map((item) => ({ residue_id: item.residue_id, origin: 'source' as const }))
  const canEditChains = ['blank', 'fasta'].includes(String(snapshot.source.kind)) || document.chains !== undefined || !committedProjection.residues.length
  const chainsReady = chainRows.length > 0 && chainRows.every((chain) => chain.chain_id.length > 0 && /^\d+$/.test(chain.length) && Number(chain.length) > 0)
  const operationBlocked = busy || viewportActive || saving
  const insertionCount = Number(insertCount)
  const insertionInputValid = Number.isInteger(insertionCount) && insertionCount > 0 && (insertSequence.length === 0 || insertSequence.length === 1 || insertSequence.length === insertionCount) && [...insertSequence].every((letter) => aminoAcids.has(letter))
  const sasaInputValid = sasaValue.trim() !== '' && Number.isFinite(Number(sasaValue)) && Number(sasaValue) >= 0

  const acceptPreview = (pending: LocalPreview) => {
    undoStack.current.push({ ...session.current, label: pending.title })
    redoStack.current = []
    const next = pending.preview.normalized_document
    desiredDocument.current = next
    pendingRef.current = undefined
    session.current = { ...session.current, document: next, projection: pending.preview }
    setDocument(next)
    setCommittedProjection(pending.preview)
    setChainRows((next.chains ?? []).map(chain => ({ chain_id: chain.chain_id, length: String(chain.length) })))
    const retained = new Set(pending.preview.residues.filter(item => item.state !== 'pending-delete').map(item => item.residue_handle))
    setSelection(current => pending.insertedHandles.length ? pending.insertedHandles : current.filter(handle => retained.has(handle)))
    if (pending.insertedHandles.length) { setFocus({ handle: pending.insertedHandles[0], track: 'sequence' }); setAnchor(pending.insertedHandles[0]) }
    setLocalPreview(undefined)
    setCellDrafts(new Map())
    setUnpreviewed(false)
    setDirty(true)
    setStatus(`已应用：${pending.title} · 可继续编辑或撤销`)
  }
  const propose = async (nextDocument: PromptAuthoringDocument, title: string, insertedResidueIds: string[] = [], insertAnchor?: string, accept = false): Promise<boolean> => {
    if (matrixProcessing.current) { setRequestError('单元格编辑正在依次应用，请稍后开始其他操作。'); return false }
    const requestId = ++previewRequest.current
    desiredDocument.current = nextDocument
    setUnpreviewed(true)
    setBusy(true)
    setRequestError('')
    try {
      const preview = await onPreview(nextDocument)
      if (requestId !== previewRequest.current) return false
      const handleById = new Map(preview.residues.map(item => [item.residue_id, item.residue_handle]))
      const insertedHandles = insertedResidueIds.map(id => handleById.get(id)).filter((item): item is string => Boolean(item))
      const pending = { title, preview, insertedHandles, insertedResidueIds, insertAnchor }
      pendingRef.current = pending
      setLocalPreview(pending)
      setUnpreviewed(false)
      if (accept && !diagnosticsHaveError(preview)) acceptPreview(pending)
      return !diagnosticsHaveError(preview)
    } catch (error) {
      if (requestId === previewRequest.current) setRequestError(requestErrorText(error))
      return false
    } finally { if (requestId === previewRequest.current) setBusy(false) }
  }

  const cancelLocalPreview = useCallback(() => {
    if (saving) return
    setChainRows((document.chains ?? []).map(chain => ({ chain_id: chain.chain_id, length: String(chain.length) })))
    previewRequest.current += 1
    matrixQueue.current = []; matrixFailed.current = false; matrixProcessing.current = false
    setBusy(false)
    setLocalPreview(undefined)
    pendingRef.current = undefined
    desiredDocument.current = document
    setCellDrafts(new Map())
    setUnpreviewed(false)
    setRequestError('')
    setStatus('已取消本次操作，保持当前编辑位置')
    mergeDraft.current = undefined; setMergeRevision(value => value + 1); setMergeDirty(false)
    if (!committedHandles.has(focus.handle)) {
      const nextHandle = selection.find((handle) => committedHandles.has(handle)) ?? committedProjection.residues.find((item) => committedHandles.has(item.residue_handle))?.residue_handle ?? ''
      setSelection((current) => current.filter((handle) => committedHandles.has(handle)))
      setAnchor(nextHandle)
      setFocus((current) => ({ ...current, handle: nextHandle }))
    }
  }, [committedHandles, committedProjection.residues, document, focus.handle, saving, selection])

  const selectFromStructure = useCallback((picked: { chain: string; resi: number; toggle: boolean; range: boolean }) => {
    const residue = projection.residues.find((item) => item.chain_id === picked.chain && item.position === picked.resi && currentHandles.has(item.residue_handle))
    if (!residue) return
    if (picked.range) {
      const handles = projection.residues.filter(item => currentHandles.has(item.residue_handle)).map(item => item.residue_handle)
      const from = handles.indexOf(anchor), to = handles.indexOf(residue.residue_handle)
      setSelection(handles.slice(Math.min(from, to), Math.max(from, to) + 1))
    } else {
      setSelection(current => picked.toggle ? current.includes(residue.residue_handle) ? current.filter(handle => handle !== residue.residue_handle) : [...current, residue.residue_handle] : [residue.residue_handle])
      setAnchor(residue.residue_handle)
    }
    setFocus((current) => ({ ...current, handle: residue.residue_handle }))
    setReveal(value => ({ revision: value.revision + 1, takeFocus: false }))
  }, [anchor, currentHandles, projection.residues])

  const applyLocalPreview = () => {
    const pending = pendingRef.current
    if (pending && !busy && !diagnosticsHaveError(pending.preview)) acceptPreview(pending)
  }
  const restoreHistory = (redo: boolean) => {
    const source = redo ? redoStack.current : undoStack.current
    const previous = source.pop()
    if (!previous) return
    ;(redo ? undoStack.current : redoStack.current).push({ ...session.current, label: previous.label })
    previewRequest.current += 1
    session.current = previous
    desiredDocument.current = previous.document
    pendingRef.current = undefined
    setDocument(previous.document); setCommittedProjection(previous.projection)
    setSelection(previous.selection); setAnchor(previous.anchor); setFocus(previous.focus); setActiveTrack(previous.focus.track)
    setChainRows((previous.document.chains ?? []).map(chain => ({ chain_id: chain.chain_id, length: String(chain.length) })))
    setLocalPreview(undefined); setCellDrafts(new Map()); setUnpreviewed(false); setBusy(false); setRequestError('')
    setDirty(JSON.stringify(previous.document) !== JSON.stringify(snapshot.document))
    setStatus(`${redo ? '已重做' : '已撤销'}：${previous.label}`)
    studio.current?.focus({ preventScroll: true })
    setReveal(value => ({ revision: value.revision + 1, takeFocus: true }))
    mergeDraft.current = undefined; setMergeRevision(value => value + 1); setMergeDirty(false)
  }
  const undo = () => { if (viewportActive || busy) return; if (localPreview || unpreviewed) cancelLocalPreview(); else restoreHistory(false) }
  const redo = () => { if (!viewportActive && !busy) restoreHistory(true) }
  const chooseMatrix = (next: MatrixSelection) => {
    setMatrixCells(next.cells)
    setSelection([...new Set(next.cells.map(cell => cell.handle))])
    if (next.anchor) setAnchor(next.anchor.handle)
    if (next.active) { setFocus(next.active); setActiveTrack(next.active.track) }
  }
  const queuedDrafts = () => new Map(matrixQueue.current.flatMap(command => command.edits.map(edit => [cellKey(edit), edit.value] as const)))
  const processMatrixQueue = async () => {
    if (matrixProcessing.current) return
    matrixProcessing.current = true
    matrixFailed.current = false
    setBusy(true); setUnpreviewed(true); setRequestError('')
    const epoch = ++previewRequest.current
    try {
      while (matrixQueue.current.length) {
        const command = matrixQueue.current[0]
        let next = session.current.document
        const ids = new Map(session.current.projection.residues.map(item => [item.residue_handle, item.residue_id]))
        for (const edit of command.edits) {
          const id = ids.get(edit.handle)
          if (!id || edit.track === 'function') throw new Error('当前选区不再可编辑；请重新选择。')
          next = trackDocument(next, [id], edit.track, edit.value === null ? 'clear' : 'replace', edit.value ?? undefined)
        }
        const preview = await onPreview(next)
        if (epoch !== previewRequest.current) return
        if (diagnosticsHaveError(preview)) throw new Error(preview.diagnostics.map(item => diagnosticText(item, displayLocators)).join('；'))
        const before = { ...session.current, selection: command.selection, anchor: command.anchor, focus: command.focus, label: command.label }
        undoStack.current.push(before); redoStack.current = []
        session.current = { ...session.current, document: preview.normalized_document, projection: preview }
        desiredDocument.current = preview.normalized_document
        setDocument(preview.normalized_document); setCommittedProjection(preview); setDirty(true)
        matrixQueue.current.shift()
        setCellDrafts(queuedDrafts())
        setStatus(`已应用：${command.label}`)
      }
      setUnpreviewed(false)
    } catch (reason) {
      if (epoch === previewRequest.current) { matrixFailed.current = true; setRequestError(`${requestErrorText(reason)} 输入已保留，请重试或取消。`) }
    } finally {
      if (epoch === previewRequest.current) { matrixProcessing.current = false; setBusy(false) }
    }
  }
  const editMatrix = (edits: MatrixEdit[]) => {
    if (localPreview || viewportActive || saving || (busy || unpreviewed && !matrixFailed.current) && !matrixProcessing.current) { setRequestError('先应用或取消当前操作，再编辑矩阵。'); return }
    const handles = [...new Set(edits.map(edit => edit.handle))]
    const label = edits.length === 1 ? `${displayLocators.get(edits[0].handle)} · ${trackRows.find(row => row.key === edits[0].track)?.label}` : `批量修改 ${edits.length} 个单元格`
    if (matrixFailed.current && matrixQueue.current[0]?.edits.length === edits.length && matrixQueue.current[0].edits.every(old => edits.some(edit => cellKey(old) === cellKey(edit)))) matrixQueue.current[0].edits = edits
    else matrixQueue.current.push({ edits, label, selection: handles, anchor, focus })
    setCellDrafts(queuedDrafts())
    if (!matrixFailed.current || matrixQueue.current[0].edits === edits) void processMatrixQueue()
  }
  const clearCells = (cells: MatrixCell[]) => {
    if (cells.some(cell => cell.track === 'function')) { setRequestError('Function 请打开区间编辑，明确删除完整注释；未修改选区。'); return }
    editMatrix(cells.map(cell => ({ ...cell, value: null })))
  }
  const openCell = (cell: MatrixCell) => {
    setFocus(cell); setActiveTrack(cell.track)
    if (!selection.includes(cell.handle)) setSelection([cell.handle])
    if (cell.track === 'coordinates') { setMode('structure'); setNarrowView('structure'); setEditorPanel('structure') }
    else { setFunctionTargetKey(''); setFunctionStart(''); setFunctionEnd(''); setFunctionSplit(''); setEditorPanel('function') }
  }

  const updateTrack = (track: ScalarTrack, action: TrackAction, value?: string | number) => {
    if (!selection.length) return
    const residueIds = selection.map((handle) => residueIdByHandle.get(handle)).filter((item): item is string => Boolean(item))
    const label = scalarTracks.find((row) => row.key === track)?.label ?? track
    void propose(trackDocument(desiredDocument.current, residueIds, track, action, value), `${label} · ${action}`)
  }

  const deleteSelection = () => {
    const selectedIds = new Set(selection.map((handle) => residueIdByHandle.get(handle)).filter((item): item is string => Boolean(item)))
    const next = deletePromptResidues(visibleDocument, targetIntent(), selectedIds)
    void propose(next, `删除 ${selection.length} 个残基`)
  }

  const insertResidues = (count = insertionCount, rawSequence = insertSequence, anchorOverride?: string) => {
    const sequence = rawSequence.trim().toUpperCase()
    if (!Number.isInteger(count) || count < 1 || ![0, 1, count].includes(sequence.length) || ![...sequence].every((letter) => aminoAcids.has(letter))) return
    const anchorHandle = anchorOverride ?? focus.handle ?? selection.at(-1)
    if (!anchorHandle) return
    const anchorResidue = projection.residues.find((item) => item.residue_handle === anchorHandle)
    if (!anchorResidue) return
    const replacedIds = anchorOverride ? localPreview?.insertedResidueIds ?? [] : []
    const baseDocument = deletePromptResidues(visibleDocument, targetIntent(), new Set(replacedIds))
    const orderedIds = projection.residues.filter(item => item.state !== 'pending-delete' && !replacedIds.includes(item.residue_id)).map(item => item.residue_id)
    const precedingIds = orderedIds.slice(0, orderedIds.indexOf(anchorResidue.residue_id) + 1)
    const insertedResidueIds = Array.from({ length: count }, () => `${anchorResidue.chain_id}:inserted.${crypto.randomUUID().replaceAll('-', '')}`)
    const letters = sequence.length === 1 ? Array(count).fill(sequence) : sequence.split('')
    const sequenceEdits = insertedResidueIds.map((residue_id, index) => letters[index] ? { track: 'sequence' as const, residue_id, action: 'replace' as const, value: letters[index] } : { track: 'sequence' as const, residue_id, action: 'clear' as const })
    const next = insertPromptResidues(baseDocument, promptLayoutTargets(baseDocument)!, precedingIds, insertedResidueIds, sequenceEdits)
    void propose(next, `插入 ${count} 个残基`, insertedResidueIds, anchorHandle)
  }

  const addFunction = (label = functionValue) => {
    if (!selection.length) return
    const replaceExisting = focusedFunction
    if (!replaceExisting && !functionSelectionValid) return
    const replacementIntent = replaceExisting ? {
      label: replaceExisting.label,
      start_residue_id: residueIdByHandle.get(replaceExisting.start_residue_handle) ?? '',
      end_residue_id: residueIdByHandle.get(replaceExisting.end_residue_handle) ?? '',
    } : undefined
    const start_residue_id = replacementIntent?.start_residue_id ?? orderedFunctionSelection[0]?.residue_id
    const end_residue_id = replacementIntent?.end_residue_id ?? orderedFunctionSelection.at(-1)?.residue_id
    if (!start_residue_id || !end_residue_id) return
    const currentDocument = visibleDocument.function_annotations === undefined ? { ...visibleDocument, function_annotations: projectedAnnotationIntents(projection, residueIdByHandle) } : visibleDocument
    const retained = replacementIntent ? removeOneAnnotation(currentDocument, replacementIntent) : annotations(currentDocument)
    const nextAnnotation: PromptDocumentFunctionAnnotation = { label, start_residue_id, end_residue_id }
    void propose({ ...visibleDocument, function_annotations: [...retained, nextAnnotation] }, `${replaceExisting ? '替换' : '新增'} Function · ${label}`)
  }

  const deleteFunction = () => {
    if (!focusedFunction) return
    const intent = {
      label: focusedFunction.label,
      start_residue_id: residueIdByHandle.get(focusedFunction.start_residue_handle) ?? '',
      end_residue_id: residueIdByHandle.get(focusedFunction.end_residue_handle) ?? '',
    }
    const currentDocument = visibleDocument.function_annotations === undefined ? { ...visibleDocument, function_annotations: projectedAnnotationIntents(projection, residueIdByHandle) } : visibleDocument
    const next = removeOneAnnotation(currentDocument, intent)
    void propose({ ...visibleDocument, function_annotations: next }, '删除 Function tuple')
  }

  const updateFunctionInterval = (split: boolean) => {
    if (!focusedFunction) return
    const old = { label: focusedFunction.label, start_residue_id: residueIdByHandle.get(focusedFunction.start_residue_handle)!, end_residue_id: residueIdByHandle.get(focusedFunction.end_residue_handle)! }
    const current = { ...visibleDocument, function_annotations: visibleDocument.function_annotations ?? projectedAnnotationIntents(projection, residueIdByHandle) }
    const retained = removeOneAnnotation(current, old)
    const start = functionStart || old.start_residue_id, end = functionEnd || old.end_residue_id
    const splitIndex = currentCommittedResidues.findIndex(item => item.residue_id === functionSplit)
    const replacements = split ? [
      { label: functionValue, start_residue_id: start, end_residue_id: functionSplit },
      { label: functionValue, start_residue_id: currentCommittedResidues[splitIndex + 1].residue_id, end_residue_id: end },
    ] : [{ label: functionValue, start_residue_id: start, end_residue_id: end }]
    void propose({ ...visibleDocument, function_annotations: [...retained, ...replacements] }, split ? '拆分 Function 区间' : '修改 Function 端点')
  }

  const randomOperation = (seed = Number(randomSeed)) => {
    const operation: PromptRandomOperation = mode === 'layout'
      ? { kind: 'insert', count: Number(randomCount), seed, ...(randomScope === 'selection' ? { eligible_chain_ids: [...new Set(projection.residues.filter(item => selection.includes(item.residue_handle)).map(item => item.chain_id))] } : {}) }
      : { kind: 'mask', count: Number(randomCount), seed, track: activeTrack as ScalarTrack, ...(randomScope === 'selection' ? { eligible_residue_ids: selection.map(handle => residueIdByHandle.get(handle)!) } : {}) }
    const operations = [...visibleDocument.random_operations ?? []]
    operations.push(operation)
    setRandomSeed(String(seed))
    void propose({ ...visibleDocument, random_operations: operations }, `随机 ${operation.kind} · seed ${seed}`)
  }

  const focusDiagnostic = (diagnostic: PromptDiagnostic) => {
    const handle = diagnostic.residue_handle
    const track = diagnostic.field_path.find(item => scalarTracks.some(row => row.key === item)) as ScalarTrack | undefined
    if (track) { setActiveTrack(track); setMode('condition') }
    if (handle) {
      setSelection([handle]); setAnchor(handle); setFocus({ handle, track: track ?? activeTrack })
      setNarrowView('matrix'); setReveal(value => ({ revision: value.revision + 1, takeFocus: true })); setEditorPanel(null)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      if (event.nativeEvent.isComposing) return
      event.preventDefault()
      if (saving || viewportActive || editorPanel || leaveOpen) return
      if (localPreview || unpreviewed) cancelLocalPreview()
      else leave()
      return
    }
    if (event.defaultPrevented || event.nativeEvent.isComposing || saving || editorPanel || leaveOpen) return
    const target = event.target as HTMLElement
    if (target.closest('input, textarea, select, [contenteditable="true"]')) return
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); event.stopPropagation(); if (event.shiftKey) redo(); else undo(); return }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'y') { event.preventDefault(); event.stopPropagation(); redo(); return }
  }

  const addMergeSource = async () => {
    setBusy(true)
    setRequestError('')
    try {
      const next = await onAddMergeSource(visibleDocument)
      if (next) {
        setMergeSourceSnapshot(next)
        setGraphDirty(true)
      }
    } catch (error) {
      setRequestError(requestErrorText(error))
    } finally {
      setBusy(false)
    }
  }

  const requestSave = async () => {
    if (busy || mergeDirty || unpreviewed || viewportActive || saving) return
    setSaving(true)
    const requestId = ++previewRequest.current
    setBusy(true); setRequestError('')
    try {
      const preview = pendingRef.current?.preview ?? ('normalized_document' in committedProjection && !graphDirty ? committedProjection : await onPreview(document))
      if (requestId !== previewRequest.current) return
      if (diagnosticsHaveError(preview)) { setRequestError('请先修正当前操作的问题，再采用。'); return }
      await onApply(preview)
    } catch (error) { if (requestId === previewRequest.current) setRequestError(requestErrorText(error)) }
    finally { if (requestId === previewRequest.current) { setBusy(false); setSaving(false) } }
  }

  const leave = () => {
    if (saving || viewportActive) return
    if (dirty || graphDirty || localPreview || unpreviewed || mergeDirty || busy || viewportActive) setLeaveOpen(true)
    else onCancel()
  }

  const localImpact = localPreview ? {
    current: localPreview.preview.residues.filter((item) => item.state !== 'pending-delete').length,
    inserted: localPreview.preview.residues.filter((item) => item.state === 'inserted').length,
    deleted: localPreview.preview.residues.filter((item) => item.state === 'pending-delete').length,
    cleared: Object.values(localPreview.preview.tracks).flatMap((track) => track.values).filter((item) => item.state === 'cleared').length,
  } : undefined

  const selectedValue = (track: ScalarTrack) => {
    const values = selection.map(handle => cellDrafts.has(`${handle}:${track}`) ? cellDrafts.get(`${handle}:${track}`) : trackMaps.get(track)?.get(handle)?.value ?? null)
    return values.length && values.every(value => value === values[0]) && values[0] !== null ? String(values[0]) : ''
  }
  const selectionKey = selection.join(',')
  const sequenceSelection = selectedValue('sequence'), ssSelection = selectedValue('secondary_structure'), sasaSelection = selectedValue('sasa')
  useLayoutEffect(() => { setSequenceValue(sequenceSelection); setSsValue(ssSelection); setSasaValue(sasaSelection) }, [sequenceSelection, ssSelection, sasaSelection, focus.handle, selectionKey])
  useEffect(() => { setFunctionValue(focusedFunction?.label ?? '') }, [focusedFunction?.label, focus.handle])
  const selectedCoordinateRows = projection.tracks.coordinates.values.filter(row => selection.includes(row.residue_handle))
  const selectedAtoms = selectedCoordinateRows.flatMap(row => typeof row.value === 'object' && row.value !== null ? row.value.atoms : [])
  const centroid: [number, number, number] | undefined = selectedAtoms.length ? [0, 1, 2].map(axis => selectedAtoms.reduce((sum, atom) => sum + atom.coordinates[axis], 0) / selectedAtoms.length) as [number, number, number] : undefined
  const beginTransform = () => { setViewportActive(true); transformStart.current = { document: desiredDocument.current, pending: pendingRef.current } }
  const previewTransform = (transform: PromptRigidTransform) => {
    const base = transformStart.current?.document ?? desiredDocument.current
    return propose({ ...base, rigid_transforms: [...base.rigid_transforms ?? [], transform] }, '结构变换')
  }
  const cancelTransform = () => {
    previewRequest.current += 1
    setViewportActive(false)
    const start = transformStart.current
    if (!start) return
    desiredDocument.current = start.document; pendingRef.current = start.pending
    setLocalPreview(start.pending); setBusy(false); setUnpreviewed(false); setRequestError(''); transformStart.current = undefined
  }
  const selectStructure = (residues: Array<{ chain: string; resi: number }>, mode: 'replace' | 'add' | 'remove') => {
    const picked = projection.residues.filter(item => residues.some(residue => residue.chain === item.chain_id && residue.resi === item.position)).map(item => item.residue_handle)
    setSelection(current => mode === 'replace' ? picked : mode === 'add' ? [...new Set([...current, ...picked])] : current.filter(handle => !picked.includes(handle)))
    if (picked[0]) { setFocus(current => ({ ...current, handle: picked[0] })); setAnchor(picked[0]) }
    setReveal(value => ({ revision: value.revision + 1, takeFocus: false }))
  }

  return <div ref={studio} className="prompt-studio" tabIndex={0} onKeyDown={onKeyDown}>
    <header className="ps-header">
      <button className="ps-icon-button" aria-label="返回 Workflow" disabled={saving || viewportActive} onClick={leave}><ChevronLeft size={18} /></button>
      <div><span className="ps-kicker">PROTEINPROMPT STUDIO</span><h1>ProteinPrompt 编辑</h1></div>
      <span className="ps-session-state"><i />{dirty || graphDirty ? '有未保存修改' : 'Authoring Snapshot'}</span>
      <button className="ps-button" disabled={busy || viewportActive || (!undoStack.current.length && !localPreview && !unpreviewed)} title={`Ctrl/⌘ Z · ${undoStack.current.at(-1)?.label ?? '取消当前操作'}`} onClick={undo}><RotateCcw size={14} /> 撤销</button><button className="ps-button" disabled={viewportActive || !redoStack.current.length || busy} title={`Ctrl/⌘ Shift Z · ${redoStack.current.at(-1)?.label ?? '重做'}`} onClick={redo}><RotateCw size={14} /> 重做</button>
      <button className="ps-primary" disabled={viewportActive || busy || unpreviewed || mergeDirty || Boolean(localPreview && diagnosticsHaveError(localPreview.preview))} title={mergeDirty ? '先预览合并表中的修改' : unpreviewed ? '先修正或重试当前输入' : '采用至流程；项目仍须手动保存'} onClick={() => void requestSave()}><Save size={14} /> {busy ? '处理中…' : '采用 ProteinPrompt'}</button>
    </header>

      {requestError && !editorPanel && <p className="ps-help" role="alert">{requestError}{unpreviewed && <><button onClick={() => matrixFailed.current ? void processMatrixQueue() : void propose(desiredDocument.current, '重试编辑')}>重试</button><button onClick={cancelLocalPreview}>取消本次编辑</button></>}</p>}<div className="ps-session-feedback" role="status">{busy ? '正在更新预览，可继续输入…' : status}</div>
    <div inert={saving} style={{ display: 'contents' }}>
    {unpreviewed && !busy && !editorPanel && JSON.stringify(chainRows) !== JSON.stringify((visibleDocument.chains ?? []).map(chain => ({ chain_id: chain.chain_id, length: String(chain.length) }))) && <div className="ps-pending-bar" role="status"><span>Chain 布局修改尚未预览，请先完成或取消，再编辑矩阵。</span><button onClick={() => setEditorPanel('layout')}>继续布局编辑</button><button onClick={cancelLocalPreview}>取消本次编辑</button></div>}
    {projection.baseline_diagnostics.length > 0 && <section className="ps-help" role="status"><strong>无可比较的旧结果</strong>{projection.baseline_diagnostics.map((item, index) => <p key={index}>{diagnosticText(item, displayLocators)}</p>)}</section>}
    <nav className="ps-modebar" aria-label="Prompt Studio 模式">
      <button disabled={viewportActive || saving} className={mode === 'layout' ? 'active' : ''} onClick={() => { setMode('layout'); setActiveTrack('sequence'); setEditorPanel('layout') }}>布局</button>
      <button disabled={viewportActive || saving} className={mode === 'condition' ? 'active' : ''} onClick={() => { setMode('condition'); setActiveTrack('sequence') }}>条件</button>
      <button disabled={viewportActive || saving || !hasCoordinates} className={mode === 'structure' ? 'active' : ''} title={hasCoordinates ? '' : '当前 Prompt 没有 Coordinates'} onClick={() => { setMode('structure'); setActiveTrack('coordinates'); setNarrowView('structure') }}>结构</button>
      <span>有序残基、条件轨道与结构定位共享同一 residue axis</span>
    </nav>

    <main className="ps-main">
      <section className="ps-summarybar">
        <div><span>当前 Prompt</span><strong>{committedHandles.size} residues</strong></div>
        <div><span>Source</span><strong>{String(snapshot.source.kind).toUpperCase()} · {[...new Set(projection.residues.map((item) => item.chain_id))].join(', ')}</strong></div>
        <div><span>Function tuples</span><strong>{projection.function_annotations.filter((item) => item.state !== 'pending-delete').length}</strong></div>
        <div><span>轨道状态</span><strong>{scalarTracks.map(({ key }) => `${key}: ${projection.tracks[key].present ? `${projection.tracks[key].values.filter(item => item.value !== null).length} specified` : 'absent'}`).join(' · ')}</strong></div>
      </section>

      <section className="ps-selectionbar" aria-label="当前选择">
        <span className="ps-kicker">SELECTION</span><strong>{selectedText}</strong><small>{selection.length} selected</small>
        <button disabled={viewportActive || saving} onClick={() => { setSelection([]); setMatrixCells([]) }}>清除选择</button><button disabled={viewportActive || !selection.length} onClick={() => { setNarrowView('matrix'); setReveal(value => ({ revision: value.revision + 1, takeFocus: true })) }}>定位选区</button><button disabled={viewportActive || !hasCoordinates || !selection.length} onClick={() => viewer.current?.frameSelection()}>聚焦结构</button>
      </section>

      <div className="ps-pane-switch" role="tablist" aria-label="工作区域"><button role="tab" disabled={viewportActive || saving} aria-selected={narrowView === 'matrix'} onClick={() => setNarrowView('matrix')}>残基矩阵</button><button role="tab" aria-selected={narrowView === 'structure'} disabled={viewportActive || saving || !hasCoordinates} onClick={() => setNarrowView('structure')}>结构视图</button></div>
      <div className={`ps-workgrid view-${narrowView} ${hasCoordinates ? '' : 'without-structure'}`} style={{ '--structure-width': `${structureWidth}%` } as CSSProperties}>
        {hasCoordinates && <><aside className="ps-structure-card">
          <header><span className="ps-kicker">STRUCTURE</span><strong>当前 Prompt · {selectedText}</strong></header>
          <StructureViewer ref={viewer} structure={projectionStructure} residueLabel={structureResidueLabel} selectedResidues={selectedPositions} onSelectResidue={selectFromStructure} onSelectResidues={selectStructure} pivot={transformOrigin ?? centroid} viewportEdit={{ enabled: !saving && !localPreview && !matrixProcessing.current && !unpreviewed, origin: transformOrigin ?? centroid, residueIds: selection.map(handle => residueIdByHandle.get(handle)!).filter(Boolean), blockedReason: !selection.length ? '先选择残基' : selectedCoordinateRows.some(row => row.value === null) ? '选区含无坐标残基，请先移除' : undefined, busy, onBegin: beginTransform, onPreviewTransform: previewTransform, onConfirm: async () => { const pending = pendingRef.current; if (!pending || diagnosticsHaveError(pending.preview)) return false; acceptPreview(pending); transformStart.current = undefined; setViewportActive(false); return true }, onCancel: cancelTransform }} />
          <small>{selectedText}</small>
        </aside><div className="ps-pane-divider" role="separator" aria-label="调整结构与矩阵宽度" aria-orientation="vertical" aria-valuemin={20} aria-valuemax={60} aria-valuenow={structureWidth} tabIndex={0} onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); setStructureWidth(width => Math.max(20, Math.min(60, width + (event.key === 'ArrowLeft' ? -2 : 2)))) } }} onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId) }} onPointerMove={event => { if (!event.currentTarget.hasPointerCapture(event.pointerId)) return; const rect = event.currentTarget.parentElement!.getBoundingClientRect(); setStructureWidth(Math.max(20, Math.min(60, (event.clientX - rect.left) / rect.width * 100))) }} onPointerUp={event => event.currentTarget.releasePointerCapture(event.pointerId)} /></>}
        <section className="ps-ledger" aria-label="Residue ledger">
          <header className="ps-ledger-header"><div><span className="ps-kicker">RESIDUE MATRIX</span><h2>共享残基矩阵</h2></div><div className="ps-ledger-controls"><button onClick={() => setLegendOpen(open => !open)}>显示轨道 / 状态</button></div></header>
          {legendOpen && <div className="ps-state-legend">{trackRows.map(row => <label key={row.key}><input type="checkbox" checked={!hiddenTracks.has(row.key)} onChange={() => setHiddenTracks(current => { const next = new Set(current); if (next.has(row.key)) next.delete(row.key); else next.add(row.key); return next })} />{row.label}</label>)}{states.map(state => <span key={state}>{state}</span>)}</div>}
          <div className="ps-matrix-tools" aria-label="选区操作">
            <strong>{trackRows.find(row => row.key === activeTrack)?.label} · {selection.length} 残基</strong>
            {activeTrack !== 'function' && <><button disabled={!selection.length || operationBlocked || Boolean(localPreview)} onClick={() => updateTrack(activeTrack, 'preserve')}>Preserve</button><button disabled={!selection.length || operationBlocked || Boolean(localPreview)} onClick={() => matrixCells.length ? clearCells(matrixCells) : updateTrack(activeTrack, 'clear')}>Clear</button></>}
            {activeTrack === 'sequence' && <label>氨基酸<input aria-label="指定氨基酸" placeholder={selection.length > 1 ? '多个值 / Mask' : 'Mask'} maxLength={1} value={sequenceValue} onChange={event => setSequenceValue(event.target.value.toUpperCase())} /><button disabled={!selection.length || viewportActive || Boolean(localPreview) || !aminoAcids.has(sequenceValue)} onClick={() => editMatrix(selection.map(handle => ({ handle, track: 'sequence', value: sequenceValue })))}>Specify</button></label>}
            {activeTrack === 'secondary_structure' && <label>SS8<select aria-label="指定二级结构" value={ssValue} onChange={event => setSsValue(event.target.value)}><option value="">多个值 / Mask</option>{[...ss8Codes].map(value => <option key={value}>{value}</option>)}</select><button disabled={!selection.length || !ss8Codes.has(ssValue) || operationBlocked || Boolean(localPreview)} onClick={() => editMatrix(selection.map(handle => ({ handle, track: 'secondary_structure', value: ssValue })))}>Specify</button></label>}
            {activeTrack === 'sasa' && <label>SASA Å²<input aria-label="指定 SASA" type="number" min="0" placeholder="多个值 / Mask" value={sasaValue} onChange={event => setSasaValue(event.target.value)} /><button disabled={!selection.length || !sasaInputValid || operationBlocked || Boolean(localPreview)} onClick={() => editMatrix(selection.map(handle => ({ handle, track: 'sasa', value: Number(sasaValue) })))}>Specify</button></label>}
            {activeTrack === 'function' && <button disabled={!selection.length} onClick={() => setEditorPanel('function')}>编辑 Function 区间</button>}
            <button disabled={operationBlocked || !selection.length} onClick={() => { setBatchValues({ sequence: sequenceSelection, coordinates: '', secondary_structure: ssSelection, sasa: sasaSelection }); setEditorPanel('batch') }}>批量修改</button><button disabled={viewportActive || busy} onClick={() => setEditorPanel('layout')}>插入 / 删除</button><button disabled={viewportActive || busy} onClick={() => setEditorPanel('random')}>随机操作</button><button disabled={viewportActive || busy} onClick={() => setEditorPanel('merge')}>合并来源</button><button disabled={viewportActive || busy} onClick={() => setEditorPanel('evidence')}>条件详情</button>
          </div>
          <ResidueMatrix projection={projection} locators={displayLocators} selection={selection} focus={focus} hiddenTracks={hiddenTracks} disabled={saving || viewportActive || Boolean(localPreview) || (busy || unpreviewed && !matrixFailed.current) && !matrixProcessing.current} reveal={reveal} drafts={cellDrafts} onSelection={chooseMatrix} onEdit={editMatrix} onOpen={openCell} onClear={clearCells} />
          {localPreview && !viewportActive && <div className="ps-pending-bar" role="status"><span>{localPreview.title} · {localPreview.preview.changes.length} 处变化</span><button onClick={cancelLocalPreview}>取消操作</button><button disabled={busy || unpreviewed || diagnosticsHaveError(localPreview.preview)} onClick={applyLocalPreview}>应用操作</button>{localPreview.preview.diagnostics.map((item, index) => <button key={index} onClick={() => focusDiagnostic(item)}>{diagnosticText(item, displayLocators)}</button>)}</div>}
        </section>
      </div>
        {editorPanel && <InteractionDialog title={{ batch: '多轨批量修改', function: 'Function 区间', layout: '残基布局', random: '随机操作', structure: '精确结构参数', merge: '合并来源', evidence: '有效条件详情' }[editorPanel]} className="ps-tools-dialog" onClose={() => { if (localPreview) cancelLocalPreview(); else setEditorPanel(null) }}><div className="ps-editor">
          {requestError && <p className="ps-help" role="alert">{requestError}</p>}
          <header><button className="ps-button" onClick={() => setEditorPanel(null)}>返回矩阵</button><span className="ps-kicker">选区操作</span><h2>{trackRows.find((item) => item.key === activeTrack)?.label ?? activeTrack}</h2><small>{selectedText}</small></header>
          {editorPanel === 'batch' && <section className="ps-editor-section ps-batch-editor"><p>对 {selectedText} 的 {selection.length} 个残基一起修改。未选择操作的轨道保持当前值。</p>{scalarTracks.map(row => <label key={row.key}><strong>{row.label}</strong><select aria-label={`${row.label} 批量动作`} value={batchActions[row.key]} onChange={event => setBatchActions(current => ({ ...current, [row.key]: event.target.value as TrackAction | 'unchanged' }))}><option value="unchanged">不修改</option><option value="preserve">Preserve</option><option value="clear">Clear / Mask</option>{row.key !== 'coordinates' && <option value="replace">指定值</option>}</select>{batchActions[row.key] === 'replace' && <input aria-label={`${row.label} 批量值`} value={batchValues[row.key]} placeholder="明确输入新值" onChange={event => setBatchValues(current => ({ ...current, [row.key]: event.target.value }))} />}</label>)}<button disabled={operationBlocked || !selection.length || Object.values(batchActions).every(action => action === 'unchanged')} onClick={() => {
            try {
              let next = visibleDocument
              for (const row of scalarTracks) {
                const action = batchActions[row.key]
                if (action === 'unchanged') continue
                const value = action === 'replace' ? parseMatrixValue(row.key, batchValues[row.key]) : undefined
                const ids = selection.map(handle => residueIdByHandle.get(handle)!)
                next = trackDocument(next, ids, row.key, value === null ? 'clear' : action, value ?? undefined)
              }
              void propose(next, `多轨修改 · ${selection.length} 个残基`)
            } catch (reason) { setRequestError(requestErrorText(reason)) }
          }}>预览批量修改</button></section>}
          {editorPanel === 'function' && <div className="ps-editor-section"><span className="ps-kicker">FUNCTION TUPLE</span>{focusedFunctionOptions.length > 0 && <div className="ps-function-options">{focusedFunctionOptions.map(({ annotation, key }) => <button key={key} className={focusedFunction === annotation ? 'active' : ''} onClick={() => { setFunctionTargetKey(key); setFunctionValue(annotation.label); setFunctionStart(''); setFunctionEnd(''); setFunctionSplit('') }}><strong>{annotation.label}</strong><small>{displayLocators.get(annotation.start_residue_handle)}–{displayLocators.get(annotation.end_residue_handle)}</small></button>)}</div>}<label><span>Label</span><input aria-label="Function label" maxLength={256} value={functionValue} onChange={(event) => setFunctionValue(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing && functionValue.trim() && !busy) { event.preventDefault(); addFunction() } }} /><button disabled={!selection.length || operationBlocked || !functionValue.trim() || functionValue.length > 256 || (!focusedFunction && !functionSelectionValid)} onClick={() => addFunction()}>{focusedFunction ? 'Replace' : 'Add'}</button></label>{!focusedFunction && selection.length > 1 && !functionSelectionValid && <p className="ps-help"><Info size={13} /> Function 区间必须是同一条链上的连续残基。</p>}{focusedFunction && <div className="ps-function-endpoints"><label>Start<select aria-label="Function 起点" value={functionStart || residueIdByHandle.get(focusedFunction.start_residue_handle)} onChange={event => setFunctionStart(event.target.value)}>{currentCommittedResidues.map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select></label><label>End<select aria-label="Function 终点" value={functionEnd || residueIdByHandle.get(focusedFunction.end_residue_handle)} onChange={event => setFunctionEnd(event.target.value)}>{currentCommittedResidues.map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select></label><button disabled={busy} onClick={() => updateFunctionInterval(false)}>预览端点修改</button><label>Split after<select aria-label="Function 拆分点" value={functionSplit} onChange={event => setFunctionSplit(event.target.value)}><option value="">选择拆分点</option>{currentCommittedResidues.slice(currentCommittedResidues.findIndex(item => item.residue_id === (functionStart || residueIdByHandle.get(focusedFunction.start_residue_handle))), currentCommittedResidues.findIndex(item => item.residue_id === (functionEnd || residueIdByHandle.get(focusedFunction.end_residue_handle)))).map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select></label><button disabled={busy || !functionSplit} onClick={() => updateFunctionInterval(true)}>预览拆分</button></div>}<button className="ps-danger-wide" disabled={!focusedFunction || operationBlocked} onClick={deleteFunction}><Trash2 size={13} /> Delete exact tuple</button></div>}
    {canEditChains && editorPanel === 'layout' && <section className="ps-chain-editor" aria-label="Chain declarations">
      <strong>Chain declarations</strong>
      {chainRows.map((chain, index) => <div key={index}>
        <input aria-label={`Chain ${index + 1} ID`} maxLength={1} value={chain.chain_id} disabled={operationBlocked} onChange={(event) => { setUnpreviewed(true); setChainRows(chainRows.map((item, i) => i === index ? { ...item, chain_id: event.target.value } : item)) }} />
        <input aria-label={`Chain ${index + 1} length`} type="number" min="1" max="2000000" step="1" value={chain.length} disabled={operationBlocked} onChange={(event) => { setUnpreviewed(true); setChainRows(chainRows.map((item, i) => i === index ? { ...item, length: event.target.value } : item)) }} />
        <button aria-label={`Move chain ${index + 1} up`} disabled={operationBlocked || index === 0} onClick={() => { setUnpreviewed(true); setChainRows(chainRows.map((item, i) => i === index - 1 ? chain : i === index ? chainRows[index - 1] : item)) }}>↑</button>
        <button aria-label={`Move chain ${index + 1} down`} disabled={operationBlocked || index === chainRows.length - 1} onClick={() => { setUnpreviewed(true); setChainRows(chainRows.map((item, i) => i === index + 1 ? chain : i === index ? chainRows[index + 1] : item)) }}>↓</button>
        <button aria-label={`Delete chain ${index + 1}`} disabled={operationBlocked} onClick={() => { setUnpreviewed(true); setChainRows(chainRows.filter((_, i) => i !== index)) }}>删除</button>
      </div>)}
      <button disabled={operationBlocked} onClick={() => { setUnpreviewed(true); setChainRows([...chainRows, { chain_id: '', length: '' }]) }}>添加 Chain</button>
      <button disabled={operationBlocked || !chainsReady} onClick={() => void propose({ ...visibleDocument, chains: chainRows.map((chain) => ({ chain_id: chain.chain_id, length: Number(chain.length) })) }, '更新 Chain declarations')}>预览 Chains</button>
    </section>}
          {editorPanel === 'layout' && <div className="ps-editor-section ps-layout-actions"><span className="ps-kicker">ORDERED RESIDUES</span><div className="ps-insert-fields"><input aria-label="插入数量" type="number" min="1" value={insertCount} onChange={(event) => setInsertCount(event.target.value)} /><input aria-label="插入序列" placeholder="Mask 或等长序列" value={insertSequence} onChange={(event) => setInsertSequence(event.target.value.toUpperCase())} /></div>{!insertionInputValid && <p className="ps-help"><Info size={13} /> 序列必须为空、单字母，或与插入数量等长。</p>}<button disabled={!selection.length || operationBlocked || !insertionInputValid} onClick={() => insertResidues()}><Plus size={13} /> Insert after focus</button><button className="danger" disabled={!selection.length || operationBlocked || committedHandles.size === selection.length} onClick={deleteSelection}><Trash2 size={13} /> Delete selected</button></div>}

          {editorPanel === 'structure' && <PromptTransformEditor projection={projection} selection={selection} document={visibleDocument} busy={busy} mode={transformMode} axis={transformAxis} amount={transformAmount} onAmount={setTransformAmount} onMode={setTransformMode} onAxis={setTransformAxis} onOrigin={setTransformOrigin} onPreview={(next, title) => void propose(next, title)} />}
          {editorPanel === 'random' && activeTrack !== 'function' && <section className="ps-editor-section" aria-label="随机条件">
            <span className="ps-kicker">SEEDED RANDOM {mode === 'layout' ? 'INSERT' : 'MASK'}</span>
            <label>Count<input aria-label="随机数量" type="number" min="0" step="1" value={randomCount} onChange={event => setRandomCount(event.target.value)} /></label>
            <label>Seed<input aria-label="随机 seed" type="number" min="0" step="1" value={randomSeed} onChange={event => setRandomSeed(event.target.value)} /></label>
            <label>范围<select aria-label="随机范围" value={randomScope} onChange={event => setRandomScope(event.target.value as typeof randomScope)}><option value="all">全部符合条件的位置</option><option value="selection">{mode === 'layout' ? '选区所在链' : '仅选区内已指定值'}</option></select></label>
            <div className="ps-action-row"><button disabled={busy || Boolean(localPreview) || !randomSeed.trim() || !randomCount.trim() || randomScope === 'selection' && !selection.length} onClick={() => randomOperation()}>预览随机操作</button></div>
            <p className="ps-help">已采用结果可直接编辑。再次随机基于当前内容作为新操作；采用前可取消预览。</p>
            {(visibleDocument.applied_random_operations ?? []).map(({ operation, realized_residue_ids }, index) => <div key={index} className="ps-random-operation"><span>{index + 1} · {operation.kind} · seed {operation.seed} · {operation.count}</span><p className="ps-help">实际位置：{realized_residue_ids.map(id => { const residue = projection.residues.find(item => item.residue_id === id && item.state !== 'pending-delete'); return residue ? displayLocators.get(residue.residue_handle) : '已删除位置' }).join(', ')}</p></div>)}
          </section>}
          {editorPanel === 'evidence' && <section className="ps-editor-section ps-effective-conditioning" aria-label="工具有效条件">
            <span className="ps-kicker">TOOL CONDITIONING</span>
            <p className="ps-help">已启用模块的 Adapter / Operation 输入投影；不会更改科学 Prompt。运行还需要实际模型和执行配置。</p>
            {projection.tool_projections.length === 0 ? <p className="ps-help">当前没有启用的工具条件投影。</p> : projection.tool_projections.map(item => <section key={item.projection_id}><h4>{item.title}</h4><pre>{JSON.stringify(item.value, null, 2)}</pre></section>)}
          </section>}
          {editorPanel === 'merge' && <><button disabled={busy} onClick={() => void addMergeSource()}>添加合并来源</button>
          <PromptMergeEditor key={mergeRevision} initialDraft={mergeDraft.current} onDraftState={draft => { mergeDraft.current = draft }} onDraftChange={setMergeDirty} sources={mergeSourceSnapshot.source.merge_sources ?? []} projection={projection} document={visibleDocument} busy={busy} diagnostics={localPreview?.preview.diagnostics ?? []} onTargetSelection={ids => { const handles = projection.residues.filter(item => ids.includes(item.residue_id) && item.state !== 'pending-delete').map(item => item.residue_handle); setSelection(handles); if (handles.length) { setAnchor(handles[0]); setFocus(current => ({ ...current, handle: handles[0] })) } }} onPreview={(next, title) => { setMergeDirty(false); void propose(next, title) }} /></>}

          {localPreview && localImpact && <section className="ps-local-preview" aria-label="即时预览">
            <span className="ps-kicker">UNAPPLIED PREVIEW</span><h3>即时预览 · {localPreview.title}</h3><p>可继续编辑其他轨道；整组操作共享此预览。应用后可继续编辑；Esc 先取消当前操作，再按一次返回矩阵。</p>
            <div className="ps-impact"><span>Current<strong>{localImpact.current}</strong></span><span>Inserted<strong>{localImpact.inserted}</strong></span><span>Tombstones<strong>{localImpact.deleted}</strong></span><span>Cleared tracks<strong>{localImpact.cleared}</strong></span></div>
            <ul>{localPreview.preview.changes.map((change, index) => <li key={`change-${index}`}>{previewChangeText(change, committedProjection, localPreview.preview, displayLocators)}</li>)}{localPreview.preview.function_annotations.filter((item) => ['inserted', 'pending-delete'].includes(item.state)).map((item, index) => <li key={`function-${index}`}>Function · {item.label} · {displayLocators.get(item.start_residue_handle)}–{displayLocators.get(item.end_residue_handle)} · {item.state}</li>)}</ul>
            <div className="ps-merge-impact">{localPreview.preview.source_merges.map((merge, index) => <details key={index}><summary>合并 {index + 1}：新增、轨道 / Mask 与注释决策</summary><pre>{JSON.stringify(merge, null, 2)}</pre></details>)}</div><ul>{localPreview.preview.diagnostics.map((item, index) => <li key={index}><button className="ps-diagnostic" onClick={() => focusDiagnostic(item)}>{diagnosticText(item, displayLocators)}</button></li>)}</ul>
            <div><button onClick={cancelLocalPreview}><X size={13} /> 取消</button><button className="apply" disabled={busy || diagnosticsHaveError(localPreview.preview)} onClick={applyLocalPreview}><Check size={13} /> 应用操作</button></div>
          </section>}
        </div></InteractionDialog>}
    </main>

    </div>
    {leaveOpen && <InteractionDialog title="离开 Prompt 编辑" className="ps-leave-dialog" onClose={() => setLeaveOpen(false)}><h2>尚有未采用的编辑</h2><p>继续编辑会保留当前输入与选区。</p><footer><button onClick={() => setLeaveOpen(false)}>继续编辑</button><button className="danger" onClick={onCancel}>放弃修改</button><button className="confirm" disabled={busy || mergeDirty || unpreviewed} onClick={() => { setLeaveOpen(false); void requestSave() }}>采用并返回</button></footer></InteractionDialog>}
  </div>
}
