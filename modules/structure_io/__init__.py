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
        return structure.make_mmcif_document().as_string().encode()
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
    matches = [obj for obj in document['objects'] if obj.get('id') == object_id]
    if len(matches) != 1:
        raise ValueError('Select exactly one actual structure object')
    obj = matches[0]
    if not isinstance(obj.get('structure'), dict) or not isinstance(obj['structure'].get('file'), str) or obj['structure'].get('format') not in ('pdb', 'mmcif'):
        raise ValueError('Selected object requires a declared PDB or mmCIF coordinate file')
    with source.open(obj['structure']['file']) as reader:
        structure = parse(reader.read(), obj['structure']['format'])
    if len(structure) != 1:
        raise ValueError('Structure operation requires a single selected conformation')
    return document, obj, structure


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
                        atom.pos = gemmi.Position(*point)
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
    return Module(id='workbench.structure_io', name='Structure processing, import and export', nodes=(
        Node(id='workbench.import_structure', name='Import one structure file', execute=import_structure,
             inputs={'file': InputPort(('workbench.structure_file',))}, outputs={'structures': OutputPort('workbench.structure_set')},
             parameters={'models': {'description': 'Actual model number, or all for independent candidates'}}),
        Node(id='workbench.extract_structure', name='Extract structure chains or fragments', execute=extract_structure,
             inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction'))}, outputs={'structures': OutputPort('workbench.structure_set')},
             parameters={'object': {'description': 'Selected object'}, 'format': {'enum': ['pdb', 'mmcif']}, 'selection': {'description': 'Explicit chains, actual positions or atom indices'}}),
        Node(id='workbench.transform_structure', name='Transform structure coordinates', execute=transform_structure,
             inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction'))}, outputs={'structures': OutputPort('workbench.structure_set')},
             parameters={'object': {'description': 'Selected object'}, 'format': {'enum': ['pdb', 'mmcif']}, 'selection': {'description': 'Optional chains, actual positions or atom indices'},
                         'rotation': {'description': '3x3 proper rotation applied about coordinate origin'}, 'translation': {'description': 'Three-coordinate translation in angstroms'}}),
        Node(id='workbench.export_structure', name='Export selected structure components', execute=export_structure,
             inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence'))}, outputs={'structures': OutputPort('workbench.structure_set')},
             parameters={'object': {'description': 'Selected object'}, 'format': {'enum': ['pdb', 'mmcif']}, 'atoms': {'description': 'Optional actual atom indices'}}),
    ), ui=str(Path(__file__).with_name('ui.js').resolve()))
