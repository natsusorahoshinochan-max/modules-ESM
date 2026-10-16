import { expect, test } from '@playwright/test'
import { promptStructure } from '../../src/prompt-structure'
import type { PromptSnapshot } from '../../src/protocol/client'

test('Prompt display encoding preserves full chain, residue position and coordinate precision', () => {
  const projection: Pick<PromptSnapshot, 'residues' | 'tracks'> = {
    residues: [{ residue_handle: 'r1', residue_id: 'LONG_CHAIN:10001', chain_id: 'LONG_CHAIN', residue_label: '10001', position: 10001, state: 'current' }],
    tracks: {
      sequence: { present: true, values: [{ residue_handle: 'r1', value: 'G', state: 'current' }] },
      coordinates: { present: true, values: [{ residue_handle: 'r1', state: 'current', value: { atoms: [{ atom_handle: 'r1:CA', atom_name: 'CA', coordinates: [1.123456, -2.345678, 3.987654] }] } }] },
      secondary_structure: { present: false, values: [] },
      sasa: { present: false, values: [] },
    },
  }
  const structure = promptStructure(projection)
  expect(structure.format).toBe('mmcif')
  expect(structure.text).toContain('_atom_site.auth_asym_id\n_atom_site.auth_seq_id')
  expect(structure.text).toContain('ATOM 1 C CA GLY LONG_CHAIN 10001 1.123456 -2.345678 3.987654\n')
  expect(projection.tracks.coordinates.values[0].value).toEqual({ atoms: [{ atom_handle: 'r1:CA', atom_name: 'CA', coordinates: [1.123456, -2.345678, 3.987654] }] })
  projection.tracks.coordinates.values[0].state = 'pending-delete'
  expect(promptStructure(projection)).toEqual({ format: 'mmcif', text: '' })
})
