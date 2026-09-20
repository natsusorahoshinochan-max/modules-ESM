import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { Check, ChevronLeft, Eye, EyeOff, Info, Plus, RotateCcw, Save, Trash2, X } from 'lucide-react'
import type { JsonObject, PromptAuthoringDocument, PromptDiagnostic, PromptDocumentFunctionAnnotation, PromptFunctionAnnotation, PromptPreview, PromptRandomOperation, PromptSnapshot, PromptTrackEdit, PromptTrackKey, PromptTrackValue } from './protocol/client'
import { StructureViewer } from './StructureViewer'
import { PromptTransformEditor } from './PromptTransformEditor'
import { PromptMergeEditor } from './PromptMergeEditor'
import { promptStructurePdb } from './prompt-structure'
import { deletePromptResidues, insertPromptResidues } from './prompt-layout'
import './prompt-studio.css'

type ScalarTrack = 'sequence' | 'coordinates' | 'secondary_structure' | 'sasa'
type Track = ScalarTrack | 'function'
type TrackAction = 'preserve' | 'clear' | 'replace'
type Projection = PromptSnapshot | PromptPreview
type LocalPreview = { title: string; preview: PromptPreview; insertedHandles: string[]; insertedResidueIds: string[]; insertAnchor?: string }
type UndoEntry = { document: PromptAuthoringDocument; projection: Projection; selection: string[]; anchor: string; focus: { handle: string; track: Track } }
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
const aminoAcids = new Set('ACDEFGHIKLMNPQRSTVWY'.split(''))
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
  const [savePreview, setSavePreview] = useState<PromptPreview>()
  const [selection, setSelection] = useState<string[]>(initiallyEdited)
  const [anchor, setAnchor] = useState(initialHandle)
  const [focus, setFocus] = useState<{ handle: string; track: Track }>({ handle: initialHandle, track: 'sequence' })
  const [activeTrack, setActiveTrack] = useState<Track>('sequence')
  const [mode, setMode] = useState<'layout' | 'condition' | 'structure'>(snapshot.source.kind === 'blank' ? 'layout' : 'condition')
  const [hiddenTracks, setHiddenTracks] = useState<Set<Track>>(new Set())
  const [sequenceValue, setSequenceValue] = useState('A')
  const [ssValue, setSsValue] = useState('H')
  const [sasaValue, setSasaValue] = useState('32')
  const [functionValue, setFunctionValue] = useState('binding_site')
  const [functionTargetKey, setFunctionTargetKey] = useState('')
  const [functionStart, setFunctionStart] = useState('')
  const [functionEnd, setFunctionEnd] = useState('')
  const [functionSplit, setFunctionSplit] = useState('')
  const [randomSeed, setRandomSeed] = useState('0')
  const [randomCount, setRandomCount] = useState('1')
  const [randomScope, setRandomScope] = useState<'all' | 'selection'>('all')
  const [randomEditing, setRandomEditing] = useState<number>()
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
  const undoStack = useRef<UndoEntry[]>([])
  const previewRequest = useRef(0)
  const keyboardEntry = useRef<{ key: string; text: string } | undefined>(undefined)

  useEffect(() => {
    if (!dirty && !graphDirty && !localPreview) return
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [dirty, graphDirty, localPreview])

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
  const visibleRows = trackRows.filter(({ key }) => !hiddenTracks.has(key))
  const trackMaps = useMemo(() => new Map(scalarTracks.map(({ key }) => [key, new Map(projection.tracks[key].values.map((item) => [item.residue_handle, item]))])), [projection])
  const rowIndex = useMemo(() => new Map(orderedResidues.map((item, index) => [item.residue_handle, index])), [orderedResidues])
  const functionCells = useMemo(() => {
    const cells = new Map<string, PromptFunctionAnnotation[]>()
    for (const annotation of projection.function_annotations) {
      const start = rowIndex.get(annotation.start_residue_handle)
      const end = rowIndex.get(annotation.end_residue_handle)
      if (start === undefined || end === undefined) continue
      const covered = Array.from({ length: end - start + 1 }, (_, index) => start + index)
      for (const index of covered) {
        const handle = orderedResidues[index].residue_handle
        cells.set(handle, [...(cells.get(handle) ?? []), annotation])
      }
    }
    return cells
  }, [orderedResidues, projection.function_annotations, rowIndex])
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
  const projectionPdb = useMemo(() => promptStructurePdb(projection), [projection])
  const randomInsertHandles = new Set(projection.random_selections.filter((operation) => operation.kind === 'insert').flatMap((operation) => operation.realized_residue_handles))
  const deletionBlocked = selection.some((handle) => randomInsertHandles.has(handle))
  const insertionBlocked = randomInsertHandles.has(focus.handle)
  const randomLayoutReason = '随机生成残基保留 seed 规则，可编辑轨道值，但不能单独删除或作为插入锚点。'
  const targetIntent = () => visibleDocument.target_residues ?? (projection.merge_targets[0]?.residues ?? committedProjection.merge_targets[0]?.residues ?? []).filter((item) => item.state !== 'pending-delete' && !randomInsertHandles.has(item.residue_handle)).map((item) => ({ residue_id: item.residue_id, origin: 'source' as const }))
  const canEditChains = ['blank', 'fasta'].includes(String(snapshot.source.kind)) || document.chains !== undefined || !committedProjection.residues.length
  const chainsReady = chainRows.length > 0 && chainRows.every((chain) => chain.chain_id.length > 0 && /^\d+$/.test(chain.length) && Number(chain.length) > 0)
  const operationBlocked = busy
  const insertionCount = Number(insertCount)
  const insertionInputValid = Number.isInteger(insertionCount) && insertionCount > 0 && (insertSequence.length === 0 || insertSequence.length === 1 || insertSequence.length === insertionCount) && [...insertSequence].every((letter) => aminoAcids.has(letter))
  const sasaInputValid = sasaValue.trim() !== '' && Number(sasaValue) >= 0

  const propose = async (nextDocument: PromptAuthoringDocument, title: string, insertedResidueIds: string[] = [], insertAnchor?: string) => {
    const requestId = ++previewRequest.current
    setBusy(true)
    setSavePreview(undefined)
    setRequestError('')
    try {
      const preview = await onPreview(nextDocument)
      if (requestId !== previewRequest.current) return
      const handleById = new Map(preview.residues.map((item) => [item.residue_id, item.residue_handle]))
      const insertedHandles = insertedResidueIds.map((residueId) => handleById.get(residueId)).filter((item): item is string => Boolean(item))
      setLocalPreview({ title, preview, insertedHandles, insertedResidueIds, insertAnchor })
    } catch (error) {
      if (requestId === previewRequest.current) setRequestError(requestErrorText(error))
    } finally {
      if (requestId === previewRequest.current) setBusy(false)
    }
  }

  const cancelLocalPreview = useCallback(() => {
    keyboardEntry.current = undefined
    previewRequest.current += 1
    setBusy(false)
    setLocalPreview(undefined)
    if (!committedHandles.has(focus.handle)) {
      const nextHandle = selection.find((handle) => committedHandles.has(handle)) ?? committedProjection.residues.find((item) => committedHandles.has(item.residue_handle))?.residue_handle ?? ''
      setSelection((current) => current.filter((handle) => committedHandles.has(handle)))
      setAnchor(nextHandle)
      setFocus((current) => ({ ...current, handle: nextHandle }))
    }
  }, [committedHandles, committedProjection.residues, focus.handle, selection])

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
  }, [anchor, currentHandles, projection.residues])

  const applyLocalPreview = () => {
    keyboardEntry.current = undefined
    const pending = localPreview
    if (!pending) return
    previewRequest.current += 1
    undoStack.current.push({ document, projection: committedProjection, selection, anchor, focus })
    setDocument(pending.preview.normalized_document)
    setCommittedProjection(pending.preview)
    setChainRows((pending.preview.normalized_document.chains ?? []).map((chain) => ({ chain_id: chain.chain_id, length: String(chain.length) })))
    const nextTargets = pending.preview.residues.filter((item) => item.state !== 'pending-delete').map((item) => item.residue_handle)
    if (pending.insertedHandles.length) {
      setSelection(pending.insertedHandles)
      setAnchor(pending.insertedHandles[0])
      setFocus({ handle: pending.insertedHandles[0], track: 'sequence' })
    } else {
      const retainedSelection = selection.filter((handle) => nextTargets.includes(handle))
      const nextFocus = nextTargets.includes(focus.handle) ? focus.handle : retainedSelection[0] ?? nextTargets[0] ?? ''
      setSelection(retainedSelection)
      setAnchor(nextFocus)
      setFocus((current) => ({ ...current, handle: nextFocus }))
    }
    setLocalPreview(undefined)
    setDirty(true)
    setGraphDirty(false)
  }

  const undo = () => {
    const previous = undoStack.current.pop()
    if (!previous) return
    setDocument(previous.document)
    setCommittedProjection(previous.projection)
    setSelection(previous.selection)
    setAnchor(previous.anchor)
    setFocus(previous.focus)
    setChainRows((previous.document.chains ?? []).map((chain) => ({ chain_id: chain.chain_id, length: String(chain.length) })))
    cancelLocalPreview()
    setSavePreview(undefined)
    setDirty(undoStack.current.length > 0)
  }

  const selectResidue = (handle: string, event: MouseEvent) => {
    if (!currentHandles.has(handle)) return
    const current = projection.residues.filter(item => currentHandles.has(item.residue_handle)).map(item => item.residue_handle)
    if (event.shiftKey) {
      const from = current.indexOf(anchor), to = current.indexOf(handle)
      setSelection(current.slice(Math.min(from, to), Math.max(from, to) + 1))
    } else if (event.metaKey || event.ctrlKey) {
      setSelection(selected => selected.includes(handle) ? selected.filter(item => item !== handle) : [...selected, handle])
      setAnchor(handle)
    } else if (!selection.includes(handle) || !event.currentTarget.getAttribute('data-cell') || event.currentTarget.getAttribute('data-cell')?.endsWith(`:${activeTrack}`)) {
      setSelection([handle]); setAnchor(handle)
    }
    setFocus(currentFocus => ({ ...currentFocus, handle }))
  }

  const updateTrack = (track: ScalarTrack, action: TrackAction, value?: string | number) => {
    if (!selection.length) return
    const residueIds = selection.map((handle) => residueIdByHandle.get(handle)).filter((item): item is string => Boolean(item))
    const label = scalarTracks.find((row) => row.key === track)?.label ?? track
    void propose(trackDocument(visibleDocument, residueIds, track, action, value), `${label} · ${action}`)
  }

  const deleteSelection = () => {
    if (deletionBlocked) { setRequestError(randomLayoutReason); return }
    const selectedIds = new Set(selection.map((handle) => residueIdByHandle.get(handle)).filter((item): item is string => Boolean(item)))
    const next = deletePromptResidues(visibleDocument, targetIntent(), selectedIds)
    void propose(next, `删除 ${selection.length} 个残基`)
  }

  const insertResidues = (count = insertionCount, rawSequence = insertSequence, anchorOverride?: string) => {
    const sequence = rawSequence.trim().toUpperCase()
    if (!Number.isInteger(count) || count < 1 || ![0, 1, count].includes(sequence.length) || ![...sequence].every((letter) => aminoAcids.has(letter))) return
    const anchorHandle = anchorOverride ?? focus.handle ?? selection.at(-1)
    if (!anchorHandle) return
    if (randomInsertHandles.has(anchorHandle)) { setRequestError(randomLayoutReason); return }
    const anchorResidue = projection.residues.find((item) => item.residue_handle === anchorHandle)
    if (!anchorResidue) return
    const replacedIds = anchorOverride ? localPreview?.insertedResidueIds ?? [] : []
    const baseDocument = deletePromptResidues(visibleDocument, targetIntent(), new Set(replacedIds))
    const orderedIds = projection.residues.filter(item => item.state !== 'pending-delete' && !replacedIds.includes(item.residue_id)).map(item => item.residue_id)
    const precedingIds = orderedIds.slice(0, orderedIds.indexOf(anchorResidue.residue_id) + 1)
    const insertedResidueIds = Array.from({ length: count }, () => `${anchorResidue.chain_id}:inserted.${crypto.randomUUID().replaceAll('-', '')}`)
    const letters = sequence.length === 1 ? Array(count).fill(sequence) : sequence.split('')
    const sequenceEdits = insertedResidueIds.map((residue_id, index) => letters[index] ? { track: 'sequence' as const, residue_id, action: 'replace' as const, value: letters[index] } : { track: 'sequence' as const, residue_id, action: 'clear' as const })
    const next = insertPromptResidues(baseDocument, baseDocument.target_residues!, precedingIds, insertedResidueIds, sequenceEdits)
    void propose(next, `插入 ${count} 个残基`, insertedResidueIds, anchorHandle)
  }

  const addFunction = (label = functionValue) => {
    if (!selection.length) return
    const replaceExisting = selection.length === 1 ? focusedFunction : undefined
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
    if (randomEditing === undefined || randomEditing >= operations.length) { setRandomEditing(operations.length); operations.push(operation) } else operations[randomEditing] = operation
    setRandomSeed(String(seed))
    void propose({ ...visibleDocument, random_operations: operations }, `随机 ${operation.kind} · seed ${seed}`)
  }

  const focusDiagnostic = (diagnostic: PromptDiagnostic) => {
    const handle = diagnostic.residue_handle
    const track = diagnostic.field_path.find(item => scalarTracks.some(row => row.key === item)) as ScalarTrack | undefined
    if (track) { setActiveTrack(track); setMode('condition') }
    if (handle) {
      setSelection([handle]); setAnchor(handle); setFocus({ handle, track: track ?? activeTrack })
      requestAnimationFrame(() => { const cell = documentQueryCell(handle, track ?? activeTrack); cell?.scrollIntoView({ block: 'nearest', inline: 'center' }); cell?.focus() })
    }
  }

  const moveFocus = (residueDelta: number, trackDelta: number) => {
    const handles = projection.residues.filter((item) => currentHandles.has(item.residue_handle)).map((item) => item.residue_handle)
    const tracks = visibleRows.map((item) => item.key)
    if (!tracks.length || !handles.length) return
    const nextHandle = handles[Math.max(0, Math.min(handles.length - 1, handles.indexOf(focus.handle) + residueDelta))]
    const nextTrack = tracks[Math.max(0, Math.min(tracks.length - 1, tracks.indexOf(focus.track) + trackDelta))]
    if (!nextHandle || !nextTrack) return
    setFocus({ handle: nextHandle, track: nextTrack })
    setActiveTrack(nextTrack)
    setSelection([nextHandle])
    setAnchor(nextHandle)
    requestAnimationFrame(() => documentQueryCell(nextHandle, nextTrack)?.focus())
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape' && savePreview) { event.preventDefault(); setSavePreview(undefined); return }
    if (event.key === 'Escape' && leaveOpen) { event.preventDefault(); setLeaveOpen(false); return }
    if (event.key === 'Escape' && localPreview) { event.preventDefault(); cancelLocalPreview(); return }
    const target = event.target as HTMLElement
    if (target.matches('input, textarea, select') || (target.matches('button') && !target.hasAttribute('data-cell'))) return
    if (busy) return
    if (event.key === 'Enter' && localPreview && !diagnosticsHaveError(localPreview.preview)) { event.preventDefault(); applyLocalPreview(); return }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(); return }
    if (event.key === 'ArrowLeft') { event.preventDefault(); moveFocus(-1, 0); return }
    if (event.key === 'ArrowRight') { event.preventDefault(); moveFocus(1, 0); return }
    if (event.key === 'ArrowUp') { event.preventDefault(); moveFocus(0, -1); return }
    if (event.key === 'ArrowDown') { event.preventDefault(); moveFocus(0, 1); return }
    if (event.key === 'Backspace' && activeTrack === 'sequence' && localPreview?.insertedHandles.length) { event.preventDefault(); setInsertSequence(''); void propose(trackDocument(localPreview.preview.normalized_document, localPreview.insertedResidueIds, 'sequence', 'clear'), `插入 ${localPreview.insertedHandles.length} 个残基`, localPreview.insertedResidueIds, localPreview.insertAnchor); return }
    if (mode === 'structure' && /^[grxyz]$/i.test(event.key)) {
      event.preventDefault()
      const key = event.key.toLowerCase()
      if (key === 'g' || key === 'r') setTransformMode(key === 'g' ? 'translate' : 'rotate')
      else setTransformAxis(key as 'x' | 'y' | 'z')
      return
    }
    if (mode === 'structure' && /^[0-9.-]$/.test(event.key)) { event.preventDefault(); setTransformAmount(event.key); globalThis.document.getElementById('prompt-transform-amount')?.focus(); return }
    if (mode === 'structure') return
    if (mode === 'layout' && event.key === '+') { event.preventDefault(); insertResidues(insertionCount, insertSequence, localPreview?.insertAnchor); return }
    if (mode === 'layout' && /^[1-9]$/.test(event.key) && activeTrack !== 'sasa' && activeTrack !== 'function') { event.preventDefault(); const count = Number(event.key); setInsertCount(event.key); if (localPreview?.insertedHandles.length) insertResidues(count, insertSequence, localPreview.insertAnchor); return }
    if (mode === 'layout') return
    const entryKey = `${focus.handle}:${activeTrack}:${selection.join(',')}`
    if (event.key === 'Backspace' && (activeTrack === 'sasa' || activeTrack === 'function') && keyboardEntry.current?.key === entryKey) {
      event.preventDefault()
      const text = keyboardEntry.current.text.slice(0, -1)
      keyboardEntry.current = { key: entryKey, text }
      if (activeTrack === 'sasa') { setSasaValue(text); updateTrack('sasa', text ? 'replace' : 'clear', text ? Number(text) : undefined) }
      else { setFunctionValue(text); if (text) addFunction(text); else deleteFunction() }
      return
    }
    if (event.key === 'Backspace' && activeTrack !== 'function') { event.preventDefault(); updateTrack(activeTrack, 'clear'); return }
    if (activeTrack === 'sequence' && aminoAcids.has(event.key.toUpperCase())) {
      event.preventDefault()
      const value = event.key.toUpperCase()
      if (localPreview?.insertedHandles.length) {
        setInsertSequence(value)
        void propose(trackDocument(localPreview.preview.normalized_document, localPreview.insertedResidueIds, 'sequence', 'replace', value), `插入 ${localPreview.insertedHandles.length} 个残基`, localPreview.insertedResidueIds, localPreview.insertAnchor)
      } else {
        setSequenceValue(value)
        updateTrack('sequence', 'replace', value)
      }
      return
    }
    if (activeTrack === 'secondary_structure' && ss8Codes.has(event.key.toUpperCase())) { event.preventDefault(); updateTrack('secondary_structure', 'replace', event.key.toUpperCase()); return }
    if (activeTrack === 'sasa' && /^[0-9.]$/.test(event.key)) { event.preventDefault(); const value = keyboardEntry.current?.key === entryKey ? `${keyboardEntry.current.text}${event.key}` : event.key === '.' ? '0.' : event.key; if ((value.match(/\./g) ?? []).length > 1) return; keyboardEntry.current = { key: entryKey, text: value }; setSasaValue(value); updateTrack('sasa', 'replace', Number(value)); return }
    if (activeTrack === 'function' && /^[A-Za-z0-9_-]$/.test(event.key)) { event.preventDefault(); const value = keyboardEntry.current?.key === entryKey ? `${keyboardEntry.current.text}${event.key}` : event.key; if (value.length > 256) return; keyboardEntry.current = { key: entryKey, text: value }; setFunctionValue(value); addFunction(value); return }
    if (activeTrack === 'coordinates' && event.key === ' ') {
      event.preventDefault()
      const value = trackMaps.get('coordinates')?.get(focus.handle)?.value
      updateTrack('coordinates', value == null ? 'preserve' : 'clear')
    }
  }

  const onPaste = (event: ClipboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement
    if (target.matches('input, textarea') || mode === 'structure') return
    const value = event.clipboardData.getData('text').trim().toUpperCase()
    if (activeTrack === 'sequence' && [...value].every((letter) => aminoAcids.has(letter))) {
      const handles = localPreview?.insertedHandles.length ? localPreview.insertedHandles : selection
      if (value.length !== handles.length) return
      event.preventDefault()
      const base = localPreview?.insertedHandles.length ? localPreview.preview.normalized_document : visibleDocument
      let next = base
      const residueIds = localPreview?.insertedHandles.length ? localPreview.insertedResidueIds : handles.map((handle) => residueIdByHandle.get(handle)).filter((item): item is string => Boolean(item))
      residueIds.forEach((residueId, index) => { next = trackDocument(next, [residueId], 'sequence', 'replace', value[index]) })
      if (localPreview?.insertedHandles.length) setInsertSequence(value)
      else if (value.length === 1) setSequenceValue(value)
      void propose(next, localPreview?.insertedHandles.length ? `插入 ${handles.length} 个残基` : `Sequence · ${value}`, localPreview?.insertedResidueIds ?? [], localPreview?.insertAnchor)
    } else if (activeTrack === 'function' && value && value.length <= 256) {
      event.preventDefault()
      setFunctionValue(value)
      addFunction(value)
    }
  }

  const addMergeSource = async () => {
    setBusy(true)
    setRequestError('')
    setSavePreview(undefined)
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
    if ('normalized_document' in committedProjection && !graphDirty) {
      setSavePreview(committedProjection)
      return
    }
    const requestId = ++previewRequest.current
    setBusy(true)
    setRequestError('')
    try {
      const preview = await onPreview(document)
      if (requestId === previewRequest.current) {
        setSavePreview(preview)
        setDocument(preview.normalized_document)
        setCommittedProjection(preview)
        setDirty((current) => current || graphDirty)
        setGraphDirty(false)
      }
    } catch (error) {
      if (requestId === previewRequest.current) setRequestError(requestErrorText(error))
    } finally {
      if (requestId === previewRequest.current) setBusy(false)
    }
  }

  const confirmSave = async () => {
    if (!savePreview) return
    const requestId = ++previewRequest.current
    setBusy(true)
    setRequestError('')
    try {
      await onApply(savePreview)
    } catch (error) {
      if (requestId === previewRequest.current) {
        setRequestError(requestErrorText(error))
        setSavePreview(undefined)
      }
    } finally {
      if (requestId === previewRequest.current) setBusy(false)
    }
  }

  const leave = () => {
    if (dirty || graphDirty || localPreview) setLeaveOpen(true)
    else onCancel()
  }

  const stateCounts = savePreview ? states.map((state) => ({ state, count: [...Object.values(savePreview.tracks).flatMap((track) => track.values), ...savePreview.function_annotations].filter((item) => item.state === state).length })) : []
  const localImpact = localPreview ? {
    current: localPreview.preview.residues.filter((item) => item.state !== 'pending-delete').length,
    inserted: localPreview.preview.residues.filter((item) => item.state === 'inserted').length,
    deleted: localPreview.preview.residues.filter((item) => item.state === 'pending-delete').length,
    cleared: Object.values(localPreview.preview.tracks).flatMap((track) => track.values).filter((item) => item.state === 'cleared').length,
  } : undefined

  return <div className="prompt-studio" tabIndex={0} onKeyDown={onKeyDown} onPaste={onPaste}>
    <header className="ps-header">
      <button className="ps-icon-button" aria-label="返回 Workflow" onClick={leave}><ChevronLeft size={18} /></button>
      <div><span className="ps-kicker">PROTEINPROMPT STUDIO</span><h1>ProteinPrompt 编辑</h1></div>
      <span className="ps-session-state"><i />{dirty || graphDirty ? '有未保存修改' : 'Authoring Snapshot'}</span>
      <button className="ps-button" disabled={!undoStack.current.length || busy} onClick={undo}><RotateCcw size={14} /> 撤销</button>
      <button className="ps-primary" disabled={Boolean(localPreview) || busy} title={localPreview ? '先应用或取消当前操作' : ''} onClick={() => void requestSave()}><Save size={14} /> {busy ? '处理中…' : '保存 ProteinPrompt'}</button>
    </header>

    {requestError && <p className="ps-help" role="alert">{requestError}</p>}
    {projection.baseline_diagnostics.length > 0 && <section className="ps-help" role="status"><strong>无可比较的旧结果</strong>{projection.baseline_diagnostics.map((item, index) => <p key={index}>{diagnosticText(item, displayLocators)}</p>)}</section>}
    {canEditChains && <section className="ps-chain-editor" aria-label="Chain declarations">
      <strong>Chain declarations</strong>
      {chainRows.map((chain, index) => <div key={index}>
        <input aria-label={`Chain ${index + 1} ID`} maxLength={1} value={chain.chain_id} disabled={operationBlocked} onChange={(event) => setChainRows(chainRows.map((item, i) => i === index ? { ...item, chain_id: event.target.value } : item))} />
        <input aria-label={`Chain ${index + 1} length`} type="number" min="1" max="2000000" step="1" value={chain.length} disabled={operationBlocked} onChange={(event) => setChainRows(chainRows.map((item, i) => i === index ? { ...item, length: event.target.value } : item))} />
        <button aria-label={`Move chain ${index + 1} up`} disabled={operationBlocked || index === 0} onClick={() => setChainRows(chainRows.map((item, i) => i === index - 1 ? chain : i === index ? chainRows[index - 1] : item))}>↑</button>
        <button aria-label={`Move chain ${index + 1} down`} disabled={operationBlocked || index === chainRows.length - 1} onClick={() => setChainRows(chainRows.map((item, i) => i === index + 1 ? chain : i === index ? chainRows[index + 1] : item))}>↓</button>
        <button aria-label={`Delete chain ${index + 1}`} disabled={operationBlocked} onClick={() => setChainRows(chainRows.filter((_, i) => i !== index))}>删除</button>
      </div>)}
      <button disabled={operationBlocked} onClick={() => setChainRows([...chainRows, { chain_id: '', length: '' }])}>添加 Chain</button>
      <button disabled={operationBlocked || !chainsReady} onClick={() => void propose({ ...visibleDocument, chains: chainRows.map((chain) => ({ chain_id: chain.chain_id, length: Number(chain.length) })) }, '更新 Chain declarations')}>预览 Chains</button>
    </section>}
    <nav className="ps-modebar" aria-label="Prompt Studio 模式">
      <button className={mode === 'layout' ? 'active' : ''} onClick={() => { setMode('layout'); setActiveTrack('sequence') }}>布局</button>
      <button className={mode === 'condition' ? 'active' : ''} onClick={() => { setMode('condition'); setActiveTrack('sequence') }}>条件</button>
      <button className={mode === 'structure' ? 'active' : ''} disabled={!hasCoordinates} title={hasCoordinates ? '' : '当前 Prompt 没有 Coordinates'} onClick={() => { setMode('structure'); setActiveTrack('coordinates') }}>结构</button>
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
        <button onClick={() => { setSelection([]); cancelLocalPreview() }}>清除选择</button>
      </section>

      <div className={`ps-workgrid ${hasCoordinates ? '' : 'without-structure'}`}>
        {hasCoordinates && <aside className="ps-structure-card">
          <header><span className="ps-kicker">STRUCTURE</span><strong>当前 Prompt · synchronized</strong></header>
          <StructureViewer pdb={projectionPdb} selectedResidues={selectedPositions} onSelectResidue={selectFromStructure} pivot={mode === 'structure' ? transformOrigin : undefined} />
          <small>{selectedText}</small>
        </aside>}

        <section className="ps-ledger" aria-label="Residue ledger">
          <header className="ps-ledger-header">
            <div><span className="ps-kicker">RESIDUE LEDGER</span><h2>共享残基矩阵</h2></div>
            <div className="ps-ledger-controls"><button onClick={() => setLegendOpen((open) => !open)}>状态图例</button></div>
          </header>
          {legendOpen && <div className="ps-state-legend">{states.map((state) => <span key={state} className={`state-${state}`}><i />{state}</span>)}</div>}
          <div className="ps-matrix-frame">
            <div className="ps-row-labels">
              <span role="rowheader"><strong>Residue axis</strong><small>chain / locator</small></span>
              {trackRows.map(({ key, label, unit }) => <span role="rowheader" key={key} className={hiddenTracks.has(key) ? 'hidden' : ''}><button aria-label={`${hiddenTracks.has(key) ? '显示' : '隐藏'} ${label}`} onClick={() => setHiddenTracks((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next })}>{hiddenTracks.has(key) ? <EyeOff size={12} /> : <Eye size={12} />}</button><strong>{label}</strong><small>{unit}</small></span>)}
            </div>
            <div className="ps-matrix-scroll">
              {!orderedResidues.length && <p className="ps-help">先在 document 中声明 chains，Preview 后即可编辑 residue axis。</p>}
              {orderedResidues.map((residue) => {
                const handle = residue.residue_handle
                const isCurrent = currentHandles.has(handle)
                return <div className={`ps-residue-column ${selection.includes(handle) ? 'selected' : ''} ${isCurrent ? '' : 'tombstone'}`} key={handle}>
                  <button aria-label={`${displayLocators.get(handle) ?? residue.residue_id} residue`} disabled={!isCurrent || busy} onClick={(event) => selectResidue(handle, event)}><strong>{displayLocators.get(handle) ?? residue.residue_id}</strong><small>{isCurrent ? `#${residue.position}` : 'deleted'}</small></button>
                  {trackRows.map(({ key, label }) => {
                    if (hiddenTracks.has(key)) return <span className="ps-cell-hidden" key={key} />
                    if (key === 'function') {
                      const values = functionCells.get(handle) ?? []
                      const cellStates = [...new Set(values.map((item) => item.state))]
                      const state = cellStates.length > 1 ? 'mixed' : cellStates[0] ?? 'empty'
                      const starting = values.filter((item) => item.start_residue_handle === handle)
                      const value = starting.map((item) => item.label).join(' · ') || (values.length ? '━' : '—')
                      const ribbonClass = values.length ? `function-ribbon ${starting.length ? 'ribbon-start' : ''} ${values.some((item) => item.end_residue_handle === handle) ? 'ribbon-end' : ''}` : ''
                      const fullValue = values.map((item) => item.label).join(' · ') || '—'
                      return <button key={key} data-cell={`${handle}:${key}`} aria-label={`${displayLocators.get(handle) ?? residue.residue_id} ${label} ${fullValue} ${state}`} disabled={!isCurrent || busy} className={`ps-cell ${ribbonClass} state-${state} ${focus.handle === handle && focus.track === key ? 'focused' : ''}`} onClick={(event) => { selectResidue(handle, event); setActiveTrack(key); setFunctionTargetKey(''); setFunctionStart(''); setFunctionEnd(''); setFunctionSplit(''); if (values[0]) setFunctionValue(values[0].label); setFocus({ handle, track: key }) }}><strong>{value}</strong><small>{state}</small></button>
                    }
                    const item = trackMaps.get(key)?.get(handle)
                    if (!item) return null
                    return <button key={key} data-cell={`${handle}:${key}`} aria-label={`${displayLocators.get(handle) ?? residue.residue_id} ${label} ${displayValue(key, item)} ${item.state}`} disabled={!isCurrent || busy} className={`ps-cell state-${item.state} ${focus.handle === handle && focus.track === key ? 'focused' : ''}`} onClick={(event) => { selectResidue(handle, event); setActiveTrack(key); setFocus({ handle, track: key }) }}><strong>{displayValue(key, item)}</strong><small>{item.state}</small></button>
                  })}
                </div>
              })}
            </div>
          </div>
        </section>

        <aside className="ps-editor">
          <header><span className="ps-kicker">JOINT EDITOR</span><h2>{trackRows.find((item) => item.key === activeTrack)?.label ?? activeTrack}</h2><small>{selectedText}</small></header>
          {mode === 'condition' && <div className="ps-track-tabs">{trackRows.map(({ key, label }) => <button key={key} className={activeTrack === key ? 'active' : ''} onClick={() => setActiveTrack(key)}>{label.replace('Secondary structure', 'SS8').replace('Function annotations', 'Function')}</button>)}</div>}
          {mode === 'condition' && activeTrack !== 'function' && <div className="ps-editor-section">
            <span className="ps-kicker">TRACK ACTION</span>
            <div className="ps-action-row"><button disabled={!selection.length || operationBlocked} onClick={() => updateTrack(activeTrack, 'preserve')}>Preserve</button><button disabled={!selection.length || operationBlocked} onClick={() => updateTrack(activeTrack, 'clear')}>Clear</button></div>
            {activeTrack === 'sequence' && <label><span>氨基酸</span><input aria-label="指定氨基酸" maxLength={1} value={sequenceValue} onChange={(event) => setSequenceValue(event.target.value.toUpperCase())} /><button disabled={!selection.length || operationBlocked || !aminoAcids.has(sequenceValue)} onClick={() => updateTrack('sequence', 'replace', sequenceValue)}>Specify</button></label>}
            {activeTrack === 'secondary_structure' && <label><span>SS8</span><input aria-label="指定二级结构" maxLength={1} value={ssValue} onChange={(event) => setSsValue(event.target.value.toUpperCase())} /><button disabled={!selection.length || operationBlocked || !ss8Codes.has(ssValue)} onClick={() => updateTrack('secondary_structure', 'replace', ssValue)}>Specify</button></label>}
            {activeTrack === 'sasa' && <label><span>SASA Å²</span><input aria-label="指定 SASA" type="number" min="0" value={sasaValue} onChange={(event) => setSasaValue(event.target.value)} /><button disabled={!selection.length || operationBlocked || !sasaInputValid} onClick={() => updateTrack('sasa', 'replace', Number(sasaValue))}>Specify</button></label>}
            {activeTrack === 'coordinates' && <p className="ps-help"><Info size={13} /> Coordinates 仅支持 Preserve 或 Clear；空格键切换。</p>}
          </div>}
          {mode === 'condition' && activeTrack === 'function' && <div className="ps-editor-section"><span className="ps-kicker">FUNCTION TUPLE</span>{focusedFunctionOptions.length > 0 && <div className="ps-function-options">{focusedFunctionOptions.map(({ annotation, key }) => <button key={key} className={focusedFunction === annotation ? 'active' : ''} onClick={() => { setFunctionTargetKey(key); setFunctionValue(annotation.label); setFunctionStart(''); setFunctionEnd(''); setFunctionSplit('') }}><strong>{annotation.label}</strong><small>{displayLocators.get(annotation.start_residue_handle)}–{displayLocators.get(annotation.end_residue_handle)}</small></button>)}</div>}<label><span>Label</span><input aria-label="Function label" maxLength={256} value={functionValue} onChange={(event) => setFunctionValue(event.target.value)} /><button disabled={!selection.length || operationBlocked || !functionValue.trim() || functionValue.length > 256 || (!focusedFunction && !functionSelectionValid)} onClick={() => addFunction()}>{focusedFunction && selection.length === 1 ? 'Replace' : 'Add'}</button></label>{!focusedFunction && selection.length > 1 && !functionSelectionValid && <p className="ps-help"><Info size={13} /> Function 区间必须是同一条链上的连续残基。</p>}{focusedFunction && <div className="ps-function-endpoints"><label>Start<select aria-label="Function 起点" value={functionStart || residueIdByHandle.get(focusedFunction.start_residue_handle)} onChange={event => setFunctionStart(event.target.value)}>{currentCommittedResidues.map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select></label><label>End<select aria-label="Function 终点" value={functionEnd || residueIdByHandle.get(focusedFunction.end_residue_handle)} onChange={event => setFunctionEnd(event.target.value)}>{currentCommittedResidues.map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select></label><button disabled={busy} onClick={() => updateFunctionInterval(false)}>预览端点修改</button><label>Split after<select aria-label="Function 拆分点" value={functionSplit} onChange={event => setFunctionSplit(event.target.value)}><option value="">选择拆分点</option>{currentCommittedResidues.slice(currentCommittedResidues.findIndex(item => item.residue_id === (functionStart || residueIdByHandle.get(focusedFunction.start_residue_handle))), currentCommittedResidues.findIndex(item => item.residue_id === (functionEnd || residueIdByHandle.get(focusedFunction.end_residue_handle)))).map(item => <option key={item.residue_id}>{item.residue_id}</option>)}</select></label><button disabled={busy || !functionSplit} onClick={() => updateFunctionInterval(true)}>预览拆分</button></div>}<button className="ps-danger-wide" disabled={!focusedFunction || operationBlocked} onClick={deleteFunction}><Trash2 size={13} /> Delete exact tuple</button></div>}
          {mode === 'layout' && <div className="ps-editor-section ps-layout-actions"><span className="ps-kicker">ORDERED RESIDUES</span>{(deletionBlocked || insertionBlocked) && <p className="ps-help">{randomLayoutReason}</p>}<div className="ps-insert-fields"><input aria-label="插入数量" type="number" min="1" value={insertCount} onChange={(event) => setInsertCount(event.target.value)} /><input aria-label="插入序列" placeholder="Mask 或等长序列" value={insertSequence} onChange={(event) => setInsertSequence(event.target.value.toUpperCase())} /></div>{!insertionInputValid && <p className="ps-help"><Info size={13} /> 序列必须为空、单字母，或与插入数量等长。</p>}<button disabled={!selection.length || operationBlocked || !insertionInputValid || insertionBlocked} onClick={() => insertResidues()}><Plus size={13} /> Insert after focus</button><button className="danger" disabled={!selection.length || operationBlocked || committedHandles.size === selection.length || deletionBlocked} onClick={deleteSelection}><Trash2 size={13} /> Delete selected</button></div>}

          {mode === 'structure' && <PromptTransformEditor projection={projection} selection={selection} document={visibleDocument} busy={busy} mode={transformMode} axis={transformAxis} amount={transformAmount} onAmount={setTransformAmount} onMode={setTransformMode} onAxis={setTransformAxis} onOrigin={setTransformOrigin} onPreview={(next, title) => void propose(next, title)} />}
          {mode !== 'structure' && (mode === 'layout' || activeTrack !== 'function') && <section className="ps-editor-section" aria-label="随机条件">
            <span className="ps-kicker">SEEDED RANDOM {mode === 'layout' ? 'INSERT' : 'MASK'}</span>
            <label>Count<input aria-label="随机数量" type="number" min="0" step="1" value={randomCount} onChange={event => setRandomCount(event.target.value)} /></label>
            <label>Seed<input aria-label="随机 seed" type="number" min="0" step="1" value={randomSeed} onChange={event => setRandomSeed(event.target.value)} /></label>
            <label>范围<select aria-label="随机范围" value={randomScope} onChange={event => setRandomScope(event.target.value as typeof randomScope)}><option value="all">全部符合条件的位置</option><option value="selection">{mode === 'layout' ? '选区所在链' : '仅选区内已指定值'}</option></select></label>
            <div className="ps-action-row"><button disabled={busy || !randomSeed.trim() || !randomCount.trim() || randomScope === 'selection' && !selection.length} onClick={() => randomOperation()}>预览随机操作</button><button disabled={busy || randomEditing === undefined} onClick={() => randomOperation(Number(randomSeed) + 1)}>换 seed 重抽</button></div>
            <button onClick={() => setRandomEditing(undefined)}>开始新的随机操作</button>
            {(visibleDocument.random_operations ?? []).map((operation, index) => <div key={index} className="ps-random-operation"><button onClick={() => { setRandomEditing(index); setRandomCount(String(operation.count)); setRandomSeed(String(operation.seed)); setMode(operation.kind === 'insert' ? 'layout' : 'condition'); if (operation.kind === 'mask') setActiveTrack(operation.track); const ids = operation.kind === 'mask' ? operation.eligible_residue_ids : undefined; setRandomScope(ids?.length || operation.kind === 'insert' && operation.eligible_chain_ids?.length ? 'selection' : 'all'); if (ids) setSelection(projection.residues.filter(item => ids.includes(item.residue_id)).map(item => item.residue_handle)); else if (operation.kind === 'insert' && operation.eligible_chain_ids?.length) setSelection(projection.residues.filter(item => operation.eligible_chain_ids!.includes(item.chain_id)).map(item => item.residue_handle)) }}>{index + 1} · {operation.kind} · seed {operation.seed} · {operation.count}</button><button disabled={busy} onClick={() => { void propose({ ...visibleDocument, random_operations: visibleDocument.random_operations!.filter((_, i) => i !== index) }, '移除随机操作'); setRandomEditing(undefined) }}>移除</button><p className="ps-help">实际位置：{projection.random_selections.find(item => item.operation_index === index)?.realized_residue_handles.map(handle => displayLocators.get(handle)).join(', ') ?? '待预览'}</p></div>)}
          </section>}
          <section className="ps-editor-section ps-effective-conditioning" aria-label="ESM3 有效条件">
            <span className="ps-kicker">ESM3 EFFECTIVE CONDITIONING</span>
            <p className="ps-help">后端 ESM3 Adapter / Operation 的实际输入投影；不会更改科学 Prompt。运行还需要实际模型和执行配置。</p>
            {!projection.esm3_conditioning ? <p className="ps-help">当前没有可投影的科学 Prompt。</p> : <>
              <strong>{projection.esm3_conditioning.status === 'compatible' ? 'SDK 可以表示当前条件' : 'SDK 无法表示当前条件'}</strong>
              {projection.esm3_conditioning.reason && <p className="ps-help">{projection.esm3_conditioning.reason}</p>}
              {Object.entries(projection.esm3_conditioning.operations).map(([operation, state]) => <p className="ps-help" key={operation}>{operation}：{state.compatible ? '满足 Node 科学前提' : state.reason}</p>)}
              {projection.esm3_conditioning.effective_input && <>
                <p className="ps-help">Coordinates：{projection.esm3_conditioning.effective_input.coordinates.present ? `[${projection.esm3_conditioning.effective_input.coordinates.shape!.join(', ')}] float32 Å · ${projection.esm3_conditioning.effective_input.coordinates.entries.length} 个实际原子` : '没有可用 atom37 坐标'}；缺失位置编码 NaN。</p>
                <p className="ps-help">SS8：{projection.esm3_conditioning.effective_input.secondary_structure === null ? 'absent' : 'present'} · SASA：{projection.esm3_conditioning.effective_input.sasa === null ? 'absent' : 'present（Å²）'}</p>
                {projection.esm3_conditioning.effective_input.coordinates.omitted_named_atoms.length > 0 && <p className="ps-help">以下 named atoms 保留在科学 Prompt 中，但不进入 atom37：{projection.esm3_conditioning.effective_input.coordinates.omitted_named_atoms.map(item => `${item.residue_id}/${item.atom_name}`).join(', ')}</p>}
                <details><summary>查看精确有效值、单位及 float32 位模式</summary><pre>{JSON.stringify(projection.esm3_conditioning.effective_input, null, 2)}</pre></details>
              </>}
            </>}
          </section>
          <button disabled={busy} onClick={() => void addMergeSource()}>添加合并来源</button>
          <PromptMergeEditor sources={mergeSourceSnapshot.source.merge_sources ?? []} projection={projection} document={visibleDocument} busy={busy} diagnostics={localPreview?.preview.diagnostics ?? []} onTargetSelection={ids => { const handles = projection.residues.filter(item => ids.includes(item.residue_id) && item.state !== 'pending-delete').map(item => item.residue_handle); setSelection(handles); if (handles.length) { setAnchor(handles[0]); setFocus(current => ({ ...current, handle: handles[0] })) } }} onPreview={(next, title) => void propose(next, title)} />

          {localPreview && localImpact && <section className="ps-local-preview" aria-label="即时预览">
            <span className="ps-kicker">UNAPPLIED PREVIEW</span><h3>即时预览 · {localPreview.title}</h3><p>可继续编辑其他轨道；整组操作共享此预览。Enter 一起应用，Esc 全部取消。</p>
            <div className="ps-impact"><span>Current<strong>{localImpact.current}</strong></span><span>Inserted<strong>{localImpact.inserted}</strong></span><span>Tombstones<strong>{localImpact.deleted}</strong></span><span>Cleared tracks<strong>{localImpact.cleared}</strong></span></div>
            <ul>{localPreview.preview.changes.map((change, index) => <li key={`change-${index}`}>{previewChangeText(change, committedProjection, localPreview.preview, displayLocators)}</li>)}{localPreview.preview.function_annotations.filter((item) => ['inserted', 'pending-delete'].includes(item.state)).map((item, index) => <li key={`function-${index}`}>Function · {item.label} · {displayLocators.get(item.start_residue_handle)}–{displayLocators.get(item.end_residue_handle)} · {item.state}</li>)}</ul>
            <div className="ps-merge-impact">{localPreview.preview.source_merges.map((merge, index) => <details key={index}><summary>合并 {index + 1}：新增、轨道 / Mask 与注释决策</summary><pre>{JSON.stringify(merge, null, 2)}</pre></details>)}</div><ul>{localPreview.preview.diagnostics.map((item, index) => <li key={index}><button className="ps-diagnostic" onClick={() => focusDiagnostic(item)}>{diagnosticText(item, displayLocators)}</button></li>)}</ul>
            <div><button onClick={cancelLocalPreview}><X size={13} /> 取消</button><button className="apply" disabled={busy || diagnosticsHaveError(localPreview.preview)} onClick={applyLocalPreview}><Check size={13} /> 应用操作</button></div>
          </section>}
        </aside>
      </div>
    </main>

    {savePreview && <div className="ps-modal-backdrop"><section className="ps-save-dialog" role="dialog" aria-modal="true" aria-labelledby="save-preview-title">
      <header><div><span className="ps-kicker">NORMALIZED BACKEND PREVIEW</span><h2 id="save-preview-title">确认写回 Workflow</h2></div><button aria-label="关闭保存预览" onClick={() => setSavePreview(undefined)}><X size={17} /></button></header>
      {savePreview.baseline_diagnostics.length > 0 && <p className="ps-help">无可比较的旧结果；将保存当前有效候选。</p>}
      <div className="ps-counts">{stateCounts.map(({ state, count }) => <span key={state} className={`state-${state}`}><i />{state}<strong>{count}</strong></span>)}</div>
      <div className="ps-save-summary"><span>Current residues<strong>{savePreview.residues.filter((item) => item.state !== 'pending-delete').length}</strong></span><span>Function tuples<strong>{savePreview.function_annotations.filter((item) => item.state !== 'pending-delete').length}</strong></span><span>Diagnostics<strong>{savePreview.diagnostics.length}</strong></span></div>
      <pre>{JSON.stringify(savePreview.summary, null, 2)}</pre>
      {savePreview.diagnostics.length > 0 && <ul>{savePreview.diagnostics.map((item, index) => <li key={index}><button className="ps-diagnostic" onClick={() => focusDiagnostic(item)}>{diagnosticText(item, displayLocators)}</button></li>)}</ul>}
      <footer><button autoFocus onClick={() => setSavePreview(undefined)}>返回编辑</button><button className="confirm" disabled={Boolean(localPreview) || busy || diagnosticsHaveError(savePreview)} onClick={() => void confirmSave()}><Check size={14} /> {busy ? '写回中…' : '确认并写回 Workflow'}</button></footer>
    </section></div>}

    {leaveOpen && <div className="ps-modal-backdrop"><section className="ps-leave-dialog" role="dialog" aria-modal="true"><h2>{localPreview ? '当前即时预览尚未应用' : '尚未保存 Prompt 修改'}</h2><p>{localPreview ? '先返回应用或取消该操作；也可以放弃本次编辑并离开。' : '应用到本地编辑会话的修改还没有写回 Workflow。'}</p><footer><button autoFocus onClick={() => setLeaveOpen(false)}>继续编辑</button><button className="danger" onClick={onCancel}>放弃修改</button><button className="confirm" disabled={Boolean(localPreview)} title={localPreview ? '先应用或取消即时预览' : ''} onClick={() => { setLeaveOpen(false); void requestSave() }}>保存</button></footer></section></div>}
  </div>
}

function documentQueryCell(handle: string, track: Track) {
  return globalThis.document.querySelector<HTMLButtonElement>(`[data-cell="${CSS.escape(`${handle}:${track}`)}"]`)
}
