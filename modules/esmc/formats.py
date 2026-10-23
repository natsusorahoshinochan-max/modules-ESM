"""Public reader and encoder for file-backed ESMC representations."""
import json
import numpy as np

PAGE_ROWS = 64


def write_array(workdir, key, value, dtype, files):
    value = np.asarray(value, dtype='<f2' if dtype == 'float16' else '<f4')
    if not np.isfinite(value).all():
        raise ValueError('ESMC saved dtype cannot represent the returned finite values')
    pages = []
    for start in range(0, value.shape[0], PAGE_ROWS):
        page = value[start:start + PAGE_ROWS]
        name = f'{key}-{start}.bin'
        with (workdir / name).open('wb') as stream:
            stream.write(page.tobytes(order='C'))
        files[name] = name
        pages.append({'file': name, 'start': start, 'rows': len(page)})
    return {'shape': list(value.shape), 'dtype': dtype, 'byte_order': 'little', 'pages': pages}


def read_manifest(package):
    with package.open(package.entry) as stream:
        return json.load(stream)


def read_page(package, descriptor, page):
    """Read at most 64 matrix rows or vector components from package streams."""
    spec = descriptor['pages'][page]
    dtype = '<f2' if descriptor['dtype'] == 'float16' else '<f4'
    shape = (spec['rows'], *descriptor['shape'][1:])
    with package.open(spec['file']) as stream:
        content = stream.read()
    return np.frombuffer(content, dtype=dtype).reshape(shape)


def read_array(package, descriptor):
    """Explicit convenience for consumers choosing to materialize a complete array."""
    return np.concatenate([read_page(package, descriptor, index) for index in range(len(descriptor['pages']))])


def read_sequences(package):
    """Read explicit sequence objects, rejecting incomplete supplied correspondence."""
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or set(document) != {'objects'} or not isinstance(document['objects'], list) or not document['objects']:
        raise ValueError('ESMC requires a nonempty sequence object batch')
    identities = set()
    for source in document['objects']:
        if not isinstance(source, dict) or set(source) - {'id', 'sequence', 'label', 'source', 'positions'}:
            raise ValueError('ESMC accepts a protein sequence only; unsupported components or conditions')
        sequence = source.get('sequence')
        if not isinstance(sequence, str) or not sequence or any(residue not in 'ACDEFGHIKLMNPQRSTVWY' for residue in sequence):
            raise ValueError('ESMC requires an unmodified canonical protein sequence')
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
                if not isinstance(position, dict) or set(position) - {'sequence_index', 'chain', 'author_number', 'insertion_code', 'label_position'} or type(position.get('sequence_index')) is not int or position['sequence_index'] != index:
                    raise ValueError('Sequence positions require ordered one-based sequence_index values')
                mapping = set(position) - {'sequence_index', 'label_position'}
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
    return document['objects']
