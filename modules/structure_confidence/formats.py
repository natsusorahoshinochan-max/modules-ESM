"""Public, standalone reader for workbench.structure_confidence packages."""
import json
import math


def read_evaluations(package):
    with package.open(package.entry) as reader:
        document = json.load(reader)
    objects = document.get('objects')
    evaluations = document.get('evaluations')
    if not isinstance(objects, list) or not objects or not isinstance(evaluations, list) or not evaluations:
        raise ValueError('Confidence package requires objects and evaluations')
    ids = [obj.get('id') for obj in objects if isinstance(obj, dict)]
    if len(ids) != len(objects) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Confidence objects require unique explicit identities')
    for obj in objects:
        structure = obj.get('structure', {})
        if structure.get('format') not in ('pdb', 'mmcif') or structure.get('file') not in package.files:
            raise ValueError('Confidence object requires its original structure file')
    for evaluation in evaluations:
        if not isinstance(evaluation, dict) or evaluation.get('object_id') not in ids:
            raise ValueError('Confidence evaluation refers to an unknown object')
        if evaluation.get('origin') != 'independent_existing_geometry':
            raise ValueError('Expected an independent existing-geometry evaluation')
        if not isinstance(evaluation.get('method'), str) or not evaluation['method'] or evaluation.get('reference') is not None:
            raise ValueError('Confidence evaluation requires its actual method and reference meaning')
        descriptor = evaluation.get('per_position', {})
        if descriptor.get('unit') != 'fraction (0–1)' or descriptor.get('file') not in package.files:
            raise ValueError('Confidence requires a declared per-position file and scale')
        with package.open(descriptor['file']) as reader:
            scores = json.load(reader)
        positions = scores.get('positions')
        values = scores.get('plddt')
        if not isinstance(positions, list) or not positions or not isinstance(values, list) or len(values) != len(positions):
            raise ValueError('Confidence position correspondence must cover every value')
        for position in positions:
            if not isinstance(position, dict) or set(position) != {'chain', 'author_number', 'insertion_code'} or not isinstance(position['chain'], str) or type(position['author_number']) is not int or not isinstance(position['insertion_code'], str):
                raise ValueError('Confidence requires actual chain, author number and insertion code')
        if len({(p['chain'], p['author_number'], p['insertion_code']) for p in positions}) != len(positions) or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError('Confidence requires unique positions and finite pLDDT fractions (0–1)')
        region = evaluation.get('region')
        if region is not None and region != positions:
            raise ValueError('Confidence region differs from its per-position correspondence')
        mean = evaluation.get('values', {}).get('mean_plddt', {})
        value = mean.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 or mean.get('unit') != 'fraction (0–1)' or not isinstance(mean.get('meaning'), str):
            raise ValueError('Confidence mean requires its finite value, fraction scale and meaning')
    return document
