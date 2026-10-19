"""Backbone-conditioned sequence design with complete, independent result packages."""
from copy import deepcopy
import json
import math
from pathlib import Path
import secrets
import shutil
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from .contract import MPNNRequest, MPNNResult


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
        obj = {'id': uuid4().hex, 'sequence': ''.join(chains[chain] for chain in by_chain),
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
        sources = json.load(stream)['objects']
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
            request = MPNNRequest(path.name, structure['format'], random_seed=random_seeds[index])
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
        sequence_objects = []
        for obj in objects:
            plain = {'id': obj['id'], 'sequence': obj['sequence'], 'positions': [
                {'sequence_index': index, **{key: position[key] for key in ('chain', 'author_number', 'insertion_code')}}
                for index, position in enumerate(obj['positions'], 1)]}
            if 'label' in obj:
                plain['label'] = obj['label']
            sequence_objects.append(plain)
        sequence_manifest = 'sequences-' + uuid4().hex + '.json'
        (runtime.workdir / sequence_manifest).write_text(json.dumps({'objects': sequence_objects}, allow_nan=False))
        outputs['sequence'] = [Delivery('workbench.sequence', 'manifest.json', {'manifest.json': sequence_manifest})]
    return Outcome(status, outputs, diagnostics, {'completed': completed, 'random_seeds': random_seeds})


def module():
    from .adapters import SLOT, tools
    return Module('workbench.proteinmpnn', 'ProteinMPNN backbone design', nodes=(Node(
        'workbench.design_backbone', 'Design sequences from backbone', execute,
        inputs={'structure': InputPort(('workbench.structure_set', 'workbench.prediction'))},
        outputs={'sequence': OutputPort('workbench.sequence'), 'design': OutputPort('workbench.proteinmpnn_design')}, tools={'mpnn': ToolSlot(SLOT, 'Backbone sequence design and scoring')}),),
        tools=tools(), settings={'source': 'Existing ProteinMPNN source directory', 'weights': 'Existing weights root with vanilla_model_weights and soluble_model_weights',
                                'python': 'Existing Python executable with torch, numpy and gemmi', 'device': 'cpu, cuda or mps'},
        ui=str(Path(__file__).with_name('ui.js').resolve()))
