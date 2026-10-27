"""Public reader for the sequence module's format."""
import json

ALPHABET = 'ACDEFGHIKLMNPQRSTVWYBXZJUO'


def sequence_values(sequence):
    """Decode the public sequence text; underscore is an unfilled position."""
    if not isinstance(sequence, str) or not sequence:
        raise ValueError('Sequence requires nonempty amino-acid text')
    for index, value in enumerate(sequence, 1):
        if value not in ALPHABET + '_':
            raise ValueError(f'Sequence position {index}: unsupported symbol {value!r}')
    return [None if value == '_' else value for value in sequence]


def require_complete(sequence, operation, alphabet='ACDEFGHIKLMNPQRSTVWY'):
    """An operation validates its own supported input, without changing it."""
    for index, value in enumerate(sequence_values(sequence), 1):
        if value is None or value not in alphabet:
            raise ValueError(f'{operation}: sequence position {index} contains {value!r}; a complete supported sequence is required')
    return sequence


def read_sequences(package):
    """Read explicit sequence objects, rejecting incomplete supplied correspondence."""
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or set(document) != {'objects'} or not isinstance(document['objects'], list) or not document['objects']:
        raise ValueError('Sequence input requires a nonempty sequence object batch')
    identities = set()
    for source in document['objects']:
        if not isinstance(source, dict) or set(source) - {'id', 'sequence', 'label', 'source', 'positions'}:
            raise ValueError('Sequence format accepts a protein sequence only; unsupported components or conditions')
        sequence = source.get('sequence')
        sequence_values(sequence)
        identity = source.get('id')
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('Sequence object id must be nonempty and unique within the batch')
        identities.add(identity)
        if 'label' in source and not isinstance(source['label'], str):
            raise ValueError('Sequence label must be text')
        if 'source' in source:
            origin = source['source']
            if not isinstance(origin, dict) or not origin or set(origin) - {'name', 'record', 'text'} or any(not isinstance(value, str) for value in origin.values()):
                raise ValueError('Sequence source must contain explicit name, record or text fields')
        if 'positions' in source:
            positions = source['positions']
            if not isinstance(positions, list) or len(positions) != len(sequence):
                raise ValueError('Sequence positions must cover every sequence residue')
            seen, seen_labels = set(), set()
            for index, position in enumerate(positions, 1):
                if not isinstance(position, dict) or set(position) - {'sequence_index', 'id', 'chain', 'author_number', 'insertion_code', 'label_position'} or type(position.get('sequence_index')) is not int or position['sequence_index'] != index:
                    raise ValueError('Sequence positions require ordered one-based sequence_index values')
                if 'id' in position and (not isinstance(position['id'], str) or not position['id']):
                    raise ValueError('Position id must be nonempty text')
                mapping = set(position) - {'sequence_index', 'id', 'label_position'}
                if mapping:
                    if mapping != {'chain', 'author_number', 'insertion_code'} or not isinstance(position['chain'], str) or type(position['author_number']) is not int or not isinstance(position['insertion_code'], str):
                        raise ValueError('Sequence residue correspondence requires explicit chain, author_number and insertion_code')
                    key = (position['chain'], position['author_number'], position['insertion_code'])
                    if key in seen:
                        raise ValueError('Sequence residue correspondence contains a repeated position')
                    seen.add(key)
                if 'label_position' in position:
                    label = position['label_position']
                    if not isinstance(label, dict) or set(label) != {'chain', 'position'} or not isinstance(label['chain'], str) or not label['chain'] or type(label['position']) is not int or label['position'] < 1:
                        raise ValueError('Sequence label correspondence requires chain and a positive one-based position')
                    key = (label['chain'], label['position'])
                    if key in seen_labels:
                        raise ValueError('Sequence label correspondence contains a repeated position')
                    seen_labels.add(key)
            identifiers = [row['id'] for row in positions if 'id' in row]
            if identifiers and (len(identifiers) != len(positions) or len(set(identifiers)) != len(identifiers)):
                raise ValueError('Position ids must be unique and cover the complete sequence')
    return document['objects']
