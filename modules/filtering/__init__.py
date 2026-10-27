"""One explicit-input implementation for canvas and temporary filtering."""
import math
import operator
from pathlib import Path

from protein_workbench_public.module_api import InputPort, Interaction, InteractionResult, Module, Node, Outcome, OutputPort
from modules.metric_analysis import FORMATS as METRICS, read_metric_choices
from modules.collection.api import collect
from modules.collection.formats import FORMAT, SourcePackage, read_collection, read_candidates, read_document

CANDIDATES = ('workbench.sequence', 'workbench.structure_set', *(format for format in METRICS if format != 'workbench.metric_analysis'), FORMAT)

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
            selector, seen = choice['selector'], set()
            while package.format == 'workbench.metric_analysis':
                entry = package.file_key(package.entry) if isinstance(package, SourcePackage) else package.entry
                if entry in seen:
                    raise ValueError('Selected analysis source contains a cycle')
                seen.add(entry)
                if not isinstance(selector, dict) or selector.get('origin') != 'analysis' or type(selector.get('analysis')) is not int or selector['analysis'] < 0:
                    raise ValueError('Reference access requires the exact selected analysis record')
                document = read_document(package)
                analysis = document['analyses'][selector['analysis']]
                source_index = analysis['source']
                if type(source_index) is not int or source_index < 0:
                    raise ValueError('Reference access requires an explicit analysis source')
                if 'analysis_source' not in context:
                    context['analysis_source'] = source_index
                package = SourcePackage(package, document['sources'][source_index])
                selector = analysis['selection']
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
            document = read_document(package)
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
        allowed = {'metric','method','reference','reference_mode','region','origin','sample'}
        provided_reference = selection.get('reference_mode') == 'provided_evaluations'
        explicit_reference = 'reference' in selection and 'reference_mode' not in selection
        if (set(selection) - allowed or not {'metric','method','region'} <= set(selection)
                or not (explicit_reference or (provided_reference and 'reference' not in selection))):
            raise ValueError('Choose metric, actual method and original region, and either reference or reference_mode: provided_evaluations')
        found = [c for c in choices if _identity(c['object']) == _identity(candidate['object']) and c['metric'] == selection['metric']
            and c['source_method'] == selection['method'] and (provided_reference or c['reference'] == selection['reference']) and c['source_region'] == selection['region']
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
    candidates = read_candidates(call.inputs.get('candidates', ()))
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
    candidates = read_candidates(call.inputs.get('candidates', ()))
    choices = _metrics(call.inputs.get('evaluations', ()), describe=True)
    return InteractionResult(data={'candidates':[{'input':c['input'],'item':c['item'],'label':c['object'].get('label',f'Object {i+1}'),
        'choices':[{'evaluation':_selection(m),'metric':m['metric'],'method':m['source_method'],
            'reference':m['reference'],'reference_display':m['reference_display'],'reference_access':m['reference_access'],
            'context':m['context'],'region':m['source_region'],'unit':m.get('unit'),'meaning':m.get('meaning'),
            'sample':m.get('sample'),'unavailable':m.get('unavailable') or ('Positional values require explicit analysis' if m.get('positions') is not None else None)}
            for m in choices if _identity(m['object']) == _identity(c['object'])]} for i,c in enumerate(candidates)]})


def execute(call, runtime):
    selected = select(call, runtime)
    try:
        delivery = collect(call.inputs.get('candidates', ()), selected, runtime,
                           evaluations=call.inputs.get('evaluations', ()), parameters=call.parameters)
    except InterruptedError:
        return Outcome(status='cancelled')
    return Outcome(status='cancelled') if runtime.cancelled else Outcome(outputs={'collection': [delivery]})


def module():
    inputs = {'candidates':InputPort(CANDIDATES,cardinality='many',required=False, name={'zh-CN': '候选', 'en': 'Candidate'}), 'evaluations':InputPort((*METRICS, FORMAT),cardinality='many',required=False, name={'zh-CN': '评分', 'en': 'Scores'})}
    parameters = {'type':'object','properties':{'conditions':{'type':'array'},'sort':{'type':'object'},'limit':{'type':'integer','minimum':0}}}
    return Module('workbench.filtering',{'zh-CN': '筛选与排序', 'en': 'Filter and sort'},ui=str(Path(__file__).with_name('ui.js')),
        nodes=(Node('workbench.filter',{'zh-CN': '筛选', 'en': 'Filter'},execute,inputs=inputs,outputs={'collection':OutputPort(FORMAT, name={'zh-CN': '候选集合', 'en': 'Candidates'})},parameters=parameters),),
        interactions=(Interaction('workbench.filter',temporary,inputs=inputs,parameters=parameters),Interaction('workbench.filter.inspect',inspect,inputs=inputs)))
