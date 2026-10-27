"""Direct reader of the published ESM3 native metric file format."""
from .formats import finite


def native_choices(document, package, selected=None):
    from . import _add_choice, read_json
    objects = document.get('objects')
    if not isinstance(objects, list) or any(not isinstance(obj, dict) or not isinstance(obj.get('id'), str) for obj in objects) or len({obj['id'] for obj in objects}) != len(objects):
        raise ValueError('Native metrics require unique complete generation objects')
    tool = document.get('tool')
    if not isinstance(tool, dict) or not isinstance(tool.get('id'), str):
        raise ValueError('Native metrics require their actual generation tool')
    result = []
    for obj in objects:
        native = read_json(package, obj.get('native', {}).get('file'))
        if not isinstance(native, dict) or native.get('tracks', {}).get('sequence') != obj.get('sequence') or not isinstance(native.get('metrics'), dict):
            raise ValueError('Native metrics require their complete original generation context')
        for metric, value in native['metrics'].items():
            common = {'object': obj, 'reference': None, 'source_region': None,
                'source_method': {'id':tool['id'], **obj.get('tool', {})},
                'unit': 'fraction (0–1)' if metric == 'ptm' else 'native source axes',
                'meaning': 'Native whole-generation pTM' if metric == 'ptm' else 'Native generation metric; explicit axis-aware analysis is required'}
            def resolve(metric=metric, value=value):
                if metric != 'ptm':
                    raise ValueError('This native metric requires explicit axis-aware analysis before scalar filtering')
                if tool['id'] == 'workbench.esm3.local' and isinstance(value, list) and len(value) == 1 and finite(value[0]):
                    # Native decode_structure accepts one structure; compute_tm retains its batch axis.
                    value = value[0]
                if not finite(value):
                    raise ValueError('Native pTM must be an actual scalar; batch-shaped values require explicit axis selection')
                return {'input_values':[value]}
            _add_choice(result, common, {'object':obj['id'], 'origin':'native_generation', 'metric':metric}, selected, resolve)
    return result
