"""Two dependent ESM3 calls with file-backed accepted phase continuation."""
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from modules.esm3.contract import ESM3Request
from modules.esm3.generation import read_sources, retain_result

FORMAT = 'workbench.joint_generation'


def execute(call, runtime):
    if set(call.parameters) - {'samples', 'conditions', 'structure_parameters'}:
        raise ValueError('Joint generation accepts samples, conditions and structure_parameters')
    samples = call.parameters.get('samples', 1)
    if type(samples) is not int or samples < 1:
        raise ValueError('samples requires a positive integer')
    conditions = call.parameters.get('conditions', {})
    if not isinstance(conditions, dict) or set(conditions) - {'secondary_structure', 'sasa', 'function_annotations', 'potential_sequence_of_concern'}:
        raise ValueError('Configure supported ESM3 conditioning tracks explicitly')
    parameters = call.tool_parameters.get('esm3', {})
    overrides = call.parameters.get('structure_parameters', {})
    if not isinstance(parameters, dict) or not isinstance(overrides, dict):
        raise ValueError('ESM3 controls and structure_parameters must be objects')
    sources = read_sources(call.inputs['source'][0])
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
                tracks = {'sequence': source['prompt'], **deepcopy(conditions)}
                if 'coordinates' in source:
                    tracks['coordinates'] = deepcopy(source['coordinates'])
                request = ESM3Request('sequence', tracks)
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
            tracks['sequence'] = sequence_native['tracks']['sequence']
            if tracks['sequence'] != pending['sequence']:
                raise ValueError('Accepted sequence phase disagrees with its native file')
            request = ESM3Request('structure', tracks)
            result = call.tools['esm3'](request, {**deepcopy(parameters), **deepcopy(overrides)}, runtime)
            candidate_files = {}
            generated, native = retain_result(result, request, source, index % samples, runtime, candidate_files)
            coordinates = native['tracks'].get('coordinates')
            if not isinstance(coordinates, list) or len(coordinates) != len(generated['sequence']) or any(not isinstance(row, list) or len(row) != 37 or any(not isinstance(point, list) or len(point) != 3 for point in row) for row in coordinates):
                raise ValueError('Structure phase requires actual native atom37 coordinates for every sequence position')
            points = [point for row in coordinates for point in row]
            if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value)) for point in points for value in point) or not any(all(value is not None for value in point) for point in points):
                raise ValueError('Structure phase requires finite actual atom coordinates; missing atoms remain null')
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
    """Explicit canonical single-chain coordinate representation, without filling atoms."""
    import gemmi
    from modules.esm3.adapters import ATOM37
    from modules.structure_io import atoms, encode, parse
    if set(call.parameters) != {'chain', 'start_number'}:
        raise ValueError('Choose chain and start_number for the generated coordinate representation')
    chain_name, start = call.parameters['chain'], call.parameters['start_number']
    if not isinstance(chain_name, str) or not chain_name.strip() or type(start) is not int:
        raise ValueError('Representation requires a nonempty chain and integer start_number')
    package = call.inputs['generated'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    source_objects = document.get('objects')
    if not isinstance(source_objects, list) or not source_objects:
        raise ValueError('Coordinate conversion requires a completed structure phase')
    if any(not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not obj['id'] for obj in source_objects) or len({obj['id'] for obj in source_objects}) != len(source_objects):
        raise ValueError('Coordinate conversion requires distinct actual generation objects')
    three = dict(zip('ACDEFGHIKLMNPQRSTVWY', ('ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE', 'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG', 'SER', 'THR', 'VAL', 'TRP', 'TYR'), strict=True))
    files, objects = {}, []
    for obj in source_objects:
        if runtime.cancelled:
            return Outcome(status='cancelled')
        sequence = obj['sequence']
        if not isinstance(sequence, str) or not sequence or any(letter not in three for letter in sequence):
            raise ValueError('Coordinate conversion supports only a canonical single chain; native extended or multichain results remain available')
        with package.open(obj['native']['file']) as stream:
            native = json.load(stream)
        coords = native.get('tracks', {}).get('coordinates')
        positions = obj['positions']
        if native.get('tracks', {}).get('sequence') != sequence or not isinstance(coords, list) or len(coords) != len(sequence) or not isinstance(positions, list) or len(positions) != len(sequence) or [row.get('sequence_index') for row in positions] != list(range(1, len(sequence) + 1)):
            raise ValueError('Native sequence, coordinates and position correspondence must cover the same complete sequence')
        structure = gemmi.Structure()
        model = gemmi.Model(1)
        chain = gemmi.Chain(chain_name)
        mapping = []
        for index, (letter, row) in enumerate(zip(sequence, coords, strict=True)):
            if not isinstance(row, list) or len(row) != len(ATOM37):
                raise ValueError('Coordinate conversion requires the documented atom37 axis')
            residue = gemmi.Residue()
            residue.name, residue.seqid, residue.het_flag = three[letter], gemmi.SeqId(start + index, ' '), 'A'
            for name, point in zip(ATOM37, row, strict=True):
                if not isinstance(point, list) or len(point) != 3:
                    raise ValueError('Every native atom37 position requires an XYZ triple')
                if point == [None, None, None]:
                    continue
                if any(type(value) not in (int, float) or not math.isfinite(value) for value in point):
                    raise ValueError('Coordinate conversion cannot represent incomplete or nonfinite atom coordinates')
                atom = gemmi.Atom()
                atom.name, atom.element = name, gemmi.Element(name[0])
                atom.pos, atom.occ, atom.b_iso = gemmi.Position(*point), 1.0, 0.0
                residue.add_atom(atom)
            if not len(residue):
                raise ValueError(f'Native sequence position {index + 1} has no finite atoms; a complete residue mapping is required')
            chain.add_residue(residue)
            mapping.append({'sequence_index': index + 1, 'original_position': deepcopy(positions[index]),
                            'position': {'model': 1, 'chain': chain_name, 'author_number': start + index, 'insertion_code': '', 'residue_name': three[letter]}})
        model.add_chain(chain)
        structure.add_model(model)
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
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'structures': [Delivery('workbench.structure_set', manifest, files)]})


def module():
    return Module('workbench.joint_generation', 'Sequence then structure generation', nodes=(
        Node('workbench.joint_generation', 'Generate sequence then structure', execute,
             inputs={'source': InputPort(('workbench.sequence', 'workbench.sequence_conditions'))},
             outputs={'generated': OutputPort(FORMAT)},
             parameters={'samples': {'type': 'integer', 'default': 1}, 'conditions': {'type': 'object', 'default': {}},
                         'structure_parameters': {'type': 'object', 'default': {}, 'description': 'Explicit ESM3 control overrides for the structure phase'}},
             tools={'esm3': ToolSlot('workbench.esm3.generate', 'ESM3 native generate')}),
        Node('workbench.joint_to_esm3', 'Select a joint generation phase', convert_stage,
             inputs={'generated': InputPort((FORMAT,))}, outputs={'generated': OutputPort('workbench.esm3_generation')},
             parameters={'stage': {'type': 'string', 'enum': ['sequence', 'structure'], 'description': 'Explicit phase to expose as native ESM3 results'}}),
        Node('workbench.joint_structure', 'Convert a canonical joint structure to coordinates', convert_structure,
             inputs={'generated': InputPort((FORMAT,))}, outputs={'structures': OutputPort('workbench.structure_set')},
             parameters={'chain': {'type': 'string', 'description': 'Explicit chain for this generated representation'},
                         'start_number': {'type': 'integer', 'description': 'Explicit first residue number for this generated representation'}})),
        ui=str(Path(__file__).with_name('ui.js').resolve()))
