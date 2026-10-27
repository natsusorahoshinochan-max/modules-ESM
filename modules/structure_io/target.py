"""Complete, single-chain design targets in standard mmCIF.

Polymer positions are read from entity_poly_seq, independently of atom_site.
This public API deliberately has no editing or model-adapter dependency.
"""
import math
import gemmi

MONOMERS = dict(zip('ACDEFGHIKLMNPQRSTVWYBXZJUO_',
    'ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU MET ASN PRO GLN ARG SER THR VAL TRP TYR ASX UNK GLX XLE SEC PYL UNK'.split()))


def write_target(positions, *, chain='A'):
    """Encode ordered residues and actual named atoms; absent atoms stay absent.

Each position has residue, optional author_number/insertion_code/author_chain,
and atoms: {atom_name: [x,y,z]}. Positions use current one-based label_seq_id.
Author numbering is source correspondence, independent of the target order.
"""
    if not isinstance(chain, str) or not chain:
        raise ValueError('A target requires one explicit chain identifier')
    if not isinstance(positions, list) or not positions:
        raise ValueError('A target requires at least one polymer position')
    doc = gemmi.cif.Document(); block = doc.add_new_block('design_target')
    block.set_pair('_entry.id', 'design_target')
    block.init_loop('_entity.', ['id', 'type']).add_row(['1', 'polymer'])
    sequence = ''.join(row['residue'].replace('_', 'X') for row in positions)
    block.init_loop('_entity_poly.', ['entity_id', 'type', 'pdbx_seq_one_letter_code', 'pdbx_seq_one_letter_code_can', 'pdbx_strand_id']).add_row(['1', "'polypeptide(L)'", gemmi.cif.quote(sequence), gemmi.cif.quote(sequence), gemmi.cif.quote(chain)])
    block.init_loop('_struct_asym.', ['id', 'entity_id']).add_row([gemmi.cif.quote(chain), '1'])
    polymer = block.init_loop('_entity_poly_seq.', ['entity_id', 'num', 'mon_id', 'hetero'])
    scheme = block.init_loop('_pdbx_poly_seq_scheme.', ['asym_id', 'entity_id', 'seq_id', 'mon_id', 'pdb_seq_num', 'auth_seq_num', 'pdb_mon_id', 'auth_mon_id', 'pdb_strand_id', 'pdb_ins_code', 'hetero'])
    atoms = block.init_loop('_atom_site.', ['group_PDB', 'id', 'type_symbol', 'label_atom_id', 'label_alt_id', 'label_comp_id', 'label_asym_id', 'label_entity_id', 'label_seq_id', 'pdbx_PDB_ins_code', 'Cartn_x', 'Cartn_y', 'Cartn_z', 'occupancy', 'B_iso_or_equiv', 'auth_seq_id', 'auth_comp_id', 'auth_asym_id', 'auth_atom_id', 'pdbx_PDB_model_num'])
    serial = 0
    for index, row in enumerate(positions, 1):
        residue = row.get('residue')
        if residue not in MONOMERS:
            raise ValueError('Target position requires an amino acid or _')
        monomer = MONOMERS[residue]
        author = row.get('author_number')
        insertion = row.get('insertion_code', '')
        author_chain = row.get('author_chain', chain)
        if author is not None and type(author) is not int:
            raise ValueError('Target author numbers must be integers or absent')
        if not isinstance(insertion, str) or len(insertion) > 1:
            raise ValueError('Target insertion codes require at most one character')
        number = str(author) if author is not None else '?'
        label = str(index)
        polymer.add_row(['1', label, monomer, 'n'])
        scheme.add_row([gemmi.cif.quote(chain), '1', label, monomer, number, number, monomer, monomer, gemmi.cif.quote(author_chain), gemmi.cif.quote(insertion) if insertion else '.', 'n'])
        for name, xyz in row.get('atoms', {}).items():
            if not isinstance(name, str) or not name or not isinstance(xyz, (list, tuple)) or len(xyz) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in xyz):
                raise ValueError('Target atoms require names and finite XYZ coordinates')
            serial += 1
            # Explicitly authored atoms without source numbering use no author identity.
            atoms.add_row(['ATOM', str(serial), gemmi.cif.quote(name.lstrip('0123456789')[0]), gemmi.cif.quote(name), '.', monomer, gemmi.cif.quote(chain), '1', label, gemmi.cif.quote(insertion) if insertion else '.', *(repr(float(x)) for x in xyz), '1', '0', number, monomer, gemmi.cif.quote(author_chain), gemmi.cif.quote(name), '1'])
    return doc.as_string().encode()


