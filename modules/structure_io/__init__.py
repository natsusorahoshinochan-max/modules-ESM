"""Public structure reading, selection, extraction, conversion and coordinates."""
import json
import math
from pathlib import Path
from shutil import copyfileobj
from uuid import uuid4

import gemmi
from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort


def parse(content, encoding):
    """Read exactly one coordinate-file data block, retaining every atom/model."""
    if encoding == 'pdb':
        structure = gemmi.read_pdb_string(content)
        records = sum(line.startswith((b'ATOM  ', b'HETATM')) for line in content.splitlines())
        if sum(model.count_atom_sites() for model in structure) != records:
            raise ValueError('PDB atom records could not all be read without loss')
    elif encoding == 'mmcif':
        document = gemmi.cif.read_string(content.decode('utf-8'))
        if len(document) != 1:
            raise ValueError('Select a file with exactly one mmCIF coordinate data block')
        block = document.sole_block()
        for tag in ('auth_asym_id', 'auth_seq_id'):
            values = block.find_values('_atom_site.' + tag)
            if not values or any(value == '?' or (tag == 'auth_seq_id' and value == '.') for value in values):
                raise ValueError('mmCIF requires actual author chain and residue numbering for every atom')
        for tag in ('label_alt_id', 'pdbx_PDB_ins_code'):
            if any(value not in ('?', '.') and len(gemmi.cif.as_string(value)) > 1 for value in block.find_values('_atom_site.' + tag)):
                raise ValueError('Structure reader cannot preserve multi-character alternate-location or insertion codes')
        structure = gemmi.make_structure_from_block(block)
        scheme = block.get_mmcif_category('_pdbx_poly_seq_scheme.')
        if scheme:
            structure.info['_workbench_polymer_scheme'] = json.dumps(scheme)
        if sum(model.count_atom_sites() for model in structure) != len(block.find_values('_atom_site.auth_seq_id')):
            raise ValueError('mmCIF coordinate rows could not all be read as atoms')
    else:
        raise ValueError('Structure format must be pdb or mmcif')
    if not len(structure):
        raise ValueError('Structure file contains no coordinate models')
    numbers = [model.num for model in structure]
    if len(set(numbers)) != len(numbers):
        raise ValueError('Repeated model numbers cannot identify a conformation unambiguously')
    for model in structure:
        if not model.count_atom_sites():
            raise ValueError(f'Model {model.num} has no atoms')
        for chain in model:
            for residue in chain:
                if residue.seqid.num is None:
                    raise ValueError('Every residue requires an actual author residue number')
                for atom in residue:
                    if not all(math.isfinite(x) for x in (atom.pos.x, atom.pos.y, atom.pos.z, atom.occ, atom.b_iso)):
                        raise ValueError('Structure contains nonfinite atom coordinates, occupancy or B factor')
    return structure


def atoms(structure):
    """Stable zero-based atom indices follow the delivered file hierarchy."""
    result = []
    for model in structure:
        for chain in model:
            for residue in chain:
                for atom in residue:
                    result.append({'index': len(result), 'model': model.num, 'chain': chain.name,
                                   'author_number': residue.seqid.num, 'insertion_code': residue.seqid.icode.strip(),
                                   'residue_name': residue.name, 'atom_name': atom.name, 'element': atom.element.name,
                                   'altloc': atom.altloc.strip('\x00 '), 'position': [atom.pos.x, atom.pos.y, atom.pos.z]})
    return result


