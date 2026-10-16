import type { PromptAuthoringDocument, PromptMergeCorrespondence, PromptTargetResidue, PromptTrackEdit } from '../../../webui/src/protocol/client'

/** Applied random insertions share the ordinary editable target layout. */
export function promptLayoutTargets(document: PromptAuthoringDocument): PromptTargetResidue[] | undefined {
  return document.target_residues
}

function withLayout(document: PromptAuthoringDocument, targets: PromptTargetResidue[]): PromptAuthoringDocument {
  return { ...document, target_residues: targets }
}

/** Explicit deletions turn only the affected source relations into source gaps. */
export function deletePromptResidues(document: PromptAuthoringDocument, targets: PromptTargetResidue[], removed: ReadonlySet<string>): PromptAuthoringDocument {
  return {
    ...withLayout(document, targets.filter(item => !removed.has(item.residue_id))),
    track_edits: document.track_edits?.filter(item => !removed.has(item.residue_id)),
    rigid_transforms: document.rigid_transforms?.map(item => ({ ...item, residue_ids: item.residue_ids.filter(id => !removed.has(id)) })).filter(item => item.residue_ids.length > 0),
    source_merges: document.source_merges?.map(merge => {
      const droppedSources = new Set(merge.correspondence.flatMap(row => row.disposition !== 'source_gap' && removed.has(row.target_residue_id) && row.disposition !== 'target_gap' ? [row.source_residue_id] : []))
      return {
        ...merge,
        correspondence: merge.correspondence.flatMap((row): PromptMergeCorrespondence[] => {
          if (row.disposition === 'source_gap' || !removed.has(row.target_residue_id)) return [row]
          return row.disposition === 'target_gap' ? [] : [{ disposition: 'source_gap', source_residue_id: row.source_residue_id }]
        }),
        track_adoptions: merge.track_adoptions.map(adoption => ({ ...adoption, source_residue_ids: adoption.source_residue_ids.filter(id => !droppedSources.has(id)) })).filter(adoption => adoption.source_residue_ids.length > 0),
      }
    }),
  }
}

/** Insert target gaps at each existing explicit correspondence stage, never match a source. */
export function insertPromptResidues(document: PromptAuthoringDocument, targets: PromptTargetResidue[], precedingFinalIds: string[], residueIds: string[], sequenceEdits: PromptTrackEdit[]): PromptAuthoringDocument {
  const predecessors = [...precedingFinalIds].reverse()
  const targetPredecessor = predecessors.find(id => targets.some(item => item.residue_id === id))
  const targetIndex = targetPredecessor === undefined ? -1 : targets.findIndex(item => item.residue_id === targetPredecessor)
  const targetRows: PromptTargetResidue[] = residueIds.map(residue_id => ({ residue_id, origin: 'inserted' }))
  return {
    ...withLayout(document, [...targets.slice(0, targetIndex + 1), ...targetRows, ...targets.slice(targetIndex + 1)]),
    track_edits: [...document.track_edits ?? [], ...sequenceEdits],
    source_merges: document.source_merges?.map(merge => {
      const predecessor = predecessors.find(id => merge.correspondence.some(row => row.disposition !== 'source_gap' && row.target_residue_id === id))
      const index = predecessor === undefined ? -1 : merge.correspondence.findIndex(row => row.disposition !== 'source_gap' && row.target_residue_id === predecessor)
      const gaps: PromptMergeCorrespondence[] = residueIds.map(target_residue_id => ({ disposition: 'target_gap', target_residue_id }))
      return { ...merge, correspondence: [...merge.correspondence.slice(0, index + 1), ...gaps, ...merge.correspondence.slice(index + 1)] }
    }),
  }
}
