"""Current structure conditions using the structure module's public operations."""
import json
from shutil import copyfileobj
from uuid import uuid4

from modules.structure_io import read_structure, positions, transform, atoms, resolve_selection


def preserve_files(document, call, runtime):
    files = {}
    source = call.inputs.get('source', ())
    if source and source[0].format == 'workbench.protein':
        for key in source[0].files:
            if key in {'edited.json', 'editor.json', 'target.cif', 'view.json'}:
                continue
            name = uuid4().hex
            with source[0].open(key) as reader, (runtime.workdir / name).open('wb') as writer:
                copyfileobj(reader, writer)
            files[key] = name
    if source and source[0].format != 'workbench.protein':
        for record in document.get('structures', []) + document.get('sources', []):
            for original, destination in record['files'].items():
                name = uuid4().hex
                with source[0].open(original) as reader, (runtime.workdir / name).open('wb') as writer:
                    copyfileobj(reader, writer)
                files[destination] = name
    for record in document.get('structures', []) + document.get('sources', []):
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
    from . import _initial, _validate, _residue, establish_baseline
    document = establish_baseline(_initial(call))
    files = preserve_files(document, call, runtime)
    operation = call.parameters.get('operation', {})
    kind = operation.get('kind')
    view = None
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
            if len(matches) != 1 or not current or current[0].format != 'workbench.protein':
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
            if not isinstance(tracks, list) or not tracks or len(set(tracks)) != len(tracks) or set(tracks) - {'coordinates', 'residue'}:
                raise ValueError('Select explicit coordinates or residue tracks')
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
                row['deleted'] = False
                if 'coordinates' in tracks:
                    coordinates = {}
                    for atom in position['atoms']:
                        if atom['altloc'] or atom['name'] in coordinates:
                            raise ValueError('Select a structure position with unambiguous atom names; alternate locations require explicit preparation')
                        coordinates[atom['name']] = atom['position']
                    names = operation.get('atoms')
                    if names is not None and (not isinstance(names, list) or not names or len(set(names)) != len(names) or set(names) - set(coordinates)):
                        raise ValueError('Coordinate adoption must select actual atom names')
                    row['coordinates'] = {name:coordinates[name] for name in names} if names is not None else coordinates
                    row['target_author'] = {'author_number':position['author_number'], 'author_chain':position['chain'], 'insertion_code':position['insertion_code']}
                if 'residue' in tracks:
                    # Residue names are interpreted by the structure module's parser dependency.
                    import gemmi
                    residue = gemmi.find_tabulated_residue(position['residue_name'])
                    if not residue.is_amino_acid() and position['residue_name'] not in ('UNK', 'XLE'):
                        raise ValueError('Residue adoption requires an amino-acid component')
                    row['residue'] = _residue('J' if position['residue_name'] == 'XLE' else 'X' if position['residue_name'] == 'UNK' else residue.one_letter_code.upper())
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
        transform_current(document, operation)
    else:
        raise ValueError('Unknown structure condition operation')
    document['sequence'] = ''.join(row['residue'] or '_' for row in document['positions'])
    _validate(document)
    if runtime.cancelled:
        raise ValueError('Structure preview cancelled')
    from .target_delivery import deliver
    return deliver(document, call, runtime, view=view, files=files)


