"""Explicit object collection operations, independent from filtering policy."""
from copy import deepcopy
import json
from pathlib import Path
from shutil import copyfileobj
from types import SimpleNamespace

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort
from .api import collect
from .formats import FORMAT, read_candidates, read_collection

FORMATS = ('workbench.sequence', 'workbench.structure_set', 'workbench.prediction',
           'workbench.comparison', 'workbench.proteinmpnn_design', 'workbench.esm3_generation',
           'workbench.structure_confidence', 'workbench.solubility',
           'workbench.sequence_backbone_evaluation', FORMAT)


def merge(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if call.parameters:
        raise ValueError('Merge has no parameters; input package order defines item order')
    packages = call.inputs.get('packages', ())
    try:
        result = collect(packages, read_candidates(packages), runtime)
    except InterruptedError:
        return Outcome(status='cancelled')
    return Outcome(outputs={'collection': [result]})


def split(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if call.parameters:
        raise ValueError('Split has no parameters')
    packages = call.inputs['collection']
    deliveries = []
    for row in read_candidates(packages):
        try:
            deliveries.append(collect(packages, [row], runtime))
        except InterruptedError:
            return Outcome(status='cancelled')
    return Outcome(outputs={'items': deliveries})


def select_items(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    packages = call.inputs['collection']
    candidates = read_candidates(packages)
    chosen = call.parameters.get('items')
    if set(call.parameters) != {'items'} or not isinstance(chosen, list) or any(type(i) is not int or not 0 <= i < len(candidates) for i in chosen) or len(set(chosen)) != len(chosen):
        raise ValueError('Select unique existing item positions in the desired output order')
    try:
        result = collect(packages, [candidates[i] for i in chosen], runtime, parameters=call.parameters)
    except InterruptedError:
        return Outcome(status='cancelled')
    return Outcome(outputs={'collection': [result]})


def extract_structures(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if call.parameters:
        raise ValueError('Structure extraction has no parameters; select collection items first')
    package = call.inputs['collection'][0]
    document = read_collection(package)
    from modules.structure_io import parse, atoms
    files, objects, identities = {}, [], set()
    for index, item in enumerate(document['items']):
        if runtime.cancelled:
            return Outcome(status='cancelled')
        obj = deepcopy(item['object'])
        identity = obj.get('id')
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('Structure extraction requires distinct selected object identities')
        identities.add(identity)
        descriptor = obj.get('structure')
        source = document['sources'][item['source']]
        if not isinstance(descriptor, dict) or descriptor.get('format') not in ('pdb','mmcif') or descriptor.get('file') not in source['files']:
            raise ValueError('Every selected object must supply its complete PDB or mmCIF structure')
        key = f'structures/{index}.'+('pdb' if descriptor['format']=='pdb' else 'cif')
        path = runtime.workdir/key
        path.parent.mkdir(parents=True,exist_ok=True)
        with package.open(source['files'][descriptor['file']]) as reader,path.open('wb') as writer:
            copyfileobj(reader,writer)
        descriptor['file'] = key
        files[key] = key
        # Preserve other object file references by mapping all remaining source files.
        mapping = {}
        for offset,(original,copied) in enumerate(source['files'].items()):
            target = f'original/{index}/{offset}'
            destination = runtime.workdir/target
            destination.parent.mkdir(parents=True,exist_ok=True)
            with package.open(copied) as reader,destination.open('wb') as writer:
                copyfileobj(reader,writer)
            files[target] = target
            mapping[original] = target
        atom_key = f'structures/{index}.atoms.json'
        structure = parse(path.read_bytes(), descriptor['format'])
        if len(structure) != 1:
            raise ValueError('Each selected structure must contain one explicit conformation')
        (runtime.workdir/atom_key).write_text(json.dumps(atoms(structure),allow_nan=False))
        files[atom_key] = atom_key
        obj = {key:obj[key] for key in ('id','label','sequence','positions') if key in obj} | {'structure':descriptor,'atoms':atom_key}
        obj['collection_source'] = {'format':source['format'],'entry':source['entry'],'files':mapping,'original_object':deepcopy(item['object'])}
        objects.append(obj)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    (runtime.workdir/'manifest.json').write_text(json.dumps({'objects':objects},allow_nan=False))
    files['manifest.json']='manifest.json'
    return Outcome(outputs={'structures':[Delivery('workbench.structure_set','manifest.json',files)]})


def extract_sequences(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if call.parameters:
        raise ValueError('Sequence extraction has no parameters; select collection items first')
    document = read_collection(call.inputs['collection'][0])
    objects, identities = [], set()
    for item in document['items']:
        original = item['object']
        sequence = original.get('sequence')
        identity = original.get('id')
        from modules.sequence_io.formats import sequence_values
        sequence_values(sequence)
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('Sequence extraction requires distinct selected object identities')
        identities.add(identity)
        obj = {'id': identity, 'sequence': sequence}
        if isinstance(original.get('label'), str):
            obj['label'] = original['label']
        source = original.get('source')
        if isinstance(source, dict) and source and not set(source) - {'name', 'record', 'text'} and all(isinstance(v, str) for v in source.values()):
            obj['source'] = deepcopy(source)
        positions = original.get('positions')
        if positions is not None:
            if not isinstance(positions, list) or len(positions) != len(sequence):
                raise ValueError('Supplied positions must cover the complete selected sequence')
            obj['positions'] = []
            for index, position in enumerate(positions, 1):
                if not isinstance(position, dict) or type(position.get('sequence_index')) is not int or position['sequence_index'] != index:
                    raise ValueError('Supplied positions must follow the complete sequence order')
                output = {'sequence_index': index}
                fields = {'chain', 'author_number', 'insertion_code'}
                source = position.get('source', {})
                correspondence = position if fields & position.keys() or 'label_position' in position else source.get('position', {})
                if not isinstance(correspondence, dict):
                    raise ValueError('Supplied sequence correspondence must be a position object')
                label = correspondence.get('label_position', source.get('label_position'))
                if label is not None:
                    output['label_position'] = deepcopy(label)
                supplied = fields & correspondence.keys()
                if supplied:
                    if supplied != fields or not isinstance(correspondence['chain'], str) or not isinstance(correspondence['insertion_code'], str):
                        raise ValueError('Supplied sequence correspondence is incomplete')
                    if correspondence['author_number'] is not None or label is None:
                        output.update({key: correspondence[key] for key in fields})
                obj['positions'].append(output)
        objects.append(obj)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    (runtime.workdir/'manifest.json').write_text(json.dumps({'objects': objects}, allow_nan=False))
    from modules.sequence_io.formats import read_sequences
    read_sequences(SimpleNamespace(entry='manifest.json', open=lambda key: (runtime.workdir/key).open('rb')))
    return Outcome(outputs={'sequences': [Delivery('workbench.sequence', 'manifest.json', {'manifest.json': 'manifest.json'})]})


def module():
    collection = {'collection': InputPort((FORMAT,), name='候选集合')}
    return Module('workbench.collection', '集合操作', ui=str(Path(__file__).with_name('ui.js')),
        nodes=(
            Node('workbench.collection.merge', '合并集合', merge,
                 inputs={'packages': InputPort(FORMATS, cardinality='many', required=False, name='输入')}, outputs={'collection': OutputPort(FORMAT, name='候选集合')}),
            Node('workbench.collection.split', '拆分集合', split,
                 inputs=collection, outputs={'items': OutputPort(FORMAT, cardinality='many', name='对象')}),
            Node('workbench.collection.select', '选择对象', select_items, inputs=collection,
                 outputs={'collection': OutputPort(FORMAT, name='候选集合')}, parameters={'items': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}}}),
            Node('workbench.collection.extract_structures', '提取结构', extract_structures,
                 inputs=collection, outputs={'structures': OutputPort('workbench.structure_set', name='结构')}),
            Node('workbench.collection.extract_sequences', '提取序列', extract_sequences,
                 inputs=collection, outputs={'sequences': OutputPort('workbench.sequence', name='序列')}),
        ))
