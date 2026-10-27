"""Protein Studio: independent editing of five aligned protein tracks."""
from copy import deepcopy
import json
import math
from pathlib import Path
import random
from uuid import uuid4

from protein_workbench_public.module_api import InputPort, Interaction, Module, Node, Outcome, OutputPort
from modules.sequence_io.formats import ALPHABET

FORMAT = 'workbench.protein'
TRACK_FIELDS = {'sequence': 'residue', 'coordinates': 'coordinates', 'secondary_structure': 'secondary_structure', 'sasa': 'sasa', 'function_annotations': 'function_annotations'}


def establish_baseline(document):
    """Keep one comparison value per original row, never an operation history."""
    if 'baseline' not in document:
        document['baseline'] = {row['id']: {key: deepcopy(row[key]) for key in TRACK_FIELDS.values()}
                                for row in document['positions']}
    return document


def active_document(document):
    current = {key: value for key, value in document.items() if key != 'baseline'}
    current['positions'] = [{key: value for key, value in row.items() if key != 'deleted'}
                            for row in document['positions'] if not row.get('deleted', False)]
    current['sequence'] = ''.join(row['residue'] or '_' for row in current['positions'])
    return current


def _residue(value):
    if value is not None and (not isinstance(value, str) or len(value) != 1 or value not in ALPHABET):
        raise ValueError('Each sequence position requires one uppercase amino acid or null')
    return value


def _sequence_values(value):
    if isinstance(value, str):
        return [_residue(None if residue == '_' else residue) for residue in value]
    if isinstance(value, list):
        return [_residue(residue) for residue in value]
    raise ValueError('Sequence requires amino-acid text or an ordered list of residues and nulls')


def _position(residue, source=None):
    return {'id': str(uuid4()), 'residue': _residue(residue), 'coordinates': None,
            'secondary_structure': None, 'sasa': None, 'function_annotations': [],
            **({'source': source} if source is not None else {})}


def _validate(document):
    if not isinstance(document, dict) or not isinstance(document.get('id'), str) or not document['id'] or not isinstance(document.get('positions'), list) or not document['positions']:
        raise ValueError('Protein document requires an identity and nonempty ordered positions')
    ids = set()
    for row in document['positions']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in ids:
            raise ValueError('Each edit position requires a distinct identity')
        if {'fixed', 'prompt', '_target_atoms'} & set(row):
            raise ValueError('Protein positions contain actual track values only')
        ids.add(row['id'])
        if 'deleted' in row and type(row['deleted']) is not bool:
            raise ValueError('Deleted position state must be boolean')
        _residue(row['residue'])
        coordinates = row['coordinates']
        if coordinates is not None:
            if not isinstance(coordinates, dict) or not coordinates:
                raise ValueError('Coordinates require named atom positions or null')
            for atom, point in coordinates.items():
                if not isinstance(atom, str) or not atom.lstrip('0123456789') or not atom.lstrip('0123456789')[0].isalpha() or not isinstance(point, list) or len(point) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point):
                    raise ValueError('Coordinates require finite XYZ values per named atom')
        ss = row['secondary_structure']
        if ss is not None and (not isinstance(ss, str) or len(ss) != 1 or ss not in 'GHITEBSC'):
            raise ValueError('Secondary structure requires a DSSP8 letter or null')
        sasa = row['sasa']
        if sasa is not None and (type(sasa) not in (int, float) or not math.isfinite(sasa) or sasa < 0):
            raise ValueError('SASA requires a nonnegative finite value or null')
        annotations = row['function_annotations']
        if not isinstance(annotations, list) or any(not isinstance(label, str) or not label.strip() for label in annotations) or len(set(annotations)) != len(annotations):
            raise ValueError('Function annotations require distinct nonempty labels per position')
    expected = ''.join(row['residue'] or '_' for row in document['positions'])
    if document.get('sequence') != expected:
        raise ValueError('Display sequence must match the ordered edit positions')
    if not isinstance(document.get('random_operations'), list):
        raise ValueError('Edit document requires random operation records')
    baseline = document.get('baseline')
    if baseline is not None:
        if not isinstance(baseline, dict) or set(baseline) - ids:
            raise ValueError('Original positions must remain available in the editor')
        for values in baseline.values():
            if not isinstance(values, dict) or set(values) != set(TRACK_FIELDS.values()):
                raise ValueError('Original positions require exactly five track values')
    return document


