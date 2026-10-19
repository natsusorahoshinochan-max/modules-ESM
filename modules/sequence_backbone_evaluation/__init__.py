"""Independent sequence/backbone evaluation using ProteinMPNN's public tool call."""
from copy import deepcopy
import json
from pathlib import Path
import secrets
from shutil import copyfileobj
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Interaction, Module, Node, Outcome, OutputPort, ToolSlot
from modules.proteinmpnn.contract import MPNNRequest, MPNNResult
from modules.structure_io import parse
from .formats import actual_position, mapped_sequences, validate_samples

FORMAT = 'workbench.sequence_backbone_evaluation'
SEQUENCES = ('workbench.sequence', 'workbench.proteinmpnn_design', FORMAT)
REFERENCES = ('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence')


def read_objects(package):
    with package.open(package.entry) as stream:
        document = json.load(stream)
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or not objects or any(not isinstance(o, dict) or not isinstance(o.get('id'), str) or not o['id'] for o in objects) or len({o['id'] for o in objects}) != len(objects):
        raise ValueError('Input requires nonempty, uniquely identified objects')
    return document


def reference_positions(package, obj):
    description = obj.get('structure')
    if not isinstance(description, dict) or description.get('file') not in package.files or description.get('format') not in ('pdb', 'mmcif'):
        raise ValueError('Reference requires its declared PDB or mmCIF file')
    with package.open(description['file']) as stream:
        structure = parse(stream.read(), description['format'])
    if len(structure) != 1:
        raise ValueError('Select one reference conformation')
    positions, chains = [], set()
    for chain in structure[0]:
        if not chain.name or chain.name in chains:
            raise ValueError('Reference requires unique nonempty chains')
        chains.add(chain.name)
        for i, residue in enumerate(chain, 1):
            positions.append({'chain': chain.name, 'author_number': residue.seqid.num, 'insertion_code': residue.seqid.icode.strip(), 'tool_position': i})
    if not positions or len({(p['chain'], p['author_number'], p['insertion_code']) for p in positions}) != len(positions):
        raise ValueError('Reference requires complete unambiguous real residue correspondence')
    return positions


def copy_package(package, runtime, files, prefix=''):
    keys = {}
    for key in package.files:
        output_key = prefix + key
        if output_key in files:
            raise ValueError('Input package file keys collide')
        destination = runtime.workdir / uuid4().hex
        with package.open(key) as reader, destination.open('wb') as writer:
            copyfileobj(reader, writer)
        keys[key] = output_key
        files[output_key] = destination.name
    return keys


def execute(call, runtime):
    if set(call.parameters) - {'reference', 'bindings', 'region'}:
        raise ValueError('Unsupported sequence/backbone evaluation parameters')
    source, reference = call.inputs['sequences'][0], call.inputs['reference'][0]
    document, ref_document = read_objects(source), read_objects(reference)
    matches = [o for o in ref_document['objects'] if o['id'] == call.parameters.get('reference')]
    if len(matches) != 1:
        raise ValueError('Select exactly one explicit supplied reference object')
    obj = matches[0]
    positions = reference_positions(reference, obj)
    sequences, identities = mapped_sequences(document['objects'], positions, call.parameters.get('bindings'))
    region = call.parameters.get('region')
    actual = [actual_position(p) for p in positions]
    if region is not None:
        if not isinstance(region, list) or not region or any(not isinstance(p, dict) or set(p) != {'chain', 'author_number', 'insertion_code'} or actual_position(p) not in actual for p in region) or len({tuple(actual_position(p).values()) for p in region}) != len(region):
            raise ValueError('Region must select unique actual reference residues')
    files = {}
    copy_package(source, runtime, files)
    reference_keys = copy_package(reference, runtime, files, 'reference-' + uuid4().hex + '/')
    path = files[reference_keys[obj['structure']['file']]]
    request = MPNNRequest(path, obj['structure']['format'], sequences, random_seed=secrets.randbelow(999))
    parameters = deepcopy(call.tool_parameters.get('mpnn', {}))
    result = call.tools['mpnn'](request, parameters, runtime)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if not isinstance(result, MPNNResult) or result.positions != positions or not result.samples:
        raise ValueError('Scoring tool must return complete original reference position correspondence')
    samples = deepcopy(result.samples)
    selected = actual if region is None else region
    region_mask = {chain: [float(actual_position(p) in selected) for p in positions if p['chain'] == chain] for chain in sequences}
    validate_samples(samples, sequences)
    if type(result.actual_seed) is not int or not 0 <= result.actual_seed <= 2**32 - 1 or not isinstance(result.parameters, dict):
        raise ValueError('Scoring tool must return actual seed and effective parameters')
    for sample in samples:
        sample['region_mask'] = deepcopy(region_mask)
        denominator = sum(sum(row) for row in region_mask.values())
        sample['region_nll'] = sum(v * m for c in sequences for v, m in zip(sample['residue_nll'][c], region_mask[c], strict=True)) / denominator
    output = deepcopy(document)
    evaluation = {'object_ids': identities, 'reference': {'id': obj['id'], 'label': obj.get('label', 'Reference structure'), 'original_object': deepcopy(obj), 'structure': {**deepcopy(obj['structure']), 'file': reference_keys[obj['structure']['file']]}},
        'reference_manifest': {'file': reference_keys[reference.entry], 'files': reference_keys},
        'bindings': deepcopy(call.parameters['bindings']), 'positions': positions, 'region': region,
        'origin': 'independent_sequence_backbone', 'method': 'ProteinMPNN score_only', 'tool': call.tool_choices['mpnn'],
        'parameters': deepcopy(result.parameters), 'requested_parameters': parameters, 'actual_seed': result.actual_seed,
        'unit': 'negative log likelihood (natural logarithm)', 'meaning': {'score': 'Mean NLL over coordinate × selected-chain × nonfixed-position mask', 'global_score': 'Mean NLL over coordinate mask of all supplied chains', 'region_nll': 'Mean NLL over explicitly selected reference residues; full structure remains tool context'}, 'samples': samples}
    output['evaluations'] = [*output.get('evaluations', []), evaluation]
    key = 'evaluation-' + uuid4().hex + '.json'
    (runtime.workdir / key).write_text(json.dumps(output, allow_nan=False))
    files[key] = key
    return Outcome(outputs={'evaluation': [Delivery(FORMAT, key, files)]})


def module():
    from .interaction import inspect
    return Module('workbench.sequence_backbone_evaluation', 'Independent sequence/backbone evaluation', nodes=(Node(
        'workbench.evaluate_sequence_backbone', 'Evaluate sequence against backbone', execute,
        inputs={'sequences': InputPort(SEQUENCES), 'reference': InputPort(REFERENCES)}, outputs={'evaluation': OutputPort(FORMAT)},
        parameters={'reference': {'description': 'Explicit reference object'}, 'bindings': {'description': 'Complete sequence-to-reference chain residue mapping'}, 'region': {'description': 'Optional actual reference residue selection'}},
        tools={'mpnn': ToolSlot('workbench.proteinmpnn.call', 'ProteinMPNN sequence scoring')}),), ui=str(Path(__file__).with_name('ui.js').resolve()),
        interactions=(Interaction('workbench.sequence_backbone.inspect', inspect,
            inputs={'sequences': InputPort(SEQUENCES), 'reference': InputPort(REFERENCES)}),))
