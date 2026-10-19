"""Direct consumer of the sequence/backbone evaluation's published JSON format."""
from .formats import finite, positions


def backbone_choices(document, package):
    objects = document.get('objects', [])
    if not isinstance(objects, list) or any(not isinstance(obj, dict) for obj in objects):
        raise ValueError('Backbone metrics require actual original objects')
    ids = [obj.get('id') for obj in objects]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Backbone metrics require unique original sequence objects')
    result = []
    for index, evaluation in enumerate(document.get('evaluations', [])):
        if evaluation.get('origin') != 'independent_sequence_backbone':
            continue
        identities = evaluation.get('object_ids')
        if not isinstance(identities, list) or not identities or len(set(identities)) != len(identities) or any(i not in ids for i in identities):
            raise ValueError('Backbone metric requires the complete explicitly evaluated object context')
        members = [objects[ids.index(identity)] for identity in identities]
        if evaluation.get('method') != 'ProteinMPNN score_only' or evaluation.get('unit') != 'negative log likelihood (natural logarithm)':
            raise ValueError('Backbone metrics require actual method and NLL unit')
        reference = evaluation.get('reference', {})
        if not reference.get('id') or reference.get('structure', {}).get('file') not in package.files:
            raise ValueError('Backbone metric requires its complete original reference structure')
        manifest = evaluation.get('reference_manifest', {})
        if manifest.get('file') not in package.files or not isinstance(manifest.get('files'), dict) or any(key not in package.files for key in manifest['files'].values()):
            raise ValueError('Backbone metric requires its complete original reference file map')
        raw_axis = evaluation.get('positions')
        if not isinstance(raw_axis, list) or not raw_axis:
            raise ValueError('Backbone metric requires complete actual position correspondence')
        axis, by_chain = [], {}
        for item in raw_axis:
            if not isinstance(item, dict) or set(item) != {'chain', 'author_number', 'insertion_code', 'tool_position'}:
                raise ValueError('Backbone metric position correspondence is incomplete')
            chain = by_chain.setdefault(item['chain'], [])
            if type(item['tool_position']) is not int or item['tool_position'] != len(chain) + 1:
                raise ValueError('Backbone tool position correspondence must be complete within each chain')
            actual = {key: item[key] for key in ('chain', 'author_number', 'insertion_code')}
            chain.append(actual)
            axis.append(actual)
        positions(axis)
        bindings = evaluation.get('bindings')
        if not isinstance(bindings, list) or len(bindings) != len(by_chain):
            raise ValueError('Backbone metric requires complete object/reference bindings')
        mapped, mapped_ids = {}, []
        for binding in bindings:
            chain = binding.get('reference_chain')
            selected = [obj for obj in members if obj['id'] == binding.get('object')]
            if chain not in by_chain or chain in mapped or len(selected) != 1:
                raise ValueError('Backbone metric object/reference bindings are ambiguous')
            obj = selected[0]
            sequence = obj.get('chains', {}).get(binding.get('source_chain')) if 'chains' in obj else obj.get('sequence')
            rows = binding.get('positions')
            if not isinstance(rows, list) or any(not isinstance(p, dict) or set(p) != {'sequence_index', 'chain', 'author_number', 'insertion_code'} or type(p['sequence_index']) is not int for p in rows):
                raise ValueError('Backbone metric requires exact integer sequence position correspondence')
            positions([{key: p[key] for key in ('chain', 'author_number', 'insertion_code')} for p in rows])
            expected = [dict(p, sequence_index=i) for i,p in enumerate(by_chain[chain],1)]
            if binding.get('positions') != expected or not isinstance(sequence, str) or len(sequence) != len(expected):
                raise ValueError('Backbone metric requires complete object/reference sequence correspondence')
            mapped[chain] = sequence
            if obj['id'] not in mapped_ids:
                mapped_ids.append(obj['id'])
        if mapped_ids != identities:
            raise ValueError('Backbone metric joint object ownership differs from its bindings')
        samples = evaluation.get('samples')
        if not isinstance(samples, list) or not samples:
            raise ValueError('Backbone metric requires explicitly selected existing samples')
        for sample_index, sample in enumerate(samples):
            sequences = sample.get('chains')
            if sequences != mapped or not isinstance(sequences, dict) or set(sequences) != set(by_chain) or any(not isinstance(sequences[c], str) or len(sequences[c]) != len(by_chain[c]) for c in by_chain):
                raise ValueError('Backbone metric sequence correspondence must cover every position')
            for name in ('residue_nll', 'coordinate_mask', 'design_mask', 'region_mask'):
                values = sample.get(name)
                if not isinstance(values, dict) or set(values) != set(by_chain) or any(not isinstance(values[c], list) or len(values[c]) != len(by_chain[c]) or any(not finite(v) or (name != 'residue_nll' and v not in (0, 1)) for v in values[c]) for c in by_chain):
                    raise ValueError(f'Backbone metric requires complete finite {name} correspondence')
            common = {'object': {'members': members, 'label': 'Joint sequence context: ' + ', '.join(obj.get('label') or f'Sequence {i+1}' for i,obj in enumerate(members))},
                'reference': reference, 'source_method': evaluation.get('method'), 'source_region': evaluation.get('region'),
                'unit': evaluation.get('unit'), 'sample': sample_index,
                'context': {'chains': sequences, 'coordinate_mask': sample['coordinate_mask'], 'design_mask': sample['design_mask'], 'region_mask': sample['region_mask']}}
            for metric in ('score', 'global_score', 'region_nll', 'residue_nll'):
                selector = {'objects': identities, 'origin': 'sequence_backbone', 'evaluation': index, 'sample': sample_index, 'metric': metric}
                if metric == 'residue_nll':
                    values = [sample[metric][p['chain']][p['tool_position']-1] for p in raw_axis]
                    meaning = 'Existing residue NLL in the complete supplied sequence/backbone context; lower is better'
                    result.append(common | {'selector': selector, 'metric': metric, 'meaning': meaning, 'input_values': values, 'positions': axis,
                        'valid_positions': [sample['coordinate_mask'][p['chain']][p['tool_position']-1] == 1 for p in raw_axis]})
                elif metric in sample:
                    meanings = {'score': 'Native mean NLL over coordinate validity × designed-chain × nonfixed-position masks',
                        'global_score': 'Native mean NLL over coordinate validity for all supplied chains',
                        'region_nll': 'Existing region NLL over the original explicit reference region mask'}
                    result.append(common | {'selector': selector, 'metric': metric, 'meaning': meanings[metric], 'input_values': [sample[metric]], 'positions': None,
                        'metric_region': evaluation.get('region') if metric == 'region_nll' else {'scope': meanings[metric]}})
    if not result:
        raise ValueError('Input contains no existing sequence/backbone metrics')
    return result
