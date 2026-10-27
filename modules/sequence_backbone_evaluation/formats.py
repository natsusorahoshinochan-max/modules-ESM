"""Standalone file reader; depends only on Python's standard library."""
import json
import math


def actual_position(row):
    if not isinstance(row, dict) or not isinstance(row.get('chain'), str) or not row['chain'] or type(row.get('author_number')) is not int or not isinstance(row.get('insertion_code'), str):
        raise ValueError('Mapping requires actual chain, integer author_number and insertion_code')
    return {k: row[k] for k in ('chain', 'author_number', 'insertion_code')}


def mapped_sequences(objects, positions, bindings):
    by_chain = {}
    for p in positions:
        by_chain.setdefault(p['chain'], []).append(p)
    if not isinstance(bindings, list) or len(bindings) != len(by_chain) or any(not isinstance(b, dict) or set(b) - {'reference_chain', 'object', 'source_chain', 'positions'} for b in bindings):
        raise ValueError('Provide one complete explicit sequence binding for every reference chain')
    result, identities = {}, []
    for binding in bindings:
        chain = binding.get('reference_chain')
        if chain not in by_chain or chain in result:
            raise ValueError('Binding has a missing or ambiguous reference chain')
        selected = [o for o in objects if o['id'] == binding.get('object')]
        if len(selected) != 1:
            raise ValueError('Select one supplied sequence object for each chain')
        obj = selected[0]
        if 'chains' in obj:
            if not isinstance(obj['chains'], dict) or binding.get('source_chain') not in obj['chains']:
                raise ValueError('Select an explicit actual source chain')
            sequence = obj['chains'][binding['source_chain']]
        else:
            if 'source_chain' in binding:
                raise ValueError('Single sequence objects have no source_chain selector')
            sequence = obj.get('sequence')
        source_positions = obj.get('positions')
        source_chain = binding.get('source_chain')
        if source_positions is not None or source_chain is not None:
            if not isinstance(source_positions, list) or any(not isinstance(p, dict) for p in source_positions):
                raise ValueError('Selected source requires complete position correspondence')
            source_rows = [p for p in source_positions if source_chain is None or p.get('chain') == source_chain]
            index_key = 'tool_position' if source_chain is not None else 'sequence_index'
            if not isinstance(sequence, str) or len(source_rows) != len(sequence) or any(type(p.get(index_key)) is not int or p[index_key] != i for i, p in enumerate(source_rows, 1)):
                raise ValueError('Selected source positions must cover every sequence residue in order')
            source_actual, source_labels = [], set()
            for row in source_rows:
                label = row.get('label_position')
                if 'label_position' in row:
                    if not isinstance(label, dict) or set(label) != {'chain', 'position'} or not isinstance(label['chain'], str) or not label['chain'] or type(label['position']) is not int or label['position'] < 1:
                        raise ValueError('Source label correspondence requires an explicit chain and position')
                    label_key = (label['chain'], label['position'])
                    if label_key in source_labels:
                        raise ValueError('Selected source has repeated label correspondence')
                    source_labels.add(label_key)
                mapping_keys = set(row) - {index_key, 'label_position'}
                if source_chain is not None or mapping_keys:
                    if mapping_keys != {'chain', 'author_number', 'insertion_code'}:
                        raise ValueError('Selected source has incomplete real residue correspondence')
                    source_actual.append(actual_position(row))
            if len({tuple(p.values()) for p in source_actual}) != len(source_actual):
                raise ValueError('Selected source has ambiguous real residue correspondence')
        rows = binding.get('positions')
        expected = by_chain[chain]
        if not isinstance(sequence, str) or len(sequence) != len(expected) or not sequence or any(aa not in 'ACDEFGHIKLMNPQRSTVWYX' for aa in sequence):
            raise ValueError('Sequence must cover the complete reference chain; no prefix or native-tail repair')
        if not isinstance(rows, list) or len(rows) != len(sequence):
            raise ValueError('Mapping must cover every sequence and reference position')
        for i, (row, position) in enumerate(zip(rows, expected, strict=True), 1):
            if not isinstance(row, dict) or set(row) != {'sequence_index', 'chain', 'author_number', 'insertion_code'} or type(row['sequence_index']) is not int or row['sequence_index'] != i or actual_position(row) != actual_position(position):
                raise ValueError('Mapping must match complete chain order, real numbering and insertion codes')
        result[chain] = sequence
        if obj['id'] not in identities:
            identities.append(obj['id'])
    return result, identities


