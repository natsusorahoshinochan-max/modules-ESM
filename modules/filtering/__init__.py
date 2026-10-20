"""One explicit-input implementation for canvas and temporary filtering."""
from copy import deepcopy
import json
import math
import operator
from pathlib import Path
from shutil import copyfileobj

from protein_workbench_public.module_api import Delivery, InputPort, Interaction, InteractionResult, Module, Node, Outcome, OutputPort
from modules.metric_analysis import FORMATS as METRICS, read_metric_choices
from .formats import SourcePackage, read_collection

FORMAT = 'workbench.filtered_collection'
CANDIDATES = ('workbench.sequence', 'workbench.structure_set', *(format for format in METRICS if format != 'workbench.metric_analysis'), FORMAT)


def _document(package):
    with package.open(package.entry) as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError('Candidate entry must be an object')
    return value


def _require_candidate_files(source, obj):
    required = []
    if 'structure' in obj or source.format in ('workbench.structure_set','workbench.prediction','workbench.structure_confidence'):
        required.append(('structure', obj.get('structure'), True))
    if source.format == 'workbench.proteinmpnn_design':
        required.append(('backbone structure', obj.get('backbone', {}).get('structure'), True))
    if source.format == 'workbench.esm3_generation':
        required.append(('original native generation', obj.get('native'), False))
    for role, descriptor, structural in required:
        key = descriptor.get('file') if isinstance(descriptor, dict) else None
        if not isinstance(key, str) or key not in source.files or (structural and descriptor.get('format') not in ('pdb','mmcif')):
            raise ValueError(f'Candidate requires its complete declared {role} file')
        try:
            with source.open(key) as reader:
                reader.read(1)
        except OSError as error:
            raise ValueError(f'Candidate {role} file is unreadable: {key}') from error


def _candidates(packages):
    result = []
    for index, package in enumerate(packages):
        document = read_collection(package) if package.format == FORMAT else _document(package)
        if package.format == FORMAT:
            objects = [item['object'] for item in document['items']]
        elif package.format == 'workbench.comparison':
            objects = [document['subject']]
        elif package.format == 'workbench.sequence_backbone_evaluation':
            # Each supplied joint evaluation context is one indivisible candidate.
            objects = []
            for evaluation in document.get('evaluations', []):
                ids = evaluation.get('object_ids')
                original = {obj.get('id'):obj for obj in document.get('objects', [])}
                if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(identity not in original for identity in ids):
                    raise ValueError('Joint candidate requires complete explicitly evaluated objects')
                members = [original[identity] for identity in ids]
                joint = {'members': members, 'label': 'Joint sequence context: '+', '.join(obj.get('label', f'Sequence {i+1}') for i,obj in enumerate(members))}
                if joint not in objects:
                    objects.append(joint)
        else:
            objects = document.get('objects')
        if not isinstance(objects, list) or any(not isinstance(obj, dict) or ('members' not in obj and not isinstance(obj.get('id'), str)) for obj in objects):
            raise ValueError('Candidates require explicit complete objects')
        for offset, obj in enumerate(objects):
            source = SourcePackage(package, document['sources'][document['items'][offset]['source']]) if package.format == FORMAT else package
            _require_candidate_files(source, obj)
            result.append({'input': index, 'item': offset, 'object': obj})
    return result


def _identity(obj):
    return ('joint', tuple(member['id'] for member in obj['members'])) if 'members' in obj else ('object', obj['id'])


def _describe_choice(package, choice, index, source=None):
    context = {'input':index, 'format':package.format, 'entry':package.entry}
    if source is not None:
        context['source'] = source
    reference = choice['reference']
    display = None
    access = {'unavailable':'This evaluation has no reference structure'}
    if isinstance(reference, dict):
        descriptor = reference.get('structure', {})
        display = {key:reference[key] for key in ('label','name') if isinstance(reference.get(key), str)}
        display.update({key:descriptor[key] for key in ('file','format') if isinstance(descriptor.get(key), str)})
        try:
            key = descriptor.get('file')
            if descriptor.get('format') not in ('pdb','mmcif') or not isinstance(key, str):
                raise ValueError('Reference has no declared PDB or mmCIF file')
            if package.format == 'workbench.metric_analysis':
                document = _document(package)
                analysis = document['analyses'][choice['selector']['analysis']]
                original = document['sources'][analysis['source']]
                key = original['files'][key]
                context['analysis_source'] = analysis['source']
            if key not in package.files:
                raise ValueError('Reference file is not declared in its actual evaluation source')
            access = {'input':index, 'key':package.file_key(key) if isinstance(package, SourcePackage) else key}
        except (KeyError, IndexError, TypeError, ValueError) as error:
            access = {'unavailable':f'Reference file access unavailable: {error}'}
    return dict(choice, context=context, reference_display=display, reference_access=access)


