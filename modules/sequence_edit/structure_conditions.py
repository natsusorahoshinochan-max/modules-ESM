"""Current structure conditions using the structure module's public operations."""
import json
from shutil import copyfileobj
from uuid import uuid4

from modules.structure_io import read_structure, positions, transform, atoms, resolve_selection
from protein_workbench_public.module_api import Delivery, InteractionResult


def preserve_files(document, call, runtime):
    files = {}
    source = call.inputs.get('source', ())
    if source and source[0].format == 'workbench.sequence_conditions':
        for key in source[0].files:
            if key == 'edited.json':
                continue
            name = uuid4().hex
            with source[0].open(key) as reader, (runtime.workdir / name).open('wb') as writer:
                copyfileobj(reader, writer)
            files[key] = name
    for record in document.get('structures', []):
        if not isinstance(record, dict) or not isinstance(record.get('files'), dict):
            raise ValueError('Preserved structures require explicit package file keys')
        if set(record['files'].values()) - set(files):
            raise ValueError('Preserved structure files are unavailable; select the current delivered edit input')
    return files


class RetainedStructure:
    """Read the explicitly selected structure record inside an editing package."""
    def __init__(self, source, record):
        self.source = source
        self.record = record
        self.format = record['format']
        self.files = tuple(record['files'])
        matches = [key for key, value in record['files'].items() if value == record['entry']]
        if len(matches) != 1:
            raise ValueError('Preserved structure entry is unavailable')
        self.entry = matches[0]

    def open(self, key):
        if key not in self.record['files']:
            raise ValueError('Preserved structure file is unavailable')
        return self.source.open(self.record['files'][key])


def interaction(call, runtime):
    from . import _initial, _validate, _residue
    document = _initial(call)
    files = preserve_files(document, call, runtime)
    operation = call.parameters.get('operation', {})
    kind = operation.get('kind')
    view = []
    if kind in (None, 'adopt_structure'):
        selection = call.parameters.get('structure')
        if not isinstance(selection, dict):
            raise ValueError('Select an explicit input structure object or retained structure record')
        sources = call.inputs.get('structures', ())
        record = None
        if set(selection) == {'input', 'object'} and selection['input'] == 'structures' and isinstance(selection['object'], str) and selection['object'] and len(sources) == 1:
            source = sources[0]
            object_id = selection['object']
        elif set(selection) == {'retained'} and isinstance(selection['retained'], str) and selection['retained'] and not sources:
            matches = [item for item in document.get('structures', []) if item['id'] == selection['retained']]
            current = call.inputs.get('source', ())
            if len(matches) != 1 or not current or current[0].format != 'workbench.sequence_conditions':
                raise ValueError('Selected retained structure record is unavailable or ambiguous')
            record = matches[0]
            source = RetainedStructure(current[0], record)
            object_id = record['object']
        else:
            raise ValueError('Select one explicit input structure object or retained record, with matching inputs')
        structure = read_structure(source, object_id)
        actual = positions(structure)
        view = atoms(structure)
        if kind == 'adopt_structure':
            tracks = operation.get('tracks')
            mapping = operation.get('mapping')
            if not isinstance(tracks, list) or not tracks or len(set(tracks)) != len(tracks) or set(tracks) - {'coordinates', 'residue', 'fixed'}:
                raise ValueError('Select explicit coordinates, residue or fixed tracks')
            if not isinstance(mapping, list) or not mapping:
                raise ValueError('Select an explicit region mapping to current edit positions')
            by_id = {row['id']:row for row in document['positions']}
            used = set()
            record_id = record['id'] if record else uuid4().hex
            for item in mapping:
                identity = item.get('edit_position')
                selected = item.get('position')
                required = {'chain', 'author_number', 'insertion_code'}
                if identity not in by_id or identity in used or not isinstance(selected, dict) or not required <= set(selected) or set(selected) - required - {'model', 'residue_name'}:
                    raise ValueError('Map each selected current edit position once to an actual structure position')
                resolve_selection(structure, {'positions':[selected]})
                matches = [p for p in actual if all(p.get(key) == value for key,value in selected.items())]
                if len(matches) != 1:
                    raise ValueError('Each structure position must resolve exactly one actual component')
                position = matches[0]
                row = by_id[identity]
                if 'coordinates' in tracks:
                    coordinates = {}
                    for atom in position['atoms']:
                        if atom['altloc'] or atom['name'] in coordinates:
                            raise ValueError('Select a structure position with unambiguous atom names; alternate locations require explicit preparation')
                        coordinates[atom['name']] = atom['position']
                    row['coordinates'] = coordinates
                if 'residue' in tracks:
                    # Residue names are interpreted by the structure module's parser dependency.
                    import gemmi
                    residue = gemmi.find_tabulated_residue(position['residue_name'])
                    if not residue.is_amino_acid():
                        raise ValueError('Residue adoption requires an amino-acid component')
                    row['residue'] = _residue(residue.one_letter_code.upper())
                if 'fixed' in tracks:
                    if row['residue'] == '_':
                        raise ValueError('Choose an amino acid before fixing a position')
                    row['fixed'] = True
                row['prompt'] = row['residue'] if row['fixed'] else '_'
                row['structure_position'] = {'structure':record_id, 'position':{key:position[key] for key in ('model','chain','author_number','insertion_code','residue_name')}}
                used.add(identity)
            if record is None:
                retained = {}
                for key in source.files:
                    name = uuid4().hex
                    destination = record_id + '/' + key
                    with source.open(key) as reader, (runtime.workdir / name).open('wb') as writer:
                        copyfileobj(reader, writer)
                    files[destination] = name
                    retained[key] = destination
                document.setdefault('structures', []).append({'id':record_id,'object':object_id, 'format':source.format,'entry':retained[source.entry],'files':retained})
    elif kind == 'transform_coordinates':
        selected = operation.get('positions')
        rows = {row['id']:row for row in document['positions']}
        if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected) or set(selected) - set(rows):
            raise ValueError('Select explicit current edit positions for coordinate preview')
        # Reuse the public rigid-transform validation and computation on current coordinates.
        for identity in selected:
            row = rows[identity]
            if row['coordinates'] is None:
                raise ValueError('Selected position has no current coordinates')
            import gemmi
            structure = gemmi.Structure(); model = gemmi.Model('1'); chain = gemmi.Chain('A'); residue = gemmi.Residue()
            residue.name = 'UNK'; residue.seqid = gemmi.SeqId(1, ' ')
            for name, xyz in row['coordinates'].items():
                atom = gemmi.Atom(); atom.name = name; atom.pos = gemmi.Position(*xyz); residue.add_atom(atom)
            chain.add_residue(residue); model.add_chain(chain); structure.add_model(model)
            result = transform(structure, operation.get('rotation'), operation.get('translation'))
            row['coordinates'] = {atom['atom_name']:atom['position'] for atom in atoms(result)}
    else:
        raise ValueError('Unknown structure condition operation')
    document['sequence'] = ''.join(row['residue'] for row in document['positions'])
    _validate(document)
    if runtime.cancelled:
        raise ValueError('Structure preview cancelled')
    (runtime.workdir / 'edited.json').write_text(json.dumps(document, allow_nan=False))
    files['edited.json'] = 'edited.json'
    (runtime.workdir / 'view.json').write_text(json.dumps(view, allow_nan=False))
    files['view.json'] = 'view.json'
    return InteractionResult({'document_file':'edited.json','view_file':'view.json','position_count':len(document['positions'])},
        {'edited':Delivery('workbench.sequence_conditions','edited.json',files)})
