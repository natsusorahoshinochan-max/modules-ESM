"""Small display data for explicit sequence/reference selection."""
from protein_workbench_public.module_api import InteractionResult
from . import read_objects, reference_positions


def inspect(call, runtime):
    if call.parameters:
        raise ValueError('Input inspection accepts only explicitly supplied packages')
    sequence_source, reference_source = call.inputs['sequences'][0], call.inputs['reference'][0]
    document, references = read_objects(sequence_source), read_objects(reference_source)
    choices = []
    for index, obj in enumerate(document['objects'], 1):
        label = obj.get('label', f'Sequence {index}')
        if 'chains' in obj:
            if not isinstance(obj['chains'], dict) or not obj['chains']:
                raise ValueError('Sequence object requires actual named chains')
            for chain, sequence in obj['chains'].items():
                if not isinstance(chain, str) or not chain or not isinstance(sequence, str) or not sequence:
                    raise ValueError('Sequence object requires complete named chain sequences')
                choices.append({'object': obj['id'], 'label': label, 'source_chain': chain, 'sequence': sequence})
        else:
            if not isinstance(obj.get('sequence'), str) or not obj['sequence']:
                raise ValueError('Sequence object requires an actual sequence')
            choices.append({'object': obj['id'], 'label': label, 'sequence': obj['sequence']})
    result = [{'object': obj['id'], 'label': obj.get('label', f'Reference {index}'), 'positions': reference_positions(reference_source, obj)} for index, obj in enumerate(references['objects'], 1)]
    return InteractionResult(data={'sequences': choices, 'references': result})