def _initial(call):
    packages = call.inputs.get('source', ())
    if 'document' in call.parameters:
        if packages:
            raise ValueError('Use the explicit source package without an inline document')
        document = _validate(deepcopy(call.parameters['document']))
        if document.get('structures'):
            raise ValueError('Retained structure documents require a file-backed source package')
        return document
    if packages:
        package = packages[0]
        if package.format == FORMAT:
            from .target_delivery import read_document
            return _validate(read_document(package))
        if package.format in ('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence'):
            from .structure_conditions import from_structure
            return from_structure(package, call.parameters)
        with package.open(package.entry) as reader:
            value = json.load(reader)
        objects = value.get('objects', [])
        selected = call.parameters.get('object')
        if selected is None and len(objects) == 1:
            selected = objects[0].get('id')
        matches = [obj for obj in objects if obj.get('id') == selected]
        if len(matches) != 1:
            raise ValueError('Select exactly one delivered protein object')
        obj = matches[0]
        if package.format in ('workbench.esm3_generation', 'workbench.joint_generation', 'workbench.coordinates'):
            from .target_delivery import document_from_tracks
            if package.format == 'workbench.coordinates':
                from .tracks import read_track
                obj = next(item for item in read_track(package, 'coordinates') if item['id'] == obj['id'])
                tracks = {'sequence': deepcopy(obj['residues']), 'coordinates': deepcopy(obj['values'])}
            else:
                tracks = deepcopy(obj['tracks'])
            lengths = [len(tracks[key]) for key in ('sequence', 'coordinates', 'secondary_structure', 'sasa') if isinstance(tracks.get(key), list)]
            if not lengths or len(set(lengths)) != 1:
                raise ValueError('Generated tracks require one explicit consistent position count')
            for key in ('sequence', 'coordinates', 'secondary_structure', 'sasa'):
                tracks.setdefault(key, [None] * lengths[0])
            tracks.setdefault('function_annotations', [])
            document = document_from_tracks(tracks, obj.get('positions'), object_id=obj['id'])
            record = uuid4().hex
            document['sources'] = [{'id': record, 'format': package.format, 'entry': record + '/' + package.entry,
                                    'files': {key: record + '/' + key for key in package.files}}]
            return document
        sequence = _sequence_values(obj['sequence'])
        mapping = obj.get('positions')
        if mapping is not None and (len(mapping) != len(sequence) or [row.get('sequence_index') for row in mapping] != list(range(1, len(sequence) + 1))):
            raise ValueError('Source positions must cover every sequence residue in order')
        rows = [_position(residue, {'object': obj['id'], 'sequence_index': i + 1, **({'position': mapping[i]} if mapping is not None else {})}) for i, residue in enumerate(sequence)]
    else:
        sequence = _sequence_values(call.parameters.get('sequence'))
        rows = [_position(residue) for residue in sequence]
    document = {'id': str(uuid4()), 'sequence': ''.join(row['residue'] or '_' for row in rows), 'positions': rows, 'random_operations': []}
    if packages:
        record = uuid4().hex
        document['sources'] = [{'id': record, 'format': package.format, 'entry': record + '/' + package.entry,
                                'files': {key: record + '/' + key for key in package.files}}]
    return _validate(document)


def _selected(operation, rows):
    selected = operation.get('positions')
    if not isinstance(selected, list) or not selected or any(not isinstance(item, str) for item in selected) or len(set(selected)) != len(selected) or set(selected) - {row['id'] for row in rows}:
        raise ValueError('Select current edit position identities')
    return selected


def _retain(document, operation):
    track = operation.get('track')
    if track not in TRACK_FIELDS:
        raise ValueError('Choose one protein track to retain')
    rows = document['positions']
    indices = operation.get('indices')
    if not isinstance(indices, list) or any(type(index) is not int or not 1 <= index <= len(rows) for index in indices) or len(set(indices)) != len(indices):
        raise ValueError('Retain requires distinct one-based current positions')
    names = operation.get('atoms')
    if names is not None and (track != 'coordinates' or not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names)):
        raise ValueError('Atom selection is available only for retained coordinates')
    field = TRACK_FIELDS[track]
    for index, row in enumerate(rows, 1):
        if index not in indices:
            row[field] = [] if field == 'function_annotations' else None
        elif names is not None:
            if not row['coordinates'] or set(names) - set(row['coordinates']):
                raise ValueError(f'Target position {index} has no requested real atoms')
            row['coordinates'] = {name: row['coordinates'][name] for name in names}