def encode(structure, encoding):
    if encoding == 'mmcif':
        document = structure.make_mmcif_document()
        scheme = structure.info['_workbench_polymer_scheme'] if '_workbench_polymer_scheme' in structure.info else None
        if scheme:
            document.sole_block().set_mmcif_category('_pdbx_poly_seq_scheme.', json.loads(scheme))
        return document.as_string().encode()
    if encoding != 'pdb':
        raise ValueError('Export format must be pdb or mmcif')
    if structure[0].count_atom_sites() > 99999:
        raise ValueError('PDB export exceeds the 99999 atom serial limit; choose mmCIF')
    for model in structure:
        if not 1 <= model.num <= 9999:
            raise ValueError('PDB model number requires 1–9999; choose mmCIF')
        for chain in model:
            if len(chain.name) > 1 or not chain.name.isascii():
                raise ValueError(f'PDB cannot represent chain {chain.name!r} in one character; choose mmCIF')
            for residue in chain:
                if not -999 <= residue.seqid.num <= 9999 or len(residue.name) > 3 or not residue.name.isascii() or not residue.seqid.icode.isascii():
                    raise ValueError('PDB cannot represent this residue number or component name; choose mmCIF')
                for atom in residue:
                    if len(atom.name) > 4 or not atom.name.isascii() or not atom.altloc.isascii() or any(len(f'{x:.3f}') > 8 for x in (atom.pos.x, atom.pos.y, atom.pos.z)):
                        raise ValueError('PDB cannot represent this atom name or coordinate; choose mmCIF')
                    if 'a' <= atom.altloc <= 'z':
                        raise ValueError(f'PDB writer cannot preserve alternate-location identifier {atom.altloc!r} exactly at model {model.num}, chain {chain.name!r}, residue {residue.seqid}, atom {atom.name!r}; choose mmCIF')
                    if not -9 <= atom.charge <= 9:
                        raise ValueError('PDB cannot represent this formal charge; choose mmCIF')
                    if any(len(f'{x:.2f}') > 6 for x in (atom.occ, atom.b_iso)):
                        raise ValueError('PDB cannot represent this occupancy or B factor; choose mmCIF')
    options = gemmi.PdbWriteOptions()
    options.numbered_ter = False
    options.end_record = False
    output = structure.make_pdb_string(options).encode()
    # PDB's single-model writer omits MODEL; preserve the actual source model.
    if len(structure) == 1 and not output.startswith(b'MODEL'):
        output = f'MODEL     {structure[0].num:4d}\n'.encode() + output + b'ENDMDL\nEND\n'
    return output


def import_structure(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    source = call.inputs['file'][0]
    with source.open(source.entry) as reader:
        description = json.load(reader)
    if not isinstance(description, dict) or set(description) != {'name', 'file', 'format'} or not isinstance(description['name'], str) or not description['name']:
        raise ValueError('Import requires exactly one named PDB or mmCIF file')
    with source.open(description['file']) as reader:
        original = reader.read()
    structure = parse(original, description['format'])
    if set(call.parameters) != {'models'}:
        raise ValueError('Choose one model number or all conformations as independent candidates')
    selected = call.parameters['models']
    if selected == 'all':
        selected = [model.num for model in structure]
    elif type(selected) is int:
        selected = [selected]
    else:
        raise ValueError('Choose one model number or all conformations as independent candidates')
    if any(number not in [model.num for model in structure] for number in selected):
        raise ValueError(f'Unknown model selection; available models: {[model.num for model in structure]}')
    folder = runtime.workdir / uuid4().hex
    folder.mkdir()
    original_key = 'original.pdb' if description['format'] == 'pdb' else 'original.cif'
    (folder / original_key).write_bytes(original)
    files = {original_key: str((folder / original_key).relative_to(runtime.workdir))}
    objects = []
    for number in selected:
        single = structure.clone()
        for index in reversed(range(len(single))):
            if single[index].num != number:
                del single[index]
        key = f'model-{number}.pdb' if description['format'] == 'pdb' else f'model-{number}.cif'
        view = f'model-{number}.atoms.json'
        encoded = encode(single, description['format'])
        for name, content in ((key, encoded), (view, json.dumps(atoms(parse(encoded, description['format']))).encode())):
            (folder / name).write_bytes(content)
            files[name] = str((folder / name).relative_to(runtime.workdir))
        objects.append({'id': uuid4().hex, 'label': f'{description["name"]} model {number}',
                        'source': {'name': description['name'], 'file': original_key, 'format': description['format'], 'model': number},
                        'structure': {'file': key, 'format': description['format']}, 'atoms': view})
    (folder / 'manifest.json').write_text(json.dumps({'objects': objects}))
    files['manifest.json'] = str((folder / 'manifest.json').relative_to(runtime.workdir))
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'structures': [Delivery('workbench.structure_set', 'manifest.json', files)]})


def read_structure(source, object_id):
    """Read a selected package object through its public read-only file access."""
    return _read_object(source, object_id)[2]


