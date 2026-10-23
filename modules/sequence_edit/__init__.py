"""Independent sequence, position and conditioning editor."""
from copy import deepcopy
import json
import math
from pathlib import Path
import random
from uuid import uuid4

from protein_workbench_public.module_api import (
    Delivery, InputPort, Interaction, InteractionResult, Module, Node, Outcome, OutputPort,
)

FORMAT = 'workbench.sequence_conditions'
ALPHABET = 'ACDEFGHIKLMNPQRSTVWYBXZJUO_'


def _residue(value):
    if not isinstance(value, str) or len(value) != 1 or value not in ALPHABET:
        raise ValueError('Each position requires one uppercase amino acid or _')
    return value


def _position(residue, source=None):
    return {'id': str(uuid4()), 'residue': _residue(residue), 'prompt': residue,
            'fixed': residue != '_', 'coordinates': None, **({'source': source} if source is not None else {})}


def _validate(document):
    if not isinstance(document, dict) or not isinstance(document.get('id'), str) or not isinstance(document.get('positions'), list):
        raise ValueError('Edit document requires identity and ordered positions')
    ids = set()
    for row in document['positions']:
        if not isinstance(row.get('id'), str) or row['id'] in ids:
            raise ValueError('Each edit position requires a distinct identity')
        ids.add(row['id'])
        _residue(row['residue']); _residue(row['prompt'])
        if type(row['fixed']) is not bool:
            raise ValueError('Fixed condition must be true or false')
        if row['prompt'] != (row['residue'] if row['fixed'] else '_') or (row['fixed'] and row['residue'] == '_'):
            raise ValueError('Prompt must use each fixed residue and mask each variable position')
        coordinates = row['coordinates']
        if coordinates is not None:
            if not isinstance(coordinates, dict) or not coordinates:
                raise ValueError('Structure condition requires named atom coordinates')
            for atom, point in coordinates.items():
                if not isinstance(atom, str) or not atom or not isinstance(point, list) or len(point) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point):
                    raise ValueError('Structure condition requires finite XYZ coordinates per named atom')
    if document.get('sequence') != ''.join(row['residue'] for row in document['positions']):
        raise ValueError('Sequence must match the ordered edit positions')
    if not isinstance(document.get('random_operations'), list):
        raise ValueError('Edit document requires random operation records')
    return document


def _initial(call):
    packages = call.inputs.get('source', ())
    if 'document' in call.parameters:
        if packages and packages[0].format == FORMAT:
            raise ValueError('Use the accepted source package without an inline document')
        document = _validate(deepcopy(call.parameters['document']))
        if document.get('structures') or any(row['coordinates'] is not None or row.get('_target_atoms') for row in document['positions']):
            raise ValueError('Coordinate and retained structure documents require a file-backed source package')
        return document
    if packages:
        package = packages[0]
        with package.open(package.entry) as reader:
            value = json.load(reader)
        if package.format == FORMAT:
            from .target_delivery import read_document
            return _validate(read_document(package))
        if package.format in ('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence'):
            from .structure_conditions import from_structure
            return from_structure(package, call.parameters)
        objects = value.get('objects', [])
        selected = call.parameters.get('object')
        if selected is None and len(objects) == 1:
            selected = objects[0].get('id')
        matches = [obj for obj in objects if obj.get('id') == selected]
        if len(matches) != 1:
            raise ValueError('Select exactly one delivered sequence object')
        obj = matches[0]
        sequence = obj['sequence']
        mapping = obj.get('positions')
        if mapping is not None and (len(mapping) != len(sequence) or [row.get('sequence_index') for row in mapping] != list(range(1, len(sequence) + 1))):
            raise ValueError('Source positions must cover every sequence residue in order')
        rows = [_position(residue, {'object': obj['id'], 'sequence_index': i + 1, **({'position': mapping[i]} if mapping is not None else {})}) for i, residue in enumerate(sequence)]
    else:
        sequence = call.parameters.get('sequence')
        if not isinstance(sequence, str):
            raise ValueError('Sequence input is unavailable; select a delivered package or enter an explicit sequence')
        rows = [_position(residue) for residue in sequence]
    return {'id': str(uuid4()), 'sequence': sequence, 'positions': rows, 'random_operations': []}


