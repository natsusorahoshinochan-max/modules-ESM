import type { PromptSnapshot, PublishedStructure } from './protocol/client'

const residueNames: Record<string, string> = { A: 'ALA', C: 'CYS', D: 'ASP', E: 'GLU', F: 'PHE', G: 'GLY', H: 'HIS', I: 'ILE', K: 'LYS', L: 'LEU', M: 'MET', N: 'ASN', P: 'PRO', Q: 'GLN', R: 'ARG', S: 'SER', T: 'THR', V: 'VAL', W: 'TRP', Y: 'TYR' }

/** Display encoding only. Scientific coordinates remain in the backend projection. */
export function promptStructure(projection: Pick<PromptSnapshot, 'residues' | 'tracks'>): PublishedStructure {
  const sequence = new Map(projection.tracks.sequence.values.map(item => [item.residue_handle, typeof item.value === 'string' ? item.value : '']))
  const coordinates = new Map(projection.tracks.coordinates.values.map(item => [item.residue_handle, item]))
  let serial = 1
  const lines: string[] = []
  for (const residue of projection.residues) {
    const structure = coordinates.get(residue.residue_handle)
    if (!structure || structure.state === 'pending-delete' || structure.value === null || typeof structure.value !== 'object') continue
    for (const atom of structure.value.atoms) {
      const [x, y, z] = atom.coordinates
      const atomName = atom.atom_name
      const element = atomName.replace(/[^A-Za-z]/g, '').slice(0, 1).toUpperCase()
      lines.push(['ATOM', serial, element, atomName, residueNames[sequence.get(residue.residue_handle) ?? ''] ?? 'UNK', residue.chain_id, residue.position, x, y, z].join(' '))
      serial += 1
    }
  }
  const columns = ['group_PDB', 'id', 'type_symbol', 'auth_atom_id', 'auth_comp_id', 'auth_asym_id', 'auth_seq_id', 'Cartn_x', 'Cartn_y', 'Cartn_z']
  return { format: 'mmcif', text: lines.length ? `data_prompt\nloop_\n${columns.map(column => `_atom_site.${column}`).join('\n')}\n${lines.join('\n')}\n#\n` : '' }
}