def _metrics(packages, describe=False):
    result = []
    for index, package in enumerate(packages):
        if package.format == FORMAT:
            document = read_collection(package)
            sources = document['sources']
            chosen = [(i,source) for i,source in enumerate(sources) if source['format'] in METRICS]
            for source_index,source in chosen:
                for choice in read_metric_choices(SourcePackage(package,source)):
                    result.append(dict(_describe_choice(SourcePackage(package,source),choice,index,source_index) if describe else choice, input=index, source=source_index))
        else:
            document = _document(package)
            if document.get('objects') == []:
                continue
            for choice in read_metric_choices(package):
                result.append(dict(_describe_choice(package,choice,index) if describe else choice, input=index))
    return result


def _selection(choice):
    return {key:choice[key] for key in ('input','source','selector') if key in choice}


def _number(candidate, selection, choices):
    if not isinstance(selection, dict):
        raise ValueError('Choose an existing evaluation for every required operation')
    bindings = selection.get('bindings')
    if bindings is not None:
        if not isinstance(bindings, list):
            raise ValueError('Evaluation bindings must be explicit selections')
        bound = [row.get('evaluation') for row in bindings if row.get('candidate') == {k:candidate[k] for k in ('input','item')}]
        if len(bound) != 1:
            raise ValueError('Required evaluation is missing or ambiguous for '+candidate['object'].get('label', 'candidate'))
        exact = bound[0]
        found = [c for c in choices if _selection(c) == exact and _identity(c['object']) == _identity(candidate['object'])]
    else:
        allowed = {'metric','method','reference','region','origin','sample'}
        if set(selection) - allowed or not {'metric','method','reference','region'} <= set(selection):
            raise ValueError('Choose metric, actual method, reference and original region')
        found = [c for c in choices if _identity(c['object']) == _identity(candidate['object']) and c['metric'] == selection['metric']
            and c['source_method'] == selection['method'] and c['reference'] == selection['reference'] and c['source_region'] == selection['region']
            and ('origin' not in selection or c['selector']['origin'] == selection['origin']) and ('sample' not in selection or c.get('sample') == selection['sample'])]
    if len(found) != 1:
        raise ValueError('Required evaluation is missing or ambiguous for '+candidate['object'].get('label', 'candidate'))
    choice = found[0]
    if choice.get('unavailable'):
        raise ValueError(choice['unavailable'])
    values = choice['input_values']
    if choice.get('positions') is not None or len(values) != 1:
        raise ValueError('Choose an existing scalar evaluation; positional values require explicit analysis first')
    return values[0]


def select(call, runtime):
    parameters = call.parameters
    if set(parameters) - {'conditions','sort','limit'}:
        raise ValueError('Unsupported filtering parameter')
    candidates = _candidates(call.inputs.get('candidates', ()))
    conditions = parameters.get('conditions', [])
    if not isinstance(conditions, list):
        raise ValueError('Conditions must be a list')
    sort = parameters.get('sort')
    if sort is not None and (not isinstance(sort, dict) or set(sort) != {'evaluation','direction'} or sort['direction'] not in ('ascending','descending')):
        raise ValueError('Sort requires an evaluation and ascending or descending direction')
    limit = parameters.get('limit')
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError('Quantity limit must be a nonnegative integer')
    operations = {'lt':operator.lt,'le':operator.le,'eq':operator.eq,'ge':operator.ge,'gt':operator.gt}
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {'evaluation','operator','value'} or condition['operator'] not in operations or type(condition['value']) not in (float,int) or not math.isfinite(condition['value']):
            raise ValueError('Condition requires an existing evaluation, comparison and finite original value')
    if not candidates:
        return []
    choices = _metrics(call.inputs.get('evaluations', ())) if conditions or sort is not None else []
    accepted = []
    for candidate in candidates:
        if runtime.cancelled:
            raise ValueError('Filtering cancelled')
        # Resolve all requested values before applying any predicate, including rejected rows.
        values = [_number(candidate, row['evaluation'], choices) for row in conditions]
        order = _number(candidate, sort['evaluation'], choices) if sort else None
        if all(operations[row['operator']](value,row['value']) for row,value in zip(conditions,values)):
            accepted.append((candidate,order))
    if sort:
        accepted.sort(key=lambda item:item[1], reverse=sort['direction']=='descending')
    return [row[0] for row in (accepted if limit is None else accepted[:limit])]


