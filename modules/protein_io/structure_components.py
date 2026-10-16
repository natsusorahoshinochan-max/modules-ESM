"""View and select full structural residues without protein-only interpretation."""
from collections.abc import Mapping
from typing import Any, cast

import gemmi
from core.catalog.builtins import restore_candidate_collection_slice
from core.catalog.result_actions import ResultActionDefinition, ResultActionError
from core.parameters.contract import admit_declarations
from datatypes.candidate import CandidateDataReference
from datatypes.structure import ProteinStructure
from datatypes.structure_format import mmcif_dictionary, read_mmcif_atoms


def describe_components(structure: ProteinStructure) -> dict[str, Any]:
    """Keep model, author and label identities separate, including insertion codes."""
    rows = []
    if structure.format == 'mmcif':
        data = mmcif_dictionary(structure.text)
        for index, atom in enumerate(read_mmcif_atoms(structure.text)):
            identity = (atom.model, atom.chain_id, atom.label_chain, atom.residue_number,
                        atom.insertion_code, atom.residue_name, atom.record)
            rows.append((identity, atom.atom_name, data['_atom_site.type_symbol'][index], atom.coordinate))
    else:
        model = '1'
        for line in structure.text.splitlines():
            if line.startswith('MODEL '):
                model = line[10:14].strip()
            elif line.startswith(('ATOM  ', 'HETATM')):
                identity = (model, line[21], line[21], line[22:26].strip(), line[26].strip(), line[17:20].strip(), line[:6].strip())
                rows.append((identity, line[12:16].strip(), line[76:78].strip(), (float(line[30:38]), float(line[38:46]), float(line[46:54]))))
    components: list[dict[str, Any]] = []
    atoms: list[dict[str, Any]] = []
    first_elements: list[str] = []
    identities: dict[tuple[str, ...], int] = {}
    for identity, name, element, coordinate in rows:
        if identity not in identities:
            identities[identity] = len(components) + 1
            model, chain, label_chain, number, insertion, residue, record = identity
            info = gemmi.find_tabulated_residue(residue)
            kind = 'protein' if info.is_amino_acid() else 'nucleic_acid' if info.is_nucleic_acid() else 'water' if info.is_water() else 'other'
            first_elements.append(element or 'X')
            components.append({'component_index': len(components) + 1, 'model_id': model,
                               'chain_id': chain, 'label_chain_id': label_chain,
                               'residue_number': number, 'insertion_code': insertion,
                               'residue_name': residue, 'record': record, 'kind': kind, 'atom_count': 0})
        index = identities[identity]
        components[index - 1]['atom_count'] += 1
        atoms.append({'component_index': index, 'name': name, 'element': gemmi.Element(element or 'X').name,
                      'x': coordinate[0], 'y': coordinate[1], 'z': coordinate[2]})
    for component, element in zip(components, first_elements, strict=True):
        if component['atom_count'] == 1 and gemmi.Element(element).is_metal:
            component['kind'] = 'metal'
    return {'components': components, 'atoms': atoms}


def candidate_structure(body: bytes, index: int) -> ProteinStructure:
    collection = restore_candidate_collection_slice(body, offset=index, limit=1)
    if index >= collection.total:
        raise ResultActionError('Candidate index is outside the collection')
    if collection.item_type != 'protein.structure':
        raise ResultActionError('Selected Candidate has no structure')
    return cast(ProteinStructure, collection.items[0].data)


def read_structure_components(body: bytes, parameters: Mapping[str, Any], references: tuple[CandidateDataReference, ...]) -> dict[str, Any]:
    return describe_components(candidate_structure(body, parameters['item_index']))


STRUCTURE_COMPONENTS_ACTION = ResultActionDefinition(
    action_id='protein_io.structure_components', port_type_id='candidate.collection',
    parameters=admit_declarations({
        'item_index': {'parameter_scope': 'scientific', 'scientific_meaning': 'Published structure Candidate index.', 'required': True, 'value_contract': {'type': 'integer', 'minimum': 0}},
    }, path='protein_io.structure_components'), apply=read_structure_components,
)


