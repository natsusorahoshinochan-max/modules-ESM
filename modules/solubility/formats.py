"""Independent readers for documented sequence and solubility packages."""
import json
import math


def read_sequences(package):
    with package.open(package.entry) as stream:
        document = json.load(stream)
    return sequence_objects(document)


def sequence_objects(document):
    if not isinstance(document, dict) or set(document) != {'objects'} or not isinstance(document['objects'], list) or not document['objects']:
        raise ValueError('Solubility requires a nonempty sequence object batch')
    identities = set()
    for source in document['objects']:
        if not isinstance(source, dict) or set(source) - {'id', 'sequence', 'label', 'source', 'positions'}:
            raise ValueError('Solubility accepts sequence objects only; unsupported components or conditions')
        sequence = source.get('sequence')
        if not isinstance(sequence, str) or not sequence or any(aa not in 'ACDEFGHIKLMNPQRSTVWY' for aa in sequence):
            raise ValueError('Solubility requires an unmodified canonical protein sequence')
        identity = source.get('id')
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('Sequence object id must be nonempty and unique within the batch')
        identities.add(identity)
        if 'label' in source and not isinstance(source['label'], str):
            raise ValueError('Sequence label must be text')
        if 'source' in source:
            origin = source['source']
            if not isinstance(origin, dict) or not origin or set(origin) - {'name', 'record', 'text'} or any(not isinstance(value, str) for value in origin.values()):
                raise ValueError('Sequence source requires explicit name, record or text')
        if 'positions' in source:
            positions = source['positions']
            if not isinstance(positions, list) or len(positions) != len(sequence):
                raise ValueError('Sequence positions must cover every sequence residue')
            seen, seen_labels = set(), set()
            for index, position in enumerate(positions, 1):
                if not isinstance(position, dict) or set(position) - {'sequence_index', 'chain', 'author_number', 'insertion_code', 'label_position'} or type(position.get('sequence_index')) is not int or position['sequence_index'] != index:
                    raise ValueError('Positions require ordered one-based sequence_index values')
                mapping = set(position) - {'sequence_index', 'label_position'}
                if mapping:
                    if mapping != {'chain', 'author_number', 'insertion_code'} or not isinstance(position['chain'], str) or type(position['author_number']) is not int or not isinstance(position['insertion_code'], str):
                        raise ValueError('Residue correspondence requires explicit chain, author_number and insertion_code')
                    key = (position['chain'], position['author_number'], position['insertion_code'])
                    if key in seen:
                        raise ValueError('Repeated sequence residue correspondence')
                    seen.add(key)
                if 'label_position' in position:
                    label = position['label_position']
                    if not isinstance(label, dict) or set(label) != {'chain', 'position'} or not isinstance(label['chain'], str) or not label['chain'] or type(label['position']) is not int or label['position'] < 1:
                        raise ValueError('Sequence label correspondence requires chain and a positive one-based position')
                    key = (label['chain'], label['position'])
                    if key in seen_labels:
                        raise ValueError('Sequence label correspondence contains a repeated position')
                    seen_labels.add(key)
    return document['objects']


def read_evaluations(package):
    """Read values using only this package, without producer or run lookups."""
    with package.open(package.entry) as stream:
        document = json.load(stream)
    validate_evaluations(document)
    output = document['tool']['output']
    if output not in package.files or output == package.entry:
        raise ValueError('Evaluation tool output file is missing from the package')
    return document


def validate_evaluations(document):
    if not isinstance(document, dict) or set(document) != {'objects', 'evaluations', 'tool'}:
        raise ValueError('Evaluation requires objects, evaluations and actual tool description')
    tool = document['tool']
    if not isinstance(tool, dict) or set(tool) != {'id', 'parameters', 'context', 'output'} or not isinstance(tool['id'], str) or not tool['id'] or not isinstance(tool['parameters'], dict) or not isinstance(tool['context'], dict) or not isinstance(tool['output'], str) or not tool['output']:
        raise ValueError('Evaluation requires actual tool id, parameters, context and output file key')
    objects = sequence_objects({'objects': document.get('objects')})
    identities = {obj['id'] for obj in objects}
    evaluations = document.get('evaluations')
    if not isinstance(evaluations, list) or not evaluations:
        raise ValueError('Missing solubility evaluations')
    seen = set()
    for evaluation in evaluations:
        if not isinstance(evaluation, dict) or set(evaluation) != {'object_id', 'reference', 'region', 'method', 'values'} or not isinstance(evaluation['object_id'], str) or evaluation['object_id'] not in identities or evaluation['object_id'] in seen:
            raise ValueError('Evaluation must identify exactly one supplied sequence object')
        seen.add(evaluation['object_id'])
        if evaluation.get('reference', 'missing') is not None or evaluation.get('region', 'missing') is not None:
            raise ValueError('Sequence solubility evaluates the complete sequence without a reference')
        if not isinstance(evaluation.get('method'), str) or not evaluation['method'] or not isinstance(evaluation.get('values'), dict) or not evaluation['values']:
            raise ValueError('Evaluation requires its actual method and values')
        for metric in evaluation['values'].values():
            if not isinstance(metric, dict):
                raise ValueError('Evaluation value must include its number, unit and meaning')
            value = metric.get('value')
            if type(value) not in (int, float) or not math.isfinite(value) or not isinstance(metric.get('meaning'), str) or not metric['meaning'] or not isinstance(metric.get('unit'), str):
                raise ValueError('Evaluation requires finite numeric values, units and meanings')
    if seen != identities:
        raise ValueError('Missing evaluation for a sequence object')
    return document