def _read_object(source, object_id):
    with source.open(source.entry) as reader:
        document = json.load(reader)
    if not isinstance(document, dict) or not isinstance(document.get('objects'), list) or any(not isinstance(obj, dict) for obj in document['objects']):
        raise ValueError('Structure operation requires a manifest with object descriptions')
    if source.format == 'workbench.prediction' and (not isinstance(document.get('tool'), dict) or not isinstance(document['tool'].get('parameters'), dict) or not isinstance(document['tool'].get('id'), str) or not document['tool']['id']):
        raise ValueError('Prediction operation requires its existing tool and calculation parameters')
    if object_id is None and len(document['objects']) == 1:
        object_id = document['objects'][0].get('id')
    matches = [obj for obj in document['objects'] if obj.get('id') == object_id]
    if len(matches) != 1:
        raise ValueError('Select exactly one actual structure object')
    obj = matches[0]
    if not isinstance(obj.get('structure'), dict) or not isinstance(obj['structure'].get('file'), str) or obj['structure'].get('format') not in ('pdb', 'mmcif'):
        raise ValueError('Selected object requires a declared PDB or mmCIF coordinate file')
    with source.open(obj['structure']['file']) as reader:
        content = reader.read()
    if source.format == 'workbench.coordinates':
        validate_coordinate_file(obj, content)
    structure = parse(content, obj['structure']['format'])
    if len(structure) != 1:
        raise ValueError('Structure operation requires a single selected conformation')
    return document, obj, structure


def validate_coordinate_file(obj, content):
    """Check the standalone coordinate format against its current mmCIF file."""
    from .target import read_target
    if obj['structure']['format'] != 'mmcif':
        raise ValueError('A coordinate track provides a current mmCIF representation')
    target = read_target(content)
    values, residues, mapping = obj.get('values'), obj.get('residues'), obj.get('positions')
    if not isinstance(values, list) or not isinstance(residues, list) or not isinstance(mapping, list) or len(values) != len(residues) or len(mapping) != len(values) or len(target['positions']) != len(values):
        raise ValueError('Coordinate values, residue identities and positions must correspond')
    for index, (actual, value, residue, position) in enumerate(zip(target['positions'], values, residues, mapping), 1):
        if not isinstance(position, dict) or position.get('sequence_index') != index or actual['author_number'] != index or actual['author_chain'] != 'A' or actual['atoms'] != (value or {}) or actual['residue'] != (residue or 'X'):
            raise ValueError('Coordinate file must contain exactly the current track values and current position numbering')


def existing_tracks(source, object_id, selected_positions):
    """Read supplied tracks and file secondary-structure records; never calculate."""
    _, obj, structure = _read_object(source, object_id)
    result = [{'secondary_structure': None, 'sasa': None, 'function_annotations': []} for _ in selected_positions]
    available = positions(structure)
    def identity(row):
        return (row['chain'], row['author_number'], row.get('insertion_code', ''))
    ordered = [identity(row) for row in available]
    ranges = []
    for helix in structure.helices:
        # PDB helix classes 1, 3 and 5 have exact DSSP8 counterparts.
        value = {1: 'H', 3: 'I', 5: 'G'}.get(helix.pdb_helix_class.value)
        if value:
            ranges.append((helix.start, helix.end, value))
    for sheet in structure.sheets:
        ranges.extend((strand.start, strand.end, 'E') for strand in sheet.strands)
    for start, end, value in ranges:
        a = (start.chain_name, start.res_id.seqid.num, start.res_id.seqid.icode.strip())
        b = (end.chain_name, end.res_id.seqid.num, end.res_id.seqid.icode.strip())
        if a not in ordered or b not in ordered:
            continue
        covered = set(ordered[ordered.index(a):ordered.index(b) + 1])
        for row, output in zip(selected_positions, result):
            if identity(row) in covered:
                output['secondary_structure'] = value
    tracks = obj.get('tracks', {})
    names = ('secondary_structure', 'sasa', 'function_annotations')
    if not any(name in tracks for name in names):
        return result
    correspondence = obj.get('positions')
    if not isinstance(correspondence, list) or not correspondence:
        raise ValueError('Supplied tracks require explicit residue positions')
    mapped = {}
    for index, row in enumerate(correspondence):
        if not isinstance(row, dict) or not {'chain', 'author_number', 'insertion_code'} <= set(row):
            raise ValueError('Supplied tracks require chain, author number and insertion code correspondence')
        key = identity(row)
        if key in mapped:
            raise ValueError('Supplied track residue correspondence is ambiguous')
        mapped[key] = index
    for name in names[:2]:
        if name in tracks and (not isinstance(tracks[name], list) or len(tracks[name]) != len(correspondence)):
            raise ValueError(f'Supplied {name} must cover its declared residue positions')
    annotations = tracks.get('function_annotations', [])
    if not isinstance(annotations, list) or any(not isinstance(a, dict) or set(a) != {'label', 'start', 'end'} or not isinstance(a['label'], str) or not a['label'].strip() or type(a['start']) is not int or type(a['end']) is not int or not 1 <= a['start'] <= a['end'] <= len(correspondence) for a in annotations):
        raise ValueError('Supplied annotations require labels and inclusive declared position intervals')
    for row, output in zip(selected_positions, result):
        index = mapped.get(identity(row))
        if index is None:
            continue
        for name in names[:2]:
            if name in tracks:
                output[name] = tracks[name][index]
        output['function_annotations'] = list(dict.fromkeys(a['label'] for a in annotations if a['start'] <= index + 1 <= a['end']))
    return result


