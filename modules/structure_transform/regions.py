"""Explicit protein-region extraction; comparison selections do not invoke this."""
from core.operation import OperationCall, OperationResources
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.region import region_residue_ids, structure_residue_id
from datatypes.structure import ProteinStructure
from datatypes.structure_format import mmcif_dictionary, read_mmcif_atoms, write_mmcif_dictionary
from .residue_axis import resolve_residue_axis, _single_model_records


def structural_region_ids(axis, selection) -> tuple[str, ...]:
    """Check author locations before mapping to the existing saved axis labels."""
    if selection:
        available = {record.residue_identity for record in _single_model_records(axis.structure) if record is not None}
        requested = {(item['chain_id'], item['residue_number'], item['insertion_code']) for item in selection}
        if not requested <= available:
            raise ValueError('region contains an author location absent from the source structure')
    return region_residue_ids(axis.layout, selection)


def extract_region(structure: ProteinStructure, residue_ids: tuple[str, ...]) -> ProteinStructure:
    selected = set(residue_ids)
    if structure.format == 'mmcif':
        original = mmcif_dictionary(structure.text)
        atoms = read_mmcif_atoms(structure.text)
        indices = [index for index, atom in enumerate(atoms)
                   if structure_residue_id(atom.chain_id, atom.residue_number, atom.insertion_code) in selected]
        # The derived polymer contains only retained residues. Separate entities
        # keep different selections of source chains from sharing a full sequence.
        data = {'data_': original['data_']}
        data.update({key: [values[index] for index in indices]
                     for key, values in original.items() if key.startswith('_atom_site.')})
        if '_entity_poly_seq.entity_id' in original:
            chains = {}
            positions = {}
            entity_ids, numbers, components = [], [], []
            for index in indices:
                atom = atoms[index]
                entity = chains.setdefault(atom.chain_id, str(len(chains) + 1))
                identity = (atom.chain_id, atom.residue_number, atom.insertion_code)
                if identity not in positions:
                    number = str(sum(key[0] == atom.chain_id for key in positions) + 1)
                    positions[identity] = number
                    entity_ids.append(entity)
                    numbers.append(number)
                    components.append(atom.residue_name)
            data['_atom_site.label_entity_id'] = [chains[atoms[index].chain_id] for index in indices]
            data['_atom_site.label_seq_id'] = [positions[(atoms[index].chain_id, atoms[index].residue_number,
                                                        atoms[index].insertion_code)] for index in indices]
            data['_entity_poly_seq.entity_id'] = entity_ids
            data['_entity_poly_seq.num'] = numbers
            data['_entity_poly_seq.mon_id'] = components
        prefix = '_pdbx_struct_mod_residue.' 
        if prefix + 'auth_seq_id' in original:
            rows = [index for index, number in enumerate(original[prefix + 'auth_seq_id'])
                    if structure_residue_id(original[prefix + 'auth_asym_id'][index], number,
                        '' if original.get(prefix + 'PDB_ins_code', ['?'] * len(original[prefix + 'auth_seq_id']))[index] in {'?', '.'}
                        else original[prefix + 'PDB_ins_code'][index]) in selected]
            if rows:
                data.update({key: [values[index] for index in rows]
                             for key, values in original.items() if key.startswith(prefix)})
        return ProteinStructure(write_mmcif_dictionary(data), 'mmcif')
    declared_chains = {line[11] for line in structure.text.splitlines() if line.startswith('SEQRES')}
    components = {}
    seen = set()
    for record in _single_model_records(structure):
        if record is not None and record.public_residue_id in selected and record.residue_identity not in seen:
            seen.add(record.residue_identity)
            if record.chain_id in declared_chains:
                components.setdefault(record.chain_id, []).append(record.residue_name)
    lines = []
    for chain, names in components.items():
        for offset in range(0, len(names), 13):
            lines.append(f'SEQRES {offset // 13 + 1:3d} {chain} {len(names):4d}  {" ".join(names[offset:offset + 13])}')
    in_fragment = False
    for line in structure.text.splitlines():
        if line.startswith(('ATOM  ', 'HETATM')):
            retained = structure_residue_id(line[21], line[22:26].strip(), line[26].strip()) in selected
            if retained:
                lines.append(line)
                in_fragment = True
            elif in_fragment:
                lines.append('TER')
                in_fragment = False
        elif line.startswith('TER') and in_fragment:
            lines.append('TER')
            in_fragment = False
        elif line.startswith('MODRES') and structure_residue_id(line[16], line[18:22].strip(), line[22].strip()) in selected:
            lines.append(line)
    if in_fragment:
        lines.append('TER')
    return ProteinStructure('\n'.join([*lines, 'END']) + '\n')


class ExtractRegionImplementation:
    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        parents = call.inputs['structure_candidates'].value
        if parents.item_type != 'protein.structure':
            raise ValueError('region extraction requires structure Candidates')
        children = []
        with self._resources.engine_invocation():
            for index, parent in enumerate(parents.items):
                axis = resolve_residue_axis(parent.data)
                selected = structural_region_ids(axis, call.node_parameters['region'])
                children.append(Candidate(
                    candidate_id=f'region-{index}', data=extract_region(parent.data, selected),
                    parent_ids=(parent.candidate_id,),
                    metadata={'transform': 'structure_transform.extract_region', 'residue_ids': list(selected)},
                ))
        return {'structure_candidates': CandidateCollection('extracted-regions', 'protein.structure', tuple(children))}