def edit(call, runtime):
    document = establish_baseline(_initial(call))
    if 'template_conditions' in call.parameters:
        raise ValueError('Edit actual track values with update or retain operations')
    if 'operation' in call.parameters and 'operations' in call.parameters:
        raise ValueError('Choose one interactive operation or an ordered operation list')
    operations = [call.parameters['operation']] if call.parameters.get('operation') else call.parameters.get('operations', [])
    if not isinstance(operations, list) or any(not isinstance(item, dict) for item in operations):
        raise ValueError('Editing operations must be an ordered list')
    for original in operations:
        operation = deepcopy(original)
        rows = document['positions']
        kind = operation.get('kind')
        if kind == 'replace_rows':
            replacement = operation.get('rows')
            if not isinstance(replacement, list):
                raise ValueError('Edited rows must be an ordered list')
            old = {row['id']: row for row in rows}
            candidate = []
            for edited in replacement:
                if not isinstance(edited, dict) or set(edited) != {'id', 'deleted', *TRACK_FIELDS.values()}:
                    raise ValueError('Edited rows require identity, deletion state and five track values')
                row = deepcopy(old.get(edited['id'], {}))
                row.update(deepcopy(edited))
                candidate.append(row)
            if set(old) - {row['id'] for row in candidate}:
                raise ValueError('Keep removed rows with their deletion state')
            document['positions'] = candidate
            continue
        if kind == 'retain':
            _retain(document, operation)
            continue
        if 'indices' in operation:
            indices = operation.pop('indices')
            if 'positions' in operation or not isinstance(indices, list) or not indices or any(type(index) is not int or not 1 <= index <= len(rows) for index in indices) or len(set(indices)) != len(indices):
                raise ValueError('Current target indices must be distinct one-based positions')
            operation['positions'] = [rows[index - 1]['id'] for index in indices]
        if kind == 'insert':
            index = operation.get('index')
            if type(index) is not int or not 0 <= index <= len(rows):
                raise ValueError('Insertion requires an existing zero-based gap index')
            rows[index:index] = [_position(residue) for residue in _sequence_values(operation.get('sequence'))]
        elif kind == 'random_insert':
            seed, count, start, end = (operation.get(key) for key in ('seed', 'count', 'start', 'end'))
            if any(type(value) is not int for value in (seed, count, start, end)) or not 0 <= start <= end <= len(rows) or not 0 <= count <= end - start + 1:
                raise ValueError('Random insertion requires integer seed, count and an inclusive range of distinct current gaps')
            alphabet = _sequence_values(operation.get('alphabet', '_'))
            if not alphabet:
                raise ValueError('Choose at least one insertion residue')
            rng = random.Random(seed)
            gaps = sorted(rng.sample(range(start, end + 1), count))
            actual = []
            for offset, gap in enumerate(gaps):
                row = _position(rng.choice(alphabet))
                rows.insert(gap + offset, row)
                actual.append({'gap': gap, 'index': gap + offset, 'position': row['id'], 'residue': row['residue']})
            document['random_operations'].append({'seed': seed, 'count': count, 'start': start, 'end': end, 'alphabet': alphabet, 'actual': actual})
        elif kind in ('delete', 'restore', 'update'):
            selected = _selected(operation, rows)
            if kind in ('delete', 'restore'):
                for row in rows:
                    if row['id'] in selected:
                        row['deleted'] = kind == 'delete'
            else:
                changes = operation.get('changes')
                if not isinstance(changes, dict) or not changes or set(changes) - set(TRACK_FIELDS.values()):
                    raise ValueError('Edit only sequence, coordinates, secondary structure, SASA or function annotations')
                for row in rows:
                    if row['id'] in selected:
                        row['deleted'] = False
                        row.update(deepcopy(changes))
        elif kind == 'transform_coordinates':
            from .structure_conditions import transform_current
            transform_current(document, operation)
        elif kind == 'reorder':
            order = _selected(operation, rows)
            if len(order) != len(rows):
                raise ValueError('Reordering must name every current position exactly once')
            by_id = {row['id']: row for row in rows}
            document['positions'] = [by_id[key] for key in order]
        else:
            raise ValueError('Unknown protein edit operation')
    document['sequence'] = ''.join(row['residue'] or '_' for row in document['positions'])
    _validate(document)
    if runtime.cancelled:
        raise ValueError('Edit cancelled')
    from .target_delivery import deliver
    return deliver(document, call, runtime)


def execute(call, runtime):
    if call.document is not None:
        from dataclasses import replace
        call = replace(call, inputs={'source': (call.document,)}, parameters={})
    result = edit(call, runtime)
    return Outcome(outputs={name: [output] for name, output in result.outputs.items()})


def module():
    from .structure_conditions import interaction
    from .tracks import TRACK_FORMATS, TRACK_NAMES
    inputs = {'source': InputPort(('workbench.sequence', 'workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.coordinates', 'workbench.esm3_generation', 'workbench.joint_generation', FORMAT), required=False, name={'zh-CN': '蛋白质输入', 'en': 'Protein input'}),
              'structures': InputPort(('workbench.structure_set', 'workbench.prediction'), required=False, name={'zh-CN': '参考三维结构', 'en': 'Reference 3D structure'})}
    return Module(id='workbench.sequence_edit', name={'zh-CN': 'Protein Studio', 'en': 'Protein Studio'}, ui=str(Path(__file__).with_name('ui.js')),
                  nodes=(Node('workbench.edit_sequence', {'zh-CN': '编辑蛋白质', 'en': 'Edit protein'}, execute, inputs=inputs, document_format=FORMAT,
                              outputs={'edited': OutputPort(FORMAT, name={'zh-CN': '蛋白质', 'en': 'Protein'}), **{name: OutputPort(format, name=TRACK_NAMES[name]) for name, format in TRACK_FORMATS.items()}}),),
                  interactions=(Interaction('workbench.sequence_edit', edit, inputs),
                                Interaction('workbench.sequence_structure', interaction, inputs)))