def edit(call, runtime):
    document = _initial(call)
    if 'operation' in call.parameters and 'operations' in call.parameters:
        raise ValueError('Choose one interactive operation or an ordered operation list')
    operations = [call.parameters['operation']] if call.parameters.get('operation') else call.parameters.get('operations', [])
    if not isinstance(operations, list) or any(not isinstance(item, dict) for item in operations):
        raise ValueError('Editing operations must be an ordered list')
    for original in operations:
        operation = deepcopy(original)
        rows = document['positions']
        if 'indices' in operation:
            indices = operation.pop('indices')
            if 'positions' in operation or not isinstance(indices, list) or not indices or any(type(index) is not int or not 1 <= index <= len(rows) for index in indices) or len(set(indices)) != len(indices):
                raise ValueError('Current target indices must be distinct one-based positions')
            operation['positions'] = [rows[index - 1]['id'] for index in indices]
        kind = operation.get('kind')
        if kind in ('insert', 'random_insert'):
            if kind == 'insert':
                index = operation.get('index')
                sequence = operation.get('sequence')
                if type(index) is not int or not 0 <= index <= len(rows) or not isinstance(sequence, str):
                    raise ValueError('Insertion requires an existing gap index and explicit sequence')
                rows[index:index] = [_position(residue) for residue in sequence]
            else:
                seed, count, start, end = (operation.get(key) for key in ('seed', 'count', 'start', 'end'))
                if any(type(value) is not int for value in (seed, count, start, end)) or not 0 <= start <= end <= len(rows) or not 0 <= count <= end - start + 1:
                    raise ValueError('Random insertion requires integer seed, count and an inclusive range of distinct current gaps')
                alphabet = operation.get('alphabet', '_')
                if not isinstance(alphabet, str) or not alphabet:
                    raise ValueError('Choose at least one insertion residue')
                for residue in alphabet:
                    _residue(residue)
                rng = random.Random(seed)
                gaps = sorted(rng.sample(range(start, end + 1), count))
                actual = []
                for offset, gap in enumerate(gaps):
                    row = _position(rng.choice(alphabet))
                    rows.insert(gap + offset, row)
                    actual.append({'gap': gap, 'index': gap + offset, 'position': row['id'], 'residue': row['residue']})
                document['random_operations'].append({'seed': seed, 'count': count, 'start': start, 'end': end, 'alphabet': alphabet, 'actual': actual})
        elif kind in ('delete', 'update'):
            selected = operation.get('positions')
            if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected) or set(selected) - {row['id'] for row in rows}:
                raise ValueError('Select current edit position identities')
            if kind == 'delete':
                document['positions'] = [row for row in rows if row['id'] not in selected]
            else:
                changes = operation.get('changes')
                if not isinstance(changes, dict) or set(changes) - {'residue', 'prompt', 'fixed', 'coordinates'}:
                    raise ValueError('Edit only residue, Prompt, fixed/variable or structure conditions')
                for row in rows:
                    if row['id'] in selected:
                        row.update(deepcopy(changes))
                        if 'prompt' in changes:
                            if changes['prompt'] == '_':
                                if changes.get('fixed') is True:
                                    raise ValueError('A masked Prompt position cannot be fixed')
                                row['fixed'] = False
                            else:
                                if changes.get('fixed') is False or ('residue' in changes and changes['residue'] != changes['prompt']):
                                    raise ValueError('A fixed Prompt residue must match the edited sequence')
                                row['residue'] = _residue(changes['prompt'])
                                row['fixed'] = True
                        if row['residue'] == '_':
                            if changes.get('fixed') is True:
                                raise ValueError('Choose an amino acid before fixing a position')
                            row['fixed'] = False
                        row['prompt'] = row['residue'] if row['fixed'] else '_'
        elif kind == 'reorder':
            order = operation.get('positions')
            by_id = {row['id']: row for row in rows}
            if not isinstance(order, list) or len(order) != len(rows) or len(set(order)) != len(rows) or set(order) != set(by_id):
                raise ValueError('Reordering must name every current position exactly once')
            document['positions'] = [by_id[key] for key in order]
        else:
            raise ValueError('Unknown sequence edit operation')
    if 'template_conditions' in call.parameters:
        _template_conditions(document, call.parameters['template_conditions'])
    document['sequence'] = ''.join(row['residue'] for row in document['positions'])
    _validate(document)
    if runtime.cancelled:
        raise ValueError('Edit cancelled')
    from .target_delivery import deliver
    return deliver(document, call, runtime)


def _template_conditions(document, conditions):
    """Apply an explicit reusable selection to the current target after edits."""
    if not isinstance(conditions, dict) or set(conditions) - {'fixed_positions', 'coordinate_positions', 'atoms'} or not {'fixed_positions', 'coordinate_positions'} <= set(conditions):
        raise ValueError('Template conditions require explicit fixed_positions and coordinate_positions')
    rows = document['positions']
    for key in ('fixed_positions', 'coordinate_positions'):
        indices = conditions[key]
        if not isinstance(indices, list) or any(type(index) is not int or not 1 <= index <= len(rows) for index in indices) or len(set(indices)) != len(indices):
            raise ValueError('Template conditions require distinct current one-based target positions')
    names = conditions.get('atoms')
    if names is not None and (not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names)):
        raise ValueError('Template coordinate conditions require explicit atom names')
    for index, row in enumerate(rows, 1):
        row['fixed'] = index in conditions['fixed_positions']
        if row['fixed'] and row['residue'] == '_':
            raise ValueError('Choose an amino acid before fixing a target position')
        row['prompt'] = row['residue'] if row['fixed'] else '_'
        actual = deepcopy(row.get('_target_atoms', {}))
        actual.update(row['coordinates'] or {})
        row['_target_atoms'] = actual
        if index in conditions['coordinate_positions']:
            if not actual or (names is not None and set(names) - set(actual)):
                raise ValueError(f'Target position {index} has no requested real coordinate atoms')
            row['coordinates'] = {name:actual[name] for name in names} if names is not None else actual
        else:
            row['coordinates'] = None


def execute(call, runtime):
    result = edit(call, runtime)
    return Outcome(outputs={'edited': [result.outputs['edited']]})


def module():
    from .structure_conditions import interaction
    inputs = {'source': InputPort(('workbench.sequence', 'workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', FORMAT), required=False),
              'structures': InputPort(('workbench.structure_set', 'workbench.prediction'), required=False)}
    return Module(id='workbench.sequence_edit', name='Sequence and condition editing',
                  ui=str(Path(__file__).with_name('ui.js')),
                  nodes=(Node('workbench.edit_sequence', 'Edit sequence and conditions', execute,
                              inputs=inputs, outputs={'edited': OutputPort(FORMAT)}),),
                  interactions=(Interaction('workbench.sequence_edit', edit, inputs),
                                Interaction('workbench.sequence_structure', interaction, inputs)))