def temporary(call, runtime):
    return InteractionResult(data={'selected':[{key:row[key] for key in ('input','item')} for row in select(call,runtime)]})


def inspect(call, runtime):
    candidates = _candidates(call.inputs.get('candidates', ()))
    choices = _metrics(call.inputs.get('evaluations', ()), describe=True)
    return InteractionResult(data={'candidates':[{'input':c['input'],'item':c['item'],'label':c['object'].get('label',f'Object {i+1}'),
        'choices':[{'evaluation':_selection(m),'metric':m['metric'],'method':m['source_method'],
            'reference':m['reference'],'reference_display':m['reference_display'],'reference_access':m['reference_access'],
            'context':m['context'],'region':m['source_region'],'unit':m.get('unit'),'meaning':m.get('meaning'),
            'sample':m.get('sample'),'unavailable':m.get('unavailable') or ('Positional values require explicit analysis' if m.get('positions') is not None else None)}
            for m in choices if _identity(m['object']) == _identity(c['object'])]} for i,c in enumerate(candidates)]})


def execute(call, runtime):
    selected = select(call,runtime)
    files, sources, locations, copied = {}, [], {}, {}
    # Full original files and manifests remain byte-for-byte intact behind explicit maps.
    for index, package in enumerate((*call.inputs.get('candidates', ()), *call.inputs.get('evaluations', ()))):
        role = 'candidate' if index < len(call.inputs.get('candidates', ())) else 'evaluation'
        if package.id in copied:
            previous = copied[package.id]
            for offset,source_index in previous['locations'].items():
                locations[index,offset] = source_index
            if package.format != FORMAT:
                for source_index in previous['sources']:
                    if role not in sources[source_index]['roles']:
                        sources[source_index]['roles'].append(role)
            continue
        start = len(sources)
        mapping = {}
        for offset, key in enumerate(package.files):
            if runtime.cancelled:
                return Outcome(status='cancelled')
            target = f'sources/{index}/{offset}'
            path = runtime.workdir/target
            path.parent.mkdir(parents=True,exist_ok=True)
            with package.open(key) as reader,path.open('wb') as writer:
                copyfileobj(reader,writer)
            mapping[key] = target
            files[target] = target
        if package.format == FORMAT:
            original = read_collection(package)
            start = len(sources)
            for source in original['sources']:
                sources.append(dict(source, files={key:mapping[value] for key,value in source['files'].items()}))
            for offset,item in enumerate(original['items']):
                locations[index,offset] = start + item['source']
        else:
            if role == 'candidate':
                for row in _candidates((package,)):
                    locations[index,row['item']] = len(sources)
            sources.append({'format':package.format,'entry':package.entry,'files':mapping,'roles':[role]})
        copied[package.id] = {'sources':list(range(start,len(sources))), 'locations':{offset:value for (input_index,offset),value in locations.items() if input_index == index}}
    document = {'sources':sources,'items':[{'source':locations[row['input'],row['item']],'object':deepcopy(row['object'])} for row in selected],
        'selected':[{key:row[key] for key in ('input','item')} for row in selected], 'parameters':deepcopy(call.parameters)}
    (runtime.workdir/'manifest.json').write_text(json.dumps(document,allow_nan=False))
    files['manifest.json']='manifest.json'
    if runtime.cancelled:
        return Outcome(status='cancelled')
    return Outcome(outputs={'collection':[Delivery(FORMAT,'manifest.json',files)]})


def extract_structures(call, runtime):
    package = call.inputs['collection'][0]
    document = read_collection(package)
    from modules.structure_io import parse, atoms
    files, objects = {}, []
    for index, item in enumerate(document['items']):
        obj = deepcopy(item['object'])
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


def module():
    inputs = {'candidates':InputPort(CANDIDATES,cardinality='many',required=False), 'evaluations':InputPort((*METRICS, FORMAT),cardinality='many',required=False)}
    parameters = {'type':'object','properties':{'conditions':{'type':'array'},'sort':{'type':'object'},'limit':{'type':'integer','minimum':0}}}
    return Module('workbench.filtering','Filtering and sorting',ui=str(Path(__file__).with_name('ui.js')),
        nodes=(Node('workbench.filter','Filter and sort',execute,inputs=inputs,outputs={'collection':OutputPort(FORMAT)},parameters=parameters), Node('workbench.filter.extract_structures','Extract selected structures',extract_structures, inputs={'collection':InputPort((FORMAT,))},outputs={'structures':OutputPort('workbench.structure_set')})),
        interactions=(Interaction('workbench.filter',temporary,inputs=inputs,parameters=parameters),Interaction('workbench.filter.inspect',inspect,inputs=inputs)))
