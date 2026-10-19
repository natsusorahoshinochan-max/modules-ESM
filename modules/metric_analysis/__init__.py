"""Analyze explicitly selected existing metric values; never invoke scientific tools."""
import json
import math
from shutil import copyfileobj

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort
from .formats import finite, positions

FORMATS = ('workbench.structure_confidence', 'workbench.comparison', 'workbench.solubility', 'workbench.prediction')


def read_json(package, key):
    if key not in package.files:
        raise ValueError(f'Required metric file is not declared: {key}')
    with package.open(key) as reader:
        return json.load(reader)


def prediction_positions(package, obj):
    # Voluntary reuse of the structure module's public parsing API only.
    import gemmi
    from modules.structure_io import parse
    descriptor = obj.get('structure', {})
    if descriptor.get('file') not in package.files:
        raise ValueError('Natural confidence requires its complete original structure')
    with package.open(descriptor['file']) as reader:
        structure = parse(reader.read(), descriptor.get('format'))
    if len(structure) != 1:
        raise ValueError('Natural confidence requires one explicit structure conformation')
    axis, sequence, chains = [], '', set()
    for chain in structure[0]:
        for residue in chain:
            info = gemmi.find_tabulated_residue(residue.name)
            if not info.is_amino_acid():
                continue
            letter = info.one_letter_code
            if letter not in 'ACDEFGHIKLMNPQRSTVWY':
                raise ValueError('Natural confidence sequence correspondence requires canonical residues')
            sequence += letter
            chains.add(chain.name)
            axis.append({'chain': chain.name, 'author_number': residue.seqid.num, 'insertion_code': residue.seqid.icode.strip()})
    if len(chains) != 1 or sequence != obj.get('sequence'):
        raise ValueError('Natural confidence requires complete prediction sequence/structure correspondence')
    positions(axis)
    return axis


def choices(package):
    document = read_json(package, package.entry)
    if package.format == 'workbench.comparison':
        subject, reference = document.get('subject'), document.get('reference')
        for obj in (subject, reference):
            if not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not obj['id']:
                raise ValueError('Comparison requires its actual subject and reference')
            if obj.get('structure', {}).get('file') not in package.files:
                raise ValueError('Comparison requires both complete original structure files')
        result = []
        for metric, descriptor in document.get('metrics', {}).items():
            result.append({'selector': {'object': subject['id'], 'origin': 'comparison', 'metric': metric},
                'object': subject, 'reference': reference, 'source_region': document.get('region'),
                'source_method': document.get('method'), 'metric': metric, 'unit': descriptor.get('unit'),
                'meaning': descriptor.get('normalization') or descriptor.get('scope'),
                'input_values': [descriptor.get('value')], 'positions': None})
        if not result:
            raise ValueError('Comparison contains no existing numeric metrics')
        return result
    objects = document.get('objects', [])
    ids = [obj.get('id') for obj in objects]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Metric objects require unique explicit identities')
    result = []
    if package.format == 'workbench.prediction':
        for obj in objects:
            common = {'object': obj, 'reference': None, 'source_region': None,
                'source_method': document.get('tool'), 'unit': 'fraction (0–1)'}
            confidence = obj.get('confidence', {})
            if 'plddt' in confidence:
                descriptor = confidence['plddt']
                if descriptor.get('scale') != '0-1':
                    raise ValueError('Natural confidence requires its explicit 0–1 scale')
                scores = read_json(package, descriptor.get('file')).get('plddt')
                axis = prediction_positions(package, obj)
                if not isinstance(scores, list) or len(scores) != len(axis) or any(not finite(v) or not 0 <= v <= 1 for v in scores):
                    raise ValueError('Natural confidence correspondence must cover every finite 0–1 value')
                result.append(common | {'selector': {'object': obj['id'], 'origin': 'generation', 'metric': 'plddt'},
                    'metric': 'plddt', 'meaning': 'Source prediction local confidence', 'input_values': scores, 'positions': axis})
            if 'ptm' in confidence:
                value = confidence['ptm']
                if not finite(value) or not 0 <= value <= 1:
                    raise ValueError('Natural pTM requires a finite 0–1 value')
                result.append(common | {'selector': {'object': obj['id'], 'origin': 'generation', 'metric': 'ptm'},
                    'metric': 'ptm', 'meaning': 'Source whole-prediction pTM', 'input_values': [value], 'positions': None})
    for index, evaluation in enumerate(document.get('evaluations', [])):
        matches = [obj for obj in objects if obj['id'] == evaluation.get('object_id')]
        if len(matches) != 1:
            raise ValueError('Metric evaluation requires one explicitly supplied object')
        obj = matches[0]
        for metric, value in evaluation.get('values', {}).items():
            result.append({'selector': {'object': obj['id'], 'origin': 'evaluation', 'evaluation': index, 'metric': metric},
                'object': obj, 'reference': evaluation.get('reference'), 'source_region': evaluation.get('region'),
                'source_method': evaluation.get('method'), 'metric': metric, 'unit': value.get('unit'),
                'meaning': value.get('meaning'), 'input_values': [value.get('value')], 'positions': None})
        if 'per_position' in evaluation:
            descriptor = evaluation['per_position']
            scores = read_json(package, descriptor.get('file'))
            axis, values = scores.get('positions'), scores.get('plddt')
            keys = positions(axis)
            if not isinstance(values, list) or len(keys) != len(values) or any(not finite(v) or not 0 <= v <= 1 for v in values):
                raise ValueError('Confidence position correspondence must cover every finite 0–1 value')
            if evaluation.get('region') is not None and evaluation['region'] != axis:
                raise ValueError('Confidence region differs from its position correspondence')
            result.append({'selector': {'object': obj['id'], 'origin': 'evaluation', 'evaluation': index, 'metric': 'plddt'},
                'object': obj, 'reference': evaluation.get('reference'), 'source_region': evaluation.get('region'),
                'source_method': evaluation.get('method'), 'metric': 'plddt', 'unit': descriptor.get('unit'),
                'meaning': descriptor.get('meaning'), 'input_values': values, 'positions': axis})
    if not result:
        raise ValueError('Input contains no supported existing metrics')
    return result


