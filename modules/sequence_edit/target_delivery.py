"""Portable five-track protein delivery and derived editor views."""
from copy import deepcopy
import json
from uuid import uuid4

from modules.structure_io.target import read_target, write_target
from protein_workbench_public.module_api import Delivery, InteractionResult

TRACKS = {'sequence', 'coordinates', 'secondary_structure', 'sasa', 'function_annotations'}
POSITION_METADATA = {'id', 'source', 'structure_position', 'target_author'}


def document_from_tracks(tracks, positions=None, *, object_id=None):
    """Decode prepared values without depending on any producing tool's layout."""
    from . import _position, _validate
    if not isinstance(tracks, dict) or set(tracks) != TRACKS:
        raise ValueError('Protein input requires all five prepared tracks')
    sequence = tracks['sequence']
    if not isinstance(sequence, list) or not sequence:
        raise ValueError('Protein sequence track requires nonempty ordered values and nulls')
    size = len(sequence)
    if any(not isinstance(tracks[key], list) or len(tracks[key]) != size for key in TRACKS - {'function_annotations'}):
        raise ValueError('Protein tracks must cover the same ordered positions')
    if positions is not None and (not isinstance(positions, list) or len(positions) != size or any(not isinstance(row, dict) for row in positions)):
        raise ValueError('Protein correspondence must cover all track positions')
    rows = []
    for index, residue in enumerate(sequence):
        row = _position(residue)
        row.update({key: deepcopy(tracks[key][index]) for key in ('coordinates', 'secondary_structure', 'sasa')})
        if positions is not None:
            metadata = positions[index]
            row.update({key: deepcopy(value) for key, value in metadata.items() if key in POSITION_METADATA})
            if object_id is not None and not row.get('source'):
                row['source'] = {'object': object_id, 'sequence_index': index + 1}
                correspondence = {key: deepcopy(metadata[key]) for key in ('chain', 'author_number', 'insertion_code') if key in metadata}
                if correspondence:
                    row['source']['position'] = correspondence
                if 'label_position' in metadata:
                    row['source']['label_position'] = deepcopy(metadata['label_position'])
        rows.append(row)
    annotations = tracks['function_annotations']
    if not isinstance(annotations, list):
        raise ValueError('Function annotations require an interval list')
    for annotation in annotations:
        if not isinstance(annotation, dict) or set(annotation) != {'label', 'start', 'end'}:
            raise ValueError('Each annotation requires label, start and end')
        label, start, end = (annotation[key] for key in ('label', 'start', 'end'))
        if not isinstance(label, str) or not label.strip() or type(start) is not int or type(end) is not int or not 1 <= start <= end <= size:
            raise ValueError('Function annotation must address an inclusive current position range')
        for row in rows[start - 1:end]:
            if label not in row['function_annotations']:
                row['function_annotations'].append(label)
    return _validate({'id': str(uuid4()), 'sequence': ''.join(residue or '_' for residue in sequence), 'positions': rows, 'random_operations': []})


def prepared_tracks(document):
    rows = [row for row in document['positions'] if not row.get('deleted', False)]
    annotations = []
    labels = list(dict.fromkeys(label for row in rows for label in row['function_annotations']))
    for label in labels:
        start = None
        for index in range(len(rows) + 1):
            present = index < len(rows) and label in rows[index]['function_annotations']
            if present and start is None:
                start = index + 1
            elif not present and start is not None:
                annotations.append({'label': label, 'start': start, 'end': index})
                start = None
    return {'sequence': [row['residue'] for row in rows],
            **{key: [deepcopy(row[key]) for row in rows] for key in ('coordinates', 'secondary_structure', 'sasa')},
            'function_annotations': annotations}


def protein_manifest(document):
    return {'id': document['id'],
            'positions': [{key: deepcopy(value) for key, value in row.items() if key in POSITION_METADATA} for row in document['positions']],
            'tracks': prepared_tracks(document),
            'target': {'file': 'target.cif', 'format': 'mmcif', 'chain': 'A'},
            **{key: deepcopy(document[key]) for key in ('structures', 'sources') if document.get(key)}}


def read_document(package):
    with package.open(package.entry) as reader:
        manifest = json.load(reader)
    if not isinstance(manifest.get('id'), str) or not manifest['id']:
        raise ValueError('Protein input requires an object identity')
    rows = manifest.get('positions')
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) - POSITION_METADATA or not isinstance(row.get('id'), str) for row in rows):
        raise ValueError('Protein positions contain identity and correspondence only')
    document = document_from_tracks(manifest.get('tracks'), rows)
    document['id'] = manifest['id']
    document.update({key: deepcopy(manifest[key]) for key in ('structures', 'sources') if key in manifest})
    target = manifest.get('target')
    if target is not None:
        if not isinstance(target, dict) or target.get('format') != 'mmcif' or not isinstance(target.get('file'), str):
            raise ValueError('Protein target must name its current mmCIF file')
        with package.open(target['file']) as reader:
            current = read_target(reader.read(), chain=target.get('chain'))
        if len(current['positions']) != len(document['positions']):
            raise ValueError('Target mmCIF must cover every current protein position')
        for row, actual in zip(document['positions'], current['positions']):
            if (row['residue'] or 'X') != actual['residue'] or (row['coordinates'] or {}) != actual['atoms']:
                raise ValueError('Target mmCIF must contain exactly the current sequence and coordinate values')
    if 'editor.json' in package.files:
        with package.open('editor.json') as reader:
            editor = json.load(reader)
        from . import _validate, active_document
        _validate(editor)
        effective = active_document(editor)
        if editor['id'] != document['id'] or protein_manifest(effective)['positions'] != manifest['positions'] or prepared_tracks(effective) != manifest['tracks']:
            raise ValueError('Editor content must agree with the delivered protein')
        document = editor
    return document


