"""Independent confidence evaluation of explicitly supplied structure geometry."""
from copy import deepcopy
import json
import math
from pathlib import Path
from shutil import copyfileobj
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from modules.structure_io import parse
from .contract import SLOT, ConfidenceRequest, ConfidenceResult


def positions_for(content, encoding):
    structure = parse(content, encoding)
    if len(structure) != 1:
        raise ValueError('Select a single structure conformation for confidence evaluation')
    positions = []
    for chain in structure[0]:
        for residue in chain:
            positions.append({'chain': chain.name, 'author_number': residue.seqid.num, 'insertion_code': residue.seqid.icode.strip()})
    if not positions or len({tuple(p.values()) for p in positions}) != len(positions):
        raise ValueError('Confidence requires nonempty unique actual residue positions')
    return positions


def execute(call, runtime):
    if set(call.parameters) - {'object', 'region'}:
        raise ValueError('Unsupported confidence node parameters')
    source = call.inputs['structures'][0]
    with source.open(source.entry) as reader:
        document = json.load(reader)
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or any(not isinstance(obj, dict) for obj in objects):
        raise ValueError('Confidence requires explicit structure objects')
    identities = [obj.get('id') for obj in objects]
    if any(not isinstance(value, str) or not value for value in identities) or len(set(identities)) != len(identities):
        raise ValueError('Structure objects require unique explicit identities')
    selected = [obj for obj in objects if obj.get('id') == call.parameters.get('object')]
    if len(selected) != 1:
        raise ValueError('Select exactly one supplied structure object')
    obj = selected[0]
    description = obj.get('structure', {})
    if not isinstance(description, dict) or description.get('file') not in source.files or description.get('format') not in ('pdb', 'mmcif'):
        raise ValueError('Selected structure requires its declared PDB or mmCIF file')
    with source.open(description['file']) as reader:
        content = reader.read()
    positions = positions_for(content, description['format'])
    region = call.parameters.get('region')
    if region is not None and (not isinstance(region, list) or not region or any(position not in positions for position in region) or len({json.dumps(position, sort_keys=True) for position in region}) != len(region)):
        raise ValueError('Region must select unique actual chain, author_number and insertion_code positions')
    folder = runtime.workdir / uuid4().hex
    folder.mkdir()
    files = {}
    for index, key in enumerate(source.files):
        destination = folder / f'input-{index}'
        with source.open(key) as reader, destination.open('wb') as writer:
            copyfileobj(reader, writer)
        files[key] = str(destination.relative_to(runtime.workdir))
    result = call.tools['evaluator'](ConfidenceRequest(str(runtime.workdir / files[description['file']]), description['format'], tuple(positions)), deepcopy(call.tool_parameters.get('evaluator', {})), runtime)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if not isinstance(result, ConfidenceResult) or list(result.positions) != positions or len(result.plddt) != len(positions):
        raise ValueError('Confidence tool must return every supplied position in request order')
    if not isinstance(result.method, str) or not result.method or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in result.plddt):
        raise ValueError('Confidence tool must return finite pLDDT fractions (0–1) and its actual method')
    chosen = positions if region is None else region
    values = [result.plddt[positions.index(position)] for position in chosen]
    score_key = 'confidence-' + uuid4().hex + '.json'
    (folder / score_key).write_text(json.dumps({'positions': chosen, 'plddt': values}, allow_nan=False))
    files[score_key] = str((folder / score_key).relative_to(runtime.workdir))
    output = deepcopy(document)
    output['evaluations'] = [*output.get('evaluations', []), {'object_id': obj['id'], 'reference': None, 'region': region,
        'method': result.method, 'tool': call.tool_choices['evaluator'], 'parameters': deepcopy(call.tool_parameters.get('evaluator', {})), 'origin': 'independent_existing_geometry', 'context': deepcopy(result.context),
        'values': {'mean_plddt': {'value': sum(values) / len(values), 'unit': 'fraction (0–1)', 'meaning': 'Mean predicted local confidence over the selected actual residues'}},
        'per_position': {'file': score_key, 'unit': 'fraction (0–1)', 'meaning': 'Model-predicted local confidence at the given structure coordinates'}}]
    output['confidence_tool'] = {'id': call.tool_choices['evaluator'], 'parameters': deepcopy(call.tool_parameters.get('evaluator', {}))}
    (folder / 'manifest.json').write_text(json.dumps(output, allow_nan=False))
    files['manifest.json'] = str((folder / 'manifest.json').relative_to(runtime.workdir))
    return Outcome(outputs={'evaluation': [Delivery('workbench.structure_confidence', 'manifest.json', files)]})


def prepare(call, runtime):
    if set(call.parameters) != {'object'}:
        raise ValueError('Choose one existing structure to prepare region selection')
    source = call.inputs['structures'][0]
    with source.open(source.entry) as reader:
        document = json.load(reader)
    matches = [obj for obj in document.get('objects', []) if obj.get('id') == call.parameters['object']]
    if len(matches) != 1:
        raise ValueError('Select exactly one supplied structure object')
    obj = matches[0]
    with source.open(obj['structure']['file']) as reader:
        positions = positions_for(reader.read(), obj['structure']['format'])
    folder = runtime.workdir / uuid4().hex
    folder.mkdir()
    files = {}
    for index, key in enumerate(source.files):
        destination = folder / f'input-{index}'
        with source.open(key) as reader, destination.open('wb') as writer:
            copyfileobj(reader, writer)
        files[key] = str(destination.relative_to(runtime.workdir))
    key = 'positions-' + uuid4().hex + '.json'
    (folder / key).write_text(json.dumps(positions))
    files[key] = str((folder / key).relative_to(runtime.workdir))
    document['confidence_positions'] = {obj['id']: key}
    (folder / 'manifest.json').write_text(json.dumps(document, allow_nan=False))
    files['manifest.json'] = str((folder / 'manifest.json').relative_to(runtime.workdir))
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'prepared': [Delivery('workbench.confidence_input', 'manifest.json', files)]})


def module():
    return Module(id='workbench.structure_confidence', name='Existing structure confidence', nodes=(Node(id='workbench.prepare_structure_confidence', name='Prepare confidence region selection', execute=prepare, inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.confidence_input'))}, outputs={'prepared': OutputPort('workbench.confidence_input')}, parameters={'object': {'description': 'Existing structure to display actual residues'}}), Node(
        id='workbench.evaluate_structure_confidence', name='Evaluate existing structure confidence', execute=execute,
        inputs={'structures': InputPort(('workbench.structure_set', 'workbench.prediction', 'workbench.structure_confidence', 'workbench.confidence_input'))},
        outputs={'evaluation': OutputPort('workbench.structure_confidence')},
        parameters={'object': {'description': 'Explicit supplied structure object'}, 'region': {'description': 'Optional actual chain/residue/insertion-code positions'}},
        tools={'evaluator': ToolSlot(SLOT, 'Existing geometry evaluator')}),), ui=str(Path(__file__).with_name('ui.js').resolve()))