def analyze(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    packages = call.inputs.get('metrics', ())
    selections = call.parameters.get('selections')
    if not isinstance(selections, list) or not selections:
        raise ValueError('Choose existing object, reference, method and metric explicitly')
    analyses = []
    for selection in selections:
        if not isinstance(selection, dict) or type(selection.get('input')) is not int or not 0 <= selection['input'] < len(packages):
            raise ValueError('Select an explicitly supplied metric input')
        available = choices(packages[selection['input']])
        selector = {k: v for k, v in selection.items() if k not in ('input', 'region')}
        found = [choice for choice in available if all(choice['selector'].get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise ValueError('Existing metric selection is missing or ambiguous; choose object, reference, method and metric')
        choice = found[0]
        values, axis = choice['input_values'], choice['positions']
        region = selection.get('region')
        if region is not None:
            requested = positions(region)
            if axis is None:
                raise ValueError('Scalar metric has no per-position values for a new region')
            keys = positions(axis)
            if any(p not in keys for p in requested):
                raise ValueError('Selected region lacks existing values or complete position correspondence')
            indices = [keys.index(p) for p in requested]
            values, axis = [values[i] for i in indices], region
        if not values or not all(finite(v) for v in values) or not choice['unit'] or not choice['source_method'] or not choice['meaning']:
            raise ValueError('Selected metric requires finite existing values, actual method, unit and meaning')
        analyses.append({k: v for k, v in choice.items() if k != 'selector'} | {
            'source': selection['input'], 'selection': choice['selector'], 'region': region if axis is not None else choice['source_region'],
            'positions': axis, 'input_values': values,
            'method': 'arithmetic mean, minimum, maximum of existing values',
            'statistics': {'count': len(values), 'mean': math.fsum(values) / len(values), 'minimum': min(values), 'maximum': max(values)}})
    files, sources = {}, []
    for index, package in enumerate(packages):
        mapping = {}
        for offset, key in enumerate(package.files):
            target = f'sources/{index}/{offset}'
            path = runtime.workdir / target
            path.parent.mkdir(parents=True, exist_ok=True)
            with package.open(key) as reader, path.open('wb') as writer:
                copyfileobj(reader, writer)
            files[target] = target
            mapping[key] = target
        sources.append({'format': package.format, 'entry': package.entry, 'files': mapping})
    (runtime.workdir / 'manifest.json').write_text(json.dumps({'sources': sources, 'analyses': analyses}, allow_nan=False))
    files['manifest.json'] = 'manifest.json'
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'analysis': [Delivery('workbench.metric_analysis', 'manifest.json', files)]})


def module():
    return Module('workbench.metric_analysis', 'Existing metric analysis', nodes=(Node(
        'workbench.analyze_metrics', 'Analyze existing metrics', analyze,
        inputs={'metrics': InputPort(FORMATS, cardinality='many')},
        outputs={'analysis': OutputPort('workbench.metric_analysis')},
        parameters={'type': 'object', 'properties': {'selections': {'type': 'array'}}, 'required': ['selections']}),))