def _sequence_delivery(document, runtime):
    sequence = ''.join(row['residue'] or '_' for row in document['positions'])
    positions = []
    used = set()
    for index, row in enumerate(document['positions'], 1):
        position = {'sequence_index': index, 'id': row['id']}
        author = row.get('target_author')
        source = row.get('source', {})
        if author and author.get('author_number') is not None:
            key = (author.get('author_chain', 'A'), author['author_number'], author.get('insertion_code', ''))
            if key not in used:
                position.update(chain=key[0], author_number=key[1], insertion_code=key[2])
                used.add(key)
        elif isinstance(source.get('position'), dict):
            original = source['position']
            if {'chain', 'author_number', 'insertion_code'} <= set(original):
                key = (original['chain'], original['author_number'], original['insertion_code'])
                if key not in used:
                    position.update({name: original[name] for name in ('chain', 'author_number', 'insertion_code')})
                    used.add(key)
        if source.get('label_position'):
            position['label_position'] = deepcopy(source['label_position'])
        positions.append(position)
    value = {'objects': [{'id': document['id'], 'sequence': sequence, 'positions': positions}]}
    (runtime.workdir / 'sequence.json').write_text(json.dumps(value, allow_nan=False))
    return Delivery('workbench.sequence', 'sequence.json', {'sequence.json': 'sequence.json'})


def track_deliveries(document, runtime):
    from .tracks import TRACK_FORMATS
    sequence = _sequence_delivery(document, runtime)
    manifest = json.loads((runtime.workdir / 'sequence.json').read_text())['objects'][0]
    outputs = {'sequence': sequence}
    for track, values in prepared_tracks(document).items():
        if track == 'sequence':
            continue
        obj = {'id': document['id'], 'positions': manifest['positions'], 'values': values}
        files = {}
        if track == 'coordinates':
            obj['residues'] = [row['residue'] for row in document['positions']]
            from modules.structure_io import atoms, parse
            coordinates = write_target([{'residue': row['residue'] or '_', 'author_number': i + 1,
                                         'author_chain': 'A', 'atoms': row['coordinates'] or {}}
                                        for i, row in enumerate(document['positions'])])
            (runtime.workdir / 'coordinates.cif').write_bytes(coordinates)
            view = atoms(parse(coordinates, 'mmcif')) if any(values) else []
            (runtime.workdir / 'coordinates.atoms.json').write_text(json.dumps(view, allow_nan=False))
            obj.update(structure={'file': 'coordinates.cif', 'format': 'mmcif'}, atoms='coordinates.atoms.json')
            files.update({'coordinates.cif': 'coordinates.cif', 'coordinates.atoms.json': 'coordinates.atoms.json'})
        key = track + '.json'
        (runtime.workdir / key).write_text(json.dumps({'objects': [obj]}, ensure_ascii=False, allow_nan=False))
        outputs[track] = Delivery(TRACK_FORMATS[track], key, {key: key, **files})
    return outputs


def deliver(document, call, runtime, *, view=None, files=None):
    from . import establish_baseline, active_document
    establish_baseline(document)
    current = active_document(document)
    if not current['positions']:
        raise ValueError('请至少保留一个有效位置，再完成编辑。')
    from .structure_conditions import preserve_files, RetainedStructure
    source = call.inputs.get('source', ())
    files = preserve_files(document, call, runtime) if files is None else files
    if view is None and document.get('structures') and source:
        from modules.structure_io import atoms, read_structure
        first = document['structures'][0]
        package = RetainedStructure(source[0], first) if source[0].format == 'workbench.protein' else source[0]
        view = atoms(read_structure(package, first['object']))
    target = [{'residue': row['residue'] or '_', 'atoms': row['coordinates'] or {}, **row.get('target_author', {})} for row in current['positions']]
    (runtime.workdir / 'target.cif').write_bytes(write_target(target))
    (runtime.workdir / 'edited.json').write_text(json.dumps(protein_manifest(current), ensure_ascii=False, allow_nan=False))
    (runtime.workdir / 'editor.json').write_text(json.dumps(document, ensure_ascii=False, allow_nan=False))
    files.update({'target.cif': 'target.cif', 'edited.json': 'edited.json', 'editor.json': 'editor.json'})
    if document.get('structures') or any(row['coordinates'] is not None for row in document['positions']):
        display = {'document_file': 'editor.json', 'position_count': len(target)}
    else:
        display = {'document': document}
    if view is not None:
        (runtime.workdir / 'view.json').write_text(json.dumps(view, allow_nan=False))
        files['view.json'] = 'view.json'
        display['view_file'] = 'view.json'
    outputs = {'edited': Delivery('workbench.protein', 'edited.json', files)}
    outputs.update(track_deliveries(current, runtime))
    return InteractionResult(display, outputs)