def read_target(content, *, chain=None):
    """Read complete target positions, real atoms and author correspondence.

Returns {chain, sequence, positions}; each position has position, residue,
author_number, insertion_code, author_chain and atoms. Unknown residues are X.
"""
    doc = gemmi.cif.read_string(content.decode() if isinstance(content, bytes) else content)
    if len(doc) != 1:
        raise ValueError('A target requires exactly one mmCIF data block')
    block = doc.sole_block()
    asym = [(gemmi.cif.as_string(row[0]), gemmi.cif.as_string(row[1])) for row in block.find('_struct_asym.', ['id', 'entity_id'])]
    if chain is None:
        if len(asym) != 1:
            raise ValueError('Select one target label chain')
        chain = asym[0][0]
    entities = [entity for name, entity in asym if name == chain]
    if len(entities) != 1:
        raise ValueError('Target label chain is unavailable or ambiguous')
    rows = []
    for row in block.find('_entity_poly_seq.', ['entity_id', 'num', 'mon_id']):
        if gemmi.cif.as_string(row[0]) != entities[0]:
            continue
        monomer = gemmi.cif.as_string(row[2]); residue = gemmi.find_tabulated_residue(monomer)
        if not residue.is_amino_acid() and monomer not in ('UNK', 'XLE'):
            raise ValueError('Target polymer must contain amino-acid monomers')
        rows.append({'position':int(row[1]), 'residue':('J' if monomer == 'XLE' else residue.one_letter_code.upper()) if residue.is_amino_acid() or monomer == 'XLE' else 'X', 'author_number':None, 'insertion_code':'', 'author_chain':chain, 'atoms':{}})
    if not rows or [row['position'] for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('Target polymer positions must cover one complete ordered chain')
    scheme = {}
    for row in block.find('_pdbx_poly_seq_scheme.', ['asym_id', 'seq_id', 'auth_seq_num', 'pdb_strand_id', 'pdb_ins_code']):
        if gemmi.cif.as_string(row[0]) != chain:
            continue
        index = int(row[1])
        if index in scheme or not 1 <= index <= len(rows):
            raise ValueError('Target residue scheme must address each current position once')
        scheme[index] = True
        rows[index-1].update(author_number=int(row[2]) if row[2] not in ('?', '.') else None,
            author_chain=gemmi.cif.as_string(row[3]), insertion_code=gemmi.cif.as_string(row[4]) if row[4] not in ('?', '.') else '')
    if set(scheme) != set(range(1, len(rows) + 1)):
        raise ValueError('Target requires author correspondence for every polymer position')
    for atom in block.find('_atom_site.', ['label_asym_id', 'label_seq_id', 'label_atom_id', 'label_alt_id', 'Cartn_x', 'Cartn_y', 'Cartn_z', 'pdbx_PDB_model_num']):
        if gemmi.cif.as_string(atom[0]) != chain:
            continue
        index, name = int(atom[1]), gemmi.cif.as_string(atom[2])
        if not 1 <= index <= len(rows) or atom[3] not in ('.', '?') or atom[7] != '1' or name in rows[index-1]['atoms']:
            raise ValueError('Target atoms require one conformation and unique names at actual positions')
        xyz = [float(atom[i]) for i in (4,5,6)]
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError('Target atom coordinates must be finite')
        rows[index-1]['atoms'][name] = xyz
    return {'chain':chain, 'sequence':''.join(row['residue'] for row in rows), 'positions':rows}
