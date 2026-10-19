"""Analyze explicitly selected existing metric values; never invoke scientific tools."""
import json
import math
from shutil import copyfileobj
from pathlib import Path

from protein_workbench_public.module_api import Delivery, InputPort, Interaction, InteractionResult, Module, Node, Outcome, OutputPort
from .formats import finite, positions

FORMATS = ('workbench.structure_confidence', 'workbench.comparison', 'workbench.solubility', 'workbench.prediction', 'workbench.sequence_backbone_evaluation')


def read_json(package, key):
    if not isinstance(key, str) or key not in package.files:
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


def _add_choice(result, common, selector, selected, resolve):
    if selected is not None and (set(selector) != set(selected) or any(type(selector[key]) is not type(value) or selector[key] != value for key, value in selected.items())):
        return
    choice = common | {'selector': selector, 'metric': selector['metric'], 'positions': None}
    try:
        choice.update(resolve())
        if (not choice['input_values'] or not all(finite(value) for value in choice['input_values'])
                or not isinstance(choice.get('unit'), str) or not choice['unit']
                or not isinstance(choice.get('source_method'), (str, dict)) or not choice['source_method']
                or not isinstance(choice.get('meaning'), str) or not choice['meaning']):
            raise ValueError('Selected metric requires finite existing values, actual method, unit and meaning')
    except (ValueError, OSError, UnicodeError) as error:
        if selected is not None:
            raise
        choice = common | {'selector': selector, 'metric': selector['metric'], 'positions': None, 'unavailable': str(error)}
    result.append(choice)


