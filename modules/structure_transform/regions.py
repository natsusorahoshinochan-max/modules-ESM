"""Explicit protein-region extraction; comparison selections do not invoke this."""
from core.operation import OperationCall, OperationResources
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.region import region_residue_ids, structure_residue_id
from datatypes.structure import ProteinStructure
from datatypes.structure_format import mmcif_dictionary, read_mmcif_atoms, write_mmcif_dictionary
from .residue_axis import resolve_residue_axis


def extract_region(structure: ProteinStructure, residue_ids: tuple[str, ...]) -> ProteinStructure:
    selected = set(residue_ids)
    if structure.format == 'mmcif':
        original = mmcif_dictionary(structure.text)
        atoms = read_mmcif_atoms(structure.text)
        indices = [index for index, atom in enumerate(atoms)
                   if structure_residue_id(atom.chain_id, atom.residue_number, atom.insertion_code) in selected]
        # This is a new coordinate fragment, not a claim to retain the full
        # polymer sequence, assembly, or connections to excluded residues.
        data = {'data_': original['data_']}
        data.update({key: [values[index] for index in indices]
                     for key, values in original.items() if key.startswith('_atom_site.')})
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
    lines = []
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
                selected = region_residue_ids(axis.layout, call.node_parameters['region'])
                children.append(Candidate(
                    candidate_id=f'region-{index}', data=extract_region(parent.data, selected),
                    parent_ids=(parent.candidate_id,),
                    metadata={'transform': 'structure_transform.extract_region', 'residue_ids': list(selected)},
                ))
        return {'structure_candidates': CandidateCollection('extracted-regions', 'protein.structure', tuple(children))}
