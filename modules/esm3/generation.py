"""Public current-condition reading and native generation-file encoding; see TOOL.md."""
from copy import deepcopy
import json
from uuid import uuid4

from .contract import ESM3Result

def read_sources(package):
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if package.format == 'workbench.sequence_conditions':
        rows = document.get('positions')
        if not isinstance(document.get('id'), str) or not isinstance(rows, list) or not rows or len({row.get('id') for row in rows}) != len(rows):
            raise ValueError('Sequence conditions require distinct edit positions')
        for row in rows:
            if not isinstance(row.get('id'), str) or not isinstance(row.get('residue'), str) or len(row['residue']) != 1 or type(row.get('fixed')) is not bool or row.get('prompt') != (row['residue'] if row['fixed'] else '_') or row['fixed'] and row['residue'] == '_':
                raise ValueError('Sequence conditions must contain consistent current residues, Prompt and fixed regions')
            if 'coordinates' not in row:
                raise ValueError('Sequence conditions require explicit current coordinates or null')
        if document.get('sequence') != ''.join(row['residue'] for row in rows):
            raise ValueError('Sequence must match current condition positions')
        return [{'id': document['id'], 'prompt': ''.join(row['prompt'] for row in rows),
                 'positions': [{'sequence_index': i + 1, 'edit_position': row['id'], **({'source': deepcopy(row['source'])} if 'source' in row else {}), **({'structure_position': deepcopy(row['structure_position'])} if 'structure_position' in row else {})} for i, row in enumerate(rows)],
                 'coordinates': [row['coordinates'] for row in rows]}]
    if set(document) != {'objects'}:
        raise ValueError('Sequence input cannot contain additional components or conditions')
    objects = document.get('objects')
    if not isinstance(objects, list) or not objects or any(not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not isinstance(obj.get('sequence'), str) or not obj['sequence'] for obj in objects) or len({obj['id'] for obj in objects}) != len(objects):
        raise ValueError('Completion requires explicit ordered sequence objects')
    sources = []
    for obj in objects:
        if set(obj) - {'id', 'sequence', 'label', 'source', 'positions'}:
            raise ValueError('Sequence input cannot contain additional components or conditions')
        sequence = obj['sequence']
        if any(symbol not in 'ACDEFGHIKLMNPQRSTVWY' for symbol in sequence):
            raise ValueError('workbench.sequence requires canonical amino acids; edit a sequence to add variable positions')
        positions = obj.get('positions', [{'sequence_index': i + 1} for i in range(len(sequence))])
        if not isinstance(positions, list) or len(positions) != len(sequence) or [row.get('sequence_index') for row in positions] != list(range(1, len(sequence) + 1)):
            raise ValueError('Sequence positions must cover every residue in order')
        seen = set()
        for row in positions:
            mapping = set(row) - {'sequence_index'}
            if mapping and (mapping != {'chain', 'author_number', 'insertion_code'} or not isinstance(row['chain'], str) or type(row['author_number']) is not int or not isinstance(row['insertion_code'], str)):
                raise ValueError('Sequence positions require complete real residue correspondence')
            if mapping:
                identity = (row['chain'], row['author_number'], row['insertion_code'])
                if identity in seen:
                    raise ValueError('Sequence positions contain repeated real residues')
                seen.add(identity)
        sources.append({'id': obj['id'], 'prompt': sequence, 'positions': [{'sequence_index': i + 1, 'source': {'object': obj['id'], 'sequence_index': i + 1, 'position': deepcopy(row)}} for i, row in enumerate(positions)]})
    return sources


def retain_result(result, request, source, ordinal, runtime, files):
    if not isinstance(result, ESM3Result):
        raise ValueError('ESM3 tool must return the public ESM3Result')
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
    return {'id': uuid4().hex, 'sequence': sequence, 'positions': deepcopy(source['positions']),
            'generation': {'input': source['id'], 'sample': ordinal + 1, 'tracks': deepcopy(request.tracks)},
            'native': {'file': key}, 'tool': {'parameters': deepcopy(result.parameters), 'actual_seed': result.actual_seed}}, native