def choices(package, selected=None):
    document = read_json(package, package.entry)
    if not isinstance(document, dict):
        raise ValueError('Metric input requires an object entry')
    if package.format == 'workbench.sequence_backbone_evaluation':
        from .backbone import backbone_choices
        return backbone_choices(document, package, selected)
    if package.format == 'workbench.comparison':
        subject, reference = document.get('subject'), document.get('reference')
        for obj in (subject, reference):
            if not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not obj['id']:
                raise ValueError('Comparison requires its actual subject and reference')
            if obj.get('structure', {}).get('file') not in package.files:
                raise ValueError('Comparison requires both complete original structure files')
        result = []
        for metric, descriptor in document.get('metrics', {}).items():
            common = {'object': subject, 'reference': reference, 'source_region': document.get('region'), 'source_method': document.get('method'),
                'unit': descriptor.get('unit') if isinstance(descriptor, dict) else None,
                'meaning': (descriptor.get('normalization') or descriptor.get('scope')) if isinstance(descriptor, dict) else None}
            def resolve():
                if not isinstance(descriptor, dict):
                    raise ValueError('Comparison metric requires its numeric descriptor')
                return {'unit': descriptor.get('unit'), 'meaning': descriptor.get('normalization') or descriptor.get('scope'), 'input_values': [descriptor.get('value')]}
            _add_choice(result, common, {'object': subject['id'], 'origin': 'comparison', 'metric': metric}, selected, resolve)
        if not result and selected is None:
            raise ValueError('Comparison contains no existing numeric metrics')
        return result
    objects = document.get('objects', [])
    if not isinstance(objects, list) or any(not isinstance(obj, dict) for obj in objects):
        raise ValueError('Metric input requires actual object descriptions')
    ids = [obj.get('id') for obj in objects]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Metric objects require unique explicit identities')
    if package.format in ('workbench.structure_confidence', 'workbench.prediction'):
        if any(obj.get('structure', {}).get('file') not in package.files for obj in objects):
            raise ValueError('Metric input requires every complete original structure file')
    result = []
    if package.format == 'workbench.prediction':
        tool = document.get('tool')
        if not isinstance(tool, dict) or not isinstance(tool.get('id'), str) or not tool['id'] or not isinstance(tool.get('parameters'), dict):
            raise ValueError('Natural confidence requires its actual source tool and parameters')
        for obj in objects:
            common = {'object': obj, 'reference': None, 'source_region': None, 'source_method': tool, 'unit': 'fraction (0–1)'}
            confidence = obj.get('confidence', {})
            for metric in ('plddt', 'ptm'):
                if metric not in confidence:
                    continue
                def resolve():
                    if metric == 'ptm':
                        value = confidence[metric]
                        if not finite(value) or not 0 <= value <= 1:
                            raise ValueError('Natural pTM requires a finite 0–1 value')
                        return {'meaning': 'Source whole-prediction pTM', 'input_values': [value]}
                    descriptor = confidence[metric]
                    if not isinstance(descriptor, dict) or descriptor.get('scale') != '0-1':
                        raise ValueError('Natural confidence requires its explicit 0–1 scale')
                    saved = read_json(package, descriptor.get('file'))
                    if not isinstance(saved, dict):
                        raise ValueError('Natural confidence requires its value object')
                    scores = saved.get('plddt')
                    axis = prediction_positions(package, obj)
                    if not isinstance(scores, list) or len(scores) != len(axis) or any(not finite(v) or not 0 <= v <= 1 for v in scores):
                        raise ValueError('Natural confidence correspondence must cover every finite 0–1 value')
                    return {'meaning': 'Source prediction local confidence', 'input_values': scores, 'positions': axis}
                _add_choice(result, common | {'meaning': 'Source whole-prediction pTM' if metric == 'ptm' else 'Source prediction local confidence'},
                    {'object': obj['id'], 'origin': 'generation', 'metric': metric}, selected, resolve)
    for index, evaluation in enumerate(document.get('evaluations', [])):
        if selected is not None and (type(selected.get('evaluation')) is not int or selected['evaluation'] != index):
            continue
        if not isinstance(evaluation, dict) or 'reference' not in evaluation or 'region' not in evaluation:
            raise ValueError('Metric evaluation requires explicit attribution and original region')
        matches = [obj for obj in objects if obj['id'] == evaluation.get('object_id')]
        if len(matches) != 1:
            raise ValueError('Metric evaluation requires one explicitly supplied object')
        obj = matches[0]
        if package.format == 'workbench.structure_confidence' and (evaluation.get('origin') != 'independent_existing_geometry' or evaluation['reference'] is not None):
            raise ValueError('Confidence requires its independent existing-geometry attribution')
        common = {'object': obj, 'reference': evaluation['reference'], 'source_region': evaluation['region'], 'source_method': evaluation.get('method')}
        for metric, descriptor in evaluation.get('values', {}).items():
            def resolve():
                if not isinstance(descriptor, dict):
                    raise ValueError('Metric scalar requires its numeric descriptor')
                number = descriptor.get('value')
                if package.format == 'workbench.structure_confidence' and (descriptor.get('unit') != 'fraction (0–1)' or not finite(number) or not 0 <= number <= 1):
                    raise ValueError('Confidence scalar requires an existing finite fraction (0–1)')
                return {'unit': descriptor.get('unit'), 'meaning': descriptor.get('meaning'), 'input_values': [number]}
            metadata = {'unit': descriptor.get('unit'), 'meaning': descriptor.get('meaning')} if isinstance(descriptor, dict) else {}
            _add_choice(result, common | metadata, {'object': obj['id'], 'origin': 'evaluation', 'evaluation': index, 'metric': metric}, selected, resolve)
        if 'per_position' in evaluation:
            def resolve():
                descriptor = evaluation['per_position']
                if not isinstance(descriptor, dict) or descriptor.get('unit') != 'fraction (0–1)':
                    raise ValueError('Confidence requires its explicit fraction (0–1) unit')
                scores = read_json(package, descriptor.get('file'))
                if not isinstance(scores, dict):
                    raise ValueError('Confidence requires its position/value object')
                axis, values = scores.get('positions'), scores.get('plddt')
                keys = positions(axis)
                if not isinstance(values, list) or len(keys) != len(values) or any(not finite(v) or not 0 <= v <= 1 for v in values):
                    raise ValueError('Confidence position correspondence must cover every finite 0–1 value')
                if evaluation['region'] is not None and evaluation['region'] != axis:
                    raise ValueError('Confidence region differs from its position correspondence')
                return {'unit': descriptor.get('unit'), 'meaning': descriptor.get('meaning'), 'input_values': values, 'positions': axis}
            descriptor = evaluation['per_position']
            metadata = {'unit': descriptor.get('unit'), 'meaning': descriptor.get('meaning')} if isinstance(descriptor, dict) else {}
            _add_choice(result, common | metadata, {'object': obj['id'], 'origin': 'evaluation', 'evaluation': index, 'metric': 'plddt'}, selected, resolve)
    if not result and selected is None:
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
        selector = {k: v for k, v in selection.items() if k not in ('input', 'region')}
        if not isinstance(selector.get('metric'), str) or not isinstance(selector.get('origin'), str) or not ({'object', 'objects'} & selector.keys()):
            raise ValueError('Existing metric selection is missing or ambiguous; choose object, reference, method and metric')
        available = choices(packages[selection['input']], selector)
        found = [choice for choice in available if set(choice['selector']) == set(selector) and all(type(choice['selector'][k]) is type(v) and choice['selector'][k] == v for k, v in selector.items())]
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
            lookup = {key: i for i, key in enumerate(keys)}
            indices = [lookup[p] for p in requested]
            values, axis = [values[i] for i in indices], region
        if 'valid_positions' in choice:
            lookup = {key: i for i, key in enumerate(positions(choice['positions']))}
            indices = [lookup[p] for p in positions(axis)]
            if any(not choice['valid_positions'][i] for i in indices):
                raise ValueError('Selected region lacks valid existing backbone coordinates for its values')
        if not values or not all(finite(v) for v in values) or not isinstance(choice['unit'], str) or not choice['unit'] or not isinstance(choice['source_method'], (str, dict)) or not choice['source_method'] or not isinstance(choice['meaning'], str) or not choice['meaning']:
            raise ValueError('Selected metric requires finite existing values, actual method, unit and meaning')
        analyses.append({k: v for k, v in choice.items() if k not in ('selector', 'valid_positions')} | {
            'source': selection['input'], 'selection': choice['selector'], 'region': axis if axis is not None else choice.get('metric_region', choice['source_region']),
            'positions': axis, 'input_values': values,
            'method': 'arithmetic mean, minimum, maximum of existing values',
            'statistics': {'count': len(values), 'mean': math.fsum(values) / len(values), 'minimum': min(values), 'maximum': max(values)}})
    files, sources = {}, []
    for index, package in enumerate(packages):
        mapping = {}
        for offset, key in enumerate(package.files):
            if runtime.cancelled:
                return Outcome(status='cancelled')
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