def validate_samples(samples, sequences):
    if not isinstance(samples, list) or not samples:
        raise ValueError('Evaluation requires actual scoring samples')
    for sample in samples:
        if not isinstance(sample, dict) or sample.get('chains') != sequences:
            raise ValueError('Scoring tool changed the supplied sequences')
        for name in ('score', 'global_score'):
            if type(sample.get(name)) not in (int, float) or not math.isfinite(sample[name]):
                raise ValueError('Scoring tool must return finite actual NLL scores')
        for name in ('residue_nll', 'design_mask', 'coordinate_mask'):
            values = sample.get(name)
            if not isinstance(values, dict) or set(values) != set(sequences) or any(not isinstance(values[c], list) or len(values[c]) != len(sequences[c]) or any(type(v) not in (int, float) or not math.isfinite(v) or (name != 'residue_nll' and v not in (0, 1)) for v in values[c]) for c in sequences):
                raise ValueError(f'Scoring tool must return complete numeric {name}')


def read_evaluations(package):
    """Read objects, separate evaluation relations and actual masks without tools/history."""
    with package.open(package.entry) as stream:
        document = json.load(stream)
    objects, evaluations = document.get('objects'), document.get('evaluations')
    if not isinstance(objects, list) or not objects or any(not isinstance(o, dict) or not isinstance(o.get('id'), str) for o in objects):
        raise ValueError('Evaluation requires explicit sequence objects')
    identities = [o['id'] for o in objects]
    if len(set(identities)) != len(identities) or not all(identities):
        raise ValueError('Sequence objects require unique nonempty identities')
    if not isinstance(evaluations, list) or not evaluations:
        raise ValueError('Evaluation package requires evaluation records')
    found = False
    for e in evaluations:
        if not isinstance(e, dict):
            raise ValueError('Evaluation record must be an object')
        if e.get('origin') != 'independent_sequence_backbone':
            continue
        found = True
        if not isinstance(e.get('object_ids'), list) or not e['object_ids'] or any(i not in identities for i in e['object_ids']):
            raise ValueError('Evaluation must identify its supplied sequence objects')
        reference, manifest = e.get('reference', {}), e.get('reference_manifest', {})
        structure = reference.get('structure', {})
        if not isinstance(reference.get('id'), str) or not reference['id'] or structure.get('file') not in package.files or structure.get('format') not in ('pdb', 'mmcif') or manifest.get('file') not in package.files or not isinstance(manifest.get('files'), dict) or any(key not in package.files for key in manifest['files'].values()):
            raise ValueError('Evaluation reference requires its complete original file package')
        if e.get('method') != 'ProteinMPNN score_only' or e.get('unit') != 'negative log likelihood (natural logarithm)' or type(e.get('actual_seed')) is not int or not 0 <= e['actual_seed'] <= 2**32 - 1 or not isinstance(e.get('parameters'), dict):
            raise ValueError('Evaluation requires actual method, NLL unit, parameters and seed')
        positions = e.get('positions')
        if not isinstance(positions, list) or not positions:
            raise ValueError('Evaluation requires full reference correspondence')
        by_chain, actual = {}, []
        for p in positions:
            if not isinstance(p, dict) or set(p) != {'chain', 'author_number', 'insertion_code', 'tool_position'} or not isinstance(p['chain'], str) or not p['chain'] or type(p['author_number']) is not int or not isinstance(p['insertion_code'], str) or type(p['tool_position']) is not int:
                raise ValueError('Invalid actual reference correspondence')
            chain = by_chain.setdefault(p['chain'], [])
            if p['tool_position'] != len(chain) + 1:
                raise ValueError('Reference tool positions must be consecutive per chain')
            chain.append(p)
            actual.append({key: p[key] for key in ('chain', 'author_number', 'insertion_code')})
        if len({tuple(p.values()) for p in actual}) != len(actual):
            raise ValueError('Reference residue correspondence is ambiguous')
        samples = e.get('samples')
        sequences = samples[0].get('chains') if isinstance(samples, list) and samples and isinstance(samples[0], dict) else None
        if not isinstance(sequences, dict) or set(sequences) != set(by_chain) or any(not isinstance(sequences[c], str) or len(sequences[c]) != len(rows) for c, rows in by_chain.items()):
            raise ValueError('Evaluation sequences must cover complete reference chains')
        expected_sequences, expected_ids = mapped_sequences(objects, positions, e.get('bindings'))
        if sequences != expected_sequences or e['object_ids'] != expected_ids:
            raise ValueError('Evaluation sequence ownership differs from complete supplied mapping')
        validate_samples(samples, sequences)
        region = e.get('region')
        if region is not None and (not isinstance(region, list) or not region or any(p not in actual for p in region) or len({json.dumps(p, sort_keys=True) for p in region}) != len(region)):
            raise ValueError('Evaluation region requires unique actual positions')
        chosen = actual if region is None else region
        expected_mask = {c: [float({key: p[key] for key in ('chain', 'author_number', 'insertion_code')} in chosen) for p in rows] for c, rows in by_chain.items()}
        for sample in samples:
            if sample.get('region_mask') != expected_mask or type(sample.get('region_nll')) not in (float, int) or not math.isfinite(sample['region_nll']):
                raise ValueError('Evaluation requires finite region NLL and its complete region mask')
    if not found:
        raise ValueError('No independent sequence/backbone evaluation records')
    return document
