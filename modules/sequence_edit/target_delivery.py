"""File-backed target encoding and current editing-state reconstruction."""
from copy import deepcopy
import json
from modules.structure_io.target import read_target, write_target
from protein_workbench_public.module_api import Delivery, InteractionResult


def read_document(package):
    with package.open(package.entry) as reader:
        document = json.load(reader)
    target = document.get('target')
    if not isinstance(target, dict) or target.get('format') != 'mmcif' or not isinstance(target.get('file'), str):
        raise ValueError('Editing input requires its complete target mmCIF file')
    with package.open(target['file']) as reader:
        current = read_target(reader.read(), chain=target.get('chain'))
    rows = document.get('positions', [])
    if len(rows) != len(current['positions']):
        raise ValueError('Editing positions must cover the complete target')
    conditions = document.get('conditions')
    if not isinstance(conditions, dict) or set(conditions) != {'sequence', 'coordinates'}:
        raise ValueError('Editing input requires explicit sequence and coordinate conditions')
    fixed, coordinates = {}, {}
    for name, destination in [('sequence', fixed), ('coordinates', coordinates)]:
        if not isinstance(conditions[name], list):
            raise ValueError('Conditions must be explicit ordered position lists')
        for item in conditions[name]:
            index = item.get('position')
            if type(index) is not int or not 1 <= index <= len(rows) or index in destination:
                raise ValueError('Conditions must name distinct current target positions')
            destination[index] = item
    for index, (row, position) in enumerate(zip(rows, current['positions']), 1):
        if 'coordinates' in row or '_target_atoms' in row:
            raise ValueError('Target coordinates must be read from the declared mmCIF file')
        if row.get('residue', '').replace('_', 'X') != position['residue']:
            raise ValueError('Edited sequence does not match the complete target monomers')
        if row.get('fixed') != (index in fixed) or (index in fixed and fixed[index].get('residue') != row.get('residue')):
            raise ValueError('Sequence conditions do not match the current fixed residues')
        row['_target_atoms'] = position['atoms']
        row['coordinates'] = None
        if index in coordinates:
            names = coordinates[index].get('atoms')
            if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or len(names) != len(set(names)) or set(names) - set(position['atoms']):
                raise ValueError('Coordinate conditions must select actual target atoms')
            row['coordinates'] = {name:position['atoms'][name] for name in names}
    document.pop('target'); document.pop('conditions')
    return document


def deliver(document, call, runtime, *, view=None, files=None):
    from .structure_conditions import preserve_files
    source = call.inputs.get('source', ())
    if view is None and source and source[0].format in ('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence'):
        from modules.structure_io import atoms, read_structure
        view = atoms(read_structure(source[0], document['structures'][0]['object']))
    files = preserve_files(document, call, runtime) if files is None else files
    target = []
    manifest = deepcopy(document)
    conditions = {'sequence':[], 'coordinates':[]}
    for index, (row, saved) in enumerate(zip(document['positions'], manifest['positions']), 1):
        full = deepcopy(row.get('_target_atoms', {}))
        if row['coordinates'] is not None:
            full.update(row['coordinates'])
        row['_target_atoms'] = full
        # Coordinate conditions select target atoms; actual numbers live in mmCIF.
        target.append({'residue':row['residue'], 'atoms':full,
                       **row.get('target_author', {})})
        saved.pop('coordinates'); saved.pop('_target_atoms', None)
        if row['fixed']:
            conditions['sequence'].append({'position':index, 'residue':row['residue']})
        if row['coordinates'] is not None:
            conditions['coordinates'].append({'position':index, 'atoms':list(row['coordinates'])})
    manifest['target'] = {'file':'target.cif', 'format':'mmcif', 'chain':'A'}
    manifest['conditions'] = conditions
    (runtime.workdir / 'target.cif').write_bytes(write_target(target))
    (runtime.workdir / 'edited.json').write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False))
    files.update({'target.cif':'target.cif', 'edited.json':'edited.json'})
    # Display state is derived from the target and is never the package entry.
    if document.get('structures') or any(row['coordinates'] is not None for row in document['positions']) or view is not None:
        (runtime.workdir / 'editor.json').write_text(json.dumps(document, ensure_ascii=False, allow_nan=False))
        files['editor.json'] = 'editor.json'
        display = {'document_file':'editor.json', 'position_count':len(target)}
    else:
        display = {'document':document}
    if view is not None:
        (runtime.workdir / 'view.json').write_text(json.dumps(view, allow_nan=False))
        files['view.json'] = 'view.json'; display['view_file'] = 'view.json'
    return InteractionResult(display, {'edited':Delivery('workbench.sequence_conditions', 'edited.json', files)})
