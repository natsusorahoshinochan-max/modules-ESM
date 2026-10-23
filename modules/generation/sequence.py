"""Sequence completion and conditioned generation; task ownership stays here."""
from copy import deepcopy
import json
import shutil
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, Outcome
from .sources import read_sources, retain_result, request_for

FORMAT = 'workbench.esm3_generation'


def _copy_previous(package, runtime, files):
    for key in package.files:
        if key != package.entry:
            path = uuid4().hex
            with package.open(key) as source, (runtime.workdir / path).open('wb') as target:
                shutil.copyfileobj(source, target)
            files[key] = path


def execute(call, runtime):
    if set(call.parameters) - {'samples', 'conditions'}:
        raise ValueError('Sequence generation accepts samples and explicit conditions')
    samples = call.parameters.get('samples', 1)
    if type(samples) is not int or samples < 1:
        raise ValueError('samples requires a positive integer')
    conditions = call.parameters.get('conditions', {})
    if not isinstance(conditions, dict) or set(conditions) - {'secondary_structure', 'sasa', 'function_annotations', 'potential_sequence_of_concern'}:
        raise ValueError('Configure supported ESM3 conditioning tracks explicitly')
    sources = read_sources(call.inputs['source'][0])
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
        request = request_for('sequence', source, tracks, call.inputs['source'][0], runtime)
        try:
            result = call.tools['esm3'](request, deepcopy(parameters), runtime)
            if runtime.cancelled:
                status = 'cancelled'
                break
            generated, _ = retain_result(result, request, source, index % samples, runtime, files)
            objects.append(generated)
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
            source = row.get('source', {})
            original = source.get('position', {})
            label = source.get('label_position', original.get('label_position'))
            if label is not None:
                position['label_position'] = deepcopy(label)
            keys = ('chain', 'author_number', 'insertion_code')
            if any(key in original for key in keys):
                if not all(key in original for key in keys) or not isinstance(original['chain'], str) or not isinstance(original['insertion_code'], str):
                    raise ValueError('Source residue correspondence must be complete')
                if original['author_number'] is None and label is not None:
                    pass
                elif type(original['author_number']) is int:
                    position.update({key: original[key] for key in keys})
                else:
                    raise ValueError('Source author numbering requires an actual integer or explicit label correspondence')
            positions.append(position)
        objects.append({'id': uuid4().hex, 'sequence': text, 'positions': positions,
                        'source': {'name': f"ESM3 object {obj['id']}; chain {selected}"}})
    (runtime.workdir / 'sequence.json').write_text(json.dumps({'objects': objects}, allow_nan=False))
    from types import SimpleNamespace
    from modules.sequence_io.formats import read_sequences
    read_sequences(SimpleNamespace(entry='sequence.json', open=lambda key:(runtime.workdir/key).open('rb')))
    return Outcome(outputs={'sequence': [Delivery('workbench.sequence', 'sequence.json', {'sequence.json': 'sequence.json'})]})
