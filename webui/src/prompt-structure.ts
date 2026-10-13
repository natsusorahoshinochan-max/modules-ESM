import type { PromptSnapshot } from './protocol/client'

const residueNames: Record<string, string> = { A: 'ALA', C: 'CYS', D: 'ASP', E: 'GLU', F: 'PHE', G: 'GLY', H: 'HIS', I: 'ILE', K: 'LYS', L: 'LEU', M: 'MET', N: 'ASN', P: 'PRO', Q: 'GLN', R: 'ARG', S: 'SER', T: 'THR', V: 'VAL', W: 'TRP', Y: 'TYR' }

/** Display encoding only. Scientific coordinates remain in the backend projection. */
export function promptStructurePdb(projection: Pick<PromptSnapshot, 'residues' | 'tracks'>): string {
  const sequence = new Map(projection.tracks.sequence.values.map(item => [item.residue_handle, typeof item.value === 'string' ? item.value : '']))
  const coordinates = new Map(projection.tracks.coordinates.values.map(item => [item.residue_handle, item]))
  let serial = 1
  const lines: string[] = []
  for (const residue of projection.residues) {
    const structure = coordinates.get(residue.residue_handle)
    if (!structure || structure.state === 'pending-delete' || structure.value === null || typeof structure.value !== 'object') continue
    for (const atom of structure.value.atoms) {
      const [x, y, z] = atom.coordinates
      const atomName = atom.atom_name.slice(0, 4)
      const element = atomName.replace(/[^A-Za-z]/g, '').slice(0, 1).toUpperCase()
      lines.push(`ATOM  ${String(serial).padStart(5)} ${atomName.padStart(4)} ${residueNames[sequence.get(residue.residue_handle) ?? ''] ?? 'UNK'} ${residue.chain_id}${String(residue.position).padStart(4)}    ${x.toFixed(3).padStart(8)}${y.toFixed(3).padStart(8)}${z.toFixed(3).padStart(8)}  1.00  0.00          ${element.padStart(2)}`)
      serial += 1
    }
  }
  return lines.length ? `${lines.join('\n')}\nEND\n` : ''
}
