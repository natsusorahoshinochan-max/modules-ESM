"""Two dependent ESM3 calls with file-backed accepted phase continuation."""
from copy import deepcopy
import json
import shutil
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, Outcome
from .sources import read_inputs, retain_result, request_for

FORMAT = 'workbench.joint_generation'


def execute(call, runtime):
    if set(call.parameters) - {'samples', 'structure_parameters'}:
        raise ValueError('Joint generation accepts samples and structure_parameters; protein tracks come from source')
    samples = call.parameters.get('samples', 1)
    if type(samples) is not int or samples < 1:
        raise ValueError('samples requires a positive integer')
    parameters = call.tool_parameters.get('esm3', {})
    overrides = call.parameters.get('structure_parameters', {})
    if not isinstance(parameters, dict) or not isinstance(overrides, dict):
        raise ValueError('ESM3 controls and structure_parameters must be objects')
    sources = read_inputs(call)
    total = len(sources) * samples
    objects, pending, files = [], None, {}
    if call.previous is not None and call.previous.continuation is not None:
        progress = call.previous.continuation
        completed = progress['completed']
        if type(completed) is not int or not 0 <= completed <= total or type(progress.get('sequence_ready')) is not bool:
            raise ValueError('Invalid joint generation continuation')
        packages = call.previous.outputs.get('generated', ())
        if completed or progress['sequence_ready']:
            if len(packages) != 1:
                raise ValueError('Continue requires accepted joint generation files')
            package = packages[0]
            with package.open(package.entry) as stream:
                previous = json.load(stream)
            objects, pending = previous['objects'], previous['pending_sequence']
            if len(objects) != completed or (pending is not None) != progress['sequence_ready'] or previous['batch']['completed'] != completed:
                raise ValueError('Accepted joint files and continuation progress disagree')
            for key in package.files:
                if key != package.entry:
                    path = uuid4().hex
                    with package.open(key) as source, (runtime.workdir / path).open('wb') as target:
                        shutil.copyfileobj(source, target)
                    files[key] = path
    status, diagnostics = 'succeeded', ()
    for index in range(len(objects), total):
        if runtime.cancelled:
            status = 'cancelled'
            break
        source = sources[index // samples]
        phase = 'sequence'
        try:
            if pending is None:
                tracks = deepcopy(source['tracks'])
                request = request_for('sequence', tracks)
                result = call.tools['esm3'](request, deepcopy(parameters), runtime)
                # Keep actual successful sequence files even if cancellation arrived after the call.
                pending, _ = retain_result(result, request, source, index % samples, runtime, files)
                runtime.progress(f'Sample {index + 1} of {total}: sequence completed; structure pending')
            if runtime.cancelled:
                status = 'cancelled'
                break
            phase = 'structure'
            tracks = deepcopy(pending['generation']['tracks'])
            # The accepted native file is the sequence authority on continuation.
            with (runtime.workdir / files[pending['native']['file']]).open() as stream:
                sequence_native = json.load(stream)
            tracks['sequence'] = list(sequence_native['tracks']['sequence'])
            if ''.join(tracks['sequence']) != pending['sequence']:
                raise ValueError('Accepted sequence phase disagrees with its native file')
            request = request_for('structure', tracks)
            result = call.tools['esm3'](request, {**deepcopy(parameters), **deepcopy(overrides)}, runtime)
            candidate_files = {}
            generated, native = retain_result(result, request, source, index % samples, runtime, candidate_files)
            if result.coordinate_role != 'generated_structure':
                raise ValueError('Structure phase requires actual generated structure output from the tool')
            files.update(candidate_files)
            generated['sequence_stage'] = pending
            generated['generation']['sequence_object'] = pending['id']
            objects.append(generated)
            pending = None
            runtime.progress(f'Completed {len(objects)} of {total} joint generation samples')
            if runtime.cancelled:
                status = 'cancelled'
                break
        except Exception as exc:
            status = 'cancelled' if runtime.cancelled else 'failed'
            diagnostics = (f'Joint sample {index + 1} of {total}, {phase} phase failed: {exc}',)
            break
    outputs = {}
    if objects or pending is not None:
        path = 'joint-' + uuid4().hex + '.json'
        document = {'objects': objects, 'pending_sequence': pending,
                    'batch': {'completed': len(objects), 'total': total, 'status': status, 'sequence_completed': len(objects) + int(pending is not None)},
                    'tool': {'id': call.tool_choices['esm3'], 'parameters': parameters, 'structure_parameters': overrides}}
        (runtime.workdir / path).write_text(json.dumps(document, allow_nan=False))
        files[path] = path
        outputs['generated'] = [Delivery(FORMAT, path, files)]
    return Outcome(status, outputs, diagnostics, {'completed': len(objects), 'sequence_ready': pending is not None})


def convert_stage(call, runtime):
    """Explicitly expose one real phase using the existing public native format."""
    if set(call.parameters) != {'stage'} or call.parameters['stage'] not in ('sequence', 'structure'):
        raise ValueError('Select stage sequence or structure explicitly')
    source = call.inputs['generated'][0]
    with source.open(source.entry) as stream:
        document = json.load(stream)
    objects = document['objects']
    if call.parameters['stage'] == 'sequence':
        objects = [obj['sequence_stage'] for obj in objects]
        if document['pending_sequence'] is not None:
            objects = [*objects, document['pending_sequence']]
    if not objects:
        raise ValueError('The selected stage has no accepted successful results')
    files = {}
    # Preserve all real native files and the source manifest under a distinct key.
    for key in source.files:
        destination = uuid4().hex
        with source.open(key) as reader, (runtime.workdir / destination).open('wb') as writer:
            shutil.copyfileobj(reader, writer)
        files[key] = destination
    manifest = 'stage-' + uuid4().hex + '.json'
    converted = {'objects': objects, 'batch': {'completed': len(objects), 'total': document['batch']['total'], 'status': document['batch']['status']},
                 'tool': document['tool'], 'source_manifest': {'file': source.entry, 'format': FORMAT}, 'stage': call.parameters['stage']}
    (runtime.workdir / manifest).write_text(json.dumps(converted, allow_nan=False))
    files[manifest] = manifest
    return Outcome(outputs={'generated': [Delivery('workbench.esm3_generation', manifest, files)]})


def convert_structure(call, runtime):
    """Use an adapter-delivered file and explicitly assign output numbering."""
    import gemmi
    from modules.structure_io import atoms, encode, parse
    if set(call.parameters) != {'chain', 'start_number'}:
        raise ValueError('Choose chain and start_number for the generated coordinate representation')
    chain_name, start = call.parameters['chain'], call.parameters['start_number']
    if not isinstance(chain_name, str) or not chain_name.strip() or type(start) is not int:
        raise ValueError('Representation requires a nonempty chain and integer start_number')
    package = call.inputs['generated'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    sources = document.get('objects')
    if not isinstance(sources, list) or not sources or len({obj.get('id') for obj in sources}) != len(sources):
        raise ValueError('Coordinate conversion requires distinct completed generation objects')
    files, objects = {}, []
    for obj in sources:
        if runtime.cancelled:
            return Outcome(status='cancelled')
        sequence, positions = obj['sequence'], obj['positions']
        if not isinstance(sequence, str) or not sequence or any(letter not in 'ACDEFGHIKLMNPQRSTVWY' for letter in sequence):
            raise ValueError('Coordinate conversion supports only a canonical single chain')
        reference = obj.get('structure')
        if obj.get('coordinate_role') != 'generated_structure' or not isinstance(reference, dict):
            raise ValueError('Generation tool did not provide a complete structure file; a target position may have no finite atoms')
        with package.open(reference['file']) as stream:
            structure = parse(stream.read(), reference['format'])
        if len(structure) != 1 or len(structure[0]) != 1 or len(structure[0][0]) != len(sequence) or len(positions) != len(sequence):
            raise ValueError('Generated structure and position correspondence must cover the complete sequence')
        chain = structure[0][0]
        chain.name = chain_name
        mapping = []
        for index, (letter, residue) in enumerate(zip(sequence, chain, strict=True)):
            if gemmi.find_tabulated_residue(residue.name).one_letter_code != letter or not len(residue):
                raise ValueError('Generated structure must match every sequence residue')
            residue.seqid = gemmi.SeqId(start + index, ' ')
            mapping.append({'sequence_index': index + 1, 'original_position': deepcopy(positions[index]),
                'position': {'model': 1, 'chain': chain_name, 'author_number': start + index, 'insertion_code': '', 'residue_name': residue.name}})
        key, view = uuid4().hex + '.cif', uuid4().hex + '.atoms.json'
        content = encode(structure, 'mmcif')
        (runtime.workdir / key).write_bytes(content)
        (runtime.workdir / view).write_text(json.dumps(atoms(parse(content, 'mmcif')), allow_nan=False))
        files.update({key: key, view: view})
        objects.append({'id': obj['id'], 'sequence': sequence, 'structure': {'file': key, 'format': 'mmcif'}, 'atoms': view,
                        'source_object': deepcopy(obj), 'native_positions': mapping,
                        'representation': {'chain': chain_name, 'start_number': start, 'occupancy': 1.0, 'b_iso': 0.0}})
    for key in package.files:
        path = uuid4().hex
        with package.open(key) as reader, (runtime.workdir / path).open('wb') as writer:
            shutil.copyfileobj(reader, writer)
        files[key] = path
    manifest = 'structures-' + uuid4().hex + '.json'
    (runtime.workdir / manifest).write_text(json.dumps({'objects': objects, 'tool': document['tool'],
        'source_manifest': {'file': package.entry, 'format': FORMAT}}, allow_nan=False))
    files[manifest] = manifest
    return Outcome(outputs={'structures': [Delivery('workbench.structure_set', manifest, files)]})