def inspect_metrics(call, runtime):
    display = []
    for index, package in enumerate(call.inputs.get('metrics', ())):
        if runtime.cancelled:
            raise ValueError('Metric inspection cancelled')
        object_labels = {}
        for choice in choices(package):
            identity = json.dumps(choice['selector'].get('object', choice['selector'].get('objects')))
            if identity not in object_labels:
                object_labels[identity] = f'Object {len(object_labels) + 1}'
            reference = choice['reference']
            display.append({'selector': {'input': index, **choice['selector']},
                'object_label': choice['object'].get('label') or object_labels[identity],
                'reference_label': (reference.get('label') or 'Selected reference') if isinstance(reference, dict) else 'No reference',
                'source_region': choice['source_region'], 'source_method': choice['source_method'],
                'positions': choice['positions'], 'unit': choice.get('unit'), 'meaning': choice.get('meaning'),
                **({'unavailable': choice['unavailable']} if 'unavailable' in choice else {})})
    return InteractionResult(data={'choices': display})


def module():
    return Module('workbench.metric_analysis', 'Existing metric analysis', ui=str(Path(__file__).with_name('ui.js')),
        interactions=(Interaction('workbench.inspect_metrics', inspect_metrics, inputs={'metrics': InputPort(FORMATS, cardinality='many')}),), nodes=(Node(
        'workbench.analyze_metrics', 'Analyze existing metrics', analyze,
        inputs={'metrics': InputPort(FORMATS, cardinality='many')},
        outputs={'analysis': OutputPort('workbench.metric_analysis')},
        parameters={'type': 'object', 'properties': {'selections': {'type': 'array'}}, 'required': ['selections']}),))
