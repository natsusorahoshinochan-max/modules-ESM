import { useCallback, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { Check, ChevronLeft, Eye, EyeOff, Info, Plus, RotateCcw, Save, Trash2, X } from 'lucide-react'
import type { JsonObject, PromptDiagnostic, PromptFunctionAnnotation, PromptPreview, PromptSnapshot, PromptTrackValue } from './protocol/client'
import { StructureViewer } from './StructureViewer'
import './prompt-studio.css'

type ScalarTrack = 'sequence' | 'structure' | 'secondary_structure' | 'sasa'
type Track = ScalarTrack | 'function'
type TrackAction = 'preserve' | 'mask' | 'specify'
type Projection = Pick<PromptSnapshot, 'residues' | 'tracks' | 'function_annotations'>
type LocalPreview = { title: string; preview: PromptPreview; insertedHandles: string[]; insertAnchor?: string }
type UndoEntry = { document: JsonObject; projection: Projection; selection: string[]; anchor: string; focus: { handle: string; track: Track }; axisOrder: string[] }
type PromptStudioProps = {
  snapshot: PromptSnapshot
  onCancel: () => void
  onPreview: (document: JsonObject) => Promise<PromptPreview>
  onApply: (preview: PromptPreview) => Promise<void>
}

const trackRows: Array<{ key: Track; label: string; unit: string }> = [
  { key: 'sequence', label: 'Sequence', unit: 'amino acid' },
  { key: 'structure', label: 'Coordinates', unit: 'named atoms' },
  { key: 'secondary_structure', label: 'Secondary structure', unit: 'SS8' },
  { key: 'sasa', label: 'SASA', unit: 'Å²' },
  { key: 'function', label: 'Function annotations', unit: 'tuple interval' },
]
const scalarTracks = trackRows.slice(0, 4) as Array<{ key: ScalarTrack; label: string; unit: string }>
const aminoAcids = new Set('ACDEFGHIKLMNPQRSTVWY'.split(''))
const ss8Codes = new Set('HBEGITS-'.split(''))
const states = ['source', 'current', 'changed', 'cleared', 'inserted', 'pending-delete'] as const
const residueNames: Record<string, string> = { A: 'ALA', C: 'CYS', D: 'ASP', E: 'GLU', F: 'PHE', G: 'GLY', H: 'HIS', I: 'ILE', K: 'LYS', L: 'LEU', M: 'MET', N: 'ASN', P: 'PRO', Q: 'GLN', R: 'ARG', S: 'SER', T: 'THR', V: 'VAL', W: 'TRP', Y: 'TYR' }

function intents(document: JsonObject) { return document.track_intents as JsonObject[] }
function targets(document: JsonObject) { return document.target_residues as JsonObject[] }
function annotations(document: JsonObject) { return document.function_annotations as JsonObject[] }

function extendAxisOrder(base: string[], targetOrder: string[]) {
  const result = [...base]
  for (let targetIndex = 0; targetIndex < targetOrder.length; targetIndex += 1) {
    const handle = targetOrder[targetIndex]
    if (result.includes(handle)) continue
    const previous = [...targetOrder.slice(0, targetIndex)].reverse().find((item) => result.includes(item))
    if (previous) result.splice(result.indexOf(previous) + 1, 0, handle)
    else {
      const next = targetOrder.slice(targetIndex + 1).find((item) => result.includes(item))
      result.splice(next ? result.indexOf(next) : result.length, 0, handle)
    }
  }
  return result
}

function removeOneAnnotation(document: JsonObject, annotation: PromptFunctionAnnotation) {
  let removed = false
  return annotations(document).filter((item) => {
    if (!removed && item.label === annotation.label && item.start_residue_handle === annotation.start_residue_handle && item.end_residue_handle === annotation.end_residue_handle) {
      removed = true
      return false
    }
    return true
  })
}

function displayValue(track: ScalarTrack, item: PromptTrackValue) {
  if (item.value == null) return 'Mask'
  if (track === 'structure') return `${(item.value as { atoms: unknown[] }).atoms.length} atoms`
  return String(item.value)
}

function selectionText(handles: string[], projection: Projection, locators: Map<string, string>) {
  const selected = projection.residues.filter((residue) => handles.includes(residue.residue_handle) && residue.position > 0)
  if (!selected.length) return '未选择残基'
  const labels = selected.map((residue) => locators.get(residue.residue_handle)!)
  if (labels.length <= 6) return labels.join(' + ')
  return `${labels[0]}–${labels.at(-1)} · ${labels.length} residues`
}

function trackDocument(document: JsonObject, selected: string[], track: ScalarTrack, action: TrackAction, value?: string | number) {
  const retained = intents(document).filter((intent) => String(intent.track) !== track || !selected.includes(String(intent.residue_handle)))
  const additions = selected.map((residue_handle) => ({ track, residue_handle, action, ...(action === 'specify' ? { value } : {}) }))
  return { ...document, track_intents: [...retained, ...additions] }
}

function diagnosticsHaveError(preview: PromptPreview) {
  return preview.diagnostics.length > 0
}

function diagnosticText(diagnostic: PromptDiagnostic, locators: Map<string, string>) {
  return `${diagnostic.residue_handle ? `${locators.get(diagnostic.residue_handle)} · ` : ''}${String(diagnostic.message)}`
}

function previewChangeText(change: JsonObject, before: Projection, after: PromptPreview, locators: Map<string, string>) {
  if (change.kind === 'layout') return `Ordered residues · ${String(change.source_length)} → ${String(change.target_length)} · +${String(change.inserted_count)} / −${String(change.deleted_count)}`
  const track = String(change.track) as ScalarTrack
  const handle = String(change.residue_handle)
  const previous = before.tracks[track].find((item) => item.residue_handle === handle)
  const next = after.tracks[track].find((item) => item.residue_handle === handle)!
  return `${locators.get(handle)} · ${track} · ${previous ? displayValue(track, previous) : 'not present'} → ${displayValue(track, next)} · ${String(change.action)}`
}

export function PromptStudio({ snapshot, onCancel, onPreview, onApply }: PromptStudioProps) {
  const initialTargetHandles = new Set(targets(snapshot.document).map((item) => String(item.residue_handle)))
  const initiallyEdited = snapshot.residues.filter((residue) => initialTargetHandles.has(residue.residue_handle) && scalarTracks.some(({ key }) => {
    const item = snapshot.tracks[key].find((value) => value.residue_handle === residue.residue_handle)
    return item && !['source', 'current'].includes(item.state)
  })).map((residue) => residue.residue_handle)
  const [document, setDocument] = useState(snapshot.document)
  const [committedProjection, setCommittedProjection] = useState<Projection>(snapshot)
  const [axisOrder, setAxisOrder] = useState(snapshot.residues.map((item, index) => ({ handle: item.residue_handle, chain: item.chain_id, position: item.position, index })).sort((left, right) => left.chain.localeCompare(right.chain) || left.position - right.position || left.index - right.index).map((item) => item.handle))
  const [localPreview, setLocalPreview] = useState<LocalPreview>()
  const [savePreview, setSavePreview] = useState<PromptPreview>()
  const [selection, setSelection] = useState<string[]>(initiallyEdited)
  const [anchor, setAnchor] = useState(initiallyEdited[0] ?? snapshot.residues[0].residue_handle)
  const [focus, setFocus] = useState<{ handle: string; track: Track }>({ handle: initiallyEdited[0] ?? snapshot.residues[0].residue_handle, track: 'sequence' })
  const [activeTrack, setActiveTrack] = useState<Track>('sequence')
  const [mode, setMode] = useState<'layout' | 'condition' | 'structure'>('condition')
  const [hiddenTracks, setHiddenTracks] = useState<Set<Track>>(new Set())
  const [sequenceValue, setSequenceValue] = useState('A')
  const [ssValue, setSsValue] = useState('H')
  const [sasaValue, setSasaValue] = useState('32')
  const [functionValue, setFunctionValue] = useState('binding_site')
  const [functionTargetKey, setFunctionTargetKey] = useState('')
  const [insertCount, setInsertCount] = useState('1')
  const [insertSequence, setInsertSequence] = useState('')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [leaveOpen, setLeaveOpen] = useState(false)
  const [legendOpen, setLegendOpen] = useState(false)
  const undoStack = useRef<UndoEntry[]>([])
  const previewRequest = useRef(0)

  const projection: Projection = localPreview?.preview ?? committedProjection
  const committedHandles = useMemo(() => new Set(targets(document).map((item) => String(item.residue_handle))), [document])
  const visibleDocument = localPreview?.preview.normalized_document ?? document
  const currentHandles = useMemo(() => new Set(targets(visibleDocument).map((item) => String(item.residue_handle))), [visibleDocument])
  const visibleAxisOrder = useMemo(() => extendAxisOrder(axisOrder, targets(visibleDocument).map((item) => String(item.residue_handle))), [axisOrder, visibleDocument])
  const orderedResidues = useMemo(() => [...projection.residues].sort((left, right) => visibleAxisOrder.indexOf(left.residue_handle) - visibleAxisOrder.indexOf(right.residue_handle)), [projection.residues, visibleAxisOrder])
  const committedOrderedResidues = useMemo(() => [...committedProjection.residues].sort((left, right) => axisOrder.indexOf(left.residue_handle) - axisOrder.indexOf(right.residue_handle)), [axisOrder, committedProjection.residues])
  const displayLocators = useMemo(() => {
    const origin = new Map(targets(visibleDocument).map((item) => [String(item.residue_handle), String(item.origin)]))
    const lastSource = new Map<string, string>()
    const insertCounts = new Map<string, number>()
    const locators = new Map<string, string>()
    for (const residue of orderedResidues) {
      if (!currentHandles.has(residue.residue_handle) || origin.get(residue.residue_handle) !== 'insert') {
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
  const trackMaps = useMemo(() => new Map(scalarTracks.map(({ key }) => [key, new Map(projection.tracks[key].map((item) => [item.residue_handle, item]))])), [projection])
  const rowIndex = useMemo(() => new Map(orderedResidues.map((item, index) => [item.residue_handle, index])), [orderedResidues])
  const committedRowIndex = useMemo(() => new Map(committedOrderedResidues.map((item, index) => [item.residue_handle, index])), [committedOrderedResidues])
  const functionCells = useMemo(() => {
    const cells = new Map<string, PromptFunctionAnnotation[]>()
    for (const annotation of projection.function_annotations) {
      const start = rowIndex.get(annotation.start_residue_handle)!
      const end = rowIndex.get(annotation.end_residue_handle)!
      const covered = Array.from({ length: end - start + 1 }, (_, index) => start + index)
      for (const index of covered) {
        const handle = orderedResidues[index].residue_handle
        cells.set(handle, [...(cells.get(handle) ?? []), annotation])
      }
    }
    return cells
  }, [orderedResidues, projection.function_annotations, rowIndex])
  const focusedFunctionOptions = useMemo(() => committedProjection.function_annotations.map((annotation, index) => ({ annotation, key: `${annotation.label}:${annotation.start_residue_handle}:${annotation.end_residue_handle}:${index}` })).filter(({ annotation }) => {
    const index = committedRowIndex.get(focus.handle)!
    return annotation.state !== 'pending-delete' && committedRowIndex.get(annotation.start_residue_handle)! <= index && index <= committedRowIndex.get(annotation.end_residue_handle)!
  }), [committedProjection.function_annotations, committedRowIndex, focus.handle])
  const focusedFunction = focusedFunctionOptions.find((item) => item.key === functionTargetKey)?.annotation ?? focusedFunctionOptions[0]?.annotation
  const orderedFunctionSelection = committedProjection.residues.filter((item) => selection.includes(item.residue_handle) && committedHandles.has(item.residue_handle))
  const functionSelectionValid = orderedFunctionSelection.length === selection.length && orderedFunctionSelection.every((item, index) => index === 0 || (item.chain_id === orderedFunctionSelection[index - 1].chain_id && item.position === orderedFunctionSelection[index - 1].position + 1))
  const selectedText = selectionText(selection, { ...projection, residues: orderedResidues }, displayLocators)
  const hasCoordinates = projection.tracks.structure.some((item) => item.value != null && item.state !== 'pending-delete')
  const selectedPositions = useMemo(() => projection.residues.filter((item) => selection.includes(item.residue_handle) && currentHandles.has(item.residue_handle)).map((item) => ({ chain: item.chain_id, resi: item.position })), [currentHandles, projection.residues, selection])
  const projectionPdb = useMemo(() => {
    const sequence = new Map(projection.tracks.sequence.map((item) => [item.residue_handle, typeof item.value === 'string' ? item.value : 'G']))
    let serial = 1
    const lines: string[] = []
    for (const residue of projection.residues) {
      const structure = projection.tracks.structure.find((item) => item.residue_handle === residue.residue_handle)
      if (!structure || structure.state === 'pending-delete' || structure.value == null || typeof structure.value !== 'object') continue
      for (const atom of structure.value.atoms) {
        const [x, y, z] = atom.coordinates
        const atomName = atom.atom_label.slice(0, 4)
        const element = atomName.replace(/[^A-Za-z]/g, '').slice(0, 1).toUpperCase()
        lines.push(`ATOM  ${String(serial).padStart(5)} ${atomName.padStart(4)} ${residueNames[sequence.get(residue.residue_handle)!] ?? 'GLY'} ${residue.chain_id}${String(residue.position).padStart(4)}    ${x.toFixed(3).padStart(8)}${y.toFixed(3).padStart(8)}${z.toFixed(3).padStart(8)}  1.00  0.00          ${element.padStart(2)}`)
        serial += 1
      }
    }
    return `${lines.join('\n')}\nEND\n`
  }, [projection.residues, projection.tracks.sequence, projection.tracks.structure])
  const operationBlocked = busy || Boolean(localPreview)
  const insertionCount = Number(insertCount)
  const insertionInputValid = Number.isInteger(insertionCount) && insertionCount > 0 && (insertSequence.length === 0 || insertSequence.length === 1 || insertSequence.length === insertionCount) && [...insertSequence].every((letter) => aminoAcids.has(letter))
  const sasaInputValid = sasaValue.trim() !== '' && Number(sasaValue) >= 0

  const propose = async (nextDocument: JsonObject, title: string, insertedHandles: string[] = [], insertAnchor?: string) => {
    const requestId = ++previewRequest.current
    setBusy(true)
    setSavePreview(undefined)
    const preview = await onPreview(nextDocument)
    if (requestId !== previewRequest.current) return
    setLocalPreview({ title, preview, insertedHandles, insertAnchor })
    setBusy(false)
  }

  const cancelLocalPreview = useCallback(() => {
    previewRequest.current += 1
    setBusy(false)
    setLocalPreview(undefined)
    if (!committedHandles.has(focus.handle)) {
      const nextHandle = selection.find((handle) => committedHandles.has(handle)) ?? committedProjection.residues.find((item) => committedHandles.has(item.residue_handle))!.residue_handle
      setSelection((current) => current.filter((handle) => committedHandles.has(handle)))
      setAnchor(nextHandle)
      setFocus((current) => ({ ...current, handle: nextHandle }))
    }
  }, [committedHandles, committedProjection.residues, focus.handle, selection])

  const selectFromStructure = useCallback((picked: { chain: string; resi: number }) => {
    const residue = committedProjection.residues.find((item) => item.chain_id === picked.chain && item.position === picked.resi && committedHandles.has(item.residue_handle))
    if (!residue) return
    cancelLocalPreview()
    setSelection([residue.residue_handle])
    setAnchor(residue.residue_handle)
    setFocus((current) => ({ ...current, handle: residue.residue_handle }))
  }, [cancelLocalPreview, committedHandles, committedProjection.residues])

  const applyLocalPreview = () => {
    const pending = localPreview!
    previewRequest.current += 1
    undoStack.current.push({ document, projection: committedProjection, selection, anchor, focus, axisOrder })
    setDocument(pending.preview.normalized_document)
    setCommittedProjection(pending.preview)
    setAxisOrder(visibleAxisOrder)
    const nextTargets = targets(pending.preview.normalized_document).map((item) => String(item.residue_handle))
    if (pending.insertedHandles.length) {
      setSelection(pending.insertedHandles)
      setAnchor(pending.insertedHandles[0])
      setFocus({ handle: pending.insertedHandles[0], track: 'sequence' })
    } else {
      const retainedSelection = selection.filter((handle) => nextTargets.includes(handle))
      const nextFocus = nextTargets.includes(focus.handle) ? focus.handle : retainedSelection[0] ?? nextTargets[0]
      setSelection(retainedSelection)
      setAnchor(nextFocus)
      setFocus((current) => ({ ...current, handle: nextFocus }))
    }
    setLocalPreview(undefined)
    setDirty(true)
  }

  const undo = () => {
    const previous = undoStack.current.pop()
    if (!previous) return
    setDocument(previous.document)
    setCommittedProjection(previous.projection)
    setSelection(previous.selection)
    setAnchor(previous.anchor)
    setFocus(previous.focus)
    setAxisOrder(previous.axisOrder)
    cancelLocalPreview()
    setSavePreview(undefined)
    setDirty(undoStack.current.length > 0)
  }

  const selectResidue = (handle: string, event: MouseEvent) => {
    if (localPreview && currentHandles.has(handle) && !committedHandles.has(handle)) {
      setSelection([handle])
      setAnchor(handle)
      setFocus((current) => ({ ...current, handle }))
      return
    }
    if (!committedHandles.has(handle)) return
    const current = committedProjection.residues.filter((item) => committedHandles.has(item.residue_handle)).map((item) => item.residue_handle)
    if (event.shiftKey) {
      const from = current.indexOf(anchor)
      const to = current.indexOf(handle)
      setSelection(current.slice(Math.min(from, to), Math.max(from, to) + 1))
    } else if (event.metaKey || event.ctrlKey) {
      setSelection((selected) => selected.includes(handle) ? selected.filter((item) => item !== handle) : [...selected, handle])
      setAnchor(handle)
    } else {
      setSelection([handle])
      setAnchor(handle)
    }
    cancelLocalPreview()
    setFocus((currentFocus) => ({ ...currentFocus, handle }))
  }

  const updateTrack = (track: ScalarTrack, action: TrackAction, value?: string | number) => {
    if (!selection.length) return
    void propose(trackDocument(document, selection, track, action, value), `${scalarTracks.find((row) => row.key === track)!.label} · ${action}`)
  }

  const deleteSelection = () => {
    const nextTargets = targets(document).filter((item) => !selection.includes(String(item.residue_handle)))
    const nextAnnotations = annotations(document).filter((item) => !selection.includes(String(item.start_residue_handle)) && !selection.includes(String(item.end_residue_handle)))
    const next = { ...document, target_residues: nextTargets, track_intents: intents(document).filter((item) => !selection.includes(String(item.residue_handle))), function_annotations: nextAnnotations }
    void propose(next, `删除 ${selection.length} 个残基`)
  }

  const insertResidues = (count = insertionCount, rawSequence = insertSequence, anchorOverride?: string) => {
    const sequence = rawSequence.trim().toUpperCase()
    if (!Number.isInteger(count) || count < 1 || ![0, 1, count].includes(sequence.length) || ![...sequence].every((letter) => aminoAcids.has(letter))) return
    const anchorHandle = anchorOverride ?? focus.handle ?? selection.at(-1)!
    const nextTargets = [...targets(document)]
    const anchorIndex = nextTargets.findIndex((item) => item.residue_handle === anchorHandle)
    const chainId = String(nextTargets[anchorIndex].chain_id)
    const insertedHandles = Array.from({ length: count }, () => `insert-${crypto.randomUUID()}`)
    nextTargets.splice(anchorIndex + 1, 0, ...insertedHandles.map((residue_handle) => ({ residue_handle, origin: 'insert', chain_id: chainId })))
    const letters = sequence.length === 1 ? Array(count).fill(sequence) : sequence.split('')
    const sequenceIntents = insertedHandles.map((residue_handle, index) => letters[index] ? { track: 'sequence', residue_handle, action: 'specify', value: letters[index] } : { track: 'sequence', residue_handle, action: 'mask' })
    void propose({ ...document, target_residues: nextTargets, track_intents: [...intents(document), ...sequenceIntents] }, `插入 ${count} 个残基`, insertedHandles, anchorHandle)
  }

  const addFunction = (label = functionValue) => {
    if (!selection.length) return
    const replaceExisting = selection.length === 1 ? focusedFunction : undefined
    if (!replaceExisting && !functionSelectionValid) return
    const start_residue_handle = replaceExisting?.start_residue_handle ?? orderedFunctionSelection[0].residue_handle
    const end_residue_handle = replaceExisting?.end_residue_handle ?? orderedFunctionSelection.at(-1)!.residue_handle
    const retained = replaceExisting ? removeOneAnnotation(document, replaceExisting) : annotations(document)
    const nextAnnotation = { label, start_residue_handle, end_residue_handle }
    void propose({ ...document, function_annotations: [...retained, nextAnnotation] }, `${replaceExisting ? '替换' : '新增'} Function · ${label}`)
  }

  const deleteFunction = () => {
    if (!focusedFunction) return
    const next = removeOneAnnotation(document, focusedFunction)
    void propose({ ...document, function_annotations: next }, '删除 Function tuple')
  }

  const moveFocus = (residueDelta: number, trackDelta: number) => {
    cancelLocalPreview()
    const handles = committedProjection.residues.filter((item) => committedHandles.has(item.residue_handle)).map((item) => item.residue_handle)
    const tracks = visibleRows.map((item) => item.key)
    if (!tracks.length) return
    const nextHandle = handles[Math.max(0, Math.min(handles.length - 1, handles.indexOf(focus.handle) + residueDelta))]
    const nextTrack = tracks[Math.max(0, Math.min(tracks.length - 1, tracks.indexOf(focus.track) + trackDelta))]
    setFocus({ handle: nextHandle, track: nextTrack })
    setActiveTrack(nextTrack)
    setSelection([nextHandle])
    setAnchor(nextHandle)
    requestAnimationFrame(() => documentQueryCell(nextHandle, nextTrack)?.focus())
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape' && savePreview) { event.preventDefault(); setSavePreview(undefined); return }
    if (event.key === 'Escape' && leaveOpen) { event.preventDefault(); setLeaveOpen(false); return }
    const target = event.target as HTMLElement
    if (target.matches('input, textarea, select') || (target.matches('button') && !target.hasAttribute('data-cell'))) return
    if (event.key === 'Escape' && localPreview) { event.preventDefault(); cancelLocalPreview(); return }
    if (busy) return
    if (event.key === 'Enter' && localPreview && !diagnosticsHaveError(localPreview.preview)) { event.preventDefault(); applyLocalPreview(); return }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(); return }
    if (event.key === 'ArrowLeft') { event.preventDefault(); moveFocus(-1, 0); return }
    if (event.key === 'ArrowRight') { event.preventDefault(); moveFocus(1, 0); return }
    if (event.key === 'ArrowUp') { event.preventDefault(); moveFocus(0, -1); return }
    if (event.key === 'ArrowDown') { event.preventDefault(); moveFocus(0, 1); return }
    if (event.key === 'Backspace' && activeTrack === 'sequence' && localPreview?.insertedHandles.length) { event.preventDefault(); setInsertSequence(''); void propose(trackDocument(localPreview.preview.normalized_document, localPreview.insertedHandles, 'sequence', 'mask'), `插入 ${localPreview.insertedHandles.length} 个残基`, localPreview.insertedHandles, localPreview.insertAnchor); return }
    if (event.key === '+') { event.preventDefault(); insertResidues(insertionCount, insertSequence, localPreview?.insertAnchor); return }
    if (/^[1-9]$/.test(event.key) && activeTrack !== 'sasa' && activeTrack !== 'function') { event.preventDefault(); const count = Number(event.key); setInsertCount(event.key); if (localPreview?.insertedHandles.length) insertResidues(count, insertSequence, localPreview.insertAnchor); return }
    if (activeTrack === 'sequence' && aminoAcids.has(event.key.toUpperCase())) {
      event.preventDefault()
      const value = event.key.toUpperCase()
      if (localPreview?.insertedHandles.length) {
        setInsertSequence(value)
        void propose(trackDocument(localPreview.preview.normalized_document, localPreview.insertedHandles, 'sequence', 'specify', value), `插入 ${localPreview.insertedHandles.length} 个残基`, localPreview.insertedHandles, localPreview.insertAnchor)
      } else {
        setSequenceValue(value)
        updateTrack('sequence', 'specify', value)
      }
      return
    }
    if (activeTrack === 'secondary_structure' && ss8Codes.has(event.key.toUpperCase())) { event.preventDefault(); updateTrack('secondary_structure', 'specify', event.key.toUpperCase()); return }
    if (activeTrack === 'sasa' && /^[0-9]$/.test(event.key)) { event.preventDefault(); const value = localPreview ? `${sasaValue}${event.key}` : event.key; setSasaValue(value); updateTrack('sasa', 'specify', Number(value)); return }
    if (activeTrack === 'function' && /^[A-Za-z0-9_-]$/.test(event.key)) { event.preventDefault(); const value = localPreview ? `${functionValue}${event.key}` : event.key; if (value.length > 256) return; setFunctionValue(value); addFunction(value); return }
    if (activeTrack === 'structure' && event.key === ' ') {
      event.preventDefault()
      const value = trackMaps.get('structure')!.get(focus.handle)!.value
      updateTrack('structure', value == null ? 'preserve' : 'mask')
    }
  }

  const onPaste = (event: ClipboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement
    if (target.matches('input, textarea')) return
    const value = event.clipboardData.getData('text').trim().toUpperCase()
    if (activeTrack === 'sequence' && [...value].every((letter) => aminoAcids.has(letter))) {
      const handles = localPreview?.insertedHandles.length ? localPreview.insertedHandles : selection
      if (value.length !== handles.length) return
      event.preventDefault()
      const base = localPreview?.insertedHandles.length ? localPreview.preview.normalized_document : document
      let next = base
      handles.forEach((handle, index) => { next = trackDocument(next, [handle], 'sequence', 'specify', value[index]) })
      if (localPreview?.insertedHandles.length) setInsertSequence(value)
      else if (value.length === 1) setSequenceValue(value)
      void propose(next, localPreview?.insertedHandles.length ? `插入 ${handles.length} 个残基` : `Sequence · ${value}`, localPreview?.insertedHandles ?? [], localPreview?.insertAnchor)
    } else if (activeTrack === 'function' && value && value.length <= 256) {
      event.preventDefault()
      setFunctionValue(value)
      addFunction(value)
    }
  }

  const requestSave = async () => {
    setBusy(true)
    const preview = await onPreview(document)
    setSavePreview(preview)
    setBusy(false)
  }

  const confirmSave = async () => {
    setBusy(true)
    await onApply(savePreview!)
  }

  const leave = () => {
    if (dirty || localPreview) setLeaveOpen(true)
    else onCancel()
  }

  const stateCounts = savePreview ? states.map((state) => ({ state, count: [...Object.values(savePreview.tracks).flat(), ...savePreview.function_annotations].filter((item) => item.state === state).length })) : []
  const localImpact = localPreview ? {
    current: targets(localPreview.preview.normalized_document).length,
    inserted: localPreview.preview.residues.filter((item) => localPreview.preview.tracks.sequence.find((value) => value.residue_handle === item.residue_handle)?.state === 'inserted').length,
    deleted: localPreview.preview.residues.filter((item) => localPreview.preview.tracks.sequence.find((value) => value.residue_handle === item.residue_handle)?.state === 'pending-delete').length,
    cleared: Object.values(localPreview.preview.tracks).flat().filter((item) => item.state === 'cleared').length,
  } : undefined

  return <div className="prompt-studio" tabIndex={0} onKeyDown={onKeyDown} onPaste={onPaste}>
    <header className="ps-header">
      <button className="ps-icon-button" aria-label="返回 Workflow" onClick={leave}><ChevronLeft size={18} /></button>
      <div><span className="ps-kicker">PROTEINPROMPT STUDIO</span><h1>3GB1 局部环区重设计</h1></div>
      <span className="ps-session-state"><i />{dirty ? '有未保存修改' : 'Authoring Snapshot'}</span>
      <button className="ps-button" disabled={!undoStack.current.length || busy} onClick={undo}><RotateCcw size={14} /> 撤销</button>
      <button className="ps-primary" disabled={Boolean(localPreview) || busy} title={localPreview ? '先应用或取消当前操作' : ''} onClick={() => void requestSave()}><Save size={14} /> {busy ? '处理中…' : '保存 ProteinPrompt'}</button>
    </header>

    <nav className="ps-modebar" aria-label="Prompt Studio 模式">
      <button className={mode === 'layout' ? 'active' : ''} onClick={() => { setMode('layout'); setActiveTrack('sequence') }}>布局</button>
      <button className={mode === 'condition' ? 'active' : ''} onClick={() => { setMode('condition'); setActiveTrack('sequence') }}>条件</button>
      <button className={mode === 'structure' ? 'active' : ''} disabled={!hasCoordinates} title={hasCoordinates ? '' : '当前 Prompt 没有 Coordinates'} onClick={() => { setMode('structure'); setActiveTrack('structure') }}>结构</button>
      <span>有序残基、条件轨道与结构定位共享同一 residue axis</span>
    </nav>

    <main className="ps-main">
      <section className="ps-summarybar">
        <div><span>当前 Prompt</span><strong>{targets(document).length} residues</strong></div>
        <div><span>Source</span><strong>{String(snapshot.source.kind).toUpperCase()} · {[...new Set(projection.residues.map((item) => item.chain_id))].join(', ')}</strong></div>
        <div><span>Function tuples</span><strong>{projection.function_annotations.filter((item) => item.state !== 'pending-delete').length}</strong></div>
        <div><span>Backend projection</span><strong>six-state ledger</strong></div>
      </section>

      <section className="ps-selectionbar" aria-label="当前选择">
        <span className="ps-kicker">SELECTION</span><strong>{selectedText}</strong><small>{selection.length} selected</small>
        <button onClick={() => { setSelection([]); cancelLocalPreview() }}>清除选择</button>
      </section>

      <div className={`ps-workgrid ${hasCoordinates ? '' : 'without-structure'}`}>
        {hasCoordinates && <aside className="ps-structure-card">
          <header><span className="ps-kicker">STRUCTURE</span><strong>3GB1 · synchronized</strong></header>
          <StructureViewer pdb={projectionPdb} selectedResidues={selectedPositions} onSelectResidue={selectFromStructure} />
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
              {orderedResidues.map((residue) => {
                const isCurrent = currentHandles.has(residue.residue_handle)
                return <div className={`ps-residue-column ${selection.includes(residue.residue_handle) ? 'selected' : ''} ${isCurrent ? '' : 'tombstone'}`} key={residue.residue_handle}>
                  <button aria-label={`${displayLocators.get(residue.residue_handle)} residue`} disabled={!isCurrent || busy} onClick={(event) => selectResidue(residue.residue_handle, event)}><strong>{displayLocators.get(residue.residue_handle)}</strong><small>{isCurrent ? `#${residue.position}` : 'deleted'}</small></button>
                  {trackRows.map(({ key, label }) => {
                    if (hiddenTracks.has(key)) return <span className="ps-cell-hidden" key={key} />
                    if (key === 'function') {
                      const values = functionCells.get(residue.residue_handle) ?? []
                      const cellStates = [...new Set(values.map((item) => item.state))]
                      const state = cellStates.length > 1 ? 'mixed' : cellStates[0] ?? 'empty'
                      const starting = values.filter((item) => item.start_residue_handle === residue.residue_handle)
                      const value = starting.map((item) => item.label).join(' · ') || (values.length ? '━' : '—')
                      const ribbonClass = values.length ? `function-ribbon ${starting.length ? 'ribbon-start' : ''} ${values.some((item) => item.end_residue_handle === residue.residue_handle) ? 'ribbon-end' : ''}` : ''
                      const fullValue = values.map((item) => item.label).join(' · ') || '—'
                      return <button key={key} data-cell={`${residue.residue_handle}:${key}`} aria-label={`${displayLocators.get(residue.residue_handle)} ${label} ${fullValue} ${state}`} disabled={!isCurrent || busy} className={`ps-cell ${ribbonClass} state-${state} ${focus.handle === residue.residue_handle && focus.track === key ? 'focused' : ''}`} onClick={(event) => { selectResidue(residue.residue_handle, event); setActiveTrack(key); setFunctionTargetKey(''); setFocus({ handle: residue.residue_handle, track: key }) }}><strong>{value}</strong><small>{state}</small></button>
                    }
                    const item = trackMaps.get(key)!.get(residue.residue_handle)!
                    return <button key={key} data-cell={`${residue.residue_handle}:${key}`} aria-label={`${displayLocators.get(residue.residue_handle)} ${label} ${displayValue(key, item)} ${item.state}`} disabled={!isCurrent || busy} className={`ps-cell state-${item.state} ${focus.handle === residue.residue_handle && focus.track === key ? 'focused' : ''}`} onClick={(event) => { selectResidue(residue.residue_handle, event); setActiveTrack(key); setFocus({ handle: residue.residue_handle, track: key }) }}><strong>{displayValue(key, item)}</strong><small>{item.state}</small></button>
                  })}
                </div>
              })}
            </div>
          </div>
        </section>

        <aside className="ps-editor">
          <header><span className="ps-kicker">JOINT EDITOR</span><h2>{trackRows.find((item) => item.key === activeTrack)!.label}</h2><small>{selectedText}</small></header>
          <div className="ps-track-tabs">{trackRows.map(({ key, label }) => <button key={key} className={activeTrack === key ? 'active' : ''} onClick={() => setActiveTrack(key)}>{label.replace('Secondary structure', 'SS8').replace('Function annotations', 'Function')}</button>)}</div>
          {activeTrack !== 'function' && <div className="ps-editor-section">
            <span className="ps-kicker">TRACK ACTION</span>
            <div className="ps-action-row"><button disabled={!selection.length || operationBlocked} onClick={() => updateTrack(activeTrack, 'preserve')}>Preserve</button><button disabled={!selection.length || operationBlocked} onClick={() => updateTrack(activeTrack, 'mask')}>Mask</button></div>
            {activeTrack === 'sequence' && <label><span>氨基酸</span><input aria-label="指定氨基酸" maxLength={1} value={sequenceValue} onChange={(event) => setSequenceValue(event.target.value.toUpperCase())} /><button disabled={!selection.length || operationBlocked || !aminoAcids.has(sequenceValue)} onClick={() => updateTrack('sequence', 'specify', sequenceValue)}>Specify</button></label>}
            {activeTrack === 'secondary_structure' && <label><span>SS8</span><input aria-label="指定二级结构" maxLength={1} value={ssValue} onChange={(event) => setSsValue(event.target.value.toUpperCase())} /><button disabled={!selection.length || operationBlocked || !ss8Codes.has(ssValue)} onClick={() => updateTrack('secondary_structure', 'specify', ssValue)}>Specify</button></label>}
            {activeTrack === 'sasa' && <label><span>SASA Å²</span><input aria-label="指定 SASA" type="number" min="0" value={sasaValue} onChange={(event) => setSasaValue(event.target.value)} /><button disabled={!selection.length || operationBlocked || !sasaInputValid} onClick={() => updateTrack('sasa', 'specify', Number(sasaValue))}>Specify</button></label>}
            {activeTrack === 'structure' && <p className="ps-help"><Info size={13} /> Coordinates 仅支持 Preserve 或 Mask；空格键切换。</p>}
          </div>}
          {activeTrack === 'function' && <div className="ps-editor-section"><span className="ps-kicker">FUNCTION TUPLE</span>{focusedFunctionOptions.length > 0 && <div className="ps-function-options">{focusedFunctionOptions.map(({ annotation, key }) => <button key={key} className={focusedFunction === annotation ? 'active' : ''} onClick={() => { setFunctionTargetKey(key); setFunctionValue(annotation.label) }}><strong>{annotation.label}</strong><small>{displayLocators.get(annotation.start_residue_handle)}–{displayLocators.get(annotation.end_residue_handle)}</small></button>)}</div>}<label><span>Label</span><input aria-label="Function label" maxLength={256} value={functionValue} onChange={(event) => setFunctionValue(event.target.value)} /><button disabled={!selection.length || operationBlocked || !functionValue.trim() || functionValue.length > 256 || (!focusedFunction && !functionSelectionValid)} onClick={() => addFunction()}>{focusedFunction && selection.length === 1 ? 'Replace' : 'Add'}</button></label>{!focusedFunction && selection.length > 1 && !functionSelectionValid && <p className="ps-help"><Info size={13} /> Function 区间必须是同一条链上的连续残基。</p>}<button className="ps-danger-wide" disabled={!focusedFunction || operationBlocked} onClick={deleteFunction}><Trash2 size={13} /> Delete exact tuple</button></div>}
          <div className="ps-editor-section ps-layout-actions"><span className="ps-kicker">ORDERED RESIDUES</span><div className="ps-insert-fields"><input aria-label="插入数量" type="number" min="1" value={insertCount} onChange={(event) => setInsertCount(event.target.value)} /><input aria-label="插入序列" placeholder="Mask 或等长序列" value={insertSequence} onChange={(event) => setInsertSequence(event.target.value.toUpperCase())} /></div>{!insertionInputValid && <p className="ps-help"><Info size={13} /> 序列必须为空、单字母，或与插入数量等长。</p>}<button disabled={!selection.length || operationBlocked || !insertionInputValid} onClick={() => insertResidues()}><Plus size={13} /> Insert after focus</button><button className="danger" disabled={!selection.length || operationBlocked || targets(document).length === selection.length} onClick={deleteSelection}><Trash2 size={13} /> Delete selected</button></div>

          {localPreview && <section className="ps-local-preview" aria-label="即时预览">
            <span className="ps-kicker">UNAPPLIED PREVIEW</span><h3>即时预览 · {localPreview.title}</h3><p>矩阵显示后端返回的未应用投影。Enter 应用，Esc 取消。</p>
            <div className="ps-impact"><span>Current<strong>{localImpact!.current}</strong></span><span>Inserted<strong>{localImpact!.inserted}</strong></span><span>Tombstones<strong>{localImpact!.deleted}</strong></span><span>Cleared tracks<strong>{localImpact!.cleared}</strong></span></div>
            <ul>{localPreview.preview.changes.map((change, index) => <li key={`change-${index}`}>{previewChangeText(change, committedProjection, localPreview.preview, displayLocators)}</li>)}{localPreview.preview.function_annotations.filter((item) => ['inserted', 'pending-delete'].includes(item.state)).map((item, index) => <li key={`function-${index}`}>Function · {item.label} · {displayLocators.get(item.start_residue_handle)}–{displayLocators.get(item.end_residue_handle)} · {item.state}</li>)}</ul>
            <ul>{localPreview.preview.diagnostics.map((item, index) => <li key={index}>{diagnosticText(item, displayLocators)}</li>)}</ul>
            <div><button onClick={cancelLocalPreview}><X size={13} /> 取消</button><button className="apply" disabled={busy || diagnosticsHaveError(localPreview.preview)} onClick={applyLocalPreview}><Check size={13} /> 应用操作</button></div>
          </section>}
        </aside>
      </div>
    </main>

    {savePreview && <div className="ps-modal-backdrop"><section className="ps-save-dialog" role="dialog" aria-modal="true" aria-labelledby="save-preview-title">
      <header><div><span className="ps-kicker">NORMALIZED BACKEND PREVIEW</span><h2 id="save-preview-title">确认写回 Workflow</h2></div><button aria-label="关闭保存预览" onClick={() => setSavePreview(undefined)}><X size={17} /></button></header>
      <div className="ps-digest"><span>Preview digest</span><code>{savePreview.preview_digest}</code></div>
      <div className="ps-counts">{stateCounts.map(({ state, count }) => <span key={state} className={`state-${state}`}><i />{state}<strong>{count}</strong></span>)}</div>
      <div className="ps-save-summary"><span>Current residues<strong>{targets(savePreview.normalized_document).length}</strong></span><span>Function tuples<strong>{savePreview.function_annotations.filter((item) => item.state !== 'pending-delete').length}</strong></span><span>Diagnostics<strong>{savePreview.diagnostics.length}</strong></span></div>
      <pre>{JSON.stringify(savePreview.summary, null, 2)}</pre>
      {savePreview.diagnostics.length > 0 && <ul>{savePreview.diagnostics.map((item, index) => <li key={index}>{diagnosticText(item, displayLocators)}</li>)}</ul>}
      <footer><button autoFocus onClick={() => setSavePreview(undefined)}>返回编辑</button><button className="confirm" disabled={Boolean(localPreview) || busy || diagnosticsHaveError(savePreview)} onClick={() => void confirmSave()}><Check size={14} /> {busy ? '写回中…' : '确认并写回 Workflow'}</button></footer>
    </section></div>}

    {leaveOpen && <div className="ps-modal-backdrop"><section className="ps-leave-dialog" role="dialog" aria-modal="true"><h2>{localPreview ? '当前即时预览尚未应用' : '尚未保存 Prompt 修改'}</h2><p>{localPreview ? '先返回应用或取消该操作；也可以放弃本次编辑并离开。' : '应用到本地编辑会话的修改还没有写回 Workflow。'}</p><footer><button autoFocus onClick={() => setLeaveOpen(false)}>继续编辑</button><button className="danger" onClick={onCancel}>放弃修改</button><button className="confirm" disabled={Boolean(localPreview)} title={localPreview ? '先应用或取消即时预览' : ''} onClick={() => { setLeaveOpen(false); void requestSave() }}>保存</button></footer></section></div>}
  </div>
}

function documentQueryCell(handle: string, track: Track) {
  return globalThis.document.querySelector<HTMLButtonElement>(`[data-cell="${CSS.escape(`${handle}:${track}`)}"]`)
}
