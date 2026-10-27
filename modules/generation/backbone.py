"""Backbone-conditioned sequence design with complete, independent result packages."""
from copy import deepcopy
import json
import math
import secrets
import shutil
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, Outcome
from modules.proteinmpnn.contract import MPNNRequest, MPNNResult


def _copy_files(package, runtime, files, skip=None):
    for key in package.files:
        if key == skip:
            continue
        destination = runtime.workdir / uuid4().hex
        with package.open(key) as source, destination.open('wb') as target:
            shutil.copyfileobj(source, target)
        files[key] = destination.name


def _objects(result, source):
    if not isinstance(result, MPNNResult) or not result.samples or not result.positions:
        raise ValueError('ProteinMPNN tool must return actual samples and residue correspondence')
    by_chain = {}
    identities = set()
    for position in result.positions:
        chain = position['chain']
        identity = (chain, position['author_number'], position['insertion_code'])
        if identity in identities or not isinstance(chain, str) or not chain or type(position['author_number']) is not int or not isinstance(position['insertion_code'], str):
            raise ValueError('Tool returned ambiguous residue correspondence')
        identities.add(identity)
        rows = by_chain.setdefault(chain, [])
        if position['tool_position'] != len(rows) + 1:
            raise ValueError('Tool positions must be complete consecutive chain positions')
        rows.append(position)
    objects = []
    for sample in result.samples:
        chains = sample.get('chains')
        if not isinstance(chains, dict) or set(chains) != set(by_chain) or any(not isinstance(chains[chain], str) or len(chains[chain]) != len(rows) or any(aa not in 'ACDEFGHIKLMNPQRSTVWYX' for aa in chains[chain]) for chain, rows in by_chain.items()):
            raise ValueError('Tool must return complete sequences for all mapped chains')
        for name in ('score', 'global_score'):
            value = sample.get(name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f'Tool must return finite natural {name}')
        for name in ('residue_nll', 'design_mask', 'coordinate_mask'):
            values = sample.get(name)
            if not isinstance(values, dict) or set(values) != set(by_chain) or any(not isinstance(values[chain], list) or len(values[chain]) != len(rows) or any(type(value) not in (int, float) or not math.isfinite(value) for value in values[chain]) for chain, rows in by_chain.items()):
                raise ValueError(f'Tool must return complete numeric {name} values')
        obj = {'id': uuid4().hex,
               'chains': deepcopy(chains), 'positions': deepcopy(result.positions), 'backbone': deepcopy(source),
               'design': deepcopy(sample), 'tool': {'actual_seed': result.actual_seed, 'parameters': deepcopy(result.parameters)}}
        if 'label' in source:
            obj['label'] = source['label']
        objects.append(obj)
    return objects


