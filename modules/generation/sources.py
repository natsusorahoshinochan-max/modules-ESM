"""Public current-condition reading and native generation-file encoding; see TOOL.md."""
from copy import deepcopy
import json
from uuid import uuid4

from .contract import GenerateResult

def read_sources(package):
    if package.format == 'workbench.sequence':
        from modules.sequence_io.formats import read_sequences
        return [{'id':obj['id'], 'prompt':obj['sequence'], 'positions':[
            {'sequence_index':index, 'source':{'object':obj['id'], 'sequence_index':index, 'position':deepcopy(row)}}
            for index, row in enumerate(obj.get('positions', [{'sequence_index':i+1} for i in range(len(obj['sequence']))]), 1)]}
            for obj in read_sequences(package)]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if package.format == 'workbench.sequence_conditions':
        rows, target, conditions = document.get('positions'), document.get('target'), document.get('conditions')
        if not isinstance(document.get('id'), str) or not isinstance(rows, list) or not rows:
            raise ValueError('Sequence conditions require current edit positions')
        if not isinstance(target, dict) or target.get('format') != 'mmcif' or not isinstance(target.get('file'), str) or target['file'] not in package.files:
            raise ValueError('Sequence conditions require the complete target mmCIF file')
        if not isinstance(conditions, dict) or set(conditions) != {'sequence', 'coordinates'}:
            raise ValueError('Sequence conditions require explicit sequence and coordinate selections')
        sequence = document.get('sequence')
        if not isinstance(sequence, str) or len(sequence) != len(rows):
            raise ValueError('Sequence must cover current condition positions')
        prompt = ['_'] * len(sequence)
        selected = set()
        for row in conditions['sequence']:
            position, residue = row.get('position'), row.get('residue')
            if type(position) is not int or not 1 <= position <= len(sequence) or position in selected or not isinstance(residue, str) or len(residue) != 1 or residue == '_' or residue != sequence[position - 1]:
                raise ValueError('Fixed sequence conditions must match unique current target positions')
            selected.add(position)
            prompt[position - 1] = residue
        return [{'id': document['id'], 'prompt': ''.join(prompt), 'target': deepcopy(target), 'conditions': deepcopy(conditions),
                 'positions': [{'sequence_index': i + 1, 'edit_position': row['id'], **({'source': deepcopy(row['source'])} if 'source' in row else {}), **({'structure_position': deepcopy(row['structure_position'])} if 'structure_position' in row else {})} for i, row in enumerate(rows)]}]
    raise ValueError('Generation input requires explicit sequence or sequence conditions')


def request_for(track, source, tracks, package, runtime):
    from .contract import GenerateRequest
    if 'target' not in source:
        return GenerateRequest(track, tracks)
    target = source['target']
    filename = 'target-' + uuid4().hex + '.cif'
    with package.open(target['file']) as stream:
        (runtime.workdir / filename).write_bytes(stream.read())
    return GenerateRequest(track, tracks, filename, deepcopy(source['conditions']))


def retain_result(result, request, source, ordinal, runtime, files):
    if not isinstance(result, GenerateResult):
        raise ValueError('ESM3 tool must return the public GenerateResult')
    sequence = result.tracks.get('sequence')
    prompt = request.tracks['sequence']
    if not isinstance(sequence, str) or len(sequence) != len(prompt) or any(symbol not in 'ACDEFGHIKLMNPQRSTVWYXBZUO.-|' for symbol in sequence):
        raise ValueError('ESM3 must return a complete native sequence with every input position represented')
    if any(expected != '_' and expected != actual for expected, actual in zip(prompt, sequence, strict=True)):
        raise ValueError('ESM3 changed a fixed Prompt position')
    path = runtime.workdir / result.values_file
    if not path.resolve().is_relative_to(runtime.workdir.resolve()) or not path.is_file():
        raise ValueError('ESM3 native output file must belong to this invocation workdir')
    with path.open() as stream:
        native = json.load(stream)
    if native.get('tracks', {}).get('sequence') != sequence or not isinstance(native.get('metrics'), dict):
        raise ValueError('ESM3 native file must contain the actual sequence and natural metrics')
    key = 'native/' + uuid4().hex + '.json'
    files[key] = str(path.relative_to(runtime.workdir))
    obj = {'id': uuid4().hex, 'sequence': sequence, 'positions': deepcopy(source['positions']),
            'generation': {'input': source['id'], 'sample': ordinal + 1, 'tracks': deepcopy(request.tracks), **({'target': deepcopy(source['target']), 'conditions': deepcopy(source['conditions'])} if 'target' in source else {})},
            'native': {'file': key}, 'tool': {'parameters': deepcopy(result.parameters), 'actual_seed': result.actual_seed}, 'coordinate_role': result.coordinate_role}
    if request.target_file is not None:
        key = 'targets/' + uuid4().hex + '.cif'
        files[key] = request.target_file
        obj['generation']['target']['file'] = key
    if result.structure_file is not None:
        structure = runtime.workdir / result.structure_file
        if not structure.resolve().is_relative_to(runtime.workdir.resolve()) or not structure.is_file() or result.coordinate_role != 'generated_structure':
            raise ValueError('Generated structure file must be a completed tool output in this workdir')
        key = 'structures/' + uuid4().hex + '.cif'
        files[key] = str(structure.relative_to(runtime.workdir))
        obj['structure'] = {'file': key, 'format': 'mmcif'}
    return obj, native