def from_structure(source, parameters):
    """Build current template rows directly from selected chains or regions."""
    from . import _position, _residue
    import gemmi
    with source.open(source.entry) as reader:
        manifest = json.load(reader)
    objects = manifest.get('objects', [])
    object_id = parameters.get('object')
    if object_id is None and len(objects) == 1:
        object_id = objects[0]['id']
    structure = read_structure(source, object_id)
    selection = parameters.get('selection')
    if not isinstance(selection, dict) or not set(selection) <= {'chains', 'positions'}:
        raise ValueError('Choose a structure chain or explicit discontinuous residue positions to establish a template')
    selected = set(resolve_selection(structure, selection))
    actual = [position for position in positions(structure) if any(atom['index'] in selected for atom in position['atoms'])]
    if set(selection) == {'chains'} and len(selection['chains']) == 1:
        from modules.structure_io import polymer_positions
        actual = polymer_positions(source, object_id, selection['chains'][0])
    regions = parameters.get('regions')
    if regions:
        import re
        if not isinstance(regions, str):
            raise ValueError('Residue regions require comma-separated author numbers or ranges')
        retained = []
        for token in regions.split(','):
            match = re.fullmatch(r'\s*(-?\d+)([A-Za-z]?)(?:\s*:\s*(-?\d+)([A-Za-z]?))?\s*', token)
            if match is None:
                raise ValueError('Use author regions such as 12A,15:20,25:28')
            first = (int(match[1]), match[2]); last = (int(match[3]), match[4]) if match[3] else first
            if last < first:
                raise ValueError('Residue region end must follow its start')
            found = [position for position in actual if position['author_number'] is not None and first <= (position['author_number'], position['insertion_code']) <= last]
            if not found:
                raise ValueError(f'Residue region has no actual positions: {token.strip()}')
            retained.extend(found)
        actual = [position for position in actual if position in retained]
    if len({position['chain'] for position in actual}) != 1:
        raise ValueError('Establish one template from positions on one explicit chain')
    tracks = parameters.get('tracks', ['coordinates', 'sequence'])
    if not isinstance(tracks, list) or len(tracks) != len(set(tracks)) or set(tracks) - {'coordinates', 'sequence'}:
        raise ValueError('Initial protein tracks may select coordinates and sequence')
    atom_names = parameters.get('atoms')
    if atom_names is not None and (not isinstance(atom_names, list) or not atom_names or any(not isinstance(name, str) for name in atom_names) or len(atom_names) != len(set(atom_names))):
        raise ValueError('Choose distinct actual atom names for coordinate conditions')
    record_id = uuid4().hex
    from modules.structure_io import existing_tracks
    supplied_tracks = existing_tracks(source, object_id, actual)
    rows = []
    for position, supplied in zip(actual, supplied_tracks):
        residue = gemmi.find_tabulated_residue(position['residue_name'])
        if not residue.is_amino_acid() and position['residue_name'] not in ('UNK', 'XLE'):
            raise ValueError('A design template requires amino-acid positions; retained source components remain available')
        coordinates = {}
        for atom in position['atoms']:
            if atom['altloc'] or atom['name'] in coordinates:
                raise ValueError('Template positions require unambiguous atom names; prepare alternate locations explicitly')
            coordinates[atom['name']] = atom['position']
        if coordinates and atom_names is not None and set(atom_names) - set(coordinates):
            raise ValueError('Selected coordinate atom names are unavailable at a template position')
        origin = {key:position[key] for key in ('model','chain','author_number','insertion_code','residue_name')}
        row = _position(_residue('J' if position['residue_name'] == 'XLE' else 'X' if position['residue_name'] == 'UNK' else residue.one_letter_code.upper()), {'object':object_id, 'position':origin, **({'label_position':position['label_position']} if 'label_position' in position else {})})
        row.update(supplied)
        if 'sequence' not in tracks:
            row['residue'] = None
        row['coordinates'] = ({name:coordinates[name] for name in atom_names} if atom_names is not None else coordinates) if 'coordinates' in tracks and coordinates else None
        row['target_author'] = {'author_number':position['author_number'], 'author_chain':position['chain'], 'insertion_code':position['insertion_code']}
        row['structure_position'] = {'structure':record_id, 'position':origin}
        rows.append(row)
    retained = {key:record_id + '/' + key for key in source.files}
    return {'id':str(uuid4()), 'sequence':''.join(row['residue'] or '_' for row in rows), 'positions':rows, 'random_operations':[],
            'structures':[{'id':record_id, 'object':object_id, 'format':source.format, 'entry':retained[source.entry], 'files':retained}]}


def transform_current(document, operation):
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
