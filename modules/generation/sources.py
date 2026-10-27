"""Public current-condition reading and native generation-file encoding; see TOOL.md."""
from copy import deepcopy
import json
from uuid import uuid4

from .contract import GenerateResult

def read_sources(package):
    if package.format == 'workbench.sequence':
        from modules.sequence_io.formats import read_sequences, sequence_values
        return [{'id': obj['id'], 'tracks': {'sequence': sequence_values(obj['sequence'])}, 'positions': [
            {'sequence_index': index, 'source': {'object': obj['id'], 'sequence_index': index, 'position': deepcopy(row)}}
            for index, row in enumerate(obj.get('positions', [{'sequence_index': i + 1} for i in range(len(obj['sequence']))]), 1)]}
            for obj in read_sequences(package)]
    if package.format != 'workbench.protein':
        raise ValueError('Generation input requires an explicit sequence or prepared protein')
    with package.open(package.entry) as stream:
        document = json.load(stream)
    rows, tracks = document.get('positions'), document.get('tracks')
    if not isinstance(document.get('id'), str) or not isinstance(rows, list) or not rows:
        raise ValueError('Prepared protein requires current positions and an object ID')
    if not isinstance(tracks, dict) or set(tracks) != {'sequence', 'coordinates', 'secondary_structure', 'sasa', 'function_annotations'}:
        raise ValueError('Prepared protein requires all five explicit tracks')
    size = len(rows)
    for name in ('sequence', 'coordinates', 'secondary_structure', 'sasa'):
        if not isinstance(tracks[name], list) or len(tracks[name]) != size:
            raise ValueError(f'{name} must cover every current protein position')
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in rows) or len({row['id'] for row in rows}) != size:
        raise ValueError('Prepared protein positions require unique IDs')
    return [{'id': document['id'], 'tracks': deepcopy(tracks), 'positions': [
        {'sequence_index': i + 1, 'edit_position': row['id'],
         **({'source': deepcopy(row['source'])} if 'source' in row else {}),
         **({'structure_position': deepcopy(row['structure_position'])} if 'structure_position' in row else {})}
        for i, row in enumerate(rows)]}]


def read_inputs(call):
    """Whole-object and independent-track inputs are mutually exclusive."""
    from modules.sequence_edit.tracks import TRACK_FORMATS, read_track
    whole = call.inputs.get('source', ())
    supplied = {name: packages for name, packages in call.inputs.items() if name in TRACK_FORMATS and packages}
    if whole:
        if supplied or len(whole) != 1:
            raise ValueError('Choose either one whole protein source or independent tracks')
        return read_sources(whole[0])
    if not supplied:
        raise ValueError('Connect a protein source or at least one independent track')
    if any(len(packages) != 1 for packages in supplied.values()):
        raise ValueError('Each track input accepts one package')
    decoded = {name: read_track(packages[0], name) for name, packages in supplied.items()}
    first = next(iter(decoded.values()))
    sources = []
    for index, obj in enumerate(first):
        tracks = {}
        for name, objects in decoded.items():
            if len(objects) != len(first) or objects[index]['id'] != obj['id'] or objects[index]['positions'] != obj['positions']:
                raise ValueError('Independent tracks must describe the same object and explicit ordered positions')
            tracks[name] = deepcopy(objects[index]['values'])
        tracks.setdefault('sequence', [None] * len(obj['positions']))
        sources.append({'id': obj['id'], 'tracks': tracks, 'positions': [
            {'sequence_index': i + 1, **({'edit_position': row['id']} if 'id' in row else {}),
             'source': {'object': obj['id'], 'sequence_index': i + 1, 'position': deepcopy(row)}}
            for i, row in enumerate(obj['positions'])]})
    return sources


def request_for(track, tracks):
    from .contract import GenerateRequest
    return GenerateRequest(track, deepcopy(tracks))


def retain_result(result, request, source, ordinal, runtime, files):
    if not isinstance(result, GenerateResult):
        raise ValueError('ESM3 tool must return the public GenerateResult')
    sequence_values = result.tracks.get('sequence')
    supplied = request.tracks['sequence']
    if not isinstance(sequence_values, list) or len(sequence_values) != len(supplied) or any(not isinstance(symbol, str) or len(symbol) != 1 or symbol not in 'ACDEFGHIKLMNPQRSTVWYXBZUO.-|' for symbol in sequence_values):
        raise ValueError('ESM3 must return a complete native sequence with every input position represented')
    sequence = ''.join(sequence_values)
    if any(expected is not None and expected != actual for expected, actual in zip(supplied, sequence_values, strict=True)):
        raise ValueError('ESM3 changed a supplied sequence value')
    path = runtime.workdir / result.values_file
    if not path.resolve().is_relative_to(runtime.workdir.resolve()) or not path.is_file():
        raise ValueError('ESM3 native output file must belong to this invocation workdir')
    with path.open() as stream:
        native = json.load(stream)
    if native.get('tracks', {}).get('sequence') != sequence or not isinstance(native.get('metrics'), dict):
        raise ValueError('ESM3 native file must contain the actual sequence and natural metrics')
    key = 'native/' + uuid4().hex + '.json'
    files[key] = str(path.relative_to(runtime.workdir))
    obj = {'id': uuid4().hex, 'sequence': sequence, 'tracks': deepcopy(result.tracks), 'positions': deepcopy(source['positions']),
            'generation': {'input': source['id'], 'sample': ordinal + 1, 'tracks': deepcopy(request.tracks)},
            'native': {'file': key}, 'tool': {'parameters': deepcopy(result.parameters), 'actual_seed': result.actual_seed}, 'coordinate_role': result.coordinate_role}
    if result.structure_file is not None:
        structure = runtime.workdir / result.structure_file
        if not structure.resolve().is_relative_to(runtime.workdir.resolve()) or not structure.is_file() or result.coordinate_role != 'generated_structure':
            raise ValueError('Generated structure file must be a completed tool output in this workdir')
        key = 'structures/' + uuid4().hex + '.cif'
        files[key] = str(structure.relative_to(runtime.workdir))
        obj['structure'] = {'file': key, 'format': 'mmcif'}
    return obj, native