def execute(call, runtime):
    if call.parameters:
        raise ValueError('Configure design conditions and sampling in the selected ProteinMPNN tool')
    package = call.inputs['structure'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    complete_target = package.format == 'workbench.protein'
    if complete_target:
        target = document.get('target')
        if not isinstance(target, dict) or target.get('format') != 'mmcif' or not isinstance(document.get('tracks'), dict):
            raise ValueError('Backbone design requires a complete target mmCIF')
        sources = [{'id': document.get('id'), 'structure': deepcopy(target), 'tracks': deepcopy(document['tracks'])}]
    else:
        sources = document.get('objects')
    if not isinstance(sources, list) or not sources or any(not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not isinstance(obj.get('structure'), dict) for obj in sources):
        raise ValueError('Design requires explicit structure objects')
    if len({obj['id'] for obj in sources}) != len(sources):
        raise ValueError('Design requires unique structure object identities')
    parameters = call.tool_parameters.get('mpnn', {})
    if not isinstance(parameters, dict):
        raise ValueError('ProteinMPNN parameters must be an object')
    objects, files, completed = [], {}, 0
    random_seeds = [secrets.randbelow(999) for _ in sources]
    if call.previous is not None and call.previous.continuation is not None:
        completed = call.previous.continuation['completed']
        random_seeds = call.previous.continuation['random_seeds']
        if type(completed) is not int or not 0 <= completed <= len(sources) or len(random_seeds) != len(sources):
            raise ValueError('Invalid ProteinMPNN continuation progress')
        if completed:
            previous = call.previous.outputs.get('design', ())
            if len(previous) != 1:
                raise ValueError('Continue requires the accepted ProteinMPNN partial package')
            with previous[0].open(previous[0].entry) as stream:
                document = json.load(stream)
            objects = document['objects']
            if document['batch']['completed'] != completed:
                raise ValueError('Partial output and continuation progress disagree')
            _copy_files(previous[0], runtime, files, skip=previous[0].entry)
    if not files:
        _copy_files(package, runtime, files)
    status, diagnostics = 'succeeded', ()
    for index in range(completed, len(sources)):
        if runtime.cancelled:
            status = 'cancelled'
            break
        source = sources[index]
        try:
            structure = source['structure']
            key = structure['file']
            if key not in package.files:
                raise ValueError(f'Structure file {key!r} is missing')
            path = runtime.workdir / uuid4().hex
            with package.open(key) as src, path.open('wb') as target:
                shutil.copyfileobj(src, target)
            request = MPNNRequest(path.name, structure['format'], random_seed=random_seeds[index], complete_target=complete_target, tracks=source.get('tracks'))
            result = call.tools['mpnn'](request, deepcopy(parameters), runtime)
            if runtime.cancelled:
                status = 'cancelled'
                break
            generated = _objects(result, source)
            objects.extend(generated)
            completed += 1
            runtime.progress(f'Completed {completed} of {len(sources)} backbone design requests')
        except Exception as exc:
            status = 'cancelled' if runtime.cancelled else 'failed'
            diagnostics = (f'Backbone design {index + 1} of {len(sources)} failed: {exc}',)
            break
    outputs = {}
    if objects:
        manifest = 'mpnn-' + uuid4().hex + '.json'
        (runtime.workdir / manifest).write_text(json.dumps({'objects': objects,
            'batch': {'completed': completed, 'total': len(sources), 'status': status},
            'tool': {'id': call.tool_choices['mpnn'], 'parameters': parameters}}, allow_nan=False))
        files[manifest] = manifest
        outputs['design'] = [Delivery('workbench.proteinmpnn_design', manifest, dict(files))]
    return Outcome(status, outputs, diagnostics, {'completed': completed, 'random_seeds': random_seeds})


def _chain_sequence_objects(document, chain):
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or not objects or any(not isinstance(obj, dict) or not isinstance(obj.get('chains'), dict) or not obj['chains'] or any(not isinstance(key, str) or not key for key in obj['chains']) for obj in objects):
        raise ValueError('Chain conversion requires design objects with actual named chains')
    if chain is None:
        choices = [list(obj['chains']) for obj in objects]
        if any(len(names) != 1 or names != choices[0] for names in choices):
            raise ValueError('Choose an explicit chain for every design sample; actual chains: ' + '; '.join(', '.join(names) for names in choices))
        chain = choices[0][0]
    converted = []
    for index, obj in enumerate(objects, 1):
        context = f'Design sample {index}, chain {chain!r}'
        if chain not in obj['chains']:
            raise ValueError(f'{context} is missing; actual chains: {", ".join(obj["chains"])}')
        sequence = obj['chains'][chain]
        if not isinstance(sequence, str) or not sequence:
            raise ValueError(f'{context} requires a complete chain sequence')
        from modules.sequence_io.formats import sequence_values
        sequence_values(sequence)
        positions = obj.get('positions')
        if not isinstance(positions, list) or any(not isinstance(row, dict) for row in positions):
            raise ValueError(f'{context} requires complete residue correspondence')
        rows = [row for row in positions if row.get('chain') == chain]
        if len(rows) != len(sequence) or any(type(row.get('tool_position')) is not int or type(row.get('author_number')) is not int or not isinstance(row.get('insertion_code'), str) for row in rows):
            raise ValueError(f'{context} requires complete residue correspondence')
        rows.sort(key=lambda row: row['tool_position'])
        if [row['tool_position'] for row in rows] != list(range(1, len(sequence) + 1)) or len({(row['author_number'], row['insertion_code']) for row in rows}) != len(rows):
            raise ValueError(f'{context} requires complete unambiguous residue correspondence')
        plain = {'id': uuid4().hex, 'sequence': sequence, 'positions': [
            {'sequence_index': row['tool_position'], **{key: row[key] for key in ('chain', 'author_number', 'insertion_code')}} for row in rows]}
        if 'label' in obj:
            if not isinstance(obj['label'], str):
                raise ValueError(f'{context} label must be text')
            plain['label'] = f'{obj["label"]} · chain {chain}'
        converted.append(plain)
    return converted


def _chain_sequence(call, runtime):
    if set(call.parameters) - {'chain'} or 'chain' in call.parameters and (not isinstance(call.parameters['chain'], str) or not call.parameters['chain']):
        raise ValueError('Chain conversion accepts only an optional actual chain name')
    package = call.inputs['design'][0]
    with package.open(package.entry) as stream:
        objects = _chain_sequence_objects(json.load(stream), call.parameters.get('chain'))
    (runtime.workdir / 'manifest.json').write_text(json.dumps({'objects': objects}, allow_nan=False))
    return Outcome(outputs={'sequence': [Delivery('workbench.sequence', 'manifest.json', {'manifest.json': 'manifest.json'})]})
