"""Sequence completion and conditioned generation; task ownership stays here."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from .contract import ESM3Request, ESM3Result

FORMAT = 'workbench.esm3_generation'


def _sources(package):
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


def _copy_previous(package, runtime, files):
    for key in package.files:
        if key != package.entry:
            path = uuid4().hex
            with package.open(key) as source, (runtime.workdir / path).open('wb') as target:
                shutil.copyfileobj(source, target)
            files[key] = path


def _generated(result, request, source, ordinal, runtime, files):
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
            'native': {'file': key}, 'tool': {'parameters': deepcopy(result.parameters), 'actual_seed': result.actual_seed}}


def execute(call, runtime):
    if set(call.parameters) - {'samples', 'conditions'}:
        raise ValueError('Sequence generation accepts samples and explicit conditions')
    samples = call.parameters.get('samples', 1)
    if type(samples) is not int or samples < 1:
        raise ValueError('samples requires a positive integer')
    conditions = call.parameters.get('conditions', {})
    if not isinstance(conditions, dict) or set(conditions) - {'secondary_structure', 'sasa', 'function_annotations', 'potential_sequence_of_concern'}:
        raise ValueError('Configure supported ESM3 conditioning tracks explicitly')
    sources = _sources(call.inputs['source'][0])
    parameters = call.tool_parameters.get('esm3', {})
    if not isinstance(parameters, dict):
        raise ValueError('ESM3 parameters must be an object')
    total = len(sources) * samples
    completed, objects, files = 0, [], {}
    if call.previous is not None and call.previous.continuation is not None:
        completed = call.previous.continuation['completed']
        if type(completed) is not int or not 0 <= completed <= total:
            raise ValueError('Invalid sequence generation continuation')
        if completed:
            packages = call.previous.outputs.get('generated', ())
            if len(packages) != 1:
                raise ValueError('Continue requires the accepted partial generation package')
            with packages[0].open(packages[0].entry) as stream:
                previous = json.load(stream)
            objects = previous['objects']
            if len(objects) != completed or previous['batch']['completed'] != completed:
                raise ValueError('Partial output and continuation progress disagree')
            _copy_previous(packages[0], runtime, files)
    status, diagnostics = 'succeeded', ()
    for index in range(completed, total):
        if runtime.cancelled:
            status = 'cancelled'
            break
        source = sources[index // samples]
        tracks = {'sequence': source['prompt'], **deepcopy(conditions)}
        if 'coordinates' in source:
            tracks['coordinates'] = deepcopy(source['coordinates'])
        request = ESM3Request('sequence', tracks)
        try:
            result = call.tools['esm3'](request, deepcopy(parameters), runtime)
            if runtime.cancelled:
                status = 'cancelled'
                break
            objects.append(_generated(result, request, source, index % samples, runtime, files))
            completed += 1
            runtime.progress(f'Completed {completed} of {total} sequence generation requests')
        except Exception as exc:
            status = 'cancelled' if runtime.cancelled else 'failed'
            diagnostics = (f'Sequence generation request {index + 1} of {total} failed: {exc}',)
            break
    outputs = {}
    if objects:
        path = 'generation-' + uuid4().hex + '.json'
        (runtime.workdir / path).write_text(json.dumps({'objects': objects, 'batch': {'completed': completed, 'total': total, 'status': status}, 'tool': {'id': call.tool_choices['esm3'], 'parameters': parameters}}, allow_nan=False))
        files[path] = path
        outputs['generated'] = [Delivery(FORMAT, path, files)]
    return Outcome(status, outputs, diagnostics, {'completed': completed})


def sequence(call, runtime):
    if set(call.parameters) - {'chain_index'}:
        raise ValueError('Sequence conversion accepts only an explicit zero-based chain_index')
    package = call.inputs['generated'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    objects = []
    for obj in document['objects']:
        chains = obj['sequence'].split('|')
        selected = call.parameters.get('chain_index')
        if selected is None and len(chains) == 1:
            selected = 0
        if type(selected) is not int or not 0 <= selected < len(chains):
            raise ValueError('Select an explicit zero-based chain_index from the generated sequence')
        text = chains[selected]
        if not text or any(symbol not in 'ACDEFGHIKLMNPQRSTVWY' for symbol in text):
            raise ValueError('Selected chain cannot be represented by canonical workbench.sequence')
        offset = sum(len(chain) + 1 for chain in chains[:selected])
        rows = obj['positions'][offset:offset + len(text)]
        if len(rows) != len(text):
            raise ValueError('Generated positions must cover the selected chain')
        positions = []
        for i, row in enumerate(rows):
            position = {'sequence_index': i + 1}
            original = row.get('source', {}).get('position', {})
            keys = ('chain', 'author_number', 'insertion_code')
            if any(key in original for key in keys):
                if not all(key in original for key in keys) or not isinstance(original['chain'], str) or type(original['author_number']) is not int or not isinstance(original['insertion_code'], str):
                    raise ValueError('Source residue correspondence must be complete')
                position.update({key: original[key] for key in keys})
            positions.append(position)
        objects.append({'id': uuid4().hex, 'sequence': text, 'positions': positions,
                        'source': {'name': f"ESM3 object {obj['id']}; chain {selected}"}})
    (runtime.workdir / 'sequence.json').write_text(json.dumps({'objects': objects}, allow_nan=False))
    return Outcome(outputs={'sequence': [Delivery('workbench.sequence', 'sequence.json', {'sequence.json': 'sequence.json'})]})


def module():
    from .adapters import SLOT, tools
    return Module('workbench.esm3', 'ESM3 sequence generation', nodes=(
        Node('workbench.complete_sequence', 'Complete or generate a conditioned sequence', execute,
             inputs={'source': InputPort(('workbench.sequence', 'workbench.sequence_conditions'))},
             outputs={'generated': OutputPort(FORMAT)}, parameters={'samples': {'type': 'integer', 'default': 1}, 'conditions': {'type': 'object', 'default': {}}},
             tools={'esm3': ToolSlot(SLOT, 'ESM3 native generate')}),
        Node('workbench.esm3_sequence', 'Use a generated chain as sequence', sequence,
             inputs={'generated': InputPort((FORMAT,))}, outputs={'sequence': OutputPort('workbench.sequence')},
             parameters={'chain_index': {'description': 'Explicit zero-based chain index; required for multiple chains'}})),
        tools=tools(), settings={'token': 'Biohub credential', 'service_url': 'Biohub service URL', 'model_path': 'Existing esm3-sm-open-v1 snapshot directory', 'device': 'cpu, cuda or mps', 'python': 'Existing Python executable with pinned esm and torch'},
        ui=str(Path(__file__).with_name('ui.js').resolve()))