def select_components(source: ProteinStructure, selected: list[int]) -> ProteinStructure:
    description = describe_components(source)
    known = {item['component_index'] for item in description['components']}
    if not set(selected) <= known:
        raise ResultActionError('Selected structural component is not present')
    selected_set = set(selected)
    if selected_set == known:
        return source
    indices = [i for i, atom in enumerate(description['atoms']) if atom['component_index'] in selected_set]
    if source.format == 'mmcif':
        from datatypes.structure_format import write_mmcif_dictionary
        data = mmcif_dictionary(source.text)
        selected_ids = {data['_atom_site.id'][i] for i in indices}
        for key, values in tuple(data.items()):
            if key.startswith('_atom_site.'):
                data[key] = [values[i] for i in indices]
        if '_atom_site_anisotrop.id' in data:
            keep = [i for i, atom_id in enumerate(data['_atom_site_anisotrop.id']) if atom_id in selected_ids]
            for key, values in tuple(data.items()):
                if key.startswith('_atom_site_anisotrop.'):
                    if keep:
                        data[key] = [values[i] for i in keep]
                    else:
                        del data[key]
        # Connections are meaningful only when both named partner atoms remain.
        if '_struct_conn.id' in data:
            fields = [('label_asym_id', 'label_asym_id'), ('label_comp_id', 'label_comp_id'),
                      ('label_seq_id', 'label_seq_id'), ('label_atom_id', 'label_atom_id'),
                      ('auth_asym_id', 'auth_asym_id'), ('auth_seq_id', 'auth_seq_id')]
            def has_partner(row: int, partner: int) -> bool:
                columns = [(data[f'_struct_conn.ptnr{partner}_{field}'][row], data[f'_atom_site.{atom_field}'])
                           for field, atom_field in fields
                           if f'_struct_conn.ptnr{partner}_{field}' in data and f'_atom_site.{atom_field}' in data]
                for field, atom_field in [('PDB_ins_code', 'pdbx_PDB_ins_code'), ('label_alt_id', 'label_alt_id'), ('PDB_model_num', 'pdbx_PDB_model_num')]:
                    key = f'_struct_conn.pdbx_ptnr{partner}_{field}'
                    if key in data and f'_atom_site.{atom_field}' in data:
                        columns.append((data[key][row], data[f'_atom_site.{atom_field}']))
                return bool(columns) and any(all(expected == values[i] or expected in {'.', '?'} and values[i] in {'.', '?'} for expected, values in columns)
                                             for i in range(len(indices)))
            keep = [i for i in range(len(data['_struct_conn.id'])) if has_partner(i, 1) and has_partner(i, 2)]
            for key, values in tuple(data.items()):
                if key.startswith('_struct_conn.'):
                    if keep:
                        data[key] = [values[i] for i in keep]
                    else:
                        del data[key]
        return ProteinStructure(text=write_mmcif_dictionary(data), format='mmcif')
    lines = source.text.splitlines()
    coordinate_lines = [line for line in lines if line.startswith(('ATOM  ', 'HETATM'))]
    serials = {coordinate_lines[i][6:11] for i in indices}
    component_models = {component['component_index']: component['model_id'] for component in description['components']}
    model_serials = {(component_models[description['atoms'][i]['component_index']], coordinate_lines[i][6:11]) for i in indices}
    chosen = set(indices)
    selected_atoms = {(coordinate_lines[i][12:16], coordinate_lines[i][16], coordinate_lines[i][17:20],
                       coordinate_lines[i][21], coordinate_lines[i][22:26], coordinate_lines[i][26]) for i in indices}
    selected_residues = {(coordinate_lines[i][21], coordinate_lines[i][22:26], coordinate_lines[i][26]) for i in indices}
    coordinate_index = -1
    last_atom_kept = False
    output = []
    model_lines = []
    in_model = False
    model_kept = False
    current_model = '1'
    for line in lines:
        record = line[:6].strip()
        if record == 'MODEL':
            current_model = line[10:14].strip()
            last_atom_kept = False
            in_model = True; model_kept = False; model_lines = [line]
            continue
        if record == 'ENDMDL':
            if model_kept:
                output.extend([*model_lines, line])
            in_model = False
            continue
        if record in {'ATOM', 'HETATM'}:
            coordinate_index += 1
            last_atom_kept = coordinate_index in chosen
            if not last_atom_kept:
                continue
            model_kept = True
        elif record == 'TER':
            if not last_atom_kept:
                continue
        elif record in {'ANISOU', 'SIGATM', 'SIGUIJ'}:
            if (current_model, line[6:11]) not in model_serials:
                continue
        elif record == 'CONECT':
            if line[6:11] not in serials:
                continue
            neighbors = [line[i:i + 5] for i in range(11, len(line), 5) if line[i:i + 5] in serials]
            if not neighbors:
                continue
            line = line[:11] + ''.join(neighbors)
        elif record == 'LINK':
            first = (line[12:16], line[16], line[17:20], line[21], line[22:26], line[26])
            second = (line[42:46], line[46], line[47:50], line[51], line[52:56], line[56])
            if first not in selected_atoms or second not in selected_atoms:
                continue
        elif record == 'SSBOND':
            if (line[15], line[17:21], line[21]) not in selected_residues or (line[29], line[31:35], line[35]) not in selected_residues:
                continue
        elif record in {'MASTER', 'NUMMDL', 'SITE'}:
            # These residue/topology summaries describe the original selection.
            continue
        (model_lines if in_model else output).append(line)
    return ProteinStructure(text='\n'.join(output) + '\n', format='pdb')


def export_structure_components(body: bytes, parameters: Mapping[str, Any], references: tuple[CandidateDataReference, ...]) -> dict[str, Any]:
    from .structure_export import convert_structure, StructureExportError
    source = candidate_structure(body, parameters['item_index'])
    selected = list(parameters['component_indices'])
    subset = select_components(source, selected)
    try:
        converted = convert_structure(subset, parameters['format'])
    except StructureExportError as error:
        raise ResultActionError(str(error)) from error
    return {'text': converted.text, 'format': converted.format, 'component_indices': selected}


EXPORT_COMPONENTS_ACTION = ResultActionDefinition(
    action_id='protein_io.export_structure_components', port_type_id='candidate.collection',
    parameters=admit_declarations({
        'item_index': {'parameter_scope': 'scientific', 'scientific_meaning': 'Published structure Candidate index.', 'required': True, 'value_contract': {'type': 'integer', 'minimum': 0}},
        'component_indices': {'parameter_scope': 'scientific', 'scientific_meaning': 'Explicit components of this immutable Candidate to export.', 'required': True, 'value_contract': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': {'type': 'integer', 'minimum': 1}}},
        'format': {'parameter_scope': 'scientific', 'scientific_meaning': 'Export format.', 'required': True, 'value_contract': {'type': 'string', 'enum': ['pdb', 'mmcif']}},
    }, path='protein_io.export_structure_components'), apply=export_structure_components,
)
