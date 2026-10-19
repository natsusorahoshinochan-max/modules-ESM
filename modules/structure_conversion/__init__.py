"""Explicit prediction conversion and a consumer of the delivered structure format.

Execution reuse depends on the comparison API shipped in protein-workbench.
Prediction data is read from its published files without importing its producer.
"""
import json
from pathlib import Path
from shutil import copyfileobj

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort
from modules.structure_comparison.api import StructureInput, compare, read_reference


def _structure(value):
    if not isinstance(value, dict):
        raise ValueError('Structure record is required')
    for key in ('id', 'sequence', 'file'):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f'Structure {key} is required')
    if value.get('format') not in ('pdb', 'mmcif'):
        raise ValueError('Structure format must be pdb or mmcif')
    if 'label' in value and not isinstance(value['label'], str):
        raise ValueError('Structure label must be text')
    return value


def convert_prediction(call, runtime):
    if call.parameters:
        raise ValueError('Prediction conversion has no node parameters')
    if runtime.cancelled:
        return Outcome(status='cancelled')
    source = call.inputs['prediction'][0]
    with source.open(source.entry) as stream:
        document = json.load(stream)
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or len(objects) != 1 or not isinstance(objects[0], dict):
        raise ValueError('Conversion requires exactly one prediction object')
    obj = objects[0]
    original = obj.get('structure')
    if not isinstance(original, dict):
        raise ValueError('Prediction structure file is required')
    structure = _structure({**original, 'id': obj.get('id'), 'sequence': obj.get('sequence'),
                            **({'label': obj['label']} if 'label' in obj else {})})
    tool = document.get('tool')
    if not isinstance(tool, dict) or not isinstance(tool.get('id'), str) or not tool['id'] or not isinstance(tool.get('parameters'), dict):
        raise ValueError('Prediction tool id and parameters are required')
    key = 'structure.pdb' if structure['format'] == 'pdb' else 'structure.cif'
    with source.open(structure['file']) as reader, (runtime.workdir / key).open('wb') as writer:
        copyfileobj(reader, writer, length=1024 * 1024)
    if not (runtime.workdir / key).stat().st_size:
        raise ValueError('Prediction structure file is empty')
    # C carries the complete structure and original sequence, not prediction confidence.
    converted = {'structure': {name: structure[name] for name in ('id', 'sequence', 'format')},
                 'generation': {'tool': tool}}
    converted['structure']['file'] = key
    if 'label' in structure:
        converted['structure']['label'] = structure['label']
    (runtime.workdir / 'manifest.json').write_text(json.dumps(converted), encoding='utf-8')
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'structure': [Delivery('workbench.structure', 'manifest.json',
                                                   {'manifest.json': 'manifest.json', key: key})]})


def compare_structure(call, runtime):
    if call.parameters:
        raise ValueError('Complete-structure comparison has no node parameters')
    source = call.inputs['subject'][0]
    with source.open(source.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError('Structure manifest is required')
    structure = _structure(document.get('structure'))
    generation = document.get('generation')
    if generation is not None and not isinstance(generation, dict):
        raise ValueError('Structure generation must be an object')
    with source.open(structure['file']) as stream:
        content = stream.read()
    subject = StructureInput(structure['id'], content, structure['format'], structure['sequence'],
                             structure.get('label'), generation)
    return compare(subject, read_reference(call.inputs['reference'][0]), runtime)


def module():
    return Module(
        id='workbench.structure_conversion', name='Explicit structure conversion',
        nodes=(
            Node(id='workbench.prediction_to_structure', name='Convert prediction to structure', execute=convert_prediction,
                 inputs={'prediction': InputPort(('workbench.prediction',))},
                 outputs={'structure': OutputPort('workbench.structure')}),
            Node(id='workbench.compare_structure', name='Compare converted structure', execute=compare_structure,
                 inputs={'subject': InputPort(('workbench.structure',)), 'reference': InputPort(('workbench.reference',))},
                 outputs={'comparison': OutputPort('workbench.comparison')}),
        ), ui=str(Path(__file__).with_name('ui.js').resolve()),
    )