def positions(structure):
    """Actual component positions with all corresponding atom indices/coordinates."""
    result = []
    index = 0
    for model in structure:
        for chain in model:
            for residue in chain:
                records = []
                for atom in residue:
                    records.append({'index': index, 'name': atom.name,
                                    'altloc': atom.altloc.strip('\x00 '),
                                    'position': [atom.pos.x, atom.pos.y, atom.pos.z]})
                    index += 1
                result.append({'model': model.num, 'chain': chain.name,
                               'author_number': residue.seqid.num,
                               'insertion_code': residue.seqid.icode.strip(),
                               'residue_name': residue.name, 'atoms': records})
    return result


def resolve_selection(structure, selection=None):
    """Resolve explicit atom, chain or real-position selection without guessing."""
    records = atoms(structure)
    if selection is None:
        return list(range(len(records)))
    if not isinstance(selection, dict) or len(selection) != 1:
        raise ValueError('Selection requires exactly one of atoms, chains or positions')
    kind, values = next(iter(selection.items()))
    if not isinstance(values, list) or not values:
        raise ValueError('Selection must be a nonempty list')
    if kind == 'atoms':
        if any(type(i) is not int or not 0 <= i < len(records) for i in values) or len(set(values)) != len(values):
            raise ValueError('Atom selection requires unique actual zero-based atom indices')
        return sorted(values)
    selected = set()
    if kind == 'chains':
        if any(not isinstance(chain, str) for chain in values) or len(set(values)) != len(values):
            raise ValueError('Chain selection requires unique actual chain names')
        for chain in values:
            found = [a['index'] for a in records if a['chain'] == chain]
            if not found:
                raise ValueError(f'Unknown chain selection: {chain!r}')
            selected.update(found)
    elif kind == 'positions':
        actual = positions(structure)
        for position in values:
            required = {'chain', 'author_number', 'insertion_code'}
            if (not isinstance(position, dict) or not required <= set(position)
                    or set(position) - required - {'model', 'residue_name'}
                    or not isinstance(position['chain'], str)
                    or type(position['author_number']) is not int
                    or not isinstance(position['insertion_code'], str)
                    or ('model' in position and type(position['model']) is not int)
                    or ('residue_name' in position and not isinstance(position['residue_name'], str))):
                raise ValueError('Position selection requires actual chain, integer author_number and insertion_code')
            found = [p for p in actual if all(p[key] == value for key, value in position.items())]
            if len(found) != 1:
                raise ValueError(f'Position selection must match exactly one actual component: {position!r}')
            selected.update(a['index'] for a in found[0]['atoms'])
    else:
        raise ValueError('Selection requires exactly one of atoms, chains or positions')
    return sorted(selected)


