"""Read natural ProteinMPNN whole-design scalars from the public result format."""
from .formats import finite


def design_choices(document, package, selected=None):
    from . import _add_choice
    objects, tool = document.get('objects'), document.get('tool')
    if not isinstance(objects, list) or any(not isinstance(obj, dict) or not isinstance(obj.get('id'), str) for obj in objects) or len({obj['id'] for obj in objects}) != len(objects):
        raise ValueError('Design metrics require unique complete design objects')
    if not isinstance(tool, dict) or not isinstance(tool.get('id'), str):
        raise ValueError('Design metrics require their actual source tool')
    result = []
    meanings = {'score':'Native mean NLL over coordinate validity × designed-chain × nonfixed-position masks',
        'global_score':'Native mean NLL over coordinate validity of all backbone chains',
        'recovery':'Native design-mask fraction matching the original backbone sequence'}
    for index,obj in enumerate(objects):
        design = obj.get('design', {})
        for metric in meanings:
            if metric not in design:
                continue
            def resolve(metric=metric, obj=obj, design=design):
                chains = obj.get('chains')
                reference = obj.get('backbone', {}).get('structure', {})
                if not isinstance(chains, dict) or not chains or design.get('chains') != chains or any(not isinstance(sequence, str) or not sequence for sequence in chains.values()):
                    raise ValueError('Design metric requires the complete original multichain sample')
                if reference.get('file') not in package.files:
                    raise ValueError('Design metric requires its original complete backbone file')
                for name in (('coordinate_mask',) if metric == 'global_score' else ('coordinate_mask','design_mask')):
                    mask = design.get(name)
                    if not isinstance(mask, dict) or set(mask) != set(chains) or any(not isinstance(mask[c], list) or len(mask[c]) != len(sequence) or any(not finite(value) or value not in (0,1) for value in mask[c]) for c,sequence in chains.items()):
                        raise ValueError('Design metric requires its complete original scoring mask')
                return {'input_values':[design[metric]]}
            common = {'object':obj,'reference':obj.get('backbone'),'source_region':{'scope':meanings[metric]},
                'source_method':{'id':tool['id'],**obj.get('tool',{})},'unit':'fraction (0–1)' if metric=='recovery' else 'negative log likelihood (natural logarithm)',
                'meaning':meanings[metric]}
            _add_choice(result,common,{'object':obj['id'],'origin':'native_design','metric':metric},selected,resolve)
    return result