def _fragment_entities(structure):
    """Project current polymer declarations from retained actual residue groups."""
    # Fragment labels and polymer contents are rebuilt below; original full-chain
    # correspondence is retained only in the separately copied source file.
    if '_workbench_polymer_scheme' in structure.info:
        del structure.info['_workbench_polymer_scheme']
    fragments = {}
    entities = list(structure.entities)
    for model in structure:
        for chain in model:
            members = {}
            for group in chain.whole().residue_groups():
                assignments = []
                for residue in group:
                    matches = [entity for entity in entities if
                               (residue.subchain and residue.subchain in entity.subchains)
                               or (residue.entity_id and residue.entity_id == entity.name)]
                    # Gemmi's PDB parser names SEQRES entities from the explicit
                    # author-chain field, even when no TER supplies subchains.
                    if not matches and structure.input_format == gemmi.CoorFormat.Pdb and residue.het_flag == 'A':
                        matches = [entity for entity in entities if entity.name == chain.name and entity.entity_type == gemmi.EntityType.Polymer]
                    if len(matches) > 1:
                        raise ValueError(f'Ambiguous fragment entity at model {model.num}, chain {chain.name!r}, residue {residue.seqid}')
                    entity = matches[0] if matches else None
                    if (entity is None and structure.input_format == gemmi.CoorFormat.Mmcif
                            and residue.entity_type == gemmi.EntityType.Unknown
                            and any(item.entity_type == gemmi.EntityType.Polymer and not item.subchains for item in entities)):
                        raise ValueError(f'Fragment cannot associate an unbound polymer entity with model {model.num}, chain {chain.name!r}, residue {residue.seqid}')
                    if entity is not None and entity.entity_type == gemmi.EntityType.Polymer:
                        assignments.append((entity.name, residue.subchain, entity))
                    elif residue.entity_type == gemmi.EntityType.Polymer:
                        raise ValueError(f'Fragment polymer lacks an explicit entity at model {model.num}, chain {chain.name!r}, residue {residue.seqid}')
                if not assignments:
                    continue
                if len(assignments) != len(group) or len({item[:2] for item in assignments}) != 1:
                    raise ValueError(f'Ambiguous fragment residue-group entity at chain {chain.name!r}, residue {group[0].seqid}')
                name, subchain, entity = assignments[0]
                members.setdefault((name, subchain), (entity, []))[1].append(list(group))
            for (name, subchain), (source_entity, groups) in members.items():
                key = (chain.name, name, subchain)
                signature = [(str(group[0].seqid), tuple(residue.name for residue in group)) for group in groups]
                if key in fragments:
                    previous, entity = fragments[key]
                    if signature != previous:
                        raise ValueError(f'Models retain different fragment residue groups for chain {chain.name!r}, subchain {subchain!r}')
                else:
                    entity = gemmi.Entity(uuid4().hex)
                    entity.entity_type = gemmi.EntityType.Polymer
                    entity.polymer_type = source_entity.polymer_type
                    entity.subchains = [subchain or uuid4().hex]
                    entity.full_sequence = [','.join(dict.fromkeys(residue.name for residue in group)) for group in groups]
                    fragments[key] = (signature, entity)
                for position, group in enumerate(groups, 1):
                    for residue in group:
                        residue.entity_type = gemmi.EntityType.Polymer
                        residue.entity_id = entity.name
                        residue.subchain = entity.subchains[0]
                        residue.label_seq = position
    retained_subchains = {residue.subchain for model in structure for chain in model for residue in chain}
    for index in reversed(range(len(structure.entities))):
        entity = structure.entities[index]
        if entity.entity_type == gemmi.EntityType.Polymer:
            structure.entities.pop(index)
        elif entity.subchains:
            entity.subchains = [subchain for subchain in entity.subchains if subchain in retained_subchains]
            if not entity.subchains:
                structure.entities.pop(index)
    for _, entity in fragments.values():
        structure.entities.append(entity)


def extract(structure, selection):
    """Clone selected atoms, preserving their model, component and atom identities."""
    selected = set(resolve_selection(structure, selection))
    result = structure.clone()
    index = 0
    for model in result:
        for chain in model:
            for residue in chain:
                removals = []
                for ai in range(len(residue)):
                    if index not in selected:
                        removals.append(ai)
                    index += 1
                for ai in reversed(removals):
                    del residue[ai]
            for ri in reversed(range(len(chain))):
                if not len(chain[ri]):
                    del chain[ri]
        for ci in reversed(range(len(model))):
            if not len(model[ci]):
                del model[ci]
    for mi in reversed(range(len(result))):
        if not result[mi].count_atom_sites():
            del result[mi]
    _fragment_entities(result)
    return result


def transform(structure, rotation, translation, selection=None):
    """Clone and rigidly transform selected coordinates: rotation @ xyz + translation.

    Unselected atoms are retained unchanged. No centering, fitting or repair occurs.
    """
    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)
    if (not isinstance(rotation, (list, tuple)) or len(rotation) != 3
            or any(not isinstance(row, (list, tuple)) or len(row) != 3 or not all(finite_number(v) for v in row) for row in rotation)
            or not isinstance(translation, (list, tuple)) or len(translation) != 3
            or not all(finite_number(v) for v in translation)):
        raise ValueError('Rigid transform requires a finite 3x3 rotation and three-coordinate translation')
    for i in range(3):
        for j in range(3):
            if not math.isclose(sum(rotation[i][k] * rotation[j][k] for k in range(3)), float(i == j), abs_tol=1e-6):
                raise ValueError('Rotation must be orthonormal; scaling and shear are not coordinate rotations')
    determinant = sum(rotation[0][i] * (rotation[1][(i+1)%3] * rotation[2][(i+2)%3] - rotation[1][(i+2)%3] * rotation[2][(i+1)%3]) for i in range(3))
    if not math.isclose(determinant, 1, abs_tol=1e-6):
        raise ValueError('Rotation must have determinant +1')
    selected = set(resolve_selection(structure, selection))
    result = structure.clone()
    matrix = gemmi.Mat33()
    matrix.fromlist(rotation)
    index = 0
    for model in result:
        for chain in model:
            for residue in chain:
                for atom in residue:
                    if index in selected:
                        xyz = (atom.pos.x, atom.pos.y, atom.pos.z)
                        point = [sum(row[k] * xyz[k] for k in range(3)) + translation[i] for i, row in enumerate(rotation)]
                        if not all(math.isfinite(v) for v in point):
                            raise ValueError('Transformed coordinates must remain finite')
                        displacement = atom.aniso.transformed_by(matrix)
                        if not all(math.isfinite(v) for v in displacement.elements_pdb()):
                            raise ValueError(f'Transformed anisotropic displacement must remain finite at model {model.num}, chain {chain.name!r}, residue {residue.seqid}, atom {atom.name!r}')
                        atom.pos = gemmi.Position(*point)
                        atom.aniso = displacement
                    index += 1
    return result


def export_structure(call, runtime):
    return _process(call, runtime, 'export')


def extract_structure(call, runtime):
    return _process(call, runtime, 'extract')


def transform_structure(call, runtime):
    return _process(call, runtime, 'transform')


def _process(call, runtime, operation):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    allowed = {'object', 'format'} | ({'atoms'} if operation == 'export' else {'selection'})
    if operation == 'transform':
        allowed |= {'rotation', 'translation'}
    if set(call.parameters) - allowed:
        raise ValueError('Unknown structure operation parameters')
    source = call.inputs['structures'][0]
    document, obj, structure = _read_object(source, call.parameters.get('object'))
    selection = call.parameters.get('atoms') if operation == 'export' else call.parameters.get('selection')
    if operation == 'export':
        if selection is not None:
            structure = extract(structure, {'atoms': selection})
    elif operation == 'extract':
        if selection is None:
            raise ValueError('Extraction requires an explicit atom, chain or position selection')
        structure = extract(structure, selection)
    else:
        structure = transform(structure, call.parameters.get('rotation'), call.parameters.get('translation'), selection)
    encoding = call.parameters.get('format')
    content = encode(structure, encoding)
    folder = runtime.workdir / uuid4().hex
    folder.mkdir()
    files = {}
    # Preserve declared original research files and existing calculation records.
    for index, key in enumerate(source.files):
        destination = folder / f'preserved-{index}'
        with source.open(key) as reader, destination.open('wb') as writer:
            copyfileobj(reader, writer)
        files[key] = str(destination.relative_to(runtime.workdir))
    source_manifest_key = 'source-manifest-' + uuid4().hex + '.json'
    files[source_manifest_key] = files[source.entry]
    prefix = 'export-' + uuid4().hex
    key = prefix + ('.pdb' if encoding == 'pdb' else '.cif')
    view = prefix + '.atoms.json'
    exported = {name: obj[name] for name in ('label', 'source') if name in obj}
    exported.update({'id': uuid4().hex, 'structure': {'file': key, 'format': encoding}, 'atoms': view,
                     'source_manifest': {'file': source_manifest_key, 'format': source.format}})
    if operation == 'export':
        exported['selection'] = {'source_object': obj['id'], 'atoms': selection if selection is not None else 'all'}
    else:
        exported['operation'] = {'kind': operation, 'selection': selection if selection is not None else 'all',
                                 **({key: call.parameters[key] for key in ('rotation', 'translation')} if operation == 'transform' else {})}
    exported['source_object'] = obj
    note = 'Original calculation parameters, when present in the source package, belong to the source object. Exported selection was not recalculated.\n'
    for name, data in ((key, content), (view, json.dumps(atoms(parse(content, encoding))).encode()),
                       ('manifest.json', json.dumps({'objects': [exported], **({'tool': document['tool']} if 'tool' in document else {})}).encode()),
                       ('export-notes.txt', note.encode())):
        (folder / name).write_bytes(data)
        files[name] = str((folder / name).relative_to(runtime.workdir))
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'structures': [Delivery('workbench.structure_set', 'manifest.json', files)]})


def module():
    position = {'type': 'object', 'properties': {'chain': {'title': {'zh-CN': '链', 'en': 'Chain'}, 'type': 'string'}, 'author_number': {'title': {'zh-CN': '残基编号', 'en': 'Residue number'}, 'type': 'integer'}, 'insertion_code': {'title': {'zh-CN': '插入码', 'en': 'Insertion code'}, 'type': 'string', 'default': ''}}}
    selection = {'title': {'zh-CN': '选区', 'en': 'Selection'}, 'type': 'object', 'properties': {'chains': {'title': {'zh-CN': '链', 'en': 'Chain'}, 'type': 'array', 'items': {'type': 'string'}}, 'positions': {'title': {'zh-CN': '残基', 'en': 'Residue'}, 'type': 'array', 'items': position}, 'atoms': {'title': {'zh-CN': '原子索引', 'en': 'Atom indices'}, 'type': 'array', 'items': {'type': 'integer'}}}}
    return Module(id='workbench.structure_io', name={'zh-CN': '结构处理', 'en': 'Structure processing'}, nodes=(
        Node(id='workbench.import_structure', name={'zh-CN': '导入结构', 'en': 'Import structure'}, execute=import_structure,
             inputs={'file': InputPort(('workbench.structure_file',), name={'zh-CN': '文件', 'en': 'Files'})}, outputs={'structures': OutputPort('workbench.structure_set', name={'zh-CN': '结构', 'en': 'Structure'})},
             parameters={'models': {'description': 'Actual model number, or all for independent candidates', 'title': {'zh-CN': '构象', 'en': 'Conformations'}}}),
        Node(id='workbench.extract_structure', name={'zh-CN': '提取片段', 'en': 'Extract region'}, execute=extract_structure,
             inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.coordinates'), name={'zh-CN': '结构', 'en': 'Structure'})}, outputs={'structures': OutputPort('workbench.structure_set', name={'zh-CN': '结构', 'en': 'Structure'})},
             parameters={'object': {'title': {'zh-CN': '对象', 'en': 'Object'}, 'type': 'string'}, 'format': {'title': {'zh-CN': '文件格式', 'en': 'File format'}, 'enum': ['pdb', 'mmcif']}, 'selection': selection}),
        Node(id='workbench.transform_structure', name={'zh-CN': '移动与旋转', 'en': 'Move and rotate'}, execute=transform_structure,
             inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.coordinates'), name={'zh-CN': '结构', 'en': 'Structure'})}, outputs={'structures': OutputPort('workbench.structure_set', name={'zh-CN': '结构', 'en': 'Structure'})},
             parameters={'object': {'title': {'zh-CN': '对象', 'en': 'Object'}, 'type': 'string'}, 'format': {'title': {'zh-CN': '文件格式', 'en': 'File format'}, 'enum': ['pdb', 'mmcif']}, 'selection': selection,
                         'rotation': {'title': {'zh-CN': '旋转矩阵', 'en': 'Rotation matrix'}, 'type': 'array', 'default': [[1,0,0],[0,1,0],[0,0,1]], 'items': {'type': 'array', 'items': {'type': 'number'}}}, 'translation': {'title': {'zh-CN': '位移 (Å)', 'en': 'Translation (Å)'}, 'type': 'array', 'default': [0,0,0], 'items': {'type': 'number'}}}),
        Node(id='workbench.export_structure', name={'zh-CN': '导出结构', 'en': 'Export structure'}, execute=export_structure,
             inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.coordinates'), name={'zh-CN': '结构', 'en': 'Structure'})}, outputs={'structures': OutputPort('workbench.structure_set', name={'zh-CN': '结构', 'en': 'Structure'})},
             parameters={'object': {'title': {'zh-CN': '对象', 'en': 'Object'}, 'type': 'string'}, 'format': {'title': {'zh-CN': '文件格式', 'en': 'File format'}, 'enum': ['pdb', 'mmcif']}, 'atoms': {'title': {'zh-CN': '原子索引', 'en': 'Atom indices'}, 'type': 'array', 'items': {'type': 'integer'}}}),
    ), ui=str(Path(__file__).with_name('ui.js').resolve()))


def polymer_positions(source, object_id, chain_name):
    """Read a complete selected polymer chain, retaining coordinate-free positions.

mmCIF sequence labels establish correspondence. PDB SEQRES without an explicit
complete residue correspondence is rejected when observed and declared lengths
are different, rather than guessing how author numbering crosses missing atoms.
"""
    _, obj, structure = _read_object(source, object_id)
    actual = [row for row in positions(structure) if row['chain'] == chain_name]
    if not actual:
        raise ValueError('Selected chain has no actual structure positions')
    source_chain = structure[0][chain_name]
    protein = [(residue, row) for residue, row in zip(source_chain, actual, strict=True)
               if gemmi.find_tabulated_residue(residue.name).is_amino_acid()
               or residue.name in ('UNK', 'XLE')]
    if not protein:
        raise ValueError('Selected chain has no amino-acid positions')
    actual = [row for _, row in protein]
    if obj['structure']['format'] == 'pdb':
        entities = [entity for entity in structure.entities if entity.name == chain_name and entity.full_sequence]
        if entities and any(len(entity.full_sequence) != len(actual) for entity in entities):
            raise ValueError('PDB SEQRES does not supply correspondence for unobserved positions; provide mmCIF with explicit polymer position labels or select actual residues')
        return actual
    with source.open(obj['structure']['file']) as reader:
        block = gemmi.cif.read_string(reader.read().decode()).sole_block()
    declared = {gemmi.cif.as_string(row[0]):gemmi.cif.as_string(row[1]) for row in block.find('_struct_asym.', ['id','entity_id'])}
    polymer = {}
    for row in block.find('_entity_poly_seq.', ['entity_id','num','mon_id']):
        polymer.setdefault(gemmi.cif.as_string(row[0]), []).append((int(row[1]),gemmi.cif.as_string(row[2])))
    if not polymer:
        return actual
    subchains = {residue.subchain for residue, _ in protein}
    candidates = [(subchain, declared[subchain]) for subchain in subchains if subchain in declared and declared[subchain] in polymer]
    if len(candidates) != 1:
        raise ValueError('Selected chain requires one explicit polymer entity and label correspondence')
    subchain, entity = candidates[0]
    complete = polymer[entity]
    if [index for index, _ in complete] != list(range(1, len(complete) + 1)):
        raise ValueError('Source polymer sequence requires complete unique ordered positions')
    mapped = {}
    for residue, row in protein:
        if residue.subchain != subchain or residue.label_seq is None or residue.label_seq in mapped:
            raise ValueError('Observed residues require unique explicit sequence labels for complete-chain templates')
        mapped[residue.label_seq] = row
    if set(mapped) - set(range(1,len(complete)+1)):
        raise ValueError('Observed residue labels exceed the declared complete polymer')
    scheme = {}
    for row in block.find('_pdbx_poly_seq_scheme.', ['asym_id','seq_id','auth_seq_num','pdb_strand_id','pdb_ins_code']):
        if gemmi.cif.as_string(row[0]) == subchain:
            scheme[int(row[1])] = {'author_number':int(row[2]) if row[2] not in ('.','?') else None,
                'insertion_code':gemmi.cif.as_string(row[4]) if row[4] not in ('.','?') else ''}
    result = []
    for label, monomer in complete:
        if label in mapped:
            row = dict(mapped[label])
        else:
            row = {'model':structure[0].num, 'chain':chain_name,
                   'author_number':None, 'insertion_code':'', 'residue_name':monomer, 'atoms':[], **scheme.get(label,{})}
        row['label_position'] = {'chain':subchain, 'position':label}
        result.append(row)
    return result
